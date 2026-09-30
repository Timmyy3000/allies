import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.cache import cache
from django.db import close_old_connections, connection, transaction
from django.http import HttpResponse
from django.test import Client
from django.utils import timezone

from activities.services.projection import project_foundry_event
from activities.tests import test_cld005
from activities.tests.test_cld005 import event_for
from auths.config import cookie_name
from auths.models import User
from auths.services.sessions import authenticate_access, issue_session, logout_session
from chat.models import AssistantReply
from notifications import services, transport
from notifications.middleware import PushRequestLimitMiddleware
from notifications.models import PushDelivery, PushNotification, PushSubscription
from notifications.schemas import PushPresence, RegisterPush
from routines.tests import test_approvals, test_results

conversation_records = test_cld005.conversation_records
result_account = test_results.result_account
approval_account = test_approvals.approval_account


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture
def push_setup(conversation_records, settings, monkeypatch):
    settings.DEBUG = True
    private = ec.generate_private_key(ec.SECP256R1())
    settings.ALLIES_PUSH_VAPID_PRIVATE_KEY = b64(
        private.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    settings.ALLIES_PUSH_VAPID_PUBLIC_KEY = b64(
        private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    settings.ALLIES_PUSH_VAPID_CONTACT = "mailto:push@example.com"
    settings.ALLIES_PUSH_ENABLED = True
    settings.CSRF_TRUSTED_ORIGINS = ["https://app.example.com"]
    monkeypatch.setattr(
        transport.socket,
        "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(services, "_nudge", lambda: None)
    cache.clear()
    user, _workspace, *_ = conversation_records
    issued = issue_session(user)
    payload = RegisterPush(
        browser_id=uuid4(),
        binding_id=uuid4(),
        replaces_binding_id=None,
        endpoint="https://fcm.googleapis.com/push/private-capability",
        keys={"p256dh": settings.ALLIES_PUSH_VAPID_PUBLIC_KEY, "auth": b64(b"a" * 16)},
    )
    return conversation_records, issued, payload


def register(push_setup):
    records, issued, payload = push_setup
    response = services.register_subscription(issued.family, records[1].id, payload)
    return PushSubscription.objects.get(pk=response.subscription_id)


def intent(push_setup, row=None):
    records, _issued, _payload = push_setup
    message = records[-1]
    message.status = "completed"
    message.save()
    reply = AssistantReply.objects.create(message=message, content="private reply")
    services.notify_reply(reply)
    return PushDelivery.objects.get(subscription=row or register(push_setup))


def client_for(issued):
    client = Client()
    client.cookies[cookie_name("access")] = issued.access_token
    client.cookies["csrftoken"] = "a" * 32
    return client


def api_request(client, method, path, payload, **headers):
    return getattr(client, method)(
        path,
        json.dumps(payload),
        content_type="application/json",
        HTTP_ORIGIN="https://app.example.com",
        HTTP_X_CSRFTOKEN="a" * 32,
        **headers,
    )


def test_registration_idempotency_renewal_cas_tombstone_and_family(push_setup):
    records, issued, payload = push_setup
    first = register(push_setup)
    replay = services.register_subscription(issued.family, records[1].id, payload)
    assert replay.subscription_id == first.id and replay.session_id == issued.family.id
    assert bytes(first.secret) and b"private-capability" not in bytes(first.secret)
    changed = payload.model_copy(
        update={
            "binding_id": uuid4(),
            "replaces_binding_id": first.binding_id,
            "endpoint": "https://fcm.googleapis.com/push/renewed",
        }
    )
    renewed = services.register_subscription(issued.family, records[1].id, changed)
    assert (
        services.register_subscription(issued.family, records[1].id, changed) == renewed
    )
    first.refresh_from_db()
    assert first.state == "revoked" and not first.secret
    with pytest.raises(services.PushError) as exc:
        services.register_subscription(
            issued.family,
            records[1].id,
            changed.model_copy(update={"binding_id": uuid4()}),
        )
    assert exc.value.code == "push_binding_conflict"
    with pytest.raises(services.PushError):
        services.register_subscription(issued.family, records[1].id, payload)
    other_family = issue_session(records[0]).family
    with pytest.raises(services.PushError):
        services.register_subscription(other_family, records[1].id, changed)
    services.revoke_subscription(
        issued.family, records[1].id, renewed.subscription_id, changed.binding_id
    )
    services.revoke_subscription(
        issued.family, records[1].id, renewed.subscription_id, changed.binding_id
    )
    with pytest.raises(services.PushError):
        services.register_subscription(issued.family, records[1].id, changed)


def test_api_auth_origin_csrf_strict_size_and_contract(push_setup):
    records, issued, payload = push_setup
    path = f"/api/v1/workspaces/{records[1].id}/push"
    assert Client().get(path + "/config").status_code == 401
    client = client_for(issued)
    config = client.get(path + "/config")
    assert config.status_code == 200 and config["Cache-Control"] == "no-store"
    assert config.json()["data"]["presence_ttl_seconds"] == 60
    body = payload.model_dump(mode="json")
    assert (
        client.post(
            path + "/subscriptions", json.dumps(body), content_type="application/json"
        ).status_code
        == 403
    )
    assert (
        api_request(
            client,
            "post",
            path + "/subscriptions",
            {**body, "owner_id": str(records[0].id)},
        ).status_code
        == 422
    )
    assert (
        client.post(
            path + "/subscriptions", " " * 8193, content_type="application/json"
        ).status_code
        == 422
    )
    response = api_request(client, "post", path + "/subscriptions", body)
    assert response.status_code == 200
    assert response.json()["data"]["session_id"] == str(issued.family.id)
    subscription_path = (
        path + "/subscriptions/" + response.json()["data"]["subscription_id"]
    )
    foreign = client_for(issue_session(User.objects.create_user()))
    assert (
        api_request(
            foreign,
            "delete",
            subscription_path,
            {"binding_id": str(payload.binding_id)},
        ).status_code
        == 403
    )
    other = client_for(issue_session(records[0]))
    assert (
        api_request(
            other, "delete", subscription_path, {"binding_id": str(payload.binding_id)}
        ).status_code
        == 404
    )
    native = issue_session(records[0], client_kind="native")
    assert (
        Client()
        .get(path + "/config", HTTP_AUTHORIZATION=f"Bearer {native.access_token}")
        .status_code
        == 401
    )
    presence = {
        "binding_id": str(payload.binding_id),
        "client_id": str(uuid4()),
        "sequence": True,
        "visible": True,
    }
    assert (
        api_request(
            client, "post", subscription_path + "/presence", presence
        ).status_code
        == 422
    )
    assert (
        api_request(
            client, "delete", subscription_path, {"binding_id": str(uuid4())}
        ).status_code
        == 409
    )
    assert (
        api_request(
            client, "delete", subscription_path, {"binding_id": str(payload.binding_id)}
        ).status_code
        == 204
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/push",
        "https://fcm.googleapis.com.evil.test/push",
        "https://fcm.googleapis.com@evil.test/",
        "https://127.0.0.1/",
        "https://web.push.apple.com:8443/",
        "https://web.push.apple.com/#private",
        "https://FCM.GOOGLEAPIS.COM/",
        "https://fcm.googleapis.com./",
        "https://web.push.apple.com/\n",
    ],
)
def test_endpoint_rejects_untrusted_targets(push_setup, endpoint):
    with pytest.raises(transport.PushInvalid):
        transport.validate_endpoint(endpoint)


def test_dns_private_keys_and_response_transport_are_bounded(push_setup, monkeypatch):
    monkeypatch.setattr(
        transport.socket,
        "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(transport.PushInvalid):
        transport.validate_endpoint("https://fcm.googleapis.com/push")
    for value, size in [("=" * 22, 16), (b64(b"x" * 65), 65), (b64(b"x" * 15), 16)]:
        with pytest.raises(transport.PushInvalid):
            transport.decode_key(value, size)
    monkeypatch.setattr(
        transport.socket,
        "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    calls = []

    def post(self, url, **kwargs):
        calls.append((self.trust_env, kwargs))
        response = requests.Response()
        response.status_code = 302
        response.raw = BytesIO(b"private provider body")
        return response

    monkeypatch.setattr(requests.Session, "post", post)
    with transport.ProviderSession() as session:
        response = session.post(
            "https://fcm.googleapis.com/push", timeout=10, data=b"encrypted"
        )
    assert response.content == b""
    assert calls == [
        (
            False,
            {
                "timeout": 10,
                "data": b"encrypted",
                "allow_redirects": False,
                "stream": True,
            },
        )
    ]


def test_cached_foreground_defers_then_sends_and_fresh_suppresses(
    push_setup, monkeypatch
):
    row = register(push_setup)
    records, issued, payload = push_setup
    now = timezone.now()
    tab = uuid4()
    presence = PushPresence(
        binding_id=payload.binding_id, client_id=tab, sequence=1, visible=True
    )
    services.update_presence(
        issued.family, records[1].id, row.id, presence, now=now - timedelta(seconds=1)
    )
    delivery = intent(push_setup, row)
    created = delivery.notification.created_at
    assert services.claim_delivery(delivery.id, now=created) is None
    delivery.refresh_from_db()
    assert delivery.state == "pending" and delivery.attempts == 0
    calls = []
    monkeypatch.setattr(
        services, "send_push", lambda *a: calls.append(a) or (201, None, "")
    )
    assert services.dispatch_push(now=now + timedelta(seconds=61)) == 1
    delivery.refresh_from_db()
    assert delivery.state == "sent" and len(calls) == 1
    assert (
        len(calls[0][1].encode()) <= 1024
        and '"title":"Mira"' in calls[0][1]
        and '"body":"private reply"' in calls[0][1]
    )
    delivery.state = "pending"
    delivery.next_attempt_at = created
    delivery.save()
    receipt = services.update_presence(
        issued.family,
        records[1].id,
        row.id,
        presence.model_copy(update={"sequence": 2}),
        now=created + timedelta(seconds=1),
    )
    assert receipt.accepted_sequence == 2
    stale = services.update_presence(
        issued.family,
        records[1].id,
        row.id,
        presence.model_copy(update={"visible": False}),
        now=created + timedelta(seconds=2),
    )
    assert stale.accepted_sequence == 2
    assert (
        services.claim_delivery(delivery.id, now=created + timedelta(seconds=3)) is None
    )
    delivery.refresh_from_db()
    assert delivery.state == "suppressed"


def test_hidden_tab_does_not_clear_other_tab_and_presence_limit(push_setup):
    records, issued, payload = push_setup
    row = register(push_setup)
    now = timezone.now()
    for index in range(8):
        p = PushPresence(
            binding_id=payload.binding_id,
            client_id=uuid4(),
            sequence=1,
            visible=index == 0,
        )
        receipt = services.update_presence(
            issued.family, records[1].id, row.id, p, now=now
        )
    assert receipt.foreground_until == now + timedelta(seconds=60)
    with pytest.raises(services.PushError) as exc:
        services.update_presence(
            issued.family,
            records[1].id,
            row.id,
            p.model_copy(update={"client_id": uuid4()}),
            now=now,
        )
    assert exc.value.status == 429
    services.update_presence(
        issued.family,
        records[1].id,
        row.id,
        p.model_copy(update={"client_id": uuid4()}),
        now=now + timedelta(seconds=61),
    )
    row.refresh_from_db()
    assert len(row.presence) == 9


@pytest.mark.parametrize("status", [0, 408, 429, 500])
def test_bounded_retry_and_crash_lease_recovery(push_setup, status):
    row = register(push_setup)
    delivery = intent(push_setup, row)
    now = timezone.now()
    lease = services.claim_delivery(delivery.id, now=now)
    assert lease and services.claim_delivery(delivery.id, now=now) is None
    recovered = services.claim_delivery(delivery.id, now=now + timedelta(seconds=31))
    assert recovered.attempts == 2
    assert not services.settle_delivery(lease, 201, now=now + timedelta(seconds=32))
    assert services.settle_delivery(
        recovered, status, "99999", now=now + timedelta(seconds=32)
    )
    delivery.refresh_from_db()
    assert delivery.next_attempt_at == now + timedelta(seconds=332)
    third = services.claim_delivery(delivery.id, now=delivery.next_attempt_at)
    services.settle_delivery(third, status, now=delivery.next_attempt_at)
    delivery.refresh_from_db()
    assert delivery.state == "failed" and delivery.attempts == 3


@pytest.mark.parametrize(
    "status,state",
    [
        (404, "retired"),
        (410, "retired"),
        (401, "failed"),
        (403, "failed"),
        (302, "failed"),
        (400, "failed"),
        (204, "sent"),
    ],
)
def test_provider_outcomes(push_setup, status, state):
    row = register(push_setup)
    delivery = intent(push_setup, row)
    lease = services.claim_delivery(delivery.id)
    services.settle_delivery(lease, status)
    delivery.refresh_from_db()
    row.refresh_from_db()
    assert delivery.state == state
    if status in (404, 410):
        assert row.state == "revoked" and not row.secret


def test_logout_retirement_membership_and_late_enable_no_backfill(push_setup):
    row = register(push_setup)
    delivery = intent(push_setup, row)
    records, issued, payload = push_setup
    logout_session(access=authenticate_access(issued.access_token))
    row.refresh_from_db()
    assert row.state == "revoked" and not row.secret
    assert services.claim_delivery(delivery.id) is None
    late = services.register_subscription(
        issue_session(records[0]).family,
        records[1].id,
        payload.model_copy(update={"binding_id": uuid4()}),
    )
    assert not PushDelivery.objects.filter(
        subscription_id=late.subscription_id
    ).exists()


def test_product_projection_atomic_and_duplicate_reply(push_setup):
    row = register(push_setup)
    records = push_setup[0]
    message, binding = records[-1], records[3]
    project_foundry_event(event_for(message, binding))
    assert not PushNotification.objects.exists()
    completed = event_for(
        message,
        binding,
        event_type="execution.completed",
        attempt_sequence=2,
        payload={"status": "completed"},
    )
    with pytest.raises(RuntimeError), transaction.atomic():
        project_foundry_event(completed)
        assert PushDelivery.objects.filter(subscription=row).count() == 1
        raise RuntimeError
    assert not PushNotification.objects.exists()
    project_foundry_event(completed)
    project_foundry_event(completed)
    assert PushNotification.objects.count() == 1 and PushDelivery.objects.count() == 1


def _register_account(push_setup, account):
    user, workspace = account[:2]
    payload = push_setup[2].model_copy(
        update={
            "binding_id": uuid4(),
            "browser_id": uuid4(),
            "endpoint": f"https://fcm.googleapis.com/{uuid4()}",
        }
    )
    services.register_subscription(issue_session(user).family, workspace.id, payload)


def test_routine_result_only_after_insertion(push_setup, result_account):
    _register_account(push_setup, result_account)
    test_results._accept_dispatch(result_account)
    result = test_results.project_routine_result(test_results._event(result_account))
    assert not PushNotification.objects.filter(
        identity=f"routine-result:{result.result.id}"
    ).exists()
    test_results.complete_routine_result_insertion(
        result_id=result.result.id, insertion_watermark=1
    )
    assert PushNotification.objects.filter(
        identity=f"routine-result:{result.result.id}"
    ).exists()
    notification = PushNotification.objects.get(result=result.result)
    assert notification.kind == "routine_completed"
    assert services._preview(notification) == " ".join(result.result.text.split())


def test_routine_approval_staleness(push_setup, approval_account):
    _register_account(push_setup, approval_account)
    event = test_approvals._approval_event(approval_account)
    # Fixture event time is historical; use a future authoritative expiry.
    created = timezone.now()
    event["created_at"] = created.isoformat().replace("+00:00", "Z")
    event["expires_at"] = (
        (created + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    )
    event["fingerprint"] = test_approvals.canonical_fingerprint(event)
    approval = test_approvals.apply_routine_approval_requested_event(event).approval
    delivery = PushDelivery.objects.get(notification__routine_approval=approval)
    approval.status = "decision_recorded"
    approval.save()
    assert services.claim_delivery(delivery.id) is None
    delivery.refresh_from_db()
    assert delivery.state == "retired"


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_postgresql_binding_and_event_claims(push_setup):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL")
    records, issued, payload = push_setup
    barrier = Barrier(2)

    def bind(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return services.register_subscription(
                issued.family, records[1].id, payload
            ).subscription_id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(bind, range(2)))
    assert ids[0] == ids[1] and PushSubscription.objects.count() == 1
    row = PushSubscription.objects.get(pk=ids[0])
    delivery = intent(push_setup, row)
    barrier = Barrier(2)

    def claim(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return services.claim_delivery(delivery.id)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(claim, range(2)))
    assert sum(lease is not None for lease in leases) == 1


def test_batch_refreshes_clock_and_retires_expired_later_item(push_setup, monkeypatch):
    row = register(push_setup)
    first = intent(push_setup, row)
    second = services.create_intent(
        identity=f"reply:{uuid4()}",
        kind="reply_completed",
        conversation=push_setup[0][4],
        expires_at=timezone.now() + timedelta(seconds=2),
    )
    now = timezone.now()
    PushDelivery.objects.filter(notification=second).update(
        next_attempt_at=now + timedelta(microseconds=1)
    )
    PushDelivery.objects.filter(pk=first.pk).update(next_attempt_at=now)
    clock = [now + timedelta(microseconds=2)]
    calls = []
    monkeypatch.setattr(services.timezone, "now", lambda: clock[0])

    def send(*args):
        calls.append(args)
        clock[0] += timedelta(seconds=10)
        return 201, None, ""

    monkeypatch.setattr(services, "send_push", send)
    assert services.dispatch_push() == 1 and len(calls) == 1
    assert PushDelivery.objects.get(notification=second).state == "retired"


def test_ordinary_approval_stale_and_reply_origin_exclusion(push_setup):
    row = register(push_setup)
    records = push_setup[0]
    message, binding = records[-1], records[3]
    event = event_for(
        message,
        binding,
        event_type="execution.awaiting_action",
        payload={
            "approval_request_id": str(uuid4()),
            "action_kind": "terminal",
            "action_label": "Run command",
            "action_preview": "private command",
            "expires_at": "2026-08-25T12:05:00Z",
        },
    )
    values = event.model_dump(mode="json")
    values["issued_at"] = timezone.now().isoformat()
    values["payload"]["expires_at"] = (
        timezone.now() + timedelta(seconds=60)
    ).isoformat()
    values["fingerprint"] = test_cld005.canonical_fingerprint(values)
    event = test_cld005.FoundryEventEnvelope.model_validate(values)
    project_foundry_event(event)
    delivery = PushDelivery.objects.get(subscription=row)
    approval = delivery.notification.approval
    approval.status = "decision_recorded"
    approval.save()
    assert services.claim_delivery(delivery.id) is None
    reply = AssistantReply.objects.get(message=message)
    message.status = "completed"
    message.routine_action = {"kind": "routine"}
    message.save()
    reply.message = message
    reply.content = "routine text"
    reply.save()
    assert services.notify_reply(reply) is None
    message.routine_action = None
    message.origin = "onboarding"
    assert services.notify_reply(reply) is None


def test_limits_throttle_unavailable_configuration_and_cleanup(push_setup, settings):
    records, issued, payload = push_setup
    for index in range(5):
        services.register_subscription(
            issued.family,
            records[1].id,
            payload.model_copy(
                update={
                    "binding_id": uuid4(),
                    "browser_id": uuid4(),
                    "endpoint": f"https://fcm.googleapis.com/{index}",
                }
            ),
        )
    with pytest.raises(services.PushError) as exc:
        services.register_subscription(issued.family, records[1].id, payload)
    assert exc.value.status == 429
    settings.ALLIES_PUSH_VAPID_PRIVATE_KEY = "invalid"
    path = f"/api/v1/workspaces/{records[1].id}/push"
    client = client_for(issued)
    assert client.get(path + "/config").json()["data"]["enabled"] is False
    cache.clear()
    for _ in range(20):
        assert (
            api_request(
                client, "post", path + "/subscriptions", payload.model_dump(mode="json")
            ).status_code
            == 503
        )
    assert (
        api_request(
            client, "post", path + "/subscriptions", payload.model_dump(mode="json")
        ).status_code
        == 429
    )
    issued.family.idle_expires_at = timezone.now() - timedelta(seconds=1)
    issued.family.save()
    services.cleanup_push()
    assert not PushSubscription.objects.exists()


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_postgresql_same_event_intent_deduplication(push_setup):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL")
    register(push_setup)
    identity = f"reply:{uuid4()}"
    barrier = Barrier(2)

    def create(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return services.create_intent(
                identity=identity,
                kind="reply_completed",
                conversation=push_setup[0][4],
                expires_at=timezone.now() + timedelta(hours=1),
            ).id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(create, range(2)))
    assert ids[0] == ids[1] and PushNotification.objects.count() == 1
    assert PushDelivery.objects.count() == 1


@pytest.mark.parametrize("sequence", [1, 2])
def test_presence_updates_preserve_provider_retry_after(push_setup, sequence):
    row = register(push_setup)
    delivery = intent(push_setup, row)
    records, issued, payload = push_setup
    now = timezone.now()
    tab = uuid4()
    presence = PushPresence(
        binding_id=payload.binding_id, client_id=tab, sequence=1, visible=False
    )
    services.update_presence(issued.family, records[1].id, row.id, presence, now=now)
    lease = services.claim_delivery(delivery.id, now=now)
    services.settle_delivery(lease, 429, "300", now=now)
    delivery.refresh_from_db()
    retry_at = delivery.next_attempt_at
    services.update_presence(
        issued.family,
        records[1].id,
        row.id,
        presence.model_copy(update={"sequence": sequence}),
        now=now + timedelta(seconds=1),
    )
    delivery.refresh_from_db()
    assert delivery.next_attempt_at == retry_at
    assert services.claim_delivery(delivery.id, now=now + timedelta(seconds=2)) is None


def test_expired_presence_keeps_high_water_and_does_not_suppress_new_event(push_setup):
    row = register(push_setup)
    records, issued, payload = push_setup
    now = timezone.now()
    presence = PushPresence(
        binding_id=payload.binding_id, client_id=uuid4(), sequence=2, visible=True
    )
    services.update_presence(
        issued.family, records[1].id, row.id, presence, now=now - timedelta(seconds=61)
    )
    row.refresh_from_db()
    before = dict(row.presence)
    delivery = intent(push_setup, row)
    receipt = services.update_presence(
        issued.family,
        records[1].id,
        row.id,
        presence.model_copy(update={"sequence": 1}),
        now=now,
    )
    row.refresh_from_db()
    assert receipt.accepted_sequence == 2 and receipt.foreground_until is None
    assert row.presence == before
    assert (
        services.claim_delivery(delivery.id, now=now + timedelta(seconds=1)) is not None
    )


def test_presence_history_cap_never_evicts_sequence(push_setup):
    row = register(push_setup)
    records, issued, payload = push_setup
    now = timezone.now()
    history = {
        str(uuid4()): {
            "sequence": 2,
            "visible": True,
            "received_at": (now - timedelta(seconds=61)).isoformat(),
            "expires_at": (now - timedelta(seconds=1)).isoformat(),
        }
        for _ in range(256)
    }
    row.presence = history
    row.save()
    fresh = PushPresence(
        binding_id=payload.binding_id, client_id=uuid4(), sequence=1, visible=False
    )
    with pytest.raises(services.PushError) as exc:
        services.update_presence(issued.family, records[1].id, row.id, fresh, now=now)
    assert exc.value.status == 429
    key = next(iter(history))
    stale = fresh.model_copy(update={"client_id": key})
    assert (
        services.update_presence(
            issued.family, records[1].id, row.id, stale, now=now
        ).accepted_sequence
        == 2
    )
    row.refresh_from_db()
    assert row.presence == history
    newer = fresh.model_copy(update={"client_id": key, "sequence": 3})
    assert (
        services.update_presence(
            issued.family, records[1].id, row.id, newer, now=now
        ).accepted_sequence
        == 3
    )
    row.refresh_from_db()
    assert len(row.presence) == 256


def test_real_webpush_uses_controlled_transport_without_provider_body(
    push_setup, monkeypatch
):
    calls = []
    responses = []

    def provider_post(session, endpoint, **kwargs):
        calls.append((session.trust_env, endpoint, kwargs))
        response = requests.Response()
        response.status_code = 201
        response.raw = BytesIO(b"private provider response")
        responses.append(response)
        return response

    monkeypatch.setattr(requests.Session, "post", provider_post)
    registration = push_setup[2]
    plaintext = '{"version":1}'
    result = transport.send_push(
        {"endpoint": registration.endpoint, "keys": registration.keys.model_dump()},
        plaintext,
        120,
    )
    assert result == (201, None, "")
    assert len(calls) == 1
    trust_env, endpoint, request = calls[0]
    assert not trust_env and endpoint == registration.endpoint
    assert request["timeout"] == 10
    assert request["allow_redirects"] is False and request["stream"] is True
    assert isinstance(request["data"], bytes) and request["data"] != plaintext.encode()
    headers = requests.structures.CaseInsensitiveDict(request["headers"])
    assert headers["TTL"] == "120"
    assert headers["Content-Encoding"] == "aes128gcm"
    assert headers["Authorization"].startswith("vapid ")
    assert responses[0].content == b"" and responses[0].raw.closed


@pytest.mark.parametrize("length", (None, "0", "-1", "8193", "invalid"))
def test_body_limit_rejects_unbounded_length_without_reading(length):
    request = SimpleNamespace(
        path="/api/v1/workspaces/test/push/subscriptions",
        method="POST",
        META={"CONTENT_LENGTH": length},
    )
    response = PushRequestLimitMiddleware(lambda request: pytest.fail("parsed body"))(
        request
    )
    assert response.status_code == 422


@pytest.mark.parametrize("body,status", ((b"{}", 204), (b"x" * 8193, 422)))
def test_body_limit_reads_only_bounded_bytes_and_caches_for_parser(body, status):
    reads = []
    request = SimpleNamespace(
        path="/api/v1/workspaces/test/push/subscriptions",
        method="POST",
        META={"CONTENT_LENGTH": "2"},
        read=lambda size: reads.append(size) or body,
    )
    response = PushRequestLimitMiddleware(lambda request: HttpResponse(status=204))(
        request
    )
    assert reads == [8193] and response.status_code == status
    if status == 204:
        assert request._body == body


@pytest.mark.parametrize("stage", ("claim", "reload", "settle"))
def test_dispatch_continues_when_subscription_is_deleted_mid_batch(
    push_setup, monkeypatch, stage
):
    first = register(push_setup)
    records, issued, payload = push_setup
    other = services.register_subscription(
        issued.family,
        records[1].id,
        payload.model_copy(
            update={
                "browser_id": uuid4(),
                "binding_id": uuid4(),
                "endpoint": "https://fcm.googleapis.com/push/another-capability",
            }
        ),
    )
    notification = services.create_intent(
        identity=f"reply:{uuid4()}",
        kind="reply_completed",
        conversation=records[-1].conversation,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    doomed = PushDelivery.objects.get(notification=notification, subscription=first)
    survivor = PushDelivery.objects.get(
        notification=notification, subscription_id=other.subscription_id
    )
    now = timezone.now()
    PushDelivery.objects.filter(pk=doomed.id).update(
        next_attempt_at=now - timedelta(seconds=2)
    )
    PushDelivery.objects.filter(pk=survivor.id).update(
        next_attempt_at=now - timedelta(seconds=1)
    )
    claim = services.claim_delivery
    sends = []

    def raced_claim(delivery_id, **kwargs):
        if delivery_id == doomed.id and stage == "claim":
            first.delete()
        lease = claim(delivery_id, **kwargs)
        if delivery_id == doomed.id and stage == "reload":
            first.delete()
        return lease

    def provider(*args):
        sends.append(args)
        if len(sends) == 1 and stage == "settle":
            first.delete()
        return 201, None, ""

    monkeypatch.setattr(services, "claim_delivery", raced_claim)
    monkeypatch.setattr(services, "send_push", provider)
    assert services.dispatch_push(now=now) == (2 if stage == "settle" else 1)
    survivor.refresh_from_db()
    assert survivor.state == "sent"
