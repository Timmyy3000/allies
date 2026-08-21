from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from allies.models import (
    Ally,
    AllyBinding,
    BindingStatus,
    OnboardingAttempt,
    ProvisioningOperation,
    ProvisioningStatus,
)
from auths.models import User
from workspaces.models import Workspace


def _workspace_and_user():
    user = User.objects.create_user(public_id="ally-model-user")
    workspace = Workspace.objects.create(
        public_id="wsp_model_workspace",
        owner=user,
        name="Model workspace",
    )
    return workspace, user


def _ally(*, workspace):
    return Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm, curious, and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )


def _operation(*, ally, workspace, user, status=ProvisioningStatus.PENDING):
    binding = AllyBinding.objects.create(ally=ally)
    return ProvisioningOperation.objects.create(
        binding=binding,
        workspace=workspace,
        user=user,
        api_idempotency_key_digest="a" * 64,
        content_fingerprint="b" * 64,
        status=status,
        next_attempt_at=timezone.now(),
        expires_at=timezone.now() + timedelta(hours=1),
    )


@pytest.mark.django_db
def test_ally_has_seed_fields_without_persisted_provisioning_state():
    workspace, _ = _workspace_and_user()
    ally = _ally(workspace=workspace)

    assert ally.provisioning_state == BindingStatus.PENDING
    assert "provisioning_state" not in {field.name for field in Ally._meta.fields}

    binding = AllyBinding.objects.create(
        ally=ally,
        status=BindingStatus.BOUND,
        receipt_digest="c" * 64,
    )
    assert ally.provisioning_state == BindingStatus.BOUND
    assert binding.cloud_binding_id.startswith("bnd_")


@pytest.mark.django_db
def test_binding_identity_is_immutable_and_one_to_one():
    workspace, _ = _workspace_and_user()
    ally = _ally(workspace=workspace)
    binding = AllyBinding.objects.create(ally=ally)

    binding.cloud_binding_id = "bnd_replacement"
    with pytest.raises(ValueError, match="immutable"):
        binding.save()

    with pytest.raises(IntegrityError):
        AllyBinding.objects.create(ally=ally)


@pytest.mark.django_db
def test_operation_identity_is_unique_per_workspace_user_and_key():
    workspace, user = _workspace_and_user()
    first = _ally(workspace=workspace)
    second = _ally(workspace=workspace)
    _operation(ally=first, workspace=workspace, user=user)

    with pytest.raises(IntegrityError):
        _operation(ally=second, workspace=workspace, user=user)


@pytest.mark.django_db
def test_onboarding_attempt_retains_seed_and_preview_but_only_token_digest():
    workspace, user = _workspace_and_user()
    attempt = OnboardingAttempt.objects.create(
        attempt_token_digest="d" * 64,
        browser_binding_digest="e" * 64,
        name="Mira",
        job="Study partner",
        personality="Calm, curious, and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
        greeting="Hello from Mira.",
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    assert attempt.reply is None
    assert attempt.greeting == "Hello from Mira."
    assert "attempt_token" not in {
        field.name for field in OnboardingAttempt._meta.fields
    }
    assert attempt.is_usable()

    ally = _ally(workspace=workspace)
    attempt.consume(user=user, ally=ally, reply="I need help planning my week.")
    attempt.refresh_from_db()
    assert attempt.user_id == user.id
    assert attempt.ally_id == ally.id
    assert attempt.consumed_at is not None
    assert not attempt.is_usable()


@pytest.mark.django_db
def test_onboarding_attempt_expires_and_cannot_be_consumed():
    workspace, user = _workspace_and_user()
    attempt = OnboardingAttempt.objects.create(
        attempt_token_digest="f" * 64,
        browser_binding_digest="1" * 64,
        name="Mira",
        job="Study partner",
        personality="Calm, curious, and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
        greeting="Hello from Mira.",
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    assert attempt.is_expired()
    with pytest.raises(ValueError, match="expired"):
        attempt.consume(
            user=user,
            ally=_ally(workspace=workspace),
            reply="I need help planning my week.",
        )


@pytest.mark.django_db
def test_onboarding_attempt_consumption_fields_are_coherent():
    workspace, user = _workspace_and_user()
    ally = _ally(workspace=workspace)
    values = {
        "attempt_token_digest": "2" * 64,
        "browser_binding_digest": "3" * 64,
        "name": "Mira",
        "job": "Study partner",
        "personality": "Calm, curious, and specific.",
        "appearance_catalog_version": "v1",
        "appearance_key": "sunrise",
        "greeting": "Hello from Mira.",
        "expires_at": timezone.now() + timedelta(minutes=10),
    }

    with pytest.raises(IntegrityError), transaction.atomic():
        OnboardingAttempt.objects.create(
            **values,
            user=user,
            ally=ally,
            consumed_at=None,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        OnboardingAttempt.objects.create(
            **{**values, "attempt_token_digest": "4" * 64},
            consumed_at=timezone.now(),
            reply="",
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        OnboardingAttempt.objects.create(
            **{**values, "attempt_token_digest": "5" * 64},
            reply="reply before consumption",
        )
