"""
Fair-System 评估 API 路由
处理成员对分配到的模块进行难度、时间等维度的主观打分评估。
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List

from app import models, schemas
from app.api.dependencies import CurrentMemberContext, get_current_member_context, get_db
from app.api.project_access import require_business_member

router = APIRouter(prefix="/assessments", tags=["模块评估"])


class AssessmentSubmitPayload(BaseModel):
    module_id: int
    dimension_scores: List[schemas.DimensionScoreCreate] = Field(default_factory=list)


@router.post("/", response_model=schemas.ModuleAssessment)
def create_assessment(
    assessment: AssessmentSubmitPayload,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    """
    **业务逻辑说明**：
    成员对某个未完成的模块进行“评估”。提交打分、预估工时等。
    1. 检查模块存不存在？
    2. 从当前会话识别评分成员
    3. 检查这个成员是不是该模块所属项目的组员？
    4. 检查这个成员有没有**重复打分**？每个人对每个模块只能评一次！
    """
    # 步骤 1: 模块在不在？
    module = db.query(models.Module).filter(models.Module.id == assessment.module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="想打分的模块不存在！")

    # 步骤 2: 成员必须来自当前会话业务身份
    if isinstance(context, CurrentMemberContext):
        member = require_business_member(context, "请选择当前业务身份后再评分。")
    else:
        # 兼容直接调用该函数的单元测试：允许显式传 member_id 进行非 HTTP 场景验证
        legacy_member_id = getattr(assessment, "member_id", None)
        if legacy_member_id is None:
            raise HTTPException(status_code=401, detail="请先登录后再评分。")
        member = db.query(models.Member).filter(models.Member.id == legacy_member_id).first()
        if not member:
            raise HTTPException(status_code=404, detail="提交评估的成员不存在！")

    # 步骤 3: 必须是该项目的组员才能评分
    project = db.query(models.Project).filter(models.Project.id == module.project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="模块所属项目不存在！")

    if member not in project.members:
        raise HTTPException(status_code=403, detail="你不是该项目的组员，无权评分")

    # 步骤 3.5: 校验项目评分开放时间
    assessment_start = getattr(project, "assessment_start", None)
    assessment_end = getattr(project, "assessment_end", None)
    if assessment_start is None or assessment_end is None:
        raise HTTPException(status_code=400, detail="PM 尚未开放评分")

    now = datetime.now()
    if now < assessment_start:
        raise HTTPException(status_code=400, detail="评分尚未开始")
    if now > assessment_end:
        raise HTTPException(status_code=400, detail="评分已截止，你已丧失打分资格")
         
    # 步骤 4: 检查是否已经填过了？
    # [新手注意]：filter() 里面可以写多个条件！用逗号隔开代表“并且(AND)” 
    existing = db.query(models.ModuleAssessment).filter(
        models.ModuleAssessment.member_id == member.id,
        models.ModuleAssessment.module_id == assessment.module_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="你已经评估过这个模块啦，不能重复刷票！")

    project_dimensions = db.query(models.ScoringDimension).filter(
        models.ScoringDimension.project_id == project.id
    ).order_by(models.ScoringDimension.sort_order.asc(), models.ScoringDimension.id.asc()).all()
    if not project_dimensions:
        raise HTTPException(status_code=400, detail="当前项目尚未配置评分维度")

    project_dimension_ids = {dimension.id for dimension in project_dimensions}
    provided_dimension_ids = [item.dimension_id for item in assessment.dimension_scores]
    if any(dimension_id not in project_dimension_ids for dimension_id in provided_dimension_ids):
        raise HTTPException(status_code=400, detail="存在不属于当前项目的评分维度")
    if len(set(provided_dimension_ids)) != len(provided_dimension_ids):
        raise HTTPException(status_code=400, detail="评分维度不能重复提交")
    if set(provided_dimension_ids) != project_dimension_ids:
        raise HTTPException(status_code=400, detail="必须为项目的每个评分维度提交一次分数")
         
    # 如果一切正常，创建评估数据
    new_assessment = models.ModuleAssessment(
        member_id=member.id,               # 谁打的分？服务端注入
        module_id=assessment.module_id,    # 哪个模块？前端传
    )
    
    db.add(new_assessment)
    db.flush()

    for item in assessment.dimension_scores:
        db.add(models.DimensionScore(
            assessment_id=new_assessment.id,
            dimension_id=item.dimension_id,
            score=float(item.score),
        ))

    db.commit()
    db.refresh(new_assessment)
    
    return new_assessment

@router.get("/module/{module_id}", response_model=List[schemas.ModuleAssessment])
def read_module_assessments(module_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    用来在前端显示：这个模块目前有哪些人提交了评估。
    """
    assessments = db.query(models.ModuleAssessment).filter(
        models.ModuleAssessment.module_id == module_id
    ).all()
    return assessments
