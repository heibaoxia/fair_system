from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConfiguredModel(BaseModel):
    class Config:
        from_attributes = True


class AuthRegisterRequest(BaseModel):
    email: str
    password: str
    username: str
    gender: Literal["male", "female", "private"]
    model_config = ConfigDict(extra="forbid")


class AuthLoginRequest(BaseModel):
    login_id: str
    password: str


class AuthVerifyEmailRequest(BaseModel):
    token: str


class AuthResendVerificationRequest(BaseModel):
    login_id: str


class AuthSwitchIdentityRequest(BaseModel):
    acting_member_id: int | None = None


class AuthMemberIdentity(ConfiguredModel):
    id: int
    name: str
    tel: str | None = None
    is_active: bool
    is_virtual_identity: bool = False


class AuthAccountSummary(ConfiguredModel):
    id: int
    login_id: str
    email: str | None = None
    email_verified_at: datetime | None = None
    registration_status: str
    is_super_account: bool
    is_active: bool
    member_id: int | None = None
    created_at: datetime


class AuthSessionSummary(BaseModel):
    expires_at: datetime
    created_at: datetime
    last_seen_at: datetime


class AuthIdentityPools(BaseModel):
    own_identities: list[AuthMemberIdentity] = Field(default_factory=list)
    global_identities: list[AuthMemberIdentity] = Field(default_factory=list)
    test_identities: list[AuthMemberIdentity] = Field(default_factory=list)


class AuthAvailableIdentitiesResponse(BaseModel):
    identity_scope: str
    can_switch_identity: bool
    bound_member: AuthMemberIdentity | None = None
    acting_member: AuthMemberIdentity | None = None
    available_identities: AuthIdentityPools


class AuthSessionContextResponse(AuthAvailableIdentitiesResponse):
    authenticated: bool = True
    account: AuthAccountSummary
    session: AuthSessionSummary | None = None


class AuthVerificationStatusResponse(BaseModel):
    ok: bool = True
    account: AuthAccountSummary
    verification_email_sent: bool | None = None


class AuthResendVerificationResponse(BaseModel):
    ok: bool = True
    verification_email_sent: bool = True
