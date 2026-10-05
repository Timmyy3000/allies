from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from allies_runtime.hermes import _routine_result_value

TOOL = runpy.run_path(
    str(
        Path(__file__).resolve().parents[1]
        / "hermes-image/plugins/routine-result/tools.py"
    )
)
SCHEMA = TOOL["ROUTINE_RESULT_SCHEMA"]["function"]["parameters"]


@pytest.mark.parametrize("character", ["a", "界", "😀"])
@pytest.mark.parametrize("field", ["text", "label", "url"])
def test_advertised_field_limit_fits_tool_and_runtime_byte_budgets(character, field):
    report = {"outcome": "unchanged", "text": "Checked.", "references": []}
    properties = SCHEMA["properties"]
    if field == "text":
        report["text"] = character * properties["text"]["maxLength"]
    else:
        reference_schema = properties["references"]["items"]["properties"]
        reference = {"label": "Source", "url": "https://example.test/"}
        prefix = "https://" if field == "url" else ""
        reference[field] = prefix + character * (
            reference_schema[field]["maxLength"] - len(prefix)
        )
        report["references"] = [reference]
    assert json.loads(TOOL["handle_routine_result"](report)) == {"status": "accepted"}
    normalized = _routine_result_value(report)
    assert normalized["outcome"] == "unchanged"
    assert normalized["result_text"] == report["text"]
