from fastapi.testclient import TestClient

from tests.test_social_api import (
    build_test_app,
    login_as,
    seed_account,
    seed_follow,
)


def test_super_account_caller_gets_403_on_social_endpoints():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        regular = seed_account(
            testing_session_local,
            login_id="isolation-regular",
            name="Isolation Regular",
            email="isolation.regular@example.com",
        )
        admin = seed_account(
            testing_session_local,
            login_id="isolation-admin",
            is_super_account=True,
            bind_member=False,
        )
        login_as(client, testing_session_local, account_id=admin.account_id)

        search_response = client.get(f"/social/search?account_id={regular.account_id}")
        relationships_response = client.get("/social/relationships")
        follow_response = client.post(f"/social/follow/{regular.account_id}")
        unfollow_response = client.delete(f"/social/follow/{regular.account_id}")

        assert search_response.status_code == 403
        assert relationships_response.status_code == 403
        assert follow_response.status_code == 403
        assert unfollow_response.status_code == 403
    finally:
        engine.dispose()


def test_super_accounts_and_virtual_identities_do_not_appear_in_social_search_results():
    app, engine, testing_session_local = build_test_app()
    client = TestClient(app)

    try:
        viewer = seed_account(
            testing_session_local,
            login_id="isolation-viewer",
            name="Isolation Viewer",
            email="isolation.viewer@example.com",
        )
        super_account = seed_account(
            testing_session_local,
            login_id="isolation-super-target",
            is_super_account=True,
            bind_member=False,
        )
        virtual_account = seed_account(
            testing_session_local,
            login_id="isolation-virtual-target",
            name="Isolation Virtual Target",
            email="isolation.virtual.target@example.com",
            is_virtual_identity=True,
        )
        visible_friend = seed_account(
            testing_session_local,
            login_id="isolation-visible-friend",
            name="Isolation Visible Friend",
            email="isolation.visible.friend@example.com",
        )
        seed_follow(
            testing_session_local,
            follower_account_id=viewer.account_id,
            followed_account_id=super_account.account_id,
        )
        seed_follow(
            testing_session_local,
            follower_account_id=virtual_account.account_id,
            followed_account_id=viewer.account_id,
        )
        seed_follow(
            testing_session_local,
            follower_account_id=viewer.account_id,
            followed_account_id=visible_friend.account_id,
        )
        seed_follow(
            testing_session_local,
            follower_account_id=visible_friend.account_id,
            followed_account_id=viewer.account_id,
        )
        login_as(client, testing_session_local, account_id=viewer.account_id)

        super_response = client.get(f"/social/search?account_id={super_account.account_id}")
        virtual_response = client.get(f"/social/search?account_id={virtual_account.account_id}")
        relationships_response = client.get("/social/relationships")

        assert super_response.status_code == 200
        assert virtual_response.status_code == 200
        assert relationships_response.status_code == 200
        assert super_response.json() == {"results": []}
        assert virtual_response.json() == {"results": []}
        assert relationships_response.json() == {
            "following": [],
            "followers": [],
            "friends": [
                {
                    "account_id": visible_friend.account_id,
                    "username": "Isolation Visible Friend",
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
