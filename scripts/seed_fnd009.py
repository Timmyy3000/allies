"""Seed one isolated Cloud database for the FND-009 proof."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
repository_backend = Path(__file__).resolve().parents[1] / "backend"
container_backend = Path("/app")
sys.path.insert(
    0,
    str(container_backend if (container_backend / "manage.py").exists() else repository_backend),
)

import django  # noqa: E402

django.setup()

from django.utils import timezone  # noqa: E402

from allies.models import (  # noqa: E402
    Ally,
    AllyBinding,
    BindingStatus,
    OnboardingAttempt,
    ProvisioningOperation,
    ProvisioningStatus,
)
from allies.services.onboarding import digest_value  # noqa: E402
from auths.models import ExternalIdentity, Provider, User, UserProfile  # noqa: E402
from chat.models import Conversation, Message, MessageLifecycle, MessageOrigin, MessageSender  # noqa: E402
from workspaces.models import (  # noqa: E402
    Membership,
    MembershipRole,
    MembershipStatus,
    RuntimeIntentMode,
    Workspace,
    WorkspaceKind,
)

FND009_NAMESPACE = uuid5(NAMESPACE_URL, "allies-fnd009:proof:v1")


def stable_id(label: str) -> UUID:
    return uuid5(FND009_NAMESPACE, label)


WORKSPACE_ID = stable_id("fnd009-workspace")
USER_ID = stable_id("fnd009-user")
ALLY_A_ID = stable_id("fnd009-ally-a")
ALLY_B_ID = stable_id("fnd009-ally-b")
CONVERSATION_A_ID = stable_id("fnd009-conversation-a")
CONVERSATION_B_ID = stable_id("fnd009-conversation-b")
BINDING_A_ID = stable_id("fnd009-binding-a")
BINDING_B_ID = stable_id("fnd009-binding-b")
FAKE_SUBJECT = "fnd009-user"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _seed_ally(
    *,
    workspace: Workspace,
    ally_id: UUID,
    binding_id: UUID,
    conversation_id: UUID,
    suffix: str,
    now,
) -> None:
    ally = Ally.objects.create(
        id=ally_id,
        workspace=workspace,
        name=f"Proof Ally {suffix.upper()}",
        job="FND-009 local proof",
        personality="A deterministic local proof Ally.",
        appearance_catalog_version="v1",
        appearance_key=f"fnd009-{suffix}",
    )
    binding = AllyBinding.objects.create(
        id=binding_id,
        ally=ally,
        version=1,
        status=BindingStatus.BOUND,
        receipt_digest=_digest(f"binding-receipt-{suffix}"),
    )
    ProvisioningOperation.objects.create(
        id=stable_id(f"fnd009-provisioning-{suffix}"),
        binding=binding,
        workspace=workspace,
        user=workspace.owner,
        api_idempotency_key_digest=_digest(f"provisioning-key-{suffix}"),
        content_fingerprint=_digest(f"provisioning-content-{suffix}"),
        status=ProvisioningStatus.SUCCEEDED,
        attempt_count=1,
        next_attempt_at=now,
        expires_at=now + timedelta(hours=24),
        completed_at=now,
        receipt_digest=_digest(f"provisioning-receipt-{suffix}"),
    )
    greeting = f"Hello from deterministic proof Ally {suffix.upper()}."
    reply = f"The seeded onboarding reply for Ally {suffix.upper()}."
    OnboardingAttempt.objects.create(
        id=stable_id(f"fnd009-onboarding-{suffix}"),
        attempt_token_digest=digest_value(f"fnd009-attempt-{suffix}"),
        browser_binding_digest=digest_value(b"fnd009-browser-binding"),
        name=ally.name,
        job=ally.job,
        personality=ally.personality,
        appearance_catalog_version=ally.appearance_catalog_version,
        appearance_key=ally.appearance_key,
        greeting=greeting,
        reply=reply,
        user=workspace.owner,
        ally=ally,
        expires_at=now + timedelta(hours=24),
        consumed_at=now,
    )
    conversation = Conversation.objects.create(
        id=conversation_id,
        ally=ally,
        is_default=True,
    )
    Message.objects.create(
        id=stable_id(f"fnd009-greeting-{suffix}"),
        conversation=conversation,
        sequence=1,
        sender=MessageSender.ASSISTANT,
        origin=MessageOrigin.ONBOARDING,
        content=greeting,
        status=MessageLifecycle.COMPLETED,
    )
    # A completed SEND row keeps the durable onboarding handoff valid without
    # creating an unsolicited execution when the browser reads the history.
    Message.objects.create(
        id=stable_id(f"fnd009-reply-{suffix}"),
        conversation=conversation,
        sequence=2,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content=reply,
        status=MessageLifecycle.COMPLETED,
        send_key_digest=digest_value(f"onboarding-reply:{ally.id}"),
        content_fingerprint=_digest(reply),
    )


def main() -> None:
    now = timezone.now()
    Workspace.objects.filter(pk=WORKSPACE_ID).delete()
    user, _ = User.objects.update_or_create(
        pk=USER_ID,
        defaults={"is_active": True, "is_staff": False, "is_superuser": False},
    )
    user.set_unusable_password()
    user.save(update_fields=("password", "is_active", "is_staff", "is_superuser"))
    UserProfile.objects.update_or_create(
        user=user,
        defaults={"display_name": "FND-009 Proof User"},
    )
    ExternalIdentity.objects.update_or_create(
        provider=Provider.FAKE,
        subject=FAKE_SUBJECT,
        defaults={
            "id": stable_id("fnd009-external-identity"),
            "user": user,
            "issuer": "fake://issuer",
            "email_snapshot": "",
            "email_verified": False,
            "email_verified_at": None,
            "email_verification_source": "",
            "display_name_snapshot": "FND-009 Proof User",
        },
    )
    workspace = Workspace.objects.create(
        id=WORKSPACE_ID,
        kind=WorkspaceKind.PERSONAL,
        owner=user,
        name="FND-009 Proof Workspace",
        is_active=True,
        runtime_intent_mode=RuntimeIntentMode.COMPOSING,
    )
    Membership.objects.create(
        id=stable_id("fnd009-membership"),
        workspace=workspace,
        user=user,
        role=MembershipRole.OWNER,
        status=MembershipStatus.ACTIVE,
    )
    _seed_ally(
        workspace=workspace,
        ally_id=ALLY_A_ID,
        binding_id=BINDING_A_ID,
        conversation_id=CONVERSATION_A_ID,
        suffix="a",
        now=now,
    )
    _seed_ally(
        workspace=workspace,
        ally_id=ALLY_B_ID,
        binding_id=BINDING_B_ID,
        conversation_id=CONVERSATION_B_ID,
        suffix="b",
        now=now,
    )
    print(json.dumps({
        "status": "seeded",
        "workspace_id": str(WORKSPACE_ID),
        "ally_ids": [str(ALLY_A_ID), str(ALLY_B_ID)],
        "conversation_ids": [str(CONVERSATION_A_ID), str(CONVERSATION_B_ID)],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
