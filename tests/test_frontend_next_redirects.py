from fastapi.testclient import TestClient
import pytest

from app import models
from tests.frontend_session_helpers import (
    build_frontend_session_test_app,
    register_member_session,
)


def seed_frontend_redirect_member(testing_session_local):
    db = testing_session_local()
    try:
        member = models.Member(
            name="Frontend Redirect Member",
            tel="13800017001",
            is_active=True,
        )
        db.add(member)
        db.commit()
        return {"member_id": member.id}
    finally:
        db.close()


@pytest.mark.parametrize("route", ["/login", "/register"])
def test_auth_pages_keep_safe_local_next_paths_for_authenticated_users(route):
    harness = build_frontend_session_test_app()
    world = seed_frontend_redirect_member(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["member_id"],
            login_id="frontend-next-safe",
        )

        response = client.get(
            route,
            params={"next": "/todo?tab=mine"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/todo?tab=mine"
    finally:
        client.close()
        harness.close()


@pytest.mark.parametrize("route", ["/login", "/register"])
@pytest.mark.parametrize(
    "unsafe_next",
    [
        "//evil.com",
        "///evil.com",
        "/\\evil.com",
        "https://evil.com/phish",
    ],
)
def test_auth_pages_reject_unsafe_next_targets_for_authenticated_users(route, unsafe_next):
    harness = build_frontend_session_test_app()
    world = seed_frontend_redirect_member(harness.testing_session_local)
    client = TestClient(harness.app)

    try:
        register_member_session(
            client,
            member_id=world["member_id"],
            login_id="frontend-next-unsafe",
        )

        response = client.get(
            route,
            params={"next": unsafe_next},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/"
    finally:
        client.close()
        harness.close()
