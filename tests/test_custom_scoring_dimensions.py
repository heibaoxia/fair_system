from datetime import datetime, timedelta
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.api import assessments, projects, scoring
from app.database import Base


class CustomScoringDimensionsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = TestingSessionLocal()

        self.owner = models.Member(name="Owner", tel="13800000001", is_active=True)
        self.member = models.Member(name="Member", tel="13800000002", is_active=True)
        self.db.add_all([self.owner, self.member])
        self.db.commit()
        self.db.refresh(self.owner)
        self.db.refresh(self.member)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_project_without_dimensions_creates_default_dimension_records(self):
        payload = schemas.ProjectCreate(
            name="Default Dimension Project",
            description="",
            new_modules=[],
            dependencies=[],
        )

        project = projects.create_project(payload, created_by_member_id=self.owner.id, db=self.db)

        self.db.refresh(project)
        dimension_names = [item.name for item in project.scoring_dimensions]
        self.assertTrue(project.use_custom_dimensions)
        self.assertEqual(dimension_names, ["难度", "时长", "枯燥度", "强度"])
        self.assertEqual(sum(item.weight for item in project.scoring_dimensions), 1.0)

    def test_create_assessment_rejects_dimension_from_other_project(self):
        project = models.Project(
            name="Scored Project",
            description="",
            created_by=self.owner.id,
            use_custom_dimensions=True,
            assessment_start=datetime.now() - timedelta(hours=1),
            assessment_end=datetime.now() + timedelta(hours=1),
        )
        project.members.extend([self.owner, self.member])
        self.db.add(project)
        self.db.flush()

        module = models.Module(name="Module A", project_id=project.id)
        self.db.add(module)

        valid_dimension = models.ScoringDimension(project_id=project.id, name="难度", weight=1.0, sort_order=0)
        self.db.add(valid_dimension)

        other_project = models.Project(
            name="Other Project",
            description="",
            created_by=self.owner.id,
            use_custom_dimensions=True,
        )
        self.db.add(other_project)
        self.db.flush()
        foreign_dimension = models.ScoringDimension(project_id=other_project.id, name="外部维度", weight=1.0, sort_order=0)
        self.db.add(foreign_dimension)
        self.db.commit()

        payload = schemas.AssessmentCreate(
            member_id=self.member.id,
            module_id=module.id,
            dimension_scores=[schemas.DimensionScoreCreate(dimension_id=foreign_dimension.id, score=8.5)],
        )

        with self.assertRaises(HTTPException) as exc_info:
            assessments.create_assessment(payload, db=self.db)

        self.assertEqual(exc_info.exception.status_code, 400)
        self.assertEqual(exc_info.exception.detail, "存在不属于当前项目的评分维度")

    def test_custom_dimension_summary_uses_dynamic_weighted_scores(self):
        project = models.Project(
            name="Dynamic Summary Project",
            description="",
            created_by=self.owner.id,
            use_custom_dimensions=True,
        )
        self.db.add(project)
        self.db.flush()

        module = models.Module(name="Module A", project_id=project.id)
        self.db.add(module)
        self.db.flush()

        dimension_a = models.ScoringDimension(project_id=project.id, name="难度", weight=0.6, sort_order=0)
        dimension_b = models.ScoringDimension(project_id=project.id, name="创意度", weight=0.4, sort_order=1)
        self.db.add_all([dimension_a, dimension_b])
        self.db.flush()

        assessment_1 = models.ModuleAssessment(member_id=self.owner.id, module_id=module.id)
        assessment_2 = models.ModuleAssessment(member_id=self.member.id, module_id=module.id)
        self.db.add_all([assessment_1, assessment_2])
        self.db.flush()

        self.db.add_all([
            models.DimensionScore(assessment_id=assessment_1.id, dimension_id=dimension_a.id, score=8.0),
            models.DimensionScore(assessment_id=assessment_1.id, dimension_id=dimension_b.id, score=6.0),
            models.DimensionScore(assessment_id=assessment_2.id, dimension_id=dimension_a.id, score=4.0),
            models.DimensionScore(assessment_id=assessment_2.id, dimension_id=dimension_b.id, score=10.0),
        ])
        self.db.commit()

        summary = scoring._calc_module_summary(module, project, self.db)

        self.assertEqual(summary["assessment_count"], 2)
        self.assertEqual(summary["composite_score"], 6.8)
        self.assertEqual(summary["weights_used"], {"难度": 0.6, "创意度": 0.4})
        self.assertEqual(summary["breakdown"], {"难度": 3.6, "创意度": 3.2})


if __name__ == "__main__":
    unittest.main()
