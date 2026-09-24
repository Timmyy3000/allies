import hashlib
import json
from typing import ClassVar

from django.db import migrations

# Historical record of backend DEFAULT_COMPRESSION_THRESHOLD_TOKENS at the
# time of this migration. Do not import the live constant: rows upgraded here
# must keep the value this migration wrote even if the default moves later.
_COMPRESSION_THRESHOLD_TOKENS = 100_000


def _fingerprint(profile, seed, compression):
    canonical = {
        "schema_version": seed["version"],
        "foundry_profile_id": str(profile.id),
        "hermes_profile_key": profile.hermes_profile_key,
        "identity": {"ally_name": profile.ally_ref},
        "personality": seed["personality"],
        "first_chat_version": seed["first_chat_instruction_version"],
        "first_chat_instruction": seed["first_chat_instruction"],
        "model": {
            "provider": seed["provider"],
            "default": seed["model"],
            "base_url": seed.get("base_url"),
        },
        "credential_refs": dict(sorted(seed["credential_refs"].items())),
        "memory": {
            "provider": seed["memory_provider"],
            "mode": seed["memory_mode"],
            "policy_version": seed["memory_policy_version"],
            "tools": seed["memory_tool_allowlist"],
            "profile_isolation": seed["memory_profile_isolation"],
            "sync_roles": seed["memory_sync_roles"],
        },
    }
    if compression is not None:
        canonical["compression"] = {"threshold_tokens": compression}
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(b"allies-profile-seed-v2\0" + encoded).hexdigest()


def enable_compression_threshold_defaults(apps, _schema_editor):
    runtime_profile = apps.get_model("runtime", "RuntimeProfile")
    for profile in runtime_profile.objects.iterator():
        seed = profile.seed_payload
        required = {
            "version",
            "personality",
            "provider",
            "model",
            "first_chat_instruction",
            "first_chat_instruction_version",
            "credential_refs",
            "memory_provider",
            "memory_mode",
            "memory_policy_version",
            "memory_tool_allowlist",
            "memory_profile_isolation",
            "memory_sync_roles",
        }
        if (
            not isinstance(seed, dict)
            or not required.issubset(seed)
            or not isinstance(seed["credential_refs"], dict)
        ):
            continue
        if seed.get(
            "compression_threshold_tokens"
        ) == _COMPRESSION_THRESHOLD_TOKENS and profile.seed_fingerprint == _fingerprint(
            profile, seed, _COMPRESSION_THRESHOLD_TOKENS
        ):
            continue
        if (
            "compression_threshold_tokens" in seed
            or profile.seed_fingerprint != _fingerprint(profile, seed, None)
        ):
            continue
        upgraded_seed = dict(seed)
        upgraded_seed["compression_threshold_tokens"] = _COMPRESSION_THRESHOLD_TOKENS
        profile.seed_payload = upgraded_seed
        profile.seed_fingerprint = _fingerprint(
            profile, upgraded_seed, _COMPRESSION_THRESHOLD_TOKENS
        )
        profile.materialized_generation = 0
        profile.materialization_operation_id = None
        profile.materialization_request_digest = ""
        profile.materialization_receipt_id = None
        profile.materialization_result_code = ""
        profile.save(
            update_fields=[
                "seed_payload",
                "seed_fingerprint",
                "materialized_generation",
                "materialization_operation_id",
                "materialization_request_digest",
                "materialization_receipt_id",
                "materialization_result_code",
                "updated_at",
            ]
        )


def remove_compression_threshold_defaults(apps, _schema_editor):
    runtime_profile = apps.get_model("runtime", "RuntimeProfile")
    for profile in runtime_profile.objects.iterator():
        seed = profile.seed_payload
        required = {
            "version",
            "personality",
            "provider",
            "model",
            "first_chat_instruction",
            "first_chat_instruction_version",
            "credential_refs",
            "memory_provider",
            "memory_mode",
            "memory_policy_version",
            "memory_tool_allowlist",
            "memory_profile_isolation",
            "memory_sync_roles",
        }
        if (
            not isinstance(seed, dict)
            or not required.issubset(seed)
            or not isinstance(seed["credential_refs"], dict)
            or seed.get("compression_threshold_tokens")
            != _COMPRESSION_THRESHOLD_TOKENS
        ):
            continue
        downgraded_seed = dict(seed)
        del downgraded_seed["compression_threshold_tokens"]
        if profile.seed_fingerprint != _fingerprint(
            profile, downgraded_seed, _COMPRESSION_THRESHOLD_TOKENS
        ):
            continue
        profile.seed_payload = downgraded_seed
        profile.seed_fingerprint = _fingerprint(profile, downgraded_seed, None)
        profile.materialized_generation = 0
        profile.materialization_operation_id = None
        profile.materialization_request_digest = ""
        profile.materialization_receipt_id = None
        profile.materialization_result_code = ""
        profile.save(
            update_fields=[
                "seed_payload",
                "seed_fingerprint",
                "materialized_generation",
                "materialization_operation_id",
                "materialization_request_digest",
                "materialization_receipt_id",
                "materialization_result_code",
                "updated_at",
            ]
        )


class Migration(migrations.Migration):
    dependencies: ClassVar = [
        ("runtime", "0029_sleeping_ready_pool"),
    ]

    operations: ClassVar = [
        migrations.RunPython(
            enable_compression_threshold_defaults,
            remove_compression_threshold_defaults,
        )
    ]
