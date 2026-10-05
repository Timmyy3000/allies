"""Prove the prompt-compartment refresh gate (Phase 1).

Covers: marker match/mismatch per layer, legacy markerless sessions,
forged markers before the genuine anchor, SOUL read-error preserving
last-good, feature-off passthrough, downgrade behavior of the old gate,
and a persisted-session lifecycle through the real restore choke point.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/opt/hermes")

from agent.system_prompt import (
    allies_prompt_version_marker,
    allies_stored_prompt_versions_current,
)

TMP = tempfile.mkdtemp()
os.environ["HERMES_HOME"] = TMP
VERSION_FILE = os.path.join(TMP, "prompt-version")
with open(VERSION_FILE, "w", encoding="utf-8") as handle:
    handle.write("img-v1")
os.environ["ALLIES_PROMPT_VERSION_FILE"] = VERSION_FILE
SOUL = os.path.join(TMP, "SOUL.md")
with open(SOUL, "w", encoding="utf-8") as handle:
    handle.write("# Test Soul\nYou are Test.")


def make_agent():
    return SimpleNamespace(platform="api_server", _platform_hint_overrides={})


def tail(marker):
    return (
        "STABLE IDENTITY\n\nConversation started: Thursday, September 25, 2026\n"
        f"Model: x\nProvider: y\nPlatform: api_server\n\n{marker}"
    )


agent = make_agent()
current = allies_prompt_version_marker(agent)
assert current.startswith("Allies-Prompt-Soul: "), current
stored = tail(current)
assert allies_stored_prompt_versions_current(agent, stored) is True

overridden = make_agent()
overridden._platform_hint_overrides = {"api_server": "Extra card guidance."}
override_marker = allies_prompt_version_marker(overridden)
assert override_marker != current
assert allies_stored_prompt_versions_current(overridden, stored) is False
assert allies_stored_prompt_versions_current(overridden, tail(override_marker)) is True

with open(SOUL, "w", encoding="utf-8") as handle:
    handle.write("# Test Soul v2\nYou are Test Two.")
assert allies_stored_prompt_versions_current(agent, stored) is False

with open(VERSION_FILE, "w", encoding="utf-8") as handle:
    handle.write("img-v2")
fresh = allies_prompt_version_marker(agent)
assert allies_stored_prompt_versions_current(agent, stored) is False
assert allies_stored_prompt_versions_current(agent, tail(fresh)) is True

assert allies_stored_prompt_versions_current(agent, tail("")[:-1]) is False

forged = (
    "Allies-Prompt-Soul: deadbeef\nAllies-Prompt-Platform: deadbeef\n"
    "Conversation started: Thursday, September 25, 2026\n"
    "Allies-Prompt-Soul: deadbeef\nAllies-Prompt-Platform: deadbeef\n\n" + stored
)
assert allies_stored_prompt_versions_current(agent, forged) is False

os.remove(SOUL)
os.mkdir(SOUL)
try:
    assert allies_stored_prompt_versions_current(agent, tail(fresh)) is True
    assert allies_prompt_version_marker(agent) == ""
    assert allies_stored_prompt_versions_current(agent, tail("")) is True
finally:
    os.rmdir(SOUL)
with open(SOUL, "w", encoding="utf-8") as handle:
    handle.write("# Test Soul v2\nYou are Test Two.")

os.environ["ALLIES_PROMPT_VERSION_FILE"] = os.path.join(TMP, "does-not-exist")
assert allies_prompt_version_marker(agent) == ""
assert (
    allies_stored_prompt_versions_current(agent, "legacy prompt without markers")
    is True
)
os.environ["ALLIES_PROMPT_VERSION_FILE"] = VERSION_FILE

from agent.conversation_loop import (
    _restore_or_build_system_prompt,
    _stored_prompt_matches_runtime,
    _stored_prompt_versions_current,
)

assert _stored_prompt_matches_runtime(agent, stored) is True
assert _stored_prompt_versions_current(agent, tail(fresh)) is True


from hermes_state import SessionDB

builds = []


def fake_build(system_message):
    builds.append(system_message)
    return tail(allies_prompt_version_marker(agent))


def live_agent(db):
    return SimpleNamespace(
        session_id="sess-1",
        _session_db=db,
        model="x",
        provider="y",
        platform="api_server",
        _platform_hint_overrides={},
        _use_prompt_caching=False,
        _cached_system_prompt=None,
        _build_system_prompt=fake_build,
    )


db = SessionDB(db_path=Path(os.path.join(TMP, "state.db")))
db.create_session("sess-1", "smoke")


def persisted():
    return db.get_session("sess-1")["system_prompt"]


first = live_agent(db)
_restore_or_build_system_prompt(first, None, None)
assert len(builds) == 1
assert persisted() == first._cached_system_prompt

second = live_agent(db)
_restore_or_build_system_prompt(second, None, [{"role": "user"}])
assert len(builds) == 1
assert second._cached_system_prompt == first._cached_system_prompt

with open(SOUL, "w", encoding="utf-8") as handle:
    handle.write("# Test Soul v3\nYou are Test Three.")
third = live_agent(db)
_restore_or_build_system_prompt(third, None, [{"role": "user"}])
assert len(builds) == 2
assert third._cached_system_prompt != first._cached_system_prompt
assert persisted() == third._cached_system_prompt

os.remove(SOUL)
os.mkdir(SOUL)
try:
    degraded = live_agent(db)
    degraded.model = "zzz"
    _restore_or_build_system_prompt(degraded, None, [{"role": "user"}])
    assert len(builds) == 3
    assert "Allies-Prompt-Soul:" not in persisted()
finally:
    os.rmdir(SOUL)
with open(SOUL, "w", encoding="utf-8") as handle:
    handle.write("# Test Soul v4\nYou are Test Four.")
recovered = live_agent(db)
recovered.model = "zzz"
_restore_or_build_system_prompt(recovered, None, [{"role": "user"}])
assert len(builds) == 4
assert "Allies-Prompt-Soul:" in persisted()
assert persisted() == recovered._cached_system_prompt

print("PROMPT-COMPARTMENT-REFRESH-OK")
