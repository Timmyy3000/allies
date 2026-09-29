"""Check activity naming and details in the patched api_server."""

from gateway.platforms.api_server import _allies_activity

CASES = [
    (
        "browser_navigate",
        {"url": "https://www.wg-gesucht.de/login"},
        ("browser_navigate", "wg-gesucht.de"),
    ),
    (
        "web_search",
        {"query": "rooms in" + chr(10) + "berlin"},
        ("web_search", "rooms in berlin"),
    ),
    (
        "allies_safe_inputs",
        {"action": "request_new", "website": "wg-gesucht.de"},
        ("safe_input_request", "wg-gesucht.de"),
    ),
    ("allies_gmail", {"action": "send", "body": "private"}, ("gmail_send", None)),
    ("allies_calendar", {"action": "list_events"}, ("calendar_read", None)),
    (
        "allies_calendar",
        {"action": "delete_event", "event_id": "e1"},
        ("calendar_write", None),
    ),
    ("terminal", {"command": "cat secrets"}, ("terminal", None)),
    ("allies_routines", {"action": "list"}, ("routine_list", None)),
    ("allies_ask_approval", {"action": "Buy it"}, ("approval_request", None)),
]


def main():
    for tool, args, expected in CASES:
        assert _allies_activity(tool, args) == expected, (tool, expected)
    name, subject = _allies_activity("web_search", {"query": "x" * 200})
    assert name == "web_search" and len(subject) == 80
    print("Hermes activity naming and details: PASS")


if __name__ == "__main__":
    main()
