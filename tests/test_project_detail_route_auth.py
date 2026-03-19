from fastapi.testclient import TestClient

from app import models
from tests.frontend_session_helpers import (
    assert_login_redirect,
    build_frontend_session_test_app,
    register_member_session,
)


def seed_project_detail_world(testing_session_local):
    db = testing_session_local()
    try:
        owner = models.Member(name="Detail Owner", tel="13800015001", is_active=True)
        teammate = models.Member(name="Detail Teammate", tel="13800015002", is_active=True)
        outsider = models.Member(name="Detail Outsider", tel="13800015003", is_active=True)
        db.add_all([owner, teammate, outsider])
        db.flush()

        project = models.Project(
            name="Secret Detail Project",
            description="Sensitive detail page",
            created_by=owner.id,
        )
        project.members.extend([owner, teammate])
        db.add(project)
        db.flush()

        module = models.Module(
            name="Sensitive Module",
            description="Should never leak to outsiders",
            project_id=project.id,
        )
        db.add(module)
        db.commit()

        return {
            "project_id": project.id,
            "teammate_id": teammate.id,
            "outsider_id": outsider.id,
        }
    finally:
        db.close()


def test_project_detail_requires_login_and_preserves_next_url():
    harness = build_frontend_session_test_app()
    world = seed_project_detail_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        response = client.get(
            f"/project/{world['project_id']}?member_id={world['outsider_id']}",
            follow_redirects=False,
        )

        assert_login_redirect(
            response,
            f"/project/{world['project_id']}?member_id={world['outsider_id']}",
        )
    finally:
        client.close()
        harness.close()


def test_project_detail_rejects_non_member_without_rendering_sensitive_html():
    harness = build_frontend_session_test_app()
    world = seed_project_detail_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["outsider_id"],
            login_id="detail-outsider-login",
        )

        response = client.get(
            f"/project/{world['project_id']}?member_id={world['teammate_id']}"
        )
        body = response.text

        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/json")
        assert "Secret Detail Project" not in body
        assert "Sensitive Module" not in body
        assert "Detail Teammate" not in body
    finally:
        client.close()
        harness.close()
