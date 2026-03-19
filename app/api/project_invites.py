from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentMemberContext, get_current_member_context, get_db
from app.api.project_access import ensure_project_manager, get_project_or_404
from app import schemas_project_invites
from app.services import project_invite_service

router = APIRouter(tags=["project-invites"])


def _raise_from_service_error(exc: Exception) -> None:
    if isinstance(exc, project_invite_service.ProjectInviteNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, project_invite_service.ProjectInvitePermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, project_invite_service.ProjectInviteStateError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, project_invite_service.ProjectInviteValidationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@router.post(
    "/projects/{project_id}/invites",
    response_model=schemas_project_invites.ProjectInviteItem,
)
def create_project_invite(
    project_id: int,
    payload: schemas_project_invites.ProjectInviteCreateRequest,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_manager(project, context, "Only the project manager can create invites.")
    try:
        return project_invite_service.create_project_invite(
            db,
            project=project,
            inviter_account_id=context.account.id,
            invitee_account_id=payload.invitee_account_id,
        )
    except project_invite_service.ProjectInviteError as exc:
        _raise_from_service_error(exc)


@router.get(
    "/projects/{project_id}/invites",
    response_model=schemas_project_invites.ProjectInviteListResponse,
)
def list_project_invites(
    project_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    project = get_project_or_404(project_id, db)
    ensure_project_manager(project, context, "Only the project manager can view invites.")
    return {"invites": project_invite_service.list_project_invites(db, project_id=project_id)}


@router.post(
    "/project-invites/{invite_id}/accept",
    response_model=schemas_project_invites.ProjectInviteDecisionResponse,
)
def accept_project_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    try:
        project_invite_service.accept_project_invite(
            db,
            invite_id=invite_id,
            actor_account_id=context.account.id,
        )
    except project_invite_service.ProjectInviteError as exc:
        _raise_from_service_error(exc)
    return {"ok": True, "status": "accepted"}


@router.post(
    "/project-invites/{invite_id}/reject",
    response_model=schemas_project_invites.ProjectInviteDecisionResponse,
)
def reject_project_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    context: CurrentMemberContext = Depends(get_current_member_context),
):
    try:
        project_invite_service.reject_project_invite(
            db,
            invite_id=invite_id,
            actor_account_id=context.account.id,
        )
    except project_invite_service.ProjectInviteError as exc:
        _raise_from_service_error(exc)
    return {"ok": True, "status": "rejected"}
