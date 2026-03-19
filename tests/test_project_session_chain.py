from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.api import dependencies, modules, project_dependencies, projects
from app.api.auth import router as auth_router
from app.database import Base
from app.services.auth_service import issue_email_verification_token, register_account, verify_email_token
from app.services.schema_bootstrap import bootstrap_schema


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
    app.include_router(projects.router)
    app.include_router(modules.router)
    app.include_router(project_dependencies.router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = override_get_db
    return app, engine, testing_session_local


def seed_world(testing_session_local):
    db = testing_session_local()
    try:
        owner = models.Member(name="Owner", tel="13800005001", email="owner@example.com", is_active=True)
        teammate = models.Member(name="Teammate", tel="13800005002", email="teammate@example.com", is_active=True)
        outsider = models.Member(name="Outsider", tel="13800005003", email="outsider@example.com", is_active=True)
        db.add_all([owner, teammate, outsider])
        db.flush()

        project = models.Project(name="Managed Project", description="", created_by=owner.id)
        project.members.append(owner)
        db.add(project)
        db.flush()

        module_a = models.Module(name="Module A", project_id=project.id, status="待分配")
        module_b = models.Module(name="Module B", project_id=project.id, status="待分配")
        db.add_all([module_a, module_b])
        db.commit()

        for item in [owner, teammate, outsider, project, module_a, module_b]:
            db.refresh(item)

        return {
            "owner": owner,
            "teammate": teammate,
            "outsider": outsider,
            "project": project,
            "module_a": module_a,
            "module_b": module_b,
        }
    finally:
        db.close()


def create_accounts(testing_session_local, world):
    db = testing_session_local()
    try:
        owner_account = register_account(
            db,
            login_id="owner",
            password="owner-pass",
            member_id=world["owner"].id,
            email=world["owner"].email,
        )
        teammate_account = register_account(
            db,
            login_id="teammate",
            password="mate-pass",
            member_id=world["teammate"].id,
            email=world["teammate"].email,
        )
        outsider_account = register_account(
            db,
            login_id="outsider",
            password="outsider-pass",
            member_id=world["outsider"].id,
            email=world["outsider"].email,
        )
        register_account(db, login_id="admin", password="admin-pass", is_super_account=True)

        for account in [owner_account, teammate_account, outsider_account]:
            issue = issue_email_verification_token(db, account_id=account.id)
            verify_email_token(db, issue.token)
    finally:
        db.close()


def login(client: TestClient, login_id: str, password: str) -> None:
    response = client.post("/auth/login", json={"login_id": login_id, "password": password})
    assert response.status_code == 200, response.text


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


def test_project_creation_uses_session_identity_sets_creator_as_pm_and_allows_member_additions():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)
    create_accounts(testing_session_local, world)

    try:
        payload = {
            "name": "Created From Session",
            "description": "",
            "new_modules": [],
            "dependencies": [],
            "scoring_dimensions": [{"name": "质量", "weight": 1.0}],
        }

        unauthenticated = client.post("/projects/", json=payload)
        assert unauthenticated.status_code == 401

        login(client, "owner", "owner-pass")
        response = client.post("/projects/?created_by_member_id=999", json=payload)
        assert response.status_code == 200, response.text

        created = response.json()
        assert created["created_by"] == world["owner"].id

        my_projects = client.get("/projects/my")
        assert my_projects.status_code == 200, my_projects.text
        created_entry = next(item for item in my_projects.json() if item["id"] == created["id"])
        assert created_entry["is_manager"] is True

        add_teammate = client.post(f"/projects/{created['id']}/members/{world['teammate'].id}")
        assert add_teammate.status_code == 200, add_teammate.text

        db = testing_session_local()
        try:
            stored = db.query(models.Project).filter(models.Project.id == created["id"]).one()
            assert stored.created_by == world["owner"].id
            assert sorted(member.id for member in stored.members) == sorted(
                [world["owner"].id, world["teammate"].id]
            )
        finally:
            db.close()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_regular_accounts_only_manage_projects_they_can_access():
    app, engine, testing_session_local = build_test_app()
    owner_client = TestClient(app)
    teammate_client = TestClient(app)
    outsider_client = TestClient(app)
    world = seed_world(testing_session_local)
    create_accounts(testing_session_local, world)

    try:
        login(teammate_client, "teammate", "mate-pass")
        list_response = teammate_client.get("/projects/")
        assert list_response.status_code == 200
        assert list_response.json() == []

        hidden_project = teammate_client.get(f"/projects/{world['project'].id}")
        assert hidden_project.status_code == 403

        forbidden_add = teammate_client.post(f"/projects/{world['project'].id}/members/{world['outsider'].id}")
        assert forbidden_add.status_code == 403

        login(owner_client, "owner", "owner-pass")
        added = owner_client.post(f"/projects/{world['project'].id}/members/{world['teammate'].id}")
        assert added.status_code == 200

        module_response = owner_client.post(
            f"/projects/{world['project'].id}/modules",
            json={"name": "Managed Module", "description": "", "estimated_hours": 2.0, "allowed_file_types": ""},
        )
        assert module_response.status_code == 200
        managed_module_id = module_response.json()["id"]

        allowed_project = teammate_client.get(f"/projects/{world['project'].id}")
        assert allowed_project.status_code == 200

        denied_update = teammate_client.put(
            f"/modules/{managed_module_id}",
            json={"name": "Teammate Edit Attempt"},
        )
        assert denied_update.status_code == 403

        dependency_created = owner_client.post(
            f"/projects/{world['project'].id}/dependencies",
            json={
                "preceding_module_id": world["module_a"].id,
                "dependent_module_id": world["module_b"].id,
            },
        )
        assert dependency_created.status_code == 200, dependency_created.text

        dependency_delete_denied = teammate_client.delete(
            f"/projects/{world['project'].id}/dependencies/{dependency_created.json()['id']}"
        )
        assert dependency_delete_denied.status_code == 403

        login(outsider_client, "outsider", "outsider-pass")
        outsider_list = outsider_client.get("/projects/")
        assert outsider_list.status_code == 200
        assert outsider_list.json() == []
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_add_member_handles_project_member_uniqueness_conflict_as_already_in_project():
    app, engine, testing_session_local = build_test_app()
    owner_client = TestClient(app)
    world = seed_world(testing_session_local)
    create_accounts(testing_session_local, world)

    try:
        login(owner_client, "owner", "owner-pass")

        original_get_db_override = app.dependency_overrides[dependencies.get_db]
        app.dependency_overrides[dependencies.get_db] = build_conflicting_commit_override(
            testing_session_local,
            project_id=world["project"].id,
            member_id=world["teammate"].id,
        )

        response = owner_client.post(f"/projects/{world['project'].id}/members/{world['teammate'].id}")

        assert response.status_code == 200, response.text
        assert response.json() == {"message": "Member is already in the project."}

        db = testing_session_local()
        try:
            stored_project = db.query(models.Project).filter(models.Project.id == world["project"].id).one()
            assert sorted(member.id for member in stored_project.members) == sorted(
                [world["owner"].id, world["teammate"].id]
            )
        finally:
            db.close()
    finally:
        if "original_get_db_override" in locals():
            app.dependency_overrides[dependencies.get_db] = original_get_db_override
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_super_account_views_globally_but_executes_management_as_acting_identity():
    app, engine, testing_session_local = build_test_app()
    admin_client = TestClient(app)
    world = seed_world(testing_session_local)
    create_accounts(testing_session_local, world)

    try:
        login(admin_client, "admin", "admin-pass")

        global_list = admin_client.get("/projects/")
        assert global_list.status_code == 200
        assert {item["id"] for item in global_list.json()} == {world["project"].id}

        global_read = admin_client.get(f"/projects/{world['project'].id}")
        assert global_read.status_code == 200

        global_create = admin_client.post(
            "/projects/",
            json={
                "name": "Admin Without Identity",
                "description": "",
                "new_modules": [],
                "dependencies": [],
                "scoring_dimensions": [{"name": "质量", "weight": 1.0}],
            },
        )
        assert global_create.status_code == 403

        switch_to_teammate = admin_client.post(
            "/auth/switch-identity",
            json={"acting_member_id": world["teammate"].id},
        )
        assert switch_to_teammate.status_code == 200

        acting_list = admin_client.get("/projects/")
        assert acting_list.status_code == 200
        assert acting_list.json() == []

        acting_read = admin_client.get(f"/projects/{world['project'].id}")
        assert acting_read.status_code == 403

        acting_create = admin_client.post(
            "/projects/",
            json={
                "name": "Created As Teammate",
                "description": "",
                "new_modules": [],
                "dependencies": [],
                "scoring_dimensions": [{"name": "质量", "weight": 1.0}],
            },
        )
        assert acting_create.status_code == 200
        assert acting_create.json()["created_by"] == world["teammate"].id

        acting_add_member = admin_client.post(f"/projects/{world['project'].id}/members/{world['outsider'].id}")
        assert acting_add_member.status_code == 403

        switch_to_owner = admin_client.post(
            "/auth/switch-identity",
            json={"acting_member_id": world["owner"].id},
        )
        assert switch_to_owner.status_code == 200

        owner_mode_add_member = admin_client.post(
            f"/projects/{world['project'].id}/members/{world['outsider'].id}"
        )
        assert owner_mode_add_member.status_code == 200
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
