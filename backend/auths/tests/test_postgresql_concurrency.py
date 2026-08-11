import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Event, Lock
from urllib.parse import parse_qs, urlparse

import pytest
from django.db import close_old_connections, connection
from django.test import override_settings
from django.utils import timezone
from PIL import Image

from auths.exceptions import AvatarConflict, FlowReplay, SessionInvalid
from auths.models import (
    Actor,
    AvatarAsset,
    ExternalIdentity,
    FlowPurpose,
    RefreshToken,
    SessionFamily,
)
from auths.providers.base import ProviderKey, VerifiedIdentity
from auths.services.accounts import resolve_or_create_actor
from auths.services.avatars import (
    cleanup_avatar_assets,
    complete_avatar_upload,
    prepare_avatar_upload,
)
from auths.services.flows import begin_auth_flow, complete_auth_flow
from auths.services.sessions import issue_session, rotate_refresh
from auths.storage.avatars import InMemoryAvatarObjectStore, set_avatar_store
from workspaces.models import Membership, Workspace


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_same_subject_converges_under_postgresql_race():
    if connection.vendor != "postgresql":
        pytest.skip("row-lock race requires PostgreSQL")

    identity = VerifiedIdentity(provider="fake", subject="postgres-race")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: resolve_or_create_actor(identity), range(2)))
    assert results[0].actor.pk == results[1].actor.pk
    assert Actor.objects.filter(pk=results[0].actor.pk).count() == 1
    assert Workspace.objects.filter(owner=results[0].actor).count() == 1
    assert Membership.objects.filter(actor=results[0].actor).count() == 1


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_same_refresh_token_converges_and_revokes_family_under_postgresql_race():
    if connection.vendor != "postgresql":
        pytest.skip("row-lock race requires PostgreSQL")

    actor = resolve_or_create_actor(
        VerifiedIdentity(provider="fake", subject="postgres-refresh-race")
    ).actor
    issued = issue_session(actor)

    def rotate_once():
        close_old_connections()
        try:
            return "rotated", rotate_refresh(issued.refresh_token).family.public_id
        except SessionInvalid:
            return "rejected", None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result() for future in [pool.submit(rotate_once) for _ in range(2)]
        ]

    assert sorted(result[0] for result in results) == ["rejected", "rotated"]
    family = SessionFamily.objects.get(pk=issued.family.pk)
    assert family.revoked_at is not None
    assert family.revoke_reason == "refresh_reuse"
    assert RefreshToken.objects.filter(family=family, used_at__isnull=True).count() == 1


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True)
def test_same_callback_state_is_consumed_once_under_postgresql_race():
    if connection.vendor != "postgresql":
        pytest.skip("row-lock race requires PostgreSQL")

    start = begin_auth_flow(
        provider=ProviderKey.FAKE,
        purpose=FlowPurpose.SIGN_IN,
        redirect_to="/app",
        browser_binding=b"postgres-browser",
    )
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]

    def complete_once():
        close_old_connections()
        try:
            completed = complete_auth_flow(
                provider=ProviderKey.FAKE,
                state=state,
                code="fake:postgres-callback-race",
                browser_binding=b"postgres-browser",
                flow_cookie=start.flow_cookie,
            )
            return "completed", completed.actor.pk
        except FlowReplay:
            return "replayed", None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result() for future in [pool.submit(complete_once) for _ in range(2)]
        ]

    assert sorted(result[0] for result in results) == ["completed", "replayed"]
    identity = ExternalIdentity.objects.get(subject="postgres-callback-race")
    assert Actor.objects.filter(pk=identity.actor_id).count() == 1
    assert Workspace.objects.filter(owner_id=identity.actor_id).count() == 1
    assert Membership.objects.filter(actor_id=identity.actor_id).count() == 1


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_avatar_completion_and_cleanup_converge_under_postgresql_race():
    if connection.vendor != "postgresql":
        pytest.skip("row-lock race requires PostgreSQL")

    actor = resolve_or_create_actor(
        VerifiedIdentity(provider="fake", subject="postgres-avatar-race")
    ).actor
    copied = Event()
    resume = Event()

    class BlockingPromotionStore(InMemoryAvatarObjectStore):
        def put_verified(self, *, key, data, content_type):
            super().put_verified(key=key, data=data, content_type=content_type)
            copied.set()
            assert resume.wait(timeout=10)

    store = BlockingPromotionStore()
    set_avatar_store(store)
    output = BytesIO()
    Image.new("RGB", (2, 2), (1, 2, 3)).save(output, "PNG")
    data = output.getvalue()
    prepared = prepare_avatar_upload(
        actor=actor,
        content_type="image/png",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    store.put(prepared.asset.object_key, data, "image/png")
    AvatarAsset.objects.filter(pk=prepared.asset.pk).update(
        eligible_at=timezone.now() - timedelta(seconds=1)
    )

    def complete():
        close_old_connections()
        try:
            complete_avatar_upload(actor=actor, asset_id=prepared.asset.public_id)
            return "completed"
        except AvatarConflict:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        completion = pool.submit(complete)
        assert copied.wait(timeout=10)
        cleanup = pool.submit(cleanup_avatar_assets, batch_size=1)
        try:
            cleanup_result = cleanup.result(timeout=10)
        finally:
            resume.set()
        completion_result = completion.result(timeout=10)

    assert cleanup_result == (1, 0)
    assert completion_result == "conflict"
    assert not AvatarAsset.objects.filter(pk=prepared.asset.pk).exists()


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_same_avatar_completion_is_idempotent_under_postgresql_race():
    if connection.vendor != "postgresql":
        pytest.skip("row-lock race requires PostgreSQL")

    actor = resolve_or_create_actor(
        VerifiedIdentity(provider="fake", subject="postgres-avatar-idempotency")
    ).actor
    both_readers_started = Event()
    staging_deleted = Event()
    counter_lock = Lock()

    class SequencedReadStore(InMemoryAvatarObjectStore):
        head_calls = 0

        def head(self, *, key):
            with counter_lock:
                self.head_calls += 1
                call_number = self.head_calls
            if call_number == 1:
                assert both_readers_started.wait(timeout=10)
            elif call_number == 2:
                both_readers_started.set()
                assert staging_deleted.wait(timeout=10)
            return super().head(key=key)

        def delete(self, *, key):
            super().delete(key=key)
            if key.startswith("staging/"):
                staging_deleted.set()

    store = SequencedReadStore()
    set_avatar_store(store)
    output = BytesIO()
    Image.new("RGB", (2, 2), (3, 2, 1)).save(output, "PNG")
    data = output.getvalue()
    prepared = prepare_avatar_upload(
        actor=actor,
        content_type="image/png",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    store.put(prepared.asset.object_key, data, "image/png")

    def complete_once():
        close_old_connections()
        try:
            ready = complete_avatar_upload(
                actor=actor, asset_id=prepared.asset.public_id
            )
            return ready.asset.object_key
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=15)
            for future in [pool.submit(complete_once) for _ in range(2)]
        ]

    asset = AvatarAsset.objects.get(pk=prepared.asset.pk)
    assert asset.status == "ready"
    assert results == [asset.object_key, asset.object_key]
