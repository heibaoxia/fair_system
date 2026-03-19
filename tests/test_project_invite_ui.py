import html

from fastapi.testclient import TestClient

from app import models
from app.api.dependencies import SESSION_COOKIE_NAME
from app.services.auth_service import (
    create_session,
    issue_email_verification_token,
    register_account,
    verify_email_token,
)
from tests.frontend_session_helpers import build_frontend_session_test_app


def seed_project_invite_ui_world(testing_session_local):
    db = testing_session_local()
    try:
        owner = models.Member(name="Invite PM", tel="13800016001", is_active=True)
        teammate = models.Member(name="Invite Teammate", tel="13800016002", is_active=True)
        pending_invitee = models.Member(name="Pending Invitee", tel="13800016003", is_active=True)
        db.add_all([owner, teammate, pending_invitee])
        db.flush()

        project = models.Project(
            name="Invite Detail Project",
            description="Project detail invite UI",
            created_by=owner.id,
        )
        project.members.extend([owner, teammate])
        db.add(project)
        db.commit()
        db.refresh(project)

        return {
            "project_id": project.id,
            "owner_member_id": owner.id,
            "teammate_member_id": teammate.id,
            "pending_invitee_member_id": pending_invitee.id,
        }
    finally:
        db.close()


def create_verified_account_for_member(testing_session_local, *, member_id: int, login_id: str) -> int:
    db = testing_session_local()
    try:
        member = db.query(models.Member).filter(models.Member.id == member_id).one()
        if not member.email:
            member.email = f"{login_id}@example.test"
            db.commit()
            db.refresh(member)

        account = register_account(
            db,
            login_id=login_id,
            password="secret-pass",
            member_id=member_id,
            email=member.email,
        )
        issued_token = issue_email_verification_token(db, account_id=account.id)
        verify_email_token(db, issued_token.token)
        return account.id
    finally:
        db.close()


def login_as_account(client: TestClient, testing_session_local, *, account_id: int) -> None:
    db = testing_session_local()
    try:
        session = create_session(db, account_id=account_id)
    finally:
        db.close()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_token)


def test_pm_project_detail_contains_invite_entry_and_not_old_add_member_wording():
    harness = build_frontend_session_test_app()
    world = seed_project_invite_ui_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        owner_account_id = create_verified_account_for_member(
            harness.testing_session_local,
            member_id=world["owner_member_id"],
            login_id="invite-pm",
        )
        login_as_account(client, harness.testing_session_local, account_id=owner_account_id)

        response = client.get(f"/project/{world['project_id']}")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert 'data-manager-action="invite-member"' in body
        assert ">邀请成员<" in body
        assert "添加成员" not in body
    finally:
        client.close()
        harness.close()


def test_non_pm_project_detail_does_not_expose_invite_entry_or_controls():
    harness = build_frontend_session_test_app()
    world = seed_project_invite_ui_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        teammate_account_id = create_verified_account_for_member(
            harness.testing_session_local,
            member_id=world["teammate_member_id"],
            login_id="invite-teammate",
        )
        login_as_account(client, harness.testing_session_local, account_id=teammate_account_id)

        response = client.get(f"/project/{world['project_id']}")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert 'data-manager-action="invite-member"' not in body
        assert 'id="invite-member-modal"' not in body
        assert 'id="invite-account-id"' not in body
    finally:
        client.close()
        harness.close()


def test_pm_page_contains_friend_quick_invite_hook_and_account_id_invite_form():
    harness = build_frontend_session_test_app()
    world = seed_project_invite_ui_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        owner_account_id = create_verified_account_for_member(
            harness.testing_session_local,
            member_id=world["owner_member_id"],
            login_id="invite-pm-layout",
        )
        login_as_account(client, harness.testing_session_local, account_id=owner_account_id)

        response = client.get(f"/project/{world['project_id']}")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert "好友快捷邀请" in body
        assert 'id="invite-friends-container"' in body
        assert "输入账户ID邀请" in body
        assert 'id="invite-account-id"' in body
        assert 'id="invite-account-submit"' in body
    finally:
        client.close()
        harness.close()


def test_pm_page_js_wires_social_relationships_and_project_invites_without_old_add_member_flow():
    harness = build_frontend_session_test_app()
    world = seed_project_invite_ui_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        owner_account_id = create_verified_account_for_member(
            harness.testing_session_local,
            member_id=world["owner_member_id"],
            login_id="invite-pm-script",
        )
        login_as_account(client, harness.testing_session_local, account_id=owner_account_id)

        response = client.get(f"/project/{world['project_id']}")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert "fetch('/social/relationships')" in body
        assert f"/projects/{world['project_id']}/invites" in body
        assert "invitee_account_id" in body
        assert 'id="add-member-modal"' not in body
        assert "submitMemberForm" not in body
    finally:
        client.close()
        harness.close()


def test_pending_invites_are_not_rendered_as_actual_project_members():
    harness = build_frontend_session_test_app()
    world = seed_project_invite_ui_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        owner_account_id = create_verified_account_for_member(
            harness.testing_session_local,
            member_id=world["owner_member_id"],
            login_id="invite-pm-pending",
        )
        pending_account_id = create_verified_account_for_member(
            harness.testing_session_local,
            member_id=world["pending_invitee_member_id"],
            login_id="invite-pending",
        )
        db = harness.testing_session_local()
        try:
            db.add(
                models.ProjectInvite(
                    project_id=world["project_id"],
                    inviter_account_id=owner_account_id,
                    invitee_account_id=pending_account_id,
                    status="pending",
                )
            )
            db.commit()
        finally:
            db.close()

        login_as_account(client, harness.testing_session_local, account_id=owner_account_id)
        response = client.get(f"/project/{world['project_id']}")
        body = html.unescape(response.text)

        assert response.status_code == 200
        assert "Invite PM" in body
        assert "Invite Teammate" in body
        assert "Pending Invitee" not in body
    finally:
        client.close()
        harness.close()
