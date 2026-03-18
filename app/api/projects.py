"""
【新手必看指北：项目管理 API 路由】
这个文件专门处理针对“Project(项目)”的相关请求。
包括创建项目、查询项目、以及查询某个项目下的所有模块等。
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app import models, schemas
from app.api.dependencies import get_db
from app.api.scoring import _calc_module_summary

router = APIRouter(prefix="/projects", tags=["项目管理"])


def _ensure_project_manager_or_god(project: models.Project, current_member_id: int, detail: str) -> None:
    if current_member_id == 0:
        return
    if getattr(project, "created_by", None) != current_member_id:
        raise HTTPException(status_code=403, detail=detail)


def _resolve_scoring_dimensions(project_payload: schemas.ProjectCreate) -> List[dict]:
    requested_dimensions = project_payload.scoring_dimensions
    if not requested_dimensions:
        raise HTTPException(status_code=400, detail="至少需要设置一个评分维度")

    total_weight = sum(float(item.weight) for item in requested_dimensions)
    if abs(total_weight - 1.0) > 0.01:
        raise HTTPException(status_code=400, detail=f"评分维度权重之和必须为 1.0，当前为 {total_weight:.4f}")

    normalized_dimensions = []
    used_names = set()
    for item in requested_dimensions:
        name = (item.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="评分维度名称不能为空")
        if name in used_names:
            raise HTTPException(status_code=400, detail=f"评分维度名称不能重复：{name}")
        used_names.add(name)
        normalized_dimensions.append({"name": name, "weight": float(item.weight)})
    return normalized_dimensions

@router.post("/", response_model=schemas.Project)
def create_project(project: schemas.ProjectCreate, created_by_member_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    项目的创建。我们需要记录是谁创建了这个项目（所以需要 created_by_member_id）。
    如果 JSON 里还伴随传来了 new_modules 列表，我们会在这里把模块也一并存入数据库！
    """
    # 1. 验证这个创建者是否存在
    creator = db.query(models.Member).filter(models.Member.id == created_by_member_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="创建该项目的成员ID不存在！")
        
    scoring_dimensions = _resolve_scoring_dimensions(project)

    # 2. 创建主项目数据
    # 这里用 dict 提取 name 和 description
    db_project = models.Project(
        name=project.name, 
        description=project.description, 
        created_by=created_by_member_id,
    )
    db.add(db_project)
    
    # [新增] 自动将创建者本人加入项目组成员列表中
    db_project.members.append(creator)
    
    db.commit()      # 提交！现在数据库里有了这个项目，哪怕模块还没建
    db.refresh(db_project) # 刷新！立刻拿到它生成的 project_id

    for index, item in enumerate(scoring_dimensions):
        db.add(models.ScoringDimension(
            project_id=db_project.id,
            name=item["name"],
            weight=item["weight"],
            sort_order=index,
        ))
    db.commit()
    db.refresh(db_project)
    
    # 3. 如果伴随着创建项目，还提交了多个"子任务(模块)"
    # 我们用一个列表保存新建出来的模块对象，方便等下拿它们的真实 ID 连线
    created_modules = []
    if project.new_modules:
        for mod in project.new_modules:
            new_mod = models.Module(
                name=mod.name,
                description=mod.description,
                estimated_hours=mod.estimated_hours,
                allowed_file_types=mod.allowed_file_types,
                project_id=db_project.id # 把刚才生成的项目ID跟这些子模块绑定
            )
            db.add(new_mod)
            created_modules.append(new_mod)
        db.commit() # 将所有模块一次性批量保存
        
        # 刷新每一个模块，拿到他们真实的数据库 ID
        for mod in created_modules:
            db.refresh(mod)
            
        db.refresh(db_project) # 再次刷新项目，此时它的关联属性中就会出现这些模块了！
        
        # 4. 如果前端连带着传了依赖关系 (也就是他们谁先谁后)，连线上！
        if project.dependencies:
            for dep in project.dependencies:
                # 前端传给我们的是数组索引：比如 preceding: 0, dependent: 1
                try:
                    pre_idx = dep.get("preceding")
                    dep_idx = dep.get("dependent")
                    if pre_idx is not None and dep_idx is not None:
                        real_pre_id = created_modules[pre_idx].id
                        real_dep_id = created_modules[dep_idx].id
                        
                        new_dependency = models.FileDependency(
                            preceding_module_id=real_pre_id,
                            dependent_module_id=real_dep_id
                        )
                        db.add(new_dependency)
                except IndexError:
                    pass # 如果前端传的索引越界了，那就不建这条线
            db.commit()

    db.refresh(db_project)
    return db_project

@router.get("/", response_model=List[schemas.Project])
def read_projects(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    前端展示所有的项目列表，类似于首页的瀑布流。
    """
    projects = db.query(models.Project).offset(skip).limit(limit).all()
    # Pydantic 响应模型里的 modules = [] 会自动发挥作用，
    # 借助我们写在 models.py 里的魔法关联关系 `modules = relationship(...)`，
    # 它会自动找到每一个项目下的所有模块，一起打包发给前端！
    return projects

@router.get("/{project_id}", response_model=schemas.Project)
def read_project(project_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    查询特定一个项目的详细情况，包括它旗下的所有模块进度。
    """
    proj = db.query(models.Project).filter(models.Project.id == project_id).first()
    if proj is None:
        raise HTTPException(status_code=404, detail="哎呀，没找到这个项目！")
    return proj


@router.get("/{project_id}/completion-status")
def get_project_completion_status(project_id: int, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="未找到该项目")

    modules = db.query(models.Module).filter(models.Module.project_id == project_id).all()
    total_modules = len(modules)
    completed_modules = sum(1 for module in modules if getattr(module, "status", None) == "已完成")
    pending_modules = total_modules - completed_modules
    completion_percentage = round((completed_modules / total_modules) * 100, 1) if total_modules else 0.0

    return {
        "total_modules": total_modules,
        "completed_modules": completed_modules,
        "pending_modules": pending_modules,
        "completion_percentage": completion_percentage,
        "is_all_done": pending_modules == 0,
    }


@router.post("/{project_id}/settle")
def settle_project(project_id: int, current_member_id: int, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="未找到该项目")

    _ensure_project_manager_or_god(project, current_member_id, "只有项目创建者才能结算项目")

    project_status = getattr(project, "status", None)
    if project_status == "已完成":
        raise HTTPException(status_code=400, detail="该项目已完成结算")

    modules = db.query(models.Module).filter(models.Module.project_id == project_id).all()
    is_all_done = all(getattr(module, "status", None) == "已完成" for module in modules)
    if not is_all_done:
        raise HTTPException(status_code=400, detail="还有模块未完成，暂时不能结算")

    member_score_totals = {}
    for module in modules:
        member_id = getattr(module, "assigned_to", None)
        if member_id is None:
            continue
        summary = _calc_module_summary(module, project, db)
        member_score_totals[member_id] = member_score_totals.get(member_id, 0.0) + float(summary.get("composite_score", 0.0) or 0.0)

    total_score = sum(member_score_totals.values())
    if total_score <= 0:
        raise HTTPException(status_code=400, detail="缺少可用于结算的综合分数据")

    total_revenue = float(getattr(project, "total_revenue", 0.0) or 0.0)

    settlements = []
    for member_id, score_total in member_score_totals.items():
        member = db.query(models.Member).filter(models.Member.id == member_id).first()
        if member is None:
            continue

        share_ratio = score_total / total_score
        settlement_amount = round(share_ratio * total_revenue, 2)
        setattr(member, "total_earnings", float(getattr(member, "total_earnings", 0.0) or 0.0) + settlement_amount)

        settlements.append({
            "member_id": member.id,
            "member_name": member.name,
            "composite_score_total": round(score_total, 2),
            "share_ratio": round(share_ratio, 6),
            "settlement_amount": settlement_amount,
        })

    setattr(project, "status", "已完成")
    db.commit()

    return {
        "project_id": project.id,
        "project_name": project.name,
        "project_status": project.status,
        "total_revenue": total_revenue,
        "total_composite_score": round(total_score, 2),
        "settlements": settlements,
    }


@router.put("/{project_id}/assessment-period", response_model=schemas.Project)
def set_assessment_period(project_id: int, period: schemas.AssessmentPeriodSet, current_member_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    由 PM 为项目设置评分开放时间窗口。
    只有在这个时间段内，项目组成员才允许提交模块评估。
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="未找到该项目")

    _ensure_project_manager_or_god(project, current_member_id, "只有项目创建者才能修改评分期")

    now = datetime.now()
    max_duration_hours = 168

    if period.start_mode not in {"immediate", "scheduled"}:
        raise HTTPException(status_code=400, detail="开始方式不合法")

    if period.duration_hours <= 0:
        raise HTTPException(status_code=400, detail="评分期时长必须大于 0")

    if period.duration_hours > max_duration_hours:
        raise HTTPException(status_code=400, detail=f"评分期时长不能超过 {max_duration_hours} 小时")

    if period.start_mode == "scheduled":
        if period.start_at is None:
            raise HTTPException(status_code=400, detail="定时开始时间必须晚于当前时间")
        if period.start_at <= now:
            raise HTTPException(status_code=400, detail="定时开始时间必须晚于当前时间")
        assessment_start = period.start_at
    else:
        assessment_start = datetime.now()

    assessment_end = assessment_start + timedelta(hours=period.duration_hours)

    if assessment_end <= assessment_start:
        raise HTTPException(status_code=400, detail="评分截止时间必须晚于开始时间")

    if assessment_end <= datetime.now():
        raise HTTPException(status_code=400, detail="评分截止时间必须晚于当前时间")

    setattr(project, "assessment_start", assessment_start)
    setattr(project, "assessment_end", assessment_end)
    db.commit()
    db.refresh(project)
    return project
@router.get("/my/{member_id}")
def get_my_projects(member_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    返回所有与当前 member_id 有关的项目。
    只要你建了这个项目（manager），或者这个项目里有模块被分配给了你、或者等着你打分，它都属于“你的”。
    """
    # 获取所有的项目
    all_proj = db.query(models.Project).all()
    my_projs = []
    
    for p in all_proj:
        # 如果我是经理，这个项目肯定是我的
        if getattr(p, "created_by", None) == member_id: # models 里我们退改保留了 created_by
            my_projs.append(p)
            continue
            
        # 否则去该项目的模块里找找有没有我的事情
        involved = False
        for mod in p.modules:
            if mod.assigned_to == member_id:
                involved = True
                break
            # 看看有没有我打过的分 (或者未来看看有没有需要我打分的)
            for a in mod.assessments:
                if a.member_id == member_id:
                    involved = True
                    break
        if involved:
            my_projs.append(p)
            
    # （这里可以对过滤后的 my_projs 转换为 Pydantic Schema，为了简单测试，我们先利用 dict 解析。因为 Project 关联属性多，建议用序列化方式）
    result = []
    for p in my_projs:
        result.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "status": p.status,
            "is_manager": p.created_by == member_id,
            "total_revenue": p.total_revenue
        })
    return result

@router.post("/{project_id}/modules", response_model=schemas.Module)
def create_module_for_project(project_id: int, module: schemas.ModuleCreate, current_member_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    在已有项目中新增独立模块
    """
    proj = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="未找到该项目")

    _ensure_project_manager_or_god(proj, current_member_id, "只有项目创建者才能添加模块")
    
    new_mod = models.Module(
        name=module.name,
        description=module.description,
        estimated_hours=module.estimated_hours,
        allowed_file_types=module.allowed_file_types,
        project_id=project_id,
        status="待分配"
    )
    db.add(new_mod)
    db.commit()
    db.refresh(new_mod)
    return new_mod


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, current_member_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    删除整个项目及其所有关联数据。
    项目创建者或上帝视角（member_id = 0）可以执行删除。
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    _ensure_project_manager_or_god(project, current_member_id, "只有项目创建者或上帝视角才能删除项目")

    module_ids = [module.id for module in db.query(models.Module).filter(models.Module.project_id == project_id).all()]

    if module_ids:
        assessment_ids = [assessment.id for assessment in db.query(models.ModuleAssessment.id).filter(
            models.ModuleAssessment.module_id.in_(module_ids)
        ).all()]
        if assessment_ids:
            db.query(models.DimensionScore).filter(
                models.DimensionScore.assessment_id.in_(assessment_ids)
            ).delete(synchronize_session=False)
        db.query(models.FileDependency).filter(
            (models.FileDependency.preceding_module_id.in_(module_ids))
            | (models.FileDependency.dependent_module_id.in_(module_ids))
        ).delete(synchronize_session=False)
        db.query(models.ModuleAssessment).filter(
            models.ModuleAssessment.module_id.in_(module_ids)
        ).delete(synchronize_session=False)
        db.query(models.ModuleFile).filter(
            models.ModuleFile.module_id.in_(module_ids)
        ).delete(synchronize_session=False)
        db.query(models.Module).filter(
            models.Module.id.in_(module_ids)
        ).delete(synchronize_session=False)

    db.query(models.ScoringDimension).filter(
        models.ScoringDimension.project_id == project_id
    ).delete(synchronize_session=False)

    project.members.clear()
    db.delete(project)
    db.commit()
@router.post("/{project_id}/members/{member_id}")
def add_member_to_project(project_id: int, member_id: int, current_member_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    将一名成员拉入项目组。这会在 project_members 关联表里增加一条记录。
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    
    if project is None or member is None:
        raise HTTPException(status_code=404, detail="项目或成员不存在")

    _ensure_project_manager_or_god(project, current_member_id, "只有项目创建者才能添加项目成员")
    
    if member in project.members:
        return {"message": "成员已经在项目组中啦"}
    
    project.members.append(member)
    db.commit()
    return {"message": f"成功将 {member.name} 加入项目"}
@router.delete("/{project_id}/members/{member_id}")
def remove_member_from_project(project_id: int, member_id: int, current_member_id: int, db: Session = Depends(get_db)):
    """
    **业务逻辑说明**：
    将一名成员移除出项目组。
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    
    if project is None or member is None:
        raise HTTPException(status_code=404, detail="项目或成员不存在")

    _ensure_project_manager_or_god(project, current_member_id, "只有项目创建者才能移除项目成员")

    if member_id == getattr(project, "created_by", None):
        raise HTTPException(status_code=400, detail="不能移除项目创建者本人")
    
    if member in project.members:
        project.members.remove(member)
        db.commit()
        return {"message": f"已将 {member.name} 从项目中移除"}
    
    return {"message": "该成员本来就不在项目组中"}
