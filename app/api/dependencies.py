from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal
from app.services.auth_service import load_session

SESSION_COOKIE_NAME = "session_token"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@dataclass
class CurrentMemberContext:
    session: models.AuthSession
    account: models.Account
    bound_member: models.Member | None
    acting_member: models.Member | None

    @property
    def acting_member_id(self) -> int | None:
        return None if self.acting_member is None else self.acting_member.id


def require_login(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> models.AuthSession:
    session = load_session(db, session_token or "")
    if session is None:
        raise HTTPException(status_code=401, detail="Login required.")
    return session


def get_current_account(
    session: models.AuthSession = Depends(require_login),
) -> models.Account:
    return session.account


def get_current_member_context(
    session: models.AuthSession = Depends(require_login),
) -> CurrentMemberContext:
    return CurrentMemberContext(
        session=session,
        account=session.account,
        bound_member=session.account.member,
        acting_member=session.acting_member,
    )


def _get_project_or_404(db: Session, project_id: int) -> models.Project:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def require_project_member(
    project_id: int,
    context: CurrentMemberContext = Depends(get_current_member_context),
    db: Session = Depends(get_db),
) -> CurrentMemberContext:
    project = _get_project_or_404(db, project_id)

    if context.account.is_super_account:
        return context

    if context.acting_member is None:
        raise HTTPException(status_code=403, detail="No acting member is available.")

    if project.created_by == context.acting_member.id:
        return context

    if any(member.id == context.acting_member.id for member in project.members):
        return context

    raise HTTPException(status_code=403, detail="Project membership required.")


def require_project_pm(
    project_id: int,
    context: CurrentMemberContext = Depends(get_current_member_context),
    db: Session = Depends(get_db),
) -> CurrentMemberContext:
    project = _get_project_or_404(db, project_id)

    if context.account.is_super_account:
        return context

    if context.acting_member is None or project.created_by != context.acting_member.id:
        raise HTTPException(status_code=403, detail="Project manager access required.")

    return context

