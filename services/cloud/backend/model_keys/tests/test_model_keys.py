from __future__ import annotations

import json
import logging
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from django.test import Client, override_settings

from allies.gateways import foundry
from allies.models import Ally, AllyBinding, BindingStatus
from auths.config import cookie_name
from auths.models import User
from auths.services.sessions import issue_session
from common.vault import VaultUnavailable, seal_secret, unseal_secret
from model_keys import services
from model_keys.models import AllyModelSelection, ModelKey, SelectionStatus
from workspaces.models import Membership, Workspace

SECRET = "sk-zen-live-0123456789abcdefWXYZ"
BROKER_TOKEN = "b" * 40

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def vault_key(settings):
    settings.ALLIES_VAULT_KEYS = Fernet.generate_key().decode()


class FakeFoundry:
    def __init__(self):
        self.calls = []
        self.error = None

    def set_model_binding(self, profile_id, binding):
        self.calls.append(("set", profile_id, dict(binding)))
        if self.error:
            raise self.error
        return len(self.calls)

    def clear_model_binding(self, profile_id):
        self.calls.append(("clear", profile_id, None))
        if self.error:
            raise self.error
        return len(self.calls)


@pytest.fixture
def fake_foundry(monkeypatch):
    fake = FakeFoundry()
    monkeypatch.setattr(foundry, "set_model_binding", fake.set_model_binding)
    monkeypatch.setattr(foundry, "clear_model_binding", fake.clear_model_binding)
    return fake


def _owner():
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    return user, workspace


def _ally(workspace, *, bound=True):
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    AllyBinding.objects.create(
        ally=ally,
        status=BindingStatus.BOUND if bound else BindingStatus.PENDING,
        receipt_digest="a" * 64 if bound else "",
    )
    return ally


def _select_zen(user, workspace, ally, **overrides):
    values = {"provider": "opencode-zen", "model": "gpt-5.2", "reasoning": "high"}
    values.update(overrides)
    return services.select_model(
        user=user, workspace_id=workspace.id, ally_id=ally.id, **values
    )


def test_foundry_profile_id_matches_foundry_derivation():
    assert foundry.foundry_profile_id("00000000-0000-4000-8000-000000000001") == UUID(
        "ab303498-bbab-51bc-807d-dfa56470b02f"
    )


def test_vault_round_trips_and_rotates(settings):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.ALLIES_VAULT_KEYS = old
    sealed = seal_secret(SECRET)
    assert SECRET.encode() not in sealed
    settings.ALLIES_VAULT_KEYS = f"{new},{old}"
    assert unseal_secret(sealed) == SECRET


@pytest.mark.parametrize("keys", ["", "not-a-fernet-key"])
def test_vault_fails_closed_outside_debug(settings, keys):
    settings.DEBUG = False
    settings.ALLIES_VAULT_KEYS = keys
    with pytest.raises(VaultUnavailable):
        seal_secret(SECRET)


def test_connect_seals_key_and_select_binds_it_atomically(fake_foundry):
    user, workspace = _owner()
    ally = _ally(workspace)

    key = services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    selection = _select_zen(user, workspace, ally)

    stored = ModelKey.objects.get(pk=key.pk)
    assert SECRET.encode() not in bytes(stored.ciphertext)
    assert stored.key_hint == "WXYZ"
    assert fake_foundry.calls == [
        (
            "set",
            foundry.foundry_profile_id(ally.binding.id),
            {
                "provider": "opencode-zen",
                "model": "gpt-5.2",
                "reasoning": "high",
                "key_refs": {"OPENCODE_ZEN_API_KEY": key.reference},
            },
        )
    ]
    assert selection.synced is True
    assert selection.status == SelectionStatus.PENDING


def test_select_requires_connected_key_and_bound_ally(fake_foundry):
    user, workspace = _owner()
    with pytest.raises(services.ModelKeyMissing):
        _select_zen(user, workspace, _ally(workspace))
    services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    with pytest.raises(services.ModelKeyUnavailable):
        _select_zen(user, workspace, _ally(workspace, bound=False))
    assert fake_foundry.calls == []


@pytest.mark.parametrize(
    "overrides",
    [{"provider": "openrouter"}, {"model": "bad model"}, {"reasoning": "low"}],
)
def test_select_rejects_invalid_values(fake_foundry, overrides):
    user, workspace = _owner()
    with pytest.raises(services.ModelKeyInvalid):
        _select_zen(user, workspace, _ally(workspace), **overrides)


def test_org_default_clears_binding_and_drops_row(fake_foundry):
    user, workspace = _owner()
    ally = _ally(workspace)
    services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    _select_zen(user, workspace, ally)

    result = services.select_model(
        user=user, workspace_id=workspace.id, ally_id=ally.id, provider=None
    )

    assert result is None
    assert fake_foundry.calls[-1][0] == "clear"
    assert not AllyModelSelection.objects.exists()


def test_replace_revokes_old_key_and_repoints_allies(fake_foundry):
    user, workspace = _owner()
    ally = _ally(workspace)
    old = services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    _select_zen(user, workspace, ally)

    new = services.connect_key(
        user=user,
        workspace_id=workspace.id,
        provider="opencode-zen",
        value="sk-zen-rotated-0123456789abcd",
    )

    old.refresh_from_db()
    assert old.revoked_at is not None and bytes(old.ciphertext) == b""
    assert fake_foundry.calls[-1][2]["key_refs"] == {
        "OPENCODE_ZEN_API_KEY": new.reference
    }
    assert AllyModelSelection.objects.get().model_key_id == new.id


def test_disconnect_revokes_now_and_clears_allies(fake_foundry):
    user, workspace = _owner()
    ally = _ally(workspace)
    key = services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    _select_zen(user, workspace, ally)
    fake_foundry.error = foundry.FoundryGatewayRetryable("down")

    assert services.disconnect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen"
    )

    with pytest.raises(services.ModelKeyUnavailable):
        services.resolve_for_broker(
            workspace_id=str(workspace.id), reference=key.reference
        )
    selection = AllyModelSelection.objects.get()
    assert selection.model_key_id is None and selection.synced is False
    fake_foundry.error = None
    assert services.sync_pending() == 1
    assert fake_foundry.calls[-1][0] == "clear"
    assert not AllyModelSelection.objects.exists()


def test_retryable_failures_retry_then_degrade(fake_foundry):
    user, workspace = _owner()
    ally = _ally(workspace)
    services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    fake_foundry.error = foundry.FoundryGatewayUnknownOutcome("lost")
    _select_zen(user, workspace, ally)

    for _ in range(services.MAX_SYNC_ATTEMPTS):
        services.sync_pending()

    selection = AllyModelSelection.objects.get()
    assert selection.synced is False
    assert selection.status == SelectionStatus.DEGRADED
    calls = len(fake_foundry.calls)
    services.sync_pending()
    assert len(fake_foundry.calls) == calls


def test_rejected_selection_degrades_without_retry(fake_foundry):
    user, workspace = _owner()
    services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    fake_foundry.error = foundry.FoundryGatewayInvalid("bad")

    selection = _select_zen(user, workspace, _ally(workspace))

    assert selection.status == SelectionStatus.DEGRADED
    assert services.sync_pending() == 0


def test_stale_push_does_not_mark_newer_choice_synced(fake_foundry, monkeypatch):
    user, workspace = _owner()
    ally = _ally(workspace)
    services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    selection = _select_zen(user, workspace, ally)
    AllyModelSelection.objects.filter(pk=selection.pk).update(synced=False)

    def racing_set(profile_id, binding):
        AllyModelSelection.objects.filter(pk=selection.pk).update(
            model="glm-5", revision=selection.revision + 1
        )
        return 1

    monkeypatch.setattr(foundry, "set_model_binding", racing_set)

    assert services.push_selection(selection.pk) is False
    assert AllyModelSelection.objects.get().synced is False


def test_execution_outcomes_move_status_only_after_sync(fake_foundry):
    user, workspace = _owner()
    ally = _ally(workspace)
    services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    selection = _select_zen(user, workspace, ally)
    before = selection.synced_at - timedelta(seconds=1)
    after = selection.synced_at + timedelta(seconds=1)

    services.note_execution_outcome(
        ally_id=ally.id,
        event_type="execution.completed",
        reason=None,
        message_created_at=before,
    )
    assert AllyModelSelection.objects.get().status == SelectionStatus.PENDING

    services.note_execution_outcome(
        ally_id=ally.id,
        event_type="execution.stopped",
        reason="binding_repair_required",
        message_created_at=after,
    )
    assert AllyModelSelection.objects.get().status == SelectionStatus.DEGRADED

    services.note_execution_outcome(
        ally_id=ally.id,
        event_type="execution.completed",
        reason=None,
        message_created_at=after,
    )
    assert AllyModelSelection.objects.get().status == SelectionStatus.CONNECTED


def test_other_workspace_cannot_mutate_or_read(fake_foundry):
    _, workspace = _owner()
    ally = _ally(workspace)
    intruder, _ = _owner()
    from auths.exceptions import WorkspaceAccessDenied

    with pytest.raises(WorkspaceAccessDenied):
        services.connect_key(
            user=intruder,
            workspace_id=workspace.id,
            provider="opencode-zen",
            value=SECRET,
        )
    with pytest.raises(WorkspaceAccessDenied):
        services.get_state(user=intruder, workspace_id=workspace.id)
    with pytest.raises(WorkspaceAccessDenied):
        _select_zen(intruder, workspace, ally)


def _broker(body, token=BROKER_TOKEN):
    return Client().post(
        "/api/v1/internal/credentials/resolve",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


@override_settings(ALLIES_CREDENTIAL_BROKER_TOKEN=BROKER_TOKEN)
def test_broker_returns_value_only_to_owning_workspace(fake_foundry, caplog):
    user, workspace = _owner()
    _, other = _owner()
    key = services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    body = {"version": 1, "workspace_id": str(workspace.id), "reference": key.reference}

    unselected = _broker(body)
    _select_zen(user, workspace, _ally(workspace))
    with caplog.at_level(logging.DEBUG):
        ok = _broker(body)
    foreign = _broker({**body, "workspace_id": str(other.id)})
    unknown = _broker({**body, "reference": f"allies-key://model-keys/{uuid4()}"})
    garbage = _broker({**body, "reference": "vault://tenant/zen"})
    bad_token = _broker(body, token="x" * 40)

    assert ok.status_code == 200
    assert ok.json() == {"value": SECRET}
    assert ok["Cache-Control"] == "no-store"
    for refused in (unselected, foreign, unknown, garbage):
        assert refused.status_code == 404
        assert refused.json() == {"code": "credential_unavailable"}
    assert bad_token.status_code == 401
    assert SECRET not in caplog.text


@override_settings(ALLIES_CREDENTIAL_BROKER_TOKEN="")
def test_broker_is_closed_without_configured_token(fake_foundry):
    user, workspace = _owner()
    key = services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    response = _broker(
        {"version": 1, "workspace_id": str(workspace.id), "reference": key.reference},
        token="",
    )
    assert response.status_code == 401


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
def test_product_api_round_trip_never_echoes_key(fake_foundry, caplog):
    user, workspace = _owner()
    ally = _ally(workspace)
    _, other = _owner()
    client = Client(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    client.cookies[cookie_name("access")] = issue_session(user).access_token
    headers = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
    }
    base = f"/api/v1/workspaces/{workspace.id}"

    with caplog.at_level(logging.DEBUG):
        connected = client.put(
            f"{base}/model-keys/opencode-zen",
            json.dumps({"key": SECRET}),
            content_type="application/json",
            **headers,
        )
        selected = client.put(
            f"{base}/allies/{ally.id}/model",
            json.dumps({"provider": "opencode-zen", "model": "gpt-5.2"}),
            content_type="application/json",
            **headers,
        )
        listed = client.get(f"{base}/model-keys", **headers)
        foreign = client.get(f"/api/v1/workspaces/{other.id}/model-keys", **headers)
        disconnected = client.delete(f"{base}/model-keys/opencode-zen", **headers)

    assert connected.status_code == 200, connected.content
    assert selected.status_code == 200, selected.content
    data = listed.json()["data"]
    assert data["keys"] == [
        {
            "provider": "opencode-zen",
            "key_hint": "WXYZ",
            "connected_at": data["keys"][0]["connected_at"],
        }
    ]
    assert data["allies"] == [
        {
            "ally_id": str(ally.id),
            "source": "own_key",
            "provider": "opencode-zen",
            "model": "gpt-5.2",
            "reasoning": None,
            "status": "pending",
        }
    ]
    assert foreign.status_code == 404
    assert disconnected.status_code == 200
    assert disconnected.json()["data"]["keys"] == []
    for response in (connected, selected, listed, disconnected):
        assert SECRET not in response.content.decode()
    assert SECRET not in caplog.text


def test_conflicting_clear_is_retried_until_it_converges(fake_foundry):
    user, workspace = _owner()
    ally = _ally(workspace)
    services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    _select_zen(user, workspace, ally)
    fake_foundry.error = foundry.FoundryGatewayConflict("busy")

    services.select_model(
        user=user, workspace_id=workspace.id, ally_id=ally.id, provider=None
    )

    selection = AllyModelSelection.objects.get()
    assert selection.model_key_id is None
    assert selection.sync_attempts == 1
    assert selection.status == SelectionStatus.PENDING
    fake_foundry.error = None
    assert services.sync_pending() == 1
    assert not AllyModelSelection.objects.exists()


def test_clear_for_missing_profile_drops_row(fake_foundry):
    user, workspace = _owner()
    ally = _ally(workspace)
    services.connect_key(
        user=user, workspace_id=workspace.id, provider="opencode-zen", value=SECRET
    )
    _select_zen(user, workspace, ally)
    fake_foundry.error = foundry.FoundryGatewayInvalid("profile does not exist")

    services.select_model(
        user=user, workspace_id=workspace.id, ally_id=ally.id, provider=None
    )

    assert not AllyModelSelection.objects.exists()
