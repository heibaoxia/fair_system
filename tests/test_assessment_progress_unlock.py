from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.api.scoring import get_assessment_progress
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


def seed_project(db, *, assessment_end):
    owner = models.Member(name="Owner", tel="13800002001", is_active=True)
    member_a = models.Member(name="Member A", tel="13800002002", is_active=True)
    member_b = models.Member(name="Member B", tel="13800002003", is_active=True)
    db.add_all([owner, member_a, member_b])
    db.flush()

    project = models.Project(
        name="Progress Project",
        description="",
        created_by=owner.id,
        assessment_start=datetime.now() - timedelta(hours=2),
        assessment_end=assessment_end,
    )
    project.members.extend([owner, member_a, member_b])
    db.add(project)
    db.flush()

    module_a = models.Module(name="模块A", project_id=project.id, status="待分配")
    module_b = models.Module(name="模块B", project_id=project.id, status="待分配")
    db.add_all([module_a, module_b])
    db.commit()
    return project, owner, member_a, member_b, module_a, module_b


def add_full_assessments(db, members, modules):
    for member in members:
        for module in modules:
            db.add(models.ModuleAssessment(
                member_id=member.id,
                module_id=module.id,
                difficulty_score=6.0,
                estimated_hours=4.0,
                boredom_score=5.0,
                intensity_score=7.0,
            ))
    db.commit()


def test_effective_completion_true_after_everyone_finishes_assessments():
    engine, db = build_session()
    try:
        project, owner, member_a, member_b, module_a, module_b = seed_project(
            db,
            assessment_end=datetime.now() + timedelta(hours=4),
        )
        add_full_assessments(db, [owner, member_a, member_b], [module_a, module_b])

        progress = get_assessment_progress(project.id, db=db)

        assert progress["is_expired"] is False
        assert progress["all_done"] is True
        assert progress["effective_completion"] is True
        assert all(item["status"] == "已完成" for item in progress["members_progress"])
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_effective_completion_true_before_deadline_when_everyone_already_finished():
    engine, db = build_session()
    try:
        project, owner, member_a, member_b, module_a, module_b = seed_project(
            db,
            assessment_end=datetime.now() + timedelta(minutes=30),
        )
        add_full_assessments(db, [owner, member_a, member_b], [module_a, module_b])

        progress = get_assessment_progress(project.id, db=db)

        assert progress["assessment_period"]["end"] is not None
        assert progress["is_expired"] is False
        assert progress["effective_completion"] is True
        assert progress["all_done"] is True
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
