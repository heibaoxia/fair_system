from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.api import dependencies, projects
from app.api.dependencies import SESSION_COOKIE_NAME
from app.api.project_invites import router as project_invites_router
from app.database import Base
from app.services.auth_service import create_session
from app.services import project_invite_service
from app.services.schema_bootstrap import bootstrap_schema


@dataclass(frozen=True)
class SeededAccount:
    account_id: int
    member_id: int | None
    login_id: str


UNSET = object()


def build_test_app():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    bootstrap_schema(engine)

    app = FastAPI()
    app.include_router(projects.router)
    app.include_router(project_invites_router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = override_get_db
    return app, engine, testing_session_local


def seed_account(
    testing_session_local,
    *,
    login_id: str,
    name: str | None = None,
    email: str | None = None,
    account_is_active: bool = True,
    member_is_active: bool = True,
    is_super_account: bool = False,
    is_virtual_identity: bool = False,
    bind_member: bool = True,
    registration_status: str = "active",
    is_email_verified: bool = True,
) -> SeededAccount:
    db = testing_session_local()
    try:
        member = None
        if bind_member:
            member = models.Member(
                name=name or login_id,
                email=email or f"{login_id}@example.com",
                tel=f"138{abs(hash(login_id)) % 100000000:08d}",
                is_active=member_is_active,
                is_virtual_identity=is_virtual_identity,
            )
            db.add(member)
            db.flush()

        account = models.Account(
            login_id=login_id,
            password_hash="test-password-hash",
            email=(email or f"{login_id}@example.com") if bind_member else email,
            email_verified_at=datetime.now() if is_email_verified else None,
            registration_status=registration_status,
            is_super_account=is_super_account,
            member_id=None if member is None else member.id,
            is_active=account_is_active,
            created_at=datetime.now(),
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return SeededAccount(
            account_id=account.id,
            member_id=account.member_id,
            login_id=account.login_id,
        )
    finally:
        db.close()


def seed_world(testing_session_local):
    owner = seed_account(testing_session_local, login_id="owner", name="Owner")
    invitee = seed_account(testing_session_local, login_id="invitee", name="Invitee")
    outsider = seed_account(testing_session_local, login_id="outsider", name="Outsider")

    db = testing_session_local()
    try:
        project = models.Project(
            name="Invites Project",
            description="",
            created_by=owner.member_id,
        )
        owner_member = db.query(models.Member).filter(models.Member.id == owner.member_id).one()
        project.members.append(owner_member)
        db.add(project)
        db.commit()
        db.refresh(project)
        return {
            "owner": owner,
            "invitee": invitee,
            "outsider": outsider,
            "project_id": project.id,
        }
    finally:
        db.close()


def login_as(client: TestClient, testing_session_local, *, account_id: int) -> None:
    db = testing_session_local()
    try:
        session = create_session(db, account_id=account_id)
    finally:
        db.close()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_token)


def get_project_member_ids(testing_session_local, project_id: int) -> list[int]:
    db = testing_session_local()
    try:
        project = db.query(models.Project).filter(models.Project.id == project_id).one()
        return sorted(member.id for member in project.members)
    finally:
        db.close()


def get_invite(testing_session_local, invite_id: int) -> models.ProjectInvite:
    db = testing_session_local()
    try:
        return db.query(models.ProjectInvite).filter(models.ProjectInvite.id == invite_id).one()
    finally:
        db.close()


def build_conflicting_commit_override(
    testing_session_local,
    *,
    project_id: int,
    member_id: int,
):
    def override_get_db():
        db = testing_session_local()
        original_commit = db.commit
        commit_count = 0

        def commit_with_conflict():
            nonlocal commit_count
            commit_count += 1
            if commit_count == 2:
                other_db = testing_session_local()
                try:
                    other_db.execute(
                        models.project_members_association.insert().values(
                            project_id=project_id,
                            member_id=member_id,
                        )
                    )
                    other_db.commit()
                finally:
                    other_db.close()
                raise IntegrityError(
                    "INSERT INTO project_members (project_id, member_id) VALUES (?, ?)",
                    {"project_id": project_id, "member_id": member_id},
                    Exception("UNIQUE constraint failed: project_members.project_id, project_members.member_id"),
                )
            return original_commit()

        db.commit = commit_with_conflict
        try:
            yield db
        finally:
            db.close()

    return override_get_db


def update_account_and_member(
    testing_session_local,
    *,
    account_id: int,
    account_is_active: bool | None = None,
    email_verified_at=UNSET,
    registration_status: str | None = None,
    member_is_active: bool | None = None,
    member_is_virtual_identity: bool | None = None,
) -> None:
    db = testing_session_local()
    try:
        account = db.query(models.Account).filter(models.Account.id == account_id).one()
        if account_is_active is not None:
            account.is_active = account_is_active
        if email_verified_at is not UNSET:
            account.email_verified_at = email_verified_at
        if registration_status is not None:
            account.registration_status = registration_status
        if account.member is not None:
            if member_is_active is not None:
                account.member.is_active = member_is_active
            if member_is_virtual_identity is not None:
                account.member.is_virtual_identity = member_is_virtual_identity
        db.commit()
    finally:
        db.close()


def test_non_pm_cannot_create_invite():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        login_as(client, testing_session_local, account_id=world["outsider"].account_id)

        response = client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )

        assert response.status_code == 403
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_pm_can_create_invite_by_invitee_account_id():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        login_as(client, testing_session_local, account_id=world["owner"].account_id)

        response = client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["project_id"] == world["project_id"]
        assert payload["inviter_account_id"] == world["owner"].account_id
        assert payload["invitee_account_id"] == world["invitee"].account_id
        assert payload["status"] == "pending"
        assert payload["resolved_at"] is None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_pending_invite_does_not_add_member_to_project():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        login_as(client, testing_session_local, account_id=world["owner"].account_id)

        response = client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )

        assert response.status_code == 200, response.text
        assert get_project_member_ids(testing_session_local, world["project_id"]) == [world["owner"].member_id]
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_invitee_can_accept_and_member_is_added():
    app, engine, testing_session_local = build_test_app()
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
        accept_response = invitee_client.post(f"/project-invites/{invite_id}/accept")

        assert accept_response.status_code == 200, accept_response.text
        assert accept_response.json() == {"ok": True, "status": "accepted"}
        assert get_project_member_ids(testing_session_local, world["project_id"]) == sorted(
            [world["owner"].member_id, world["invitee"].member_id]
        )

        stored_invite = get_invite(testing_session_local, invite_id)
        assert stored_invite.status == "accepted"
        assert stored_invite.resolved_at is not None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_invitee_can_reject_and_member_is_not_added():
    app, engine, testing_session_local = build_test_app()
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
        reject_response = invitee_client.post(f"/project-invites/{invite_id}/reject")

        assert reject_response.status_code == 200, reject_response.text
        assert reject_response.json() == {"ok": True, "status": "rejected"}
        assert get_project_member_ids(testing_session_local, world["project_id"]) == [world["owner"].member_id]

        stored_invite = get_invite(testing_session_local, invite_id)
        assert stored_invite.status == "rejected"
        assert stored_invite.resolved_at is not None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_non_invitee_cannot_accept_or_reject():
    app, engine, testing_session_local = build_test_app()
    pm_client = TestClient(app)
    outsider_client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        login_as(pm_client, testing_session_local, account_id=world["owner"].account_id)
        create_response = pm_client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )
        invite_id = create_response.json()["id"]

        login_as(outsider_client, testing_session_local, account_id=world["outsider"].account_id)
        accept_response = outsider_client.post(f"/project-invites/{invite_id}/accept")
        reject_response = outsider_client.post(f"/project-invites/{invite_id}/reject")

        assert accept_response.status_code == 403
        assert reject_response.status_code == 403

        stored_invite = get_invite(testing_session_local, invite_id)
        assert stored_invite.status == "pending"
        assert stored_invite.resolved_at is None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_get_project_invites_is_pm_only_and_shows_history_status_transitions():
    app, engine, testing_session_local = build_test_app()
    pm_client = TestClient(app)
    invitee_client = TestClient(app)
    outsider_client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        login_as(pm_client, testing_session_local, account_id=world["owner"].account_id)
        create_response = pm_client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )
        invite_id = create_response.json()["id"]

        login_as(outsider_client, testing_session_local, account_id=world["outsider"].account_id)
        forbidden_list = outsider_client.get(f"/projects/{world['project_id']}/invites")
        assert forbidden_list.status_code == 403

        login_as(invitee_client, testing_session_local, account_id=world["invitee"].account_id)
        reject_response = invitee_client.post(f"/project-invites/{invite_id}/reject")
        assert reject_response.status_code == 200, reject_response.text

        login_as(pm_client, testing_session_local, account_id=world["owner"].account_id)
        list_response = pm_client.get(f"/projects/{world['project_id']}/invites")

        assert list_response.status_code == 200, list_response.text
        assert list_response.json() == {
            "invites": [
                {
                    "id": invite_id,
                    "project_id": world["project_id"],
                    "inviter_account_id": world["owner"].account_id,
                    "invitee_account_id": world["invitee"].account_id,
                    "status": "rejected",
                    "created_at": create_response.json()["created_at"],
                    "resolved_at": get_invite(testing_session_local, invite_id).resolved_at.isoformat(),
                }
            ]
        }
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_cannot_create_duplicate_pending_invite():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        login_as(client, testing_session_local, account_id=world["owner"].account_id)

        first_response = client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )
        duplicate_response = client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )

        assert first_response.status_code == 200, first_response.text
        assert duplicate_response.status_code == 400
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_db_prevents_duplicate_pending_invites_even_if_bypassing_service():
    app, engine, testing_session_local = build_test_app()
    world = seed_world(testing_session_local)

    try:
        db = testing_session_local()
        try:
            first_invite = models.ProjectInvite(
                project_id=world["project_id"],
                inviter_account_id=world["owner"].account_id,
                invitee_account_id=world["invitee"].account_id,
                status="pending",
            )
            duplicate_invite = models.ProjectInvite(
                project_id=world["project_id"],
                inviter_account_id=world["owner"].account_id,
                invitee_account_id=world["invitee"].account_id,
                status="pending",
            )
            db.add(first_invite)
            db.commit()

            db.add(duplicate_invite)
            try:
                db.commit()
                raise AssertionError("Expected duplicate pending invite insert to fail.")
            except IntegrityError:
                db.rollback()
        finally:
            db.close()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_resolved_invite_does_not_block_creating_a_new_pending_invite():
    app, engine, testing_session_local = build_test_app()
    pm_client = TestClient(app)
    invitee_client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        login_as(pm_client, testing_session_local, account_id=world["owner"].account_id)
        first_response = pm_client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )
        invite_id = first_response.json()["id"]

        login_as(invitee_client, testing_session_local, account_id=world["invitee"].account_id)
        reject_response = invitee_client.post(f"/project-invites/{invite_id}/reject")
        assert reject_response.status_code == 200, reject_response.text

        login_as(pm_client, testing_session_local, account_id=world["owner"].account_id)
        second_response = pm_client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["invitee"].account_id},
        )

        assert second_response.status_code == 200, second_response.text
        assert second_response.json()["status"] == "pending"
        assert second_response.json()["id"] != invite_id
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_cannot_invite_self():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        login_as(client, testing_session_local, account_id=world["owner"].account_id)

        response = client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": world["owner"].account_id},
        )

        assert response.status_code == 400
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_cannot_invite_super_virtual_or_unverified_target_accounts():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)

    try:
        super_account = seed_account(
            testing_session_local,
            login_id="super-target",
            bind_member=False,
            is_super_account=True,
        )
        virtual_account = seed_account(
            testing_session_local,
            login_id="virtual-target",
            is_virtual_identity=True,
        )
        unverified_account = seed_account(
            testing_session_local,
            login_id="unverified-target",
            registration_status="pending_verification",
            is_email_verified=False,
        )

        login_as(client, testing_session_local, account_id=world["owner"].account_id)

        super_response = client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": super_account.account_id},
        )
        virtual_response = client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": virtual_account.account_id},
        )
        unverified_response = client.post(
            f"/projects/{world['project_id']}/invites",
            json={"invitee_account_id": unverified_account.account_id},
        )

        assert super_response.status_code == 400
        assert virtual_response.status_code == 400
        assert unverified_response.status_code == 400
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_accept_service_fails_if_invitee_account_becomes_inactive():
    app, engine, testing_session_local = build_test_app()
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

        update_account_and_member(
            testing_session_local,
            account_id=world["invitee"].account_id,
            account_is_active=False,
        )

        db = testing_session_local()
        try:
            try:
                project_invite_service.accept_project_invite(
                    db,
                    invite_id=invite_id,
                    actor_account_id=world["invitee"].account_id,
                )
                raise AssertionError("Expected accepting an invite for an inactive account to fail.")
            except project_invite_service.ProjectInviteValidationError:
                db.rollback()
        finally:
            db.close()

        assert get_project_member_ids(testing_session_local, world["project_id"]) == [world["owner"].member_id]
        stored_invite = get_invite(testing_session_local, invite_id)
        assert stored_invite.status == "pending"
        assert stored_invite.resolved_at is None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_accept_service_fails_if_invitee_account_becomes_unverified():
    app, engine, testing_session_local = build_test_app()
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

        update_account_and_member(
            testing_session_local,
            account_id=world["invitee"].account_id,
            email_verified_at=None,
            registration_status="pending_verification",
        )

        db = testing_session_local()
        try:
            try:
                project_invite_service.accept_project_invite(
                    db,
                    invite_id=invite_id,
                    actor_account_id=world["invitee"].account_id,
                )
                raise AssertionError("Expected accepting an invite for an unverified account to fail.")
            except project_invite_service.ProjectInviteValidationError:
                db.rollback()
        finally:
            db.close()

        assert get_project_member_ids(testing_session_local, world["project_id"]) == [world["owner"].member_id]
        stored_invite = get_invite(testing_session_local, invite_id)
        assert stored_invite.status == "pending"
        assert stored_invite.resolved_at is None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_accept_service_fails_if_invitee_member_becomes_virtual():
    app, engine, testing_session_local = build_test_app()
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

        update_account_and_member(
            testing_session_local,
            account_id=world["invitee"].account_id,
            member_is_virtual_identity=True,
        )

        db = testing_session_local()
        try:
            try:
                project_invite_service.accept_project_invite(
                    db,
                    invite_id=invite_id,
                    actor_account_id=world["invitee"].account_id,
                )
                raise AssertionError("Expected accepting an invite for a virtual member to fail.")
            except project_invite_service.ProjectInviteValidationError:
                db.rollback()
        finally:
            db.close()

        assert get_project_member_ids(testing_session_local, world["project_id"]) == [world["owner"].member_id]
        stored_invite = get_invite(testing_session_local, invite_id)
        assert stored_invite.status == "pending"
        assert stored_invite.resolved_at is None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_accepting_a_now_stale_invite_cancels_it_and_returns_400():
    app, engine, testing_session_local = build_test_app()
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

        add_member_response = pm_client.post(
            f"/projects/{world['project_id']}/members/{world['invitee'].member_id}"
        )
        assert add_member_response.status_code == 200, add_member_response.text

        login_as(invitee_client, testing_session_local, account_id=world["invitee"].account_id)
        accept_response = invitee_client.post(f"/project-invites/{invite_id}/accept")

        assert accept_response.status_code == 400
        assert get_project_member_ids(testing_session_local, world["project_id"]) == sorted(
            [world["owner"].member_id, world["invitee"].member_id]
        )
        stored_invite = get_invite(testing_session_local, invite_id)
        assert stored_invite.status == "cancelled"
        assert stored_invite.resolved_at is not None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_bootstrap_schema_reconciles_legacy_duplicate_pending_project_invites():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE project_invites (
                        id INTEGER PRIMARY KEY,
                        project_id INTEGER NOT NULL,
                        inviter_account_id INTEGER NOT NULL,
                        invitee_account_id INTEGER NOT NULL,
                        status VARCHAR NOT NULL,
                        created_at DATETIME NOT NULL,
                        resolved_at DATETIME NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO project_invites (id, project_id, inviter_account_id, invitee_account_id, status, created_at, resolved_at)
                    VALUES
                        (1, 10, 100, 200, 'pending', '2026-03-01 10:00:00', NULL),
                        (2, 10, 100, 200, 'pending', '2026-03-02 10:00:00', NULL),
                        (3, 10, 100, 200, 'rejected', '2026-03-03 10:00:00', '2026-03-03 12:00:00')
                    """
                )
            )

        bootstrap_schema(engine)

        with engine.begin() as connection:
            statuses = connection.execute(
                text(
                    """
                    SELECT id, status, resolved_at
                    FROM project_invites
                    ORDER BY id ASC
                    """
                )
            ).fetchall()
            index_rows = connection.execute(text("PRAGMA index_list(project_invites)")).fetchall()

            assert statuses[0][1] == "pending"
            assert statuses[0][2] is None
            assert statuses[1][1] == "cancelled"
            assert statuses[1][2] is not None
            assert statuses[2][1] == "rejected"

            matching_indexes = [row for row in index_rows if row[1] == "uq_project_invites_pending_pair"]
            assert matching_indexes, index_rows

            try:
                connection.execute(
                    text(
                        """
                        INSERT INTO project_invites (project_id, inviter_account_id, invitee_account_id, status, created_at, resolved_at)
                        VALUES (10, 101, 200, 'pending', '2026-03-04 10:00:00', NULL)
                        """
                    )
                )
                raise AssertionError("Expected the bootstrap-added pending invite unique index to reject duplicates.")
            except IntegrityError:
                pass
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_bootstrap_schema_reconciles_legacy_duplicate_project_members_and_adds_uniqueness():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE project_members (
                        project_id INTEGER NOT NULL,
                        member_id INTEGER NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO project_members (project_id, member_id)
                    VALUES
                        (10, 20),
                        (10, 20),
                        (10, 21)
                    """
                )
            )

        bootstrap_schema(engine)

        with engine.begin() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT project_id, member_id, COUNT(*)
                    FROM project_members
                    GROUP BY project_id, member_id
                    ORDER BY project_id ASC, member_id ASC
                    """
                )
            ).fetchall()
            index_rows = connection.execute(text("PRAGMA index_list(project_members)")).fetchall()

            assert rows == [(10, 20, 1), (10, 21, 1)]
            matching_indexes = [row for row in index_rows if row[1] == "uq_project_members_pair"]
            assert matching_indexes, index_rows

            try:
                connection.execute(
                    text(
                        """
                        INSERT INTO project_members (project_id, member_id)
                        VALUES (10, 20)
                        """
                    )
                )
                raise AssertionError("Expected the bootstrap-added project_members unique index to reject duplicates.")
            except IntegrityError:
                pass
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_accept_handles_project_member_uniqueness_conflict_by_cancelling_invite():
    app, engine, testing_session_local = build_test_app()
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

        original_get_db_override = app.dependency_overrides[dependencies.get_db]
        app.dependency_overrides[dependencies.get_db] = build_conflicting_commit_override(
            testing_session_local,
            project_id=world["project_id"],
            member_id=world["invitee"].member_id,
        )

        login_as(invitee_client, testing_session_local, account_id=world["invitee"].account_id)
        accept_response = invitee_client.post(f"/project-invites/{invite_id}/accept")

        assert accept_response.status_code == 400
        stored_invite = get_invite(testing_session_local, invite_id)
        assert stored_invite.status == "cancelled"
        assert stored_invite.resolved_at is not None
        assert get_project_member_ids(testing_session_local, world["project_id"]) == sorted(
            [world["owner"].member_id, world["invitee"].member_id]
        )
    finally:
        if "original_get_db_override" in locals():
            app.dependency_overrides[dependencies.get_db] = original_get_db_override
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
