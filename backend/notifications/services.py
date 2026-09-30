import hashlib
import json
import logging
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from auths.models import SessionFamily, User
from chat.models import Conversation
from common.vault import VaultUnavailable, seal_secret, unseal_secret
from workspaces.models import Membership, MembershipStatus

from .models import PushDelivery, PushNotification, PushSubscription
from .schemas import PresenceReceipt, PushPayload, PushRegistration
from .transport import configuration, decode_key, send_push, validate_endpoint

logger = logging.getLogger("allies.notifications")


class PushError(Exception):
    def __init__(self, code, status):
        self.code, self.status = code, status


def _retire(rows):
    rows.update(state="revoked", secret=b"", presence={}, updated_at=timezone.now())


def retire_family(family_id):
    _retire(PushSubscription.objects.filter(family_id=family_id, state="active"))


def _scope(family, workspace_id):
    now = timezone.now()
    locked = (
        SessionFamily.objects.select_for_update()
        .select_related("user")
        .get(pk=family.id)
    )
    if not locked.is_active(now) or locked.client_kind != "browser":
        raise PushError("session_invalid", 401)
    if not Membership.objects.filter(
        user_id=locked.user_id,
        workspace_id=workspace_id,
        status=MembershipStatus.ACTIVE,
        workspace__is_active=True,
    ).exists():
        raise PushError("push_not_found", 404)
    return locked


def registration(row):
    return PushRegistration(
        subscription_id=row.id,
        browser_id=row.browser_id,
        binding_id=row.binding_id,
        workspace_id=row.workspace_id,
        session_id=row.family_id,
    )


@transaction.atomic
def register_subscription(family, workspace_id, payload):
    User.objects.select_for_update().get(pk=family.user_id)
    family = _scope(family, workspace_id)
    raw = payload.model_dump_json()
    digest = hashlib.sha256(raw.encode()).hexdigest()
    existing = PushSubscription.objects.filter(binding_id=payload.binding_id).first()
    if existing:
        if (
            existing.owner_id != family.user_id
            or existing.workspace_id != workspace_id
            or existing.family_id != family.id
            or existing.registration_digest != digest
            or existing.state != "active"
        ):
            raise PushError("push_binding_conflict", 409)
        return registration(existing)
    if configuration() is None:
        raise PushError("push_unavailable", 503)
    decode_key(payload.keys.p256dh, 65)
    decode_key(payload.keys.auth, 16)
    validate_endpoint(payload.endpoint)
    active = PushSubscription.objects.filter(
        owner_id=family.user_id, browser_id=payload.browser_id, state="active"
    ).first()
    if (active is None and payload.replaces_binding_id is not None) or (
        active is not None
        and (
            active.binding_id != payload.replaces_binding_id
            or active.family_id != family.id
            or active.workspace_id != workspace_id
        )
    ):
        raise PushError("push_binding_conflict", 409)
    endpoint_digest = hashlib.sha256(payload.endpoint.encode()).hexdigest()
    collision = PushSubscription.objects.filter(
        endpoint_digest=endpoint_digest, state="active"
    )
    if active:
        collision = collision.exclude(pk=active.pk)
    if collision.exists():
        raise PushError("push_binding_conflict", 409)
    count = PushSubscription.objects.filter(
        owner_id=family.user_id, workspace_id=workspace_id, state="active"
    ).count()
    if count - bool(active) >= 5:
        raise PushError("push_subscription_limit", 429)
    secret = seal_secret(
        json.dumps(
            {"endpoint": payload.endpoint, "keys": payload.keys.model_dump()},
            separators=(",", ":"),
        )
    )
    try:
        with transaction.atomic():
            if active:
                _retire(PushSubscription.objects.filter(pk=active.pk))
            row = PushSubscription.objects.create(
                owner_id=family.user_id,
                workspace_id=workspace_id,
                family=family,
                browser_id=payload.browser_id,
                binding_id=payload.binding_id,
                registration_digest=digest,
                endpoint_digest=endpoint_digest,
                secret=secret,
            )
    except IntegrityError:
        raise PushError("push_binding_conflict", 409) from None
    return registration(row)


def _owned(family, workspace_id, subscription_id, binding_id):
    family = _scope(family, workspace_id)
    row = (
        PushSubscription.objects.select_for_update()
        .filter(
            pk=subscription_id,
            owner_id=family.user_id,
            workspace_id=workspace_id,
            family=family,
        )
        .first()
    )
    if row is None:
        raise PushError("push_not_found", 404)
    if row.binding_id != binding_id:
        raise PushError("push_binding_conflict", 409)
    return row


@transaction.atomic
def revoke_subscription(family, workspace_id, subscription_id, binding_id):
    row = _owned(family, workspace_id, subscription_id, binding_id)
    _retire(PushSubscription.objects.filter(pk=row.pk))


@transaction.atomic
def update_presence(family, workspace_id, subscription_id, payload, *, now=None):
    row = _owned(family, workspace_id, subscription_id, payload.binding_id)
    if row.state != "active":
        raise PushError("push_binding_conflict", 409)
    now = now or timezone.now()
    entries = dict(row.presence)
    live = {
        key: value
        for key, value in entries.items()
        if datetime.fromisoformat(value["expires_at"]) > now
    }
    key = str(payload.client_id)
    previous = entries.get(key)
    accepted = previous is None or payload.sequence > previous["sequence"]
    if accepted:
        # ponytail: 256 tab lifetimes per binding; rebind if this history limit is reached.
        if previous is None and len(entries) >= 256:
            raise PushError("push_presence_limit", 429)
        if key not in live and len(live) >= 8:
            raise PushError("push_presence_limit", 429)
        entries[key] = {
            "sequence": payload.sequence,
            "visible": payload.visible,
            "received_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=60)).isoformat(),
        }
    row.presence = entries
    row.save(update_fields=("presence", "updated_at"))
    # A hidden update releases cached-presence deferrals; other tabs still gate dispatch.
    if accepted:
        PushDelivery.objects.filter(
            subscription=row, state="pending", attempts=0, next_attempt_at__gt=now
        ).update(next_attempt_at=now)
    visible = [
        datetime.fromisoformat(v["expires_at"])
        for v in entries.values()
        if v["visible"] and datetime.fromisoformat(v["expires_at"]) > now
    ]
    return PresenceReceipt(
        accepted_sequence=entries[key]["sequence"],
        foreground_until=max(visible, default=None),
    )


def _nudge():
    from .tasks import dispatch_push_task

    try:
        dispatch_push_task.delay()
    except Exception:  # noqa: BLE001 - queue failure must leave the durable outbox recoverable
        logger.warning("push queue publication unavailable")


@transaction.atomic
def create_intent(*, identity, kind, conversation, expires_at, **sources):
    ally = conversation.ally
    if not conversation.is_default or ally.deletion_state != "active":
        return None
    notification, created = PushNotification.objects.get_or_create(
        identity=identity,
        defaults=dict(
            kind=kind,
            owner_id=ally.workspace.owner_id,
            workspace_id=ally.workspace_id,
            ally=ally,
            conversation=conversation,
            expires_at=expires_at,
            **sources,
        ),
    )
    if not created:
        return notification
    now = timezone.now()
    subscriptions = PushSubscription.objects.filter(
        owner_id=ally.workspace.owner_id,
        workspace_id=ally.workspace_id,
        state="active",
        family__revoked_at__isnull=True,
        family__idle_expires_at__gt=now,
        family__absolute_expires_at__gt=now,
        owner__is_active=True,
    )
    deliveries = []
    if Membership.objects.filter(
        user_id=ally.workspace.owner_id,
        workspace_id=ally.workspace_id,
        workspace__is_active=True,
        status=MembershipStatus.ACTIVE,
    ).exists():
        deliveries = PushDelivery.objects.bulk_create(
            [
                PushDelivery(
                    notification=notification, subscription=s, binding_id=s.binding_id
                )
                for s in subscriptions[:5]
            ]
        )
    if deliveries:
        transaction.on_commit(_nudge)
    return notification


def notify_reply(reply):
    message = reply.message
    if (
        message.origin != "send"
        or message.sender != "user"
        or message.status != "completed"
        or not reply.content.strip()
        or message.deleted_at is not None
        or not message.conversation.is_default
        or message.routine_action is not None
    ):
        return None
    from routines.models import Routine

    if Routine.objects.filter(source_message_id=message.id).exists():
        return None
    return create_intent(
        identity=f"reply:{reply.id}",
        kind="reply_completed",
        conversation=message.conversation,
        expires_at=timezone.now() + timedelta(hours=1),
        reply=reply,
    )


def notify_approval(approval):
    routine = hasattr(approval, "routine_id")
    conversation = (
        Conversation.objects.get(pk=approval.routine.main_conversation_id)
        if routine
        else approval.conversation
    )
    return create_intent(
        identity=f"approval:{approval.approval_request_id}",
        kind="approval_needed",
        conversation=conversation,
        expires_at=min(approval.expires_at, timezone.now() + timedelta(hours=24)),
        **{"routine_approval" if routine else "approval": approval},
    )


def notify_result(result, conversation):
    return create_intent(
        identity=f"routine-result:{result.id}",
        kind="routine_failed" if result.outcome == "failed" else "routine_completed",
        conversation=conversation,
        expires_at=timezone.now() + timedelta(hours=24),
        result=result,
    )


def _eligible(row, now):
    s, n = row.subscription, row.notification
    if (
        s.owner_id != n.owner_id
        or s.workspace_id != n.workspace_id
        or s.family.user_id != s.owner_id
        or s.state != "active"
        or s.binding_id != row.binding_id
        or not s.family.is_active(now)
        or n.expires_at <= now
        or not n.owner.is_active
        or n.ally.deletion_state != "active"
        or n.ally.workspace.owner_id != n.owner_id
        or n.ally.workspace_id != n.workspace_id
        or not n.conversation.is_default
        or n.conversation.ally_id != n.ally_id
    ):
        return False
    if not Membership.objects.filter(
        user_id=n.owner_id,
        workspace_id=n.workspace_id,
        workspace__is_active=True,
        status=MembershipStatus.ACTIVE,
    ).exists():
        return False
    if n.approval_id:
        a = n.approval
        if (
            a.status != "pending"
            or a.expires_at <= now
            or a.message.status != "awaiting_action"
            or a.conversation_id != n.conversation_id
        ):
            return False
    if n.routine_approval_id:
        a = n.routine_approval
        if (
            a.status != "pending"
            or a.expires_at <= now
            or a.run.outcome != "approval_waiting"
            or a.owner_id != n.owner_id
            or a.routine.main_conversation_id != n.conversation_id
        ):
            return False
    if n.reply_id and (
        n.reply.message.status != "completed" or n.reply.message.deleted_at is not None
    ):
        return False
    return not (
        n.result_id
        and (
            n.result.insertion_state != "inserted"
            or n.result.run.outcome not in ("succeeded", "failed")
        )
    )


def _presence_gate(row, now):
    cached_until = None
    for entry in row.subscription.presence.values():
        expires = datetime.fromisoformat(entry["expires_at"])
        if entry["visible"] and expires > now:
            if (
                datetime.fromisoformat(entry["received_at"])
                > row.notification.created_at
            ):
                return "suppressed", None
            cached_until = max(cached_until or expires, expires)
    return "pending", cached_until


def _row(delivery_id):
    return PushDelivery.objects.select_related(
        "subscription__family__user",
        "notification__owner",
        "notification__ally",
        "notification__conversation",
        "notification__approval__message",
        "notification__routine_approval__routine",
        "notification__routine_approval__run",
        "notification__reply__message",
        "notification__result__run",
    ).get(pk=delivery_id)


@transaction.atomic
def claim_delivery(delivery_id, *, now=None):
    now = now or timezone.now()
    # Subscription first also serializes presence and renewal against admission.
    try:
        identity = PushDelivery.objects.only("subscription_id").get(pk=delivery_id)
        PushSubscription.objects.select_for_update().get(pk=identity.subscription_id)
        PushDelivery.objects.select_for_update().get(pk=delivery_id)
        row = _row(delivery_id)
    except (PushDelivery.DoesNotExist, PushSubscription.DoesNotExist):
        return None
    if not (
        (row.state == "pending" and row.next_attempt_at <= now)
        or (
            row.state == "sending"
            and row.lease_until is not None
            and row.lease_until <= now
        )
    ):
        return None
    if not _eligible(row, now):
        row.state = "retired"
        if not row.subscription.family.is_active(now):
            retire_family(row.subscription.family_id)
    elif row.attempts >= 3:
        row.state, row.safe_error_code = "failed", "push_attempts_exhausted"
    else:
        state, defer = _presence_gate(row, now)
        if state == "suppressed":
            row.state = state
        elif defer:
            row.state, row.next_attempt_at = "pending", defer
        elif configuration() is None:
            row.state, row.next_attempt_at = "pending", now + timedelta(seconds=60)
        else:
            row.state = "sending"
            row.attempts += 1
            row.lease_until = now + timedelta(seconds=30)
            row.save()
            return row
    row.lease_until = None
    row.save()
    return None


def _retry_after(value, now):
    try:
        seconds = int(value)
    except (ValueError, TypeError):
        try:
            seconds = int((parsedate_to_datetime(value) - now).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0
    return max(0, min(seconds, 300))


@transaction.atomic
def settle_delivery(lease, status, retry_after=None, code="", *, now=None):
    now = now or timezone.now()
    if (
        not PushSubscription.objects.select_for_update()
        .filter(pk=lease.subscription_id)
        .first()
    ):
        return False
    row = (
        PushDelivery.objects.select_for_update()
        .filter(
            pk=lease.id,
            state="sending",
            attempts=lease.attempts,
            lease_until=lease.lease_until,
        )
        .first()
    )
    if row is None:
        return False
    row.safe_error_code = code
    if 200 <= status < 300:
        row.state = "sent"
    elif status in (404, 410):
        row.state = "retired"
        _retire(PushSubscription.objects.filter(pk=row.subscription_id))
    elif status in (0, 408, 429) or status >= 500:
        delay = max((30, 120, 120)[row.attempts - 1], _retry_after(retry_after, now))
        row.next_attempt_at = now + timedelta(seconds=delay)
        row.state = (
            "pending"
            if row.attempts < 3 and row.next_attempt_at < row.notification.expires_at
            else "failed"
        )
        row.safe_error_code = (
            "push_retryable" if row.state == "pending" else "push_attempts_exhausted"
        )
    else:
        row.state = "failed"
        row.safe_error_code = (
            "push_configuration_error"
            if status in (401, 403)
            else code or "push_rejected"
        )
        if status in (401, 403):
            logger.warning(
                "push provider configuration error",
                extra={"push_configuration_error_count": 1},
            )
    row.lease_until = None
    row.save()
    return True


def _clip(text, limit):
    return text and text.encode()[:limit].decode(errors="ignore")


def _preview(n):
    if n.kind != "reply_completed" or n.reply is None:
        return None
    return " ".join(n.reply.content.split())


def dispatch_push(*, now=None, limit=50):
    boundary = now or timezone.now()
    due = Q(state="pending", next_attempt_at__lte=boundary) | Q(
        state="sending", lease_until__lte=boundary
    )
    ids = list(
        PushDelivery.objects.filter(due)
        .order_by("next_attempt_at", "id")
        .values_list("id", flat=True)[: max(1, min(limit, 50))]
    )
    attempts = 0
    for delivery_id in ids:
        lease = claim_delivery(delivery_id, now=now or timezone.now())
        if lease is None:
            continue
        admitted_at = now or timezone.now()
        try:
            current = _row(delivery_id)
        except PushDelivery.DoesNotExist:
            continue
        if not _eligible(current, admitted_at):
            PushDelivery.objects.filter(
                pk=lease.id,
                state="sending",
                attempts=lease.attempts,
                lease_until=lease.lease_until,
            ).update(state="retired", lease_until=None)
            continue
        n = lease.notification
        payload = PushPayload(
            title=_clip(n.ally.name, 100),
            body=_clip(_preview(n), 200),
            notification_id=n.id,
            binding_id=lease.binding_id,
            kind=n.kind,
            workspace_id=n.workspace_id,
            ally_id=n.ally_id,
            conversation_id=n.conversation_id,
            expires_at=n.expires_at,
        ).model_dump_json()
        try:
            subscription = json.loads(unseal_secret(lease.subscription.secret))
            if len(payload.encode()) > 1024:
                raise ValueError
            status, retry_after, code = send_push(
                subscription,
                payload,
                min(300, max(0, int((n.expires_at - admitted_at).total_seconds()))),
            )
        except (VaultUnavailable, ValueError, TypeError, KeyError):
            status, retry_after, code = 400, None, "push_secret_invalid"
        settle_delivery(lease, status, retry_after, code, now=now or timezone.now())
        attempts += 1
    cleanup_push(now=now or timezone.now())
    return attempts


def cleanup_push(*, now=None):
    now = now or timezone.now()
    stale = PushSubscription.objects.filter(state="active").filter(
        Q(family__revoked_at__isnull=False)
        | Q(family__idle_expires_at__lte=now)
        | Q(family__absolute_expires_at__lte=now)
    )
    _retire(
        PushSubscription.objects.filter(
            pk__in=list(stale.values_list("pk", flat=True)[:100])
        )
    )
    old = PushNotification.objects.filter(
        expires_at__lt=now - timedelta(days=7)
    ).exclude(pushdelivery__state__in=("pending", "sending"))
    PushNotification.objects.filter(
        pk__in=list(old.values_list("pk", flat=True)[:100])
    ).delete()
    tombstones = PushSubscription.objects.filter(state="revoked").filter(
        Q(family__idle_expires_at__lte=now) | Q(family__absolute_expires_at__lte=now)
    )
    PushSubscription.objects.filter(
        pk__in=list(tombstones.values_list("pk", flat=True)[:100])
    ).delete()
