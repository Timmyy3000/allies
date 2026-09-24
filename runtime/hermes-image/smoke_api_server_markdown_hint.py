"""Prove the api_server platform hint declares Markdown support."""

from pathlib import Path

text = Path("/opt/hermes/agent/prompt_builder.py").read_text(encoding="utf-8")
assert "assume plain text" not in text, "stale plain-text api_server hint"
assert "renders Markdown" in text, "api_server hint must declare Markdown support"
