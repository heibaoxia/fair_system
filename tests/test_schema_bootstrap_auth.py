import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app import models
from app.services.schema_bootstrap import bootstrap_schema


def get_column_names(engine, table_name):
    with engine.begin() as connection:
        return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table_name})"))}


def test_bootstrap_creates_auth_tables_and_member_email_auth_columns(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fresh.db'}",
        connect_args={"check_same_thread": False},
    )

    bootstrap_schema(engine)

    inspector = inspect(engine)

    assert "accounts" in inspector.get_table_names()
    assert "auth_sessions" in inspector.get_table_names()
    assert "email_verification_tokens" in inspector.get_table_names()
    assert get_column_names(engine, "members") >= {
        "email",
        "is_virtual_identity",
        "total_earnings",
    }
    assert get_column_names(engine, "accounts") >= {
        "login_id",
        "password_hash",
        "email",
        "email_verified_at",
        "registration_status",
        "is_super_account",
        "member_id",
        "is_active",
        "created_at",
    }
    assert get_column_names(engine, "auth_sessions") >= {
        "session_token",
        "account_id",
        "acting_member_id",
        "expires_at",
        "created_at",
        "last_seen_at",
    }


def test_bootstrap_upgrades_legacy_auth_tables_and_rejects_duplicate_emails(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy.db'}",
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
                    is_active BOOLEAN DEFAULT 1,
                    skills VARCHAR DEFAULT '',
                    available_hours FLOAT DEFAULT 0.0,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE accounts (
                    id INTEGER NOT NULL PRIMARY KEY,
                    login_id VARCHAR UNIQUE NOT NULL,
                    password_hash VARCHAR NOT NULL,
                    is_super_account BOOLEAN DEFAULT 0,
                    member_id INTEGER UNIQUE,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME
                )
                """
            )
        )

    bootstrap_schema(engine)

    inspector = inspect(engine)
    member_columns = get_column_names(engine, "members")
    account_columns = get_column_names(engine, "accounts")

    assert "email_verification_tokens" in inspector.get_table_names()
    assert "email" in member_columns
    assert "is_virtual_identity" in member_columns
    assert "total_earnings" in member_columns
    assert "email" in account_columns
    assert "email_verified_at" in account_columns
    assert "registration_status" in account_columns

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        member = models.Member(name="Owner", tel="13800001999", is_active=True)
        db.add(member)
        db.commit()
        db.refresh(member)

        project = models.Project(
            name="Bootstrap Regression Project",
            description="",
            created_by=member.id,
        )
        db.add(project)
        db.flush()

        module = models.Module(
            name="Bootstrap Regression Module",
            project_id=project.id,
        )
        db.add(module)
        db.commit()

        stored_project = db.query(models.Project).filter_by(id=project.id).one()
        stored_module = db.query(models.Module).filter_by(id=module.id).one()

        assert stored_project.created_by == member.id
        assert stored_module.project_id == project.id

        db.add(
            models.Member(
                name="With Email",
                tel="13800001998",
                email="member@example.com",
                is_active=True,
            )
        )
        db.commit()

        db.add(
            models.Member(
                name="Duplicate Email",
                tel="13800001997",
                email="member@example.com",
                is_active=True,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        first_account = models.Account(
            login_id="account-one",
            password_hash="hash-one",
            email="account@example.com",
            member_id=member.id,
        )
        second_member = db.query(models.Member).filter_by(tel="13800001998").one()
        second_account = models.Account(
            login_id="account-two",
            password_hash="hash-two",
            email="account@example.com",
            member_id=second_member.id,
        )

        db.add(first_account)
        db.commit()
        db.add(second_account)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_bootstrap_normalizes_legacy_email_conflicts_and_backfills_virtual_members(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-dirty.db'}",
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
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO members (id, name, tel, email, is_active)
                VALUES
                    (1, 'No Email', '13800002001', NULL, 1),
                    (2, 'Blank Email', '13800002002', '', 1),
                    (3, 'Dup A', '13800002003', 'dup@example.com', 1),
                    (4, 'Dup B', '13800002004', 'dup@example.com', 1),
                    (5, 'Unique', '13800002005', 'unique@example.com', 1)
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE accounts (
                    id INTEGER NOT NULL PRIMARY KEY,
                    login_id VARCHAR UNIQUE NOT NULL,
                    password_hash VARCHAR NOT NULL,
                    email VARCHAR,
                    is_super_account BOOLEAN DEFAULT 0,
                    member_id INTEGER UNIQUE,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO accounts (id, login_id, password_hash, email, member_id, is_active)
                VALUES
                    (1, 'acc-blank', 'hash-1', '', 1, 1),
                    (2, 'acc-dup-a', 'hash-2', 'account-dup@example.com', 3, 1),
                    (3, 'acc-dup-b', 'hash-3', 'account-dup@example.com', 4, 1)
                """
            )
        )

    with pytest.warns(RuntimeWarning) as caught_warnings:
        bootstrap_schema(engine)

    with engine.begin() as connection:
        members = list(
            connection.execute(
                text(
                    "SELECT tel, email, is_virtual_identity FROM members ORDER BY id"
                )
            )
        )
        accounts = list(
            connection.execute(
                text(
                    "SELECT login_id, email, registration_status, is_active FROM accounts ORDER BY id"
                )
            )
        )

    warning_messages = [str(item.message) for item in caught_warnings]

    assert len(warning_messages) == 3
    assert any(
        "members.email" in message
        and "duplicate non-empty legacy emails" in message
        and "require follow-up" in message
        for message in warning_messages
    )
    assert any(
        "accounts.email" in message
        and "duplicate non-empty legacy emails" in message
        and "require follow-up" in message
        for message in warning_messages
    )
    assert any(
        "virtualized legacy members" in message
        and "deactivated 3 bound account" in message
        for message in warning_messages
    )
    assert members == [
        ("13800002001", None, 1),
        ("13800002002", None, 1),
        ("13800002003", None, 1),
        ("13800002004", None, 1),
        ("13800002005", "unique@example.com", 0),
    ]
    assert accounts == [
        ("acc-blank", None, "pending_verification", 0),
        ("acc-dup-a", None, "pending_verification", 0),
        ("acc-dup-b", None, "pending_verification", 0),
    ]


def test_bootstrap_reconciles_accounts_for_virtualized_members(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-reconcile.db'}",
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
                    created_at DATETIME,
                    is_virtual_identity BOOLEAN DEFAULT 0
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO members (id, name, tel, email, is_active, is_virtual_identity)
                VALUES
                    (1, 'Needs Reconcile', '13800002101', NULL, 1, 0),
                    (2, 'Keeps Email', '13800002102', 'keep@example.com', 1, 0)
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE accounts (
                    id INTEGER NOT NULL PRIMARY KEY,
                    login_id VARCHAR UNIQUE NOT NULL,
                    password_hash VARCHAR NOT NULL,
                    email VARCHAR,
                    is_super_account BOOLEAN DEFAULT 0,
                    member_id INTEGER UNIQUE,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO accounts (id, login_id, password_hash, email, is_super_account, member_id, is_active, created_at)
                VALUES
                    (1, 'legacy-user', 'hash-1', 'legacy-user@example.com', 0, 1, 1, '2026-03-19 10:00:00'),
                    (2, 'kept-user', 'hash-2', 'keep@example.com', 0, 2, 1, '2026-03-19 10:00:00')
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE auth_sessions (
                    id INTEGER NOT NULL PRIMARY KEY,
                    session_token VARCHAR UNIQUE NOT NULL,
                    account_id INTEGER NOT NULL,
                    acting_member_id INTEGER,
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME,
                    last_seen_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO auth_sessions (id, session_token, account_id, acting_member_id, expires_at, created_at, last_seen_at)
                VALUES
                    (1, 'legacy-session', 1, 1, '2026-03-20 10:00:00', '2026-03-19 10:00:00', '2026-03-19 10:00:00'),
                    (2, 'kept-session', 2, 2, '2026-03-20 10:00:00', '2026-03-19 10:00:00', '2026-03-19 10:00:00')
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE email_verification_tokens (
                    id INTEGER NOT NULL PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    email VARCHAR NOT NULL,
                    token_hash VARCHAR UNIQUE NOT NULL,
                    expires_at DATETIME NOT NULL,
                    consumed_at DATETIME,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO email_verification_tokens (id, account_id, email, token_hash, expires_at, consumed_at, created_at)
                VALUES
                    (1, 1, 'legacy-user@example.com', 'legacy-token', '2026-03-20 10:00:00', NULL, '2026-03-19 10:00:00'),
                    (2, 2, 'keep@example.com', 'keep-token', '2026-03-20 10:00:00', NULL, '2026-03-19 10:00:00')
                """
            )
        )

    with pytest.warns(RuntimeWarning) as caught_warnings:
        bootstrap_schema(engine)

    with engine.begin() as connection:
        members = list(
            connection.execute(
                text(
                    "SELECT id, is_virtual_identity FROM members ORDER BY id"
                )
            )
        )
        accounts = list(
            connection.execute(
                text(
                    "SELECT id, is_active, member_id FROM accounts ORDER BY id"
                )
            )
        )
        sessions = list(
            connection.execute(
                text(
                    "SELECT id, account_id FROM auth_sessions ORDER BY id"
                )
            )
        )
        tokens = list(
            connection.execute(
                text(
                    "SELECT id, account_id FROM email_verification_tokens ORDER BY id"
                )
            )
        )

    warning_messages = [str(item.message) for item in caught_warnings]

    assert any(
        "virtualized legacy members" in message
        and "deactivated 1 bound account" in message
        and "cleared 1 session" in message
        and "cleared 1 verification token" in message
        for message in warning_messages
    )
    assert members == [(1, 1), (2, 0)]
    assert accounts == [(1, 0, 1), (2, 1, 2)]
    assert sessions == [(2, 2)]
    assert tokens == [(2, 2)]
