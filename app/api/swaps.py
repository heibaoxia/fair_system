from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.api.dependencies import get_db

router = APIRouter(prefix="/swaps", tags=["模块交换"])


class SwapCreatePayload(BaseModel):
    module_id: int
    to_member_id: int
    swap_type: str = "reassign"
    reason: str = ""
    swap_module_id: Optional[int] = None


def _get_swap_or_404(swap_id: int, db: Session) -> models.ModuleSwapRequest:
    swap = db.query(models.ModuleSwapRequest).filter(models.ModuleSwapRequest.id == swap_id).first()
    if swap is None:
        raise HTTPException(status_code=404, detail="交换请求不存在")
    return swap


def _get_project_or_404(project_id: int, db: Session) -> models.Project:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _member_in_project(project: models.Project, member_id: int) -> bool:
    return any(int(member.id) == member_id for member in project.members)


def get_pending_swap_requests(member_id: int, db: Session) -> list[dict]:
    swaps = db.query(models.ModuleSwapRequest).filter(
        models.ModuleSwapRequest.to_member_id == member_id,
        models.ModuleSwapRequest.status == "待确认",
    ).order_by(models.ModuleSwapRequest.created_at.desc()).all()

    results = []
    for swap in swaps:
        module = db.query(models.Module).filter(models.Module.id == swap.module_id).first()
        swap_module = db.query(models.Module).filter(models.Module.id == swap.swap_module_id).first() if swap.swap_module_id else None
        project = db.query(models.Project).filter(models.Project.id == swap.project_id).first()
        initiator = db.query(models.Member).filter(models.Member.id == swap.initiated_by).first()
        from_member = db.query(models.Member).filter(models.Member.id == swap.from_member_id).first()
        to_member = db.query(models.Member).filter(models.Member.id == swap.to_member_id).first()

        results.append({
            "id": swap.id,
            "project_id": swap.project_id,
            "project_name": project.name if project else "未知项目",
            "module_id": swap.module_id,
            "module_name": module.name if module else f"模块 #{swap.module_id}",
            "swap_module_id": swap.swap_module_id,
            "swap_module_name": swap_module.name if swap_module else "",
            "swap_type": swap.swap_type,
            "initiated_by": swap.initiated_by,
            "initiator_name": initiator.name if initiator else f"成员 #{swap.initiated_by}",
            "from_member_id": swap.from_member_id,
            "from_member_name": from_member.name if from_member else f"成员 #{swap.from_member_id}",
            "to_member_id": swap.to_member_id,
            "to_member_name": to_member.name if to_member else f"成员 #{swap.to_member_id}",
            "reason": swap.reason or "",
            "created_at": swap.created_at.isoformat() if swap.created_at else "",
        })

    return results


@router.post("/")
def create_swap_request(payload: SwapCreatePayload, current_member_id: int, db: Session = Depends(get_db)):
    module = db.query(models.Module).filter(models.Module.id == payload.module_id).first()
    if module is None:
        raise HTTPException(status_code=404, detail="模块不存在")
    if module.status != "开发中":
        raise HTTPException(status_code=400, detail="只有开发中的模块才能发起交换请求")
    if module.assigned_to is None:
        raise HTTPException(status_code=400, detail="当前模块没有负责人，无法发起交换")

    project = _get_project_or_404(int(module.project_id), db)
    if int(project.created_by) != current_member_id:
        raise HTTPException(status_code=403, detail="非 PM 无法发起请求")
    if not _member_in_project(project, payload.to_member_id):
        raise HTTPException(status_code=400, detail="接收人必须是项目组成员")
    if payload.to_member_id == int(module.assigned_to):
        raise HTTPException(status_code=400, detail="接收人已是当前负责人")
    if payload.swap_type not in {"swap", "reassign"}:
        raise HTTPException(status_code=400, detail="交换类型不合法")

    swap_module_id = payload.swap_module_id
    if payload.swap_type == "swap":
        if not swap_module_id:
            raise HTTPException(status_code=400, detail="交换模式必须提供对方模块")
        swap_module = db.query(models.Module).filter(models.Module.id == swap_module_id).first()
        if swap_module is None or int(swap_module.project_id) != int(project.id):
            raise HTTPException(status_code=400, detail="交换模块必须属于同一项目")
        if swap_module.status != "开发中":
            raise HTTPException(status_code=400, detail="交换模块必须处于开发中")
        if int(swap_module.assigned_to or 0) != payload.to_member_id:
            raise HTTPException(status_code=400, detail="交换模块当前负责人必须是接收人")

    swap = models.ModuleSwapRequest(
        project_id=project.id,
        initiated_by=current_member_id,
        swap_type=payload.swap_type,
        module_id=payload.module_id,
        swap_module_id=swap_module_id,
        from_member_id=int(module.assigned_to),
        to_member_id=payload.to_member_id,
        reason=payload.reason or "",
    )
    db.add(swap)
    db.commit()
    db.refresh(swap)
    return {"message": "交换请求已发起", "swap_id": swap.id, "status": swap.status}


@router.get("/pending/{member_id}")
def read_pending_swaps(member_id: int, db: Session = Depends(get_db)):
    return get_pending_swap_requests(member_id, db)


@router.post("/{swap_id}/accept")
def accept_swap(swap_id: int, member_id: int, db: Session = Depends(get_db)):
    swap = _get_swap_or_404(swap_id, db)
    if swap.status != "待确认":
        raise HTTPException(status_code=400, detail="该交换请求已处理")
    if int(swap.to_member_id) != member_id:
        raise HTTPException(status_code=403, detail="只有接收人才能接受交换")

    module = db.query(models.Module).filter(models.Module.id == swap.module_id).first()
    if module is None:
        raise HTTPException(status_code=404, detail="目标模块不存在")

    now = datetime.now()
    if swap.swap_type == "swap":
        swap_module = db.query(models.Module).filter(models.Module.id == swap.swap_module_id).first()
        if swap_module is None:
            raise HTTPException(status_code=404, detail="交换模块不存在")
        module.assigned_to = swap.to_member_id
        module.assigned_at = now
        swap_module.assigned_to = swap.from_member_id
        swap_module.assigned_at = now
    else:
        module.assigned_to = swap.to_member_id
        module.assigned_at = now

    swap.status = "已接受"
    swap.resolved_at = now
    db.commit()
    return {"message": "交换请求已接受", "status": swap.status}


@router.post("/{swap_id}/reject")
def reject_swap(swap_id: int, member_id: int, db: Session = Depends(get_db)):
    swap = _get_swap_or_404(swap_id, db)
    if swap.status != "待确认":
        raise HTTPException(status_code=400, detail="该交换请求已处理")
    if int(swap.to_member_id) != member_id:
        raise HTTPException(status_code=403, detail="只有接收人才能拒绝交换")

    swap.status = "已拒绝"
    swap.resolved_at = datetime.now()
    db.commit()
    return {"message": "交换请求已拒绝", "status": swap.status}


@router.post("/{swap_id}/cancel")
def cancel_swap(swap_id: int, current_member_id: int, db: Session = Depends(get_db)):
    swap = _get_swap_or_404(swap_id, db)
    project = _get_project_or_404(int(swap.project_id), db)
    if int(project.created_by) != current_member_id:
        raise HTTPException(status_code=403, detail="只有 PM 可以取消交换请求")
    if swap.status != "待确认":
        raise HTTPException(status_code=400, detail="只有待确认的请求才能取消")

    swap.status = "已取消"
    swap.resolved_at = datetime.now()
    db.commit()
    return {"message": "交换请求已取消", "status": swap.status}
