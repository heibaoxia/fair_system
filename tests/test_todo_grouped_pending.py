from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import models
from tests.frontend_session_helpers import (
    assert_login_redirect,
    build_frontend_session_test_app,
    register_member_session,
)


def seed_todo_world(testing_session_local):
    db = testing_session_local()
    try:
        member = models.Member(name="Todo User", tel="13800012001", is_active=True)
        owner = models.Member(name="Owner", tel="13800012002", is_active=True)
        outsider = models.Member(name="Outsider", tel="13800012003", is_active=True)
        db.add_all([member, owner, outsider])
        db.flush()

        project = models.Project(
            name="Pending Project",
            description="Session-driven todo page",
            created_by=owner.id,
            assessment_start=datetime.now() - timedelta(hours=1),
            assessment_end=datetime.now() + timedelta(hours=8),
        )
        project.members.extend([member, owner])
        db.add(project)
        db.flush()

        db.add_all(
            [
                models.Module(name="Module 1", description="A", project_id=project.id),
                models.Module(name="Module 2", description="B", project_id=project.id),
            ]
        )
        db.commit()

        return {
            "member_id": member.id,
            "owner_id": owner.id,
            "outsider_id": outsider.id,
            "project_id": project.id,
        }
    finally:
        db.close()


def test_todo_page_requires_login_and_preserves_next_url():
    harness = build_frontend_session_test_app()
    world = seed_todo_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        response = client.get(
            f"/todo?member_id={world['member_id']}",
            follow_redirects=False,
        )

        assert_login_redirect(response, f"/todo?member_id={world['member_id']}")
    finally:
        client.close()
        harness.close()


def test_todo_page_groups_pending_projects_from_session_and_drops_member_id_links():
    harness = build_frontend_session_test_app()
    world = seed_todo_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["member_id"],
            login_id="todo-user-login",
        )

        response = client.get(f"/todo?member_id={world['outsider_id']}")
        body = response.text

        assert response.status_code == 200
        assert "Pending Project" in body
        assert "Module 1" not in body
        assert "Module 2" not in body
        assert f'/scoring/{world["project_id"]}' in body
        assert f'/scoring/{world["project_id"]}?member_id={world["member_id"]}' not in body
        assert "member_id=" not in body
    finally:
        client.close()
        harness.close()


def test_todo_page_redirects_to_login_after_logout():
    harness = build_frontend_session_test_app()
    world = seed_todo_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["member_id"],
            login_id="todo-logout-login",
        )

        pre_logout = client.get("/todo")
        assert pre_logout.status_code == 200

        logout_response = client.post("/auth/logout")
        assert logout_response.status_code == 200
        assert "session_token=" in logout_response.headers.get("set-cookie", "")

        post_logout = client.get(
            f"/todo?member_id={world['member_id']}",
            follow_redirects=False,
        )
        assert_login_redirect(post_logout, f"/todo?member_id={world['member_id']}")
    finally:
        client.close()
        harness.close()
