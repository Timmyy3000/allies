"""Build-time smoke for routine-only typed-result tool exposure."""

from __future__ import annotations

import json

from gateway.platforms.api_server import (
    _ALLIES_ROUTINE_RESULT_SYSTEM_PROMPT,
    _ALLIES_ROUTINE_RESULT_TOOLSET,
    _allies_routine_enabled_toolsets,
)
from hermes_cli.plugins import discover_plugins
from hermes_cli.tools_config import _get_platform_tools
from model_tools import get_tool_definitions
from tools.registry import registry
from toolsets import TOOLSETS, create_custom_toolset, resolve_toolset


def main() -> None:
    discover_plugins(force=True)
    entry = registry.get_entry("allies_routine_result")
    assert entry is not None
    assert entry.toolset == _ALLIES_ROUTINE_RESULT_TOOLSET

    ordinary_toolsets = _allies_routine_enabled_toolsets(
        _get_platform_tools({}, "api_server"), routine_result=False
    )
    routine_toolsets = _allies_routine_enabled_toolsets(
        ordinary_toolsets, routine_result=True
    )
    ordinary_tools = {
        name
        for toolset in ordinary_toolsets
        for name in resolve_toolset(toolset)
    }
    assert "allies_routine_result" not in ordinary_tools

    composite_name = "_allies_routine_result_smoke_composite"
    create_custom_toolset(
        composite_name,
        "Build-time composite containing the private routine tool.",
        includes=[_ALLIES_ROUTINE_RESULT_TOOLSET],
    )
    try:
        composite_definitions = get_tool_definitions(
            enabled_toolsets=[composite_name],
            disabled_toolsets=[_ALLIES_ROUTINE_RESULT_TOOLSET],
            quiet_mode=True,
        )
        assert "allies_routine_result" not in {
            definition["function"]["name"] for definition in composite_definitions
        }
    finally:
        TOOLSETS.pop(composite_name, None)

    for wildcard in ("all", "*"):
        wildcard_ordinary = _allies_routine_enabled_toolsets(
            [wildcard], routine_result=False
        )
        wildcard_ordinary_tools = {
            name
            for toolset in wildcard_ordinary
            for name in resolve_toolset(toolset)
        }
        assert "allies_routine_result" not in wildcard_ordinary_tools
        wildcard_routine = _allies_routine_enabled_toolsets(
            [wildcard], routine_result=True
        )
        wildcard_routine_tools = {
            name
            for toolset in wildcard_routine
            for name in resolve_toolset(toolset)
        }
        assert "allies_routine_result" in wildcard_routine_tools

    routine_tools = {
        name
        for toolset in routine_toolsets
        for name in resolve_toolset(toolset)
    }
    assert _ALLIES_ROUTINE_RESULT_TOOLSET not in ordinary_toolsets
    assert _ALLIES_ROUTINE_RESULT_TOOLSET in routine_toolsets
    assert "allies_routine_result" in routine_tools
    assert json.loads(
        entry.handler(
            {
                "outcome": "unchanged",
                "text": "No change.",
                "references": [],
            }
        )
    ) == {"status": "accepted"}
    assert json.loads(
        entry.handler({"outcome": "changed", "text": "bad", "references": [{}]})
    )["status"] == "rejected"

    assert _ALLIES_ROUTINE_RESULT_SYSTEM_PROMPT
    print("routine result tool exposure: PASS")


if __name__ == "__main__":
    main()
