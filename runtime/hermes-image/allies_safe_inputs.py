"""Safe inputs and approval tools; login values never reach this machine."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import NAMESPACE_URL, uuid4, uuid5

INSTRUCTION = (
    "Use logins the user saved in Allies without ever seeing them. "
    "list shows saved logins by name and website and whether you have access. "
    "If you need a login you do not have, call request_access with its id, or "
    "request_new with a name and website when none exists; the user answers in "
    "Allies and this call waits for them. Never ask the user to type a password "
    "in chat. To sign in, open the site's login form in the browser (accept any "
    "cookie banner, open the login pop-up), click the username or email field, "
    "then call fill with the safe_input_id and field=username; Allies types it "
    "and presses Enter. Logins that ask for the password on a later step: click "
    "the password field once it appears and call fill with field=password. You "
    "never see the values. no_field or ambiguous_field means click the right "
    "field first and retry. If fill returns domain_mismatch, you are on the "
    "wrong site: stop and tell the user."
)
SCHEMA = {
    "type": "function",
    "function": {
        "name": "allies_safe_inputs",
        "description": INSTRUCTION,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "request_new", "request_access", "status", "fill"],
                },
                "safe_input_id": {"type": "string", "maxLength": 36},
                "request_id": {"type": "string", "maxLength": 36},
                "name": {"type": "string", "maxLength": 80},
                "website": {"type": "string", "maxLength": 253},
                "field": {"type": "string", "enum": ["username", "password"]},
            },
        },
    },
}
APPROVAL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "allies_ask_approval",
        "description": (
            "Ask the user to approve an action before you take it, such as buying, "
            "sending, booking or deleting something in the browser. Describe exactly "
            "what you will do. Act only if the result is approved."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {"action": {"type": "string", "maxLength": 500}},
        },
    },
}
_MAX_BYTES = 64 * 1024
POLL_SECONDS = 5
WAIT_SECONDS = 240


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def relay(integration, args, call_key, current=None):
    """POST one tool call to Cloud through Foundry; returns a result dict."""
    if current is None:
        from tools.allies_routines import context

        current = context.get()
    if current is None:
        return {"error": integration + "_tool_unavailable"}
    token, origin = current
    raw = json.dumps(
        {
            "call_id": str(uuid5(NAMESPACE_URL, f"allies-{integration}:{call_key}")),
            "integration": integration,
            "arguments": args,
        }
    ).encode()
    request = Request(
        origin + "/api/v1/runtime/integrations/tool",
        data=raw,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    for _ in range(2):
        try:
            try:
                response = build_opener(NoRedirect).open(request, timeout=30)
            except HTTPError as exc:
                response = exc
            with response:
                status = response.status
                body = response.read(_MAX_BYTES + 1)
            result = json.loads(body[:_MAX_BYTES])
            if isinstance(result, dict) and status < 500:
                return result
        except (URLError, OSError, ValueError):
            pass
    return {"error": integration + "_service_unavailable"}


def handle_safe_inputs(args, **kwargs):
    from tools.approval import _approval_tool_call_id

    call_key = _approval_tool_call_id.get() or uuid4().hex
    result = relay("safe_inputs", args, call_key)
    if (
        args.get("action") in {"request_new", "request_access"}
        and result.get("status") == "pending"
    ):
        deadline = time.monotonic() + WAIT_SECONDS
        request_id = result.get("request_id")
        while (
            request_id
            and result.get("status") == "pending"
            and time.monotonic() < deadline
        ):
            time.sleep(POLL_SECONDS)
            polled = relay(
                "safe_inputs",
                {"action": "status", "request_id": request_id},
                uuid4().hex,
            )
            result = {**polled, "request_id": request_id}
        if result.get("status") == "pending":
            result["instruction"] = (
                "The user has not answered yet. Tell them the request is waiting in "
                "Allies, and check status later."
            )
    return json.dumps(result)


def handle_ask_approval(args, **kwargs):
    from tools.approval import request_tool_approval

    action = str(args.get("action") or "")[:500]
    decision = request_tool_approval(
        "allies_ask_approval",
        action,
        rule_key="allies_ask_approval:" + uuid4().hex,
        tool_args={"action": action},
    )
    return json.dumps(
        {"approved": bool(decision.get("approved")), "message": decision.get("message")}
    )
