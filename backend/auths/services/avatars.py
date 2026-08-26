"""Private avatar lifecycle with bounded object verification."""

from __future__ import annotations

import hashlib
import hmac
import io
import logging
import re
import secrets
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone as django_timezone

from auths.config import (
    avatar_max_bytes,
    avatar_max_dimension,
    avatar_max_pixels,
    avatar_pending_ttl_seconds,
    avatar_url_ttl_seconds,
)
from auths.exceptions import (
    AvatarConflict,
    AvatarError,
    AvatarNotFound,
    AvatarStorageUnavailable,
    ValidationError,
)
from auths.models import AvatarAsset, AvatarStatus, User, UserProfile
from auths.storage.avatars import ObjectMetadata, get_avatar_store
from common.uuids import canonical_uuid

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
STAGING_PREFIX = "staging/"
VERIFIED_SUFFIX = ".verified"
logger = logging.getLogger(__name__)


def _store():
    try:
        return get_avatar_store()
    except Exception as exc:
        raise AvatarStorageUnavailable("avatar storage unavailable") from exc


@dataclass(frozen=True)
class PreparedAvatar:
    asset: AvatarAsset
    upload_url: str
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class ReadyAvatar:
    asset: AvatarAsset
    read_url: str | None = None
    read_expires_at: datetime | None = None


def _validate_prepare(
    content_type: str, size: int, sha256: str
) -> tuple[str, int, str]:
    content_type = content_type.strip().lower() if isinstance(content_type, str) else ""
    if content_type not in ALLOWED_TYPES:
        raise ValidationError("avatar content type is not allowed")
    if not isinstance(size, int) or not 1 <= size <= avatar_max_bytes():
        raise ValidationError("avatar size is not allowed")
    if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
        raise ValidationError("avatar checksum is invalid")
    return content_type, size, sha256.lower()


def prepare_avatar_upload(
    *, user: User, content_type: str, size: int, sha256: str
) -> PreparedAvatar:
    content_type, size, sha256 = _validate_prepare(content_type, size, sha256)
    store = _store()
    now = django_timezone.now()
    expires = now + timedelta(seconds=avatar_url_ttl_seconds())
    asset_id = uuid.uuid4()
    key = (
        f"{STAGING_PREFIX}users/{user.id}/avatars/"
        f"{asset_id}/{secrets.token_urlsafe(18)}"
    )
    asset = AvatarAsset.objects.create(
        id=asset_id,
        user=user,
        object_key=key,
        status=AvatarStatus.PENDING,
        expected_content_type=content_type,
        expected_size=size,
        expected_sha256=sha256,
        eligible_at=now + timedelta(seconds=avatar_pending_ttl_seconds()),
    )
    try:
        url, headers = store.sign_put(
            key=key,
            content_type=content_type,
            size=size,
            expires_in=avatar_url_ttl_seconds(),
        )
    except Exception as exc:
        asset.delete()
        raise AvatarStorageUnavailable("avatar upload signing unavailable") from exc
    return PreparedAvatar(
        asset=asset, upload_url=url, headers=headers, expires_at=expires
    )


def _read_object(asset: AvatarAsset) -> tuple[bytes, ObjectMetadata]:
    store = _store()
    try:
        metadata = store.head(key=asset.object_key)
        if metadata.size != asset.expected_size or metadata.size > avatar_max_bytes():
            raise AvatarError("avatar object size invalid")
        if metadata.content_type.lower() != asset.expected_content_type:
            raise AvatarError("avatar object type invalid")
        chunks: list[bytes] = []
        total = 0
        for chunk in store.stream_get(
            key=asset.object_key, max_bytes=avatar_max_bytes() + 1
        ):
            if not isinstance(chunk, (bytes, bytearray)):
                raise AvatarError("avatar object malformed")
            total += len(chunk)
            if total > avatar_max_bytes():
                raise AvatarError("avatar object too large")
            chunks.append(bytes(chunk))
        data = b"".join(chunks)
    except AvatarError:
        raise
    except KeyError as exc:
        raise AvatarNotFound("avatar object unavailable") from exc
    except Exception as exc:
        raise AvatarStorageUnavailable("avatar object unavailable") from exc
    if len(data) != asset.expected_size:
        raise AvatarError("avatar object size invalid")
    digest = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(digest, asset.expected_sha256):
        raise AvatarError("avatar object checksum invalid")
    return data, metadata


def _verify_image(data: bytes, expected_type: str) -> tuple[int, int, str]:
    try:
        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                detected = (Image.MIME.get(image.format) or "").lower()
                if detected != expected_type:
                    raise AvatarError("avatar bytes type invalid")
                width, height = image.size
                if (
                    width > avatar_max_dimension()
                    or height > avatar_max_dimension()
                    or width * height > avatar_max_pixels()
                ):
                    raise AvatarError("avatar dimensions invalid")
                if getattr(image, "n_frames", 1) != 1:
                    raise AvatarError("animated avatars are not allowed")
                image.verify()
            with Image.open(io.BytesIO(data)) as decoded:
                decoded.load()
    except AvatarError:
        raise
    except Exception as exc:
        raise AvatarError("avatar bytes invalid") from exc
    return width, height, expected_type


def _verified_key_for(staging_key: str) -> str:
    relative = (
        staging_key.removeprefix(STAGING_PREFIX)
        if staging_key.startswith(STAGING_PREFIX)
        else staging_key
    )
    return f"{relative}{VERIFIED_SUFFIX}"


def _related_object_keys(object_key: str) -> tuple[str, ...]:
    if object_key.startswith(STAGING_PREFIX):
        return object_key, _verified_key_for(object_key)
    if object_key.endswith(VERIFIED_SUFFIX):
        staging = f"{STAGING_PREFIX}{object_key.removesuffix(VERIFIED_SUFFIX)}"
        return object_key, staging
    return (object_key,)


def _delete_related_objects(object_key: str) -> None:
    store = _store()
    for key in _related_object_keys(object_key):
        store.delete(key=key)


def complete_avatar_upload(*, user: User, asset_id: UUID | str) -> ReadyAvatar:
    try:
        parsed_asset_id = canonical_uuid(asset_id)
    except (TypeError, ValueError) as exc:
        raise AvatarNotFound("avatar is unavailable") from exc
    asset = AvatarAsset.objects.filter(user=user, pk=parsed_asset_id).first()
    if asset is None:
        raise AvatarNotFound("avatar is unavailable")
    if asset.status == AvatarStatus.READY:
        return ReadyAvatar(asset)
    if asset.status != AvatarStatus.PENDING:
        raise AvatarConflict("avatar state cannot be completed")
    try:
        data, metadata = _read_object(asset)
    except AvatarError:
        concurrent = AvatarAsset.objects.filter(pk=asset.pk, user=user).first()
        if concurrent is not None and concurrent.status == AvatarStatus.READY:
            return ReadyAvatar(concurrent)
        raise
    width, height, detected_type = _verify_image(data, asset.expected_content_type)
    store = _store()
    staging_key = asset.object_key
    verified_key = _verified_key_for(staging_key)
    try:
        store.put_verified(key=verified_key, data=data, content_type=detected_type)
    except Exception as exc:
        raise AvatarStorageUnavailable("avatar promotion unavailable") from exc
    try:
        with transaction.atomic():
            profile, _ = UserProfile.objects.select_for_update().get_or_create(
                user=user, defaults={"display_name": ""}
            )
            try:
                locked = AvatarAsset.objects.select_for_update().get(pk=asset.pk)
            except AvatarAsset.DoesNotExist as exc:
                raise AvatarConflict("avatar state changed") from exc
            if locked.status == AvatarStatus.READY:
                pass
            elif locked.status != AvatarStatus.PENDING or locked.user_id != user.pk:
                raise AvatarConflict("avatar state changed")
            else:
                previous = profile.current_avatar
                if previous is not None and previous.user_id != user.pk:
                    raise AvatarConflict("profile avatar ownership invalid")
                locked.object_key = verified_key
                locked.status = AvatarStatus.READY
                locked.actual_content_type = detected_type
                locked.actual_size = metadata.size
                locked.actual_sha256 = hashlib.sha256(data).hexdigest()
                locked.width = width
                locked.height = height
                locked.verified_at = django_timezone.now()
                locked.save(
                    update_fields=(
                        "object_key",
                        "status",
                        "actual_content_type",
                        "actual_size",
                        "actual_sha256",
                        "width",
                        "height",
                        "verified_at",
                    )
                )
                profile.current_avatar = locked
                profile.save(update_fields=("current_avatar", "updated_at"))
                if (
                    previous is not None
                    and previous.pk != locked.pk
                    and previous.status == AvatarStatus.READY
                ):
                    AvatarAsset.objects.filter(pk=previous.pk).update(
                        status=AvatarStatus.REPLACED,
                        eligible_at=django_timezone.now()
                        + timedelta(seconds=avatar_pending_ttl_seconds()),
                    )
    except Exception:
        promoted = AvatarAsset.objects.filter(
            pk=asset.pk, status=AvatarStatus.READY, object_key=verified_key
        ).exists()
        if not promoted:
            try:
                store.delete(key=verified_key)
            except Exception as cleanup_exc:  # noqa: BLE001 - best-effort cleanup
                logger.warning(
                    "verified avatar cleanup failed: %s",
                    type(cleanup_exc).__name__,
                )
        raise
    try:
        store.delete(key=staging_key)
    except Exception as cleanup_exc:  # noqa: BLE001 - lifecycle cleanup is external
        # Staging keys are never used for reads after promotion and the bucket
        # lifecycle removes abandoned uploads independently.
        logger.warning("avatar staging cleanup failed: %s", type(cleanup_exc).__name__)
    return ReadyAvatar(locked)


def signed_avatar_read(*, user: User) -> tuple[AvatarAsset, str, datetime]:
    profile = (
        UserProfile.objects.select_related("current_avatar").filter(user=user).first()
    )
    if (
        not profile
        or not profile.current_avatar
        or profile.current_avatar.status != AvatarStatus.READY
        or profile.current_avatar.user_id != user.pk
    ):
        raise AvatarNotFound("avatar is unavailable")
    try:
        url, expires = _store().sign_get(
            key=profile.current_avatar.object_key, expires_in=avatar_url_ttl_seconds()
        )
        return profile.current_avatar, url, expires
    except AvatarStorageUnavailable:
        raise
    except Exception as exc:
        raise AvatarStorageUnavailable("avatar read unavailable") from exc


def delete_current_avatar(user: User) -> None:
    with transaction.atomic():
        profile = (
            UserProfile.objects.select_for_update()
            .select_related("current_avatar")
            .filter(user=user)
            .first()
        )
        if not profile or profile.current_avatar is None:
            return
        if profile.current_avatar.user_id != user.pk:
            raise AvatarConflict("profile avatar ownership invalid")
        asset = AvatarAsset.objects.select_for_update().get(
            pk=profile.current_avatar.pk
        )
        profile.current_avatar = None
        profile.save(update_fields=("current_avatar", "updated_at"))
        asset.status = AvatarStatus.DELETED
        asset.eligible_at = django_timezone.now()
        asset.save(update_fields=("status", "eligible_at"))
    try:
        _delete_related_objects(asset.object_key)
    except Exception as exc:  # noqa: BLE001 - best-effort delete is reconciled by cleanup
        # The row is already non-current; bounded cleanup retries object delete.
        asset.cleanup_attempts += 1
        asset.cleanup_last_error = type(exc).__name__[:255]
        asset.save(update_fields=("cleanup_attempts", "cleanup_last_error"))


def cleanup_avatar_assets(*, batch_size: int = 100) -> tuple[int, int]:
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
        raise ValidationError("batch size is invalid")
    now = django_timezone.now()
    cleanup_statuses = (
        AvatarStatus.PENDING,
        AvatarStatus.REJECTED,
        AvatarStatus.REPLACED,
        AvatarStatus.DELETED,
    )
    rows = list(
        AvatarAsset.objects.filter(
            status__in=cleanup_statuses,
            eligible_at__lte=now,
        ).order_by("eligible_at", "pk")[:batch_size]
    )
    deleted = failed = 0
    for asset in rows:
        try:
            with transaction.atomic():
                locked = AvatarAsset.objects.select_for_update().get(pk=asset.pk)
                if locked.eligible_at is None or locked.eligible_at > now:
                    continue
                if locked.status not in cleanup_statuses:
                    continue
                if locked.status == AvatarStatus.PENDING:
                    locked.status = AvatarStatus.REJECTED
                    locked.save(update_fields=("status",))
                asset = locked
        except AvatarAsset.DoesNotExist:
            continue
        try:
            _delete_related_objects(asset.object_key)
            deleted += 1
            # Terminalize the row after the idempotent object delete so a
            # successful cleanup is not selected on every scheduler tick.
            asset.delete()
        except Exception as exc:  # noqa: BLE001 - cleanup must continue bounded batch on one object failure
            failed += 1
            asset.cleanup_attempts += 1
            asset.cleanup_last_error = type(exc).__name__[:255]
            asset.save(update_fields=("cleanup_attempts", "cleanup_last_error"))
    return deleted, failed
