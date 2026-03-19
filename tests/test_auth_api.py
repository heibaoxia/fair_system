from urllib.parse import parse_qs, urlparse

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.api import auth, dependencies
from app.api.auth import router as auth_router
from app.api.dependencies import (
    get_current_member_context,
    require_project_member,
    require_project_pm,
)
from app.database import Base
from app.main import app as main_app
from app.services.auth_service import (
    INVALID_CREDENTIALS_MESSAGE,
    issue_email_verification_token,
    register_account,
    verify_email_token,
)
from app.services.email_sender import EmailDeliveryError, EmailSenderConfigurationError, VerificationEmailMessage
from app.services.schema_bootstrap import bootstrap_schema


class RecordingEmailSender:
    def __init__(self):
        self.messages: list[VerificationEmailMessage] = []

    def send_verification_email(self, message: VerificationEmailMessage) -> None:
        self.messages.append(message)


class FailingEmailSender:
    def send_verification_email(self, message: VerificationEmailMessage) -> None:
        raise EmailDeliveryError("delivery failed")


def build_test_app():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    bootstrap_schema(engine)

    app = FastAPI()
    app.include_router(auth_router)

    email_sender = RecordingEmailSender()

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = override_get_db
    app.dependency_overrides[auth.get_email_sender] = lambda: email_sender
    app.dependency_overrides[auth.get_verification_base_url] = lambda: "https://example.test/auth/verify-email"
    app.state.email_sender = email_sender
    app.state.verification_base_url = "https://example.test/auth/verify-email"

    @app.get("/protected/context")
    def protected_context(
        member_id: int | None = None,
        context=Depends(get_current_member_context),
    ):
        return {
            "query_member_id": member_id,
            "acting_member_id": None if context.acting_member is None else context.acting_member.id,
            "account_id": context.account.id,
        }

    @app.get("/protected/projects/{project_id}/member")
    def protected_project_member(context=Depends(require_project_member)):
        return {
            "acting_member_id": None if context.acting_member is None else context.acting_member.id,
            "is_super_account": context.account.is_super_account,
        }

    @app.get("/protected/projects/{project_id}/pm")
    def protected_project_pm(context=Depends(require_project_pm)):
        return {
            "acting_member_id": None if context.acting_member is None else context.acting_member.id,
            "is_super_account": context.account.is_super_account,
        }

    return app, engine, testing_session_local, email_sender


def seed_world(testing_session_local):
    db = testing_session_local()
    try:
        owner = models.Member(name="Owner", tel="13800004001", email="owner@example.com", is_active=True)
        teammate = models.Member(name="Teammate", tel="13800004002", email="teammate@example.com", is_active=True)
        outsider = models.Member(name="Outsider", tel="13800004003", email="outsider@example.com", is_active=True)
        virtual = models.Member(
            name="Virtual QA",
            tel="13800004004",
            is_active=True,
            is_virtual_identity=True,
        )
        db.add_all([owner, teammate, outsider, virtual])
        db.flush()

        project = models.Project(
            name="Auth Project",
            description="",
            created_by=owner.id,
        )
        project.members.extend([owner, teammate])
        db.add(project)
        db.commit()

        db.refresh(owner)
        db.refresh(teammate)
        db.refresh(outsider)
        db.refresh(virtual)
        db.refresh(project)
        return {
            "owner": owner,
            "teammate": teammate,
            "outsider": outsider,
            "virtual": virtual,
            "project": project,
        }
    finally:
        db.close()


def create_verified_regular_account(testing_session_local, *, login_id: str, password: str, member: models.Member):
    db = testing_session_local()
    try:
        account = register_account(
            db,
            login_id=login_id,
            password=password,
            member_id=member.id,
            email=member.email,
        )
        issue = issue_email_verification_token(db, account_id=account.id)
        verify_email_token(db, issue.token)
    finally:
        db.close()


def create_super_account(testing_session_local, *, login_id: str, password: str):
    db = testing_session_local()
    try:
        register_account(db, login_id=login_id, password=password, is_super_account=True)
    finally:
        db.close()


def extract_token(message: VerificationEmailMessage) -> str:
    query = parse_qs(urlparse(message.verification_url).query)
    return query["token"][0]


def test_register_returns_pending_verification_without_session_and_emails_token():
    app, engine, testing_session_local, email_sender = build_test_app()
    client = TestClient(app)

    try:
        assert any(getattr(route, "path", None) == "/auth/me" for route in main_app.routes)

        me_response = client.get("/auth/me")
        assert me_response.status_code == 401

        register_response = client.post(
            "/auth/register",
            json={
                "email": "  Owner.Public@Example.com ",
                "password": "owner-password",
                "username": "Owner Public",
                "gender": "female",
            },
        )
        assert register_response.status_code == 201
        assert "session_token=" not in register_response.headers.get("set-cookie", "")

        payload = register_response.json()
        assert payload["authenticated"] is False
        assert payload["session"] is None
        assert payload["identity_scope"] == "own_only"
        assert payload["account"]["login_id"] == "owner.public@example.com"
        assert payload["account"]["registration_status"] == "pending_verification"
        assert payload["account"]["email"] == "owner.public@example.com"
        assert payload["account"]["email_verified_at"] is None
        assert payload["bound_member"]["name"] == "Owner Public"
        assert payload["acting_member"] is None

        db = testing_session_local()
        try:
            stored_account = db.query(models.Account).filter(
                models.Account.login_id == "owner.public@example.com"
            ).one()
            stored_member = db.query(models.Member).filter(models.Member.id == stored_account.member_id).one()
            assert stored_account.password_hash != "owner-password"
            assert "owner-password" not in stored_account.password_hash
            assert stored_account.registration_status == "pending_verification"
            assert stored_account.email_verified_at is None
            assert stored_member.name == "Owner Public"
            assert stored_member.gender == "female"
            assert stored_member.public_email is False
            assert stored_member.public_tel is False
            assert payload["bound_member"]["id"] == stored_member.id
        finally:
            db.close()

        assert len(email_sender.messages) == 1
        assert email_sender.messages[0].recipient == "owner.public@example.com"
        verification_url = urlparse(email_sender.messages[0].verification_url)
        assert verification_url.path == "/login"
        assert parse_qs(verification_url.query)["token"]
        assert client.get("/auth/me").status_code == 401
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_register_rejects_old_member_based_contract_and_public_super_account_signup():
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        old_contract = client.post(
            "/auth/register",
            json={
                "login_id": "owner",
                "password": "owner-password",
                "member_id": world["owner"].id,
                "email": "wrong@example.com",
            },
        )
        assert old_contract.status_code == 422

        super_signup = client.post(
            "/auth/register",
            json={
                "email": "admin@example.com",
                "password": "admin-password",
                "username": "Admin",
                "gender": "private",
                "is_super_account": True,
            },
        )
        assert super_signup.status_code == 422
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_invalid_register_contract_returns_422_before_email_config_lookup(monkeypatch):
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app, raise_server_exceptions=False)
    world = seed_world(testing_session_local)

    try:
        del app.state.email_sender
        del app.state.verification_base_url
        monkeypatch.setattr(
            auth,
            "get_email_sender",
            lambda: (_ for _ in ()).throw(EmailSenderConfigurationError("smtp not configured")),
        )
        monkeypatch.setattr(
            auth,
            "get_verification_base_url",
            lambda: (_ for _ in ()).throw(EmailSenderConfigurationError("missing verification url")),
        )

        response = client.post(
            "/auth/register",
            json={
                "login_id": "owner",
                "password": "owner-password",
                "member_id": world["owner"].id,
                "email": "owner@example.com",
            },
        )

        assert response.status_code == 422
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_verify_email_activates_account_and_login_requires_verified_account():
    app, engine, testing_session_local, email_sender = build_test_app()
    client = TestClient(app)

    try:
        register_response = client.post(
            "/auth/register",
            json={
                "email": "verify.me@example.com",
                "password": "owner-password",
                "username": "Verify Me",
                "gender": "male",
            },
        )
        assert register_response.status_code == 201

        login_before_verify = client.post(
            "/auth/login",
            json={"login_id": "verify.me@example.com", "password": "owner-password"},
        )
        assert login_before_verify.status_code == 401
        assert login_before_verify.json()["detail"] == INVALID_CREDENTIALS_MESSAGE

        verify_response = client.post(
            "/auth/verify-email",
            json={"token": extract_token(email_sender.messages[0])},
        )
        assert verify_response.status_code == 200
        verify_payload = verify_response.json()
        assert verify_payload["ok"] is True
        assert verify_payload["account"]["login_id"] == "verify.me@example.com"
        assert verify_payload["account"]["registration_status"] == "active"
        assert verify_payload["account"]["email_verified_at"] is not None

        login_response = client.post(
            "/auth/login",
            json={"login_id": "verify.me@example.com", "password": "owner-password"},
        )
        assert login_response.status_code == 200
        assert "session_token=" in login_response.headers.get("set-cookie", "")

        me_payload = client.get("/auth/me").json()
        assert me_payload["authenticated"] is True
        assert me_payload["account"]["registration_status"] == "active"
        assert me_payload["account"]["email_verified_at"] is not None
        assert me_payload["account"]["login_id"] == "verify.me@example.com"
        assert me_payload["acting_member"]["id"] == me_payload["bound_member"]["id"]
        assert me_payload["bound_member"]["name"] == "Verify Me"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_email_backed_login_and_resend_accept_different_case_input():
    app, engine, testing_session_local, email_sender = build_test_app()
    client = TestClient(app)

    try:
        register_response = client.post(
            "/auth/register",
            json={
                "email": "Case.Api@example.com",
                "password": "owner-password",
                "username": "Case Api",
                "gender": "private",
            },
        )
        assert register_response.status_code == 201

        resend_response = client.post(
            "/auth/resend-verification",
            json={"login_id": "CASE.API@EXAMPLE.COM"},
        )
        assert resend_response.status_code == 200
        replacement_token = extract_token(email_sender.messages[-1])

        verify_response = client.post(
            "/auth/verify-email",
            json={"token": replacement_token},
        )
        assert verify_response.status_code == 200

        login_response = client.post(
            "/auth/login",
            json={"login_id": " CASE.API@EXAMPLE.COM ", "password": "owner-password"},
        )
        assert login_response.status_code == 200
        assert "session_token=" in login_response.headers.get("set-cookie", "")
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_api_handles_legacy_mixed_case_email_rows_case_insensitively_but_keeps_super_login_id_case_sensitive():
    app, engine, testing_session_local, email_sender = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        db = testing_session_local()
        try:
            owner = db.query(models.Member).filter(models.Member.id == world["owner"].id).one()
            owner.email = "Legacy.Api@example.com"
            db.commit()

            account = register_account(
                db,
                login_id="Legacy.Api@example.com",
                password="owner-password",
                member_id=owner.id,
                email="Legacy.Api@example.com",
            )
            issue_email_verification_token(db, account_id=account.id)

            stored_account = db.query(models.Account).filter(models.Account.id == account.id).one()
            stored_account.login_id = "Legacy.Api@example.com"
            stored_account.email = "Legacy.Api@example.com"

            admin = register_account(
                db,
                login_id="AdminRoot",
                password="admin-password",
                is_super_account=True,
            )
            admin.email_verified_at = admin.created_at
            admin.registration_status = "active"
            db.commit()
        finally:
            db.close()

        resend_response = client.post(
            "/auth/resend-verification",
            json={"login_id": "legacy.api@EXAMPLE.com"},
        )
        assert resend_response.status_code == 200
        assert email_sender.messages[-1].recipient.lower() == "legacy.api@example.com"

        replacement_token = extract_token(email_sender.messages[-1])
        verify_response = client.post("/auth/verify-email", json={"token": replacement_token})
        assert verify_response.status_code == 200

        login_response = client.post(
            "/auth/login",
            json={"login_id": "LEGACY.API@example.COM", "password": "owner-password"},
        )
        assert login_response.status_code == 200

        wrong_case_super = client.post(
            "/auth/login",
            json={"login_id": "adminroot", "password": "admin-password"},
        )
        assert wrong_case_super.status_code == 401
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_public_registration_rejects_legacy_case_only_email_duplicates_via_api():
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        db = testing_session_local()
        try:
            owner = db.query(models.Member).filter(models.Member.id == world["owner"].id).one()
            owner.email = "Legacy.Duplicate.Api@example.com"
            db.commit()

            account = register_account(
                db,
                login_id="Legacy.Duplicate.Api@example.com",
                password="owner-password",
                member_id=owner.id,
                email="Legacy.Duplicate.Api@example.com",
            )
            stored_account = db.query(models.Account).filter(models.Account.id == account.id).one()
            stored_account.login_id = "Legacy.Duplicate.Api@example.com"
            stored_account.email = "Legacy.Duplicate.Api@example.com"
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/auth/register",
            json={
                "email": "legacy.duplicate.api@EXAMPLE.com",
                "password": "new-password",
                "username": "Duplicate Api",
                "gender": "private",
            },
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_verify_email_rejects_expired_and_reused_tokens():
    app, engine, testing_session_local, email_sender = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        expired_db = testing_session_local()
        try:
            expired_account = register_account(
                expired_db,
                login_id="teammate",
                password="mate-password",
                member_id=world["teammate"].id,
                email=world["teammate"].email,
            )
            expired_issue = issue_email_verification_token(expired_db, account_id=expired_account.id, ttl=None)
            token_row = (
                expired_db.query(models.EmailVerificationToken)
                .filter(models.EmailVerificationToken.account_id == expired_account.id)
                .one()
            )
            token_row.expires_at = token_row.created_at
            expired_db.commit()
        finally:
            expired_db.close()

        expired_response = client.post("/auth/verify-email", json={"token": expired_issue.token})
        assert expired_response.status_code == 400
        assert "expired" in expired_response.json()["detail"].lower()

        register_response = client.post(
            "/auth/register",
            json={
                "email": "owner.reuse@example.com",
                "password": "owner-password",
                "username": "Owner Reuse",
                "gender": "private",
            },
        )
        assert register_response.status_code == 201
        token = extract_token(email_sender.messages[-1])

        first_verify = client.post("/auth/verify-email", json={"token": token})
        assert first_verify.status_code == 200

        second_verify = client.post("/auth/verify-email", json={"token": token})
        assert second_verify.status_code == 400
        assert "already been used" in second_verify.json()["detail"].lower()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_resend_verification_replaces_old_token_and_allows_login_after_verification():
    app, engine, testing_session_local, email_sender = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        register_response = client.post(
            "/auth/register",
            json={
                "email": "resend.me@example.com",
                "password": "owner-password",
                "username": "Resend Me",
                "gender": "private",
            },
        )
        assert register_response.status_code == 201
        original_token = extract_token(email_sender.messages[-1])

        resend_response = client.post(
            "/auth/resend-verification",
            json={"login_id": "resend.me@example.com"},
        )
        assert resend_response.status_code == 200
        resend_payload = resend_response.json()
        assert resend_payload["ok"] is True
        assert resend_payload["verification_email_sent"] is True
        assert "account" not in resend_payload

        replacement_token = extract_token(email_sender.messages[-1])
        assert replacement_token != original_token

        invalid_old = client.post("/auth/verify-email", json={"token": original_token})
        assert invalid_old.status_code == 400
        assert "invalid" in invalid_old.json()["detail"].lower()

        verified = client.post("/auth/verify-email", json={"token": replacement_token})
        assert verified.status_code == 200

        login_response = client.post(
            "/auth/login",
            json={"login_id": "resend.me@example.com", "password": "owner-password"},
        )
        assert login_response.status_code == 200
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_resend_verification_is_publicly_non_enumerating_for_missing_and_verified_accounts():
    app, engine, testing_session_local, email_sender = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        create_verified_regular_account(
            testing_session_local,
            login_id="owner",
            password="owner-password",
            member=world["owner"],
        )
        sent_count = len(email_sender.messages)

        missing_response = client.post("/auth/resend-verification", json={"login_id": "missing-user"})
        verified_response = client.post("/auth/resend-verification", json={"login_id": "owner"})

        assert missing_response.status_code == 200
        assert verified_response.status_code == 200
        assert missing_response.json() == {"ok": True, "verification_email_sent": True}
        assert verified_response.json() == {"ok": True, "verification_email_sent": True}
        assert len(email_sender.messages) == sent_count
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_register_returns_503_for_email_configuration_errors(monkeypatch):
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    try:
        del app.state.verification_base_url
        monkeypatch.setattr(
            auth,
            "get_verification_base_url",
            lambda: (_ for _ in ()).throw(EmailSenderConfigurationError("missing verification url")),
        )

        response = client.post(
            "/auth/register",
            json={
                "email": "config.error@example.com",
                "password": "owner-password",
                "username": "Config Error",
                "gender": "private",
            },
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "missing verification url"

        db = testing_session_local()
        try:
            assert db.query(models.Account).filter(models.Account.login_id == "config.error@example.com").count() == 0
            assert db.query(models.Member).filter(models.Member.email == "config.error@example.com").count() == 0
        finally:
            db.close()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_register_rolls_back_pending_account_and_token_when_email_delivery_fails():
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    try:
        app.state.email_sender = FailingEmailSender()

        first_response = client.post(
            "/auth/register",
            json={
                "email": "delivery.fail@example.com",
                "password": "owner-password",
                "username": "Delivery Fail",
                "gender": "female",
            },
        )

        assert first_response.status_code == 503
        assert first_response.json()["detail"] == "delivery failed"

        db = testing_session_local()
        try:
            assert db.query(models.Account).filter(
                models.Account.login_id == "delivery.fail@example.com"
            ).count() == 0
            assert db.query(models.EmailVerificationToken).count() == 0
            assert db.query(models.Member).filter(models.Member.email == "delivery.fail@example.com").count() == 0
        finally:
            db.close()

        app.state.email_sender = RecordingEmailSender()
        retry_response = client.post(
            "/auth/register",
            json={
                "email": "delivery.fail@example.com",
                "password": "owner-password",
                "username": "Delivery Fail",
                "gender": "female",
            },
        )

        assert retry_response.status_code == 201
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_resend_verification_preserves_existing_token_when_email_delivery_fails():
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app, raise_server_exceptions=False)
    world = seed_world(testing_session_local)

    try:
        register_response = client.post(
            "/auth/register",
            json={
                "email": "resend.failure@example.com",
                "password": "owner-password",
                "username": "Resend Failure",
                "gender": "female",
            },
        )
        assert register_response.status_code == 201
        old_token = extract_token(app.state.email_sender.messages[-1])

        app.state.email_sender = FailingEmailSender()
        response = client.post("/auth/resend-verification", json={"login_id": "resend.failure@example.com"})

        assert response.status_code == 200
        assert response.json() == {"ok": True, "verification_email_sent": True}

        verify_response = client.post("/auth/verify-email", json={"token": old_token})
        assert verify_response.status_code == 200
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_resend_verification_preserves_legacy_mixed_case_token_email_when_delivery_fails():
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    try:
        register_response = client.post(
            "/auth/register",
            json={
                "email": "legacy.token@example.com",
                "password": "owner-password",
                "username": "Legacy Token",
                "gender": "private",
            },
        )
        assert register_response.status_code == 201
        old_token = extract_token(app.state.email_sender.messages[-1])

        db = testing_session_local()
        try:
            account = db.query(models.Account).filter(models.Account.login_id == "legacy.token@example.com").one()
            token_row = (
                db.query(models.EmailVerificationToken)
                .filter(models.EmailVerificationToken.account_id == account.id)
                .one()
            )
            token_row.email = "Legacy.Token@Example.com"
            db.commit()
        finally:
            db.close()

        app.state.email_sender = FailingEmailSender()
        response = client.post("/auth/resend-verification", json={"login_id": "LEGACY.TOKEN@example.com"})

        assert response.status_code == 200
        assert response.json() == {"ok": True, "verification_email_sent": True}

        verify_response = client.post("/auth/verify-email", json={"token": old_token})
        assert verify_response.status_code == 200
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_resend_verification_failure_realigns_to_current_member_email_after_drift():
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app, raise_server_exceptions=False)

    try:
        register_response = client.post(
            "/auth/register",
            json={
                "email": "drift.before@example.com",
                "password": "owner-password",
                "username": "Drift Before",
                "gender": "female",
            },
        )
        assert register_response.status_code == 201
        old_token = extract_token(app.state.email_sender.messages[-1])

        db = testing_session_local()
        try:
            account = db.query(models.Account).filter(models.Account.login_id == "drift.before@example.com").one()
            owner = db.query(models.Member).filter(models.Member.id == account.member_id).one()
            owner.email = "drift.after@example.com"
            db.commit()
        finally:
            db.close()

        app.state.email_sender = FailingEmailSender()
        response = client.post("/auth/resend-verification", json={"login_id": "drift.before@example.com"})

        assert response.status_code == 200
        assert response.json() == {"ok": True, "verification_email_sent": True}

        db = testing_session_local()
        try:
            account = db.query(models.Account).filter(models.Account.login_id == "drift.before@example.com").one()
            tokens = (
                db.query(models.EmailVerificationToken)
                .filter(models.EmailVerificationToken.account_id == account.id)
                .all()
            )
            assert account.email == "drift.after@example.com"
            assert [token.email for token in tokens] == []
        finally:
            db.close()

        verify_response = client.post("/auth/verify-email", json={"token": old_token})
        assert verify_response.status_code == 400
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_regular_account_only_sees_own_identity_and_cannot_switch_or_become_pm():
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        create_verified_regular_account(
            testing_session_local,
            login_id="owner",
            password="owner-password",
            member=world["owner"],
        )
        create_verified_regular_account(
            testing_session_local,
            login_id="teammate",
            password="mate-password",
            member=world["teammate"],
        )

        login_response = client.post(
            "/auth/login",
            json={"login_id": "teammate", "password": "mate-password"},
        )
        assert login_response.status_code == 200

        available_response = client.get("/auth/available-identities")
        assert available_response.status_code == 200
        available_payload = available_response.json()
        assert available_payload["identity_scope"] == "own_only"
        assert available_payload["can_switch_identity"] is False
        assert available_payload["bound_member"]["id"] == world["teammate"].id
        assert [item["id"] for item in available_payload["available_identities"]["own_identities"]] == [
            world["teammate"].id
        ]
        assert available_payload["available_identities"]["global_identities"] == []
        assert available_payload["available_identities"]["test_identities"] == []

        member_response = client.get(f"/protected/projects/{world['project'].id}/member")
        assert member_response.status_code == 200

        pm_response = client.get(f"/protected/projects/{world['project'].id}/pm")
        assert pm_response.status_code == 403

        switch_response = client.post(
            "/auth/switch-identity",
            json={"acting_member_id": world["owner"].id},
        )
        assert switch_response.status_code == 403

        me_response = client.get("/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["acting_member"]["id"] == world["teammate"].id
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_super_account_gets_global_identity_pools_and_can_switch_context():
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        create_verified_regular_account(
            testing_session_local,
            login_id="owner",
            password="owner-password",
            member=world["owner"],
        )
        create_verified_regular_account(
            testing_session_local,
            login_id="teammate",
            password="mate-password",
            member=world["teammate"],
        )
        create_super_account(testing_session_local, login_id="admin", password="admin-password")

        login_response = client.post(
            "/auth/login",
            json={"login_id": "admin", "password": "admin-password"},
        )
        assert login_response.status_code == 200

        available_response = client.get("/auth/available-identities")
        assert available_response.status_code == 200
        available_payload = available_response.json()
        assert available_payload["identity_scope"] == "global_pool"
        assert available_payload["can_switch_identity"] is True
        assert {
            item["id"] for item in available_payload["available_identities"]["global_identities"]
        } >= {world["owner"].id, world["teammate"].id, world["outsider"].id}
        assert [item["id"] for item in available_payload["available_identities"]["test_identities"]] == [
            world["virtual"].id
        ]

        switch_response = client.post(
            "/auth/switch-identity",
            json={"acting_member_id": world["virtual"].id},
        )
        assert switch_response.status_code == 200
        assert switch_response.json()["acting_member"]["id"] == world["virtual"].id

        me_response = client.get("/auth/me")
        assert me_response.status_code == 200
        me_payload = me_response.json()
        assert me_payload["account"]["is_super_account"] is True
        assert me_payload["account"]["registration_status"] == "active"
        assert me_payload["acting_member"]["id"] == world["virtual"].id

        pm_response = client.get(f"/protected/projects/{world['project'].id}/pm")
        assert pm_response.status_code == 200
        assert pm_response.json()["is_super_account"] is True
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_login_errors_are_indistinguishable_for_missing_and_wrong_credentials():
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        create_verified_regular_account(
            testing_session_local,
            login_id="owner",
            password="owner-password",
            member=world["owner"],
        )

        wrong_password = client.post(
            "/auth/login",
            json={"login_id": "owner", "password": "incorrect"},
        )
        missing_account = client.post(
            "/auth/login",
            json={"login_id": "ghost-user", "password": "whatever"},
        )

        assert wrong_password.status_code == 401
        assert missing_account.status_code == 401
        assert wrong_password.json()["detail"] == INVALID_CREDENTIALS_MESSAGE
        assert missing_account.json()["detail"] == INVALID_CREDENTIALS_MESSAGE
        assert wrong_password.json()["detail"] == missing_account.json()["detail"]
        assert "session_token=" not in wrong_password.headers.get("set-cookie", "")
        assert "session_token=" not in missing_account.headers.get("set-cookie", "")
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_virtual_identity_login_is_rejected_without_creating_a_session():
    app, engine, testing_session_local, _ = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        create_verified_regular_account(
            testing_session_local,
            login_id="owner",
            password="owner-password",
            member=world["owner"],
        )

        db = testing_session_local()
        try:
            owner = db.query(models.Member).filter(models.Member.id == world["owner"].id).one()
            owner.is_virtual_identity = True
            db.commit()
        finally:
            db.close()

        login_response = client.post(
            "/auth/login",
            json={"login_id": "owner", "password": "owner-password"},
        )

        assert login_response.status_code == 401
        assert login_response.json()["detail"] == INVALID_CREDENTIALS_MESSAGE
        assert "session_token=" not in login_response.headers.get("set-cookie", "")
        assert client.get("/auth/me").status_code == 401
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
