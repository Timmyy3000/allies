"""Execution-bound adapter to the existing routine management services."""

import hashlib
import json
from typing import Literal
from uuid import UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat.models import DispatchOutbox, Message
from routines.models import Routine, RoutineToolCall
from routines.services.management import (
    create_routine_intent,
    delete_routine_intent,
    issue_deletion_confirmation,
    owner_routine_page,
    update_routine_intent,
)
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability


class RoutineToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal[
        "create",
        "list",
        "inspect",
        "update",
        "pause",
        "resume",
        "request_delete",
        "delete",
    ]
    routine_id: str | None = Field(default=None, max_length=36)
    expected_revision: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    execution_prompt: str | None = Field(default=None, min_length=1, max_length=16384)
    schedule: dict | None = None
    confirmation_ref: str | None = Field(default=None, max_length=36)
    cursor: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def action_fields(self):
        allowed = {
            "create": {"title", "execution_prompt", "schedule"},
            "list": {"cursor"},
            "inspect": {"routine_id"},
            "update": {
                "routine_id",
                "expected_revision",
                "title",
                "execution_prompt",
                "schedule",
            },
            "pause": {"routine_id", "expected_revision"},
            "resume": {"routine_id", "expected_revision"},
            "request_delete": {"routine_id", "expected_revision"},
            "delete": {"routine_id", "expected_revision", "confirmation_ref"},
        }[self.action]
        if self.model_fields_set - allowed - {"action"}:
            raise ValueError("unexpected fields for this action")
        return self


def _detail(routine):
    return {
        "routine_id": str(routine.id),
        "title": routine.title,
        "execution_prompt": routine.execution_prompt,
        "schedule": routine.schedule,
        "state": routine.state,
        "revision": routine.revision,
        "next_run_at": routine.next_run_at.isoformat() if routine.next_run_at else None,
    }


@transaction.atomic
def execute_routine_tool(
    *,
    message_id: UUID,
    binding_id: UUID,
    command_fingerprint: str,
    call_id: UUID,
    arguments: dict,
):
    args = RoutineToolRequest.model_validate(arguments)
    message = (
        Message.objects.select_for_update(of=("self",))
        .select_related(
            "conversation__ally__workspace__owner", "conversation__ally__binding"
        )
        .get(pk=message_id, sender="user", origin="send", deleted_at__isnull=True)
    )
    ally = message.conversation.ally
    workspace = ally.workspace
    if ally.binding.id != binding_id or not workspace.is_active:
        raise PermissionError("routine tool binding unavailable")
    require_workspace_capability(
        user=workspace.owner,
        workspace_id=workspace.id,
        capability=Capability.WORKSPACE_WRITE,
    )
    outbox = DispatchOutbox.objects.get(message=message)
    if not command_fingerprint or outbox.command_fingerprint != command_fingerprint:
        raise PermissionError("routine tool dispatch unavailable")
    digest = hashlib.sha256(
        json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    previous = RoutineToolCall.objects.filter(message=message, call_id=call_id).first()
    if previous:
        if previous.request_digest != digest:
            raise ValueError("tool call identity reused with different arguments")
        return previous.response
    scope = {"user": workspace.owner, "workspace_id": workspace.id}
    receipt_id = uuid5(message.id, str(call_id))
    if args.action == "list":
        page = owner_routine_page(
            **scope, ally_id=ally.id, cursor=args.cursor, limit=20
        )
        result = {
            "items": [
                {k: v for k, v in _detail(r).items() if k != "execution_prompt"}
                for r in page.items
            ],
            "next_cursor": page.next_cursor,
        }
    elif args.action == "create":
        if not args.title or not args.execution_prompt or not args.schedule:
            raise ValidationError(
                "title, execution_prompt and an explicit schedule are required"
            )
        result = _detail(
            create_routine_intent(
                **scope,
                ally_id=ally.id,
                main_conversation_id=message.conversation_id,
                title=args.title,
                execution_prompt=args.execution_prompt,
                schedule=args.schedule,
                command_id=receipt_id,
                idempotency_key=receipt_id,
            )
        )
    else:
        routine = Routine.objects.get(
            id=UUID(args.routine_id or ""),
            workspace=workspace,
            owner=workspace.owner,
            ally=ally,
            binding_id=binding_id,
            main_conversation_id=message.conversation_id,
        )
        if args.action == "inspect":
            result = _detail(routine)
        else:
            if args.expected_revision is None:
                raise ValidationError(
                    "expected_revision is required; inspect the routine first"
                )
            mutation = {
                **scope,
                "routine_id": routine.id,
                "expected_revision": args.expected_revision,
            }
            if args.action == "request_delete":
                result = issue_deletion_confirmation(
                    **mutation, main_conversation_id=message.conversation_id
                )
                result["instruction"] = (
                    "Ask the user to confirm deletion; delete only in a subsequent user turn after confirmation."
                )
            elif args.action == "delete":
                challenge = RoutineToolCall.objects.filter(
                    message__conversation_id=message.conversation_id,
                    message__sequence__lt=message.sequence,
                    response__confirmation_ref=args.confirmation_ref,
                    response__routine_id=str(routine.id),
                ).exists()
                if not args.confirmation_ref or not challenge:
                    raise ValidationError(
                        "deletion requires a challenge from an earlier user turn"
                    )
                result = _detail(
                    delete_routine_intent(
                        **mutation,
                        main_conversation_id=message.conversation_id,
                        confirmation_ref=args.confirmation_ref,
                        command_id=receipt_id,
                        idempotency_key=receipt_id,
                    )
                )
            else:
                updates = {
                    key: getattr(args, key)
                    for key in ("title", "execution_prompt", "schedule")
                    if getattr(args, key) is not None
                }
                if args.action in {"pause", "resume"}:
                    updates = {
                        "state": "paused" if args.action == "pause" else "active"
                    }
                result = _detail(
                    update_routine_intent(
                        **mutation,
                        **updates,
                        command_id=receipt_id,
                        idempotency_key=receipt_id,
                    )
                )
    response = {
        "status": "saved"
        if args.action not in {"list", "inspect", "request_delete"}
        else "ok",
        **result,
    }
    response["current_time"] = timezone.now().isoformat()
    RoutineToolCall.objects.create(
        message=message, call_id=call_id, request_digest=digest, response=response
    )
    return response
