"""
模块管理 API。
负责补充项目模块的查询、更新和删除能力，避免所有模块逻辑都塞在 projects.py 里。
"""

from typing import List

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.dependencies import get_db
from app.utils.dependency_checker import check_module_unlocked


router = APIRouter(tags=["模块管理"])

VALID_MODULE_STATUSES = {"待分配", "开发中", "待审核", "已完成"}


def _get_project_or_404(project_id: int, db: Session) -> models.Project:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _get_module_or_404(module_id: int, db: Session) -> models.Module:
    module = db.query(models.Module).filter(models.Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="模块不存在")
    return module


def _ensure_project_manager(project: models.Project, current_member_id: int, detail: str) -> None:
    if getattr(project, "created_by", None) != current_member_id:
        raise HTTPException(status_code=403, detail=detail)


def _ensure_module_not_assessed(module_id: int, db: Session, detail: str) -> None:
    existing_assessment = db.query(models.ModuleAssessment).filter(
        models.ModuleAssessment.module_id == module_id
    ).first()
    if existing_assessment is not None:
        raise HTTPException(status_code=400, detail=detail)


def _build_module_detail(module: models.Module, db: Session) -> schemas.ModuleDetail:
    module_id = getattr(module, "id", None)
    incoming = db.query(models.FileDependency).filter(
        models.FileDependency.dependent_module_id == module_id
    ).all()
    outgoing = db.query(models.FileDependency).filter(
        models.FileDependency.preceding_module_id == module_id
    ).all()
    payload = schemas.Module.model_validate(module).model_dump()
    payload.update({
        "is_unlocked": check_module_unlocked(module_id, db),
        "incoming_dependencies": incoming,
        "outgoing_dependencies": outgoing,
    })
    return schemas.ModuleDetail(**payload)


@router.get("/projects/{project_id}/modules", response_model=List[schemas.Module])
def read_modules_for_project(project_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    return db.query(models.Module).filter(models.Module.project_id == project_id).all()


@router.get("/modules/{module_id}", response_model=schemas.ModuleDetail)
def read_module(module_id: int, db: Session = Depends(get_db)):
    module = _get_module_or_404(module_id, db)
    return _build_module_detail(module, db)


@router.put("/modules/{module_id}", response_model=schemas.ModuleDetail)
def update_module(module_id: int, module_in: schemas.ModuleUpdate, current_member_id: int, db: Session = Depends(get_db)):
    module = _get_module_or_404(module_id, db)
    project = _get_project_or_404(getattr(module, "project_id", 0), db)
    _ensure_project_manager(project, current_member_id, "只有项目创建者才能编辑模块")
    _ensure_module_not_assessed(module_id, db, "该模块已有成员评分，不能再编辑")
    updates = module_in.model_dump(exclude_unset=True)

    if not updates:
        return _build_module_detail(module, db)

    if "status" in updates and updates["status"] not in VALID_MODULE_STATUSES:
        raise HTTPException(status_code=400, detail="模块状态不合法")

    if "assigned_to" in updates and updates["assigned_to"] is not None:
        member = db.query(models.Member).filter(models.Member.id == updates["assigned_to"]).first()
        if not member:
            raise HTTPException(status_code=404, detail="指定负责人不存在")

        project = _get_project_or_404(getattr(module, "project_id", 0), db)
        if member not in project.members:
            raise HTTPException(status_code=400, detail="负责人必须先加入项目组")

    final_status = updates.get("status", module.status)
    final_assigned_to = updates.get("assigned_to", module.assigned_to)

    if final_status in {"开发中", "待审核", "已完成"} and final_assigned_to is None:
        raise HTTPException(status_code=400, detail="模块进入执行阶段前必须指定负责人")

    if final_status == "待分配":
        setattr(module, "assigned_to", None)
        setattr(module, "assigned_at", None)
        final_assigned_to = None

    for field in ["name", "description", "estimated_hours", "allowed_file_types", "status"]:
        if field in updates:
            setattr(module, field, updates[field])

    if "assigned_to" in updates and final_status != "待分配":
        module.assigned_to = updates["assigned_to"]
        module.assigned_at = datetime.now() if updates["assigned_to"] is not None else None

    db.commit()
    db.refresh(module)
    return _build_module_detail(module, db)


@router.delete("/modules/{module_id}", status_code=204)
def delete_module(module_id: int, current_member_id: int, db: Session = Depends(get_db)):
    module = _get_module_or_404(module_id, db)
    project = _get_project_or_404(getattr(module, "project_id", 0), db)
    _ensure_project_manager(project, current_member_id, "只有项目创建者才能删除模块")
    _ensure_module_not_assessed(module_id, db, "该模块已有成员评分，不能删除")

    db.query(models.FileDependency).filter(
        (models.FileDependency.preceding_module_id == module_id)
        | (models.FileDependency.dependent_module_id == module_id)
    ).delete(synchronize_session=False)
    db.query(models.ModuleAssessment).filter(
        models.ModuleAssessment.module_id == module_id
    ).delete(synchronize_session=False)
    db.query(models.ModuleFile).filter(
        models.ModuleFile.module_id == module_id
    ).delete(synchronize_session=False)
    db.delete(module)
    db.commit()
