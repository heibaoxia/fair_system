import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.api import assignments, dependencies, files, swaps
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
    app.include_router(assignments.router)
    app.include_router(files.router)
    app.include_router(swaps.router)

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
        owner = models.Member(name="Owner", tel="13800006001", email="owner@example.com", is_active=True)
        teammate = models.Member(name="Teammate", tel="13800006002", email="teammate@example.com", is_active=True)
        outsider = models.Member(name="Outsider", tel="13800006003", email="outsider@example.com", is_active=True)
        db.add_all([owner, teammate, outsider])
        db.flush()

        project = models.Project(name="Identity Project", description="", created_by=owner.id)
        project.members.extend([owner, teammate, outsider])
        db.add(project)
        db.flush()

        pending_module = models.Module(name="Pending Module", project_id=project.id, status="待分配")
        upload_module = models.Module(
            name="Upload Module",
            project_id=project.id,
            status="开发中",
            assigned_to=teammate.id,
        )
        swap_module = models.Module(
            name="Swap Module",
            project_id=project.id,
            status="开发中",
            assigned_to=teammate.id,
        )
        partner_module = models.Module(
            name="Partner Module",
            project_id=project.id,
            status="开发中",
            assigned_to=outsider.id,
        )
        db.add_all([pending_module, upload_module, swap_module, partner_module])
        db.commit()

        for item in [owner, teammate, outsider, project, pending_module, upload_module, swap_module, partner_module]:
            db.refresh(item)

        return {
            "owner_id": owner.id,
            "teammate_id": teammate.id,
            "outsider_id": outsider.id,
            "project_id": project.id,
            "pending_module_id": pending_module.id,
            "upload_module_id": upload_module.id,
            "swap_module_id": swap_module.id,
            "partner_module_id": partner_module.id,
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


class AssignmentFileSwapIdentityTests(unittest.TestCase):
    def setUp(self):
        self.app, self.engine, self.testing_session_local = build_test_app()
        self.world = seed_world(self.testing_session_local)
        create_accounts(self.testing_session_local, self.world)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def login_client(self, login_id: str, password: str) -> TestClient:
        client = TestClient(self.app)
        response = client.post("/auth/login", json={"login_id": login_id, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def test_batch_confirm_uses_session_pm_identity(self):
        owner_client = self.login_client("owner", "owner-pass")
        outsider_client = self.login_client("outsider", "outsider-pass")

        payload = {"assignments": {str(self.world["teammate_id"]): [self.world["pending_module_id"]]}}
        owner_response = owner_client.post(
            f"/assignments/batch/{self.world['project_id']}/confirm",
            json=payload,
        )
        self.assertEqual(owner_response.status_code, 200, owner_response.text)

        db = self.testing_session_local()
        try:
            module = db.query(models.Module).filter(models.Module.id == self.world["pending_module_id"]).one()
            self.assertEqual(module.assigned_to, self.world["teammate_id"])
            self.assertEqual(module.status, "开发中")
        finally:
            db.close()

        outsider_response = outsider_client.post(
            f"/assignments/batch/{self.world['project_id']}/confirm",
            json={"assignments": {str(self.world["outsider_id"]): [self.world["pending_module_id"]]}},
        )
        self.assertEqual(outsider_response.status_code, 403)

    def test_upload_and_review_use_session_identity(self):
        teammate_client = self.login_client("teammate", "mate-pass")
        outsider_client = self.login_client("outsider", "outsider-pass")
        owner_client = self.login_client("owner", "owner-pass")

        denied_upload = outsider_client.post(
            f"/files/upload/?uploaded_by={self.world['teammate_id']}",
            data={"module_id": str(self.world["upload_module_id"]), "uploaded_by": str(self.world["teammate_id"])},
            files={"file": ("deliverable.txt", b"demo", "text/plain")},
        )
        self.assertEqual(denied_upload.status_code, 403)

        upload_response = teammate_client.post(
            f"/files/upload/?uploaded_by={self.world['owner_id']}",
            data={"module_id": str(self.world["upload_module_id"]), "uploaded_by": str(self.world["owner_id"])},
            files={"file": ("deliverable.txt", b"demo", "text/plain")},
        )
        self.assertEqual(upload_response.status_code, 200, upload_response.text)
        file_record_id = upload_response.json()["file_record_id"]

        db = self.testing_session_local()
        try:
            stored = db.query(models.ModuleFile).filter(models.ModuleFile.id == file_record_id).one()
            self.assertEqual(stored.uploaded_by, self.world["teammate_id"])
        finally:
            db.close()

        denied_review = outsider_client.post(
            f"/files/review/{file_record_id}?action=approve"
        )
        self.assertEqual(denied_review.status_code, 403)

        approved_review = owner_client.post(
            f"/files/review/{file_record_id}?action=approve"
        )
        self.assertEqual(approved_review.status_code, 200, approved_review.text)

    def test_swap_routes_use_session_identity_for_process_and_cancel(self):
        owner_client = self.login_client("owner", "owner-pass")
        teammate_client = self.login_client("teammate", "mate-pass")
        outsider_client = self.login_client("outsider", "outsider-pass")

        create_response = owner_client.post(
            "/swaps/",
            json={
                "module_id": self.world["swap_module_id"],
                "to_member_id": self.world["outsider_id"],
                "swap_type": "reassign",
                "reason": "rebalance",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        first_swap_id = create_response.json()["swap_id"]

        denied_accept = teammate_client.post(f"/swaps/{first_swap_id}/accept")
        self.assertEqual(denied_accept.status_code, 403)

        accepted = outsider_client.post(f"/swaps/{first_swap_id}/accept")
        self.assertEqual(accepted.status_code, 200, accepted.text)

        second_swap = owner_client.post(
            "/swaps/",
            json={
                "module_id": self.world["swap_module_id"],
                "to_member_id": self.world["teammate_id"],
                "swap_type": "reassign",
                "reason": "redo",
            },
        )
        self.assertEqual(second_swap.status_code, 200, second_swap.text)
        second_swap_id = second_swap.json()["swap_id"]

        denied_cancel = teammate_client.post(f"/swaps/{second_swap_id}/cancel")
        self.assertEqual(denied_cancel.status_code, 403)

        cancelled = owner_client.post(f"/swaps/{second_swap_id}/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)

        third_swap = owner_client.post(
            "/swaps/",
            json={
                "module_id": self.world["partner_module_id"],
                "to_member_id": self.world["teammate_id"],
                "swap_type": "reassign",
                "reason": "pending check",
            },
        )
        self.assertEqual(third_swap.status_code, 200, third_swap.text)
        third_swap_id = third_swap.json()["swap_id"]

        teammate_pending = teammate_client.get("/swaps/pending")
        self.assertEqual(teammate_pending.status_code, 200, teammate_pending.text)
        self.assertTrue(any(item["id"] == third_swap_id for item in teammate_pending.json()))

        outsider_pending = outsider_client.get("/swaps/pending")
        self.assertEqual(outsider_pending.status_code, 200, outsider_pending.text)
        self.assertFalse(any(item["id"] == third_swap_id for item in outsider_pending.json()))


if __name__ == "__main__":
    unittest.main()
