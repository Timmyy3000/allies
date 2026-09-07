from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from django.db import connection, connections, transaction

from runtime.exceptions import (
    ActivityWaitSaturated,
    ActivityWaitUnavailable,
    RuntimeFencedError,
)
from runtime.models import Workspace
from runtime.services import activity
from runtime.services.runtime_auth import RuntimeContext

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def workspace(settings):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL LISTEN/NOTIFY required")
    settings.ALLIES_RUNTIME_ACTIVITY_WAIT_ENABLED = True
    return Workspace.objects.create(
        tenant_ref=str(uuid4()),
        machine_generation=1,
        fly_app_ref="test-app",
        machine_ref="test-machine",
        volume_ref="test-volume",
    )


def context(workspace):
    return RuntimeContext(workspace.id, 1, uuid4())


def wait(workspace, seconds=1):
    try:
        return activity.wait_for_workspace_activity(context(workspace), 0, seconds)
    finally:
        connections.close_all()


def test_commit_before_subscribe_is_not_lost(workspace):
    activity.advance_workspace_activity(workspace)
    result = wait(workspace)
    assert (result.revision, result.reason) == (1, "changed")
    assert activity._active_waiters == 0


def test_subscribe_before_commit_observes_only_committed_change(workspace, monkeypatch):
    subscribed = Event()
    original = activity._read_revision

    def read(*args):
        revision = original(*args)
        subscribed.set()
        return revision

    monkeypatch.setattr(activity, "_read_revision", read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(wait, workspace, 2)
        assert subscribed.wait(1)
        with transaction.atomic():
            activity.advance_workspace_activity(workspace)
            assert not result.done()
        receipt = result.result(timeout=3)
    assert (receipt.revision, receipt.reason) == (1, "changed")
    assert activity._active_waiters == 0


def test_rollback_and_other_workspace_do_not_wake(workspace):
    other = Workspace.objects.create(
        tenant_ref=str(uuid4()),
        machine_generation=1,
        fly_app_ref="test-app",
        machine_ref="test-machine",
        volume_ref="test-volume",
    )
    with transaction.atomic():
        activity.advance_workspace_activity(workspace)
        transaction.set_rollback(True)
    activity.advance_workspace_activity(other)
    receipt = wait(workspace, 0.05)
    assert (receipt.revision, receipt.reason) == (0, "timeout")


def test_generation_change_fences_wait_and_releases_capacity(workspace, monkeypatch):
    subscribed = Event()
    original = activity._read_revision

    def read(*args):
        revision = original(*args)
        subscribed.set()
        return revision

    monkeypatch.setattr(activity, "_read_revision", read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(wait, workspace, 0.2)
        assert subscribed.wait(1)
        Workspace.objects.filter(pk=workspace.id).update(machine_generation=2)
        with pytest.raises(RuntimeFencedError):
            result.result(timeout=2)
    assert activity._active_waiters == 0
    assert not activity._workspace_waits


def test_wait_capacity_preserves_ordinary_database_work(
    workspace, monkeypatch, settings
):
    settings.ALLIES_RUNTIME_ACTIVITY_WAIT_MAX_WAITERS = 1
    subscribed = Event()
    original = activity._read_revision

    def read(*args):
        revision = original(*args)
        subscribed.set()
        return revision

    monkeypatch.setattr(activity, "_read_revision", read)
    other = Workspace.objects.create(
        tenant_ref=str(uuid4()),
        machine_generation=1,
        fly_app_ref="test-app",
        machine_ref="test-machine",
        volume_ref="test-volume",
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(wait, workspace, 2)
        assert subscribed.wait(1)
        with pytest.raises(ActivityWaitSaturated):
            wait(other, 0.05)
        assert Workspace.objects.filter(pk=other.id).exists()
        activity.advance_workspace_activity(workspace)
        assert result.result(timeout=3).reason == "changed"
    assert activity._active_waiters == 0


def test_feature_off_does_not_reserve_capacity(workspace, settings):
    settings.ALLIES_RUNTIME_ACTIVITY_WAIT_ENABLED = False
    with pytest.raises(ActivityWaitUnavailable):
        wait(workspace, 0.05)
    assert activity._active_waiters == 0
