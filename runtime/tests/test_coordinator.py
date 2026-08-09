from __future__ import annotations

import pytest

from allies_runtime.coordinator import ProfileProofCoordinator
from allies_runtime.errors import IdentityIsolationError
from allies_runtime.fake import FakeHermesClient, FakeProfilePlan


@pytest.mark.asyncio
async def test_different_profiles_overlap_and_same_profile_waits():
    client = FakeHermesClient(
        {"a": FakeProfilePlan(delay=0.04), "b": FakeProfilePlan(delay=0.04)}
    )
    coordinator = ProfileProofCoordinator(client, slots=2)
    results = await coordinator.run_profiles(
        {"a": "one", "b": "two"}, sessions={"a": "sa", "b": "sb"}
    )
    assert len(results) == 2
    assert results[0].started_at < results[1].finished_at
    assert results[1].started_at < results[0].finished_at
    first, second = await coordinator.run_same_profile_pair("a", session_id="sa")
    assert first.waited_for_same_profile or second.waited_for_same_profile
    assert first.session_id == second.session_id == "sa"


@pytest.mark.asyncio
async def test_duplicate_replay_is_deduplicated():
    client = FakeHermesClient({"a": FakeProfilePlan(duplicate_event=True)})
    result = await ProfileProofCoordinator(client).run_turn("a", "hello")
    assert [event.sequence for event in result.events] == [1, 2, 3]


@pytest.mark.asyncio
async def test_crossed_profile_is_rejected():
    client = FakeHermesClient({"a": FakeProfilePlan(cross_profile="b")})
    with pytest.raises(IdentityIsolationError):
        await ProfileProofCoordinator(client).run_turn("a", "hello")
