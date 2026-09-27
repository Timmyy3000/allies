"""Safe inputs: logins the user saves for Allies, which Allies never see.

Allies see only name and website. Values are sealed with the Cloud vault
and unsealed only here, at fill time, to be typed into the Ally's browser
over CDP after Cloud itself checks the page's domain.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from allies.models import Ally
from common.vault import seal_secret, unseal_secret

from ..exceptions import IntegrationInvalid
from ..models import SafeInput, SafeInputGrant, SafeInputRequest
from . import browser
from .turns import resolve_tool_turn

logger = logging.getLogger(__name__)

REQUEST_TTL = timedelta(minutes=10)
MAX_FIELD = 512

_FILL = """function (website, username, password) {
  const host = location.hostname.toLowerCase();
  if (location.protocol !== "https:" || !(host === website || host.endsWith("." + website)))
    return "domain_mismatch:" + host;
  const inputs = [...document.querySelectorAll("input")].filter(
    (i) => i.offsetParent !== null && !i.disabled && i.type !== "hidden");
  const pass = inputs.find((i) => i.type === "password");
  const user = inputs.find((i) => i.autocomplete === "username" || i.type === "email")
    || inputs.find((i) => i.type !== "password" && /user|email|login/i.test(i.name + " " + i.id));
  if (!pass && !user) return "no_login_form";
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  for (const [el, value] of [[user, username], [pass, password]]) {
    if (!el) continue;
    el.focus();
    setter.call(el, value);
    el.dispatchEvent(new Event("input", {bubbles: true}));
    el.dispatchEvent(new Event("change", {bubbles: true}));
  }
  const form = (pass || user).form;
  if (form && form.requestSubmit) form.requestSubmit();
  else (form || document).querySelector("button[type=submit],input[type=submit]")?.click();
  return "filled";
}"""

# Types one value into the input the Ally focused (or the only fitting one). The Ally drives the page
# (pop-ups, multi-step logins); Cloud only decides that a password goes into
# a password input and nothing goes to a foreign domain.
_FILL_FOCUSED = """function (website, field, value) {
  const host = location.hostname.toLowerCase();
  if (location.protocol !== "https:" || !(host === website || host.endsWith("." + website)))
    return "domain_mismatch:" + host;
  const fits = (i) => i instanceof HTMLInputElement && !i.disabled && !i.readOnly
    && (field === "password" ? i.type === "password" : ["text", "email", "tel"].includes(i.type));
  let el = document.activeElement;
  while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
  if (!fits(el)) {
    // Nothing suitable focused: use the one visible field that fits, if unambiguous.
    const named = (i) => field === "password" || i.type === "email"
      || /user|mail|login/i.test(i.name + " " + i.id + " " + i.autocomplete);
    const found = [...document.querySelectorAll("input")].filter(
      (i) => fits(i) && i.offsetParent !== null && named(i));
    if (found.length !== 1) return found.length ? "ambiguous_field" : "no_field";
    el = found[0];
    el.focus();
  }
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  setter.call(el, value);
  el.dispatchEvent(new Event("input", {bubbles: true}));
  el.dispatchEvent(new Event("change", {bubbles: true}));
  return "filled";
}"""

_CLEAR = """function (username, password) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  for (const el of document.querySelectorAll("input"))
    if (el.value && (el.value === username || el.value === password)) setter.call(el, "");
}"""


def _status(request: SafeInputRequest) -> str:
    if (
        request.status == SafeInputRequest.PENDING
        and timezone.now() - request.created_at > REQUEST_TTL
    ):
        return "expired"
    return request.status


def _seal(username: str, password: str) -> bytes:
    if not username or not password or max(len(username), len(password)) > MAX_FIELD:
        raise IntegrationInvalid("username and password are required")
    return seal_secret(json.dumps({"username": username, "password": password}))


def _website(value: str) -> str:
    try:
        return browser.normalize_website(value)
    except ValueError as exc:
        raise IntegrationInvalid(str(exc)) from exc


def _metadata(item: SafeInput) -> dict:
    return {"id": str(item.id), "name": item.name, "website": item.website}


# Relay (Ally side) -------------------------------------------------------


def execute_safe_input_tool(
    *, message_id, binding_id, command_fingerprint, call_id, arguments
) -> tuple[int, dict]:
    ally = resolve_tool_turn(
        message_id, binding_id, command_fingerprint
    ).conversation.ally
    action = arguments.get("action")
    try:
        if action == "list":
            granted = set(
                SafeInputGrant.objects.filter(ally=ally).values_list(
                    "safe_input_id", flat=True
                )
            )
            items = SafeInput.objects.filter(workspace_id=ally.workspace_id).order_by(
                "name"
            )
            return 200, {
                "safe_inputs": [
                    {**_metadata(i), "has_access": i.id in granted} for i in items
                ]
            }
        if action == "request_new":
            name = str(arguments.get("name") or "").strip()[:80]
            website = _website(str(arguments.get("website") or ""))
            request = _pending_or_create(
                ally, safe_input=None, name=name or website, website=website
            )
            return 200, {"request_id": str(request.id), "status": "pending"}
        if action == "request_access":
            item = SafeInput.objects.get(
                pk=UUID(str(arguments.get("safe_input_id"))),
                workspace_id=ally.workspace_id,
            )
            if SafeInputGrant.objects.filter(safe_input=item, ally=ally).exists():
                return 200, {"status": "allowed", **_metadata(item)}
            request = _pending_or_create(
                ally, safe_input=item, name=item.name, website=item.website
            )
            return 200, {"request_id": str(request.id), "status": "pending"}
        if action == "status":
            request = SafeInputRequest.objects.get(
                pk=UUID(str(arguments.get("request_id"))), ally=ally
            )
            result = {"status": _status(request)}
            if request.safe_input_id and request.status in {"saved", "allowed"}:
                result |= _metadata(request.safe_input)
            return 200, result
        if action == "fill":
            return 200, fill(
                ally,
                UUID(str(arguments.get("safe_input_id"))),
                arguments.get("field") or None,
            )
    except (SafeInput.DoesNotExist, SafeInputRequest.DoesNotExist, ValueError):
        return 404, {"error": "not_found"}
    except IntegrationInvalid as exc:
        return 422, {"error": "invalid_request", "detail": str(exc)}
    return 422, {"error": "invalid_request"}


def _pending_or_create(ally, **fields) -> SafeInputRequest:
    # A retried or repeated ask reuses the open request, so the user sees one.
    return SafeInputRequest.objects.filter(
        ally=ally,
        status=SafeInputRequest.PENDING,
        created_at__gt=timezone.now() - REQUEST_TTL,
        **fields,
    ).first() or SafeInputRequest.objects.create(
        workspace_id=ally.workspace_id, ally=ally, **fields
    )


def execute_browser_tool(
    *, message_id, binding_id, command_fingerprint, call_id, arguments
) -> tuple[int, dict]:
    ally = resolve_tool_turn(
        message_id, binding_id, command_fingerprint
    ).conversation.ally
    if arguments.get("action") == "open":
        result = browser.open_browser(ally)
        return (429 if result.get("error") == "browser_limit_reached" else 200), result
    if arguments.get("action") == "close":
        result = browser.close_browser(ally, str(arguments.get("session_id")))
        return (422 if "error" in result else 200), result
    return 422, {"error": "invalid_request"}


def fill(ally, safe_input_id: UUID, field: str | None = None) -> dict:
    if field not in {None, "username", "password"}:
        raise IntegrationInvalid("field must be username or password")
    grant = (
        SafeInputGrant.objects.select_related("safe_input")
        .filter(ally=ally, safe_input_id=safe_input_id)
        .first()
    )
    if grant is None:
        return {"status": "no_access"}
    item = grant.safe_input
    session = browser.open_sessions(ally=ally).order_by("-started_at").first()
    if session is None or not session.cdp_url:
        return {"status": "no_browser"}
    values = json.loads(unseal_secret(item.sealed))
    # No reload first: many logins live in pop-ups that a reload closes. An
    # Ally-injected script could observe the fill; see the accepted limits in
    # the browser-and-safe-inputs spec (SEC-001).
    try:
        with browser.Cdp(session.cdp_url) as cdp:
            page = cdp.page()
            if field is None:
                outcome = _call(
                    cdp,
                    page,
                    _FILL,
                    item.website,
                    values["username"],
                    values["password"],
                )
            else:
                outcome = _call(
                    cdp, page, _FILL_FOCUSED, item.website, field, values[field]
                )
                if outcome == "filled":
                    # A trusted Enter submits the way a person would, form or not.
                    for kind in ("keyDown", "keyUp"):
                        cdp.call(
                            "Input.dispatchKeyEvent",
                            {
                                "type": kind,
                                "key": "Enter",
                                "code": "Enter",
                                "windowsVirtualKeyCode": 13,
                            },
                            session=page,
                        )
            # Field-by-field logins stay on the page while the Ally continues, so
            # clearing would empty the fields before the site reads them.
            if outcome == "filled" and field is None:
                time.sleep(3)
                try:
                    _call(cdp, page, _CLEAR, values["username"], values["password"])
                except ValueError:
                    pass  # The page navigated away, which is the usual success path.
    except (browser.BrowserUnavailable, ValueError, OSError, KeyError, StopIteration):
        outcome = "failed"
    status, _, page_host = outcome.partition(":")
    logger.info(
        "safe_input.fill ally=%s safe_input=%s site=%s field=%s outcome=%s",
        ally.id,
        item.id,
        item.website,
        field or "both",
        status,
    )
    result = {"status": status}
    if status == "domain_mismatch":
        result |= {"page_host": page_host, "website": item.website}
    return result


def _call(cdp, page: str, function: str, *args) -> str:
    window = cdp.call("Runtime.evaluate", {"expression": "window"}, session=page)
    reply = cdp.call(
        "Runtime.callFunctionOn",
        {
            "functionDeclaration": function,
            "objectId": window["result"]["objectId"],
            "arguments": [{"value": a} for a in args],
            "returnByValue": True,
        },
        session=page,
    )
    return str(reply["result"].get("value") or "")


# User side -----------------------------------------------------------------


def workspace_safe_inputs(workspace_id) -> list[dict]:
    items = SafeInput.objects.filter(workspace_id=workspace_id).prefetch_related(
        "grants"
    )
    return [
        {
            **_metadata(i),
            "ally_ids": [str(g.ally_id) for g in i.grants.all()],
            "updated_at": i.updated_at,
        }
        for i in items.order_by("name")
    ]


def pending_requests(workspace_id, ally_id=None) -> list[SafeInputRequest]:
    rows = SafeInputRequest.objects.filter(
        workspace_id=workspace_id,
        status=SafeInputRequest.PENDING,
        created_at__gt=timezone.now() - REQUEST_TTL,
    )
    if ally_id is not None:
        rows = rows.filter(ally_id=ally_id)
    return list(rows.order_by("created_at"))


def resolve_request(
    workspace_id, request_id, *, allow: bool, user, fields: dict
) -> SafeInputRequest:
    with transaction.atomic():
        request = SafeInputRequest.objects.select_for_update().get(
            pk=request_id, workspace_id=workspace_id
        )
        if _status(request) != SafeInputRequest.PENDING:
            raise IntegrationInvalid("request is no longer pending")
        if not allow:
            request.status = SafeInputRequest.DENIED
        elif request.safe_input_id is None:
            request.safe_input = SafeInput.objects.create(
                workspace_id=workspace_id,
                name=(fields.get("name") or request.name).strip()[:80],
                website=_website(fields.get("website") or request.website),
                sealed=_seal(fields.get("username", ""), fields.get("password", "")),
                created_by=user,
            )
            request.status = SafeInputRequest.SAVED
        else:
            request.status = SafeInputRequest.ALLOWED
        if allow:
            SafeInputGrant.objects.get_or_create(
                safe_input=request.safe_input, ally_id=request.ally_id
            )
            logger.info(
                "safe_input.granted safe_input=%s ally=%s",
                request.safe_input_id,
                request.ally_id,
            )
        request.save(update_fields=["safe_input", "status"])
    return request


def update_safe_input(workspace_id, safe_input_id, fields: dict) -> SafeInput:
    item = SafeInput.objects.get(pk=safe_input_id, workspace_id=workspace_id)
    if fields.get("name"):
        item.name = fields["name"].strip()[:80]
    if fields.get("website"):
        item.website = _website(fields["website"])
    if fields.get("username") or fields.get("password"):
        current = json.loads(unseal_secret(item.sealed))
        item.sealed = _seal(
            fields.get("username") or current["username"],
            fields.get("password") or current["password"],
        )
    item.save()
    return item


def delete_safe_input(workspace_id, safe_input_id) -> None:
    item = SafeInput.objects.get(pk=safe_input_id, workspace_id=workspace_id)
    for grant in item.grants.select_related("ally"):
        browser.sign_out_site(grant.ally, item.website)
    logger.info("safe_input.deleted safe_input=%s", item.id)
    item.delete()


def grant_access(workspace_id, safe_input_id, ally_id) -> None:
    item = SafeInput.objects.get(pk=safe_input_id, workspace_id=workspace_id)
    ally = Ally.objects.get(pk=ally_id, workspace_id=workspace_id)
    with transaction.atomic():
        SafeInputGrant.objects.get_or_create(safe_input=item, ally=ally)
        # The user answered any open access request by turning access on.
        SafeInputRequest.objects.filter(
            safe_input=item, ally=ally, status=SafeInputRequest.PENDING
        ).update(status=SafeInputRequest.ALLOWED)
    logger.info("safe_input.granted safe_input=%s ally=%s", item.id, ally.id)


def revoke_grant(workspace_id, safe_input_id, ally_id) -> None:
    grant = SafeInputGrant.objects.select_related("safe_input", "ally").get(
        safe_input_id=safe_input_id,
        safe_input__workspace_id=workspace_id,
        ally_id=ally_id,
    )
    browser.sign_out_site(grant.ally, grant.safe_input.website)
    logger.info("safe_input.revoked safe_input=%s ally=%s", safe_input_id, ally_id)
    grant.delete()
