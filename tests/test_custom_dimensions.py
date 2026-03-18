from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.api import assessments, projects, scoring
from app.database import Base


def build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return engine, TestingSessionLocal()


def seed_members(db):
    owner = models.Member(name="Owner", tel="13800001001", is_active=True)
    scorer = models.Member(name="Scorer", tel="13800001002", is_active=True)
    db.add_all([owner, scorer])
    db.commit()
    db.refresh(owner)
    db.refresh(scorer)
    return owner, scorer


def test_create_project_with_custom_dimensions():
    engine, db = build_session()
    try:
        owner, _ = seed_members(db)

        payload = schemas.ProjectCreate(
            name="Custom Dimension Project",
            description="",
            new_modules=[],
            dependencies=[],
            scoring_dimensions=[
                schemas.ScoringDimensionCreate(name="难度", weight=0.5),
                schemas.ScoringDimensionCreate(name="创意度", weight=0.3),
                schemas.ScoringDimensionCreate(name="沟通成本", weight=0.2),
            ],
        )

        project = projects.create_project(payload, created_by_member_id=owner.id, db=db)
        db.refresh(project)

        assert project.use_custom_dimensions is True
        assert [item.name for item in project.scoring_dimensions] == ["难度", "创意度", "沟通成本"]
        assert [item.weight for item in project.scoring_dimensions] == [0.5, 0.3, 0.2]
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_submit_assessment_with_custom_dimension_scores():
    engine, db = build_session()
    try:
        owner, scorer = seed_members(db)
        project = models.Project(
            name="Assessment Project",
            description="",
            created_by=owner.id,
            use_custom_dimensions=True,
            assessment_start=datetime.now() - timedelta(hours=1),
            assessment_end=datetime.now() + timedelta(hours=1),
        )
        project.members.extend([owner, scorer])
        db.add(project)
        db.flush()

        module = models.Module(name="Module A", project_id=project.id, status="待分配")
        db.add(module)
        db.flush()

        difficulty = models.ScoringDimension(project_id=project.id, name="难度", weight=0.6, sort_order=0)
        creativity = models.ScoringDimension(project_id=project.id, name="创意度", weight=0.4, sort_order=1)
        db.add_all([difficulty, creativity])
        db.commit()

        payload = schemas.AssessmentCreate(
            member_id=scorer.id,
            module_id=module.id,
            dimension_scores=[
                schemas.DimensionScoreCreate(dimension_id=difficulty.id, score=5.6),
                schemas.DimensionScoreCreate(dimension_id=creativity.id, score=7.3),
            ],
        )

        created = assessments.create_assessment(payload, db=db)
        db.refresh(created)

        assert created.member_id == scorer.id
        assert created.module_id == module.id
        assert len(created.dimension_scores) == 2
        assert sorted((item.dimension_id, item.score) for item in created.dimension_scores) == sorted([
            (difficulty.id, 5.6),
            (creativity.id, 7.3),
        ])
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_custom_dimension_weighted_summary():
    engine, db = build_session()
    try:
        owner, scorer = seed_members(db)
        project = models.Project(
            name="Summary Project",
            description="",
            created_by=owner.id,
            use_custom_dimensions=True,
        )
        db.add(project)
        db.flush()

        module = models.Module(name="Module A", project_id=project.id, status="待分配")
        db.add(module)
        db.flush()

        difficulty = models.ScoringDimension(project_id=project.id, name="难度", weight=0.5, sort_order=0)
        creativity = models.ScoringDimension(project_id=project.id, name="创意度", weight=0.3, sort_order=1)
        communication = models.ScoringDimension(project_id=project.id, name="沟通成本", weight=0.2, sort_order=2)
        db.add_all([difficulty, creativity, communication])
        db.flush()

        assessment_a = models.ModuleAssessment(member_id=owner.id, module_id=module.id)
        assessment_b = models.ModuleAssessment(member_id=scorer.id, module_id=module.id)
        db.add_all([assessment_a, assessment_b])
        db.flush()

        db.add_all([
            models.DimensionScore(assessment_id=assessment_a.id, dimension_id=difficulty.id, score=8.0),
            models.DimensionScore(assessment_id=assessment_a.id, dimension_id=creativity.id, score=6.0),
            models.DimensionScore(assessment_id=assessment_a.id, dimension_id=communication.id, score=5.0),
            models.DimensionScore(assessment_id=assessment_b.id, dimension_id=difficulty.id, score=4.0),
            models.DimensionScore(assessment_id=assessment_b.id, dimension_id=creativity.id, score=8.0),
            models.DimensionScore(assessment_id=assessment_b.id, dimension_id=communication.id, score=7.0),
        ])
        db.commit()

        summary = scoring._calc_module_summary(module, project, db)

        assert summary["assessment_count"] == 2
        assert summary["weights_used"] == {"难度": 0.5, "创意度": 0.3, "沟通成本": 0.2}
        assert summary["breakdown"] == {"难度": 3.0, "创意度": 2.1, "沟通成本": 1.2}
        assert summary["composite_score"] == 6.3
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
