import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

from app import models
from app.database import Base
from app.services.auth_service import (
    AuthenticationError,
    authenticate_account,
    create_session,
    register_account,
)
import seed_demo_data


def test_seed_members_without_email_become_virtual_and_cleanup_bound_auth_records(
    tmp_path,
    monkeypatch,
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'seed.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    member_definitions = [dict(item) for item in seed_demo_data.MEMBER_DEFINITIONS]
    member_definitions[2].pop("email", None)

    monkeypatch.setattr(seed_demo_data, "engine", engine)
    monkeypatch.setattr(seed_demo_data, "SessionLocal", testing_session_local)
    monkeypatch.setattr(seed_demo_data, "MEMBER_DEFINITIONS", member_definitions)

    seed_demo_data.ensure_base_schema()

    db = testing_session_local()
    try:
        legacy_member = models.Member(
            name="赵宁",
            tel="13800001003",
            email="legacy-zhaoning@example.com",
            is_active=True,
            is_virtual_identity=False,
        )
        db.add(legacy_member)
        db.commit()
        db.refresh(legacy_member)

        legacy_account = register_account(
            db,
            login_id="legacy-zhaoning",
            password="secret123",
            email=legacy_member.email,
            member_id=legacy_member.id,
        )
        legacy_account.registration_status = "active"
        legacy_account.email_verified_at = datetime.now()
        db.commit()
        legacy_session = create_session(db, account_id=legacy_account.id)
        legacy_token = models.EmailVerificationToken(
            account_id=legacy_account.id,
            email="legacy-zhaoning@example.com",
            token_hash="legacy-token-hash",
            expires_at=legacy_session.expires_at,
        )
        db.add(legacy_token)
        db.commit()

        legacy_account_id = legacy_account.id
    finally:
        db.close()

    try:
        seed_demo_data.seed_demo_data()

        db = testing_session_local()
        try:
            no_email_member = db.query(models.Member).filter_by(tel="13800001003").one()

            assert no_email_member.email is None
            assert no_email_member.is_virtual_identity is True
            assert (
                db.query(models.Account)
                .filter(models.Account.member_id == no_email_member.id)
                .count()
                == 0
            )
            assert (
                db.query(models.AuthSession)
                .filter(models.AuthSession.account_id == legacy_account_id)
                .count()
                == 0
            )
            assert (
                db.query(models.EmailVerificationToken)
                .filter(models.EmailVerificationToken.account_id == legacy_account_id)
                .count()
                == 0
            )

            with pytest.raises(
                ValueError,
                match="虚拟身份不能绑定登录账户。",
            ):
                register_account(
                    db,
                    login_id="zhaoning",
                    password="secret123",
                    member_id=no_email_member.id,
                )
        finally:
            db.close()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_seed_super_account_is_fixed_to_god_with_password_888888(
    tmp_path,
    monkeypatch,
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'seed-super.db'}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(seed_demo_data, "engine", engine)
    monkeypatch.setattr(seed_demo_data, "SessionLocal", testing_session_local)

    seed_demo_data.ensure_base_schema()

    db = testing_session_local()
    try:
        legacy_super = register_account(
            db,
            login_id="god",
            password="old-password",
            is_super_account=True,
        )
        legacy_super.registration_status = "active"
        db.commit()
        legacy_super_id = legacy_super.id
    finally:
        db.close()

    try:
        seed_demo_data.seed_demo_data()

        db = testing_session_local()
        try:
            super_accounts = (
                db.query(models.Account)
                .filter(models.Account.is_super_account.is_(True))
                .all()
            )

            assert [account.login_id for account in super_accounts] == ["god"]
            assert super_accounts[0].id == legacy_super_id
            assert super_accounts[0].member_id is None
            assert super_accounts[0].registration_status == "active"

            authenticated = authenticate_account(
                db,
                login_id="god",
                password="888888",
            )
            assert authenticated.id == legacy_super_id

            with pytest.raises(AuthenticationError):
                authenticate_account(
                    db,
                    login_id="god",
                    password="old-password",
                )

            assert (
                db.query(models.Account)
                .filter(models.Account.login_id == "seed_super_admin")
                .count()
                == 0
            )
        finally:
            db.close()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
