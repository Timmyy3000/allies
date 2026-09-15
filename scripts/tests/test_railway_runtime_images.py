import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "railway_images",
    Path(__file__).parents[1] / "integrations/railway/update_runtime_images.py",
)
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)
PAIR = {key: f"ghcr.io/example/{key.lower()}@sha256:{'a' * 64}" for key in images.KEYS}
OLD = {key: value.replace("a" * 64, "b" * 64) for key, value in PAIR.items()}
PROJECT = "00000000-0000-0000-0000-000000000001"
ENVIRONMENT = "00000000-0000-0000-0000-000000000002"


class API:
    def __init__(self, current=None, *, lose_response=False, ignore_write=False):
        self.current = current if current is not None else {}
        self.lose_response = lose_response
        self.ignore_write = ignore_write
        self.writes = []

    def __call__(self, query, variables):
        if "project(id:" in query:
            return {
                "project": {
                    "environments": {
                        "edges": [{"node": {"id": ENVIRONMENT, "name": "staging"}}]
                    }
                }
            }
        if "variableCollectionUpsert" in query:
            self.writes.append(variables["input"])
            if not self.ignore_write:
                self.current = variables["input"]["variables"]
            if self.lose_response:
                raise images.PairUpdateError("response lost")
            return {"variableCollectionUpsert": True}
        return {"variables": {**self.current, "UNRELATED_SECRET": "not-for-output"}}


@pytest.mark.parametrize("initial", [{}, OLD, PAIR])
def test_pair_update_initialization_and_idempotent_readback(initial):
    api = API(initial)
    receipt = images.update_pair(PROJECT, "staging", PAIR, request=api)
    assert receipt["previous"] == (initial or None)
    assert receipt["readback"] == PAIR
    assert receipt["machine_adoption"] == "not_verified"
    assert "not-for-output" not in str(receipt)
    assert len(api.writes) == (0 if initial == PAIR else 1)
    for write in api.writes:
        assert write == {
            "projectId": PROJECT,
            "environmentId": ENVIRONMENT,
            "variables": PAIR,
            "replace": False,
        }


@pytest.mark.parametrize(
    "initial",
    [{"HERMES_IMAGE": PAIR["HERMES_IMAGE"]}, {**PAIR, "RUNTIME_IMAGE": "latest"}],
)
def test_invalid_existing_state_never_writes(initial):
    api = API(initial)
    with pytest.raises(images.PairUpdateError):
        images.update_pair(PROJECT, "staging", PAIR, request=api)
    assert api.writes == []


def test_lost_mutation_response_reconciles_without_repeating_write():
    api = API(OLD, lose_response=True)
    assert images.update_pair(PROJECT, "staging", PAIR, request=api)["readback"] == PAIR
    assert len(api.writes) == 1


def test_readback_mismatch_is_bounded_and_fails():
    api = API(OLD, ignore_write=True)
    delays = []
    with pytest.raises(images.PairUpdateError, match="not verified"):
        images.update_pair(PROJECT, "staging", PAIR, request=api, sleep=delays.append)
    assert len(api.writes) == 3
    assert delays == [1, 2]


@pytest.mark.parametrize(
    "result",
    [
        {"variables": None},
        {"project": {"environments": {"edges": []}}},
    ],
)
def test_failed_preread_and_ambiguous_environment_never_write(result):
    api = API(OLD)

    def request(query, variables):
        if ("variables(" in query) == ("variables" in result):
            return result
        return api(query, variables)

    with pytest.raises(images.PairUpdateError):
        images.update_pair(PROJECT, "staging", PAIR, request=request)
    assert api.writes == []


@pytest.mark.parametrize(
    "status,raw",
    [
        (401, b"private error"),
        (200, b'{"errors":[{"message":"private error"}]}'),
        (200, b"not JSON"),
        (200, b"[]"),
        (200, b"x" * 1_048_577),
    ],
    ids=["http", "graphql", "malformed", "shape", "oversized"],
)
def test_api_errors_are_bounded_closed_and_sanitized(monkeypatch, status, raw):
    connection = Mock()
    connection.getresponse.return_value.status = status
    connection.getresponse.return_value.read.return_value = raw
    factory = Mock(return_value=connection)
    monkeypatch.setattr(images.http.client, "HTTPSConnection", factory)
    monkeypatch.setenv("RAILWAY_API_TOKEN", "synthetic-token")
    with pytest.raises(images.PairUpdateError) as failure:
        images.graphql("query", {})
    assert "private error" not in str(failure.value)
    factory.assert_called_once_with("backboard.railway.com", timeout=10)
    connection.sock.settimeout.assert_called_once_with(30)
    connection.getresponse.return_value.read.assert_called_once_with(1_048_577)
    connection.close.assert_called_once()
