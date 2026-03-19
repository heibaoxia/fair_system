from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.api.dependencies import CurrentMemberContext, get_current_member_context, get_db
from app.api.project_access import (
    build_visible_projects_query,
    ensure_project_manager,
    ensure_project_visible,
    get_project_or_404,
    require_business_member,
)
from app.api.scoring import _calc_module_summary

router = APIRouter(prefix="/projects", tags=["projects"])

PENDING_STATUS = "\u5f85\u5206\u914d"
COMPLETED_STATUS = "\u5df2\u5b8c\u6210"


def _resolve_scoring_dimensions(project_payload: schemas.ProjectCreate) -> List[dict]:
    requested_dimensions = project_payload.scoring_dimensions
    if not requested_dimensions:
        raise HTTPException(status_code=400, detail="At least one scoring dimension is required.")

    total_weight = sum(float(item.weight) for item in requested_dimensions)
    if abs(total_weight - 1.0) > 0.01:
        raise HTTPException(status_code=400, detail=f"Scoring dimension weights must add up to 1.0, got {total_weight:.4f}.")

    normalized_dimensions = []
    used_names = set()
    for item in requested_dimensions:
        name = (item.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Scoring dimension name must not be empty.")
        if name in used_names:
            raise HTTPException(status_code=400, detail=f"Duplicate scoring dimension name: {name}")
        used_names.add(name)
        normalized_dimensions.append({"name": name, "weight": float(item.weight)})
    return normalized_dimensions


@router.post("/", response_model=schemas.Project)
def create_project(
    project: schemas.ProjectCreate,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    creator = require_business_member(context, "Select an acting identity before creating a project.")
    scoring_dimensions = _resolve_scoring_dimensions(project)

    db_project = models.Project(
        name=project.name,
        description=project.description,
        created_by=creator.id,
    )
    db.add(db_project)
    db_project.members.append(creator)
    db.commit()
    db.refresh(db_project)

    for index, item in enumerate(scoring_dimensions):
        db.add(
            models.ScoringDimension(
                project_id=db_project.id,
                name=item["name"],
                weight=item["weight"],
                sort_order=index,
            )
        )
    db.commit()
    db.refresh(db_project)

    created_modules = []
    for mod in project.new_modules:
        new_mod = models.Module(
            name=mod.name,
            description=mod.description,
            estimated_hours=mod.estimated_hours,
            allowed_file_types=mod.allowed_file_types,
            project_id=db_project.id,
        )
        db.add(new_mod)
        created_modules.append(new_mod)

    if created_modules:
        db.commit()
        for mod in created_modules:
            db.refresh(mod)

    for dep in project.dependencies:
        try:
            pre_idx = dep.get("preceding")
            dep_idx = dep.get("dependent")
        except AttributeError:
            continue
        if pre_idx is None or dep_idx is None:
            continue
        try:
            db.add(
                models.FileDependency(
                    preceding_module_id=created_modules[pre_idx].id,
                    dependent_module_id=created_modules[dep_idx].id,
                )
            )
        except IndexError:
            continue
    db.commit()
    db.refresh(db_project)
    return db_project


@router.get("/", response_model=List[schemas.Project])
def read_projects(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    return build_visible_projects_query(db, context).offset(skip).limit(limit).all()


@router.get("/my")
def get_my_projects(
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    actor_id = None if context.acting_member is None else context.acting_member.id
    projects = build_visible_projects_query(db, context).all()
    return [
        {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "is_manager": actor_id is not None and project.created_by == actor_id,
            "total_revenue": project.total_revenue,
        }
        for project in projects
    ]


@router.get("/{project_id}", response_model=schemas.Project)
def read_project(
    project_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_visible(project, context)
    return project


@router.get("/{project_id}/completion-status")
def get_project_completion_status(
    project_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_visible(project, context)

    modules = db.query(models.Module).filter(models.Module.project_id == project_id).all()
    total_modules = len(modules)
    completed_modules = sum(1 for module in modules if getattr(module, "status", None) == COMPLETED_STATUS)
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
def settle_project(
    project_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_manager(project, context, "Only the project manager can settle a project.")

    if getattr(project, "status", None) == COMPLETED_STATUS:
        raise HTTPException(status_code=400, detail="Project is already settled.")

    modules = db.query(models.Module).filter(models.Module.project_id == project_id).all()
    if not all(getattr(module, "status", None) == COMPLETED_STATUS for module in modules):
        raise HTTPException(status_code=400, detail="All modules must be completed before settlement.")

    member_score_totals = {}
    for module in modules:
        member_id = getattr(module, "assigned_to", None)
        if member_id is None:
            continue
        summary = _calc_module_summary(module, project, db)
        member_score_totals[member_id] = member_score_totals.get(member_id, 0.0) + float(
            summary.get("composite_score", 0.0) or 0.0
        )

    total_score = sum(member_score_totals.values())
    if total_score <= 0:
        raise HTTPException(status_code=400, detail="No composite scores are available for settlement.")

    total_revenue = float(getattr(project, "total_revenue", 0.0) or 0.0)
    settlements = []
    for member_id, score_total in member_score_totals.items():
        member = db.query(models.Member).filter(models.Member.id == member_id).first()
        if member is None:
            continue

        share_ratio = score_total / total_score
        settlement_amount = round(share_ratio * total_revenue, 2)
        member.total_earnings = float(getattr(member, "total_earnings", 0.0) or 0.0) + settlement_amount
        settlements.append(
            {
                "member_id": member.id,
                "member_name": member.name,
                "composite_score_total": round(score_total, 2),
                "share_ratio": round(share_ratio, 6),
                "settlement_amount": settlement_amount,
            }
        )

    project.status = COMPLETED_STATUS
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
def set_assessment_period(
    project_id: int,
    period: schemas.AssessmentPeriodSet,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_manager(project, context, "Only the project manager can change the assessment period.")

    now = datetime.now()
    max_duration_hours = 168

    if period.start_mode not in {"immediate", "scheduled"}:
        raise HTTPException(status_code=400, detail="Invalid assessment start mode.")
    if period.duration_hours <= 0:
        raise HTTPException(status_code=400, detail="Assessment duration must be greater than 0.")
    if period.duration_hours > max_duration_hours:
        raise HTTPException(status_code=400, detail=f"Assessment duration cannot exceed {max_duration_hours} hours.")

    if period.start_mode == "scheduled":
        if period.start_at is None or period.start_at <= now:
            raise HTTPException(status_code=400, detail="Scheduled start time must be in the future.")
        assessment_start = period.start_at
    else:
        assessment_start = now

    assessment_end = assessment_start + timedelta(hours=period.duration_hours)
    if assessment_end <= assessment_start or assessment_end <= now:
        raise HTTPException(status_code=400, detail="Assessment end time must be in the future.")

    project.assessment_start = assessment_start
    project.assessment_end = assessment_end
    db.commit()
    db.refresh(project)
    return project


@router.post("/{project_id}/modules", response_model=schemas.Module)
def create_module_for_project(
    project_id: int,
    module: schemas.ModuleCreate,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_manager(project, context, "Only the project manager can add modules.")

    new_module = models.Module(
        name=module.name,
        description=module.description,
        estimated_hours=module.estimated_hours,
        allowed_file_types=module.allowed_file_types,
        project_id=project_id,
        status=PENDING_STATUS,
    )
    db.add(new_module)
    db.commit()
    db.refresh(new_module)
    return new_module


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_manager(project, context, "Only the project manager can delete a project.")

    module_ids = [module.id for module in db.query(models.Module).filter(models.Module.project_id == project_id).all()]
    if module_ids:
        assessment_ids = [
            assessment.id
            for assessment in db.query(models.ModuleAssessment.id).filter(
                models.ModuleAssessment.module_id.in_(module_ids)
            )
        ]
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
        db.query(models.ModuleFile).filter(models.ModuleFile.module_id.in_(module_ids)).delete(
            synchronize_session=False
        )
        db.query(models.Module).filter(models.Module.id.in_(module_ids)).delete(synchronize_session=False)

    db.query(models.ProjectInvite).filter(models.ProjectInvite.project_id == project_id).delete(
        synchronize_session=False
    )
    db.query(models.ScoringDimension).filter(models.ScoringDimension.project_id == project_id).delete(
        synchronize_session=False
    )
    project.members.clear()
    db.delete(project)
    db.commit()


@router.post("/{project_id}/members/{member_id}")
def add_member_to_project(
    project_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_manager(project, context, "Only the project manager can add project members.")
    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if member in project.members:
        return {"message": "Member is already in the project."}

    project.members.append(member)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        refreshed_project = get_project_or_404(project_id, db)
        refreshed_member = db.query(models.Member).filter(models.Member.id == member_id).first()
        if refreshed_member is not None and refreshed_member in refreshed_project.members:
            return {"message": "Member is already in the project."}
        raise
    return {"message": f"Added {member.name} to the project."}


@router.delete("/{project_id}/members/{member_id}")
def remove_member_from_project(
    project_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_manager(project, context, "Only the project manager can remove project members.")
    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if member_id == getattr(project, "created_by", None):
        raise HTTPException(status_code=400, detail="Cannot remove the project creator.")
    if member in project.members:
        project.members.remove(member)
        db.commit()
        return {"message": f"Removed {member.name} from the project."}
    return {"message": "Member is not in the project."}
