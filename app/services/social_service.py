from __future__ import annotations

from sqlalchemy import and_, exists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models

GENDER_LABELS = {
    "male": "\u7537",
    "female": "\u5973",
    "private": "\u4fdd\u5bc6",
}


class SocialError(Exception):
    pass


class SocialTargetNotFoundError(SocialError):
    pass


class SocialSelfFollowError(SocialError):
    pass


def _visible_account_query(
    db: Session,
    *,
    viewer_account_id: int,
    exclude_viewer: bool,
):
    is_following = exists().where(
        and_(
            models.AccountFollow.follower_account_id == viewer_account_id,
            models.AccountFollow.followed_account_id == models.Account.id,
        )
    )
    is_follower = exists().where(
        and_(
            models.AccountFollow.follower_account_id == models.Account.id,
            models.AccountFollow.followed_account_id == viewer_account_id,
        )
    )

    query = (
        db.query(
            models.Account.id.label("account_id"),
            models.Member.name.label("username"),
            models.Member.gender.label("gender_code"),
            models.Member.email.label("member_email"),
            models.Member.tel.label("member_tel"),
            models.Member.public_email.label("public_email"),
            models.Member.public_tel.label("public_tel"),
            is_following.label("is_following"),
            is_follower.label("is_follower"),
        )
        .join(models.Member, models.Account.member_id == models.Member.id)
        .filter(
            models.Account.is_super_account.is_(False),
            models.Account.is_active.is_(True),
            models.Account.registration_status == "active",
            models.Account.email_verified_at.is_not(None),
            models.Account.member_id.is_not(None),
            models.Member.is_active.is_(True),
            models.Member.is_virtual_identity.is_(False),
        )
    )
    if exclude_viewer:
        query = query.filter(models.Account.id != viewer_account_id)
    return query


def _build_public_profile(row) -> dict:
    is_following = bool(row.is_following)
    is_follower = bool(row.is_follower)
    return {
        "account_id": row.account_id,
        "username": row.username,
        "gender": GENDER_LABELS.get(row.gender_code, "\u4fdd\u5bc6"),
        "email": row.member_email if bool(row.public_email) else None,
        "tel": row.member_tel if bool(row.public_tel) else None,
        "is_following": is_following,
        "is_follower": is_follower,
        "is_friend": is_following and is_follower,
    }


def search_visible_accounts(
    db: Session,
    *,
    viewer_account_id: int,
    account_id: int,
) -> list[dict]:
    rows = (
        _visible_account_query(
            db,
            viewer_account_id=viewer_account_id,
            exclude_viewer=False,
        )
        .filter(models.Account.id == account_id)
        .order_by(models.Account.id.asc())
        .all()
    )
    return [_build_public_profile(row) for row in rows]


def get_relationships(
    db: Session,
    *,
    viewer_account_id: int,
) -> dict:
    rows = (
        _visible_account_query(
            db,
            viewer_account_id=viewer_account_id,
            exclude_viewer=True,
        )
        .order_by(models.Account.id.asc())
        .all()
    )
    profiles = [_build_public_profile(row) for row in rows]
    return {
        "following": [
            profile
            for profile in profiles
            if profile["is_following"] and not profile["is_follower"]
        ],
        "followers": [
            profile
            for profile in profiles
            if profile["is_follower"] and not profile["is_following"]
        ],
        "friends": [
            profile
            for profile in profiles
            if profile["is_following"] and profile["is_follower"]
        ],
    }


def _ensure_visible_target(
    db: Session,
    *,
    viewer_account_id: int,
    target_account_id: int,
) -> None:
    target_profiles = search_visible_accounts(
        db,
        viewer_account_id=viewer_account_id,
        account_id=target_account_id,
    )
    if not target_profiles:
        raise SocialTargetNotFoundError("未找到该账户。")


def follow_account(
    db: Session,
    *,
    follower_account_id: int,
    target_account_id: int,
) -> None:
    if follower_account_id == target_account_id:
        raise SocialSelfFollowError("不能关注自己。")

    _ensure_visible_target(
        db,
        viewer_account_id=follower_account_id,
        target_account_id=target_account_id,
    )

    existing = (
        db.query(models.AccountFollow)
        .filter(
            models.AccountFollow.follower_account_id == follower_account_id,
            models.AccountFollow.followed_account_id == target_account_id,
        )
        .first()
    )
    if existing is not None:
        return

    db.add(
        models.AccountFollow(
            follower_account_id=follower_account_id,
            followed_account_id=target_account_id,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = (
            db.query(models.AccountFollow)
            .filter(
                models.AccountFollow.follower_account_id == follower_account_id,
                models.AccountFollow.followed_account_id == target_account_id,
            )
            .first()
        )
        if duplicate is None:
            raise


def unfollow_account(
    db: Session,
    *,
    follower_account_id: int,
    target_account_id: int,
) -> None:
    if follower_account_id == target_account_id:
        raise SocialSelfFollowError("不能关注自己。")

    _ensure_visible_target(
        db,
        viewer_account_id=follower_account_id,
        target_account_id=target_account_id,
    )

    (
        db.query(models.AccountFollow)
        .filter(
            models.AccountFollow.follower_account_id == follower_account_id,
            models.AccountFollow.followed_account_id == target_account_id,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
