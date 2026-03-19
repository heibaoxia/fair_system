from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.services import auth_service as auth_service_module
from app.services.auth_service import (
    AuthenticationError,
    AuthorizationError,
    EmailVerificationError,
    authenticate_account,
    create_session,
    issue_email_verification_token,
    load_session,
    logout_session,
    register_public_account,
    register_account,
    resend_email_verification,
    switch_acting_member,
    verify_email_token,
)
from app.services.schema_bootstrap import bootstrap_schema


def build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    bootstrap_schema(engine)
    return engine, testing_session_local()


def seed_members(db):
    owner = models.Member(name="Owner", tel="13800003001", email="owner@example.com", is_active=True)
    teammate = models.Member(name="Teammate", tel="13800003002", email="teammate@example.com", is_active=True)
    db.add_all([owner, teammate])
    db.commit()
    db.refresh(owner)
    db.refresh(teammate)
    return owner, teammate


def register_and_verify_regular_account(db, *, login_id: str, password: str, member: models.Member) -> models.Account:
    account = register_account(
        db,
        login_id=login_id,
        password=password,
        member_id=member.id,
        email=member.email,
    )
    issue = issue_email_verification_token(db, account_id=account.id)
    verify_email_token(db, issue.token)
    return account


def test_register_public_account_creates_member_pending_verification_uses_email_login_id_and_allows_duplicate_usernames():
    engine, db = build_session()
    try:
        first_account = register_public_account(
            db,
            email="  Shared.User@Example.com ",
            password="correct horse battery staple",
            username="Shared User",
            gender="female",
        )
        first_member = db.query(models.Member).filter(models.Member.id == first_account.member_id).one()

        assert first_account.login_id == "shared.user@example.com"
        assert first_account.email == "shared.user@example.com"
        assert first_account.registration_status == "pending_verification"
        assert first_account.email_verified_at is None
        assert first_account.is_super_account is False
        assert first_member.name == "Shared User"
        assert first_member.gender == "female"
        assert first_member.email == "shared.user@example.com"
        assert first_member.public_email is False
        assert first_member.public_tel is False

        second_account = register_public_account(
            db,
            email="shared.user.2@example.com",
            password="another correct horse battery staple",
            username="Shared User",
            gender="private",
        )
        second_member = db.query(models.Member).filter(models.Member.id == second_account.member_id).one()

        assert second_account.login_id == "shared.user.2@example.com"
        assert second_member.name == first_member.name
        assert second_member.id != first_member.id

        with pytest.raises(AuthenticationError):
            authenticate_account(
                db,
                login_id="shared.user@example.com",
                password="correct horse battery staple",
            )
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_register_public_account_does_not_delegate_to_internal_bound_member_helper(monkeypatch):
    engine, db = build_session()
    try:
        def fail_if_called(*args, **kwargs):
            raise AssertionError("register_account should not be used for public registration")

        monkeypatch.setattr(auth_service_module, "register_account", fail_if_called)

        account = register_public_account(
            db,
            email="direct.path@example.com",
            password="correct horse battery staple",
            username="Direct Path",
            gender="male",
        )

        member = db.query(models.Member).filter(models.Member.id == account.member_id).one()
        assert account.login_id == "direct.path@example.com"
        assert account.email == "direct.path@example.com"
        assert member.name == "Direct Path"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_register_account_internal_path_hashes_password_requires_member_email_match_and_starts_pending_verification():
    engine, db = build_session()
    try:
        owner, teammate = seed_members(db)

        account = register_account(
            db,
            login_id="owner",
            password="correct horse battery staple",
            member_id=owner.id,
            email="owner@example.com",
        )

        assert account.password_hash != "correct horse battery staple"
        assert "correct horse battery staple" not in account.password_hash
        assert account.password_hash.startswith("pbkdf2_sha256$")
        assert account.email == "owner@example.com"
        assert account.registration_status == "pending_verification"
        assert account.email_verified_at is None

        with pytest.raises(AuthenticationError) as pending_login:
            authenticate_account(
                db,
                login_id="owner",
                password="correct horse battery staple",
            )

        with pytest.raises(AuthenticationError) as missing_account:
            authenticate_account(db, login_id="missing", password="wrong password")

        with pytest.raises(ValueError) as mismatch:
            register_account(
                db,
                login_id="teammate",
                password="another-secret",
                member_id=teammate.id,
                email="other@example.com",
            )

        assert str(pending_login.value) == str(missing_account.value)
        assert "match member email" in str(mismatch.value).lower()
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_email_verification_token_supports_hash_only_verify_expiry_single_use_and_resend():
    engine, db = build_session()
    try:
        owner, teammate = seed_members(db)

        account = register_account(
            db,
            login_id="owner",
            password="secret123",
            member_id=owner.id,
            email=owner.email,
        )

        first_issue = issue_email_verification_token(db, account_id=account.id)
        stored_token = (
            db.query(models.EmailVerificationToken)
            .filter(models.EmailVerificationToken.account_id == account.id)
            .one()
        )
        assert stored_token.token_hash != first_issue.token
        assert first_issue.token not in stored_token.token_hash

        verified_account = verify_email_token(db, first_issue.token)
        assert verified_account.id == account.id
        assert verified_account.registration_status == "active"
        assert verified_account.email_verified_at is not None

        with pytest.raises(EmailVerificationError) as reused:
            verify_email_token(db, first_issue.token)

        assert "already been used" in str(reused.value).lower()

        expired_account = register_account(
            db,
            login_id="teammate",
            password="secret456",
            member_id=teammate.id,
            email=teammate.email,
        )
        expired_issue = issue_email_verification_token(
            db,
            account_id=expired_account.id,
            ttl=timedelta(seconds=-1),
        )

        with pytest.raises(EmailVerificationError) as expired:
            verify_email_token(db, expired_issue.token)

        assert "expired" in str(expired.value).lower()

        resend_member = models.Member(
            name="Resend User",
            tel="13800003003",
            email="resend@example.com",
            is_active=True,
        )
        db.add(resend_member)
        db.commit()
        db.refresh(resend_member)

        resend_account = register_account(
            db,
            login_id="resend-user",
            password="secret789",
            member_id=resend_member.id,
            email=resend_member.email,
        )
        original_issue = issue_email_verification_token(db, account_id=resend_account.id)
        replacement_issue = resend_email_verification(db, login_id="resend-user")

        assert replacement_issue.token != original_issue.token
        outstanding_tokens = (
            db.query(models.EmailVerificationToken)
            .filter(models.EmailVerificationToken.account_id == resend_account.id)
            .all()
        )
        assert len(outstanding_tokens) == 1

        with pytest.raises(EmailVerificationError) as invalidated:
            verify_email_token(db, original_issue.token)

        assert "invalid" in str(invalidated.value).lower()

        resent_verified_account = verify_email_token(db, replacement_issue.token)
        assert resent_verified_account.id == resend_account.id
        assert resent_verified_account.registration_status == "active"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_resend_realigns_pending_account_email_to_member_email_and_stale_token_cannot_verify():
    engine, db = build_session()
    try:
        owner, _ = seed_members(db)

        account = register_account(
            db,
            login_id="owner",
            password="secret123",
            member_id=owner.id,
            email=owner.email,
        )
        original_issue = issue_email_verification_token(db, account_id=account.id)

        owner.email = "owner-new@example.com"
        db.commit()

        replacement_issue = resend_email_verification(db, login_id="owner")
        refreshed_account = db.query(models.Account).filter(models.Account.id == account.id).one()

        assert refreshed_account.email == "owner-new@example.com"
        assert replacement_issue.email == "owner-new@example.com"
        assert replacement_issue.token != original_issue.token

        with pytest.raises(EmailVerificationError):
            verify_email_token(db, original_issue.token)

        verified_account = verify_email_token(db, replacement_issue.token)
        assert verified_account.email == "owner-new@example.com"
        assert verified_account.registration_status == "active"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_resend_email_verification_handles_email_realign_collision_as_controlled_error():
    engine, db = build_session()
    try:
        owner, teammate = seed_members(db)
        register_account(
            db,
            login_id="owner",
            password="secret123",
            member_id=owner.id,
            email=owner.email,
        )
        register_and_verify_regular_account(
            db,
            login_id="teammate",
            password="secret456",
            member=teammate,
        )
        register_account(
            db,
            login_id="admin",
            password="super-secret",
            email="collision@example.com",
            is_super_account=True,
        )

        owner.email = "collision@example.com"
        db.commit()

        with pytest.raises(ValueError) as exc_info:
            resend_email_verification(db, login_id="owner")

        assert "email is already registered" in str(exc_info.value).lower()
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_email_backed_login_and_resend_are_case_insensitive():
    engine, db = build_session()
    try:
        account = register_public_account(
            db,
            email="Case.Mixed@example.com",
            password="secret123",
            username="Case Mixed",
            gender="private",
        )
        issue = issue_email_verification_token(db, account_id=account.id)
        replacement_issue = resend_email_verification(db, login_id="CASE.MIXED@EXAMPLE.COM")

        assert replacement_issue.account_id == account.id
        assert replacement_issue.token != issue.token

        verify_email_token(db, replacement_issue.token)
        authenticated = authenticate_account(
            db,
            login_id="  CASE.MIXED@EXAMPLE.COM  ",
            password="secret123",
        )
        assert authenticated.id == account.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_legacy_mixed_case_email_account_authenticates_and_resends_with_different_case_input():
    engine, db = build_session()
    try:
        owner, _ = seed_members(db)
        owner.email = "Legacy.Mixed@example.com"
        db.commit()

        account = register_account(
            db,
            login_id="Legacy.Mixed@example.com",
            password="secret123",
            member_id=owner.id,
            email="Legacy.Mixed@example.com",
        )
        issue = issue_email_verification_token(db, account_id=account.id)

        stored_account = db.query(models.Account).filter(models.Account.id == account.id).one()
        stored_account.login_id = "Legacy.Mixed@example.com"
        stored_account.email = "Legacy.Mixed@example.com"
        db.commit()

        replacement_issue = resend_email_verification(db, login_id="legacy.mixed@EXAMPLE.com")
        verify_email_token(db, replacement_issue.token)
        authenticated = authenticate_account(
            db,
            login_id=" LEGACY.MIXED@example.COM ",
            password="secret123",
        )

        assert replacement_issue.account_id == account.id
        assert replacement_issue.token != issue.token
        assert authenticated.id == account.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_public_registration_rejects_legacy_email_duplicates_that_only_differ_by_case():
    engine, db = build_session()
    try:
        owner, _ = seed_members(db)
        owner.email = "Legacy.Duplicate@example.com"
        db.commit()

        account = register_account(
            db,
            login_id="Legacy.Duplicate@example.com",
            password="secret123",
            member_id=owner.id,
            email="Legacy.Duplicate@example.com",
        )
        stored_account = db.query(models.Account).filter(models.Account.id == account.id).one()
        stored_account.login_id = "Legacy.Duplicate@example.com"
        stored_account.email = "Legacy.Duplicate@example.com"
        db.commit()

        with pytest.raises(ValueError) as exc_info:
            register_public_account(
                db,
                email="legacy.duplicate@EXAMPLE.com",
                password="another-secret123",
                username="Duplicate Attempt",
                gender="private",
            )

        assert "already registered" in str(exc_info.value).lower()
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_non_email_super_account_login_id_remains_case_sensitive():
    engine, db = build_session()
    try:
        account = register_account(
            db,
            login_id="AdminRoot",
            password="super-secret",
            is_super_account=True,
        )
        authenticated = authenticate_account(db, login_id="AdminRoot", password="super-secret")
        assert authenticated.id == account.id

        with pytest.raises(AuthenticationError):
            authenticate_account(db, login_id="adminroot", password="super-secret")
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_session_lifecycle_is_persisted_server_side_for_verified_accounts():
    engine, db = build_session()
    try:
        owner, _ = seed_members(db)
        account = register_and_verify_regular_account(
            db,
            login_id="owner",
            password="secret123",
            member=owner,
        )

        created_session = create_session(db, account_id=account.id, ttl=timedelta(hours=8))

        assert created_session.session_token
        assert created_session.acting_member_id == owner.id

        loaded_session = load_session(db, created_session.session_token)
        assert loaded_session is not None
        assert loaded_session.id == created_session.id
        assert loaded_session.account_id == account.id
        assert loaded_session.acting_member_id == owner.id

        assert logout_session(db, created_session.session_token) is True
        assert load_session(db, created_session.session_token) is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_super_account_session_is_cleared_when_acting_member_becomes_inactive():
    engine, db = build_session()
    try:
        owner, teammate = seed_members(db)
        super_account = register_account(
            db,
            login_id="admin",
            password="super-secret",
            is_super_account=True,
        )
        session = create_session(db, account_id=super_account.id, acting_member_id=teammate.id)

        loaded_session = load_session(db, session.session_token)
        assert loaded_session is not None
        assert loaded_session.acting_member_id == teammate.id

        teammate.is_active = False
        db.commit()

        assert load_session(db, session.session_token) is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_regular_account_rejects_inactive_or_virtual_member_after_registration_and_clears_session():
    engine, db = build_session()
    try:
        owner, _ = seed_members(db)
        account = register_and_verify_regular_account(
            db,
            login_id="owner",
            password="secret123",
            member=owner,
        )

        owner.is_active = False
        db.commit()

        with pytest.raises(AuthenticationError):
            authenticate_account(db, login_id="owner", password="secret123")

        with pytest.raises(AuthenticationError):
            create_session(db, account_id=account.id)

        owner.is_active = True
        db.commit()

        session = create_session(db, account_id=account.id)
        assert load_session(db, session.session_token) is not None

        owner.is_virtual_identity = True
        db.commit()

        assert load_session(db, session.session_token) is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_only_super_accounts_can_switch_acting_member():
    engine, db = build_session()
    try:
        owner, teammate = seed_members(db)
        regular_account = register_and_verify_regular_account(
            db,
            login_id="owner",
            password="secret123",
            member=owner,
        )
        super_account = register_account(
            db,
            login_id="admin",
            password="super-secret",
            is_super_account=True,
        )

        regular_session = create_session(db, account_id=regular_account.id)
        super_session = create_session(db, account_id=super_account.id)

        with pytest.raises(AuthorizationError):
            switch_acting_member(db, regular_session.session_token, teammate.id)

        unchanged_regular_session = load_session(db, regular_session.session_token)
        assert unchanged_regular_session is not None
        assert unchanged_regular_session.acting_member_id == owner.id

        switched_session = switch_acting_member(db, super_session.session_token, teammate.id)
        assert switched_session.acting_member_id == teammate.id

        refreshed_super_session = load_session(db, super_session.session_token)
        assert refreshed_super_session is not None
        assert refreshed_super_session.acting_member_id == teammate.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_super_account_can_switch_to_virtual_identity():
    engine, db = build_session()
    try:
        virtual_member = models.Member(
            name="Virtual QA",
            tel="13800005001",
            is_active=True,
            is_virtual_identity=True,
        )
        db.add(virtual_member)
        db.commit()
        db.refresh(virtual_member)

        super_account = register_account(
            db,
            login_id="admin",
            password="super-secret",
            is_super_account=True,
        )
        session = create_session(db, account_id=super_account.id)

        switched = switch_acting_member(db, session.session_token, virtual_member.id)
        assert switched.acting_member_id == virtual_member.id

        refreshed_session = load_session(db, session.session_token)
        assert refreshed_session is not None
        assert refreshed_session.acting_member_id == virtual_member.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_virtual_member_accounts_cannot_authenticate():
    engine, db = build_session()
    try:
        owner, _ = seed_members(db)
        register_and_verify_regular_account(
            db,
            login_id="owner",
            password="secret123",
            member=owner,
        )
        owner.is_virtual_identity = True
        db.commit()

        with pytest.raises(AuthenticationError):
            authenticate_account(db, login_id="owner", password="secret123")
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
