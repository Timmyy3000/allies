"""Prove the Allies platform prompt layer.

Covers: the image ships PLATFORM.md, the platform layer follows the soul,
it replaces Hermes' own docs pointer, it is absent when the file is absent,
and editing it changes the platform version marker so live sessions rebuild.
"""

from __future__ import annotations

import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, "/opt/hermes")

from agent.prompt_builder import HERMES_AGENT_HELP_GUIDANCE
from agent.system_prompt import (
    allies_platform_prompt,
    allies_prompt_version_marker,
    build_system_prompt_parts,
)

shipped = allies_platform_prompt()
assert shipped.startswith("# How you work"), shipped[:80]

TMP = tempfile.mkdtemp()
os.environ["HERMES_HOME"] = TMP
with open(os.path.join(TMP, "SOUL.md"), "w", encoding="utf-8") as handle:
    handle.write("# Mira\n\nYou are **Mira**, an Ally in Allies.")
VERSION_FILE = os.path.join(TMP, "prompt-version")
with open(VERSION_FILE, "w", encoding="utf-8") as handle:
    handle.write("img-v1")
os.environ["ALLIES_PROMPT_VERSION_FILE"] = VERSION_FILE
PLATFORM = os.path.join(TMP, "PLATFORM.md")
with open(PLATFORM, "w", encoding="utf-8") as handle:
    handle.write("# How you work\n\nPlatform rule one.")
os.environ["ALLIES_PLATFORM_PROMPT_FILE"] = PLATFORM


class Agent(SimpleNamespace):
    def __getattr__(self, name):
        return None


def make_agent():
    return Agent(
        platform="api_server",
        load_soul_identity=True,
        skip_context_files=True,
        valid_tool_names=set(),
        model="x",
        provider="y",
        _platform_hint_overrides={},
    )


stable = build_system_prompt_parts(make_agent())["stable"]
assert stable.index("You are **Mira**") < stable.index("Platform rule one.")
assert HERMES_AGENT_HELP_GUIDANCE not in stable

before = allies_prompt_version_marker(make_agent())
with open(PLATFORM, "w", encoding="utf-8") as handle:
    handle.write("# How you work\n\nPlatform rule two.")
after = allies_prompt_version_marker(make_agent())
assert before.splitlines()[0] == after.splitlines()[0]
assert before.splitlines()[1] != after.splitlines()[1]

os.environ["ALLIES_PLATFORM_PROMPT_FILE"] = os.path.join(TMP, "does-not-exist")
stable = build_system_prompt_parts(make_agent())["stable"]
assert "Platform rule" not in stable
assert HERMES_AGENT_HELP_GUIDANCE in stable

print("PLATFORM-LAYER-OK")
