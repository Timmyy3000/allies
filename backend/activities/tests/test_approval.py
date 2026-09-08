from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection, connections
from django.test import Client, override_settings
from django.utils import timezone

from activities.exceptions import ApprovalConflict
from activities.models import Approval, ApprovalDeliveryState, ApprovalStatus
from activities.presentation import activity_metadata
from activities.services.approvals import (
    _claim_due,
    _deliver_one,
    dispatch_pending_approvals,
    get_approval_detail,
    list_approvals,
    record_approval_decision,
)
from activities.services.projection import project_foundry_event, read_activity_snapshot
from allies.exceptions import FoundryGatewayRetryable, FoundryGatewayUnknownOutcome
from allies.gateways.contracts import (
    ApprovalDecisionReceipt,
    FoundryEventEnvelope,
    canonical_fingerprint,
)
from allies.models import BindingStatus
from auths.config import cookie_name
from auths.models import SessionClientKind, User
from auths.services.sessions import issue_session
from workspaces.models import Membership

from . import test_cld005

conversation_records = test_cld005.conversation_records
event_for = test_cld005.event_for


def _rich_event(
    message,
    binding,
    *,
    event_type="execution.awaiting_action",
    attempt_sequence=1,
    outcome=None,
    action_kind="terminal",
):
    approval_request_id = uuid4()
    payload = {
        "approval_request_id": str(approval_request_id),
        "action_kind": action_kind,
        "action_label": "Run the command",
        "action_preview": "echo safe",
        "expires_at": "2026-08-25T12:05:00Z",
    }
    if event_type == "execution.approval_resolved":
        payload = {"approval_request_id": str(approval_request_id), "outcome": outcome}
    return event_for(
        message,
        binding,
        event_type=event_type,
        attempt_sequence=attempt_sequence,
        payload=payload,
    ), approval_request_id


def _approval_values(approval, **overrides):
    values = {
        "workspace_id": approval.workspace_id,
        "ally_id": approval.ally_id,
        "conversation_id": approval.conversation_id,
        "message_id": approval.message_id,
        "approval_request_id": uuid4(),
        "cloud_binding_id": approval.cloud_binding_id,
        "execution_id": approval.execution_id,
        "attempt_id": approval.attempt_id,
        "generation": approval.generation,
        "attempt_sequence": approval.attempt_sequence,
        "action_kind": approval.action_kind,
        "action_label": approval.action_label,
        "action_preview": approval.action_preview,
        "requested_at": approval.requested_at,
        "expires_at": approval.expires_at,
    }
    values.update(overrides)
    return values


def test_rich_awaiting_event_creates_private_approval_and_safe_activity(
    conversation_records,
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)

    result = project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)

    assert result.activity is not None
    assert result.activity.approval_id == approval.id
    assert approval.cloud_binding_id == binding.id
    public = activity_metadata(result.activity)["approval"]
    assert public == {
        "id": approval.id,
        "status": ApprovalStatus.PENDING,
        "expires_at": approval.expires_at,
        "decided_at": None,
    }
    assert "action_preview" not in public


def test_plugin_tool_rich_approval_uses_the_same_bounded_projection(
    conversation_records,
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding, action_kind="plugin_tool")

    result = project_foundry_event(event)

    approval = Approval.objects.get(approval_request_id=request_id)
    assert result.activity.approval_id == approval.id
    assert approval.action_kind == "plugin_tool"


@pytest.mark.parametrize("expires_at", [None, 123, {}])
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_FOUNDRY_EXECUTION_ENABLED=True,
    ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN="event-secret",
)
def test_rich_awaiting_event_rejects_non_string_expiry(
    conversation_records, expires_at
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, _request_id = _rich_event(message, binding)
    values = event.model_dump(mode="json")
    values["payload"]["expires_at"] = expires_at
    values["fingerprint"] = canonical_fingerprint(values)

    with pytest.raises(ValueError):
        FoundryEventEnvelope.model_validate(values)

    response = Client().post(
        "/api/v1/internal/foundry/events",
        data=json.dumps(values),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer event-secret",
    )
    assert response.status_code == 422
    assert response.json()["data"]["code"] == "validation_error"


def test_approval_decision_is_first_wins_and_exact_retry_replays(
    conversation_records,
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )

    key = uuid4()
    first = record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=key,
    )
    replay = record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=key,
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert first.approval.status == ApprovalStatus.DECISION_RECORDED
    assert replay.approval.decision == "approve"


def test_stale_binding_rejects_a_new_decision_without_recording_it(
    conversation_records,
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    binding.status = BindingStatus.INCOMPATIBLE
    binding.save(update_fields=("status", "updated_at"))

    with pytest.raises(ApprovalConflict):
        record_approval_decision(
            user=user,
            workspace_id=approval.workspace_id,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            decision="approve",
            idempotency_key=uuid4(),
        )

    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.PENDING
    assert approval.decision == ""
    assert approval.decision_idempotency_key is None


def test_stale_binding_does_not_abort_other_delivery_rows(
    conversation_records, monkeypatch
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    first_event, first_request_id = _rich_event(message, binding, attempt_sequence=1)
    second_event, second_request_id = _rich_event(message, binding, attempt_sequence=2)
    project_foundry_event(first_event)
    project_foundry_event(second_event)
    first = Approval.objects.get(approval_request_id=first_request_id)
    second = Approval.objects.get(approval_request_id=second_request_id)
    expiry = timezone.now() + timedelta(minutes=5)
    Approval.objects.filter(pk__in=(first.pk, second.pk)).update(expires_at=expiry)
    monkeypatch.setattr(
        "activities.services.approvals._schedule_approval_delivery", lambda: None
    )
    for approval in (first, second):
        record_approval_decision(
            user=user,
            workspace_id=approval.workspace_id,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            decision="approve",
            idempotency_key=uuid4(),
        )
    missing_binding = uuid4()
    Approval.objects.filter(pk=first.pk).update(cloud_binding_id=missing_binding)

    def submit(command, *, raw_body):
        return ApprovalDecisionReceipt(
            schema_version="v1",
            kind="approval.receipt",
            status="accepted",
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            approval_request_id=command.approval_request_id,
            fingerprint=command.fingerprint,
        )

    monkeypatch.setattr(
        "activities.services.approvals.submit_approval_decision", submit
    )
    report = dispatch_pending_approvals(now=timezone.now(), limit=2)
    first.refresh_from_db()
    second.refresh_from_db()

    assert report.delivered == 1
    assert first.status == ApprovalStatus.OUTCOME_UNKNOWN
    assert first.delivery_safe_error_code == "binding_unavailable"
    assert second.delivery_state == ApprovalDeliveryState.DELIVERED


def test_approval_resolution_updates_status_without_new_public_activity(
    conversation_records,
):
    user, _workspace, _ally, binding, conversation, message = conversation_records
    awaiting, request_id = _rich_event(message, binding)
    project_foundry_event(awaiting)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=uuid4(),
    )
    resolved, _ = _rich_event(
        message,
        binding,
        event_type="execution.approval_resolved",
        attempt_sequence=2,
        outcome="approved",
    )
    # Keep the same request correlation as the awaiting event.
    resolved.payload["approval_request_id"] = str(request_id)
    values = resolved.model_dump(mode="json")
    from allies.gateways.contracts import FoundryEventEnvelope, canonical_fingerprint

    values["fingerprint"] = canonical_fingerprint(values)
    project_foundry_event(FoundryEventEnvelope.model_validate(values))

    approval.refresh_from_db()
    snapshot = read_activity_snapshot(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=conversation.id,
    )
    assert approval.status == ApprovalStatus.APPROVED
    assert len(snapshot.activities) == 1
    assert snapshot.activities[0].approval.status == ApprovalStatus.APPROVED


def test_matching_late_resolution_is_consumed_without_wedging_the_event_stream(
    conversation_records,
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    awaiting, request_id = _rich_event(message, binding)
    project_foundry_event(awaiting)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5),
        acknowledgement_deadline_at=timezone.now() + timedelta(seconds=30),
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=uuid4(),
    )
    Approval.objects.filter(pk=approval.pk).update(
        acknowledgement_deadline_at=timezone.now() - timedelta(seconds=1),
    )
    resolved, _ = _rich_event(
        message,
        binding,
        event_type="execution.approval_resolved",
        attempt_sequence=2,
        outcome="approved",
    )
    values = resolved.model_dump(mode="json")
    values["payload"]["approval_request_id"] = str(request_id)
    from allies.gateways.contracts import FoundryEventEnvelope, canonical_fingerprint

    values["fingerprint"] = canonical_fingerprint(values)
    assert project_foundry_event(
        FoundryEventEnvelope.model_validate(values)
    ).status == ("applied")
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.OUTCOME_UNKNOWN

    follow_up = event_for(
        message,
        binding,
        attempt_sequence=3,
        payload={"kind": "assistant_delta", "text": "after timeout"},
    )
    assert project_foundry_event(follow_up).status == "applied"


def test_pre_reconciled_unknown_cancellation_is_consumed_without_wedging_stream(
    conversation_records,
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    awaiting, request_id = _rich_event(message, binding)
    project_foundry_event(awaiting)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=uuid4(),
    )
    Approval.objects.filter(pk=approval.pk).update(
        acknowledgement_deadline_at=timezone.now() - timedelta(seconds=1),
    )
    get_approval_detail(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
    )
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.OUTCOME_UNKNOWN
    resolved, _ = _rich_event(
        message,
        binding,
        event_type="execution.approval_resolved",
        attempt_sequence=2,
        outcome="cancelled",
    )
    values = resolved.model_dump(mode="json")
    values["payload"]["approval_request_id"] = str(request_id)
    from allies.gateways.contracts import FoundryEventEnvelope, canonical_fingerprint

    values["fingerprint"] = canonical_fingerprint(values)
    assert project_foundry_event(
        FoundryEventEnvelope.model_validate(values)
    ).status == ("applied")
    assert (
        project_foundry_event(
            event_for(
                message,
                binding,
                attempt_sequence=3,
                payload={"kind": "assistant_delta", "text": "after cancellation"},
            )
        ).status
        == "applied"
    )


@pytest.mark.parametrize("outcome", ["expired", "cancelled"])
def test_recorded_resolution_after_consent_expiry_does_not_wedge_stream(
    conversation_records, outcome
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    awaiting, request_id = _rich_event(message, binding)
    project_foundry_event(awaiting)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5),
        acknowledgement_deadline_at=timezone.now() + timedelta(seconds=30),
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=uuid4(),
    )
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    resolved, _ = _rich_event(
        message,
        binding,
        event_type="execution.approval_resolved",
        attempt_sequence=2,
        outcome=outcome,
    )
    values = resolved.model_dump(mode="json")
    values["payload"]["approval_request_id"] = str(request_id)
    from allies.gateways.contracts import FoundryEventEnvelope, canonical_fingerprint

    values["fingerprint"] = canonical_fingerprint(values)
    assert project_foundry_event(
        FoundryEventEnvelope.model_validate(values)
    ).status == ("applied")
    approval.refresh_from_db()
    assert approval.status == getattr(ApprovalStatus, outcome.upper())
    assert (
        project_foundry_event(
            event_for(
                message,
                binding,
                attempt_sequence=3,
                payload={"kind": "assistant_delta", "text": "after resolution"},
            )
        ).status
        == "applied"
    )


def test_terminal_event_cancels_unresolved_approval(conversation_records):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    awaiting, request_id = _rich_event(message, binding)
    project_foundry_event(awaiting)
    terminal = event_for(
        message,
        binding,
        event_type="execution.stopped",
        attempt_sequence=2,
        payload={"reason": "user_requested"},
    )

    assert project_foundry_event(terminal).status == "applied"
    assert Approval.objects.get(approval_request_id=request_id).status == (
        ApprovalStatus.CANCELLED
    )


def test_terminal_event_cancels_pending_and_marks_recorded_unknown(
    conversation_records, monkeypatch
):
    user, workspace, ally, binding, conversation, message = conversation_records
    awaiting, request_id = _rich_event(message, binding)
    project_foundry_event(awaiting)
    first = Approval.objects.get(approval_request_id=request_id)
    now = timezone.now()
    Approval.objects.filter(pk=first.pk).update(expires_at=now + timedelta(minutes=5))
    monkeypatch.setattr(
        "activities.services.approvals._schedule_approval_delivery", lambda: None
    )
    record_approval_decision(
        user=user,
        workspace_id=first.workspace_id,
        conversation_id=first.conversation_id,
        approval_id=first.id,
        decision="approve",
        idempotency_key=uuid4(),
    )
    Approval.objects.bulk_create(
        [
            Approval(
                workspace=workspace,
                ally=ally,
                conversation=conversation,
                message=message,
                approval_request_id=uuid4(),
                cloud_binding_id=first.cloud_binding_id,
                execution_id=first.execution_id,
                attempt_id=first.attempt_id,
                generation=first.generation,
                attempt_sequence=first.attempt_sequence,
                action_kind="terminal",
                action_label="Run the command",
                action_preview="echo safe",
                requested_at=now,
                expires_at=now + timedelta(minutes=5),
            )
            for _ in range(51)
        ]
    )
    terminal = event_for(
        message,
        binding,
        event_type="execution.stopped",
        attempt_sequence=2,
        payload={"reason": "user_requested"},
    )

    assert project_foundry_event(terminal).status == "applied"
    first.refresh_from_db()
    assert first.status == ApprovalStatus.OUTCOME_UNKNOWN
    assert first.delivery_safe_error_code == "execution_terminal_ack_missing"
    assert not Approval.objects.filter(
        message=message,
        execution_id=first.execution_id,
        status__in=(ApprovalStatus.PENDING, ApprovalStatus.DECISION_RECORDED),
    ).exists()
    assert (
        Approval.objects.filter(
            message=message,
            execution_id=first.execution_id,
            status=ApprovalStatus.CANCELLED,
        ).count()
        == 51
    )


def test_approval_list_reconciles_due_rows_before_bounding_live_rows(
    conversation_records,
):
    user, workspace, ally, binding, conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    base = Approval.objects.get(approval_request_id=request_id)
    now = timezone.now()
    expired_at = now - timedelta(seconds=1)
    Approval.objects.filter(pk=base.pk).update(
        requested_at=now - timedelta(minutes=2), expires_at=expired_at
    )
    Approval.objects.bulk_create(
        [
            Approval(
                **_approval_values(
                    base,
                    requested_at=now - timedelta(minutes=2),
                    expires_at=expired_at,
                )
            )
            for _ in range(50)
        ]
    )
    approved = Approval.objects.create(
        **_approval_values(
            base,
            status=ApprovalStatus.APPROVED,
            delivery_state=ApprovalDeliveryState.DELIVERED,
            requested_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=5),
            decided_at=now - timedelta(seconds=30),
            decision="approve",
        )
    )
    live = Approval.objects.create(
        **_approval_values(
            base,
            requested_at=now,
            expires_at=now + timedelta(minutes=5),
        )
    )

    rows = list_approvals(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=3,
    )

    assert [row.id for row in rows[:2]] == [live.id, approved.id]
    assert rows[2].status == ApprovalStatus.EXPIRED
    assert rows[0].status == ApprovalStatus.PENDING
    assert (
        Approval.objects.filter(
            workspace=workspace,
            ally=ally,
            conversation=conversation,
            status=ApprovalStatus.PENDING,
            expires_at__lte=now,
        ).count()
        == 1
    )


def test_approval_delivery_validates_receipt_identity(
    conversation_records, monkeypatch
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="reject",
        idempotency_key=uuid4(),
    )

    def submit(command, *, raw_body):
        return ApprovalDecisionReceipt(
            schema_version="v1",
            kind="approval.receipt",
            status="accepted",
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            approval_request_id=command.approval_request_id,
            fingerprint=command.fingerprint,
        )

    monkeypatch.setattr(
        "activities.services.approvals.submit_approval_decision", submit
    )
    report = dispatch_pending_approvals(now=timezone.now())
    approval.refresh_from_db()
    assert report.delivered == 1
    assert approval.delivery_state == ApprovalDeliveryState.DELIVERED
    assert approval.status == ApprovalStatus.DECISION_RECORDED


def test_mismatched_receipt_becomes_unknown_without_claiming_runtime_success(
    conversation_records, monkeypatch
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    monkeypatch.setattr(
        "activities.services.approvals._schedule_approval_delivery", lambda: None
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=uuid4(),
    )

    def submit(command, *, raw_body):
        return ApprovalDecisionReceipt(
            schema_version="v1",
            kind="approval.receipt",
            status="accepted",
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            approval_request_id=uuid4(),
            fingerprint=command.fingerprint,
        )

    monkeypatch.setattr(
        "activities.services.approvals.submit_approval_decision", submit
    )
    report = dispatch_pending_approvals(now=timezone.now())
    approval.refresh_from_db()

    assert report.unknown == 1
    assert approval.status == ApprovalStatus.OUTCOME_UNKNOWN
    assert approval.delivery_state == ApprovalDeliveryState.CANCELLED
    assert approval.delivery_safe_error_code == "receipt_identity_mismatch"


@pytest.mark.parametrize(
    ("gateway_error", "safe_error"),
    [
        (FoundryGatewayRetryable, "foundry_unavailable"),
        (FoundryGatewayUnknownOutcome, "foundry_outcome_unknown"),
    ],
)
def test_retryable_gateway_outcomes_keep_decision_recorded_for_bounded_retry(
    conversation_records, monkeypatch, gateway_error, safe_error
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    monkeypatch.setattr(
        "activities.services.approvals._schedule_approval_delivery", lambda: None
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=uuid4(),
    )

    def submit(*args, **kwargs):
        raise gateway_error()

    monkeypatch.setattr(
        "activities.services.approvals.submit_approval_decision", submit
    )
    report = dispatch_pending_approvals(now=timezone.now())
    approval.refresh_from_db()

    assert report.deferred == 1
    assert approval.status == ApprovalStatus.DECISION_RECORDED
    assert approval.delivery_state == ApprovalDeliveryState.FAILED
    assert approval.delivery_safe_error_code == safe_error
    assert approval.delivery_next_attempt_at is not None


def test_exhausted_delivery_attempts_become_unknown_without_resubmission(
    conversation_records, monkeypatch
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    monkeypatch.setattr(
        "activities.services.approvals._schedule_approval_delivery", lambda: None
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="reject",
        idempotency_key=uuid4(),
    )
    retry_at = timezone.now() - timedelta(seconds=1)
    Approval.objects.filter(pk=approval.pk).update(
        delivery_state=ApprovalDeliveryState.FAILED,
        delivery_attempt_count=5,
        delivery_next_attempt_at=retry_at,
    )

    def submit(*args, **kwargs):
        pytest.fail("exhausted delivery must not be submitted again")

    monkeypatch.setattr(
        "activities.services.approvals.submit_approval_decision", submit
    )
    report = dispatch_pending_approvals(now=timezone.now())
    approval.refresh_from_db()

    assert report.claimed == 0
    assert approval.status == ApprovalStatus.OUTCOME_UNKNOWN
    assert approval.delivery_state == ApprovalDeliveryState.CANCELLED
    assert approval.delivery_safe_error_code == "delivery_attempts_exhausted"


def test_delivery_does_not_submit_after_acknowledgement_deadline_crosses(
    conversation_records, monkeypatch
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    monkeypatch.setattr(
        "activities.services.approvals._schedule_approval_delivery", lambda: None
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=uuid4(),
    )
    approval.refresh_from_db()
    before_deadline = approval.decided_at + timedelta(seconds=1)
    after_deadline = approval.acknowledgement_deadline_at + timedelta(seconds=1)
    Approval.objects.filter(pk=approval.pk).update(
        delivery_state=ApprovalDeliveryState.IN_PROGRESS,
        delivery_attempt_count=1,
        delivery_lease_expires_at=after_deadline + timedelta(seconds=30),
    )
    clock = iter((before_deadline, after_deadline))
    monkeypatch.setattr(
        "activities.services.approvals.timezone.now", lambda: next(clock)
    )

    def submit(*args, **kwargs):
        pytest.fail("expired acknowledgement must not be submitted to Foundry")

    monkeypatch.setattr(
        "activities.services.approvals.submit_approval_decision", submit
    )
    assert _deliver_one(pk=approval.pk, fence=1) == "unknown"
    approval.refresh_from_db()

    assert approval.status == ApprovalStatus.OUTCOME_UNKNOWN
    assert approval.delivery_state == ApprovalDeliveryState.CANCELLED
    assert approval.delivery_safe_error_code == "acknowledgement_timeout"


def test_delivery_rechecks_acknowledgement_deadline_after_gateway_response(
    conversation_records, monkeypatch
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    monkeypatch.setattr(
        "activities.services.approvals._schedule_approval_delivery", lambda: None
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=uuid4(),
    )
    approval.refresh_from_db()
    before_deadline = approval.decided_at + timedelta(seconds=1)
    after_deadline = approval.acknowledgement_deadline_at + timedelta(seconds=1)
    Approval.objects.filter(pk=approval.pk).update(
        delivery_state=ApprovalDeliveryState.IN_PROGRESS,
        delivery_attempt_count=1,
        delivery_lease_expires_at=after_deadline + timedelta(seconds=30),
    )
    clock = iter((before_deadline, before_deadline, after_deadline))
    monkeypatch.setattr(
        "activities.services.approvals.timezone.now", lambda: next(clock)
    )

    def submit(command, *, raw_body):
        return ApprovalDecisionReceipt(
            schema_version="v1",
            kind="approval.receipt",
            status="accepted",
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            approval_request_id=command.approval_request_id,
            fingerprint=command.fingerprint,
        )

    monkeypatch.setattr(
        "activities.services.approvals.submit_approval_decision", submit
    )
    assert _deliver_one(pk=approval.pk, fence=1) == "unknown"
    approval.refresh_from_db()

    assert approval.status == ApprovalStatus.OUTCOME_UNKNOWN
    assert approval.delivery_state == ApprovalDeliveryState.CANCELLED
    assert approval.delivery_safe_error_code == "acknowledgement_timeout"


def test_delivery_rechecks_consent_before_each_outbound_request(
    conversation_records, monkeypatch
):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=uuid4(),
    )
    approval.refresh_from_db()
    before_request = approval.decided_at + timedelta(seconds=1)
    after_consent_expiry = approval.decided_at + timedelta(seconds=11)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=approval.decided_at + timedelta(seconds=10),
        delivery_state=ApprovalDeliveryState.IN_PROGRESS,
        delivery_attempt_count=1,
        delivery_lease_expires_at=after_consent_expiry + timedelta(seconds=30),
    )
    clock = iter((before_request, after_consent_expiry))
    monkeypatch.setattr(
        "activities.services.approvals.timezone.now", lambda: next(clock)
    )

    def submit(*args, **kwargs):
        pytest.fail("expired consent must not be submitted to Foundry")

    monkeypatch.setattr(
        "activities.services.approvals.submit_approval_decision", submit
    )
    assert _deliver_one(pk=approval.pk, fence=1) == "skipped"
    approval.refresh_from_db()
    assert approval.delivery_state == ApprovalDeliveryState.CANCELLED
    assert approval.delivery_safe_error_code == "consent_expired"


def test_approval_detail_and_list_are_membership_scoped(conversation_records):
    user, workspace, _ally, binding, conversation, message = conversation_records
    event, request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(approval_request_id=request_id)

    assert (
        get_approval_detail(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            approval_id=approval.id,
        ).action_preview
        == "echo safe"
    )

    client = Client()
    client.cookies[cookie_name("access")] = issue_session(user).access_token
    response = client.get(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/approvals"
    )
    assert response.status_code == 200
    assert response.json()["data"]["approvals"][0]["id"] == str(approval.id)
    assert response.json()["data"]["approvals"][0]["message_id"] == str(
        approval.message_id
    )
    assert (
        response.json()["data"]["approvals"][0]["acknowledgement_deadline_at"] is None
    )


def test_approval_api_requires_auth_and_write_capability(conversation_records):
    _user, workspace, _ally, binding, conversation, message = conversation_records
    event, _request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(message=message)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    list_path = (
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/approvals"
    )
    detail_path = f"{list_path}/{approval.id}"
    assert Client().get(list_path).status_code == 401

    read_only = User.objects.create_user()
    Membership.objects.create(
        workspace=workspace, user=read_only, role="owner", status="inactive"
    )
    read_only_client = Client()
    read_only_client.cookies[cookie_name("access")] = issue_session(
        read_only
    ).access_token
    assert read_only_client.get(detail_path).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "post"])
def test_approval_api_rejects_foreign_scope(conversation_records, method):
    _user, workspace, _ally, binding, conversation, message = conversation_records
    event, _request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(message=message)
    other = User.objects.create_user()
    other_workspace = workspace.__class__.objects.create(owner=other, name="Other")
    Membership.objects.create(
        workspace=other_workspace, user=other, role="owner", status="active"
    )
    client = Client()
    list_path = (
        f"/api/v1/workspaces/{other_workspace.id}/conversations/{conversation.id}"
        "/approvals"
    )
    path = (
        f"/api/v1/workspaces/{other_workspace.id}/conversations/{conversation.id}"
        f"/approvals/{approval.id}"
    )
    if method == "get":
        client.cookies[cookie_name("access")] = issue_session(other).access_token
        assert client.get(list_path).status_code == 404
        response = client.get(path)
    else:
        session = issue_session(other, client_kind=SessionClientKind.NATIVE)
        response = client.post(
            path + "/decision",
            data='{"decision":"approve"}',
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid4()),
            HTTP_AUTHORIZATION=f"Bearer {session.access_token}",
        )
    assert response.status_code == 404


def test_browser_decision_requires_csrf_and_native_bearer_can_decide(
    conversation_records, monkeypatch, settings
):
    user, workspace, _ally, binding, conversation, message = conversation_records
    event, _request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(message=message)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    path = (
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}"
        f"/approvals/{approval.id}/decision"
    )
    monkeypatch.setattr(
        "activities.services.approvals._schedule_approval_delivery", lambda: None
    )
    settings.CSRF_TRUSTED_ORIGINS = ["http://testserver"]
    browser = Client()
    browser.cookies[cookie_name("access")] = issue_session(user).access_token
    rejected = browser.post(
        path,
        data='{"decision":"approve"}',
        content_type="application/json",
        HTTP_ORIGIN="http://testserver",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert rejected.status_code == 403
    assert rejected.json()["data"]["code"] == "csrf_rejected"

    native = Client()
    native_session = issue_session(user, client_kind=SessionClientKind.NATIVE)
    accepted = native.post(
        path,
        data='{"decision":"reject"}',
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {native_session.access_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert accepted.status_code == 202
    assert accepted.json()["data"]["status"] == ApprovalStatus.DECISION_RECORDED


def test_decision_conflicts_are_bounded_and_expiry_is_lazy(conversation_records):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, _request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(message=message)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    first_key = uuid4()
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=first_key,
    )
    with pytest.raises(ApprovalConflict):
        record_approval_decision(
            user=user,
            workspace_id=approval.workspace_id,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            decision="reject",
            idempotency_key=first_key,
        )
    with pytest.raises(ApprovalConflict):
        record_approval_decision(
            user=user,
            workspace_id=approval.workspace_id,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            decision="approve",
            idempotency_key=uuid4(),
        )

    expired = Approval.objects.create(
        workspace_id=approval.workspace_id,
        ally_id=approval.ally_id,
        conversation_id=approval.conversation_id,
        message_id=approval.message_id,
        approval_request_id=uuid4(),
        cloud_binding_id=approval.cloud_binding_id,
        execution_id=approval.execution_id,
        attempt_id=uuid4(),
        generation=approval.generation,
        attempt_sequence=1,
        action_kind="terminal",
        action_label="Run the command",
        action_preview="echo safe",
        requested_at=timezone.now() - timedelta(minutes=1),
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    assert (
        get_approval_detail(
            user=user,
            workspace_id=expired.workspace_id,
            conversation_id=expired.conversation_id,
            approval_id=expired.id,
        ).status
        == ApprovalStatus.EXPIRED
    )


@pytest.mark.postgresql
@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="requires PostgreSQL row locks"
)
@pytest.mark.django_db(transaction=True)
def test_concurrent_decisions_have_one_first_winner(conversation_records, monkeypatch):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, _request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(message=message)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    monkeypatch.setattr(
        "activities.services.approvals._schedule_approval_delivery", lambda: None
    )
    gate = Barrier(2)

    def decide(decision):
        close_old_connections()
        try:
            gate.wait(timeout=10)
            try:
                return record_approval_decision(
                    user=user,
                    workspace_id=approval.workspace_id,
                    conversation_id=approval.conversation_id,
                    approval_id=approval.id,
                    decision=decision,
                    idempotency_key=uuid4(),
                ).replayed
            except ApprovalConflict:
                return "conflict"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(decide, ["approve", "reject"]))
    assert sorted(outcomes, key=str) == [False, "conflict"]


@pytest.mark.postgresql
@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="requires PostgreSQL row locks"
)
@pytest.mark.django_db(transaction=True)
def test_concurrent_delivery_claims_have_one_winner(conversation_records, monkeypatch):
    user, _workspace, _ally, binding, _conversation, message = conversation_records
    event, _request_id = _rich_event(message, binding)
    project_foundry_event(event)
    approval = Approval.objects.get(message=message)
    Approval.objects.filter(pk=approval.pk).update(
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    monkeypatch.setattr(
        "activities.services.approvals._schedule_approval_delivery", lambda: None
    )
    record_approval_decision(
        user=user,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
        approval_id=approval.id,
        decision="approve",
        idempotency_key=uuid4(),
    )
    claim_time = timezone.now()
    gate = Barrier(2)

    def claim(_worker):
        close_old_connections()
        try:
            gate.wait(timeout=10)
            return _claim_due(now=claim_time, limit=1)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, [1, 2]))
    assert sorted(len(items) for items in claims) == [0, 1]
    approval.refresh_from_db()
    assert approval.delivery_state == ApprovalDeliveryState.IN_PROGRESS
    assert approval.delivery_attempt_count == 1
