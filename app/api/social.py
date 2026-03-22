from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentMemberContext, get_current_member_context, get_db
from app import schemas_social
from app.services import project_invite_service, social_service

router = APIRouter(prefix="/social", tags=["social"])


def require_regular_social_context(
    context: CurrentMemberContext = Depends(get_current_member_context),
) -> CurrentMemberContext:
    if context.account.is_super_account:
        raise HTTPException(status_code=403, detail="测试超级号不能使用社交功能。")
    if (
        not context.account.is_active
        or context.bound_member is None
        or not context.bound_member.is_active
        or bool(getattr(context.bound_member, "is_virtual_identity", False))
    ):
        raise HTTPException(status_code=403, detail="只有激活的普通账户才能使用社交功能。")
    return context


@router.get("/search", response_model=schemas_social.SocialSearchResponse)
def search_social_accounts(
    account_id: int,
    context: CurrentMemberContext = Depends(require_regular_social_context),
    db: Session = Depends(get_db),
):
    return {
        "results": social_service.search_visible_accounts(
            db,
            viewer_account_id=context.account.id,
            account_id=account_id,
        )
    }


@router.get("/relationships", response_model=schemas_social.SocialRelationshipsResponse)
def get_social_relationships(
    context: CurrentMemberContext = Depends(require_regular_social_context),
    db: Session = Depends(get_db),
):
    return social_service.get_relationships(
        db,
        viewer_account_id=context.account.id,
    )


@router.get("/project-invites", response_model=schemas_social.SocialProjectInvitesResponse)
def get_social_project_invites(
    context: CurrentMemberContext = Depends(require_regular_social_context),
    db: Session = Depends(get_db),
):
    return project_invite_service.list_project_invites_for_invitee(
        db,
        invitee_account_id=context.account.id,
    )


@router.post("/follow/{account_id}", response_model=schemas_social.SocialOkResponse)
def follow_social_account(
    account_id: int,
    context: CurrentMemberContext = Depends(require_regular_social_context),
    db: Session = Depends(get_db),
):
    try:
        social_service.follow_account(
            db,
            follower_account_id=context.account.id,
            target_account_id=account_id,
        )
    except social_service.SocialSelfFollowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except social_service.SocialTargetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/follow/{account_id}", response_model=schemas_social.SocialOkResponse)
def unfollow_social_account(
    account_id: int,
    context: CurrentMemberContext = Depends(require_regular_social_context),
    db: Session = Depends(get_db),
):
    try:
        social_service.unfollow_account(
            db,
            follower_account_id=context.account.id,
            target_account_id=account_id,
        )
    except social_service.SocialSelfFollowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except social_service.SocialTargetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
