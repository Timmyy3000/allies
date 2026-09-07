import logging

from allies.services.provisioning import DispatchReport
from allies.tasks import dispatch_due_provisioning_task


def test_provisioning_task_schedules_each_reported_follow_up(monkeypatch):
    report = DispatchReport(
        claimed=3,
        deferred=3,
        follow_up_delays=(2, 4, 8),
    )
    monkeypatch.setattr("allies.tasks.dispatch_due_provisioning", lambda limit: report)
    scheduled = []
    monkeypatch.setattr(
        dispatch_due_provisioning_task,
        "apply_async",
        lambda **kwargs: scheduled.append(kwargs),
    )

    result = dispatch_due_provisioning_task.run(limit=7)

    assert result == report.as_dict()
    assert scheduled == [
        {"kwargs": {"limit": 7}, "countdown": 2},
        {"kwargs": {"limit": 7}, "countdown": 4},
        {"kwargs": {"limit": 7}, "countdown": 8},
    ]


def test_provisioning_task_keeps_counts_when_follow_up_publish_fails(
    monkeypatch, caplog
):
    report = DispatchReport(
        claimed=3,
        deferred=3,
        follow_up_delays=(2, 4, 8),
    )
    monkeypatch.setattr("allies.tasks.dispatch_due_provisioning", lambda limit: report)
    attempts = []

    def fail_publish(**kwargs):
        attempts.append(kwargs)
        raise RuntimeError("broker details must not be logged")

    monkeypatch.setattr(dispatch_due_provisioning_task, "apply_async", fail_publish)
    with caplog.at_level(logging.WARNING, logger="allies.tasks"):
        result = dispatch_due_provisioning_task.run(limit=7)

    assert result == report.as_dict()
    assert [item["countdown"] for item in attempts] == [2, 4, 8]
    records = [record for record in caplog.records if record.name == "allies.tasks"]
    assert len(records) == 3
    assert {record.outcome for record in records} == {"broker_unavailable"}
    assert "broker details" not in caplog.text
