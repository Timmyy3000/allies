import hashlib
import json
import re
from datetime import UTC, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from allies.gateways.contracts import canonical_json_bytes

CONTRACT_ROOT = Path(__file__).resolve().parents[3] / "docs" / "contracts"
DOCUMENT_PATH = CONTRACT_ROOT / "routines-v1.md"
FIXTURE_PATH = CONTRACT_ROOT / "fixtures" / "routines-v1.json"
LOCK_PATH = CONTRACT_ROOT / "routines-v1.lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )


def _fixture() -> dict:
    return _load_json(FIXTURE_PATH)


MESSAGE_PATHS = (
    tuple(
        ("management", operation, "request")
        for operation in (
            "create",
            "update",
            "pause",
            "resume",
            "delete",
            "get",
            "list",
        )
    )
    + tuple(
        ("management", operation, "receipt")
        for operation in ("create", "update", "pause", "resume", "delete")
    )
    + (
        ("management", "get", "response"),
        ("management", "list", "response"),
        ("dispatch", "command"),
        ("dispatch", "receipt"),
        ("result", "event"),
        ("result", "receipt"),
        ("approval", "requested"),
        ("approval", "decision"),
        ("approval", "receipt"),
        ("approval", "cancel_wait"),
    )
)


def _at_path(value: dict, path: tuple[str, ...]) -> dict:
    for key in path:
        value = value[key]
    return value


def _utc_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _next_weekly_utc(after: datetime, schedule: dict) -> datetime:
    zone = ZoneInfo(schedule["timezone"])
    local_after = after.astimezone(zone)
    for offset in range(8):
        local_date = local_after.date() + timedelta(days=offset)
        if local_date.isoweekday() not in schedule["days_of_week"]:
            continue
        local_candidate = datetime.combine(
            local_date,
            time.fromisoformat(schedule["local_time"]),
            tzinfo=zone,
        )
        candidate = local_candidate.astimezone(UTC)
        if candidate > after:
            return candidate
    raise AssertionError("weekly schedule has no future candidate")


def _confirmation_binding(reference: dict) -> dict:
    scope = reference["scope"]
    return {
        "workspace_id": scope["workspace_id"],
        "owner_user_id": scope["owner_user_id"],
        "ally_id": scope["ally_id"],
        "cloud_binding_id": scope["cloud_binding_id"],
        "main_conversation_id": reference["main_conversation_id"],
        "routine_id": reference["routine_id"],
        "expected_revision": reference["expected_revision"],
    }


def test_routines_v1_artifacts_match_cloud_owned_lock():
    fixture = _fixture()
    lock = _load_json(LOCK_PATH)

    assert lock == {
        "contract_name": "routines",
        "schema_version": "v1",
        "content_revision": 14,
        "normative_owner": "cloud",
        "content_sha256": _sha256(DOCUMENT_PATH),
        "fixture_sha256": _sha256(FIXTURE_PATH),
        "hash_algorithm": "sha256",
        "hash_encoding": "utf-8-no-bom-lf-final-newline",
        "future_enforcement_owners": ["CLD-013", "FND-012", "integration"],
    }
    assert fixture["contract"]["contract_name"] == lock["contract_name"]
    assert fixture["contract"]["schema_version"] == lock["schema_version"]
    assert fixture["contract"]["content_revision"] == lock["content_revision"]
    assert fixture["contract"]["normative_owner"] == lock["normative_owner"]
    document_revision = re.search(
        r"^content_revision=(\d+)$",
        DOCUMENT_PATH.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert document_revision
    assert int(document_revision.group(1)) == lock["content_revision"]

    document_bytes = DOCUMENT_PATH.read_bytes()
    fixture_bytes = FIXTURE_PATH.read_bytes()
    assert not document_bytes.startswith(b"\xef\xbb\xbf")
    assert not fixture_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in document_bytes
    assert b"\r" not in fixture_bytes
    assert document_bytes.endswith(b"\n")
    assert fixture_bytes.endswith(b"\n")


def test_routines_v1_fixture_covers_shapes_and_future_owner_metadata():
    fixture = _fixture()
    assert set(fixture["management"]) == {
        "create",
        "update",
        "pause",
        "resume",
        "delete",
        "get",
        "list",
    }
    assert set(fixture) >= {
        "management",
        "management_success_codes",
        "deletion_confirmation",
        "discovery",
        "schedule",
        "dispatch",
        "result",
        "approval",
        "lifecycle",
        "correlation",
        "idempotency",
        "revision",
        "errors",
        "race_cases",
        "cases",
    }

    identity = fixture["identity"]
    uuid_fields = {key for key in identity if key.endswith(("_id", "_key"))}
    assert all(UUID(identity[key]) for key in uuid_fields)
    assert identity["main_conversation_id"] != identity["run_conversation_id"]
    assert identity["run_conversation_id"] != identity["execution_id"]
    assert identity["main_conversation_id"] != identity["execution_id"]

    allowed_owners = {"CLD-013", "FND-012", "integration"}
    cases = fixture["cases"] + fixture["race_cases"]
    assert len(cases) >= 30
    assert len({case["case_id"] for case in cases}) == len(cases)
    for case in cases:
        assert {
            "case_id",
            "requirement",
            "preconditions",
            "actions",
            "expected_postcondition",
            "enforcing_owner",
        } <= set(case)
        assert (
            len({"expected_result_code", "expected_constraint_outcome"} & set(case))
            == 1
        )
        if "input" in case:
            assert isinstance(case["input"], str) and case["input"]
        assert case["enforcing_owner"] in allowed_owners
        assert case["actions"]
    assert {error["enforcing_owner"] for error in fixture["errors"]} <= allowed_owners
    error_codes = {error["code"] for error in fixture["errors"]}
    manual_reconciliation = next(
        case for case in cases if case["case_id"] == "lifecycle-terminal"
    )
    assert manual_reconciliation["input"] == "approval.crash_vectors"
    assert manual_reconciliation["preconditions"] == [
        "action attempt is unknown after ambiguous external outcome"
    ]
    assert manual_reconciliation["actions"] == [
        "transition unknown to manual_reconciliation",
        "stop automatic processing",
    ]
    assert (
        manual_reconciliation["expected_result_code"] == "ACTION_MANUAL_RECONCILIATION"
    )
    assert manual_reconciliation["expected_result_code"] in error_codes
    assert manual_reconciliation["expected_postcondition"] == (
        "action attempt reaches manual_reconciliation; automatic processing stops "
        "and any later human reconciliation never reopens the terminal run"
    )
    action_attempt_states = fixture["approval"]["action_attempt_states"]
    assert action_attempt_states.index("manual_reconciliation") == (
        action_attempt_states.index("unknown") + 1
    )
    assert {
        "STALE_DUE_CANDIDATE",
        "CONFIRMATION_REQUIRED",
        "CONFIRMATION_STALE",
        "CONFIRMATION_REPLAYED",
        "CONFIRMATION_WRONG_CONVERSATION",
        "CONFIRMATION_WRONG_OWNER",
        "CONFIRMATION_WRONG_WORKSPACE",
        "CONFIRMATION_WRONG_ALLY",
        "CONFIRMATION_WRONG_BINDING",
        "CONFIRMATION_WRONG_ROUTINE",
        "APPROVAL_EXPIRED",
        "ACTION_OUTCOME_UNKNOWN",
        "RESULT_INSERTED_ONCE",
    } <= {error["code"] for error in fixture["errors"]}
    assert fixture["management_success_codes"] == [
        "MANAGEMENT_SAVED",
        "ROUTINE_RESUMED",
    ]

    confirmation = fixture["deletion_confirmation"]
    assert confirmation["shape"] == {
        "required_fields": [
            "confirmation_ref",
            "scope",
            "main_conversation_id",
            "routine_id",
            "expected_revision",
            "state",
        ],
        "state_values": ["unconsumed", "consumed"],
        "client_transport_fields": ["confirmation_ref"],
        "downstream_observability_fields": ["confirmation_ref_digest"],
        "transport_rule": "authenticated_delete_request_only",
        "binding_fields": [
            "scope",
            "main_conversation_id",
            "routine_id",
            "expected_revision",
        ],
    }
    assert confirmation["observability"] == {
        "raw_confirmation_ref_logging_allowed": False,
        "raw_confirmation_ref_tracing_allowed": False,
        "correlation_field": "confirmation_ref_digest",
        "correlation_digest": "HMAC-SHA-256(telemetry_key, confirmation_ref)",
        "digest_is_reversible": False,
    }
    assert "atomically" in confirmation["reference_consumption_policy"]
    assert "not consumed" in confirmation["reference_consumption_policy"]
    references = confirmation["references"]
    assert set(references) == {
        "valid",
        "missing",
        "stale",
        "replayed",
        "foreign_conversation",
        "foreign_owner",
        "foreign_workspace",
        "foreign_ally",
        "foreign_binding",
        "cross_routine",
    }
    assert confirmation["valid_reference"] == references["valid"]
    valid_reference = references["valid"]
    assert valid_reference["scope"] == fixture["common"]["scope"]
    assert valid_reference["main_conversation_id"] == identity["main_conversation_id"]
    assert valid_reference["routine_id"] == identity["routine_id"]
    assert (
        valid_reference["expected_revision"]
        == fixture["management"]["delete"]["request"]["expected_revision"]
    )
    assert valid_reference["state"] == "unconsumed"

    delete_request = fixture["management"]["delete"]["request"]
    assert delete_request["confirmation_ref"] == valid_reference["confirmation_ref"]
    assert not {
        "confirmation_scope",
        "confirmation_state",
        "confirmation_main_conversation_id",
        "confirmation_routine_id",
        "confirmation_ref_digest",
    } & set(delete_request)

    required_fields = set(confirmation["shape"]["required_fields"])
    scope_fields = set(valid_reference["scope"])
    scope_uuid_fields = (
        "workspace_id",
        "owner_user_id",
        "ally_id",
        "cloud_binding_id",
    )
    non_missing_names = (
        "valid",
        "stale",
        "replayed",
        "foreign_conversation",
        "foreign_owner",
        "foreign_workspace",
        "foreign_ally",
        "foreign_binding",
        "cross_routine",
    )
    for name in non_missing_names:
        reference = references[name]
        assert set(reference) == required_fields
        assert set(reference["scope"]) == scope_fields
        assert reference["scope"]["kind"] == "workspace"
        UUID(reference["confirmation_ref"])
        for field in scope_uuid_fields:
            UUID(reference["scope"][field])
        UUID(reference["main_conversation_id"])
        UUID(reference["routine_id"])
        assert isinstance(reference["expected_revision"], int)
        assert not isinstance(reference["expected_revision"], bool)
        assert reference["expected_revision"] > 0
        assert reference["state"] in confirmation["shape"]["state_values"]

    assert references["missing"] is None
    expected_binding_differences = {
        "valid": set(),
        "stale": {"expected_revision"},
        "replayed": set(),
        "foreign_conversation": {"main_conversation_id"},
        "foreign_owner": {"owner_user_id"},
        "foreign_workspace": {"workspace_id"},
        "foreign_ally": {"ally_id"},
        "foreign_binding": {"cloud_binding_id"},
        "cross_routine": {"routine_id"},
    }
    valid_binding = _confirmation_binding(valid_reference)
    for name, differences in expected_binding_differences.items():
        reference = references[name]
        actual_binding = _confirmation_binding(reference)
        assert {
            field
            for field in valid_binding
            if actual_binding[field] != valid_binding[field]
        } == differences
        if name == "replayed":
            assert reference["confirmation_ref"] == valid_reference["confirmation_ref"]
            assert reference["state"] == "consumed"
        else:
            assert reference["state"] == "unconsumed"

    confirmation_cases = {
        case["case_id"]: case
        for case in fixture["cases"]
        if case["case_id"].startswith("delete-confirmation-")
    }
    expected_confirmation_codes = {
        "valid": "MANAGEMENT_SAVED",
        "missing": "CONFIRMATION_REQUIRED",
        "stale": "CONFIRMATION_STALE",
        "replayed": "CONFIRMATION_REPLAYED",
        "foreign-conversation": "CONFIRMATION_WRONG_CONVERSATION",
        "foreign-owner": "CONFIRMATION_WRONG_OWNER",
        "foreign-workspace": "CONFIRMATION_WRONG_WORKSPACE",
        "foreign-ally": "CONFIRMATION_WRONG_ALLY",
        "foreign-binding": "CONFIRMATION_WRONG_BINDING",
        "cross-routine": "CONFIRMATION_WRONG_ROUTINE",
    }
    assert set(confirmation_cases) == {
        f"delete-confirmation-{name}" for name in expected_confirmation_codes
    }
    for name, expected_code in expected_confirmation_codes.items():
        case = confirmation_cases[f"delete-confirmation-{name}"]
        reference_name = name.replace("-", "_")
        assert case["input"] == f"deletion_confirmation.{reference_name}"
        assert case["reference"] == (
            f"deletion_confirmation.references.{reference_name}"
        )
        assert (
            _at_path(fixture, tuple(case["reference"].split(".")))
            == references[reference_name]
        )
        assert case["expected_result_code"] == expected_code
        assert case["enforcing_owner"] == "CLD-013"
        assert case["actions"]
        if name == "valid":
            assert case["routine_mutated"] is True
            assert case["confirmation_consumed"] is True
            assert "atomically" in case["expected_postcondition"]
        else:
            assert case["routine_mutated"] is False
            assert case["confirmation_consumed"] is False
            assert "zero routine mutation" in case["expected_postcondition"]
            assert "no success receipt" in case["expected_postcondition"]
            if name == "replayed":
                assert "remains consumed" in case["expected_postcondition"]
            elif name != "missing":
                assert "remains unconsumed" in case["expected_postcondition"]


def test_routines_v1_management_cases_match_durable_receipts_and_separate_stale_case():
    fixture = _fixture()
    scope = fixture["common"]["scope"]
    expected_codes = {
        "create": "MANAGEMENT_SAVED",
        "update": "MANAGEMENT_SAVED",
        "pause": "MANAGEMENT_SAVED",
        "resume": "ROUTINE_RESUMED",
        "delete": "MANAGEMENT_SAVED",
    }
    expected_states = {
        "create": "active",
        "update": "active",
        "pause": "paused",
        "resume": "active",
        "delete": "deleted",
    }
    for operation, expected_code in expected_codes.items():
        case = next(
            case
            for case in fixture["cases"]
            if case["case_id"] == f"management-{operation}"
        )
        request = fixture["management"][operation]["request"]
        receipt = fixture["management"][operation]["receipt"]
        assert request["operation"] == operation
        assert case["expected_result_code"] == expected_code
        assert case["expected_result_code"] == receipt["result_code"]
        assert receipt["outcome"] == "saved"
        assert receipt["operation"] == operation
        assert receipt["routine_id"] == fixture["identity"]["routine_id"]
        assert receipt["schedule_state"] == expected_states[operation]
        assert receipt["scope"] == scope
        assert receipt["command_id"] == request["command_id"]
        assert receipt["idempotency_key"] == request["idempotency_key"]
        assert "owner authorized" in case["preconditions"]
        assert "management receipt" in case["actions"][-1]
        assert "durable management receipt" in case["expected_postcondition"]

        if operation != "create":
            assert "expected revision matches" in case["preconditions"]

    update_schedule = fixture["management"]["update"]["request"]["body"]["schedule"]
    assert update_schedule["kind"] == "recurring"
    pause_case = next(
        case for case in fixture["cases"] if case["case_id"] == "management-pause"
    )
    assert "recurring schedule" in pause_case["preconditions"]
    assert (
        fixture["management"]["pause"]["request"]["expected_revision"]
        == fixture["management"]["update"]["receipt"]["revision"]
    )
    assert fixture["management"]["pause"]["receipt"]["schedule_state"] == "paused"
    assert fixture["management"]["create"]["receipt"]["schedule_generation"] == 1
    assert fixture["management"]["update"]["receipt"]["schedule_generation"] == 2
    assert fixture["management"]["pause"]["receipt"]["schedule_generation"] == 3
    assert fixture["management"]["resume"]["receipt"]["schedule_generation"] == 4
    assert fixture["schedule"]["resume"]["schedule_generation"] == 4
    assert fixture["dispatch"]["command"]["schedule_generation"] == 4
    assert (
        fixture["dispatch"]["command"]["schedule"]
        == fixture["management"]["update"]["request"]["body"]["schedule"]
    )
    assert fixture["dispatch"]["command"]["schedule"]["timezone"] == "Europe/Berlin"
    assert (
        fixture["management"]["resume"]["request"]["expected_revision"]
        == fixture["management"]["pause"]["receipt"]["revision"]
    )
    assert fixture["management"]["resume"]["receipt"]["schedule_state"] == "active"
    assert (
        fixture["management"]["resume"]["receipt"]["next_run_at"]
        > fixture["management"]["resume"]["receipt"]["resume_effective_at"]
    )

    constraint_cases = {
        case["case_id"]: case
        for case in fixture["cases"]
        if case["case_id"].startswith("constraint-")
    }
    assert {
        case["case_id"]: case["expected_constraint_outcome"]
        for case in constraint_cases.values()
    } == {
        "constraint-binding": "BINDING_PROFILE_CONFLICT",
        "constraint-lease": "PROFILE_LEASE_ACTIVE",
        "constraint-claim": "CLAIM_SKIPPED_PROFILE_LEASE",
    }

    correlation = fixture["correlation"]
    assert set(correlation["required_dispatch"]).isdisjoint(
        {"execution_id", "attempt_id", "generation"}
    )
    assert correlation["required_dispatch_receipt"] == [
        "execution_id",
        "attempt_id",
        "generation",
    ]

    stale = next(
        case for case in fixture["cases"] if case["case_id"] == "revision-stale"
    )
    assert stale["expected_result_code"] == "REVISION_CONFLICT"
    assert "expected revision old; current revision newer" in stale["preconditions"]
    assert "zero-write" in stale["expected_postcondition"]
    assert "no saved management receipt" in stale["expected_postcondition"]

    race_cases = {case["case_id"]: case for case in fixture["race_cases"]}
    assert race_cases["race-delete-due"]["expected_result_code"] == "ROUTINE_DELETED"
    assert race_cases["race-pause-due"]["expected_result_code"] == "ROUTINE_PAUSED"
    assert (
        race_cases["race-update-due"]["expected_result_code"] == "STALE_DUE_CANDIDATE"
    )
    assert (
        race_cases["race-resume-due"]["expected_result_code"] == "STALE_DUE_CANDIDATE"
    )
    assert race_cases["race-resume-due"]["preconditions"] == [
        "routine paused after effective pause at generation 3",
        "candidate generation 3",
    ]
    assert race_cases["race-resume-due"]["actions"] == [
        "resume to generation 4",
        "admit generation 3",
    ]
    dispatch_retry = next(
        case for case in fixture["cases"] if case["case_id"] == "dispatch-retry"
    )
    assert dispatch_retry["expected_result_code"] == "OCCURRENCE_REPLAY"
    assert dispatch_retry["enforcing_owner"] == "CLD-013"
    assert all(
        case["expected_result_code"] not in fixture["management_success_codes"]
        for case in fixture["race_cases"]
    )

    deleted_receipt = fixture["management"]["delete"]["receipt"]
    detail = fixture["management"]["get"]["response"]
    page = fixture["management"]["list"]["response"]
    assert deleted_receipt["schedule_state"] == "deleted"
    assert detail["revision"] == deleted_receipt["revision"]
    assert detail["schedule_state"] == "deleted"
    assert detail["next_run_at"] is None
    assert page["items"] == []
    assert page["next_cursor"] is None
    assert (
        fixture["management"]["get"]["request"]["issued_at"]
        > deleted_receipt["issued_at"]
    )
    assert (
        fixture["management"]["list"]["request"]["issued_at"]
        > deleted_receipt["issued_at"]
    )


def test_routines_v1_receipt_schedule_instants_follow_configured_weekly_schedule():
    fixture = _fixture()
    checks = (
        (
            fixture["management"]["create"]["receipt"],
            fixture["management"]["create"]["request"]["body"]["schedule"],
        ),
        (
            fixture["management"]["update"]["receipt"],
            fixture["management"]["update"]["request"]["body"]["schedule"],
        ),
        (
            fixture["management"]["resume"]["receipt"],
            fixture["schedule"]["recurring"],
        ),
    )

    for receipt, schedule in checks:
        assert schedule["kind"] == "recurring"
        assert schedule["frequency"] == "weekly"
        assert schedule["days_of_week"] == [1, 3, 5]
        assert schedule["timezone"] == "Europe/Berlin"
        actual = _utc_timestamp(receipt["next_run_at"])
        assert actual == _next_weekly_utc(
            _utc_timestamp(receipt["issued_at"]), schedule
        )
        local = actual.astimezone(ZoneInfo(schedule["timezone"]))
        assert local.isoweekday() in schedule["days_of_week"]
        assert local.strftime("%H:%M:%S") == schedule["local_time"]


def test_routines_v1_approval_result_order_is_strict_and_terminal_is_monotonic():
    fixture = _fixture()
    approval = fixture["approval"]
    requested = approval["requested"]
    decision = approval["decision"]
    approval_receipt = approval["receipt"]
    result_event = fixture["result"]["event"]
    result_receipt = fixture["result"]["receipt"]

    timeline = (
        _utc_timestamp(requested["issued_at"]),
        _utc_timestamp(decision["decided_at"]),
        _utc_timestamp(approval_receipt["issued_at"]),
        _utc_timestamp(result_event["issued_at"]),
        _utc_timestamp(result_receipt["issued_at"]),
    )
    assert all(earlier < later for earlier, later in pairwise(timeline))

    for field in ("run_id", "attempt_id", "generation"):
        assert requested[field] == decision[field] == result_event[field]
    dispatch_command = fixture["dispatch"]["command"]
    assert result_event["routine_revision"] == dispatch_command["routine_revision"]
    assert result_event["title_snapshot"] == dispatch_command["title_snapshot"]
    assert requested["execution_id"] == result_event["execution_id"]
    assert requested["approval_request_id"] == decision["approval_request_id"]
    assert requested["action_attempt_id"] == decision["action_attempt_id"]
    assert requested["event_sequence"] < result_event["event_sequence"]
    assert result_receipt["event_id"] == result_event["event_id"]
    assert result_receipt["event_sequence"] == result_event["event_sequence"]
    assert approval_receipt["command_id"] == decision["command_id"]
    assert approval_receipt["idempotency_key"] == decision["idempotency_key"]
    assert approval_receipt["run_status"] == "working"

    lifecycle = fixture["lifecycle"]
    terminal_states = set(lifecycle["terminal_run_states"])
    assert lifecycle["terminal_is_monotonic"] is True
    assert not any(
        transition["from"] in terminal_states for transition in lifecycle["transitions"]
    )


def test_routines_v1_message_examples_have_complete_directional_envelopes():
    fixture = _fixture()
    scope = fixture["common"]["scope"]
    ignored = set(fixture["canonicalization"]["fingerprint_ignored_fields"])
    prefix = fixture["canonicalization"]["fingerprint_prefix"]
    fingerprint_pattern = re.compile(r"^canonical-json-sha256:v1:[0-9a-f]{64}$")
    cloud_commands = {
        "routine.manage",
        "routine.dispatch",
        "routine.approval_decision",
        "routine.cancel_wait",
    }
    foundry_events = {"routine.result", "routine.approval_requested"}
    responses = {
        "routine.management_receipt",
        "routine.detail",
        "routine.page",
        "routine.dispatch_receipt",
        "routine.event_receipt",
        "routine.approval_receipt",
    }
    required_metadata = {
        "schema_version",
        "kind",
        "producer",
        "service_identity",
        "scope",
        "issued_at",
        "deadline_at",
        "fingerprint",
    }
    dispatch_command = fixture["dispatch"]["command"]
    allowed_occurrence_dispositions = fixture["lifecycle"]["occurrence_dispositions"]
    assert "occurrence_disposition" in dispatch_command
    assert dispatch_command["occurrence_disposition"] == "admitted"
    assert dispatch_command["occurrence_disposition"] in allowed_occurrence_dispositions

    for path in MESSAGE_PATHS:
        message = _at_path(fixture, path)
        assert required_metadata <= set(message)
        assert message["schema_version"] == "v1"
        assert message["scope"] == scope
        assert message["issued_at"]
        assert message["deadline_at"]
        assert message["issued_at"] < message["deadline_at"]
        assert message["producer"] in {"cloud", "foundry"}
        assert (
            message["service_identity"]
            == {
                "cloud": "cloud-service",
                "foundry": "foundry-service",
            }[message["producer"]]
        )
        assert fingerprint_pattern.fullmatch(message["fingerprint"])
        projection = {
            key: value for key, value in message.items() if key not in ignored
        }
        digest = hashlib.sha256(canonical_json_bytes(projection)).hexdigest()
        assert message["fingerprint"] == prefix + digest
        if message["kind"] in cloud_commands:
            assert message["producer"] == "cloud"
            assert {"command_id", "idempotency_key"} <= set(message)
            UUID(message["command_id"])
            UUID(message["idempotency_key"])
        elif message["kind"] in foundry_events:
            assert message["producer"] == "foundry"
            assert {"event_id", "event_sequence"} <= set(message)
            UUID(message["event_id"])
            assert isinstance(message["event_sequence"], int)
            assert message["event_sequence"] > 0
        elif message["kind"] in responses:
            assert {"command_id", "idempotency_key"} <= set(message) or {
                "event_id",
                "event_sequence",
            } <= set(message)
            if "command_id" in message:
                UUID(message["command_id"])
                UUID(message["idempotency_key"])
            else:
                UUID(message["event_id"])
                assert isinstance(message["event_sequence"], int)
                assert message["event_sequence"] > 0
        else:
            raise AssertionError(f"unclassified fixture message: {message['kind']}")


def test_routines_v1_canonical_fingerprint_vectors_are_reproducible():
    fixture = _fixture()
    prefix = fixture["canonicalization"]["fingerprint_prefix"]
    ignored = set(fixture["canonicalization"]["fingerprint_ignored_fields"])
    assert ignored == {"deadline_at", "fingerprint", "issued_at"}

    for vector in fixture["canonical_fingerprint_vectors"]:
        encoded = canonical_json_bytes(vector["projection"])
        digest = hashlib.sha256(encoded).hexdigest()
        assert encoded.decode("utf-8") == vector["canonical_json"]
        assert vector["sha256"] == digest
        assert vector["fingerprint"] == prefix + digest
