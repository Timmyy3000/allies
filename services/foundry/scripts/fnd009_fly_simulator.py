"""State-owning, test-only Fly Machines HTTP simulator for the FND-009 proof.

The simulator intentionally implements only the provider calls used by the
runtime power loop.  It also starts a tiny deterministic runtime worker when
the fake Machine is started, so the proof exercises the production Foundry
claim/readiness/event APIs rather than a test-only shortcut.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from fnd009_common import (
    APP_NAME,
    FLY_TOKEN,
    MACHINE_ID,
    MACHINE_NAME,
    PROOF_TOKEN,
    PROVISIONING_ID,
    RUNTIME_TOKEN,
    VOLUME_ID,
    WORKSPACE_ID,
    stable_id,
)

HOST = os.environ.get("FND009_SIMULATOR_HOST", "0.0.0.0")
PORT = int(os.environ.get("FND009_SIMULATOR_PORT", "8765"))
FOUNDRY_URL = os.environ.get("FND009_FOUNDRY_URL", "http://foundry:8000").rstrip("/")
RESPONSE_TEXT = os.environ.get("FND009_RESPONSE_TEXT", "FND-009 proof response")
POLL_SECONDS = 0.25


class SimulatorState:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.machine_state = "stopped"
        self.starts = 0
        self.stops = 0
        self.readiness = 0
        self.claims = 0
        self.completed = 0
        self.errors = 0
        self.hold_next = False
        self.held_attempt: str | None = None
        self.last_attempt: str | None = None
        self.last_conversation: str | None = None
        self.worker: threading.Thread | None = None

    def machine(self) -> dict[str, Any]:
        return {
            "id": MACHINE_ID,
            "name": MACHINE_NAME,
            "region": "local",
            "state": self.machine_state,
            "config": {"mounts": [{"volume": VOLUME_ID}]},
            "metadata": {
                "allies_owner": "foundry",
                "allies_workspace_id": str(WORKSPACE_ID),
                "allies_operation_id": str(PROVISIONING_ID),
                "allies_machine_generation": "1",
            },
        }

    def snapshot(self) -> dict[str, Any]:
        with self.condition:
            return {
                "machine_state": self.machine_state,
                "starts": self.starts,
                "stops": self.stops,
                "readiness": self.readiness,
                "claims": self.claims,
                "completed": self.completed,
                "errors": self.errors,
                "held": self.held_attempt is not None,
                "hold_next": self.hold_next,
                "last_attempt": self.last_attempt,
                "last_conversation": self.last_conversation,
            }

    def start(self) -> dict[str, str]:
        with self.condition:
            previous = self.machine_state
            if previous == "started":
                return {"previous_state": previous, "new_state": previous}
            self.machine_state = "started"
            self.starts += 1
            start_number = self.starts
            worker = threading.Thread(
                target=_runtime_worker,
                args=(start_number,),
                name=f"fnd009-runtime-{start_number}",
                daemon=True,
            )
            self.worker = worker
            worker.start()
            return {"previous_state": previous, "new_state": self.machine_state}

    def stop(self) -> dict[str, str]:
        with self.condition:
            previous = self.machine_state
            self.machine_state = "stopped"
            if previous == "started":
                self.stops += 1
            self.condition.notify_all()
            return {"previous_state": previous, "new_state": self.machine_state}


STATE = SimulatorState()


def _json_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    attempts: int = 1,
) -> tuple[int, dict[str, Any] | None]:
    encoded = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        FOUNDRY_URL + path,
        data=encoded,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {RUNTIME_TOKEN}",
            **({"Content-Type": "application/json"} if encoded else {}),
        },
    )
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=3) as response:
                body = response.read(256 * 1024)
                return int(response.status), _decode_json(body)
        except HTTPError as error:
            try:
                body = error.read(256 * 1024)
            finally:
                error.close()
            if error.code in {409, 425, 429} or error.code >= 500:
                if attempt + 1 < attempts:
                    time.sleep(POLL_SECONDS)
                    continue
            return int(error.code), _decode_json(body)
        except (OSError, URLError, TimeoutError):
            if attempt + 1 < attempts:
                time.sleep(POLL_SECONDS)
                continue
            return 599, None
    return 599, None


def _decode_json(body: bytes) -> dict[str, Any] | None:
    if not body:
        return None
    try:
        value = json.loads(body)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _wait_for_foundry() -> bool:
    for _ in range(120):
        status, _ = _json_request("GET", "/api/v1/runtime/profiles/reconciliation")
        if status == 200:
            return True
        time.sleep(POLL_SECONDS)
    with STATE.condition:
        STATE.errors += 1
    return False


def _runtime_worker(start_number: int) -> None:
    if not _wait_for_foundry():
        return
    status, reconciliation = _json_request(
        "GET", "/api/v1/runtime/profiles/reconciliation", attempts=3
    )
    if status != 200 or not reconciliation:
        with STATE.condition:
            STATE.errors += 1
        return
    generation = reconciliation.get("machine_generation")
    start_epoch = reconciliation.get("runtime_start_epoch")
    if not isinstance(generation, int) or not isinstance(start_epoch, int):
        with STATE.condition:
            STATE.errors += 1
        return
    boot_id = stable_id(f"fnd009-boot-{start_number}")
    status, _ = _json_request(
        "POST",
        "/api/v1/runtime/readiness",
        payload={
            "boot_id": str(boot_id),
            "reconciled_generation": generation,
            "runtime_start_epoch": start_epoch,
        },
        attempts=5,
    )
    if status != 200:
        with STATE.condition:
            STATE.errors += 1
        return
    with STATE.condition:
        STATE.readiness += 1

    claim_number = 0
    while True:
        with STATE.condition:
            if STATE.machine_state != "started":
                return
        claim_number += 1
        claim_id = stable_id(f"fnd009-claim-{start_number}-{claim_number}")
        status, claim = _json_request(
            "POST",
            "/api/v1/runtime/claims",
            payload={"claim_id": str(claim_id), "available_slots": 1},
            attempts=2,
        )
        if status == 204:
            time.sleep(POLL_SECONDS)
            continue
        if status in {409, 425, 429, 500, 502, 503, 599}:
            time.sleep(POLL_SECONDS)
            continue
        if status != 200 or not claim:
            with STATE.condition:
                STATE.errors += 1
            time.sleep(POLL_SECONDS)
            continue
        if not _complete_claim(claim):
            return


def _complete_claim(claim: dict[str, Any]) -> bool:
    attempt_id = claim.get("attempt_id")
    lease_token = claim.get("lease_token")
    stream_id = claim.get("stream_id")
    conversation_id = claim.get("conversation_id")
    if not all(isinstance(item, str) and item for item in (attempt_id, lease_token, stream_id)):
        with STATE.condition:
            STATE.errors += 1
        return False
    with STATE.condition:
        STATE.claims += 1
        STATE.last_attempt = attempt_id
        STATE.last_conversation = conversation_id if isinstance(conversation_id, str) else None
        if STATE.hold_next:
            STATE.hold_next = False
            STATE.held_attempt = attempt_id
            STATE.condition.notify_all()
        while STATE.held_attempt == attempt_id and STATE.machine_state == "started":
            STATE.condition.wait(timeout=0.5)
        if STATE.machine_state != "started":
            return False
    headers_path = f"/api/v1/runtime/attempts/{attempt_id}"
    event_headers = {"X-Foundry-Lease-Token": lease_token}
    dispatch_status, _ = _json_request_with_headers(
        "POST",
        f"{headers_path}/events",
        payload={
            "event_id": str(stable_id(f"fnd009-dispatched-{attempt_id}")),
            "stream_id": stream_id,
            "sequence": 1,
            "type": "execution.dispatched",
            "payload": {"status": "dispatched"},
        },
        headers=event_headers,
    )
    if dispatch_status != 202:
        with STATE.condition:
            STATE.errors += 1
        return False
    bind_status, _ = _json_request_with_headers(
        "PUT",
        f"{headers_path}/session-binding",
        payload={
            "cloud_conversation_ref": conversation_id,
            "expected_session_id": claim.get("session_id"),
            "effective_session_id": f"fnd009-session-{claim.get('profile_id', 'unknown')}",
        },
        headers=event_headers,
    )
    if bind_status != 200:
        with STATE.condition:
            STATE.errors += 1
        return False
    delta_status, _ = _json_request_with_headers(
        "POST",
        f"{headers_path}/events",
        payload={
            "event_id": str(stable_id(f"fnd009-delta-{attempt_id}")),
            "stream_id": stream_id,
            "sequence": 2,
            "type": "message.delta",
            "payload": {"text": RESPONSE_TEXT},
        },
        headers=event_headers,
    )
    if delta_status != 202:
        with STATE.condition:
            STATE.errors += 1
        return False
    complete_status, _ = _json_request_with_headers(
        "POST",
        f"{headers_path}/complete",
        payload={
            "event_id": str(stable_id(f"fnd009-completed-{attempt_id}")),
            "stream_id": stream_id,
            "sequence": 3,
            "payload": {"run_id": f"fnd009-run-{attempt_id}", "status": "completed"},
            "receipt": {"code": "completed"},
        },
        headers=event_headers,
    )
    if complete_status != 200:
        with STATE.condition:
            STATE.errors += 1
        return False
    with STATE.condition:
        STATE.completed += 1
    return True


def _json_request_with_headers(
    method: str,
    path: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> tuple[int, dict[str, Any] | None]:
    encoded = json.dumps(payload).encode("utf-8")
    request = Request(
        FOUNDRY_URL + path,
        data=encoded,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {RUNTIME_TOKEN}",
            **headers,
        },
    )
    try:
        with urlopen(request, timeout=3) as response:
            return int(response.status), _decode_json(response.read(256 * 1024))
    except HTTPError as error:
        try:
            body = error.read(256 * 1024)
        finally:
            error.close()
        return int(error.code), _decode_json(body)
    except (OSError, URLError, TimeoutError):
        return 599, None


class SimulatorHandler(BaseHTTPRequestHandler):
    server_version = "fnd009-fly-simulator/1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _write(self, status: int, payload: dict[str, Any] | None = None) -> None:
        body = b"" if payload is None else json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _authorized(self, *, proof: bool = False) -> bool:
        expected = PROOF_TOKEN if proof else FLY_TOKEN
        return self.headers.get("Authorization", "") == f"Bearer {expected}"

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length) or b"{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._write(200, {"status": "ok"})
            return
        if self.path == "/snapshot":
            if not self._authorized(proof=True):
                self._write(401, {"code": "unauthorized"})
                return
            self._write(200, STATE.snapshot())
            return
        if not self._authorized():
            self._write(401, {"code": "unauthorized"})
            return
        machine_prefix = f"/v1/apps/{APP_NAME}/machines"
        if self.path == machine_prefix:
            self._write(200, [STATE.machine()])
            return
        if self.path == f"{machine_prefix}/{MACHINE_ID}":
            self._write(200, STATE.machine())
            return
        self._write(404, {"code": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/control/hold-next":
            if not self._authorized(proof=True):
                self._write(401, {"code": "unauthorized"})
                return
            with STATE.condition:
                STATE.hold_next = True
            self._write(200, {"status": "hold_next"})
            return
        if self.path == "/control/release":
            if not self._authorized(proof=True):
                self._write(401, {"code": "unauthorized"})
                return
            with STATE.condition:
                STATE.held_attempt = None
                STATE.condition.notify_all()
            self._write(200, {"status": "released"})
            return
        if not self._authorized():
            self._write(401, {"code": "unauthorized"})
            return
        machine_prefix = f"/v1/apps/{APP_NAME}/machines/{MACHINE_ID}"
        if self.path == f"{machine_prefix}/start":
            self._write(200, STATE.start())
            return
        if self.path == f"{machine_prefix}/stop":
            self._write(200, STATE.stop())
            return
        self._write(404, {"code": "not_found"})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), SimulatorHandler)
    server.daemon_threads = True
    print("fnd009 fly simulator ready", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
