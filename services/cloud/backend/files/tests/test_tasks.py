from __future__ import annotations

import socket
import socketserver
import time
from contextlib import nullcontext
from threading import Event, Thread
from uuid import uuid4

import pytest
import redis.connection as redis_connection

from files import tasks


def test_enqueue_file_inspection_uses_bounded_non_retrying_producer(monkeypatch):
    seen = {}

    def connection_for_write(**kwargs):
        seen["connection"] = kwargs
        return nullcontext("connection")

    def producer(connection):
        seen["producer_connection"] = connection
        return nullcontext("producer")

    def apply_async(**kwargs):
        seen["publish"] = kwargs

    monkeypatch.setattr(tasks.current_app, "connection_for_write", connection_for_write)
    monkeypatch.setattr(tasks, "Producer", producer)
    monkeypatch.setattr(tasks.inspect_file_task, "apply_async", apply_async)
    file_id = uuid4()

    tasks.enqueue_file_inspection(file_id, countdown=5)

    assert seen["connection"]["connect_timeout"] == 1
    assert seen["connection"]["transport_options"] == {
        "socket_connect_timeout": 1,
        "socket_timeout": 1,
        "retry_on_timeout": False,
    }
    assert seen["producer_connection"] == "connection"
    assert seen["publish"] == {
        "args": (str(file_id),),
        "countdown": 5,
        "producer": "producer",
        "retry": False,
    }


def test_enqueue_file_inspection_absorbs_broker_failure(monkeypatch):
    def unavailable(**_kwargs):
        raise ConnectionError("private broker details")

    monkeypatch.setattr(tasks.current_app, "connection_for_write", unavailable)

    tasks.enqueue_file_inspection(uuid4())


def test_enqueue_file_inspection_bounds_refused_redis_connection(monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"redis://127.0.0.1:{port}/1"
    monkeypatch.setattr(tasks.current_app.conf, "broker_url", url)
    monkeypatch.setattr(tasks.current_app.conf, "broker_write_url", url)

    started = time.monotonic()
    tasks.enqueue_file_inspection(uuid4())

    assert time.monotonic() - started < 3


def test_enqueue_file_inspection_bounds_nonresponsive_redis_peer(monkeypatch):
    connected = Event()
    peer_closed = Event()
    release = Event()

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            connected.set()
            release.wait(timeout=5)
            self.request.settimeout(2)
            try:
                while self.request.recv(4_096):
                    pass
            except OSError:
                return
            peer_closed.set()

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        url = f"redis://127.0.0.1:{server.server_address[1]}/1"
        monkeypatch.setattr(tasks.current_app.conf, "broker_url", url)
        monkeypatch.setattr(tasks.current_app.conf, "broker_write_url", url)
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()
        started = time.monotonic()
        tasks.enqueue_file_inspection(uuid4())
        elapsed = time.monotonic() - started
        release.set()
        thread.join(timeout=2)

    assert connected.is_set()
    assert peer_closed.is_set()
    assert elapsed < 3


def test_enqueue_file_inspection_applies_connect_timeout_and_closes_socket(
    monkeypatch,
):
    sockets = []

    class TimeoutSocket:
        def __init__(self, *_args):
            self.timeout = None
            self.closed = False
            sockets.append(self)

        def setsockopt(self, *_args):
            return None

        def settimeout(self, value):
            self.timeout = value

        def connect(self, _address):
            assert self.timeout == 1
            raise TimeoutError("controlled connect timeout")

        def shutdown(self, _how):
            return None

        def close(self):
            self.closed = True

    monkeypatch.setattr(redis_connection.socket, "socket", TimeoutSocket)
    url = "redis://127.0.0.1:6379/1"
    monkeypatch.setattr(tasks.current_app.conf, "broker_url", url)
    monkeypatch.setattr(tasks.current_app.conf, "broker_write_url", url)

    started = time.monotonic()
    tasks.enqueue_file_inspection(uuid4())

    assert time.monotonic() - started < 3
    assert sockets
    assert all(item.closed for item in sockets)


@pytest.mark.parametrize(
    "value",
    [
        "not-a-uuid",
        "550e8400e29b41d4a716446655440000",
        "{550e8400-e29b-41d4-a716-446655440000}",
        "urn:uuid:550e8400-e29b-41d4-a716-446655440000",
        "550E8400-E29B-41D4-A716-446655440000",
        123,
    ],
)
def test_inspect_file_task_rejects_noncanonical_uuid_before_service(monkeypatch, value):
    monkeypatch.setattr(
        tasks, "inspect_file", lambda **_kwargs: pytest.fail("service was called")
    )

    with pytest.raises((TypeError, ValueError)):
        tasks.inspect_file_task.run(value)
