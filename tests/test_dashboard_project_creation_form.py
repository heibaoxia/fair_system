from fastapi.testclient import TestClient

from app import models
from tests.frontend_session_helpers import (
    assert_login_redirect,
    build_frontend_session_test_app,
    register_member_session,
)


def seed_dashboard_member(testing_session_local):
    db = testing_session_local()
    try:
        member = models.Member(name="Dashboard Owner", tel="13800013001", is_active=True)
        db.add(member)
        db.commit()
        return {"member_id": member.id}
    finally:
        db.close()


def seed_dashboard_visibility_world(testing_session_local):
    db = testing_session_local()
    try:
        member = models.Member(name="Dashboard Viewer", tel="13800013011", is_active=True)
        outsider = models.Member(name="Dashboard Outsider", tel="13800013012", is_active=True)
        db.add_all([member, outsider])
        db.flush()

        visible_project = models.Project(
            name="Visible Dashboard Project",
            description="Only visible to the logged-in member",
            created_by=member.id,
        )
        visible_project.members.append(member)

        hidden_project = models.Project(
            name="Hidden Dashboard Project",
            description="Must not leak into another session",
            created_by=outsider.id,
        )
        hidden_project.members.append(outsider)

        db.add_all([visible_project, hidden_project])
        db.commit()

        return {
            "member_id": member.id,
            "outsider_id": outsider.id,
        }
    finally:
        db.close()


def test_dashboard_requires_login_and_preserves_next_url():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        response = client.get("/?member_id=999", follow_redirects=False)

        assert_login_redirect(response, "/?member_id=999")
    finally:
        client.close()
        harness.close()


def test_dashboard_for_logged_in_member_renders_structured_project_creation_form():
    harness = build_frontend_session_test_app()
    world = seed_dashboard_member(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["member_id"],
            login_id="dashboard-login",
        )

        me_response = client.get("/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["acting_member"]["id"] == world["member_id"]

        response = client.get("/?member_id=999")
        body = response.text

        assert response.status_code == 200
        assert 'id="create-project-modal"' in body
        assert 'id="create-project-form"' in body
        assert 'id="create-project-dimensions"' in body
        assert 'id="create-project-modules"' in body
        assert "scoring_dimensions" in body
        assert "function createProjectQuickly()" not in body
        assert "window.prompt(" not in body
    finally:
        client.close()
        harness.close()


def test_dashboard_only_renders_projects_visible_to_current_session():
    harness = build_frontend_session_test_app()
    world = seed_dashboard_visibility_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["member_id"],
            login_id="dashboard-visibility-login",
        )

        response = client.get(f"/?member_id={world['outsider_id']}")
        body = response.text

        assert response.status_code == 200
        assert "Visible Dashboard Project" in body
        assert "Hidden Dashboard Project" not in body
    finally:
        client.close()
        harness.close()
