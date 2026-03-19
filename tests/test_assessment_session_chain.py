from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.api import assessments, dependencies
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
    app.include_router(assessments.router)

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
        owner = models.Member(name="Owner", tel="13800007001", email="owner@example.com", is_active=True)
        teammate = models.Member(name="Teammate", tel="13800007002", email="teammate@example.com", is_active=True)
        outsider = models.Member(name="Outsider", tel="13800007003", email="outsider@example.com", is_active=True)
        db.add_all([owner, teammate, outsider])
        db.flush()

        project = models.Project(
            name="Assessment Project",
            description="",
            created_by=owner.id,
            assessment_start=datetime.now() - timedelta(hours=1),
            assessment_end=datetime.now() + timedelta(hours=1),
        )
        project.members.extend([owner, teammate])
        db.add(project)
        db.flush()

        module = models.Module(name="Scored Module", project_id=project.id, status="done")
        db.add(module)
        db.flush()

        dimension = models.ScoringDimension(project_id=project.id, name="Quality", weight=1.0, sort_order=0)
        db.add(dimension)
        db.commit()

        for item in [owner, teammate, outsider, project, module, dimension]:
            db.refresh(item)

        return {
            "owner_id": owner.id,
            "teammate_id": teammate.id,
            "outsider_id": outsider.id,
            "project_id": project.id,
            "module_id": module.id,
            "dimension_id": dimension.id,
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
            member_id=world["owner_id"],
            email="owner@example.com",
        )
        teammate_account = register_account(
            db,
            login_id="teammate",
            password="mate-pass",
            member_id=world["teammate_id"],
            email="teammate@example.com",
        )
        outsider_account = register_account(
            db,
            login_id="outsider",
            password="outsider-pass",
            member_id=world["outsider_id"],
            email="outsider@example.com",
        )

        for account in [owner_account, teammate_account, outsider_account]:
            issue = issue_email_verification_token(db, account_id=account.id)
            verify_email_token(db, issue.token)
    finally:
        db.close()


def login(client: TestClient, login_id: str, password: str) -> None:
    response = client.post("/auth/login", json={"login_id": login_id, "password": password})
    assert response.status_code == 200, response.text


def test_assessment_submission_uses_session_identity_even_if_body_claims_another_member():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)
    create_accounts(testing_session_local, world)

    try:
        login(client, "teammate", "mate-pass")

        response = client.post(
            "/assessments/",
            json={
                "module_id": world["module_id"],
                "member_id": world["owner_id"],
                "dimension_scores": [{"dimension_id": world["dimension_id"], "score": 8.5}],
            },
        )
        assert response.status_code == 200, response.text

        db = testing_session_local()
        try:
            stored = db.query(models.ModuleAssessment).filter(models.ModuleAssessment.id == response.json()["id"]).one()
            assert stored.member_id == world["teammate_id"]
            assert stored.module_id == world["module_id"]
        finally:
            db.close()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_non_project_member_cannot_impersonate_project_member_to_submit_assessment():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)
    world = seed_world(testing_session_local)
    create_accounts(testing_session_local, world)

    try:
        login(client, "outsider", "outsider-pass")

        response = client.post(
            "/assessments/",
            json={
                "module_id": world["module_id"],
                "member_id": world["owner_id"],
                "dimension_scores": [{"dimension_id": world["dimension_id"], "score": 9.0}],
            },
        )
        assert response.status_code == 403

        db = testing_session_local()
        try:
            assert db.query(models.ModuleAssessment).count() == 0
        finally:
            db.close()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
