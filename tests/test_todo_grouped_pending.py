from datetime import datetime, timedelta
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.api import frontend
from app.api.dependencies import get_db
from app.database import Base


class TodoGroupedPendingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self.app = FastAPI()
        self.app.include_router(frontend.router)

        def override_get_db():
            db = self.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(self.app)

        db = self.TestingSessionLocal()
        member = models.Member(name="TodoUser", tel="13800000021", is_active=True)
        owner = models.Member(name="Owner", tel="13800000022", is_active=True)
        db.add_all([member, owner])
        db.flush()

        project = models.Project(
            name="待评分项目",
            description="",
            created_by=owner.id,
            assessment_start=datetime.now() - timedelta(hours=1),
            assessment_end=datetime.now() + timedelta(hours=8),
        )
        project.members.extend([member, owner])
        db.add(project)
        db.flush()

        db.add_all([
            models.Module(name="模块1", description="A", project_id=project.id, status="待分配"),
            models.Module(name="模块2", description="B", project_id=project.id, status="待分配"),
        ])
        db.commit()

        self.member_id = member.id
        self.project_id = project.id
        db.close()

    def tearDown(self):
        self.app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_todo_page_shows_grouped_pending_projects_linking_to_scoring_page(self):
        response = self.client.get(f"/todo?member_id={self.member_id}")
        body = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("/scoring/", body)
        self.assertIn(f"/scoring/{self.project_id}?member_id={self.member_id}", body)
        self.assertIn("待评分项目", body)
        self.assertIn("待打分模块 2 个", body)


if __name__ == "__main__":
    unittest.main()
