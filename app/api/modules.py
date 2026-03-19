from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.dependencies import CurrentMemberContext, get_current_member_context, get_db
from app.api.project_access import ensure_project_manager, ensure_project_visible, get_project_or_404
from app.utils.dependency_checker import check_module_unlocked

router = APIRouter(tags=["modules"])

PENDING_STATUS = "\u5f85\u5206\u914d"
IN_PROGRESS_STATUS = "\u5f00\u53d1\u4e2d"
IN_REVIEW_STATUS = "\u5f85\u5ba1\u6838"
COMPLETED_STATUS = "\u5df2\u5b8c\u6210"
VALID_MODULE_STATUSES = {PENDING_STATUS, IN_PROGRESS_STATUS, IN_REVIEW_STATUS, COMPLETED_STATUS}


def _get_module_or_404(module_id: int, db: Session) -> models.Module:
    module = db.query(models.Module).filter(models.Module.id == module_id).first()
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    return module


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
    payload.update(
        {
            "is_unlocked": check_module_unlocked(module_id, db),
            "incoming_dependencies": incoming,
            "outgoing_dependencies": outgoing,
        }
    )
    return schemas.ModuleDetail(**payload)


@router.get("/projects/{project_id}/modules", response_model=List[schemas.Module])
def read_modules_for_project(
    project_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_visible(project, context)
    return db.query(models.Module).filter(models.Module.project_id == project_id).all()


@router.get("/modules/{module_id}", response_model=schemas.ModuleDetail)
def read_module(
    module_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    module = _get_module_or_404(module_id, db)
    project = get_project_or_404(getattr(module, "project_id", 0), db)
    ensure_project_visible(project, context)
    return _build_module_detail(module, db)


@router.put("/modules/{module_id}", response_model=schemas.ModuleDetail)
def update_module(
    module_id: int,
    module_in: schemas.ModuleUpdate,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    module = _get_module_or_404(module_id, db)
    project = get_project_or_404(getattr(module, "project_id", 0), db)
    ensure_project_manager(project, context, "Only the project manager can edit modules.")
    _ensure_module_not_assessed(module_id, db, "Modules with assessments cannot be edited.")
    updates = module_in.model_dump(exclude_unset=True)

    if not updates:
        return _build_module_detail(module, db)
    if "status" in updates and updates["status"] not in VALID_MODULE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid module status.")

    if "assigned_to" in updates and updates["assigned_to"] is not None:
        member = db.query(models.Member).filter(models.Member.id == updates["assigned_to"]).first()
        if member is None:
            raise HTTPException(status_code=404, detail="Assigned member not found.")
        if member not in project.members:
            raise HTTPException(status_code=400, detail="Assigned member must join the project first.")

    final_status = updates.get("status", module.status)
    final_assigned_to = updates.get("assigned_to", module.assigned_to)
    if final_status in {IN_PROGRESS_STATUS, IN_REVIEW_STATUS, COMPLETED_STATUS} and final_assigned_to is None:
        raise HTTPException(status_code=400, detail="Execution-stage modules must have an assignee.")

    if final_status == PENDING_STATUS:
        module.assigned_to = None
        module.assigned_at = None
        final_assigned_to = None

    for field in ["name", "description", "estimated_hours", "allowed_file_types", "status"]:
        if field in updates:
            setattr(module, field, updates[field])

    if "assigned_to" in updates and final_status != PENDING_STATUS:
        module.assigned_to = updates["assigned_to"]
        module.assigned_at = datetime.now() if updates["assigned_to"] is not None else None

    db.commit()
    db.refresh(module)
    return _build_module_detail(module, db)


@router.delete("/modules/{module_id}", status_code=204)
def delete_module(
    module_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    module = _get_module_or_404(module_id, db)
    project = get_project_or_404(getattr(module, "project_id", 0), db)
    ensure_project_manager(project, context, "Only the project manager can delete modules.")
    _ensure_module_not_assessed(module_id, db, "Modules with assessments cannot be deleted.")

    db.query(models.FileDependency).filter(
        (models.FileDependency.preceding_module_id == module_id)
        | (models.FileDependency.dependent_module_id == module_id)
    ).delete(synchronize_session=False)
    db.query(models.ModuleAssessment).filter(models.ModuleAssessment.module_id == module_id).delete(
        synchronize_session=False
    )
    db.query(models.ModuleFile).filter(models.ModuleFile.module_id == module_id).delete(
        synchronize_session=False
    )
    db.delete(module)
    db.commit()
