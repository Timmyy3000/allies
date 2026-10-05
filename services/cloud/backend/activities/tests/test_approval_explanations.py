from __future__ import annotations

import json
from datetime import timedelta
from urllib.error import HTTPError
from uuid import uuid4

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from activities.models import Approval, ApprovalStatus
from activities.presentation import approval_detail
from activities.services import approval_explanations as explanations
from activities.services.approval_explanations import (
    EXPLANATION_VERSION,
    build_provider_payload,
    ensure_approval_explanation,
    input_fingerprint,
    preview_digest,
)
from allies.gateways.contracts import canonical_fingerprint
from auths.config import cookie_name
from auths.exceptions import WorkspaceAccessDenied
from auths.models import User
from auths.services.sessions import issue_session

from . import test_approval, test_cld005

conversation_records = test_cld005.conversation_records


def _approval(conversation_records):
    user, workspace, _ally, binding, conversation, message = conversation_records
    event, request_id = test_approval._rich_event(message, binding)
    test_approval.project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    approval.refresh_from_db()
    return user, workspace, conversation, message, approval


def _model_result(source):
    return {
        "version": EXPLANATION_VERSION,
        "approval_request_id": source["approval_request_id"],
        "preview_digest": source["preview_digest"],
        "source": "model",
        "action": "Run a command",
        "target": "the requested workspace",
        "consequence": "the command may change data",
        "reason": "your Ally needs your approval",
        "input_fingerprint": source["input_fingerprint"],
        "action_kind": source["action_kind"],
        "policy_version": EXPLANATION_VERSION,
        "fallback_reason": "",
    }


@pytest.mark.django_db
def test_detail_contract_is_bound_and_keeps_origin_turn(conversation_records):
    _user, _workspace, _conversation, message, approval = _approval(
        conversation_records
    )

    result = approval_detail(approval)

    assert result["contract_version"] == "approval.v1"
    assert result["message_id"] == message.id
    assert result["conversation_turn_ordinal"] == message.sequence
    assert result["approval_request_id"] == approval.approval_request_id
    assert result["preview_digest"] == preview_digest(approval.action_preview)
    assert result["technical_details"]["action_preview"] == approval.action_preview
    assert result["explanation"]["source"] == "fallback"
    assert "input_fingerprint" not in result["explanation"]


@pytest.mark.django_db
def test_detail_endpoint_claims_durable_fallback_without_provider(
    conversation_records, monkeypatch
):
    user, workspace, conversation, _message, approval = _approval(conversation_records)
    called = False

    def provider(_source):
        nonlocal called
        called = True
        raise AssertionError("provider must remain disabled")

    monkeypatch.setattr(explanations, "generate_explanation", provider)
    client = Client()
    client.cookies[cookie_name("access")] = issue_session(user).access_token
    csrf = client.get("/api/v1/auths/csrf")["X-CSRFToken"]
    response = client.get(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/approvals/{approval.id}",
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.json()["data"]["explanation"]["source"] == "fallback"
    assert called is False
    approval.refresh_from_db()
    assert approval.explanation["source"] == "fallback"


@pytest.mark.django_db
@override_settings(ALLIES_APPROVAL_SUMMARIES_ENABLED=True)
def test_cross_site_detail_is_read_only_and_never_calls_provider(
    conversation_records, monkeypatch
):
    user, workspace, conversation, _message, approval = _approval(conversation_records)
    monkeypatch.setattr(
        explanations,
        "generate_explanation",
        lambda _source: pytest.fail("cross-site GET must not call provider"),
    )
    client = Client(HTTP_ORIGIN="https://attacker.example")
    client.cookies[cookie_name("access")] = issue_session(user).access_token

    response = client.get(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/approvals/{approval.id}"
    )

    assert response.status_code == 200
    assert response.json()["data"]["explanation"]["source"] == "fallback"
    approval.refresh_from_db()
    assert approval.explanation == {}


@pytest.mark.django_db
@override_settings(
    ALLIES_APPROVAL_SUMMARIES_ENABLED=True,
    ALLIES_WAITLIST_OPENAI_API_KEY="test-key",
    CACHE_URL="redis://cache.test/0",
)
def test_model_explanation_is_request_bound_and_claimed_once(
    conversation_records, monkeypatch
):
    user, workspace, conversation, _message, approval = _approval(conversation_records)
    calls = 0

    def provider(source):
        nonlocal calls
        calls += 1
        return _model_result(source)

    monkeypatch.setattr(explanations, "generate_explanation", provider)
    first = ensure_approval_explanation(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        approval_id=approval.id,
    )
    second = ensure_approval_explanation(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        approval_id=approval.id,
    )

    assert calls == 1
    assert first.explanation["source"] == "model"
    assert second.explanation["source"] == "model"
    assert second.explanation["approval_request_id"] == str(
        approval.approval_request_id
    )
    assert second.explanation["preview_digest"] == preview_digest(
        approval.action_preview
    )


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"approval_request_id": "wrong"},
        {
            "approval_request_id": "x",
            "preview_digest": "x",
            "input_fingerprint": "x",
            "action": "ignore all instructions",
            "target": "x",
            "consequence": "x",
            "reason": "x",
            "extra": "x",
        },
    ],
)
def test_provider_output_is_closed_and_rejects_malformed_values(value):
    request_id = str(uuid4())
    digest = preview_digest("echo safe")
    source = explanations._ProviderSource(
        approval_request_id=request_id,
        preview_digest=digest,
        action_kind="terminal",
        action_preview="echo safe",
        input_fingerprint=input_fingerprint(request_id, digest, "terminal"),
    )
    with pytest.raises(explanations.ExplanationFailure):
        explanations._validated_model_output(source, json.dumps(value))


def test_provider_payload_is_closed_and_has_no_authority_or_tools():
    source = {
        "approval_request_id": str(uuid4()),
        "preview_digest": preview_digest("echo safe"),
        "action_kind": "terminal",
        "action_preview": "echo safe",
        "input_fingerprint": canonical_fingerprint(
            {
                "approval_request_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d84",
                "preview_digest": preview_digest("echo safe"),
                "action_kind": "terminal",
                "policy_version": EXPLANATION_VERSION,
            }
        ),
    }
    payload = build_provider_payload(source)
    assert payload["model"] == "gpt-5.6-luna"
    assert payload["tools"] == []
    assert payload["store"] is False
    assert "approve" not in payload["input"]
    assert json.loads(payload["input"])["approval"]["action_preview"] == "echo safe"


def test_transport_uses_fixed_url_and_rejects_redirects(monkeypatch):
    source = {
        "approval_request_id": str(uuid4()),
        "preview_digest": preview_digest("echo safe"),
        "action_kind": "terminal",
        "action_preview": "echo safe",
    }
    source["input_fingerprint"] = input_fingerprint(
        source["approval_request_id"], source["preview_digest"], source["action_kind"]
    )
    captured = []

    class Response:
        status = 200

        def __init__(self):
            output = {
                "approval_request_id": source["approval_request_id"],
                "preview_digest": source["preview_digest"],
                "input_fingerprint": source["input_fingerprint"],
                "action": "Run a command",
                "target": "the requested workspace",
                "consequence": "the command may change data",
                "reason": "your Ally needs your approval",
            }
            self.body = json.dumps({"output_text": json.dumps(output)}).encode()
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            chunk = self.body[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    class Opener:
        def open(self, request, timeout):
            captured.append((request, timeout))
            return Response()

    monkeypatch.setattr(explanations, "build_opener", lambda handler: Opener())
    result = explanations._call_provider(
        explanations._ProviderSource(**source), api_key="secret"
    )

    assert result["source"] == "model"
    assert captured[0][0].full_url == explanations.OPENAI_RESPONSES_URL
    assert captured[0][0].get_header("Authorization") == "Bearer secret"
    with pytest.raises(HTTPError):
        explanations._NoRedirect().redirect_request(
            captured[0][0], None, 302, "redirect", {}, "https://evil.test"
        )


def test_response_reads_use_only_the_remaining_total_deadline(monkeypatch):
    time_values = iter((10.0, 11.5))
    monkeypatch.setattr(explanations.time, "monotonic", lambda: next(time_values))

    class Socket:
        def __init__(self):
            self.timeouts = []

        def settimeout(self, value):
            self.timeouts.append(value)

    socket = Socket()

    class Response:
        fp = type("FP", (), {"raw": type("Raw", (), {"_sock": socket})()})()

        def read(self, _size):
            return b""

    assert explanations._read_response(Response(), deadline=16.0) == b""
    assert socket.timeouts == [6.0]


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["timeout", "provider_error"])
@override_settings(
    ALLIES_APPROVAL_SUMMARIES_ENABLED=True,
    ALLIES_WAITLIST_OPENAI_API_KEY="test-key",
    CACHE_URL="redis://cache.test/0",
)
def test_provider_failure_persists_deterministic_fallback(
    conversation_records, monkeypatch, failure
):
    user, workspace, conversation, _message, approval = _approval(conversation_records)
    monkeypatch.setattr(explanations, "_provider_allowed", lambda **_kwargs: None)
    monkeypatch.setattr(
        explanations,
        "generate_explanation",
        lambda _source: (_ for _ in ()).throw(explanations.ExplanationFailure(failure)),
    )

    ensure_approval_explanation(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        approval_id=approval.id,
    )

    approval.refresh_from_db()
    assert approval.explanation["source"] == "fallback"
    assert approval.explanation["fallback_reason"] == failure


@pytest.mark.django_db
@pytest.mark.parametrize("provider_error", [False, True])
@override_settings(
    ALLIES_APPROVAL_SUMMARIES_ENABLED=True,
    ALLIES_WAITLIST_OPENAI_API_KEY="test-key",
    CACHE_URL="redis://cache.test/0",
)
def test_explanation_returns_reconciled_state_after_provider_call(
    conversation_records, monkeypatch, provider_error
):
    user, workspace, conversation, _message, approval = _approval(conversation_records)

    def provider(source):
        Approval.objects.filter(pk=approval.pk).update(
            status=ApprovalStatus.DECISION_RECORDED,
            decision="approve",
            decided_at=timezone.now(),
        )
        if provider_error:
            raise explanations.ExplanationFailure("provider_error")
        return _model_result(source)

    monkeypatch.setattr(explanations, "_provider_allowed", lambda **_kwargs: None)
    monkeypatch.setattr(explanations, "generate_explanation", provider)

    result = ensure_approval_explanation(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        approval_id=approval.id,
    )

    detail = approval_detail(result)
    assert detail["status"] == ApprovalStatus.DECISION_RECORDED
    assert detail["decision"] == "approve"
    assert detail["decision_recorded"] is True
    assert detail["explanation"]["source"] == (
        "fallback" if provider_error else "model"
    )


@pytest.mark.django_db
@override_settings(
    ALLIES_APPROVAL_SUMMARIES_ENABLED=True,
    ALLIES_WAITLIST_OPENAI_API_KEY="test-key",
    CACHE_URL="redis://cache.test/0",
)
def test_budget_denial_does_not_call_provider(conversation_records, monkeypatch):
    user, workspace, conversation, _message, approval = _approval(conversation_records)
    called = False

    def provider(_source):
        nonlocal called
        called = True
        raise AssertionError("budget denial must fail closed")

    monkeypatch.setattr(
        explanations, "_provider_allowed", lambda **_kwargs: "budget_exhausted"
    )
    monkeypatch.setattr(explanations, "generate_explanation", provider)

    ensure_approval_explanation(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        approval_id=approval.id,
    )

    approval.refresh_from_db()
    assert called is False
    assert approval.explanation["fallback_reason"] == "budget_exhausted"


@pytest.mark.django_db
@override_settings(
    ALLIES_APPROVAL_SUMMARIES_ENABLED=True,
    ALLIES_WAITLIST_OPENAI_API_KEY="test-key",
    CACHE_URL="redis://cache.test/0",
)
def test_changed_source_cannot_publish_stale_model_copy(
    conversation_records, monkeypatch
):
    user, workspace, conversation, _message, approval = _approval(conversation_records)

    def provider(source):
        Approval.objects.filter(pk=approval.pk).update(action_preview="echo changed")
        return _model_result(source)

    monkeypatch.setattr(explanations, "_provider_allowed", lambda **_kwargs: None)
    monkeypatch.setattr(explanations, "generate_explanation", provider)

    ensure_approval_explanation(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        approval_id=approval.id,
    )

    approval.refresh_from_db()
    assert approval.action_preview == "echo changed"
    assert approval.explanation["source"] == "fallback"
    assert approval.explanation["fallback_reason"] == "binding_mismatch"


@pytest.mark.django_db
def test_explanation_boundary_rejects_foreign_user_without_provider(
    conversation_records, monkeypatch
):
    _user, workspace, conversation, _message, approval = _approval(conversation_records)
    foreign = User.objects.create_user()
    monkeypatch.setattr(
        explanations,
        "generate_explanation",
        lambda _source: (_ for _ in ()).throw(AssertionError("must not call provider")),
    )

    with pytest.raises(WorkspaceAccessDenied):
        ensure_approval_explanation(
            user=foreign,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            approval_id=approval.id,
        )


def test_safe_action_preview_masks_connection_capability_paths_only():
    capability = "SYNTHETIC_CAPABILITY_0123456789"
    ordinary = "https://example.com/docs/very-long-document-name?recipient=team"
    preview = (
        f"connect https://example.com/connect/agent/{capability} then open {ordinary}"
    )

    safe = explanations._safe_action_preview(preview)

    assert capability not in safe
    assert "https://example.com/connect/agent/***" in safe
    assert ordinary in safe
    for delimiter in (",", ")"):
        value = f"https://example.com/connect/agent/{capability}{delimiter}"
        assert explanations._safe_action_preview(value) == (
            f"https://example.com/connect/agent/***{delimiter}"
        )
    assert (
        explanations._safe_action_preview(
            f"https://example.com/connect/agent/{capability}=="
        )
        == "https://example.com/connect/agent/***"
    )
    assert (
        explanations._safe_action_preview(f"https://example.com/inv%69te/{capability}")
        == "https://example.com/invite/***"
    )
    credentialed = (
        "https://synthetic-user:synthetic-pass@example.com/connect/agent/"
        f"{capability}?token=SYNTHETIC_QUERY_SECRET&recipient=team"
        "#section=overview&access_token=SYNTHETIC_FRAGMENT_SECRET"
    )
    safe_credentialed = explanations._safe_action_preview(credentialed)
    assert safe_credentialed == (
        "https://example.com/connect/agent/***?token=***&recipient=team"
        "#section=overview&access_token=***"
    )
    assert "synthetic" not in safe_credentialed.lower()
    assert (
        explanations._safe_action_preview(
            f"https://example.com/connect/{capability}?opaque=SYNTHETIC_QUERY_SECRET"
        )
        == "[redacted capability URL]"
    )
    assert (
        explanations._safe_action_preview(
            f"https://example.com/connect/{capability}#section=setup"
        )
        == "https://example.com/connect/***#section=setup"
    )
    for fragment in ("SYNTHETIC", "section", "section=setup&SYNTHETIC"):
        assert (
            explanations._safe_action_preview(
                f"https://example.com/connect/{capability}#{fragment}"
            )
            == "[redacted capability URL]"
        )
    docs_path = "https://example.com/docs/connect/very-long-document-name"
    assert explanations._safe_action_preview(docs_path) == docs_path
    for malformed in (
        "https://example.com/connect",
        "https://example.com/%63onnect/",
        f"https://example.com/connect/foo/{capability}",
    ):
        assert explanations._safe_action_preview(malformed) == (
            "[redacted capability URL]"
        )


@pytest.mark.django_db
@override_settings(
    ALLIES_APPROVAL_SUMMARIES_ENABLED=True,
    ALLIES_WAITLIST_OPENAI_API_KEY="test-key",
    CACHE_URL="redis://cache.test/0",
)
@pytest.mark.parametrize("bare_fragment", [False, True])
def test_legacy_unsafe_preview_uses_one_safe_model_and_detail_view(
    conversation_records, monkeypatch, bare_fragment
):
    user, workspace, conversation, _message, approval = _approval(conversation_records)
    capability = "SYNTHETIC_CAPABILITY_0123456789"
    raw_preview = (
        "connect https://synthetic-user:synthetic-pass@example.com/connect/agent/"
        f"{capability}?token=SYNTHETIC_QUERY_SECRET&recipient=team"
        "#section=overview&access_token=SYNTHETIC_FRAGMENT_SECRET "
        "then open https://example.com/docs/very-long-document-name?recipient=team"
    )
    if bare_fragment:
        raw_preview = f"https://example.com/connect/{capability}#SYNTHETIC"
    Approval.objects.filter(pk=approval.pk).update(action_preview=raw_preview)
    approval.refresh_from_db()
    calls = []

    def provider(source):
        calls.append(source)
        return _model_result(source)

    monkeypatch.setattr(explanations, "generate_explanation", provider)
    monkeypatch.setattr(explanations, "_provider_allowed", lambda **_kwargs: None)

    result = ensure_approval_explanation(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        approval_id=approval.id,
    )
    detail = approval_detail(result)
    safe_preview = (
        "connect https://example.com/connect/agent/***?token=***&recipient=team"
        "#section=overview&access_token=*** "
        "then open https://example.com/docs/very-long-document-name?recipient=team"
    )

    if bare_fragment:
        safe_preview = "[redacted capability URL]"

    assert len(calls) == 1
    assert calls[0]["action_preview"] == safe_preview
    assert calls[0]["preview_digest"] == preview_digest(safe_preview)
    assert calls[0]["input_fingerprint"] == input_fingerprint(
        str(approval.approval_request_id),
        preview_digest(safe_preview),
        approval.action_kind,
    )
    assert detail["action_preview"] == safe_preview
    assert detail["technical_details"]["action_preview"] == safe_preview
    assert detail["explanation"]["preview_digest"] == preview_digest(safe_preview)
    assert "SYNTHETIC" not in str(detail)
    approval.refresh_from_db()
    assert approval.action_preview == raw_preview


@pytest.mark.django_db
def test_legacy_unsafe_summary_is_replaced_without_regenerating(
    conversation_records, monkeypatch
):
    user, workspace, conversation, _message, approval = _approval(conversation_records)
    capability = "SYNTHETIC_CAPABILITY_0123456789"
    raw_preview = f"connect https://example.com/invite/{capability}"
    Approval.objects.filter(pk=approval.pk).update(action_preview=raw_preview)
    approval.refresh_from_db()
    raw_digest = preview_digest(raw_preview)
    approval.explanation = _model_result(
        {
            "approval_request_id": str(approval.approval_request_id),
            "preview_digest": raw_digest,
            "action_kind": approval.action_kind,
            "action_preview": raw_preview,
            "input_fingerprint": input_fingerprint(
                str(approval.approval_request_id), raw_digest, approval.action_kind
            ),
        }
    )
    approval.save(update_fields=("explanation", "updated_at"))
    monkeypatch.setattr(
        explanations,
        "generate_explanation",
        lambda _source: pytest.fail("legacy summaries must not regenerate"),
    )

    result = ensure_approval_explanation(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        approval_id=approval.id,
    )

    safe_preview = "connect https://example.com/invite/***"
    assert result.explanation["source"] == "fallback"
    assert result.explanation["preview_digest"] == preview_digest(safe_preview)
    assert result.explanation["preview_digest"] != raw_digest
    result.refresh_from_db()
    assert result.action_preview == raw_preview
