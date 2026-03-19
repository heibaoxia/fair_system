from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app import models

PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 600_000
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
DEFAULT_SESSION_TTL = timedelta(days=7)
DEFAULT_EMAIL_VERIFICATION_TTL = timedelta(hours=24)
INVALID_CREDENTIALS_MESSAGE = "Invalid login credentials."


class AuthServiceError(Exception):
    pass


class AuthenticationError(AuthServiceError):
    pass


class SessionError(AuthServiceError):
    pass


class AuthorizationError(AuthServiceError):
    pass


class EmailVerificationError(AuthServiceError):
    pass


@dataclass(frozen=True)
class VerificationTokenIssue:
    account_id: int
    email: str
    expires_at: datetime
    token: str


def _now() -> datetime:
    return datetime.now()


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


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


def _is_email_style_identifier(value: str) -> bool:
    return "@" in value


def _hash_password(password: str, *, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    if not password:
        raise ValueError("Password must not be empty.")

    salt = salt or secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return "$".join(
        [
            PASSWORD_HASH_SCHEME,
            str(iterations),
            _encode_bytes(salt),
            _encode_bytes(derived_key),
        ]
    )


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iteration_text, salt_text, expected_text = stored_hash.split("$", 3)
        if scheme != PASSWORD_HASH_SCHEME:
            return False
        iterations = int(iteration_text)
        salt = _decode_bytes(salt_text)
        expected = _decode_bytes(expected_text)
    except (TypeError, ValueError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected)


def _hash_verification_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_DUMMY_PASSWORD_HASH = _hash_password("dummy-password-for-timing-protection")


def _get_member_or_error(db: Session, member_id: int) -> models.Member:
    member = db.query(models.Member).filter(models.Member.id == member_id).first()
    if member is None:
        raise ValueError("Member does not exist.")
    if not member.is_active:
        raise ValueError("Member is inactive.")
    return member


def _load_account(db: Session, account_id: int) -> models.Account | None:
    return (
        db.query(models.Account)
        .options(joinedload(models.Account.member))
        .filter(models.Account.id == account_id)
        .first()
    )


def _load_account_by_login_id(db: Session, login_id: str) -> models.Account | None:
    normalized_login_id = _normalize_login_lookup(login_id)
    if _is_email_style_identifier(normalized_login_id):
        criterion = func.lower(models.Account.login_id) == normalized_login_id
    else:
        criterion = models.Account.login_id == normalized_login_id
    return (
        db.query(models.Account)
        .options(joinedload(models.Account.member))
        .filter(criterion)
        .first()
    )


def _load_session_record(db: Session, session_token: str) -> models.AuthSession | None:
    return (
        db.query(models.AuthSession)
        .options(
            joinedload(models.AuthSession.account).joinedload(models.Account.member),
            joinedload(models.AuthSession.acting_member),
        )
        .filter(models.AuthSession.session_token == session_token)
        .first()
    )


def _load_verification_record(db: Session, token_hash: str) -> models.EmailVerificationToken | None:
    return (
        db.query(models.EmailVerificationToken)
        .options(joinedload(models.EmailVerificationToken.account).joinedload(models.Account.member))
        .filter(models.EmailVerificationToken.token_hash == token_hash)
        .first()
    )


def _regular_account_member_is_valid(account: models.Account | None) -> bool:
    if account is None:
        return False
    if account.is_super_account:
        return True
    if account.member_id is None or account.member is None:
        return False
    if not account.member.is_active:
        return False
    if bool(getattr(account.member, "is_virtual_identity", False)):
        return False
    return True


def _get_current_authoritative_member_email(account: models.Account) -> str:
    if not _regular_account_member_is_valid(account):
        raise ValueError("Bound member is not eligible for email verification.")
    authoritative_email = _normalize_email(account.member.email if account.member is not None else None)
    if authoritative_email is None:
        raise ValueError("Member must have an email for verification.")
    return authoritative_email


def register_account(
    db: Session,
    *,
    login_id: str,
    password: str,
    email: str | None = None,
    member_id: int | None = None,
    is_super_account: bool = False,
    is_active: bool = True,
) -> models.Account:
    normalized_login_id = login_id.strip()
    if not normalized_login_id:
        raise ValueError("login_id must not be empty.")
    if is_super_account and member_id is not None:
        raise ValueError("Super accounts cannot be bound to a member.")
    if not is_super_account and member_id is None:
        raise ValueError("Regular accounts must be bound to a member.")

    if _load_account_by_login_id(db, normalized_login_id) is not None:
        raise ValueError("login_id is already registered.")

    normalized_email = _normalize_email(email)

    member: models.Member | None = None
    if member_id is not None:
        member = _get_member_or_error(db, member_id)
        if bool(getattr(member, "is_virtual_identity", False)):
            raise ValueError("Virtual identities cannot be bound to login accounts.")
        if (
            db.query(models.Account)
            .filter(models.Account.member_id == member_id)
            .first()
            is not None
        ):
            raise ValueError("Member already has an account.")

    account_email: str | None = normalized_email
    registration_status = "active"
    email_verified_at = _now()

    if not is_super_account:
        authoritative_email = _normalize_email(None if member is None else member.email)
        if authoritative_email is None:
            raise ValueError("Member must have an email for registration.")
        if normalized_email is None:
            raise ValueError("email must not be empty.")
        if authoritative_email != normalized_email:
            raise ValueError("Registration email must match member email.")
        account_email = authoritative_email
        registration_status = "pending_verification"
        email_verified_at = None

    if account_email is not None:
        duplicate_email = (
            db.query(models.Account)
            .filter(func.lower(models.Account.email) == account_email)
            .first()
        )
        if duplicate_email is not None:
            raise ValueError("email is already registered.")

    account = models.Account(
        login_id=normalized_login_id,
        password_hash=_hash_password(password),
        email=account_email,
        email_verified_at=email_verified_at,
        registration_status=registration_status,
        member_id=member_id,
        is_super_account=is_super_account,
        is_active=is_active,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def register_public_account(
    db: Session,
    *,
    email: str,
    password: str,
    username: str,
    gender: str,
) -> models.Account:
    normalized_email = _normalize_email(email)
    if normalized_email is None:
        raise ValueError("email must not be empty.")

    normalized_username = username.strip()
    if not normalized_username:
        raise ValueError("username must not be empty.")

    normalized_gender = gender.strip().lower()
    if normalized_gender not in {"male", "female", "private"}:
        raise ValueError("gender is invalid.")

    if _load_account_by_login_id(db, normalized_email) is not None:
        raise ValueError("email is already registered.")

    duplicate_member = (
        db.query(models.Member)
        .filter(func.lower(models.Member.email) == normalized_email)
        .first()
    )
    if duplicate_member is not None:
        raise ValueError("email is already registered.")

    duplicate_account_email = (
        db.query(models.Account)
        .filter(func.lower(models.Account.email) == normalized_email)
        .first()
    )
    if duplicate_account_email is not None:
        raise ValueError("email is already registered.")

    member = models.Member(
        name=normalized_username,
        email=normalized_email,
        gender=normalized_gender,
        public_email=False,
        public_tel=False,
        is_active=True,
    )
    account = models.Account(
        login_id=normalized_email,
        password_hash=_hash_password(password),
        email=normalized_email,
        email_verified_at=None,
        registration_status="pending_verification",
        is_super_account=False,
        is_active=True,
        member=member,
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("email is already registered.") from exc
    db.refresh(account)
    return account


def issue_email_verification_token(
    db: Session,
    *,
    account_id: int,
    ttl: timedelta | None = DEFAULT_EMAIL_VERIFICATION_TTL,
) -> VerificationTokenIssue:
    account = _load_account(db, account_id)
    if account is None:
        raise ValueError("Account does not exist.")
    if account.is_super_account:
        raise ValueError("Super accounts do not use email verification.")
    if not account.is_active:
        raise ValueError("Account is inactive.")
    authoritative_email = _get_current_authoritative_member_email(account)
    if account.registration_status == "active" and account.email_verified_at is not None:
        raise ValueError("Account is already verified.")
    if account.email != authoritative_email:
        account.email = authoritative_email

    ttl = ttl if ttl is not None else DEFAULT_EMAIL_VERIFICATION_TTL
    now = _now()
    db.query(models.EmailVerificationToken).filter(
        models.EmailVerificationToken.account_id == account.id,
        models.EmailVerificationToken.consumed_at.is_(None),
    ).delete(synchronize_session=False)

    plaintext_token = secrets.token_urlsafe(32)
    verification_token = models.EmailVerificationToken(
        account_id=account.id,
        email=authoritative_email,
        token_hash=_hash_verification_token(plaintext_token),
        expires_at=now + ttl,
        created_at=now,
    )
    db.add(verification_token)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("email is already registered.") from exc
    db.refresh(verification_token)
    return VerificationTokenIssue(
        account_id=account.id,
        email=authoritative_email,
        expires_at=verification_token.expires_at,
        token=plaintext_token,
    )


def resend_email_verification(db: Session, *, login_id: str) -> VerificationTokenIssue:
    account = _load_account_by_login_id(db, login_id)
    if account is None:
        raise ValueError("Account does not exist.")
    if account.is_super_account:
        raise ValueError("Super accounts do not use email verification.")
    if account.registration_status == "active" and account.email_verified_at is not None:
        raise ValueError("Account is already verified.")
    return issue_email_verification_token(db, account_id=account.id)


def verify_email_token(db: Session, token: str) -> models.Account:
    normalized_token = token.strip()
    if not normalized_token:
        raise EmailVerificationError("Verification token is invalid.")

    verification = _load_verification_record(db, _hash_verification_token(normalized_token))
    if verification is None:
        raise EmailVerificationError("Verification token is invalid.")
    if verification.consumed_at is not None:
        raise EmailVerificationError("Verification token has already been used.")

    now = _now()
    if verification.expires_at <= now:
        raise EmailVerificationError("Verification token has expired.")

    account = verification.account
    if account is None or not account.is_active:
        raise EmailVerificationError("Verification token is invalid.")
    if account.is_super_account:
        raise EmailVerificationError("Verification token is invalid.")
    if not _regular_account_member_is_valid(account):
        raise EmailVerificationError("Verification token is invalid.")
    authoritative_email = _normalize_email(account.member.email if account.member is not None else None)
    if authoritative_email is None:
        raise EmailVerificationError("Verification token is invalid.")
    account_email = _normalize_email(account.email)
    verification_email = _normalize_email(verification.email)
    if account_email != authoritative_email or verification_email != authoritative_email:
        raise EmailVerificationError("Verification token is invalid.")

    verification.consumed_at = now
    account.email_verified_at = now
    account.registration_status = "active"
    db.commit()
    refreshed_account = _load_account(db, account.id)
    if refreshed_account is None:
        raise EmailVerificationError("Verification token is invalid.")
    return refreshed_account


def authenticate_account(db: Session, *, login_id: str, password: str) -> models.Account:
    account = _load_account_by_login_id(db, login_id)

    stored_hash = account.password_hash if account is not None else _DUMMY_PASSWORD_HASH
    password_matches = _verify_password(password, stored_hash)

    if account is None or not account.is_active or not password_matches:
        raise AuthenticationError(INVALID_CREDENTIALS_MESSAGE)
    if account.registration_status != "active" or account.email_verified_at is None:
        raise AuthenticationError(INVALID_CREDENTIALS_MESSAGE)
    if not _regular_account_member_is_valid(account):
        raise AuthenticationError(INVALID_CREDENTIALS_MESSAGE)

    return account


def create_session(
    db: Session,
    *,
    account_id: int,
    ttl: timedelta = DEFAULT_SESSION_TTL,
    acting_member_id: int | None = None,
) -> models.AuthSession:
    account = _load_account(db, account_id)
    if (
        account is None
        or not account.is_active
        or account.registration_status != "active"
        or account.email_verified_at is None
    ):
        raise AuthenticationError(INVALID_CREDENTIALS_MESSAGE)

    resolved_acting_member_id: int | None
    if account.is_super_account:
        if acting_member_id is not None:
            _get_member_or_error(db, acting_member_id)
        resolved_acting_member_id = acting_member_id
    else:
        if not _regular_account_member_is_valid(account):
            raise AuthenticationError(INVALID_CREDENTIALS_MESSAGE)
        if acting_member_id is not None and acting_member_id != account.member_id:
            raise AuthorizationError("Regular accounts cannot switch acting members.")
        resolved_acting_member_id = account.member_id

    now = _now()
    session = models.AuthSession(
        session_token=secrets.token_urlsafe(32),
        account_id=account.id,
        acting_member_id=resolved_acting_member_id,
        expires_at=now + ttl,
        created_at=now,
        last_seen_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _load_session_record(db, session.session_token) or session


def load_session(db: Session, session_token: str) -> models.AuthSession | None:
    if not session_token:
        return None

    session = _load_session_record(db, session_token)
    if session is None:
        return None

    now = _now()
    if (
        session.expires_at <= now
        or not session.account.is_active
        or session.account.registration_status != "active"
        or session.account.email_verified_at is None
        or not _regular_account_member_is_valid(session.account)
        or (
            session.account.is_super_account
            and session.acting_member is not None
            and not session.acting_member.is_active
        )
    ):
        db.delete(session)
        db.commit()
        return None

    session.last_seen_at = now
    db.commit()
    return _load_session_record(db, session_token)


def logout_session(db: Session, session_token: str) -> bool:
    if not session_token:
        return False

    session = (
        db.query(models.AuthSession)
        .filter(models.AuthSession.session_token == session_token)
        .first()
    )
    if session is None:
        return False

    db.delete(session)
    db.commit()
    return True


def switch_acting_member(
    db: Session,
    session_token: str,
    acting_member_id: int | None,
) -> models.AuthSession:
    session = load_session(db, session_token)
    if session is None:
        raise SessionError("Session is invalid or expired.")

    if not session.account.is_super_account:
        raise AuthorizationError("Regular accounts cannot switch acting members.")

    if acting_member_id is None:
        session.acting_member_id = session.account.member_id
    else:
        _get_member_or_error(db, acting_member_id)
        session.acting_member_id = acting_member_id

    session.last_seen_at = _now()
    db.commit()
    return _load_session_record(db, session_token) or session


__all__ = [
    "AuthServiceError",
    "AuthenticationError",
    "AuthorizationError",
    "DEFAULT_EMAIL_VERIFICATION_TTL",
    "DEFAULT_SESSION_TTL",
    "EmailVerificationError",
    "INVALID_CREDENTIALS_MESSAGE",
    "SessionError",
    "VerificationTokenIssue",
    "authenticate_account",
    "create_session",
    "issue_email_verification_token",
    "load_session",
    "logout_session",
    "register_public_account",
    "register_account",
    "resend_email_verification",
    "switch_acting_member",
    "verify_email_token",
]
