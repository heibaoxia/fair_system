"""
Fair-System 综合分计算 API
负责汇总评分数据、计算加权综合分、追踪评分完成度。
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app import models
from app.api.dependencies import get_db

router = APIRouter(prefix="/scoring", tags=["综合分计算"])


def _calc_module_summary(module: models.Module, project: models.Project, db: Session) -> dict:
    """
    内部工具函数：计算单个模块的综合分。
    只统计已实际提交的有效评分。
    """
    assessments = db.query(models.ModuleAssessment).filter(
        models.ModuleAssessment.module_id == module.id
    ).all()

    if not assessments:
        empty_weight_difficulty = float(getattr(project, "weight_difficulty", 0.25) or 0.25)
        empty_weight_hours = float(getattr(project, "weight_hours", 0.25) or 0.25)
        empty_weight_boredom = float(getattr(project, "weight_boredom", 0.25) or 0.25)
        empty_weight_intensity = float(getattr(project, "weight_intensity", 0.25) or 0.25)
        return {
            "module_id": module.id,
            "module_name": module.name,
            "assessment_count": 0,
            "avg_difficulty": 0,
            "avg_estimated_hours": 0,
            "avg_boredom": 0,
            "avg_intensity": 0,
            "composite_score": 0,
            "weights_used": {
                "difficulty": empty_weight_difficulty,
                "hours": empty_weight_hours,
                "boredom": empty_weight_boredom,
                "intensity": empty_weight_intensity,
            },
            "breakdown": {
                "difficulty_component": 0,
                "hours_component": 0,
                "boredom_component": 0,
                "intensity_component": 0,
            }
        }

    weight_difficulty = float(getattr(project, "weight_difficulty", 0.25) or 0.25)
    weight_hours = float(getattr(project, "weight_hours", 0.25) or 0.25)
    weight_boredom = float(getattr(project, "weight_boredom", 0.25) or 0.25)
    weight_intensity = float(getattr(project, "weight_intensity", 0.25) or 0.25)

    count = len(assessments)
    avg_d = sum(int(getattr(a, "difficulty_score", 0) or 0) for a in assessments) / count
    avg_h = sum(float(getattr(a, "estimated_hours", 0.0) or 0.0) for a in assessments) / count
    avg_b = sum(int(getattr(a, "boredom_score", 0) or 0) for a in assessments) / count
    avg_i = sum(int(getattr(a, "intensity_score", 0) or 0) for a in assessments) / count

    # 加权综合分
    d_comp = avg_d * weight_difficulty
    h_comp = avg_h * weight_hours
    b_comp = avg_b * weight_boredom
    i_comp = avg_i * weight_intensity
    composite = d_comp + h_comp + b_comp + i_comp

    return {
        "module_id": module.id,
        "module_name": module.name,
        "assessment_count": count,
        "avg_difficulty": round(float(avg_d), 2),
        "avg_estimated_hours": round(float(avg_h), 2),
        "avg_boredom": round(float(avg_b), 2),
        "avg_intensity": round(float(avg_i), 2),
        "composite_score": round(float(composite), 2),
        "weights_used": {
            "difficulty": weight_difficulty,
            "hours": weight_hours,
            "boredom": weight_boredom,
            "intensity": weight_intensity,
        },
        "breakdown": {
            "difficulty_component": round(float(d_comp), 4),
            "hours_component": round(float(h_comp), 4),
            "boredom_component": round(float(b_comp), 4),
            "intensity_component": round(float(i_comp), 4),
        }
    }


def build_project_summary_payload(project: models.Project, modules: List[models.Module], db: Session) -> dict:
    module_summaries = [_calc_module_summary(module, project, db) for module in modules]
    effective_modules = [item for item in module_summaries if item["assessment_count"] > 0]
    is_summarized = len(effective_modules) > 0

    project_composite_score = 0.0
    project_estimated_hours = 0.0
    if is_summarized:
        project_composite_score = sum(item["composite_score"] for item in effective_modules) / len(effective_modules)
        project_estimated_hours = sum(item["avg_estimated_hours"] for item in effective_modules)

    return {
        "project_id": project.id,
        "project_name": project.name,
        "weights": {
            "difficulty": float(getattr(project, "weight_difficulty", 0.25) or 0.25),
            "hours": float(getattr(project, "weight_hours", 0.25) or 0.25),
            "boredom": float(getattr(project, "weight_boredom", 0.25) or 0.25),
            "intensity": float(getattr(project, "weight_intensity", 0.25) or 0.25),
        },
        "is_summarized": is_summarized,
        "project_composite_score": round(float(project_composite_score), 2),
        "project_estimated_hours": round(float(project_estimated_hours), 2),
        "modules": module_summaries,
    }


@router.get("/module/{module_id}/summary")
def get_module_summary(module_id: int, db: Session = Depends(get_db)):
    """
    **单模块综合分**：
    从模块所属项目中读取权重，汇总所有已提交的评分，计算加权综合分。
    """
    module = db.query(models.Module).filter(models.Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="模块不存在")

    project = db.query(models.Project).filter(models.Project.id == module.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="模块所属项目不存在")

    return _calc_module_summary(module, project, db)


@router.get("/project/{project_id}/summary")
def get_project_summary(project_id: int, db: Session = Depends(get_db)):
    """
    **项目所有模块综合分**：
    批量返回项目下所有模块的综合分计算结果。
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    modules = db.query(models.Module).filter(models.Module.project_id == project_id).all()
    return build_project_summary_payload(project, modules, db)


@router.get("/project/{project_id}/progress")
def get_assessment_progress(project_id: int, db: Session = Depends(get_db)):
    """
    **评分完成度追踪**（T5）：
    返回每个成员的打分进度。
    逾期未打分的成员标记为"已失效"。
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    members = project.members
    modules = db.query(models.Module).filter(models.Module.project_id == project_id).all()
    total_modules = len(modules)
    module_ids = [module.id for module in modules]

    now = datetime.now()
    is_expired = False
    assessment_end = getattr(project, "assessment_end", None)
    if isinstance(assessment_end, datetime) and now > assessment_end:
        is_expired = True

    assessments = []
    if module_ids:
        assessments = db.query(models.ModuleAssessment).filter(
            models.ModuleAssessment.module_id.in_(module_ids)
        ).all()

    completed_modules_by_member = {}
    for assessment in assessments:
        member_module_ids = completed_modules_by_member.setdefault(assessment.member_id, set())
        member_module_ids.add(assessment.module_id)

    members_progress = []
    all_effective_done = True

    for member in members:
        completed = len(completed_modules_by_member.get(member.id, set()))

        is_done = completed >= total_modules

        if is_expired and not is_done:
            status = "已失效"
        elif is_done:
            status = "已完成"
        else:
            status = "进行中"
            all_effective_done = False

        members_progress.append({
            "member_id": member.id,
            "name": member.name,
            "completed": completed,
            "total": total_modules,
            "status": status,
        })

    # effective_completion: 所有还有资格打分的人都已提交完毕
    effective_completion = all_effective_done or (
        is_expired and all(p["status"] in ("已完成", "已失效") for p in members_progress)
    )

    assessment_start = getattr(project, "assessment_start", None)

    start_value = assessment_start.isoformat() if isinstance(assessment_start, datetime) else None
    end_value = assessment_end.isoformat() if isinstance(assessment_end, datetime) else None

    return {
        "total_modules": total_modules,
        "assessment_period": {
            "start": start_value,
            "end": end_value,
        },
        "is_expired": is_expired,
        "members_progress": members_progress,
        "all_done": all(p["status"] == "已完成" for p in members_progress),
        "effective_completion": effective_completion,
    }


@router.post("/project/{project_id}/auto-summarize")
def auto_summarize(project_id: int, db: Session = Depends(get_db)):
    """
    **自动汇总触发**：
    检查是否所有有效成员已打完所有模块。
    如果全部完成，计算并返回所有模块的综合分。
    如果尚未全部完成，返回当前进度信息。
    """
    progress = get_assessment_progress(project_id, db)

    if not progress["effective_completion"]:
        return {
            "summarized": False,
            "message": "尚有成员未完成打分",
            "progress": progress,
        }

    # 全部完成，计算汇总
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    modules = db.query(models.Module).filter(models.Module.project_id == project_id).all()

    project_summary = build_project_summary_payload(project, modules, db)

    return {
        "summarized": True,
        "message": "所有有效评分已汇总完毕",
        "modules": project_summary["modules"],
        "project_summary": project_summary,
        "progress": progress,
    }
