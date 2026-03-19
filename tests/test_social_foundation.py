from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app import models
from app.services import social_service
from tests.test_social_api import build_test_app, seed_account


def test_visible_regular_account_is_included():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="foundation-viewer",
            name="Foundation Viewer",
            email="foundation.viewer@example.com",
        )
        target = seed_account(
            testing_session_local,
            login_id="foundation-target",
            name="Foundation Target",
            email="foundation.target@example.com",
            tel="13800006001",
            gender="male",
            public_email=True,
            public_tel=True,
        )

        db = testing_session_local()
        try:
            results = social_service.search_visible_accounts(
                db,
                viewer_account_id=viewer.account_id,
                account_id=target.account_id,
            )
        finally:
            db.close()

        assert results == [
            {
                "account_id": target.account_id,
                "username": "Foundation Target",
                "gender": "男",
                "email": "foundation.target@example.com",
                "tel": "13800006001",
                "is_following": False,
                "is_follower": False,
                "is_friend": False,
            }
        ]
    finally:
        engine.dispose()


def test_private_gender_uses_required_display_label():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="foundation-private-viewer",
            name="Foundation Private Viewer",
            email="foundation.private.viewer@example.com",
        )
        private_target = seed_account(
            testing_session_local,
            login_id="foundation-private-target",
            name="Foundation Private Target",
            email="foundation.private.target@example.com",
            gender="private",
        )

        db = testing_session_local()
        try:
            results = social_service.search_visible_accounts(
                db,
                viewer_account_id=viewer.account_id,
                account_id=private_target.account_id,
            )
        finally:
            db.close()

        assert results == [
            {
                "account_id": private_target.account_id,
                "username": "Foundation Private Target",
                "gender": "\u4fdd\u5bc6",
                "email": None,
                "tel": None,
                "is_following": False,
                "is_follower": False,
                "is_friend": False,
            }
        ]
    finally:
        engine.dispose()


def test_super_account_is_excluded_from_social_visibility():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="foundation-regular",
            name="Foundation Regular",
            email="foundation.regular@example.com",
        )
        super_account = seed_account(
            testing_session_local,
            login_id="foundation-super",
            is_super_account=True,
            bind_member=False,
        )

        db = testing_session_local()
        try:
            results = social_service.search_visible_accounts(
                db,
                viewer_account_id=viewer.account_id,
                account_id=super_account.account_id,
            )
        finally:
            db.close()

        assert results == []
    finally:
        engine.dispose()


def test_inactive_account_is_excluded_from_social_visibility():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="foundation-active",
            name="Foundation Active",
            email="foundation.active@example.com",
        )
        inactive = seed_account(
            testing_session_local,
            login_id="foundation-inactive",
            name="Foundation Inactive",
            email="foundation.inactive@example.com",
            account_is_active=False,
        )

        db = testing_session_local()
        try:
            results = social_service.search_visible_accounts(
                db,
                viewer_account_id=viewer.account_id,
                account_id=inactive.account_id,
            )
        finally:
            db.close()

        assert results == []
    finally:
        engine.dispose()


def test_pending_and_unverified_accounts_are_excluded_from_social_visibility():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="foundation-authenticated-viewer",
            name="Foundation Authenticated Viewer",
            email="foundation.authenticated.viewer@example.com",
        )
        pending = seed_account(
            testing_session_local,
            login_id="foundation-pending-target",
            name="Foundation Pending Target",
            email="foundation.pending.target@example.com",
            registration_status="pending_verification",
            is_email_verified=False,
        )
        unverified = seed_account(
            testing_session_local,
            login_id="foundation-unverified-target",
            name="Foundation Unverified Target",
            email="foundation.unverified.target@example.com",
            is_email_verified=False,
        )

        db = testing_session_local()
        try:
            pending_results = social_service.search_visible_accounts(
                db,
                viewer_account_id=viewer.account_id,
                account_id=pending.account_id,
            )
            unverified_results = social_service.search_visible_accounts(
                db,
                viewer_account_id=viewer.account_id,
                account_id=unverified.account_id,
            )
        finally:
            db.close()

        assert pending_results == []
        assert unverified_results == []
    finally:
        engine.dispose()


def test_virtual_member_bound_account_is_excluded_from_social_visibility():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="foundation-virtual-viewer",
            name="Foundation Virtual Viewer",
            email="foundation.virtual.viewer@example.com",
        )
        virtual_account = seed_account(
            testing_session_local,
            login_id="foundation-virtual-target",
            name="Foundation Virtual Target",
            email="foundation.virtual.target@example.com",
            is_virtual_identity=True,
        )

        db = testing_session_local()
        try:
            results = social_service.search_visible_accounts(
                db,
                viewer_account_id=viewer.account_id,
                account_id=virtual_account.account_id,
            )
        finally:
            db.close()

        assert results == []
    finally:
        engine.dispose()


def test_unrelated_follow_integrity_error_is_not_swallowed(monkeypatch):
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="foundation-commit-viewer",
            name="Foundation Commit Viewer",
            email="foundation.commit.viewer@example.com",
        )
        target = seed_account(
            testing_session_local,
            login_id="foundation-commit-target",
            name="Foundation Commit Target",
            email="foundation.commit.target@example.com",
        )

        db = testing_session_local()
        try:
            def broken_commit():
                raise IntegrityError("INSERT INTO account_follows", {}, Exception("foreign key mismatch"))

            monkeypatch.setattr(db, "commit", broken_commit)

            try:
                social_service.follow_account(
                    db,
                    follower_account_id=viewer.account_id,
                    target_account_id=target.account_id,
                )
            except IntegrityError as exc:
                assert "foreign key mismatch" in str(exc.orig)
            else:
                raise AssertionError("Expected unrelated IntegrityError to be raised.")
        finally:
            db.close()
    finally:
        engine.dispose()


def test_concurrent_duplicate_follow_integrity_error_is_suppressed_after_rollback(monkeypatch):
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="foundation-concurrent-viewer",
            name="Foundation Concurrent Viewer",
            email="foundation.concurrent.viewer@example.com",
        )
        target = seed_account(
            testing_session_local,
            login_id="foundation-concurrent-target",
            name="Foundation Concurrent Target",
            email="foundation.concurrent.target@example.com",
        )

        db = testing_session_local()
        try:
            commit_calls = {"count": 0}

            def concurrent_duplicate_commit():
                commit_calls["count"] += 1
                competing_db = testing_session_local()
                try:
                    competing_db.add(
                        models.AccountFollow(
                            follower_account_id=viewer.account_id,
                            followed_account_id=target.account_id,
                        )
                    )
                    competing_db.commit()
                finally:
                    competing_db.close()
                raise IntegrityError(
                    "INSERT INTO account_follows",
                    {},
                    Exception(
                        "UNIQUE constraint failed: "
                        "account_follows.follower_account_id, "
                        "account_follows.followed_account_id"
                    ),
                )

            monkeypatch.setattr(db, "commit", concurrent_duplicate_commit)

            social_service.follow_account(
                db,
                follower_account_id=viewer.account_id,
                target_account_id=target.account_id,
            )

            assert commit_calls["count"] == 1

            verification_db = testing_session_local()
            try:
                assert (
                    verification_db.query(models.AccountFollow)
                    .filter(
                        models.AccountFollow.follower_account_id == viewer.account_id,
                        models.AccountFollow.followed_account_id == target.account_id,
                    )
                    .count()
                ) == 1
            finally:
                verification_db.close()
        finally:
            db.close()
    finally:
        engine.dispose()
