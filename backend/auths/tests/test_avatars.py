import hashlib
import io
from datetime import timedelta

import pytest
from django.utils import timezone
from PIL import Image

from auths.exceptions import (
    AvatarConflict,
    AvatarError,
    AvatarNotFound,
    AvatarStorageUnavailable,
    ValidationError,
)
from auths.models import AvatarAsset, AvatarStatus, UserProfile
from auths.providers.base import VerifiedIdentity
from auths.services.accounts import resolve_or_create_user
from auths.services.avatars import (
    cleanup_avatar_assets,
    complete_avatar_upload,
    delete_current_avatar,
    prepare_avatar_upload,
    signed_avatar_read,
)
from auths.storage.avatars import InMemoryAvatarObjectStore, set_avatar_store


def _image(
    format_name: str = "PNG", size: tuple[int, int] = (12, 10)
) -> tuple[bytes, str]:
    output = io.BytesIO()
    Image.new("RGB", size, (120, 90, 30)).save(output, format_name)
    return output.getvalue(), {"PNG": "image/png", "JPEG": "image/jpeg"}[format_name]


@pytest.fixture
def avatar_context():
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="avatar-test")
    ).user
    store = InMemoryAvatarObjectStore()
    set_avatar_store(store)
    return user, store


@pytest.mark.django_db
def test_avatar_prepare_complete_replace_read_and_delete(avatar_context):
    user, store = avatar_context
    first_data, content_type = _image()
    first = prepare_avatar_upload(
        user=user,
        content_type=content_type,
        size=len(first_data),
        sha256=hashlib.sha256(first_data).hexdigest(),
    )
    store.put(first.asset.object_key, first_data, content_type)
    ready = complete_avatar_upload(user=user, asset_id=first.asset.id)
    assert ready.asset.status == AvatarStatus.READY
    assert ready.asset.width == 12
    returned_asset, url, expires = signed_avatar_read(user=user)

    assert returned_asset == ready.asset
    assert url.startswith("memory://get/")
    assert expires > timezone.now()
    second_data, second_type = _image("JPEG")
    second = prepare_avatar_upload(
        user=user,
        content_type=second_type,
        size=len(second_data),
        sha256=hashlib.sha256(second_data).hexdigest(),
    )
    store.put(second.asset.object_key, second_data, second_type)
    complete_avatar_upload(user=user, asset_id=second.asset.id)
    assert AvatarAsset.objects.get(pk=first.asset.pk).status == AvatarStatus.REPLACED
    delete_current_avatar(user)
    with pytest.raises(AvatarNotFound):
        signed_avatar_read(user=user)


@pytest.mark.django_db
def test_completed_avatar_is_immune_to_staging_url_reuse(avatar_context):
    user, store = avatar_context
    original, content_type = _image()
    prepared = prepare_avatar_upload(
        user=user,
        content_type=content_type,
        size=len(original),
        sha256=hashlib.sha256(original).hexdigest(),
    )
    staging_key = prepared.asset.object_key
    store.put(staging_key, original, content_type)

    completed = complete_avatar_upload(user=user, asset_id=prepared.asset.id)
    store.put(staging_key, b"attacker-overwrite", content_type)

    completed.asset.refresh_from_db()
    assert completed.asset.object_key == (
        f"{staging_key.removeprefix('staging/')}.verified"
    )
    assert (
        b"".join(
            store.stream_get(key=completed.asset.object_key, max_bytes=len(original))
        )
        == original
    )


@pytest.mark.django_db
def test_avatar_promotion_conflict_removes_uncommitted_verified_object(
    avatar_context, monkeypatch
):
    user, store = avatar_context
    data, content_type = _image()
    prepared = prepare_avatar_upload(
        user=user,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    store.put(prepared.asset.object_key, data, content_type)
    original_put_verified = store.put_verified

    def change_state_after_promotion(**kwargs):
        original_put_verified(**kwargs)
        AvatarAsset.objects.filter(pk=prepared.asset.pk).update(
            status=AvatarStatus.REJECTED
        )

    monkeypatch.setattr(store, "put_verified", change_state_after_promotion)
    verified_key = f"{prepared.asset.object_key.removeprefix('staging/')}.verified"

    with pytest.raises(AvatarConflict):
        complete_avatar_upload(user=user, asset_id=prepared.asset.id)
    with pytest.raises(KeyError):
        store.head(key=verified_key)


@pytest.mark.django_db
def test_avatar_completion_reloads_ready_state_after_staging_disappears(
    avatar_context, monkeypatch
):
    user, _store = avatar_context
    data, content_type = _image()
    prepared = prepare_avatar_upload(
        user=user,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    final_key = f"{prepared.asset.object_key.removeprefix('staging/')}.verified"

    def concurrently_promoted(asset):
        AvatarAsset.objects.filter(pk=asset.pk).update(
            status=AvatarStatus.READY, object_key=final_key
        )
        raise AvatarNotFound("staging object disappeared")

    monkeypatch.setattr("auths.services.avatars._read_object", concurrently_promoted)

    ready = complete_avatar_upload(user=user, asset_id=prepared.asset.id)
    assert ready.asset.status == AvatarStatus.READY
    assert ready.asset.object_key == final_key


@pytest.mark.django_db
def test_avatar_prepare_does_not_leave_row_when_signing_fails(
    avatar_context, monkeypatch
):
    user, store = avatar_context
    data, content_type = _image()
    before = AvatarAsset.objects.count()
    monkeypatch.setattr(
        store,
        "sign_put",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("signing unavailable")),
    )

    with pytest.raises(AvatarStorageUnavailable, match="signing unavailable"):
        prepare_avatar_upload(
            user=user,
            content_type=content_type,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
    assert AvatarAsset.objects.count() == before


@pytest.mark.django_db
def test_avatar_storage_failures_are_normalized(avatar_context, monkeypatch):
    user, store = avatar_context
    data, content_type = _image()
    prepared = prepare_avatar_upload(
        user=user,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    store.put(prepared.asset.object_key, data, content_type)
    monkeypatch.setattr(
        store,
        "put_verified",
        lambda **kwargs: (_ for _ in ()).throw(OSError("R2 unavailable")),
    )
    with pytest.raises(AvatarStorageUnavailable, match="promotion"):
        complete_avatar_upload(user=user, asset_id=prepared.asset.id)

    monkeypatch.undo()
    set_avatar_store(store)
    ready = complete_avatar_upload(user=user, asset_id=prepared.asset.id)
    monkeypatch.setattr(
        store,
        "sign_get",
        lambda **kwargs: (_ for _ in ()).throw(OSError("R2 unavailable")),
    )
    with pytest.raises(AvatarStorageUnavailable, match="read"):
        signed_avatar_read(user=user)
    assert ready.asset.status == AvatarStatus.READY


@pytest.mark.django_db
def test_cross_user_avatar_pointer_fails_closed(avatar_context):
    user, store = avatar_context
    other = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="avatar-other-user")
    ).user
    data, content_type = _image()
    other_upload = prepare_avatar_upload(
        user=other,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    store.put(other_upload.asset.object_key, data, content_type)
    other_ready = complete_avatar_upload(
        user=other, asset_id=other_upload.asset.id
    ).asset
    UserProfile.objects.filter(user=user).update(current_avatar=other_ready)

    with pytest.raises(AvatarNotFound):
        signed_avatar_read(user=user)
    with pytest.raises(AvatarConflict):
        delete_current_avatar(user)

    user_upload = prepare_avatar_upload(
        user=user,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    store.put(user_upload.asset.object_key, data, content_type)
    with pytest.raises(AvatarConflict):
        complete_avatar_upload(user=user, asset_id=user_upload.asset.id)
    other_ready.refresh_from_db()
    assert other_ready.status == AvatarStatus.READY
    assert store.head(key=other_ready.object_key).size == len(data)


@pytest.mark.django_db
def test_avatar_rejects_bad_objects_and_foreign_assets(avatar_context):
    user, store = avatar_context
    data, content_type = _image()
    pending = prepare_avatar_upload(
        user=user,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    store.put(pending.asset.object_key, b"not-an-image", content_type)
    with pytest.raises(AvatarError):
        complete_avatar_upload(user=user, asset_id=pending.asset.id)
    with pytest.raises(AvatarNotFound):
        complete_avatar_upload(
            user=user, asset_id="00000000-0000-4000-8000-000000000000"
        )
    with pytest.raises(ValidationError):
        prepare_avatar_upload(
            user=user, content_type="text/plain", size=1, sha256="0" * 64
        )
    with pytest.raises(ValidationError):
        prepare_avatar_upload(
            user=user, content_type=content_type, size=1, sha256="bad"
        )


@pytest.mark.django_db
def test_avatar_cleanup_claims_expired_pending_and_records_failures(avatar_context):
    user, store = avatar_context
    asset = AvatarAsset.objects.create(
        user=user,
        object_key="expired-key",
        status=AvatarStatus.PENDING,
        expected_content_type="image/png",
        expected_size=1,
        expected_sha256="0" * 64,
        eligible_at=timezone.now() - timedelta(hours=1),
    )
    store.put(asset.object_key, b"x", "image/png")
    deleted, failed = cleanup_avatar_assets(batch_size=1)
    assert (deleted, failed) == (1, 0)
    assert not AvatarAsset.objects.filter(pk=asset.pk).exists()


@pytest.mark.django_db
def test_avatar_cleanup_rechecks_status_after_candidate_selection(
    avatar_context, monkeypatch
):
    user, store = avatar_context
    asset = AvatarAsset.objects.create(
        user=user,
        object_key="staging/users/test/avatar-race",
        status=AvatarStatus.PENDING,
        expected_content_type="image/png",
        expected_size=1,
        expected_sha256="0" * 64,
        eligible_at=timezone.now() - timedelta(hours=1),
    )
    store.put(asset.object_key, b"x", "image/png")
    original_select_for_update = AvatarAsset.objects.select_for_update

    def become_ready_before_lock(*args, **kwargs):
        AvatarAsset.objects.filter(pk=asset.pk).update(status=AvatarStatus.READY)
        return original_select_for_update(*args, **kwargs)

    monkeypatch.setattr(
        AvatarAsset.objects, "select_for_update", become_ready_before_lock
    )

    assert cleanup_avatar_assets(batch_size=1) == (0, 0)
    assert AvatarAsset.objects.filter(pk=asset.pk, status=AvatarStatus.READY).exists()
    assert store.head(key=asset.object_key).size == 1


@pytest.mark.django_db
def test_avatar_cleanup_reconciles_crash_between_copy_and_database_promotion(
    avatar_context,
):
    user, store = avatar_context
    data, content_type = _image()
    prepared = prepare_avatar_upload(
        user=user,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    staging_key = prepared.asset.object_key
    verified_key = f"{staging_key.removeprefix('staging/')}.verified"
    store.put(staging_key, data, content_type)
    store.put_verified(key=verified_key, data=data, content_type=content_type)
    AvatarAsset.objects.filter(pk=prepared.asset.pk).update(
        eligible_at=timezone.now() - timedelta(seconds=1)
    )

    assert cleanup_avatar_assets(batch_size=1) == (1, 0)
    for key in (staging_key, verified_key):
        with pytest.raises(KeyError):
            store.head(key=key)
