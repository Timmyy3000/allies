import importlib.util
import json
import re
import sys
from contextvars import ContextVar
from io import BytesIO
from pathlib import Path
from types import ModuleType
from urllib.error import URLError

import pytest

HERMES_IMAGE = Path(__file__).parents[1] / "hermes-image"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERMES_IMAGE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


routines = _load("routine_tool_for_gmail", "allies_routines.py")
_load("allies_profile_sandbox", "allies_profile_sandbox.py")
gmail = _load("gmail_tool", "allies_gmail.py")
PUBLICATION = "00000000-0000-4000-8000-000000000001"
FILE_ID = "11111111-2222-4333-8444-555555555555"
PDF = b"%PDF-1.4 certificate"


@pytest.fixture
def turn(monkeypatch):
    tools = ModuleType("tools")
    approval = ModuleType("tools.approval")
    approval._approval_tool_call_id = ContextVar("tool_call_id", default="call1")
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setitem(sys.modules, "tools.approval", approval)
    monkeypatch.setitem(sys.modules, "tools.allies_routines", routines)
    token = routines.context.set(
        routines.turn_context("capability", "https://foundry.example.test")
    )
    yield
    routines.context.reset(token)


def _opener(monkeypatch, responses):
    requests = []

    class Response(BytesIO):
        pass

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            outcome = responses.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            status, body, *headers = outcome
            response = Response(body)
            response.status = status
            response.headers = (
                headers[0] if headers else {"Content-Length": str(len(body))}
            )
            return response

    monkeypatch.setattr(gmail, "build_opener", lambda *a: Opener())
    return requests


def test_posts_opaque_integration_call_to_foundry(turn, monkeypatch):
    requests = _opener(monkeypatch, [(200, b'{"messages":[]}')])
    result = gmail.handle_gmail({"action": "search", "query": "from:a"})
    assert json.loads(result) == {"messages": []}
    request = requests[0]
    assert request.full_url == (
        "https://foundry.example.test/api/v1/runtime/integrations/tool"
    )
    assert request.headers["Authorization"] == "Bearer capability"
    body = json.loads(request.data)
    assert body["integration"] == "gmail"
    assert body["arguments"] == {"action": "search", "query": "from:a"}


def test_retry_keeps_call_identity(turn, monkeypatch):
    requests = _opener(monkeypatch, [URLError("lost"), (200, b'{"status":"sent"}')])
    assert json.loads(gmail.handle_gmail({"action": "send"})) == {"status": "sent"}
    first, second = (json.loads(r.data)["call_id"] for r in requests)
    assert first == second


def test_client_errors_are_returned_not_retried(turn, monkeypatch):
    requests = _opener(monkeypatch, [(403, b'{"error":"integration_unavailable"}')])
    result = json.loads(gmail.handle_gmail({"action": "get", "message_id": "m"}))
    assert result == {"error": "integration_unavailable"}
    assert len(requests) == 1


def test_repeated_failure_never_claims_success(turn, monkeypatch):
    _opener(monkeypatch, [(502, b"{}"), URLError("down")])
    result = json.loads(gmail.handle_gmail({"action": "send"}))
    assert result["error"] == "gmail_service_unavailable"
    assert "Do not claim" in result["instruction"]


def test_unavailable_without_turn_context(monkeypatch):
    approval = ModuleType("tools.approval")
    approval._approval_tool_call_id = ContextVar("tool_call_id", default="call1")
    monkeypatch.setitem(sys.modules, "tools", ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.approval", approval)
    monkeypatch.setitem(sys.modules, "tools.allies_routines", routines)
    monkeypatch.setattr(
        gmail, "build_opener", lambda *a: pytest.fail("no context must not call out")
    )
    assert "unavailable" in gmail.handle_gmail({"action": "search"})


@pytest.mark.parametrize("state", ["validating", "ready", "rejected"])
@pytest.mark.parametrize("action", ["download_attachment", "attachment_status"])
def test_attachment_results_pass_through_without_promoting_state(
    turn, monkeypatch, state, action
):
    publication_id = "00000000-0000-4000-8000-000000000001"
    args = (
        {"action": action, "message_id": "m", "part_id": ""}
        if action == "download_attachment"
        else {"action": action, "publication_id": publication_id}
    )
    result = {
        "publication_id": publication_id,
        "state": state,
        "filename": "document.pdf",
    }
    if state == "ready":
        result["chat_reference"] = (
            "[document.pdf](/files/00000000-0000-4000-8000-000000000002)"
        )
    requests = _opener(monkeypatch, [(200, json.dumps(result).encode())])
    assert json.loads(gmail.handle_gmail(args)) == result
    assert json.loads(requests[0].data)["arguments"] == args
    assert len(requests) == 1


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys.modules["allies_profile_sandbox"],
        "child_workspace_path",
        lambda: str(tmp_path),
    )
    return tmp_path


def _ready(name="certificate.pdf"):
    return json.dumps(
        {
            "publication_id": PUBLICATION,
            "state": "ready",
            "files": [
                {
                    "filename": name,
                    "file_id": FILE_ID,
                    "chat_reference": f"[{name}](/files/{FILE_ID})",
                }
            ],
        }
    ).encode()


def _save():
    return json.loads(
        gmail.handle_gmail({"action": "save_attachment", "publication_id": PUBLICATION})
    )


def _saved_files(workspace):
    root = workspace / "email-attachments"
    return (
        sorted(path for path in root.rglob("*") if path.is_file())
        if root.exists()
        else []
    )


def test_save_attachment_writes_ready_file_into_workspace(turn, monkeypatch, workspace):
    requests = _opener(
        monkeypatch,
        [(200, _ready()), (200, PDF, {"Content-Length": str(len(PDF))})],
    )
    result = _save()
    target = workspace / "email-attachments" / FILE_ID / "certificate.pdf"
    assert target.read_bytes() == PDF
    assert result["state"] == "ready"
    assert result["files"] == [
        {
            "filename": "certificate.pdf",
            "path": str(target),
            "chat_reference": f"[certificate.pdf](/files/{FILE_ID})",
        }
    ]
    assert json.loads(requests[0].data)["arguments"] == {
        "action": "attachment_status",
        "publication_id": PUBLICATION,
    }
    file_request = requests[1]
    assert file_request.full_url == (
        f"https://foundry.example.test/api/v1/runtime/integrations/files/{FILE_ID}/content"
    )
    assert file_request.headers["Authorization"] == "Bearer capability"


def test_save_attachment_returns_pending_state_without_downloading(
    turn, monkeypatch, workspace
):
    pending = {"publication_id": PUBLICATION, "state": "validating"}
    requests = _opener(monkeypatch, [(200, json.dumps(pending).encode())])
    assert _save() == pending
    assert len(requests) == 1
    assert not (workspace / "email-attachments").exists()


@pytest.mark.parametrize(
    "name,expected", [("../../escape.pdf", "escape.pdf"), ("..\\up.pdf", "up.pdf")]
)
def test_save_attachment_keeps_files_inside_their_directory(
    turn, monkeypatch, workspace, name, expected
):
    _opener(
        monkeypatch,
        [(200, _ready(name)), (200, PDF, {"Content-Length": str(len(PDF))})],
    )
    result = _save()
    directory = workspace / "email-attachments" / FILE_ID
    assert result["files"][0]["path"] == str(directory / expected)
    assert (directory / expected).read_bytes() == PDF


def test_save_attachment_rejects_a_name_that_is_only_a_dot_segment(
    turn, monkeypatch, workspace
):
    requests = _opener(monkeypatch, [(200, _ready("..")), (200, PDF)])
    assert _save()["error"] == "gmail_attachment_save_failed"
    assert len(requests) == 1
    assert _saved_files(workspace) == []


@pytest.mark.parametrize(
    "declared,body",
    [
        ("25000001", PDF),
        (str(len(PDF) + 5), PDF),
        ("not-a-length", PDF),
    ],
)
def test_save_attachment_fails_closed_on_bad_length(
    turn, monkeypatch, workspace, declared, body
):
    _opener(monkeypatch, [(200, _ready()), (200, body, {"Content-Length": declared})])
    assert _save()["error"] == "gmail_attachment_save_failed"
    assert _saved_files(workspace) == []


def test_save_attachment_reports_cloud_denial_without_a_file(
    turn, monkeypatch, workspace
):
    _opener(
        monkeypatch,
        [(200, _ready()), (404, b'{"error":"integration_file_unavailable"}')],
    )
    assert _save()["error"] == "gmail_attachment_save_failed"
    assert _saved_files(workspace) == []


def test_save_attachment_without_a_workspace_makes_no_request(turn, monkeypatch):
    sandbox = sys.modules["allies_profile_sandbox"]

    def unavailable():
        raise sandbox.ProfileSandboxUnavailable("child_workspace_unavailable")

    monkeypatch.setattr(sandbox, "child_workspace_path", unavailable)
    monkeypatch.setattr(
        gmail, "build_opener", lambda *a: pytest.fail("no workspace, no request")
    )
    assert _save()["error"] == "gmail_attachment_workspace_unavailable"


def test_tool_loads_and_refuses_to_save_outside_the_sandbox(turn, monkeypatch):
    monkeypatch.setitem(sys.modules, "allies_profile_sandbox", None)
    module = _load("gmail_outside_sandbox", "allies_gmail.py")
    monkeypatch.setattr(
        module, "build_opener", lambda *a: pytest.fail("no workspace, no request")
    )
    result = json.loads(
        module.handle_gmail(
            {"action": "save_attachment", "publication_id": PUBLICATION}
        )
    )
    assert result["error"] == "gmail_attachment_workspace_unavailable"


def test_attachment_tool_schema_and_guidance_contract():
    function = gmail.SCHEMA["function"]
    properties = function["parameters"]["properties"]
    assert {"download_attachment", "attachment_status", "save_attachment"} <= set(
        properties["action"]["enum"]
    )
    assert properties["part_id"]["type"] == "string"
    assert properties["part_id"]["maxLength"] == 128
    assert properties["part_id"].get("minLength", 0) == 0
    publication = properties["publication_id"]
    assert publication["type"] == "string"
    assert publication["format"] == "uuid"
    assert re.fullmatch(publication["pattern"], "00000000-0000-4000-8000-000000000001")
    assert not re.fullmatch(publication["pattern"], "00000000000040008000000000000001")
    assert not re.fullmatch(
        publication["pattern"], "AAAAAAAA-0000-4000-8000-000000000001"
    )
    guidance = function["description"]
    for rule in (
        "get exposes attachment metadata and part_id",
        "one attachment at a time",
        "Cloud waits up to 20 seconds per call",
        "at most five status checks per turn",
        "chat_reference exactly in your final answer",
        "Never claim an attachment was downloaded or returned before ready",
        "preserve publication_id in the receipt",
        "retrieval succeeded and inspection is pending",
        "do not say Gmail cannot retrieve attachments",
    ):
        assert rule in guidance
