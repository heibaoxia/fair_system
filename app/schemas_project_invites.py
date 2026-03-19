from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ConfiguredModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectInviteCreateRequest(BaseModel):
    invitee_account_id: int


class ProjectInviteItem(ConfiguredModel):
    id: int
    project_id: int
    inviter_account_id: int
    invitee_account_id: int
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


class ProjectInviteListResponse(BaseModel):
    invites: list[ProjectInviteItem]


class ProjectInviteDecisionResponse(BaseModel):
    ok: bool
    status: Literal["accepted", "rejected"]
