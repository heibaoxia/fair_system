"""
分配核心 API。
提供拖拽直分和公平批量分配能力。
"""

from datetime import datetime
from typing import Dict, List, cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_db
from app.api.scoring import _calc_module_summary, get_assessment_progress
from app.schemas_assignment import BatchAssignmentConfirmRequest, BatchAssignmentResult, MemberLoad
from app.services.fair_assignment import FairBatchAssignmentRule
from app.utils.dependency_checker import check_module_unlocked
from app.utils.load_tracker import get_member_30day_load

router = APIRouter(prefix="/assignments", tags=["智能分配"])


def _get_project_or_404(project_id: int, db: Session) -> models.Project:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _ensure_project_manager(project: models.Project, current_member_id: int, detail: str) -> None:
    if getattr(project, "created_by", None) != current_member_id:
        raise HTTPException(status_code=403, detail=detail)


def _build_batch_preview(project: models.Project, modules: List[models.Module], members: List[models.Member], db: Session) -> BatchAssignmentResult:
    member_ids = {member: cast(int, getattr(member, "id", 0)) for member in members}
    member_loads = {
        member_ids[member]: float(get_member_30day_load(member_ids[member], db))
        for member in members
    }
    module_summaries = [_calc_module_summary(module, project, db) for module in modules]

    rule = FairBatchAssignmentRule()
    rule_result = rule.assign(module_summaries, members, member_loads)
    assignments = rule_result["assignments"]
    total_loads = rule_result["member_total_loads"]
    summary_by_module_id = {int(item["module_id"]): item for item in module_summaries}

    result_rows = []
    for member in members:
        member_id = member_ids[member]
        assigned_module_ids = list(assignments.get(member_id, []))
        new_assigned_score = round(
            sum(float(summary_by_module_id[module_id]["composite_score"] or 0.0) for module_id in assigned_module_ids),
            2,
        )
        result_rows.append(
            MemberLoad(
                member_id=member_id,
                member_name=str(getattr(member, "name", f"成员 #{member_id}")),
                existing_30day_score=round(float(member_loads.get(member_id, 0.0) or 0.0), 2),
                new_assigned_score=new_assigned_score,
                total_30day_score=round(float(total_loads.get(member_id, 0.0) or 0.0), 2),
                assigned_modules=assigned_module_ids,
            )
        )

    return BatchAssignmentResult(
        member_loads=result_rows,
        fairness_index=float(rule_result.get("fairness_index", 0.0) or 0.0),
    )


@router.post("/batch/{project_id}", response_model=BatchAssignmentResult)
def preview_batch_assignment(project_id: int, db: Session = Depends(get_db)):
    project = _get_project_or_404(project_id, db)

    progress = get_assessment_progress(project_id, db)
    if not progress["effective_completion"]:
        raise HTTPException(status_code=400, detail="评分尚未完成，暂不能进行批量分配")

    modules = db.query(models.Module).filter(
        models.Module.project_id == project_id,
        models.Module.status == "待分配",
    ).all()
    if not modules:
        raise HTTPException(status_code=400, detail="没有待分配的模块")

    members = list(project.members)
    if not members:
        raise HTTPException(status_code=400, detail="项目组还没有成员")

    return _build_batch_preview(project, modules, members, db)


@router.post("/batch/{project_id}/confirm")
def confirm_batch_assignment(
    project_id: int,
    payload: BatchAssignmentConfirmRequest,
    current_member_id: int,
    db: Session = Depends(get_db),
):
    project = _get_project_or_404(project_id, db)
    _ensure_project_manager(project, current_member_id, "只有项目创建者才能确认批量分配")

    pending_modules = db.query(models.Module).filter(
        models.Module.project_id == project_id,
        models.Module.status == "待分配",
    ).all()
    if not pending_modules:
        raise HTTPException(status_code=400, detail="没有待分配的模块")

    pending_module_map = {cast(int, getattr(module, "id", 0)): module for module in pending_modules}
    project_member_ids = {cast(int, getattr(member, "id", 0)) for member in project.members}
    touched_module_ids = set()
    now = datetime.now()

    for raw_member_id, module_ids in payload.assignments.items():
        member_id = int(raw_member_id)
        if member_id not in project_member_ids:
            raise HTTPException(status_code=400, detail=f"成员 {member_id} 不在项目组中")

        member = db.query(models.Member).filter(models.Member.id == member_id).first()
        if member is None:
            raise HTTPException(status_code=404, detail=f"成员 {member_id} 不存在")

        for module_id in module_ids:
            normalized_module_id = int(module_id)
            module = pending_module_map.get(normalized_module_id)
            if module is None:
                raise HTTPException(status_code=400, detail=f"模块 {normalized_module_id} 不是待分配模块")
            if normalized_module_id in touched_module_ids:
                raise HTTPException(status_code=400, detail=f"模块 {normalized_module_id} 被重复分配")

            setattr(module, "assigned_to", member_id)
            setattr(module, "assigned_at", now)
            setattr(module, "status", "开发中")
            touched_module_ids.add(normalized_module_id)

    db.commit()

    return {
        "message": "批量分配已确认",
        "updated_modules": sorted(touched_module_ids),
        "count": len(touched_module_ids),
    }


@router.post("/direct/{module_id}/{member_id}")
def direct_assignment(module_id: int, member_id: int, db: Session = Depends(get_db)):
    """
    拖拽快速分配：给前端看板用的快捷接口。
    """
    module = db.query(models.Module).filter(models.Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="该模块不存在。")

    project_id = getattr(module, "project_id", None)
    project = db.query(models.Project).filter(models.Project.id == project_id).first() if project_id is not None else None
    if project is not None:
        now = datetime.now()
        a_start = getattr(project, "assessment_start", None)
        a_end = getattr(project, "assessment_end", None)
        if a_start is not None and a_end is not None and a_start <= now and now <= a_end:
            raise HTTPException(status_code=400, detail="评分期内禁止手动分配，请等待评分结束后使用一键分配功能")

    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="该员工不存在。")

    module_status = getattr(module, "status", None)
    if module_status not in {"待分配", "开发中"}:
        raise HTTPException(status_code=400, detail=f"该模块当前状态为『{module_status}』，无法重新分配。")

    module_id_value = getattr(module, "id", module_id)
    is_unlocked = check_module_unlocked(module_id_value, db)
    if not is_unlocked:
        raise HTTPException(
            status_code=403,
            detail="【硬性依赖阻止】：该模块有前置模块还没有完成并上传通过审核，现在分配了也不能干活！",
        )

    setattr(module, "assigned_to", getattr(member, "id", member_id))
    setattr(module, "assigned_at", datetime.now())
    setattr(module, "status", "开发中")
    db.commit()

    return {"message": f"快速指派成功！【{member.name}】被绑定到该模块。", "module_status": getattr(module, "status", None)}
