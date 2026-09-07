from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

from django.core.management import call_command


def test_managed_readiness_publisher_recovers_and_uses_default_cadence(monkeypatch):
    from runtime.management.commands import publish_profile_readiness_hints as command

    publish = Mock(
        side_effect=[
            RuntimeError("unavailable"),
            SimpleNamespace(delivered=1, deferred=0, exhausted=0),
        ]
    )
    sleeps = []
    monkeypatch.setattr(command, "publish_due_profile_readiness_hints", publish)
    monkeypatch.setattr(command, "sleep", sleeps.append)
    errors = StringIO()
    call_command(
        "publish_profile_readiness_hints",
        "--watch",
        "--max-runs",
        "2",
        stdout=StringIO(),
        stderr=errors,
    )
    assert publish.call_count == 2
    assert all(call.kwargs == {"limit": 1} for call in publish.call_args_list)
    assert sleeps == [1]
    assert "RuntimeError" in errors.getvalue()
    assert "unavailable" not in errors.getvalue()
