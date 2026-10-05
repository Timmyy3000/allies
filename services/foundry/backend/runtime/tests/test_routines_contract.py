import hashlib
import json
import re
from pathlib import Path
from uuid import UUID

import pytest

from runtime.contracts import canonical_json_bytes
from runtime.exceptions import RuntimeValidationError
from runtime.routine_contracts import parse_routine_message, routine_fingerprint

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


MESSAGE_PATHS = tuple(
    ("management", operation, "request")
    for operation in ("create", "update", "pause", "resume", "delete", "get", "list")
) + tuple(
    ("management", operation, "receipt")
    for operation in ("create", "update", "pause", "resume", "delete")
) + (
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


def _at_path(value: dict, path: tuple[str, ...]) -> dict:
    for key in path:
        value = value[key]
    return value


def test_routines_v1_artifacts_match_cloud_owned_lock():
    fixture = _fixture()
    lock = _load_json(LOCK_PATH)

    assert lock == {
        "contract_name": "routines",
        "schema_version": "v1",
        "content_revision": 14,
        "normative_owner": "cloud",
        "content_sha256": "f05ab0a1baf63551f426c288f0144484c813b5cda535bf1cf5d614fb7a22ea84",
        "fixture_sha256": "2660d30ee73e8f3cebf94340ea1169019e3c937fd01a30bff6d0e16ecd54ab35",
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
    assert _sha256(DOCUMENT_PATH) == lock["content_sha256"]
    assert _sha256(FIXTURE_PATH) == lock["fixture_sha256"]

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
        assert len({"expected_result_code", "expected_constraint_outcome"} & set(case)) == 1
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
    assert manual_reconciliation["expected_result_code"] == "ACTION_MANUAL_RECONCILIATION"
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
        "APPROVAL_EXPIRED",
        "ACTION_OUTCOME_UNKNOWN",
        "ACTION_MANUAL_RECONCILIATION",
        "RESULT_INSERTED_ONCE",
    } <= {error["code"] for error in fixture["errors"]}
    assert fixture["management_success_codes"] == [
        "MANAGEMENT_SAVED",
        "ROUTINE_RESUMED",
    ]


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
    assert fixture["management"]["pause"]["receipt"]["schedule_generation"] == 3
    assert fixture["management"]["create"]["receipt"]["schedule_generation"] == 1
    assert fixture["management"]["update"]["receipt"]["schedule_generation"] == 2
    assert fixture["management"]["resume"]["receipt"]["schedule_generation"] == 4
    assert fixture["schedule"]["resume"]["schedule_generation"] == 4
    assert fixture["dispatch"]["command"]["schedule_generation"] == 4
    assert fixture["dispatch"]["command"]["schedule"] == update_schedule
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

    stale = next(case for case in fixture["cases"] if case["case_id"] == "revision-stale")
    assert stale["expected_result_code"] == "REVISION_CONFLICT"
    assert "expected revision old; current revision newer" in stale["preconditions"]
    assert "zero-write" in stale["expected_postcondition"]
    assert "no saved management receipt" in stale["expected_postcondition"]

    race_cases = {case["case_id"]: case for case in fixture["race_cases"]}
    assert race_cases["race-delete-due"]["expected_result_code"] == "ROUTINE_DELETED"
    assert race_cases["race-pause-due"]["expected_result_code"] == "ROUTINE_PAUSED"
    assert race_cases["race-update-due"]["expected_result_code"] == "STALE_DUE_CANDIDATE"
    assert race_cases["race-resume-due"]["expected_result_code"] == "STALE_DUE_CANDIDATE"
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
    assert fixture["management"]["get"]["request"]["issued_at"] > deleted_receipt["issued_at"]
    assert fixture["management"]["list"]["request"]["issued_at"] > deleted_receipt["issued_at"]


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

    for path in MESSAGE_PATHS:
        message = _at_path(fixture, path)
        assert required_metadata <= set(message)
        assert message["schema_version"] == "v1"
        assert message["scope"] == scope
        assert message["issued_at"]
        assert message["deadline_at"]
        assert message["issued_at"] < message["deadline_at"]
        assert message["producer"] in {"cloud", "foundry"}
        assert message["service_identity"] == {
            "cloud": "cloud-service",
            "foundry": "foundry-service",
        }[message["producer"]]
        assert fingerprint_pattern.fullmatch(message["fingerprint"])
        projection = {key: value for key, value in message.items() if key not in ignored}
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
            assert (
                {"command_id", "idempotency_key"} <= set(message)
                or {"event_id", "event_sequence"} <= set(message)
            )
            if "command_id" in message:
                UUID(message["command_id"])
                UUID(message["idempotency_key"])
            else:
                UUID(message["event_id"])
                assert isinstance(message["event_sequence"], int)
                assert message["event_sequence"] > 0
        else:
            raise AssertionError(f"unclassified fixture message: {message['kind']}")

    dispatch = fixture["dispatch"]["command"]
    result = fixture["result"]["event"]
    assert result["routine_revision"] == dispatch["routine_revision"]
    assert result["title_snapshot"] == dispatch["title_snapshot"]
    assert dispatch["schedule"]["timezone"] == "Europe/Berlin"
    assert all(
        message["service_identity"] == "foundry-service"
        for section in ("result", "approval")
        for message in fixture[section].values()
        if isinstance(message, dict) and message.get("producer") == "foundry"
    )


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


def test_unknown_fields_and_kinds_fail_closed():
    message = dict(_fixture()["dispatch"]["command"])
    message["unexpected"] = True
    with pytest.raises(RuntimeValidationError):
        parse_routine_message(message)

    message = dict(_fixture()["dispatch"]["command"])
    message["kind"] = "execution.command"
    with pytest.raises(RuntimeValidationError):
        parse_routine_message(message)


def test_routine_result_composed_envelope_stays_within_transport_budget():
    message = dict(_fixture()["result"]["event"])
    message["text"] = "a" * (16 * 1024)
    url = "https://example.test/" + "u" * (2048 - len("https://example.test/"))
    message["references"] = [
        {"label": "l" * 255, "url": url}
        for _ in range(32)
    ]
    message["fingerprint"] = routine_fingerprint(message)

    with pytest.raises(RuntimeValidationError):
        parse_routine_message(message)


def test_routine_prompt_and_event_envelope_bounds_are_utf8_bytes():
    message = dict(_fixture()["dispatch"]["command"])
    message["execution_prompt"] = "é" * (16 * 1024)
    message["fingerprint"] = routine_fingerprint(message)
    with pytest.raises(RuntimeValidationError):
        parse_routine_message(message)
