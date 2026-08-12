import logging

from auths.services.cleanup import CleanupResult
from auths.tasks import cleanup_auth_artifacts_task


def test_cleanup_task_returns_safe_counts_and_logs_partial_failure(monkeypatch, caplog):
    monkeypatch.setattr(
        "auths.tasks.cleanup_auth_artifacts",
        lambda: CleanupResult(flows=1, refresh_tokens=2, avatars=3, failures=1),
    )

    with caplog.at_level(logging.WARNING, logger="auths.tasks"):
        result = cleanup_auth_artifacts_task.run()

    assert result == {
        "flows": 1,
        "refresh_tokens": 2,
        "avatars": 3,
        "failures": 1,
    }
    assert caplog.records[-1].cleanup_failures == 1


def test_cleanup_task_has_bounded_redelivery_contract():
    assert cleanup_auth_artifacts_task.max_retries == 1
    assert cleanup_auth_artifacts_task.acks_late is True
    assert cleanup_auth_artifacts_task.ignore_result is True
    assert cleanup_auth_artifacts_task.soft_time_limit == 270
    assert cleanup_auth_artifacts_task.time_limit == 300
