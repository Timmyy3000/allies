import asyncio
import json
from types import SimpleNamespace

import allies_mnemosyne.provider as provider_module
import pytest
from allies_mnemosyne import ALLOWED_TOOLS, AlliesMnemosyneProvider


def schema(name, properties, required=()):
    return {
        "name": name,
        "description": "test schema",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(required),
        },
    }


class FakeDelegate:
    def __init__(self, result='{"status":"ok"}', error=None):
        self.result = result
        self.error = error
        self.calls = []

    def prefetch(self, query, *, session_id=""):
        if self.error:
            raise self.error
        self.calls.append(("prefetch", query, session_id))
        return "## context\nA durable preference"

    def handle_tool_call(self, name, args, **kwargs):
        if self.error:
            raise self.error
        self.calls.append((name, args))
        return self.result

    def shutdown(self):
        if self.error:
            raise self.error


def ready_provider(tmp_path, mode="narrow_tools", delegate=None):
    provider = AlliesMnemosyneProvider()
    provider._available = True
    provider._mode = mode
    provider._profile_key = "ally-1"
    provider._profile_root = tmp_path / "ally-1"
    provider._profile_root.mkdir()
    provider._db_path = (
        provider._profile_root
        / "mnemosyne"
        / "data"
        / "banks"
        / "ally-1"
        / "mnemosyne.db"
    )
    provider._db_path.parent.mkdir(parents=True)
    provider._delegate = delegate or FakeDelegate()
    provider._tools = ("mnemosyne_recall", "mnemosyne_remember")
    provider._schemas = {
        "mnemosyne_recall": schema(
            "mnemosyne_recall",
            {"query": {"type": "string"}},
            ("query",),
        ),
        "mnemosyne_remember": schema(
            "mnemosyne_remember",
            {
                "content": {"type": "string"},
                "source": {"type": "string"},
                "extract": {"type": "boolean"},
                "scope": {"type": "string", "enum": ["session", "global"]},
            },
            ("content",),
        ),
    }
    provider._reason = "ready"
    return provider


def test_context_only_advertises_no_tools_and_rejects_hidden_dispatch(tmp_path):
    delegate = FakeDelegate()
    provider = ready_provider(tmp_path, mode="context_only", delegate=delegate)

    assert provider.get_tool_schemas() == []
    assert provider.get_tool_names() == ()
    result = json.loads(
        provider.handle_tool_call("mnemosyne_recall", {"query": "name"})
    )
    assert result == {"reason": "tool_not_advertised", "status": "tool_rejected"}
    assert delegate.calls == []


def test_narrow_mode_validates_allowlist_and_arguments(tmp_path):
    delegate = FakeDelegate()
    provider = ready_provider(tmp_path, delegate=delegate)

    result = provider.handle_tool_call("mnemosyne_recall", {"query": "name"})
    assert json.loads(result) == {"status": "ok"}
    assert delegate.calls == [("mnemosyne_recall", {"query": "name"})]

    hidden = json.loads(provider.handle_tool_call("mnemosyne_sleep", {}))
    assert hidden["status"] == "tool_rejected"
    assert hidden["reason"] == "tool_not_advertised"

    cross_bank = json.loads(
        provider.handle_tool_call(
            "mnemosyne_recall", {"query": "name", "bank": "surface"}
        )
    )
    assert cross_bank["reason"] == "profile_override_forbidden"


def test_deeply_nested_arguments_fail_soft(tmp_path):
    provider = ready_provider(tmp_path)
    nested: list[object] = []
    for _ in range(5_000):
        nested = [nested]

    result = json.loads(
        provider.handle_tool_call("mnemosyne_recall", {"query": nested})
    )

    assert result["status"] == "tool_rejected"
    assert result["reason"] in {
        "arguments_not_serializable",
        "arguments_too_large",
    }


def test_retention_scan_handles_deeply_nested_metadata():
    nested: list[object] = []
    forbidden: object = "api_key=top-secret-value"
    for _ in range(5_000):
        nested = [nested]
        forbidden = [forbidden]

    assert provider_module._contains_forbidden(nested) is False
    assert provider_module._contains_forbidden(forbidden) is True


@pytest.mark.parametrize(
    "content",
    [
        "api_key=top-secret-value",
        "user: raw transcript text",
        "one-off calculation: 2 + 2",
        "completed artifact id 0123456789abcdef",
    ],
)
def test_explicit_write_retention_gate_rejects_forbidden_data(tmp_path, content):
    delegate = FakeDelegate()
    provider = ready_provider(tmp_path, delegate=delegate)

    result = json.loads(
        provider.handle_tool_call(
            "mnemosyne_remember", {"content": content, "source": "fact"}
        )
    )
    assert result["status"] == "tool_rejected"
    assert result["reason"] == "retention_policy_rejected"
    assert delegate.calls == []


def test_retention_gate_allows_durable_commitment_language(tmp_path):
    delegate = FakeDelegate()
    provider = ready_provider(tmp_path, delegate=delegate)

    result = json.loads(
        provider.handle_tool_call(
            "mnemosyne_remember",
            {
                "content": "The user is committed to a 10-minute daily walk",
                "source": "preference",
            },
        )
    )

    assert result["status"] == "ok"
    assert delegate.calls[-1][1]["scope"] == "global"


def test_write_disables_llm_extraction(tmp_path):
    provider = ready_provider(tmp_path)
    result = json.loads(
        provider.handle_tool_call(
            "mnemosyne_remember",
            {
                "content": "The user prefers tea",
                "source": "preference",
                "extract": True,
            },
        )
    )
    assert result["reason"] == "implicit_extraction_disabled"


def test_remember_forces_profile_durable_scope(tmp_path):
    delegate = FakeDelegate()
    provider = ready_provider(tmp_path, delegate=delegate)

    result = json.loads(
        provider.handle_tool_call(
            "mnemosyne_remember",
            {"content": "The user prefers tea", "source": "preference"},
        )
    )

    assert result["status"] == "ok"
    assert delegate.calls[-1][1]["scope"] == "global"
    rejected = json.loads(
        provider.handle_tool_call(
            "mnemosyne_remember",
            {
                "content": "The user prefers a short greeting",
                "source": "preference",
                "scope": "session",
            },
        )
    )
    assert rejected["reason"] == "non_durable_scope_rejected"


def test_prefetch_and_lifecycle_are_fail_soft_for_cancellation_and_faults(tmp_path):
    provider = ready_provider(
        tmp_path, delegate=FakeDelegate(error=asyncio.CancelledError())
    )

    assert provider.prefetch("meaningful query") == ""
    result = json.loads(
        provider.handle_tool_call("mnemosyne_recall", {"query": "name"})
    )
    assert result["status"] == "memory_unavailable"
    provider.on_session_end([{"role": "user", "content": "secret"}])
    provider.on_pre_compress([])
    provider.shutdown()
    assert provider.status()["available"] is False


def test_profile_paths_and_immutable_identity_are_checked(tmp_path):
    provider = AlliesMnemosyneProvider()
    root, memory_root, identity, error = provider._configuration(
        {
            "hermes_home": str(tmp_path / "ally-1"),
            "agent_identity": "ally-1",
            "agent_context": "primary",
            "memory_mode": "context_only",
        }
    )
    assert error is None
    assert root == (tmp_path / "ally-1").resolve()
    assert memory_root == (tmp_path / "ally-1" / "mnemosyne").resolve()
    assert identity == "ally-1"

    _, _, _, error = provider._configuration(
        {
            "hermes_home": str(tmp_path),
            "agent_identity": "../other",
            "agent_context": "primary",
        }
    )
    assert error == "profile_identity_invalid"


def test_initialize_shuts_down_delegate_after_invariant_failure(tmp_path, monkeypatch):
    class FakeConnection:
        def execute(self, _query):
            return None

    class InitializedDelegate:
        def __init__(self):
            self._beam = SimpleNamespace(
                db_path=tmp_path / "outside" / "ally-1" / "mnemosyne.db",
                conn=FakeConnection(),
            )
            self._surface_beam = None
            self.shutdown_called = False

        def initialize(self, _session_id, **_kwargs):
            return None

        def shutdown(self):
            self.shutdown_called = True

    delegate = InitializedDelegate()
    original_import = provider_module.importlib.import_module

    def import_module(name):
        if name == "mnemosyne_hermes":
            return SimpleNamespace(MnemosyneMemoryProvider=lambda: delegate)
        return original_import(name)

    monkeypatch.setattr(provider_module.importlib, "import_module", import_module)
    provider = AlliesMnemosyneProvider()
    profile = (tmp_path / "profile").resolve()

    provider.initialize(
        "session",
        hermes_home=str(profile),
        profile_root=str(profile),
        agent_identity="ally-1",
        agent_context="conversation",
    )

    assert provider.status()["available"] is False
    assert provider.status()["reason"] == "mnemosyne_database_outside_profile"
    assert delegate.shutdown_called is True


def test_safe_reason_does_not_expose_untrusted_exception_text():
    assert provider_module._safe_reason(RuntimeError("secret path")) == "runtime"


def test_profile_config_controls_mode_and_tools_without_hermes_core_changes(tmp_path):
    profile = tmp_path / "ally-1"
    profile.mkdir()
    (profile / "config.yaml").write_text(
        "memory:\n"
        "  provider: allies_mnemosyne\n"
        "  mode: narrow_tools\n"
        "  policy_version: allies-mnemosyne-v1\n"
        "  profile_isolation: true\n"
        "  tools: [mnemosyne_recall]\n",
        encoding="utf-8",
    )
    provider = AlliesMnemosyneProvider()
    _, _, _, error = provider._configuration(
        {
            "hermes_home": str(profile),
            "agent_identity": "ally-1",
            "agent_context": "primary",
        }
    )
    assert error is None
    assert provider._mode == "narrow_tools"
    assert provider._tools == ("mnemosyne_recall",)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("provider", "stock_mnemosyne", "memory_provider_invalid"),
        ("policy_version", "future-policy", "memory_policy_version_invalid"),
    ],
)
def test_profile_config_rejects_an_unreviewed_provider_or_policy(
    tmp_path, field, value, reason
):
    profile = tmp_path / "ally-1"
    profile.mkdir()
    (profile / "config.yaml").write_text(
        "memory:\n"
        f"  provider: {'allies_mnemosyne' if field != 'provider' else value}\n"
        f"  policy_version: "
        f"{'allies-mnemosyne-v1' if field != 'policy_version' else value}\n",
        encoding="utf-8",
    )
    provider = AlliesMnemosyneProvider()
    _, _, _, error = provider._configuration(
        {
            "hermes_home": str(profile),
            "agent_identity": "ally-1",
            "agent_context": "primary",
        }
    )
    assert error == reason


def test_schema_allowlist_is_explicit_and_sorted():
    assert tuple(sorted(ALLOWED_TOOLS)) == ALLOWED_TOOLS
    assert "mnemosyne_export" not in ALLOWED_TOOLS
    assert "mnemosyne_sync_push" not in ALLOWED_TOOLS
