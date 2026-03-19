from fastapi.testclient import TestClient

from app import models
from tests.frontend_session_helpers import (
    assert_login_redirect,
    build_frontend_session_test_app,
    register_member_session,
)


def seed_overview_world(testing_session_local):
    db = testing_session_local()
    try:
        viewer = models.Member(name="Overview Viewer", tel="13800014001", is_active=True)
        outsider = models.Member(name="Overview Outsider", tel="13800014002", is_active=True)
        db.add_all([viewer, outsider])
        db.flush()

        visible_project = models.Project(
            name="Visible Overview Project",
            description="Visible in overview",
            created_by=viewer.id,
        )
        visible_project.members.append(viewer)

        hidden_project = models.Project(
            name="Hidden Overview Project",
            description="Must not leak in overview",
            created_by=outsider.id,
        )
        hidden_project.members.append(outsider)

        db.add_all([visible_project, hidden_project])
        db.commit()

        return {
            "viewer_id": viewer.id,
            "outsider_id": outsider.id,
        }
    finally:
        db.close()


def test_overview_requires_login_and_preserves_next_url():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)

    try:
        response = client.get("/overview?member_id=123", follow_redirects=False)

        assert_login_redirect(response, "/overview?member_id=123")
    finally:
        client.close()
        harness.close()


def test_overview_only_renders_projects_visible_to_current_session():
    harness = build_frontend_session_test_app()
    world = seed_overview_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["viewer_id"],
            login_id="overview-viewer-login",
        )

        response = client.get(f"/overview?member_id={world['outsider_id']}")
        body = response.text

        assert response.status_code == 200
        assert "Visible Overview Project" in body
        assert "Hidden Overview Project" not in body
    finally:
        client.close()
        harness.close()
