"""
Fair-System 通知 API
查询成员的待打分模块列表，为待办页面提供数据。
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import CurrentMemberContext, get_current_member_context, get_db
from app.api.project_access import require_business_member

router = APIRouter(prefix="/notifications", tags=["通知"])


def _build_pending_assessments(member_id: int, db: Session):
    """
    **查询某成员的待打分模块列表**：
    1. 查找该成员参与的所有项目
    2. 筛选出处于评分期内的项目
    3. 获取这些项目下的所有模块
    4. 排除该成员已经打过分的模块
    5. 返回待打分模块列表 + 剩余时间 + 是否紧急
    """
    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if not member:
        return {"pending": [], "total_pending": 0, "total_expired": 0, "pending_project_count": 0}

    now = datetime.now()
    pending_list = []

    # 查找成员参与的所有项目
    projects = db.query(models.Project).filter(
        models.Project.members.any(models.Member.id == member_id)
    ).all()

    for project in projects:
        raw_start = getattr(project, "assessment_start", None)
        raw_end = getattr(project, "assessment_end", None)
        a_start = raw_start if isinstance(raw_start, datetime) else None
        a_end = raw_end if isinstance(raw_end, datetime) else None

        # 必须已设置评分期
        if a_start is None or a_end is None:
            continue

        # 判断评分期状态
        if now < a_start:
            # 还没开始
            continue

        is_expired = now > a_end

        # 获取项目下所有待评分模块
        modules = db.query(models.Module).filter(
            models.Module.project_id == project.id,
            models.Module.status == "待分配"
        ).all()

        # 获取该成员已打过分的模块 ID
        assessed_module_ids = set(
            row[0] for row in db.query(models.ModuleAssessment.module_id).filter(
                models.ModuleAssessment.member_id == member_id,
                models.ModuleAssessment.module_id.in_([m.id for m in modules])
            ).all()
        ) if modules else set()

        for module in modules:
            if module.id in assessed_module_ids:
                continue  # 已打过分，跳过

            remaining_seconds = (a_end - now).total_seconds() if is_expired is False else 0
            remaining_hours = max(0, remaining_seconds / 3600)
            is_urgent = 0 < remaining_hours < 24

            pending_list.append({
                "project_id": project.id,
                "project_name": project.name,
                "module_id": module.id,
                "module_name": module.name,
                "module_description": module.description or "",
                "assessment_end": a_end.isoformat(),
                "remaining_hours": round(remaining_hours, 1),
                "is_urgent": is_urgent,
                "is_expired": is_expired,
            })

    # 按紧急程度排序：已过期排最后(灰色)，紧急排最前(红色)
    pending_list.sort(key=lambda x: (x["is_expired"], not x["is_urgent"], x["remaining_hours"]))

    pending_project_ids = {
        item["project_id"]
        for item in pending_list
        if item["is_expired"] is False
    }

    return {
        "member_id": member_id,
        "pending": pending_list,
        "total_pending": len([p for p in pending_list if not p["is_expired"]]),
        "total_expired": len([p for p in pending_list if p["is_expired"]]),
        "pending_project_count": len(pending_project_ids),
    }


def get_pending_assessments_for_member(member_id: int, db: Session):
    return _build_pending_assessments(member_id, db)


@router.get("/pending-assessments")
def get_pending_assessments(
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    member = require_business_member(context, "请选择当前业务身份后再查看待办。")
    return _build_pending_assessments(member.id, db)


@router.get("/pending-assessments/{member_id}")
def get_pending_assessments_by_member_id(
    member_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    member = require_business_member(context, "请选择当前业务身份后再查看待办。")
    if member.id != member_id:
        raise HTTPException(status_code=403, detail="禁止读取其他成员的待评分列表。")
    return _build_pending_assessments(member.id, db)
