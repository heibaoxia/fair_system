from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.api import auth, dependencies, frontend
from app.api.auth import router as auth_router
from app.database import Base
from app.services.auth_service import issue_email_verification_token, register_account, verify_email_token
from app.services.email_sender import VerificationEmailMessage
from app.services.schema_bootstrap import bootstrap_schema


@dataclass
class FrontendSessionTestApp:
    app: FastAPI
    engine: Any
    testing_session_local: sessionmaker

    def close(self) -> None:
        self.app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()


class RecordingEmailSender:
    def __init__(self):
        self.messages: list[VerificationEmailMessage] = []

    def send_verification_email(self, message: VerificationEmailMessage) -> None:
        self.messages.append(message)


def build_frontend_session_test_app() -> FrontendSessionTestApp:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    bootstrap_schema(engine)

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(frontend.router)
    email_sender = RecordingEmailSender()

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = override_get_db
    app.dependency_overrides[auth.get_email_sender] = lambda: email_sender
    app.dependency_overrides[auth.get_verification_base_url] = lambda: "https://example.test/auth/verify-email"
    app.state.test_email_sender = email_sender
    app.state.email_sender = email_sender
    app.state.verification_base_url = "https://example.test/auth/verify-email"
    return FrontendSessionTestApp(
        app=app,
        engine=engine,
        testing_session_local=testing_session_local,
    )


def register_member_session(
    client: TestClient,
    *,
    member_id: int,
    login_id: str,
    password: str = "secret-pass",
) -> None:
    override_get_db = client.app.dependency_overrides[dependencies.get_db]
    db_generator = override_get_db()
    db = next(db_generator)
    try:
        member = db.query(models.Member).filter(models.Member.id == member_id).one()
        if not member.email:
            member.email = f"{login_id}@example.test"
            db.commit()
            db.refresh(member)
        email = member.email
    finally:
        db.close()
        try:
            next(db_generator)
        except StopIteration:
            pass

    db_generator = override_get_db()
    db = next(db_generator)
    try:
        account = register_account(
            db,
            login_id=login_id,
            password=password,
            member_id=member_id,
            email=email,
        )
        issue = issue_email_verification_token(db, account_id=account.id)
        verify_email_token(db, issue.token)
    finally:
        db.close()
        try:
            next(db_generator)
        except StopIteration:
            pass

    login_response = client.post(
        "/auth/login",
        json={
            "login_id": login_id,
            "password": password,
        },
    )
    assert login_response.status_code == 200, login_response.text
    assert "session_token=" in login_response.headers.get("set-cookie", "")


def assert_login_redirect(response, expected_next: str) -> None:
    assert response.status_code == 303
    assert response.headers["location"] == f"/login?next={quote(expected_next, safe='')}"
