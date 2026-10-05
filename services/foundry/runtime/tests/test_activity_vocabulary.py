import pytest

from allies_runtime.hermes import _normalize_activity_kind

# Tools the Allies Hermes image exposes (hermes-api-server toolset at the pinned
# source SHA, plus Allies plugins as renamed by patches/activity-detail.patch).
EXPOSED_TOOLS = [
    "web_search", "web_extract", "terminal", "process", "read_file", "write_file",
    "patch", "search_files", "vision_analyze", "image_generate",
    "bfl_flux3_text_to_video", "bfl_flux3_image_to_video",
    "bfl_flux3_keyframes_to_video", "bfl_flux3_video_continuation",
    "bfl_flux3_get_result", "bfl_flux3_prompting_guide",
    "skills_list", "skill_view", "skill_manage",
    "browser_navigate", "browser_snapshot", "browser_click", "browser_type",
    "browser_scroll", "browser_back", "browser_press", "browser_get_images",
    "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
    "todo", "memory", "session_search", "execute_code", "delegate_task",
    "cronjob", "ha_list_entities", "ha_get_state", "ha_list_services",
    "ha_call_service", "tool_search", "tool_describe",
    "memory_remember", "memory_recall", "publish_files", "routine_result",
    "routine_create", "routine_list", "gmail_read", "gmail_send",
    "gmail_organise", "calendar_read", "calendar_write", "safe_input_check",
    "safe_input_request", "safe_input_fill", "approval_request",
]  # fmt: skip


@pytest.mark.parametrize("tool", EXPOSED_TOOLS)
def test_every_exposed_tool_has_a_named_activity(tool):
    assert _normalize_activity_kind(tool) != "unknown"
