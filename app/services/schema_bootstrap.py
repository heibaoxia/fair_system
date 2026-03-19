import warnings

from sqlalchemy import text

from app import models  # noqa: F401
from app.database import Base, engine as default_engine


def _ensure_column(connection, table_name, column_name, column_definition):
    existing_columns = {
        row[1] for row in connection.execute(text(f"PRAGMA table_info({table_name})"))
    }
    if column_name not in existing_columns:
        connection.execute(
            text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
        )


def _has_unique_index(connection, table_name, column_names):
    target_columns = tuple(column_names)
    for row in connection.execute(text(f"PRAGMA index_list({table_name})")):
        index_name = row[1]
        is_unique = bool(row[2])
        if not is_unique:
            continue
        indexed_columns = tuple(
            index_row[2]
            for index_row in connection.execute(text(f"PRAGMA index_info({index_name})"))
        )
        if indexed_columns == target_columns:
            return True
    return False


def _ensure_unique_index(connection, table_name, index_name, column_names):
    if _has_unique_index(connection, table_name, column_names):
        return
    indexed_columns = ", ".join(column_names)
    connection.execute(
        text(f"CREATE UNIQUE INDEX {index_name} ON {table_name} ({indexed_columns})")
    )


def _has_index_named(connection, table_name, index_name):
    return any(
        row[1] == index_name
        for row in connection.execute(text(f"PRAGMA index_list({table_name})"))
    )


def _reconcile_duplicate_pending_project_invites(connection):
    duplicate_pairs = connection.execute(
        text(
            """
            SELECT project_id, invitee_account_id
            FROM project_invites
            WHERE status = 'pending'
            GROUP BY project_id, invitee_account_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if not duplicate_pairs:
        return

    cancelled_count = 0
    for project_id, invitee_account_id in duplicate_pairs:
        pending_invite_ids = [
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT id
                    FROM project_invites
                    WHERE project_id = :project_id
                      AND invitee_account_id = :invitee_account_id
                      AND status = 'pending'
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {
                    "project_id": project_id,
                    "invitee_account_id": invitee_account_id,
                },
            )
        ]
        for invite_id in pending_invite_ids[1:]:
            connection.execute(
                text(
                    """
                    UPDATE project_invites
                    SET status = 'cancelled',
                        resolved_at = COALESCE(resolved_at, CURRENT_TIMESTAMP)
                    WHERE id = :invite_id
                    """
                ),
                {"invite_id": invite_id},
            )
            cancelled_count += 1

    warnings.warn(
        (
            "bootstrap_schema reconciled duplicate pending project invites: "
            f"cancelled {cancelled_count} duplicate row(s) before adding the pending invite unique index."
        ),
        RuntimeWarning,
        stacklevel=2,
    )


def _ensure_project_invite_pending_unique_index(connection):
    index_name = "uq_project_invites_pending_pair"
    if _has_index_named(connection, "project_invites", index_name):
        return
    _reconcile_duplicate_pending_project_invites(connection)
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_project_invites_pending_pair
            ON project_invites (project_id, invitee_account_id)
            WHERE status = 'pending'
            """
        )
    )


def _reconcile_duplicate_project_members(connection):
    duplicate_pairs = connection.execute(
        text(
            """
            SELECT project_id, member_id
            FROM project_members
            GROUP BY project_id, member_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if not duplicate_pairs:
        return

    removed_count = 0
    for project_id, member_id in duplicate_pairs:
        rowids = [
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT rowid
                    FROM project_members
                    WHERE project_id = :project_id
                      AND member_id = :member_id
                    ORDER BY rowid ASC
                    """
                ),
                {
                    "project_id": project_id,
                    "member_id": member_id,
                },
            )
        ]
        for rowid in rowids[1:]:
            connection.execute(
                text(
                    """
                    DELETE FROM project_members
                    WHERE rowid = :rowid
                    """
                ),
                {"rowid": rowid},
            )
            removed_count += 1

    warnings.warn(
        (
            "bootstrap_schema reconciled duplicate project membership rows: "
            f"removed {removed_count} duplicate row(s) before adding the project_members unique index."
        ),
        RuntimeWarning,
        stacklevel=2,
    )


def _ensure_project_members_unique_index(connection):
    index_name = "uq_project_members_pair"
    if _has_index_named(connection, "project_members", index_name):
        return
    _reconcile_duplicate_project_members(connection)
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_project_members_pair
            ON project_members (project_id, member_id)
            """
        )
    )


def _duplicate_non_empty_email_stats(connection, table_name):
    duplicate_value_count = connection.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT email
                FROM {table_name}
                WHERE email IS NOT NULL AND TRIM(email) <> ''
                GROUP BY email
                HAVING COUNT(*) > 1
            ) duplicate_values
            """
        )
    ).scalar_one()
    affected_row_count = connection.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE email IN (
                SELECT email
                FROM {table_name}
                WHERE email IS NOT NULL AND TRIM(email) <> ''
                GROUP BY email
                HAVING COUNT(*) > 1
            )
            """
        )
    ).scalar_one()
    return duplicate_value_count, affected_row_count


def _warn_duplicate_non_empty_emails(table_name, duplicate_value_count, affected_row_count):
    if affected_row_count == 0:
        return
    warnings.warn(
        (
            f"bootstrap_schema cleared duplicate non-empty legacy emails in "
            f"{table_name}.email ({affected_row_count} rows across "
            f"{duplicate_value_count} duplicated values); affected "
            f"{table_name} records require follow-up."
        ),
        RuntimeWarning,
        stacklevel=2,
    )


def _normalize_email_column(connection, table_name):
    connection.execute(
        text(
            f"""
            UPDATE {table_name}
            SET email = NULL
            WHERE email IS NOT NULL AND TRIM(email) = ''
            """
        )
    )
    connection.execute(
        text(
            f"""
            UPDATE {table_name}
            SET email = NULL
            WHERE email IN (
                SELECT email
                FROM {table_name}
                WHERE email IS NOT NULL
                GROUP BY email
                HAVING COUNT(*) > 1
            )
            """
        )
    )


def _backfill_legacy_virtual_members(connection):
    connection.execute(
        text(
            """
            UPDATE members
            SET is_virtual_identity = 1
            WHERE email IS NULL
            """
        )
    )


def _backfill_member_profile_defaults(connection):
    connection.execute(
        text(
            """
            UPDATE members
            SET gender = 'private'
            WHERE gender IS NULL
               OR TRIM(gender) = ''
               OR gender NOT IN ('male', 'female', 'private')
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE members
            SET public_email = 0
            WHERE public_email IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE members
            SET public_tel = 0
            WHERE public_tel IS NULL
            """
        )
    )


def _backfill_registration_status(connection):
    connection.execute(
        text(
            """
            UPDATE accounts
            SET registration_status = 'pending_verification'
            WHERE registration_status IS NULL OR TRIM(registration_status) = ''
            """
        )
    )


def _reconcile_virtual_member_accounts(connection):
    virtual_account_ids = [
        row[0]
        for row in connection.execute(
            text(
                """
                SELECT accounts.id
                FROM accounts
                JOIN members ON members.id = accounts.member_id
                WHERE accounts.member_id IS NOT NULL
                  AND accounts.is_super_account = 0
                  AND members.is_virtual_identity = 1
                ORDER BY accounts.id
                """
            )
        )
    ]
    if not virtual_account_ids:
        return

    account_ids_sql = ", ".join(str(account_id) for account_id in virtual_account_ids)
    cleared_session_count = connection.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM auth_sessions
            WHERE account_id IN ({account_ids_sql})
            """
        )
    ).scalar_one()
    cleared_token_count = connection.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM email_verification_tokens
            WHERE account_id IN ({account_ids_sql})
            """
        )
    ).scalar_one()

    connection.execute(
        text(
            f"""
            DELETE FROM auth_sessions
            WHERE account_id IN ({account_ids_sql})
            """
        )
    )
    connection.execute(
        text(
            f"""
            DELETE FROM email_verification_tokens
            WHERE account_id IN ({account_ids_sql})
            """
        )
    )
    connection.execute(
        text(
            f"""
            UPDATE accounts
            SET is_active = 0
            WHERE id IN ({account_ids_sql})
            """
        )
    )
    warnings.warn(
        (
            "bootstrap_schema reconciled virtualized legacy members: "
            f"deactivated {len(virtual_account_ids)} bound account(s), "
            f"cleared {cleared_session_count} session(s), "
            f"cleared {cleared_token_count} verification token(s)."
        ),
        RuntimeWarning,
        stacklevel=2,
    )


def bootstrap_schema(target_engine=None):
    engine = target_engine or default_engine

    Base.metadata.create_all(bind=engine)

    with engine.begin() as connection:
        _ensure_column(connection, "members", "email", "VARCHAR")
        _ensure_column(connection, "members", "total_earnings", "FLOAT DEFAULT 0.0")
        _ensure_column(
            connection,
            "members",
            "gender",
            "VARCHAR DEFAULT 'private' NOT NULL",
        )
        _ensure_column(
            connection,
            "members",
            "public_email",
            "BOOLEAN DEFAULT 0 NOT NULL",
        )
        _ensure_column(
            connection,
            "members",
            "public_tel",
            "BOOLEAN DEFAULT 0 NOT NULL",
        )
        _ensure_column(
            connection,
            "members",
            "is_virtual_identity",
            "BOOLEAN DEFAULT 0 NOT NULL",
        )
        duplicate_value_count, affected_row_count = _duplicate_non_empty_email_stats(
            connection,
            "members",
        )
        _normalize_email_column(connection, "members")
        _warn_duplicate_non_empty_emails("members", duplicate_value_count, affected_row_count)
        _backfill_member_profile_defaults(connection)
        _backfill_legacy_virtual_members(connection)
        _ensure_unique_index(connection, "members", "uq_members_email", ("email",))

        _ensure_column(connection, "accounts", "email", "VARCHAR")
        _ensure_column(connection, "accounts", "email_verified_at", "DATETIME")
        _ensure_column(
            connection,
            "accounts",
            "registration_status",
            "VARCHAR DEFAULT 'pending_verification' NOT NULL",
        )
        duplicate_value_count, affected_row_count = _duplicate_non_empty_email_stats(
            connection,
            "accounts",
        )
        _normalize_email_column(connection, "accounts")
        _warn_duplicate_non_empty_emails("accounts", duplicate_value_count, affected_row_count)
        _backfill_registration_status(connection)
        _reconcile_virtual_member_accounts(connection)
        _ensure_unique_index(connection, "accounts", "uq_accounts_email", ("email",))
        _ensure_project_invite_pending_unique_index(connection)
        _ensure_project_members_unique_index(connection)
