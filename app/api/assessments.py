"""
Fair-System 评估 API 路由
处理成员对分配到的模块进行难度、时间等维度的主观打分评估。
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app import models, schemas
from app.api.dependencies import get_db

router = APIRouter(prefix="/assessments", tags=["模块评估"])

@router.post("/", response_model=schemas.ModuleAssessment)
def create_assessment(assessment: schemas.AssessmentCreate, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    成员对某个未完成的模块进行“评估”。提交打分、预估工时等。
    1. 检查模块存不存在？
    2. 检查成员存不存在？
    3. 检查这个成员是不是该模块所属项目的组员？
    4. 检查这个成员有没有**重复打分**？每个人对每个模块只能评一次！
    """
    # 步骤 1: 模块在不在？
    module = db.query(models.Module).filter(models.Module.id == assessment.module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="想打分的模块不存在！")

    # 步骤 2: 成员在不在？
    member = db.query(models.Member).filter(models.Member.id == assessment.member_id).first()
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
        models.ModuleAssessment.member_id == assessment.member_id,
        models.ModuleAssessment.module_id == assessment.module_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="你已经评估过这个模块啦，不能重复刷票！")
        
    # 如果一切正常，创建评估数据
    new_assessment = models.ModuleAssessment(
        member_id=assessment.member_id,               # 谁打的分？前端传
        module_id=assessment.module_id,               # 哪个模块？前端传
        difficulty_score=assessment.difficulty_score, # 后面是四个分数
        estimated_hours=assessment.estimated_hours,
        boredom_score=assessment.boredom_score,
        intensity_score=assessment.intensity_score
    )
    
    db.add(new_assessment)
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
