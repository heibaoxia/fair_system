from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import models
from tests.frontend_session_helpers import (
    assert_login_redirect,
    build_frontend_session_test_app,
    register_member_session,
)


def seed_scoring_world(testing_session_local):
    db = testing_session_local()
    try:
        owner = models.Member(name="Owner", tel="13800011001", is_active=True)
        scorer = models.Member(name="Scorer", tel="13800011002", is_active=True)
        outsider = models.Member(name="Outsider", tel="13800011003", is_active=True)
        db.add_all([owner, scorer, outsider])
        db.flush()

        project = models.Project(
            name="Scoring Project",
            description="Session-only scoring page",
            created_by=owner.id,
            assessment_start=datetime.now() - timedelta(hours=1),
            assessment_end=datetime.now() + timedelta(hours=2),
        )
        project.members.extend([owner, scorer])
        db.add(project)
        db.flush()

        module_a = models.Module(name="Module A", description="Alpha", project_id=project.id)
        module_b = models.Module(name="Module B", description="Beta", project_id=project.id)
        db.add_all([module_a, module_b])
        db.flush()

        dimension_a = models.ScoringDimension(
            project_id=project.id,
            name="Difficulty",
            weight=0.5,
            sort_order=0,
        )
        dimension_b = models.ScoringDimension(
            project_id=project.id,
            name="Creativity",
            weight=0.5,
            sort_order=1,
        )
        db.add_all([dimension_a, dimension_b])
        db.flush()

        assessment = models.ModuleAssessment(member_id=scorer.id, module_id=module_a.id)
        db.add(assessment)
        db.flush()
        db.add_all(
            [
                models.DimensionScore(
                    assessment_id=assessment.id,
                    dimension_id=dimension_a.id,
                    score=6.5,
                ),
                models.DimensionScore(
                    assessment_id=assessment.id,
                    dimension_id=dimension_b.id,
                    score=8.0,
                ),
            ]
        )
        db.commit()

        return {
            "project_id": project.id,
            "owner_id": owner.id,
            "scorer_id": scorer.id,
            "outsider_id": outsider.id,
        }
    finally:
        db.close()


def test_scoring_page_requires_login_and_preserves_next_url():
    harness = build_frontend_session_test_app()
    world = seed_scoring_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        response = client.get(
            f"/scoring/{world['project_id']}?member_id={world['scorer_id']}",
            follow_redirects=False,
        )

        assert_login_redirect(
            response,
            f"/scoring/{world['project_id']}?member_id={world['scorer_id']}",
        )
    finally:
        client.close()
        harness.close()


def test_scoring_page_uses_cookie_session_not_member_id_query_param():
    harness = build_frontend_session_test_app()
    world = seed_scoring_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["scorer_id"],
            login_id="scorer-login",
        )

        response = client.get(f"/scoring/{world['project_id']}?member_id={world['outsider_id']}")
        body = response.text

        assert response.status_code == 200
        assert "Scorer" in body
        assert "const scoringDimensions =" in body
        assert "const scoringModules =" in body
        assert "Module A" in body
        assert "Module B" in body
        assert "Difficulty" in body
        assert "Creativity" in body
        assert "6.5" in body
        assert "8.0" in body
    finally:
        client.close()
        harness.close()


def test_scoring_page_rejects_non_project_member_even_if_query_param_targets_project_member():
    harness = build_frontend_session_test_app()
    world = seed_scoring_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["outsider_id"],
            login_id="outsider-login",
        )

        response = client.get(f"/scoring/{world['project_id']}?member_id={world['scorer_id']}")

        assert response.status_code == 403
    finally:
        client.close()
        harness.close()


def test_scoring_page_redirects_to_login_after_logout():
    harness = build_frontend_session_test_app()
    world = seed_scoring_world(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["scorer_id"],
            login_id="logout-scorer",
        )

        pre_logout = client.get(f"/scoring/{world['project_id']}")
        assert pre_logout.status_code == 200

        logout_response = client.post("/auth/logout")
        assert logout_response.status_code == 200
        assert "session_token=" in logout_response.headers.get("set-cookie", "")

        post_logout = client.get(
            f"/scoring/{world['project_id']}",
            follow_redirects=False,
        )
        assert_login_redirect(post_logout, f"/scoring/{world['project_id']}")
    finally:
        client.close()
        harness.close()
