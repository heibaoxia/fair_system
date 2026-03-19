from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Query, Session

from app import models
from app.api.dependencies import CurrentMemberContext


def get_project_or_404(project_id: int, db: Session) -> models.Project:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def is_super_global_view(context: CurrentMemberContext) -> bool:
    return bool(context.account.is_super_account and context.acting_member is None)


def require_business_member(
    context: CurrentMemberContext,
    detail: str = "Select an acting identity before performing this action.",
) -> models.Member:
    if context.acting_member is None:
        raise HTTPException(status_code=403, detail=detail)
    return context.acting_member


def build_visible_projects_query(db: Session, context: CurrentMemberContext) -> Query:
    query = db.query(models.Project)
    if is_super_global_view(context):
        return query

    business_member = require_business_member(context)
    return query.filter(
        (models.Project.created_by == business_member.id)
        | models.Project.members.any(models.Member.id == business_member.id)
    )


def ensure_project_visible(
    project: models.Project,
    context: CurrentMemberContext,
    detail: str = "Project access denied.",
) -> models.Member | None:
    if is_super_global_view(context):
        return None

    business_member = require_business_member(context, detail)
    if project.created_by == business_member.id:
        return business_member
    if any(member.id == business_member.id for member in project.members):
        return business_member
    raise HTTPException(status_code=403, detail=detail)


def ensure_project_manager(
    project: models.Project,
    context: CurrentMemberContext,
    detail: str = "Project manager access required.",
) -> models.Member:
    business_member = require_business_member(context, detail)
    if project.created_by != business_member.id:
        raise HTTPException(status_code=403, detail=detail)
    return business_member
