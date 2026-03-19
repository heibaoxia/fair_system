from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import dependencies
from app.api.members import router as members_router
from app.services.schema_bootstrap import bootstrap_schema


def build_test_app():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    bootstrap_schema(engine)

    app = FastAPI()
    app.include_router(members_router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = override_get_db
    return app, engine, testing_session_local


def test_create_member_with_only_name_succeeds_and_uses_profile_defaults():
    app, engine, _, = build_test_app()
    client = TestClient(app)

    try:
        response = client.post("/members/", json={"name": "Alice"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["name"] == "Alice"
        assert payload["tel"] is None
        assert payload["gender"] == "private"
        assert payload["public_email"] is False
        assert payload["public_tel"] is False
    finally:
        engine.dispose()


def test_update_member_can_change_gender_and_public_flags_independently():
    app, engine, _ = build_test_app()
    client = TestClient(app)

    try:
        created = client.post("/members/", json={"name": "Alice"}).json()

        gender_update = client.put(
            f"/members/{created['id']}",
            json={"gender": "female"},
        )
        assert gender_update.status_code == 200
        assert gender_update.json()["gender"] == "female"
        assert gender_update.json()["public_email"] is False
        assert gender_update.json()["public_tel"] is False

        email_visibility_update = client.put(
            f"/members/{created['id']}",
            json={"public_email": True},
        )
        assert email_visibility_update.status_code == 200
        assert email_visibility_update.json()["gender"] == "female"
        assert email_visibility_update.json()["public_email"] is True
        assert email_visibility_update.json()["public_tel"] is False

        tel_visibility_update = client.put(
            f"/members/{created['id']}",
            json={"public_tel": True},
        )
        assert tel_visibility_update.status_code == 200
        assert tel_visibility_update.json()["gender"] == "female"
        assert tel_visibility_update.json()["public_email"] is True
        assert tel_visibility_update.json()["public_tel"] is True
    finally:
        engine.dispose()


def test_duplicate_non_empty_tel_is_rejected():
    app, engine, _ = build_test_app()
    client = TestClient(app)

    try:
        first = client.post("/members/", json={"name": "Alice", "tel": "13800003001"})
        duplicate = client.post("/members/", json={"name": "Bob", "tel": "13800003001"})

        assert first.status_code == 200
        assert duplicate.status_code == 400
    finally:
        engine.dispose()


def test_multiple_members_with_tel_omitted_or_null_succeed():
    app, engine, _ = build_test_app()
    client = TestClient(app)

    try:
        responses = [
            client.post("/members/", json={"name": "Alice"}),
            client.post("/members/", json={"name": "Bob", "tel": None}),
            client.post("/members/", json={"name": "Carol"}),
        ]

        assert [response.status_code for response in responses] == [200, 200, 200]
        assert [response.json()["tel"] for response in responses] == [None, None, None]
    finally:
        engine.dispose()


def test_bootstrap_adds_member_profile_columns_to_legacy_sqlite_tables(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-member-profile.db'}",
        connect_args={"check_same_thread": False},
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE members (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR,
                    tel VARCHAR UNIQUE,
                    email VARCHAR,
                    is_active BOOLEAN DEFAULT 1,
                    skills VARCHAR DEFAULT '',
                    available_hours FLOAT DEFAULT 0.0,
                    total_earnings FLOAT DEFAULT 0.0,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO members (id, name, tel, email, is_active, skills, available_hours, total_earnings)
                VALUES (1, 'Legacy Alice', NULL, NULL, 1, '', 0.0, 0.0)
                """
            )
        )

    try:
        bootstrap_schema(engine)

        with engine.begin() as connection:
            columns = {
                row[1] for row in connection.execute(text("PRAGMA table_info(members)"))
            }
            legacy_row = connection.execute(
                text(
                    """
                    SELECT gender, public_email, public_tel
                    FROM members
                    WHERE id = 1
                    """
                )
            ).one()

        assert {"gender", "public_email", "public_tel"} <= columns
        assert legacy_row == ("private", 0, 0)
    finally:
        engine.dispose()
