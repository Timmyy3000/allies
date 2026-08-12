from concurrent.futures import Future
from unittest.mock import AsyncMock, MagicMock, patch

import dj_database_url
import pytest
from django.conf import settings
from django.db import DatabaseError
from django.db.backends.postgresql.base import DatabaseWrapper
from django.test import override_settings

from config.health import healthz


class FakeAsyncCursor:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    async def execute(self, *args):
        self.calls.append(args)


class FakeAsyncDatabase:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def clear_health_cache():
    with (
        patch("config.health._health_cache_expires_at", 0.0),
        patch("config.health._health_cache_result", None),
        patch("config.health._health_probe_executor", None),
        patch("config.health._health_probe_in_flight", False),
    ):
        yield


@pytest.mark.django_db
def test_healthz_reports_ready_when_database_is_available(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_healthz_reports_unavailable_when_database_check_fails(client):
    with patch("config.health.connection.cursor", side_effect=DatabaseError):
        response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.django_db
def test_healthz_reuses_a_recent_probe_result(client):
    cursor = MagicMock()
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor

    with (
        patch("config.health.connection.cursor", return_value=cursor_context),
        patch("config.health.monotonic", side_effect=[0.0, 0.0, 0.0]),
    ):
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200

    select_calls = [
        item
        for item in cursor.execute.call_args_list
        if item.args and item.args[0] == "SELECT 1"
    ]
    assert len(select_calls) == 1


@pytest.mark.django_db
def test_healthz_bounds_postgres_probe_with_statement_timeout(client):
    future = Future()
    with (
        patch("config.health.connection.vendor", "postgresql"),
        patch("config.health._health_cache_result", ({"status": "unavailable"}, 503)),
        patch("config.health._health_probe_executor") as executor,
    ):
        executor.submit.return_value = future
        response = client.get("/healthz")

    assert response.status_code == 503
    future.set_result(None)
    assert client.get("/healthz").status_code == 200
    executor.submit.assert_called_once()


@pytest.mark.django_db
def test_healthz_returns_unavailable_when_postgres_probe_times_out(client):
    future = Future()
    with (
        patch("config.health.connection.vendor", "postgresql"),
        patch("config.health._health_cache_result", ({"status": "unavailable"}, 503)),
        patch("config.health._health_probe_executor") as executor,
    ):
        executor.submit.return_value = future
        response = client.get("/healthz")

    assert response.status_code == 503
    future.set_exception(TimeoutError)
    assert client.get("/healthz").status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.django_db
def test_healthz_runs_initial_postgres_probe_before_reply(client):
    with (
        patch("config.health.connection.vendor", "postgresql"),
        patch("config.health._run_postgres_probe_in_worker") as probe,
    ):
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    probe.assert_called_once_with()


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["healthcheck.railway.app", "example.test"],
    SECURE_SSL_REDIRECT=True,
)
def test_healthz_is_directly_probeable_over_railway_internal_http(client):
    healthcheck_headers = {
        "HTTP_HOST": "healthcheck.railway.app",
        "HTTP_USER_AGENT": "RailwayHealthCheck/1.0",
    }
    response = client.get("/healthz", **healthcheck_headers)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    port_bearing_host = client.get(
        "/healthz",
        HTTP_HOST="healthcheck.railway.app:8080",
        HTTP_USER_AGENT="RailwayHealthCheck/1.0",
    )
    assert port_bearing_host.status_code == 200
    assert port_bearing_host.json() == {"status": "ok"}

    trailing_slash = client.get("/healthz/", **healthcheck_headers)
    assert trailing_slash.status_code == 301
    assert trailing_slash["Location"] == "https://healthcheck.railway.app/healthz/"

    application_route = client.get("/api/v1/", **healthcheck_headers)
    assert application_route.status_code == 301
    assert application_route["Location"] == "https://healthcheck.railway.app/api/v1/"

    non_railway_host = client.get(
        "/healthz",
        HTTP_HOST="example.test",
        HTTP_USER_AGENT="RailwayHealthCheck/1.0",
    )
    assert non_railway_host.status_code == 301
    assert non_railway_host["Location"] == "https://example.test/healthz"

    spoofed_user_agent = client.get(
        "/healthz",
        HTTP_HOST="healthcheck.railway.app",
        HTTP_USER_AGENT="curl/8.0",
    )
    assert spoofed_user_agent.status_code == 301
    assert spoofed_user_agent["Location"] == "https://healthcheck.railway.app/healthz"


@pytest.mark.django_db
def test_healthz_fails_closed_when_initial_postgres_probe_fails(client):
    with (
        patch("config.health.connection.vendor", "postgresql"),
        patch(
            "config.health._run_postgres_probe_in_worker",
            side_effect=DatabaseError,
        ),
    ):
        response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.django_db
def test_healthz_serves_stale_result_while_probe_is_in_flight():
    with (
        patch("config.health._health_cache_result", ({"status": "ok"}, 200)),
        patch("config.health._health_probe_in_flight", True),
    ):
        response = healthz(None)

    assert response.status_code == 200
    assert response.content == b'{"status": "ok"}'


def test_postgres_probe_callback_resets_state_for_unexpected_errors():
    future = Future()
    future.set_exception(ValueError("synthetic worker failure"))

    from config import health

    with patch.object(health, "_health_probe_in_flight", True):
        with pytest.raises(ValueError, match="synthetic worker failure"):
            health._finish_postgres_probe(future)
        assert health._health_probe_in_flight is False


def test_run_postgres_probe_uses_bounded_async_connection():
    cursor = FakeAsyncCursor()
    database = FakeAsyncDatabase(cursor)

    with (
        patch(
            "config.health.connection.get_connection_params",
            return_value={"cursor_factory": object(), "dbname": "foundry"},
        ),
        patch(
            "config.health.AsyncConnection.connect",
            new=AsyncMock(return_value=database),
        ) as connect,
    ):
        from config.health import _run_postgres_probe

        _run_postgres_probe()

    connect.assert_awaited_once_with(dbname="foundry")
    assert cursor.calls == [
        (
            "SELECT set_config('statement_timeout', %s, true)",
            ["5000"],
        ),
        ("SELECT 1",),
    ]
    assert database.closed


def test_run_postgres_probe_accepts_real_django_postgres_params():
    database_settings = dj_database_url.parse(
        "postgres://ci:ci@127.0.0.1:5432/foundry",
        conn_max_age=60,
    )
    database_settings["TIME_ZONE"] = settings.TIME_ZONE
    database_settings["OPTIONS"] = {"connect_timeout": 5}
    database = DatabaseWrapper(database_settings, alias="probe")
    cursor = FakeAsyncCursor()
    fake_database = FakeAsyncDatabase(cursor)

    with patch(
        "config.health.AsyncConnection.connect",
        new=AsyncMock(return_value=fake_database),
    ) as connect:
        from config.health import _run_postgres_probe

        _run_postgres_probe(database)

    params = connect.await_args.kwargs
    assert params["dbname"] == "foundry"
    assert params["user"] == "ci"
    assert params["password"] == "ci"
    assert params["host"] == "127.0.0.1"
    assert params["port"] == 5432
    assert params["connect_timeout"] == 5
    assert "cursor_factory" not in params


def test_run_postgres_probe_reaches_real_psycopg_connect():
    database_settings = dj_database_url.parse(
        "postgres://ci:ci@127.0.0.1:65432/foundry",
        conn_max_age=60,
    )
    database_settings["TIME_ZONE"] = settings.TIME_ZONE
    database_settings["OPTIONS"] = {"connect_timeout": 1}
    database = DatabaseWrapper(database_settings, alias="probe")

    from psycopg import OperationalError

    from config.health import _run_postgres_probe

    with pytest.raises((OperationalError, OSError, TimeoutError)) as error:
        _run_postgres_probe(database)

    assert not isinstance(error.value, TypeError)
