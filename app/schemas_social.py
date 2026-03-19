from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from pydantic import ConfigDict


class ConfiguredSocialModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SocialPublicProfile(BaseModel):
    account_id: int
    username: str
    gender: str
    email: str | None = None
    tel: str | None = None
    is_following: bool
    is_follower: bool
    is_friend: bool


class SocialSearchResponse(BaseModel):
    results: list[SocialPublicProfile] = Field(default_factory=list)


class SocialRelationshipsResponse(BaseModel):
    following: list[SocialPublicProfile] = Field(default_factory=list)
    followers: list[SocialPublicProfile] = Field(default_factory=list)
    friends: list[SocialPublicProfile] = Field(default_factory=list)


class SocialOkResponse(BaseModel):
    ok: bool = True


class SocialProjectInviteSummary(ConfiguredSocialModel):
    id: int
    project_id: int
    project_name: str
    inviter_account_id: int
    inviter_username: str
    status: str
    project_total_revenue: float
    project_member_count: int
    project_description: str
    created_at: datetime
    resolved_at: datetime | None = None


class SocialProjectInvitesResponse(BaseModel):
    pending: list[SocialProjectInviteSummary] = Field(default_factory=list)
    history: list[SocialProjectInviteSummary] = Field(default_factory=list)
