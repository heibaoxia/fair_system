import html
from datetime import datetime

from fastapi.testclient import TestClient

from app import models
from app.api.dependencies import SESSION_COOKIE_NAME
from app.services.auth_service import create_session
from tests.frontend_session_helpers import build_frontend_session_test_app


def login_as_seeded_regular_account(client: TestClient, testing_session_local) -> None:
    db = testing_session_local()
    try:
        member = models.Member(
            name="Copy Check User",
            email="copy.check@example.com",
            is_active=True,
        )
        db.add(member)
        db.flush()

        account = models.Account(
            login_id="copy.check@example.com",
            password_hash="test-password-hash",
            email="copy.check@example.com",
            email_verified_at=datetime.now(),
            registration_status="active",
            is_super_account=False,
            member_id=member.id,
            is_active=True,
            created_at=datetime.now(),
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        session = create_session(db, account_id=account.id)
    finally:
        db.close()

    client.cookies.set(SESSION_COOKIE_NAME, session.session_token)


def test_base_template_regular_session_summary_shows_account_id_not_member_id():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        login_as_seeded_regular_account(client, harness.testing_session_local)

        response = client.get("/social")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert "账户ID #${context.account.id}" in body
        assert 'identityNameEl.textContent = `${actingMember.name} (#${actingMember.id})`;' not in body
        assert 'buildIdentityOption(`${member.name} (#${member.id}) - ${sourceLabel}`' in body
    finally:
        client.close()
        harness.close()


def test_base_template_super_account_copy_is_explicitly_test_only():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        login_as_seeded_regular_account(client, harness.testing_session_local)

        response = client.get("/social")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert "God Mode" not in body
        assert "const SUPER_TEST_ACCOUNT_LABEL = '测试超级号';" in body
        assert "const SUPER_TEST_MODE_LABEL = '测试视角';" in body
        assert "buildIdentityOption(getSuperTestIdentityLabel(), 0, selectedMemberId)" in body
    finally:
        client.close()
        harness.close()


def test_register_page_copy_does_not_describe_member_profile_first_registration():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        response = client.get("/register")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert "member profile" not in body.lower()
        assert "系统会自动创建你的账号" in body
        assert "邮箱和手机号默认不公开" in body
    finally:
        client.close()
        harness.close()
