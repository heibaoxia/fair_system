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


class ScoringPageRouteTests(unittest.TestCase):
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
        owner = models.Member(name="Owner", tel="13800000011", is_active=True)
        member = models.Member(name="Scorer", tel="13800000012", is_active=True)
        db.add_all([owner, member])
        db.flush()

        project = models.Project(
            name="评分项目",
            description="项目描述",
            created_by=owner.id,
            assessment_start=datetime.now() - timedelta(hours=1),
            assessment_end=datetime.now() + timedelta(hours=2),
        )
        project.members.extend([owner, member])
        db.add(project)
        db.flush()

        module_a = models.Module(name="模块A", description="模块A说明", project_id=project.id, status="待分配")
        module_b = models.Module(name="模块B", description="模块B说明", project_id=project.id, status="待分配")
        db.add_all([module_a, module_b])
        db.flush()

        dim_a = models.ScoringDimension(project_id=project.id, name="难度", weight=0.5, sort_order=0)
        dim_b = models.ScoringDimension(project_id=project.id, name="创意度", weight=0.5, sort_order=1)
        db.add_all([dim_a, dim_b])
        db.flush()

        assessment = models.ModuleAssessment(member_id=member.id, module_id=module_a.id)
        db.add(assessment)
        db.flush()
        db.add_all([
            models.DimensionScore(assessment_id=assessment.id, dimension_id=dim_a.id, score=6.5),
            models.DimensionScore(assessment_id=assessment.id, dimension_id=dim_b.id, score=8.0),
        ])
        db.commit()

        self.project_id = project.id
        self.member_id = member.id
        db.close()

    def tearDown(self):
        self.app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_scoring_page_renders_project_modules_and_existing_member_scores(self):
        response = self.client.get(f"/scoring/{self.project_id}?member_id={self.member_id}")
        body = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("const scoringDimensions =", body)
        self.assertIn("const scoringModules =", body)
        self.assertIn("\\u6a21\\u5757A", body)
        self.assertIn("\\u6a21\\u5757B", body)
        self.assertIn("\\u96be\\u5ea6", body)
        self.assertIn("\\u521b\\u610f\\u5ea6", body)
        self.assertIn("6.5", body)
        self.assertIn("8.0", body)


if __name__ == "__main__":
    unittest.main()
