from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app import models, schemas_auth
from app.api.dependencies import (
    SESSION_COOKIE_NAME,
    CurrentMemberContext,
    get_current_member_context,
    get_db,
    require_login,
)
from app.services.auth_service import (
    DEFAULT_SESSION_TTL,
    AuthenticationError,
    AuthorizationError,
    EmailVerificationError,
    SessionError,
    authenticate_account,
    create_session,
    issue_email_verification_token,
    logout_session,
    register_public_account,
    resend_email_verification,
    switch_acting_member,
    verify_email_token,
)
from app.services.email_sender import (
    EmailSenderConfigurationError,
    EmailSenderError,
    SMTPEmailSender,
    build_verification_email_message,
)

router = APIRouter(prefix="/auth", tags=["auth"])
PUBLIC_RESEND_RESPONSE = schemas_auth.AuthResendVerificationResponse(ok=True, verification_email_sent=True)


def get_email_sender():
    return SMTPEmailSender.from_env()


def get_verification_base_url() -> str:
    base_url = os.getenv("FAIR_AUTH_VERIFY_URL_BASE", "").strip()
    if not base_url:
        raise EmailSenderConfigurationError("FAIR_AUTH_VERIFY_URL_BASE is required.")
    return base_url


def _member_to_schema(member: models.Member | None) -> schemas_auth.AuthMemberIdentity | None:
    if member is None:
        return None
    return schemas_auth.AuthMemberIdentity.model_validate(member)


def _build_identity_pools(
    db: Session,
    context: CurrentMemberContext,
) -> tuple[str, schemas_auth.AuthIdentityPools]:
    own_identities = []
    if context.bound_member is not None:
        own_identities.append(_member_to_schema(context.bound_member))

    if not context.account.is_super_account:
        return (
            "own_only",
            schemas_auth.AuthIdentityPools(
                own_identities=[item for item in own_identities if item is not None],
            ),
        )

    members = (
        db.query(models.Member)
        .options(joinedload(models.Member.account))
        .filter(models.Member.is_active.is_(True))
        .order_by(models.Member.id.asc())
        .all()
    )
    global_identities = [
        schemas_auth.AuthMemberIdentity.model_validate(member)
        for member in members
        if not bool(getattr(member, "is_virtual_identity", False))
    ]
    test_identities = [
        schemas_auth.AuthMemberIdentity.model_validate(member)
        for member in members
        if bool(getattr(member, "is_virtual_identity", False)) and member.account is None
    ]
    return (
        "global_pool",
        schemas_auth.AuthIdentityPools(
            own_identities=[item for item in own_identities if item is not None],
            global_identities=global_identities,
            test_identities=test_identities,
        ),
    )


def _build_available_identities_response(
    db: Session,
    context: CurrentMemberContext,
) -> schemas_auth.AuthAvailableIdentitiesResponse:
    identity_scope, available_identities = _build_identity_pools(db, context)
    return schemas_auth.AuthAvailableIdentitiesResponse(
        identity_scope=identity_scope,
        can_switch_identity=context.account.is_super_account,
        bound_member=_member_to_schema(context.bound_member),
        acting_member=_member_to_schema(context.acting_member),
        available_identities=available_identities,
    )


def _build_session_context_response(
    db: Session,
    context: CurrentMemberContext,
) -> schemas_auth.AuthSessionContextResponse:
    identities = _build_available_identities_response(db, context)
    return schemas_auth.AuthSessionContextResponse(
        authenticated=True,
        account=schemas_auth.AuthAccountSummary.model_validate(context.account),
        session=schemas_auth.AuthSessionSummary(
            expires_at=context.session.expires_at,
            created_at=context.session.created_at,
            last_seen_at=context.session.last_seen_at,
        ),
        identity_scope=identities.identity_scope,
        can_switch_identity=identities.can_switch_identity,
        bound_member=identities.bound_member,
        acting_member=identities.acting_member,
        available_identities=identities.available_identities,
    )


def _build_pending_verification_response(
    account: models.Account,
) -> schemas_auth.AuthSessionContextResponse:
    bound_member = _member_to_schema(account.member)
    own_identities = [bound_member] if bound_member is not None else []
    return schemas_auth.AuthSessionContextResponse(
        authenticated=False,
        account=schemas_auth.AuthAccountSummary.model_validate(account),
        session=None,
        identity_scope="own_only",
        can_switch_identity=False,
        bound_member=bound_member,
        acting_member=None,
        available_identities=schemas_auth.AuthIdentityPools(own_identities=own_identities),
    )


def _build_verification_status_response(
    account: models.Account,
    *,
    verification_email_sent: bool | None = None,
) -> schemas_auth.AuthVerificationStatusResponse:
    return schemas_auth.AuthVerificationStatusResponse(
        ok=True,
        account=schemas_auth.AuthAccountSummary.model_validate(account),
        verification_email_sent=verification_email_sent,
    )


def _resolve_email_sender(request: Request):
    email_sender = getattr(request.app.state, "email_sender", None)
    if email_sender is not None:
        return email_sender
    return get_email_sender()


def _resolve_verification_base_url(request: Request) -> str:
    verification_base_url = getattr(request.app.state, "verification_base_url", None)
    if verification_base_url:
        return verification_base_url
    return get_verification_base_url()


def _send_verification_email(
    *,
    account: models.Account,
    token: str,
    expires_at,
    email_sender,
    verification_base_url: str,
) -> None:
    message = build_verification_email_message(
        recipient=account.email or "",
        login_id=account.login_id,
        token=token,
        expires_at=expires_at,
        verification_base_url=verification_base_url,
    )
    email_sender.send_verification_email(message)


def _cleanup_failed_registration(
    db: Session,
    account_id: int | None,
    member_id: int | None = None,
) -> None:
    if account_id is None and member_id is None:
        return
    db.rollback()
    resolved_member_id = member_id
    if account_id is not None:
        account = db.query(models.Account).filter(models.Account.id == account_id).first()
        if account is not None:
            resolved_member_id = account.member_id
            db.delete(account)
    db.commit()
    if resolved_member_id is None:
        return
    member = db.query(models.Member).filter(models.Member.id == resolved_member_id).first()
    if member is None or member.account is not None:
        return
    db.delete(member)
    db.commit()


def _normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    normalized = email.strip().lower()
    return normalized or None


def _normalize_login_lookup(login_id: str) -> str:
    normalized = login_id.strip()
    if "@" in normalized:
        return normalized.lower()
    return normalized


def _snapshot_pending_verification_state(db: Session, login_id: str) -> dict | None:
    normalized_login_id = _normalize_login_lookup(login_id)
    if "@" in normalized_login_id:
        criterion = func.lower(models.Account.login_id) == normalized_login_id
    else:
        criterion = models.Account.login_id == normalized_login_id
    account = (
        db.query(models.Account)
        .options(joinedload(models.Account.member), joinedload(models.Account.email_verification_tokens))
        .filter(criterion)
        .first()
    )
    if account is None:
        return None
    authoritative_email = _normalize_email(account.member.email if account.member is not None else None)
    return {
        "account_id": account.id,
        "account_email": authoritative_email,
        "registration_status": account.registration_status,
        "email_verified_at": account.email_verified_at,
        "tokens": [
            {
                "email": token.email,
                "token_hash": token.token_hash,
                "expires_at": token.expires_at,
                "consumed_at": token.consumed_at,
                "created_at": token.created_at,
            }
            for token in account.email_verification_tokens
            if token.consumed_at is None
            and authoritative_email is not None
            and _normalize_email(token.email) == authoritative_email
        ],
    }


def _restore_pending_verification_state(db: Session, snapshot: dict | None) -> None:
    if snapshot is None:
        db.rollback()
        return

    db.rollback()
    account = db.query(models.Account).filter(models.Account.id == snapshot["account_id"]).first()
    if account is None:
        return

    account.email = snapshot["account_email"]
    account.registration_status = snapshot["registration_status"]
    account.email_verified_at = snapshot["email_verified_at"]
    db.query(models.EmailVerificationToken).filter(
        models.EmailVerificationToken.account_id == account.id
    ).delete(synchronize_session=False)
    for token_data in snapshot["tokens"]:
        db.add(
            models.EmailVerificationToken(
                account_id=account.id,
                email=token_data["email"],
                token_hash=token_data["token_hash"],
                expires_at=token_data["expires_at"],
                consumed_at=token_data["consumed_at"],
                created_at=token_data["created_at"],
            )
        )
    db.commit()


def _set_session_cookie(response: Response, session_token: str) -> None:
    max_age = int(DEFAULT_SESSION_TTL.total_seconds())
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite="lax",
        max_age=max_age,
        expires=max_age,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


@router.post(
    "/register",
    response_model=schemas_auth.AuthSessionContextResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    request: Request,
    payload: schemas_auth.AuthRegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    account_id: int | None = None
    member_id: int | None = None
    try:
        account = register_public_account(
            db,
            email=payload.email,
            password=payload.password,
            username=payload.username,
            gender=payload.gender,
        )
        account_id = account.id
        member_id = account.member_id
        token_issue = issue_email_verification_token(db, account_id=account.id)
        account = (
            db.query(models.Account)
            .options(joinedload(models.Account.member))
            .filter(models.Account.id == account.id)
            .one()
        )
        email_sender = _resolve_email_sender(request)
        verification_base_url = _resolve_verification_base_url(request)
        _send_verification_email(
            account=account,
            token=token_issue.token,
            expires_at=token_issue.expires_at,
            email_sender=email_sender,
            verification_base_url=verification_base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmailSenderConfigurationError as exc:
        _cleanup_failed_registration(db, account_id, member_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmailSenderError as exc:
        _cleanup_failed_registration(db, account_id, member_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _build_pending_verification_response(account)


@router.post("/login", response_model=schemas_auth.AuthSessionContextResponse)
def login(
    payload: schemas_auth.AuthLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        account = authenticate_account(db, login_id=payload.login_id, password=payload.password)
        session = create_session(db, account_id=account.id)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    _set_session_cookie(response, session.session_token)
    context = CurrentMemberContext(
        session=session,
        account=session.account,
        bound_member=session.account.member,
        acting_member=session.acting_member,
    )
    return _build_session_context_response(db, context)


@router.post("/logout")
def logout(
    response: Response,
    session: models.AuthSession | None = Depends(require_login),
    db: Session = Depends(get_db),
):
    logout_session(db, session.session_token if session is not None else "")
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=schemas_auth.AuthSessionContextResponse)
def me(
    context: CurrentMemberContext = Depends(get_current_member_context),
    db: Session = Depends(get_db),
):
    return _build_session_context_response(db, context)


@router.post("/verify-email", response_model=schemas_auth.AuthVerificationStatusResponse)
def verify_email(
    payload: schemas_auth.AuthVerifyEmailRequest,
    db: Session = Depends(get_db),
):
    try:
        account = verify_email_token(db, payload.token)
    except EmailVerificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _build_verification_status_response(account)


@router.post("/resend-verification", response_model=schemas_auth.AuthResendVerificationResponse)
def resend_verification(
    request: Request,
    payload: schemas_auth.AuthResendVerificationRequest,
    db: Session = Depends(get_db),
):
    snapshot = _snapshot_pending_verification_state(db, payload.login_id.strip())
    try:
        token_issue = resend_email_verification(db, login_id=payload.login_id)
    except ValueError:
        return PUBLIC_RESEND_RESPONSE

    try:
        email_sender = _resolve_email_sender(request)
        verification_base_url = _resolve_verification_base_url(request)
        account = (
            db.query(models.Account)
            .options(joinedload(models.Account.member))
            .filter(models.Account.id == token_issue.account_id)
            .one()
        )
        _send_verification_email(
            account=account,
            token=token_issue.token,
            expires_at=token_issue.expires_at,
            email_sender=email_sender,
            verification_base_url=verification_base_url,
        )
    except EmailSenderConfigurationError as exc:
        _restore_pending_verification_state(db, snapshot)
        return PUBLIC_RESEND_RESPONSE
    except EmailSenderError as exc:
        _restore_pending_verification_state(db, snapshot)
        return PUBLIC_RESEND_RESPONSE

    return PUBLIC_RESEND_RESPONSE


@router.post("/switch-identity", response_model=schemas_auth.AuthSessionContextResponse)
def switch_identity(
    payload: schemas_auth.AuthSwitchIdentityRequest,
    context: CurrentMemberContext = Depends(get_current_member_context),
    db: Session = Depends(get_db),
):
    try:
        session = switch_acting_member(db, context.session.session_token, payload.acting_member_id)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SessionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    refreshed_context = CurrentMemberContext(
        session=session,
        account=session.account,
        bound_member=session.account.member,
        acting_member=session.acting_member,
    )
    return _build_session_context_response(db, refreshed_context)


@router.get(
    "/available-identities",
    response_model=schemas_auth.AuthAvailableIdentitiesResponse,
)
def available_identities(
    context: CurrentMemberContext = Depends(get_current_member_context),
    db: Session = Depends(get_db),
):
    return _build_available_identities_response(db, context)
