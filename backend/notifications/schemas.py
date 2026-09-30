from datetime import datetime
from typing import Literal

from ninja import Schema
from pydantic import ConfigDict, Field, StrictBool, StrictInt, StrictStr

from common.uuids import CanonicalUUID


class StrictSchema(Schema):
    model_config = ConfigDict(extra="forbid")


class PushKeys(StrictSchema):
    p256dh: StrictStr = Field(max_length=87)
    auth: StrictStr = Field(max_length=22)


class RegisterPush(StrictSchema):
    browser_id: CanonicalUUID
    binding_id: CanonicalUUID
    replaces_binding_id: CanonicalUUID | None
    endpoint: StrictStr = Field(max_length=2048)
    keys: PushKeys


class PushPresence(StrictSchema):
    binding_id: CanonicalUUID
    client_id: CanonicalUUID
    sequence: StrictInt = Field(ge=1, le=2147483647)
    visible: StrictBool


class RevokePush(StrictSchema):
    binding_id: CanonicalUUID


class PushConfig(Schema):
    enabled: bool
    vapid_public_key: str | None
    presence_ttl_seconds: Literal[60] = 60
    heartbeat_seconds: Literal[20] = 20


class PushRegistration(Schema):
    subscription_id: CanonicalUUID
    browser_id: CanonicalUUID
    binding_id: CanonicalUUID
    workspace_id: CanonicalUUID
    session_id: CanonicalUUID
    state: Literal["active"] = "active"


class PresenceReceipt(Schema):
    accepted_sequence: int
    foreground_until: datetime | None


class PushPayload(Schema):
    version: Literal[1] = 1
    notification_id: CanonicalUUID
    binding_id: CanonicalUUID
    kind: Literal[
        "approval_needed", "routine_completed", "routine_failed", "reply_completed"
    ]
    workspace_id: CanonicalUUID
    ally_id: CanonicalUUID
    conversation_id: CanonicalUUID
    expires_at: datetime
