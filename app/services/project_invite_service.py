from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app import models

PENDING_STATUS = "pending"
ACCEPTED_STATUS = "accepted"
REJECTED_STATUS = "rejected"
CANCELLED_STATUS = "cancelled"
RESOLVED_STATUSES = {ACCEPTED_STATUS, REJECTED_STATUS, CANCELLED_STATUS}


class ProjectInviteError(Exception):
    pass


class ProjectInviteNotFoundError(ProjectInviteError):
    pass


class ProjectInvitePermissionError(ProjectInviteError):
    pass


class ProjectInviteValidationError(ProjectInviteError):
    pass


class ProjectInviteStateError(ProjectInviteError):
    pass


@dataclass(frozen=True)
class ProjectInviteSummary:
    id: int
    project_id: int
    project_name: str
    inviter_account_id: int
    inviter_username: str
    status: str
    project_total_revenue: float
    project_member_count: int
    project_description: str
    created_at: datetime
    resolved_at: datetime | None


def _get_invitee_account_or_error(db: Session, *, invitee_account_id: int) -> models.Account:
    account = (
        db.query(models.Account)
        .options(joinedload(models.Account.member))
        .filter(models.Account.id == invitee_account_id)
        .first()
    )
    if account is None:
        raise ProjectInviteValidationError("Invite target account is not eligible.")
    if account.is_super_account:
        raise ProjectInviteValidationError("Invite target account is not eligible.")
    if not account.is_active:
        raise ProjectInviteValidationError("Invite target account is not eligible.")
    if account.registration_status != "active":
        raise ProjectInviteValidationError("Invite target account is not eligible.")
    if account.email_verified_at is None:
        raise ProjectInviteValidationError("Invite target account is not eligible.")
    if account.member is None or account.member_id is None:
        raise ProjectInviteValidationError("Invite target account is not eligible.")
    if not account.member.is_active:
        raise ProjectInviteValidationError("Invite target account is not eligible.")
    if bool(getattr(account.member, "is_virtual_identity", False)):
        raise ProjectInviteValidationError("Invite target account is not eligible.")
    return account


def _get_invite_or_error(db: Session, *, invite_id: int) -> models.ProjectInvite:
    invite = (
        db.query(models.ProjectInvite)
        .options(
            joinedload(models.ProjectInvite.project),
            joinedload(models.ProjectInvite.invitee_account).joinedload(models.Account.member),
        )
        .filter(models.ProjectInvite.id == invite_id)
        .first()
    )
    if invite is None:
        raise ProjectInviteNotFoundError("Project invite not found.")
    return invite


def create_project_invite(
    db: Session,
    *,
    project: models.Project,
    inviter_account_id: int,
    invitee_account_id: int,
) -> models.ProjectInvite:
    if inviter_account_id == invitee_account_id:
        raise ProjectInviteValidationError("Users cannot invite themselves.")

    invitee_account = _get_invitee_account_or_error(db, invitee_account_id=invitee_account_id)

    if any(member.id == invitee_account.member_id for member in project.members):
        raise ProjectInviteValidationError("Invitee is already a project member.")

    duplicate_pending_invite = (
        db.query(models.ProjectInvite)
        .filter(
            models.ProjectInvite.project_id == project.id,
            models.ProjectInvite.invitee_account_id == invitee_account_id,
            models.ProjectInvite.status == PENDING_STATUS,
        )
        .first()
    )
    if duplicate_pending_invite is not None:
        raise ProjectInviteValidationError("A pending invite already exists for this account.")

    invite = models.ProjectInvite(
        project_id=project.id,
        inviter_account_id=inviter_account_id,
        invitee_account_id=invitee_account_id,
        status=PENDING_STATUS,
    )
    db.add(invite)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate_pending_invite = (
            db.query(models.ProjectInvite)
            .filter(
                models.ProjectInvite.project_id == project.id,
                models.ProjectInvite.invitee_account_id == invitee_account_id,
                models.ProjectInvite.status == PENDING_STATUS,
            )
            .first()
        )
        if duplicate_pending_invite is not None:
            raise ProjectInviteValidationError("A pending invite already exists for this account.") from exc
        raise
    db.refresh(invite)
    return invite


def list_project_invites(db: Session, *, project_id: int) -> list[models.ProjectInvite]:
    return (
        db.query(models.ProjectInvite)
        .filter(models.ProjectInvite.project_id == project_id)
        .order_by(models.ProjectInvite.id.asc())
        .all()
    )


def _build_invite_summary(invite: models.ProjectInvite) -> ProjectInviteSummary:
    inviter_member = None if invite.inviter_account is None else invite.inviter_account.member
    inviter_username = invite.inviter_account.login_id if invite.inviter_account is not None else ""
    if inviter_member is not None and inviter_member.name:
        inviter_username = inviter_member.name

    return ProjectInviteSummary(
        id=invite.id,
        project_id=invite.project_id,
        project_name=invite.project.name if invite.project is not None else "",
        inviter_account_id=invite.inviter_account_id,
        inviter_username=inviter_username,
        status=invite.status,
        project_total_revenue=float(getattr(invite.project, "total_revenue", 0.0) or 0.0),
        project_member_count=len(getattr(invite.project, "members", []) or []),
        project_description=getattr(invite.project, "description", "") or "",
        created_at=invite.created_at,
        resolved_at=invite.resolved_at,
    )


def list_project_invites_for_invitee(
    db: Session,
    *,
    invitee_account_id: int,
) -> dict[str, list[ProjectInviteSummary]]:
    invites = (
        db.query(models.ProjectInvite)
        .options(
            joinedload(models.ProjectInvite.project).joinedload(models.Project.members),
            joinedload(models.ProjectInvite.inviter_account).joinedload(models.Account.member),
        )
        .filter(models.ProjectInvite.invitee_account_id == invitee_account_id)
        .all()
    )

    pending = []
    history = []
    for invite in invites:
        summary = _build_invite_summary(invite)
        if invite.status == PENDING_STATUS:
            pending.append(summary)
        else:
            history.append(summary)

    pending.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    history.sort(
        key=lambda item: (item.resolved_at or datetime.min, item.created_at, item.id),
        reverse=True,
    )
    return {"pending": pending, "history": history}


def accept_project_invite(
    db: Session,
    *,
    invite_id: int,
    actor_account_id: int,
) -> models.ProjectInvite:
    invite = _get_invite_or_error(db, invite_id=invite_id)
    if invite.invitee_account_id != actor_account_id:
        raise ProjectInvitePermissionError("Only the invitee can accept this invite.")
    if invite.status != PENDING_STATUS:
        raise ProjectInviteStateError("Only pending invites can be accepted.")

    current_invitee_account = (
        db.query(models.Account)
        .options(joinedload(models.Account.member))
        .filter(models.Account.id == invite.invitee_account_id)
        .first()
    )
    current_invitee_member_id = None if current_invitee_account is None else current_invitee_account.member_id
    if current_invitee_member_id is not None and any(
        member.id == current_invitee_member_id for member in invite.project.members
    ):
        invite.status = CANCELLED_STATUS
        invite.resolved_at = datetime.now()
        db.commit()
        db.refresh(invite)
        raise ProjectInviteStateError("Invite is no longer actionable.")

    invitee_account = _get_invitee_account_or_error(db, invitee_account_id=invite.invitee_account_id)
    invitee_member = invitee_account.member
    if invitee_member is None:
        raise ProjectInviteValidationError("Invite target account is not eligible.")

    invite.status = ACCEPTED_STATUS
    invite.resolved_at = datetime.now()
    if not any(member.id == invitee_member.id for member in invite.project.members):
        invite.project.members.append(invitee_member)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        refreshed_invite = _get_invite_or_error(db, invite_id=invite_id)
        refreshed_account = (
            db.query(models.Account)
            .options(joinedload(models.Account.member))
            .filter(models.Account.id == refreshed_invite.invitee_account_id)
            .first()
        )
        refreshed_member_id = None if refreshed_account is None else refreshed_account.member_id
        if refreshed_member_id is not None and any(
            member.id == refreshed_member_id for member in refreshed_invite.project.members
        ):
            refreshed_invite.status = CANCELLED_STATUS
            refreshed_invite.resolved_at = datetime.now()
            db.commit()
            db.refresh(refreshed_invite)
            raise ProjectInviteStateError("Invite is no longer actionable.") from exc
        raise
    db.refresh(invite)
    return invite


def reject_project_invite(
    db: Session,
    *,
    invite_id: int,
    actor_account_id: int,
) -> models.ProjectInvite:
    invite = _get_invite_or_error(db, invite_id=invite_id)
    if invite.invitee_account_id != actor_account_id:
        raise ProjectInvitePermissionError("Only the invitee can reject this invite.")
    if invite.status != PENDING_STATUS:
        raise ProjectInviteStateError("Only pending invites can be rejected.")

    invite.status = REJECTED_STATUS
    invite.resolved_at = datetime.now()
    db.commit()
    db.refresh(invite)
    return invite
