import html
from datetime import datetime

from fastapi.testclient import TestClient

from app import models
from app.api.social import router as social_router
from tests.frontend_session_helpers import (
    build_frontend_session_test_app,
    register_member_session,
)
from tests.test_project_invites_api import (
    build_test_app as build_invite_test_app,
    get_project_member_ids,
    login_as,
    seed_account,
    seed_world,
)


def seed_project_with_owner(
    testing_session_local,
    *,
    owner_member_id: int,
    name: str,
    description: str,
    total_revenue: float,
) -> int:
    db = testing_session_local()
    try:
        owner_member = db.query(models.Member).filter(models.Member.id == owner_member_id).one()
        project = models.Project(
            name=name,
            description=description,
            total_revenue=total_revenue,
            created_by=owner_member_id,
        )
        project.members.append(owner_member)
        db.add(project)
        db.commit()
        db.refresh(project)
        return project.id
    finally:
        db.close()


def set_invite_timestamps(
    testing_session_local,
    *,
    invite_id: int,
    created_at: datetime,
    resolved_at: datetime | None = None,
) -> None:
    db = testing_session_local()
    try:
        invite = db.query(models.ProjectInvite).filter(models.ProjectInvite.id == invite_id).one()
        invite.created_at = created_at
        invite.resolved_at = resolved_at
        db.commit()
    finally:
        db.close()


def build_social_invite_api_app():
    app, engine, testing_session_local = build_invite_test_app()
    app.include_router(social_router)
    return app, engine, testing_session_local


def test_social_page_script_wires_project_invite_listing_and_decision_endpoints():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)
    db = harness.testing_session_local()
    try:
        member = models.Member(
            name="Social Invite Viewer",
            email="social.invite.viewer@example.com",
            is_active=True,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
    finally:
        db.close()

    try:
        register_member_session(
            client,
            member_id=member.id,
            login_id="social-invite-viewer",
        )

        response = client.get("/social")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert "'/social/project-invites'" in body
        assert '`/project-invites/${inviteId}/accept`' in body
        assert '`/project-invites/${inviteId}/reject`' in body
        assert 'await loadProjectInvites();' in body
        assert 'id="social-project-invites-pending-list"' in body
        assert 'id="social-project-invites-history-list"' in body
    finally:
        client.close()
        harness.close()


def test_social_page_script_refreshes_project_invites_after_failed_decision_too():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)
    db = harness.testing_session_local()
    try:
        member = models.Member(
            name="Social Invite Error Refresh",
            email="social.invite.error.refresh@example.com",
            is_active=True,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
    finally:
        db.close()

    try:
        register_member_session(
            client,
            member_id=member.id,
            login_id="social-invite-error-refresh",
        )

        response = client.get("/social")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert (
            "} catch (error) {\n"
            "            showToast(error.message || 'Failed to update invite.', true);\n"
            "        } finally {\n"
            "            await loadProjectInvites();\n"
            "        }"
        ) in body
    finally:
        client.close()
        harness.close()


def test_social_page_invite_section_renders_pending_history_hooks_without_project_detail_link_contract():
    harness = build_frontend_session_test_app()
    client = TestClient(harness.app)
    db = harness.testing_session_local()
    try:
        member = models.Member(
            name="Social Invite Layout",
            email="social.invite.layout@example.com",
            is_active=True,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
    finally:
        db.close()

    try:
        register_member_session(
            client,
            member_id=member.id,
            login_id="social-invite-layout",
        )

        response = client.get("/social")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert "待处理邀请" in body
        assert "历史记录" in body
        assert "No pending invites yet." in body
        assert "No invite history yet." in body
        assert "邀请人" in body
        assert "成员数" in body
        assert "项目总收入" in body
        assert "Accept" in body
        assert "Reject" in body
        assert "Project Detail" not in body
        assert "View project" not in body
        assert 'href="/project/' not in body
    finally:
        client.close()
        harness.close()


def test_get_social_project_invites_returns_pending_and_history_in_newest_first_order_with_summary_shape():
    app, engine, testing_session_local = build_social_invite_api_app()
    pm_client = TestClient(app)
    invitee_client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        pending_older_project_id = seed_project_with_owner(
            testing_session_local,
            owner_member_id=world["owner"].member_id,
            name="Pending Older Project",
            description="Pending older description",
            total_revenue=1200.5,
        )
        pending_newer_project_id = seed_project_with_owner(
            testing_session_local,
            owner_member_id=world["owner"].member_id,
            name="Pending Newer Project",
            description="Pending newer description",
            total_revenue=3400.75,
        )
        history_rejected_project_id = seed_project_with_owner(
            testing_session_local,
            owner_member_id=world["owner"].member_id,
            name="Rejected History Project",
            description="Rejected history description",
            total_revenue=88.0,
        )
        history_accepted_project_id = seed_project_with_owner(
            testing_session_local,
            owner_member_id=world["owner"].member_id,
            name="Accepted History Project",
            description="Accepted history description",
            total_revenue=9900.0,
        )

        login_as(pm_client, testing_session_local, account_id=world["owner"].account_id)
        pending_older_invite = pm_client.post(
            f"/projects/{pending_older_project_id}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )
        pending_newer_invite = pm_client.post(
            f"/projects/{pending_newer_project_id}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )
        rejected_invite = pm_client.post(
            f"/projects/{history_rejected_project_id}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )
        accepted_invite = pm_client.post(
            f"/projects/{history_accepted_project_id}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )

        login_as(invitee_client, testing_session_local, account_id=world["invitee"].account_id)
        reject_response = invitee_client.post(f"/project-invites/{rejected_invite.json()['id']}/reject")
        accept_response = invitee_client.post(f"/project-invites/{accepted_invite.json()['id']}/accept")

        assert pending_older_invite.status_code == 200, pending_older_invite.text
        assert pending_newer_invite.status_code == 200, pending_newer_invite.text
        assert rejected_invite.status_code == 200, rejected_invite.text
        assert accepted_invite.status_code == 200, accepted_invite.text
        assert reject_response.status_code == 200, reject_response.text
        assert accept_response.status_code == 200, accept_response.text

        set_invite_timestamps(
            testing_session_local,
            invite_id=pending_older_invite.json()["id"],
            created_at=datetime.fromisoformat("2026-03-10T09:00:00"),
        )
        set_invite_timestamps(
            testing_session_local,
            invite_id=pending_newer_invite.json()["id"],
            created_at=datetime.fromisoformat("2026-03-12T09:00:00"),
        )
        set_invite_timestamps(
            testing_session_local,
            invite_id=rejected_invite.json()["id"],
            created_at=datetime.fromisoformat("2026-03-08T09:00:00"),
            resolved_at=datetime.fromisoformat("2026-03-12T13:00:00"),
        )
        set_invite_timestamps(
            testing_session_local,
            invite_id=accepted_invite.json()["id"],
            created_at=datetime.fromisoformat("2026-03-09T09:00:00"),
            resolved_at=datetime.fromisoformat("2026-03-13T13:00:00"),
        )

        response = invitee_client.get("/social/project-invites")
        payload = response.json()

        assert response.status_code == 200, response.text
        assert [item["project_name"] for item in payload["pending"]] == [
            "Pending Newer Project",
            "Pending Older Project",
        ]
        assert [item["project_name"] for item in payload["history"]] == [
            "Accepted History Project",
            "Rejected History Project",
        ]

        required_keys = {
            "id",
            "project_id",
            "project_name",
            "inviter_account_id",
            "inviter_username",
            "status",
            "project_total_revenue",
            "project_member_count",
            "project_description",
            "created_at",
            "resolved_at",
        }
        for item in payload["pending"] + payload["history"]:
            assert set(item.keys()) == required_keys
            assert "project_detail_url" not in item
            assert item["inviter_account_id"] == world["owner"].account_id
            assert item["inviter_username"] == "Owner"

        assert payload["pending"][0]["project_total_revenue"] == 3400.75
        assert payload["pending"][0]["project_member_count"] == 1
        assert payload["pending"][0]["project_description"] == "Pending newer description"
        assert payload["pending"][0]["resolved_at"] is None
        assert payload["history"][0]["status"] == "accepted"
        assert payload["history"][0]["project_member_count"] == 2
        assert payload["history"][1]["status"] == "rejected"
        assert payload["history"][1]["project_member_count"] == 1
    finally:
        engine.dispose()


def test_accepting_from_social_invites_moves_item_to_history_and_adds_member():
    app, engine, testing_session_local = build_social_invite_api_app()
    pm_client = TestClient(app)
    invitee_client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        login_as(pm_client, testing_session_local, account_id=world["owner"].account_id)
        create_response = pm_client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )
        invite_id = create_response.json()["id"]

        login_as(invitee_client, testing_session_local, account_id=world["invitee"].account_id)
        before_response = invitee_client.get("/social/project-invites")
        accept_response = invitee_client.post(f"/project-invites/{invite_id}/accept")
        after_response = invitee_client.get("/social/project-invites")

        assert before_response.status_code == 200, before_response.text
        assert [item["id"] for item in before_response.json()["pending"]] == [invite_id]
        assert before_response.json()["history"] == []
        assert accept_response.status_code == 200, accept_response.text
        assert accept_response.json() == {"ok": True, "status": "accepted"}
        assert after_response.status_code == 200, after_response.text
        assert after_response.json()["pending"] == []
        assert [item["id"] for item in after_response.json()["history"]] == [invite_id]
        assert after_response.json()["history"][0]["status"] == "accepted"
        assert get_project_member_ids(testing_session_local, world["project_id"]) == sorted(
            [world["owner"].member_id, world["invitee"].member_id]
        )
    finally:
        engine.dispose()


def test_rejecting_from_social_invites_moves_item_to_history_without_adding_member():
    app, engine, testing_session_local = build_social_invite_api_app()
    pm_client = TestClient(app)
    invitee_client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        login_as(pm_client, testing_session_local, account_id=world["owner"].account_id)
        create_response = pm_client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )
        invite_id = create_response.json()["id"]

        login_as(invitee_client, testing_session_local, account_id=world["invitee"].account_id)
        before_response = invitee_client.get("/social/project-invites")
        reject_response = invitee_client.post(f"/project-invites/{invite_id}/reject")
        after_response = invitee_client.get("/social/project-invites")

        assert before_response.status_code == 200, before_response.text
        assert [item["id"] for item in before_response.json()["pending"]] == [invite_id]
        assert before_response.json()["history"] == []
        assert reject_response.status_code == 200, reject_response.text
        assert reject_response.json() == {"ok": True, "status": "rejected"}
        assert after_response.status_code == 200, after_response.text
        assert after_response.json()["pending"] == []
        assert [item["id"] for item in after_response.json()["history"]] == [invite_id]
        assert after_response.json()["history"][0]["status"] == "rejected"
        assert get_project_member_ids(testing_session_local, world["project_id"]) == [world["owner"].member_id]
    finally:
        engine.dispose()


def test_social_project_invites_rejects_super_account_callers():
    app, engine, testing_session_local = build_social_invite_api_app()
    client = TestClient(app)

    try:
        super_account = seed_account(
            testing_session_local,
            login_id="social-invite-admin",
            is_super_account=True,
            bind_member=False,
        )
        login_as(client, testing_session_local, account_id=super_account.account_id)

        response = client.get("/social/project-invites")

        assert response.status_code == 403
        assert response.json() == {"detail": "Super accounts cannot use social endpoints."}
    finally:
        engine.dispose()
