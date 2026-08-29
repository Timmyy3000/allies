from __future__ import annotations

import json
from datetime import timedelta
from threading import Barrier, Thread
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import OperationalError, close_old_connections, connection, transaction
from django.utils import timezone

import runtime.services.events as event_services
import runtime.services.leases as lease_services
from runtime.exceptions import (
    RuntimeAuthorizationError,
    RuntimeConflictError,
    RuntimeValidationError,
)
from runtime.models import (
    Attempt,
    AttemptStatus,
    ConversationBinding,
    Execution,
    ExecutionEvent,
    Lease,
    LeaseState,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
)
from runtime.services.events import append_event
from runtime.services.executions import create_execution
from runtime.services.leases import (
    authorize_attempt_mutation,
    create_lease,
    digest_lease_token,
)
from runtime.services.sessions import bind_conversation, compare_and_set_session
from runtime.services.validation import MAX_JSON_NESTING_DEPTH, digest_payload


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(
        tenant_ref="tenant-1",
        fly_app_ref="app-1",
        volume_ref="volume-1",
        machine_ref="machine-1",
        machine_generation=7,
    )


@pytest.fixture
def profiles(workspace):
    return [
        RuntimeProfile.objects.create(
            workspace=workspace,
            ally_ref="ally-a",
            hermes_profile_key="ally_a",
            lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
            materialized_generation=workspace.machine_generation,
        ),
        RuntimeProfile.objects.create(
            workspace=workspace,
            ally_ref="ally-b",
            hermes_profile_key="ally_b",
            lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
            materialized_generation=workspace.machine_generation,
        ),
    ]


_UNSET = object()


def make_execution(workspace, profile, key="request-1", payload=_UNSET):
    return create_execution(
        workspace.id,
        profile.id,
        key,
        {"message": "hello"} if payload is _UNSET else payload,
    )


def make_attempt(execution, number=1):
    return Attempt.objects.create(
        execution=execution,
        number=number,
        machine_generation=execution.workspace.machine_generation,
    )


def make_lease(attempt, token="token"):
    return create_lease(
        attempt.id,
        token,
        timezone.now() + timedelta(minutes=1),
        attempt.execution.workspace.machine_generation,
    )


def unicode_payload_at_limit(limit):
    def serialized_size(character_count):
        return len(
            json.dumps(
                {"text": "é" * character_count},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )

    low, high = 0, limit
    while low < high:
        middle = (low + high + 1) // 2
        if serialized_size(middle) <= limit:
            low = middle
        else:
            high = middle - 1
    payload = {"text": "é" * low}
    oversized = {"text": "é" * (low + 1)}
    assert serialized_size(low) <= limit < serialized_size(low + 1)
    return payload, oversized


def nested_payload(wrappers):
    payload = {"value": 1}
    for _ in range(wrappers):
        payload = {"nested": payload}
    return payload


def test_execution_creation_is_workspace_scoped_and_idempotent(workspace, profiles):
    first = make_execution(workspace, profiles[0])
    replay = make_execution(workspace, profiles[0])

    assert replay.pk == first.pk
    assert Execution.objects.count() == 1
    with pytest.raises(RuntimeConflictError):
        make_execution(workspace, profiles[1])


@pytest.mark.django_db(transaction=True)
def test_concurrent_execution_exact_retries_share_one_execution(workspace, profiles):
    barrier = Barrier(2)
    outcomes = [None, None]

    def create(index):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            outcomes[index] = create_execution(
                workspace.id,
                profiles[0].id,
                "concurrent-execution",
                {"message": "same"},
            ).id
        finally:
            close_old_connections()

    threads = [Thread(target=create, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert outcomes[0] is not None
    assert outcomes[0] == outcomes[1]
    assert (
        Execution.objects.filter(
            workspace=workspace,
            idempotency_key="concurrent-execution",
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_executions_reserve_one_conversation(workspace, profiles):
    barrier = Barrier(2)
    outcomes = [None, None]
    errors = [None, None]

    def create(index):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            outcomes[index] = create_execution(
                workspace.id,
                profiles[0].id,
                f"conversation-race-{index}",
                {
                    "message": f"message-{index}",
                    "cloud_conversation_ref": "conversation-one",
                },
            ).id
        except Exception as exc:  # noqa: BLE001 - surfaced below
            errors[index] = exc
        finally:
            close_old_connections()

    threads = [Thread(target=create, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == [None, None], errors
    assert outcomes[0] is not None
    assert outcomes[1] is not None
    assert outcomes[0] != outcomes[1]
    binding = ConversationBinding.objects.get(profile=profiles[0])
    assert binding.cloud_conversation_ref == "conversation-one"
    assert binding.hermes_session_id is None


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_executions_with_different_conversations_conflict(
    workspace,
    profiles,
):
    barrier = Barrier(2)
    outcomes = [None, None]
    errors = [None, None]

    def create(index):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            create_execution(
                workspace.id,
                profiles[0].id,
                f"conversation-mismatch-{index}",
                {
                    "message": f"message-{index}",
                    "cloud_conversation_ref": f"conversation-{index}",
                },
            )
        except RuntimeConflictError:
            outcomes[index] = "conflict"
        except Exception as exc:  # noqa: BLE001 - surfaced below
            errors[index] = exc
        else:
            outcomes[index] = "created"
        finally:
            close_old_connections()

    threads = [Thread(target=create, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == [None, None], errors
    assert outcomes.count("created") == 1, outcomes
    assert outcomes.count("conflict") == 1, outcomes
    assert ConversationBinding.objects.get(
        profile=profiles[0]
    ).cloud_conversation_ref in {
        "conversation-0",
        "conversation-1",
    }


@pytest.mark.parametrize("payload", [["not", "an", "object"], "text", None])
def test_execution_payload_must_be_a_bounded_object(workspace, profiles, payload):
    with pytest.raises(RuntimeValidationError):
        make_execution(workspace, profiles[0], payload=payload)

    oversized = {"value": "x" * (64 * 1024)}
    with pytest.raises(RuntimeValidationError):
        make_execution(workspace, profiles[0], key="oversized", payload=oversized)


@pytest.mark.parametrize("payload", [{"items": ("tuple",)}, {1: "integer key"}])
def test_execution_payload_rejects_non_strict_json_shapes(workspace, profiles, payload):
    with pytest.raises(RuntimeValidationError):
        make_execution(workspace, profiles[0], key="invalid-shape", payload=payload)


def test_execution_replay_uses_canonical_json_identity(workspace, profiles):
    first = make_execution(
        workspace,
        profiles[0],
        key="canonical-replay",
        payload={"outer": {"b": 2, "a": 1}, "value": True},
    )
    replay = make_execution(
        workspace,
        profiles[0],
        key="canonical-replay",
        payload={"value": True, "outer": {"a": 1, "b": 2}},
    )
    assert replay.pk == first.pk
    with pytest.raises(RuntimeConflictError):
        make_execution(
            workspace,
            profiles[0],
            key="canonical-replay",
            payload={"outer": {"a": 1, "b": 2}, "value": 1},
        )


def test_execution_replay_uses_persisted_payload_digest_for_numeric_spelling(
    workspace,
    profiles,
):
    payload = {"value": 1e20}
    first = make_execution(
        workspace,
        profiles[0],
        key="numeric-replay",
        payload=payload,
    )
    assert first.payload_digest == digest_payload(payload)
    first.input_payload = {"value": 100000000000000000000}
    first.save(update_fields=["input_payload"])

    replay = make_execution(
        workspace,
        profiles[0],
        key="numeric-replay",
        payload=payload,
    )
    assert replay.pk == first.pk


def test_execution_payload_depth_is_bounded(workspace, profiles):
    make_execution(
        workspace,
        profiles[0],
        key="depth-boundary",
        payload=nested_payload(MAX_JSON_NESTING_DEPTH - 1),
    )
    with pytest.raises(RuntimeValidationError):
        make_execution(
            workspace,
            profiles[0],
            key="depth-too-deep",
            payload=nested_payload(MAX_JSON_NESTING_DEPTH),
        )


def test_unicode_execution_and_event_payloads_use_persisted_json_size(
    workspace,
    profiles,
):
    execution_payload, oversized_execution_payload = unicode_payload_at_limit(64 * 1024)
    execution = make_execution(
        workspace,
        profiles[0],
        key="unicode-boundary",
        payload=execution_payload,
    )
    assert execution.input_payload == execution_payload
    with pytest.raises(RuntimeValidationError):
        make_execution(
            workspace,
            profiles[0],
            key="unicode-oversized",
            payload=oversized_execution_payload,
        )

    attempt = make_attempt(execution)
    lease = make_lease(attempt, token="unicode-event-token")
    event_payload, oversized_event_payload = unicode_payload_at_limit(16 * 1024)
    append_event(
        attempt.id,
        lease.id,
        uuid4(),
        1,
        "unicode.boundary",
        event_payload,
        token_digest=digest_lease_token("unicode-event-token"),
        machine_generation=workspace.machine_generation,
    )
    with pytest.raises(RuntimeValidationError):
        append_event(
            attempt.id,
            lease.id,
            uuid4(),
            2,
            "unicode.oversized",
            oversized_event_payload,
            token_digest=digest_lease_token("unicode-event-token"),
            machine_generation=workspace.machine_generation,
        )


def test_session_binding_supports_first_bind_replay_rotation_and_stale_rejection(
    profiles,
):
    first = bind_conversation(profiles[0].id, "conversation-a", "session-1")
    assert first.hermes_session_id == "session-1"
    assert (
        bind_conversation(
            profiles[0].id,
            "conversation-a",
            "session-1",
        ).pk
        == first.pk
    )
    assert (
        compare_and_set_session(
            profiles[0].id,
            "session-1",
            "session-1",
        ).pk
        == first.pk
    )
    assert (
        compare_and_set_session(
            profiles[0].id,
            "session-1",
            "session-2",
        ).hermes_session_id
        == "session-2"
    )
    assert (
        compare_and_set_session(
            profiles[0].id,
            "session-1",
            "session-2",
        ).hermes_session_id
        == "session-2"
    )
    with pytest.raises(RuntimeConflictError):
        compare_and_set_session(profiles[0].id, "session-1", "session-3")
    with pytest.raises(RuntimeConflictError):
        bind_conversation(profiles[1].id, "conversation-a", "session-other")


@pytest.mark.django_db(transaction=True)
def test_concurrent_session_rotations_have_one_winner_and_one_conflict(profiles):
    binding = bind_conversation(profiles[0].id, "concurrent-conversation", "session-1")
    barrier = Barrier(2)
    outcomes = [None, None]

    def rotate(index):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            compare_and_set_session(
                profiles[0].id,
                "session-1",
                f"session-{index + 2}",
            )
        except RuntimeConflictError:
            outcomes[index] = "conflict"
        else:
            outcomes[index] = "success"
        finally:
            close_old_connections()

    threads = [Thread(target=rotate, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert outcomes.count("success") == 1, outcomes
    assert outcomes.count("conflict") == 1, outcomes
    binding.refresh_from_db()
    assert binding.hermes_session_id in {"session-2", "session-3"}


@pytest.mark.django_db(transaction=True)
def test_concurrent_identical_session_rotations_are_idempotent(profiles):
    bind_conversation(profiles[0].id, "identical-conversation", "session-1")
    barrier = Barrier(2)
    outcomes = [None, None]

    def rotate(index):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            compare_and_set_session(
                profiles[0].id,
                "session-1",
                "session-2",
            )
        except RuntimeConflictError:
            outcomes[index] = "conflict"
        else:
            outcomes[index] = "success"
        finally:
            close_old_connections()

    threads = [Thread(target=rotate, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert outcomes == ["success", "success"], outcomes
    assert (
        ConversationBinding.objects.get(pk=profiles[0].id).hermes_session_id
        == "session-2"
    )


def test_unresolved_leases_are_profile_scoped_but_different_profiles_can_overlap(
    workspace,
    profiles,
):
    executions = [
        make_execution(workspace, profile, key=f"request-{i}")
        for i, profile in enumerate(profiles)
    ]
    attempts = [make_attempt(execution) for execution in executions]
    first, second = [
        make_lease(attempt, token=f"token-{i}") for i, attempt in enumerate(attempts)
    ]

    assert first.profile_id != second.profile_id
    same_profile_execution = make_execution(workspace, profiles[0], key="request-third")
    with pytest.raises(RuntimeConflictError):
        make_lease(make_attempt(same_profile_execution), token="token-third")


def test_lease_creation_reports_generic_constraint_conflict(workspace, profiles):
    first_attempt = make_attempt(make_execution(workspace, profiles[0]))
    make_lease(first_attempt, token="duplicate-token")
    second_attempt = make_attempt(
        make_execution(workspace, profiles[1], key="request-2")
    )

    with pytest.raises(
        RuntimeConflictError,
        match="lease creation conflicts with an existing lease",
    ):
        create_lease(
            second_attempt.id,
            "duplicate-token",
            timezone.now() + timedelta(minutes=1),
            workspace.machine_generation,
        )


def test_create_lease_hashes_hex_shaped_raw_tokens(workspace, profiles):
    raw_token = "a" * 64
    attempt = make_attempt(make_execution(workspace, profiles[0]))

    lease = create_lease(
        attempt.id,
        raw_token,
        timezone.now() + timedelta(minutes=1),
        workspace.machine_generation,
    )

    assert lease.token_digest == digest_lease_token(raw_token)
    assert lease.token_digest != raw_token


def test_lease_creation_does_not_mask_unrelated_operational_error(workspace, profiles):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    with (
        patch(
            "runtime.services.leases._create_lease_from_digest",
            side_effect=OperationalError("disk I/O error"),
        ),
        pytest.raises(OperationalError, match="disk I/O error"),
    ):
        create_lease(
            attempt.id,
            "unrelated-error-token",
            timezone.now() + timedelta(minutes=1),
            workspace.machine_generation,
        )


def test_lease_creation_retries_a_transient_lock(workspace, profiles):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    original_create = lease_services._create_lease_from_digest
    calls = 0

    def flaky_create(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("database is locked")
        return original_create(*args, **kwargs)

    with patch.object(
        lease_services,
        "_create_lease_from_digest",
        side_effect=flaky_create,
    ):
        lease = create_lease(
            attempt.id,
            "transient-lock-token",
            timezone.now() + timedelta(minutes=1),
            workspace.machine_generation,
        )

    assert calls == 2
    assert lease.profile_id == profiles[0].id


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_profile_lease_creation_has_one_winner(
    workspace,
    profiles,
):
    """SQLite serializes writes; the unique boundary still has one winner."""

    executions = [
        make_execution(workspace, profiles[0], key=f"concurrent-{index}")
        for index in range(2)
    ]
    attempts = [make_attempt(execution) for execution in executions]
    barrier = Barrier(2)
    outcomes = [None, None]

    def create(index):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            create_lease(
                attempts[index].id,
                f"concurrent-token-{index}",
                timezone.now() + timedelta(minutes=1),
                workspace.machine_generation,
            )
        except RuntimeConflictError:
            outcomes[index] = "conflict"
        else:
            outcomes[index] = "created"
        finally:
            close_old_connections()

    threads = [Thread(target=create, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert outcomes.count("created") == 1
    assert outcomes.count("conflict") == 1, outcomes
    assert Lease.objects.filter(profile=profiles[0]).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_different_profile_lease_creation_can_both_persist(
    workspace,
    profiles,
):
    """A SQLite serialization loser can retry after the other commit."""

    executions = [
        make_execution(workspace, profile, key=f"parallel-{index}")
        for index, profile in enumerate(profiles)
    ]
    attempts = [make_attempt(execution) for execution in executions]
    tokens = [f"parallel-token-{index}" for index in range(2)]
    barrier = Barrier(2)
    outcomes = [None, None]

    def create(index):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            create_lease(
                attempts[index].id,
                tokens[index],
                timezone.now() + timedelta(minutes=1),
                workspace.machine_generation,
            )
        except RuntimeConflictError:
            outcomes[index] = "conflict"
        else:
            outcomes[index] = "created"
        finally:
            close_old_connections()

    threads = [Thread(target=create, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(outcome in {"created", "conflict"} for outcome in outcomes), outcomes
    for index, outcome in enumerate(outcomes):
        if outcome == "conflict":
            create_lease(
                attempts[index].id,
                tokens[index],
                timezone.now() + timedelta(minutes=1),
                workspace.machine_generation,
            )

    assert Lease.objects.filter(profile__in=profiles).count() == 2
    assert set(Lease.objects.values_list("profile_id", flat=True)) == {
        profiles[0].id,
        profiles[1].id,
    }


@pytest.mark.django_db(transaction=True)
def test_attempt_mutation_requires_lease_digest_and_current_machine_generation(
    workspace,
    profiles,
):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt)

    with pytest.raises(
        RuntimeValidationError,
        match="requires an atomic transaction",
    ):
        lease_services._authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest_lease_token("token"),
            workspace.machine_generation,
        )
    with transaction.atomic():
        authorization = lease_services._authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest_lease_token("token"),
            workspace.machine_generation,
        )
    assert not isinstance(authorization, Attempt)
    assert authorization.attempt_id == attempt.id

    claimed_at = timezone.now()
    assert (
        authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest_lease_token("token"),
            workspace.machine_generation,
            status=AttemptStatus.RUNNING,
            claimed_at=claimed_at,
        )
        is None
    )
    assert Attempt.objects.get(pk=attempt.pk).status == AttemptStatus.RUNNING
    assert Attempt.objects.get(pk=attempt.pk).claimed_at == claimed_at

    with pytest.raises(RuntimeAuthorizationError):
        authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest_lease_token("wrong-token"),
            workspace.machine_generation,
            status=AttemptStatus.FAILED,
        )
    with pytest.raises(RuntimeAuthorizationError):
        authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest_lease_token("token"),
            workspace.machine_generation + 1,
            status=AttemptStatus.FAILED,
        )
    assert Attempt.objects.get(pk=attempt.pk).status == AttemptStatus.RUNNING

    authorize_attempt_mutation(
        attempt.id,
        lease.id,
        digest_lease_token("token"),
        workspace.machine_generation,
        claimed_at=claimed_at,
    )
    assert Attempt.objects.get(pk=attempt.pk).claimed_at == claimed_at

    with pytest.raises(RuntimeValidationError, match="requires a field"):
        authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest_lease_token("token"),
            workspace.machine_generation,
        )


@pytest.mark.parametrize("expiry_delta", [timedelta(seconds=-1), timedelta(0)])
def test_attempt_mutation_rejects_expired_or_exactly_expiring_leases(
    workspace,
    profiles,
    expiry_delta,
):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt)
    observed_now = timezone.now()
    lease.expires_at = observed_now + expiry_delta
    lease.save(update_fields=["expires_at", "updated_at"])

    with (
        patch(
            "runtime.services.leases.timezone.now",
            return_value=observed_now,
        ),
        pytest.raises(RuntimeAuthorizationError),
    ):
        authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest_lease_token("token"),
            workspace.machine_generation,
            status=AttemptStatus.FAILED,
        )
    assert Attempt.objects.get(pk=attempt.pk).status == AttemptStatus.QUEUED


def test_attempt_mutation_enforces_state_transitions_and_terminal_immutability(
    workspace,
    profiles,
):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt, token="transition-token")
    digest = digest_lease_token("transition-token")
    claimed_at = timezone.now()

    authorize_attempt_mutation(
        attempt.id,
        lease.id,
        digest,
        workspace.machine_generation,
        status=AttemptStatus.LEASED,
        claimed_at=claimed_at,
    )
    authorize_attempt_mutation(
        attempt.id,
        lease.id,
        digest,
        workspace.machine_generation,
        status=AttemptStatus.RUNNING,
    )
    authorize_attempt_mutation(
        attempt.id,
        lease.id,
        digest,
        workspace.machine_generation,
        status=AttemptStatus.SUCCEEDED,
    )
    authorize_attempt_mutation(
        attempt.id,
        lease.id,
        digest,
        workspace.machine_generation,
        status=AttemptStatus.SUCCEEDED,
    )

    with pytest.raises(RuntimeConflictError, match="status transition"):
        authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest,
            workspace.machine_generation,
            status=AttemptStatus.RUNNING,
        )
    with pytest.raises(RuntimeConflictError, match="claimed_at"):
        authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest,
            workspace.machine_generation,
            claimed_at=None,
        )
    with pytest.raises(RuntimeConflictError, match="claimed_at"):
        authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest,
            workspace.machine_generation,
            claimed_at=claimed_at + timedelta(seconds=1),
        )

    persisted = Attempt.objects.get(pk=attempt.pk)
    assert persisted.status == AttemptStatus.SUCCEEDED
    assert persisted.claimed_at == claimed_at


def test_attempt_mutation_and_events_require_active_lease(
    workspace,
    profiles,
):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt, token="stopping-token")
    lease.state = LeaseState.STOPPING
    lease.save(update_fields=["state", "updated_at"])
    digest = digest_lease_token("stopping-token")

    with pytest.raises(RuntimeAuthorizationError):
        authorize_attempt_mutation(
            attempt.id,
            lease.id,
            digest,
            workspace.machine_generation,
            status=AttemptStatus.RUNNING,
            claimed_at=timezone.now(),
        )
    with pytest.raises(RuntimeAuthorizationError):
        append_event(
            attempt.id,
            lease.id,
            uuid4(),
            1,
            "message.delta",
            {"text": "blocked"},
            token_digest=digest,
            machine_generation=workspace.machine_generation,
        )
    persisted = Attempt.objects.get(pk=attempt.pk)
    assert persisted.status == AttemptStatus.QUEUED
    assert persisted.claimed_at is None
    assert not ExecutionEvent.objects.filter(attempt=attempt).exists()


def test_event_append_is_ordered_and_exactly_replayable(workspace, profiles):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt)
    digest = digest_lease_token("token")
    event_id = uuid4()
    first = append_event(
        attempt.id,
        lease.id,
        event_id,
        1,
        "message.delta",
        {"text": "hello"},
        token_digest=digest,
        machine_generation=workspace.machine_generation,
    )
    replay = append_event(
        attempt.id,
        lease.id,
        event_id,
        1,
        "message.delta",
        {"text": "hello"},
        token_digest=digest,
        machine_generation=workspace.machine_generation,
    )
    assert replay.pk == first.pk
    with pytest.raises(RuntimeConflictError):
        append_event(
            attempt.id,
            lease.id,
            uuid4(),
            1,
            "other",
            {},
            token_digest=digest,
            machine_generation=workspace.machine_generation,
        )
    next_event = append_event(
        attempt.id,
        lease.id,
        uuid4(),
        2,
        "message.done",
        {},
        token_digest=digest,
        machine_generation=workspace.machine_generation,
    )
    assert next_event.sequence == 2
    assert ExecutionEvent.objects.filter(attempt=attempt).count() == 2


def test_event_append_replays_terminal_events_but_rejects_new_events(
    workspace,
    profiles,
):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt, token="terminal-event-token")
    digest = digest_lease_token("terminal-event-token")
    event_id = uuid4()
    first = append_event(
        attempt.id,
        lease.id,
        event_id,
        1,
        "message.delta",
        {"text": "before-terminal"},
        token_digest=digest,
        machine_generation=workspace.machine_generation,
    )
    authorize_attempt_mutation(
        attempt.id,
        lease.id,
        digest,
        workspace.machine_generation,
        status=AttemptStatus.RUNNING,
        claimed_at=timezone.now(),
    )
    authorize_attempt_mutation(
        attempt.id,
        lease.id,
        digest,
        workspace.machine_generation,
        status=AttemptStatus.SUCCEEDED,
    )

    replay = append_event(
        attempt.id,
        lease.id,
        event_id,
        1,
        "message.delta",
        {"text": "before-terminal"},
        token_digest=digest,
        machine_generation=workspace.machine_generation,
    )
    assert replay.pk == first.pk
    with pytest.raises(RuntimeConflictError, match="terminal attempt"):
        append_event(
            attempt.id,
            lease.id,
            uuid4(),
            2,
            "message.done",
            {},
            token_digest=digest,
            machine_generation=workspace.machine_generation,
        )
    assert ExecutionEvent.objects.filter(attempt=attempt).count() == 1


def test_event_replay_uses_canonical_json_identity(workspace, profiles):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt, token="canonical-event-token")
    digest = digest_lease_token("canonical-event-token")
    event_id = uuid4()
    append_event(
        attempt.id,
        lease.id,
        event_id,
        1,
        "message.delta",
        {"outer": {"b": 2, "a": 1}, "value": True},
        token_digest=digest,
        machine_generation=workspace.machine_generation,
    )
    replay = append_event(
        attempt.id,
        lease.id,
        event_id,
        1,
        "message.delta",
        {"value": True, "outer": {"a": 1, "b": 2}},
        token_digest=digest,
        machine_generation=workspace.machine_generation,
    )
    assert replay.event_id == event_id
    with pytest.raises(RuntimeConflictError):
        append_event(
            attempt.id,
            lease.id,
            event_id,
            1,
            "message.delta",
            {"outer": {"a": 1, "b": 2}, "value": 1},
            token_digest=digest,
            machine_generation=workspace.machine_generation,
        )


def test_event_append_retries_a_transient_lock(workspace, profiles):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt, token="transient-event-lock-token")
    digest = digest_lease_token("transient-event-lock-token")
    event_id = uuid4()
    original_append = event_services._append_event_once
    calls = 0

    def flaky_append(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("database is locked")
        return original_append(*args, **kwargs)

    with patch.object(
        event_services,
        "_append_event_once",
        side_effect=flaky_append,
    ):
        event = append_event(
            attempt.id,
            lease.id,
            event_id,
            1,
            "message.transient-lock",
            {"text": "hello"},
            token_digest=digest,
            machine_generation=workspace.machine_generation,
        )

    assert calls == 2
    assert event.event_id == event_id


@pytest.mark.django_db(transaction=True)
def test_concurrent_event_appends_for_different_attempts_can_both_persist(
    workspace,
    profiles,
):
    attempts = [
        make_attempt(make_execution(workspace, profile, key=f"event-{index}"))
        for index, profile in enumerate(profiles)
    ]
    leases = [
        make_lease(attempt, token=f"concurrent-event-token-{index}")
        for index, attempt in enumerate(attempts)
    ]
    token_digests = [
        digest_lease_token(f"concurrent-event-token-{index}") for index in range(2)
    ]
    event_ids = [uuid4(), uuid4()]
    barrier = Barrier(2)
    outcomes = [None, None]
    errors = [None, None]

    def append(index):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            outcomes[index] = append_event(
                attempts[index].id,
                leases[index].id,
                event_ids[index],
                1,
                "message.concurrent",
                {"text": "same"},
                token_digest=token_digests[index],
                machine_generation=workspace.machine_generation,
            ).id
        except (OperationalError, RuntimeConflictError) as exc:
            errors[index] = exc
        finally:
            close_old_connections()

    threads = [Thread(target=append, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == [None, None], errors
    assert outcomes[0] is not None
    assert outcomes[1] is not None
    assert ExecutionEvent.objects.count() == 2


def test_event_replay_uses_persisted_payload_digest_for_numeric_spelling(
    workspace,
    profiles,
):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt, token="numeric-event-token")
    digest = digest_lease_token("numeric-event-token")
    event_id = uuid4()
    payload = {"value": 1e20}
    first = append_event(
        attempt.id,
        lease.id,
        event_id,
        1,
        "message.delta",
        payload,
        token_digest=digest,
        machine_generation=workspace.machine_generation,
    )
    assert first.payload_digest == digest_payload(payload)
    first.payload = {"value": 100000000000000000000}
    first.save(update_fields=["payload"])

    replay = append_event(
        attempt.id,
        lease.id,
        event_id,
        1,
        "message.delta",
        payload,
        token_digest=digest,
        machine_generation=workspace.machine_generation,
    )
    assert replay.pk == first.pk


def test_event_payload_depth_is_bounded(workspace, profiles):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt, token="depth-event-token")
    token_digest = digest_lease_token("depth-event-token")
    make_payload = nested_payload(MAX_JSON_NESTING_DEPTH - 1)
    append_event(
        attempt.id,
        lease.id,
        uuid4(),
        1,
        "message.depth",
        make_payload,
        token_digest=token_digest,
        machine_generation=workspace.machine_generation,
    )
    with pytest.raises(RuntimeValidationError):
        append_event(
            attempt.id,
            lease.id,
            uuid4(),
            2,
            "message.too-deep",
            nested_payload(MAX_JSON_NESTING_DEPTH),
            token_digest=token_digest,
            machine_generation=workspace.machine_generation,
        )


def test_event_append_rejects_stale_writer_and_oversized_payload(workspace, profiles):
    attempt = make_attempt(make_execution(workspace, profiles[0]))
    lease = make_lease(attempt)
    with pytest.raises(RuntimeAuthorizationError):
        append_event(
            attempt.id,
            lease.id,
            uuid4(),
            1,
            "message.delta",
            {},
            token_digest=digest_lease_token("wrong-token"),
            machine_generation=workspace.machine_generation,
        )
    with pytest.raises(RuntimeValidationError):
        append_event(
            attempt.id,
            lease.id,
            uuid4(),
            1,
            "message.delta",
            {"text": "x" * (16 * 1024)},
            token_digest=digest_lease_token("token"),
            machine_generation=workspace.machine_generation,
        )
    assert not ExecutionEvent.objects.exists()


def test_runtime_records_reload_after_database_connection_reopens(workspace, profiles):
    profile = profiles[0]
    binding = bind_conversation(profile.id, "conversation-restart", "session-restart")
    execution = make_execution(workspace, profile)
    attempt = make_attempt(execution)
    lease = make_lease(attempt)
    connection.close()

    reloaded = RuntimeProfile.objects.get(pk=profile.pk)
    assert reloaded.conversation_binding.hermes_session_id == binding.hermes_session_id
    assert (
        Execution.objects.get(pk=execution.pk).attempts.get(pk=attempt.pk).lease.pk
        == lease.pk
    )
    assert Lease.objects.get(pk=lease.pk).token_digest != "token"
    assert ConversationBinding.objects.filter(pk=profile.pk).exists()
