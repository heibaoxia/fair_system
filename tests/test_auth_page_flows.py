from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from tests.frontend_session_helpers import build_frontend_session_test_app


def test_register_page_collects_public_identity_fields_without_member_picker_or_member_loading():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        response = client.get("/register?next=/todo")
        body = response.text

        assert response.status_code == 200
        assert 'id="register-email"' in body
        assert 'id="register-username"' in body
        assert 'id="register-gender"' in body
        assert 'type="email"' in body
        assert 'id="register-member-id"' not in body
        assert 'name="member_id"' not in body
        assert "/members/" not in body
        assert "loadMembers" not in body
        assert "verification: 'pending'" in body
        assert "email: email" in body
        assert 'id="register-submit"' in body
    finally:
        client.close()
        harness.close()


def test_login_page_pending_verification_state_surfaces_resend_entry_and_prefills_login_id():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        response = client.get(
            "/login?next=/todo&verification=pending&login_id=owner@example.com&email=owner@example.com"
        )
        body = response.text

        assert response.status_code == 200
        assert "owner@example.com" in body
        assert 'id="resend-form"' in body
        assert 'id="resend-submit"' in body
        assert 'id="resend-login-id"' in body
        assert 'value="owner@example.com"' in body
        assert "/auth/resend-verification" in body
    finally:
        client.close()
        harness.close()


def test_login_page_renders_unverified_login_help_and_auto_verify_entrypoints():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        response = client.get("/login?token=abc123&next=/todo")
        body = response.text

        assert response.status_code == 200
        assert '"verificationToken": "abc123"' in body
        assert "/auth/verify-email" in body
        assert "普通用户使用邮箱登录" in body
    finally:
        client.close()
        harness.close()


def test_clicked_verification_email_lands_on_login_page_token_flow():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        register_response = client.post(
            "/auth/register",
            json={
                "email": "member@example.com",
                "password": "secret-pass",
                "username": "Member Example",
                "gender": "private",
            },
        )
        assert register_response.status_code == 201

        email_sender = harness.app.state.test_email_sender
        verification_url = urlparse(email_sender.messages[-1].verification_url)
        token = parse_qs(verification_url.query)["token"][0]

        clicked_response = client.get(verification_url.path + f"?{verification_url.query}")
        body = clicked_response.text

        assert verification_url.path == "/login"
        assert clicked_response.status_code == 200
        assert f'"verificationToken": "{token}"' in body
        assert "/auth/verify-email" in body
    finally:
        client.close()
        harness.close()


def test_login_page_renders_verify_success_and_failure_feedback():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        success_response = client.get("/login?verification=verified&login_id=owner@example.com")
        success_body = success_response.text
        failure_response = client.get("/login?verification=failed&reason=expired")
        failure_body = failure_response.text

        assert success_response.status_code == 200
        assert 'value="owner@example.com"' in success_body

        assert failure_response.status_code == 200
        assert 'id="resend-form"' in failure_body
        assert 'id="resend-login-id"' in failure_body
    finally:
        client.close()
        harness.close()


def test_login_page_explains_regular_users_use_email_and_marks_super_accounts_as_test_only():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        response = client.get("/login")
        body = response.text

        assert response.status_code == 200
        assert 'name="login_id"' in body
        assert "普通用户使用邮箱登录" in body
        assert "测试超级号使用登录标识登录" in body
    finally:
        client.close()
        harness.close()
