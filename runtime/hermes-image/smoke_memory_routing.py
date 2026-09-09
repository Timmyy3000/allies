"""Exercise initialized memory-tool routing across two isolated profiles."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agent.memory_manager import MemoryManager
from plugins.memory import load_memory_provider

PROFILE_CONFIG = """\
memory:
  provider: allies_mnemosyne
  mode: narrow_tools
  policy_version: allies-mnemosyne-v1
  profile_isolation: true
  tools: [{tools}]
  sync_roles: []
  mnemosyne:
    profile_isolation: true
    shared_surface_read: false
    storage: mnemosyne
"""


def _profile(root: Path, name: str, tools: tuple[str, ...]) -> tuple[MemoryManager, object, Path]:
    profile_root = root / "profiles" / name
    profile_root.mkdir(parents=True)
    (profile_root / "config.yaml").write_text(
        PROFILE_CONFIG.format(tools=", ".join(tools)), encoding="utf-8"
    )
    provider = load_memory_provider("allies_mnemosyne")
    assert provider is not None
    manager = MemoryManager()
    manager.add_provider(provider)
    assert manager.get_all_tool_names() == set()
    manager.initialize_all(
        f"{name}-session",
        hermes_home=str(profile_root),
        profile_root=str(profile_root),
        agent_identity=f"ally-{name}-profile",
        agent_context="conversation",
    )
    return manager, provider, profile_root


def _result(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    assert isinstance(parsed, dict)
    return parsed


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cld012-memory-routing-") as directory:
        root = Path(directory)
        alpha, alpha_provider, alpha_root = _profile(
            root, "alpha", ("mnemosyne_recall",)
        )
        beta, beta_provider, beta_root = _profile(
            root, "beta", ("mnemosyne_remember",)
        )
        try:
            assert alpha.get_all_tool_names() == {"mnemosyne_recall"}
            assert beta.get_all_tool_names() == {"mnemosyne_remember"}
            assert alpha.has_tool("mnemosyne_recall")
            assert not alpha.has_tool("mnemosyne_remember")
            assert beta.has_tool("mnemosyne_remember")
            assert not beta.has_tool("mnemosyne_recall")

            alpha_status = alpha_provider.status()
            beta_status = beta_provider.status()
            assert alpha_status["available"] is True
            assert beta_status["available"] is True
            assert alpha_status["shared_surface"] is False
            assert beta_status["shared_surface"] is False
            alpha_db_root = Path(str(alpha_status["profile_db_root"])).resolve()
            beta_db_root = Path(str(beta_status["profile_db_root"])).resolve()
            assert alpha_db_root.is_relative_to(alpha_root.resolve())
            assert beta_db_root.is_relative_to(beta_root.resolve())
            assert alpha_db_root != beta_db_root
            assert not (root / "config.yaml").exists()

            marker = "CLD012_PROFILE_B_ONLY"
            stored = _result(
                beta.handle_tool_call(
                    "mnemosyne_remember",
                    {"content": marker, "source": "preference"},
                )
            )
            assert stored.get("status") in {"ok", "stored"}, stored
            recalled = _result(
                alpha.handle_tool_call("mnemosyne_recall", {"query": marker})
            )
            assert not any(
                marker in json.dumps(item, sort_keys=True)
                for item in recalled.get("results", [])
            )
            print("two-profile memory routing: PASS")
        finally:
            alpha_provider.shutdown()
            beta_provider.shutdown()


if __name__ == "__main__":
    main()
