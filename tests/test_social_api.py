from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.api import dependencies
from app.api.dependencies import SESSION_COOKIE_NAME
from app.api.social import router as social_router
from app.services.auth_service import create_session
from app.services.schema_bootstrap import bootstrap_schema


@dataclass(frozen=True)
class SeededAccount:
    account_id: int
    member_id: int | None
    login_id: str


def build_test_app():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    bootstrap_schema(engine)

    app = FastAPI()
    app.include_router(social_router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = override_get_db
    return app, engine, testing_session_local


def seed_member_only(
    testing_session_local,
    *,
    name: str,
    email: str | None = None,
    tel: str | None = None,
    gender: str = "private",
    public_email: bool = False,
    public_tel: bool = False,
    is_active: bool = True,
    is_virtual_identity: bool = False,
) -> int:
    db = testing_session_local()
    try:
        member = models.Member(
            name=name,
            email=email,
            tel=tel,
            gender=gender,
            public_email=public_email,
            public_tel=public_tel,
            is_active=is_active,
            is_virtual_identity=is_virtual_identity,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        return member.id
    finally:
        db.close()


def seed_account(
    testing_session_local,
    *,
    login_id: str,
    name: str | None = None,
    email: str | None = None,
    tel: str | None = None,
    gender: str = "private",
    public_email: bool = False,
    public_tel: bool = False,
    account_is_active: bool = True,
    member_is_active: bool = True,
    is_super_account: bool = False,
    is_virtual_identity: bool = False,
    bind_member: bool = True,
    registration_status: str = "active",
    is_email_verified: bool = True,
) -> SeededAccount:
    db = testing_session_local()
    try:
        member = None
        if bind_member:
            member = models.Member(
                name=name or login_id,
                email=email,
                tel=tel,
                gender=gender,
                public_email=public_email,
                public_tel=public_tel,
                is_active=member_is_active,
                is_virtual_identity=is_virtual_identity,
            )
            db.add(member)
            db.flush()

        now = datetime.now()
        account = models.Account(
            login_id=login_id,
            password_hash="test-password-hash",
            email=email,
            email_verified_at=now if is_email_verified else None,
            registration_status=registration_status,
            is_super_account=is_super_account,
            member_id=None if member is None else member.id,
            is_active=account_is_active,
            created_at=now,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return SeededAccount(
            account_id=account.id,
            member_id=account.member_id,
            login_id=account.login_id,
        )
    finally:
        db.close()


def seed_follow(testing_session_local, *, follower_account_id: int, followed_account_id: int) -> None:
    db = testing_session_local()
    try:
        db.add(
            models.AccountFollow(
                follower_account_id=follower_account_id,
                followed_account_id=followed_account_id,
            )
        )
        db.commit()
    finally:
        db.close()


def login_as(client: TestClient, testing_session_local, *, account_id: int) -> None:
    db = testing_session_local()
    try:
        session = create_session(db, account_id=account_id)
    finally:
        db.close()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_token)


def get_follow_count(testing_session_local, *, follower_account_id: int, followed_account_id: int) -> int:
    db = testing_session_local()
    try:
        return (
            db.query(models.AccountFollow)
            .filter(
                models.AccountFollow.follower_account_id == follower_account_id,
                models.AccountFollow.followed_account_id == followed_account_id,
            )
            .count()
        )
    finally:
        db.close()


def test_exact_account_id_search():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        seed_member_only(testing_session_local, name="Padding One", email="pad1@example.com")
        seed_member_only(testing_session_local, name="Padding Two", email="pad2@example.com")
        viewer = seed_account(
            testing_session_local,
            login_id="viewer",
            name="Viewer",
            email="viewer@example.com",
            gender="male",
        )
        target = seed_account(
            testing_session_local,
            login_id="target",
            name="Target User",
            email="target@example.com",
            tel="13800005001",
            gender="female",
            public_email=True,
            public_tel=False,
        )
        assert target.member_id != target.account_id
        login_as(client, testing_session_local, account_id=viewer.account_id)

        response = client.get(f"/social/search?account_id={target.account_id}")

        assert response.status_code == 200
        assert response.json() == {
            "results": [
                {
                    "account_id": target.account_id,
                    "username": "Target User",
                    "gender": "女",
                    "email": "target@example.com",
                    "tel": None,
                    "is_following": False,
                    "is_follower": False,
                    "is_friend": False,
                }
            ]
        }

        wrong_identifier = client.get(f"/social/search?account_id={target.member_id}")
        assert wrong_identifier.status_code == 200
        assert wrong_identifier.json() == {"results": []}
    finally:
        engine.dispose()


def test_pending_and_unverified_accounts_are_hidden_from_search():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="viewer-hidden",
            name="Viewer Hidden",
            email="viewer.hidden@example.com",
        )
        pending = seed_account(
            testing_session_local,
            login_id="pending-hidden",
            name="Pending Hidden",
            email="pending.hidden@example.com",
            registration_status="pending_verification",
            is_email_verified=False,
        )
        unverified = seed_account(
            testing_session_local,
            login_id="unverified-hidden",
            name="Unverified Hidden",
            email="unverified.hidden@example.com",
            is_email_verified=False,
        )
        login_as(client, testing_session_local, account_id=viewer.account_id)

        pending_response = client.get(f"/social/search?account_id={pending.account_id}")
        unverified_response = client.get(f"/social/search?account_id={unverified.account_id}")

        assert pending_response.status_code == 200
        assert unverified_response.status_code == 200
        assert pending_response.json() == {"results": []}
        assert unverified_response.json() == {"results": []}
    finally:
        engine.dispose()


def test_follow_success():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="viewer-follow",
            name="Viewer Follow",
            email="viewer.follow@example.com",
        )
        target = seed_account(
            testing_session_local,
            login_id="target-follow",
            name="Target Follow",
            email="target.follow@example.com",
        )
        login_as(client, testing_session_local, account_id=viewer.account_id)

        response = client.post(f"/social/follow/{target.account_id}")

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert get_follow_count(
            testing_session_local,
            follower_account_id=viewer.account_id,
            followed_account_id=target.account_id,
        ) == 1
    finally:
        engine.dispose()


def test_pending_and_unverified_accounts_are_not_followable():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="viewer-not-followable",
            name="Viewer Not Followable",
            email="viewer.not.followable@example.com",
        )
        pending = seed_account(
            testing_session_local,
            login_id="pending-not-followable",
            name="Pending Not Followable",
            email="pending.not.followable@example.com",
            registration_status="pending_verification",
            is_email_verified=False,
        )
        unverified = seed_account(
            testing_session_local,
            login_id="unverified-not-followable",
            name="Unverified Not Followable",
            email="unverified.not.followable@example.com",
            is_email_verified=False,
        )
        login_as(client, testing_session_local, account_id=viewer.account_id)

        pending_response = client.post(f"/social/follow/{pending.account_id}")
        unverified_response = client.post(f"/social/follow/{unverified.account_id}")

        assert pending_response.status_code == 404
        assert unverified_response.status_code == 404
        assert get_follow_count(
            testing_session_local,
            follower_account_id=viewer.account_id,
            followed_account_id=pending.account_id,
        ) == 0
        assert get_follow_count(
            testing_session_local,
            follower_account_id=viewer.account_id,
            followed_account_id=unverified.account_id,
        ) == 0
    finally:
        engine.dispose()


def test_mutual_follow_moves_account_into_friends_bucket():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="viewer-friends",
            name="Viewer Friends",
            email="viewer.friends@example.com",
        )
        friend = seed_account(
            testing_session_local,
            login_id="friend-friends",
            name="Friend Friends",
            email="friend.friends@example.com",
        )
        seed_follow(
            testing_session_local,
            follower_account_id=friend.account_id,
            followed_account_id=viewer.account_id,
        )
        login_as(client, testing_session_local, account_id=viewer.account_id)

        follow_response = client.post(f"/social/follow/{friend.account_id}")
        relationships_response = client.get("/social/relationships")

        assert follow_response.status_code == 200
        assert relationships_response.status_code == 200
        assert relationships_response.json() == {
            "following": [],
            "followers": [],
            "friends": [
                {
                    "account_id": friend.account_id,
                    "username": "Friend Friends",
                    "gender": "保密",
                    "email": None,
                    "tel": None,
                    "is_following": True,
                    "is_follower": True,
                    "is_friend": True,
                }
            ],
        }
    finally:
        engine.dispose()


def test_unfollow_downgrades_friendship():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="viewer-unfollow",
            name="Viewer Unfollow",
            email="viewer.unfollow@example.com",
        )
        former_friend = seed_account(
            testing_session_local,
            login_id="friend-unfollow",
            name="Former Friend",
            email="friend.unfollow@example.com",
        )
        seed_follow(
            testing_session_local,
            follower_account_id=viewer.account_id,
            followed_account_id=former_friend.account_id,
        )
        seed_follow(
            testing_session_local,
            follower_account_id=former_friend.account_id,
            followed_account_id=viewer.account_id,
        )
        login_as(client, testing_session_local, account_id=viewer.account_id)

        unfollow_response = client.delete(f"/social/follow/{former_friend.account_id}")
        relationships_response = client.get("/social/relationships")

        assert unfollow_response.status_code == 200
        assert unfollow_response.json() == {"ok": True}
        assert relationships_response.status_code == 200
        assert relationships_response.json() == {
            "following": [],
            "followers": [
                {
                    "account_id": former_friend.account_id,
                    "username": "Former Friend",
                    "gender": "保密",
                    "email": None,
                    "tel": None,
                    "is_following": False,
                    "is_follower": True,
                    "is_friend": False,
                }
            ],
            "friends": [],
        }
    finally:
        engine.dispose()


def test_cannot_follow_self():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="viewer-self",
            name="Viewer Self",
            email="viewer.self@example.com",
        )
        login_as(client, testing_session_local, account_id=viewer.account_id)

        response = client.post(f"/social/follow/{viewer.account_id}")

        assert response.status_code == 400
    finally:
        engine.dispose()


def test_duplicate_follow_is_idempotent():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="viewer-dup",
            name="Viewer Dup",
            email="viewer.dup@example.com",
        )
        target = seed_account(
            testing_session_local,
            login_id="target-dup",
            name="Target Dup",
            email="target.dup@example.com",
        )
        login_as(client, testing_session_local, account_id=viewer.account_id)

        first = client.post(f"/social/follow/{target.account_id}")
        second = client.post(f"/social/follow/{target.account_id}")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == {"ok": True}
        assert second.json() == {"ok": True}
        assert get_follow_count(
            testing_session_local,
            follower_account_id=viewer.account_id,
            followed_account_id=target.account_id,
        ) == 1
    finally:
        engine.dispose()


def test_relationships_buckets_are_partitioned_correctly():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="viewer-rel",
            name="Viewer Rel",
            email="viewer.rel@example.com",
        )
        following_only = seed_account(
            testing_session_local,
            login_id="following-only",
            name="Following Only",
            email="following.only@example.com",
            gender="male",
        )
        follower_only = seed_account(
            testing_session_local,
            login_id="follower-only",
            name="Follower Only",
            email="follower.only@example.com",
            gender="female",
        )
        friend = seed_account(
            testing_session_local,
            login_id="friend-rel",
            name="Friend Rel",
            email="friend.rel@example.com",
        )
        seed_follow(
            testing_session_local,
            follower_account_id=viewer.account_id,
            followed_account_id=following_only.account_id,
        )
        seed_follow(
            testing_session_local,
            follower_account_id=follower_only.account_id,
            followed_account_id=viewer.account_id,
        )
        seed_follow(
            testing_session_local,
            follower_account_id=viewer.account_id,
            followed_account_id=friend.account_id,
        )
        seed_follow(
            testing_session_local,
            follower_account_id=friend.account_id,
            followed_account_id=viewer.account_id,
        )
        login_as(client, testing_session_local, account_id=viewer.account_id)

        response = client.get("/social/relationships")

        assert response.status_code == 200
        assert response.json() == {
            "following": [
                {
                    "account_id": following_only.account_id,
                    "username": "Following Only",
                    "gender": "男",
                    "email": None,
                    "tel": None,
                    "is_following": True,
                    "is_follower": False,
                    "is_friend": False,
                }
            ],
            "followers": [
                {
                    "account_id": follower_only.account_id,
                    "username": "Follower Only",
                    "gender": "女",
                    "email": None,
                    "tel": None,
                    "is_following": False,
                    "is_follower": True,
                    "is_friend": False,
                }
            ],
            "friends": [
                {
                    "account_id": friend.account_id,
                    "username": "Friend Rel",
                    "gender": "保密",
                    "email": None,
                    "tel": None,
                    "is_following": True,
                    "is_follower": True,
                    "is_friend": True,
                }
            ],
        }
    finally:
        engine.dispose()
