# ruff: noqa: RUF012

import hashlib
import json

from django.db import migrations

_MEMORY_SEED_FIELDS = (
    "memory_provider",
    "memory_mode",
    "memory_policy_version",
    "memory_tool_allowlist",
    "memory_profile_isolation",
    "memory_sync_roles",
)


def _digest(prefix, payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(prefix + encoded).hexdigest()


def add_memory_policy(apps, _schema_editor):
    runtime_profile = apps.get_model("runtime", "RuntimeProfile")
    for profile in runtime_profile.objects.iterator():
        seed = profile.seed_payload
        if not isinstance(seed, dict):
            continue
        required = {
            "version",
            "personality",
            "provider",
            "model",
            "first_chat_instruction",
            "first_chat_instruction_version",
            "credential_refs",
        }
        if not required.issubset(seed) or not isinstance(seed["credential_refs"], dict):
            continue
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
        }
        legacy = _digest(b"allies-profile-seed-v1\0", canonical)
        if profile.seed_fingerprint != legacy:
            continue
        memory = {
            "provider": "allies_mnemosyne",
            "mode": "context_only",
            "policy_version": "allies-mnemosyne-v1",
            "tools": [],
            "profile_isolation": True,
            "sync_roles": [],
        }
        upgraded_seed = dict(seed)
        upgraded_seed.update(
            {
                "memory_provider": memory["provider"],
                "memory_mode": memory["mode"],
                "memory_policy_version": memory["policy_version"],
                "memory_tool_allowlist": [],
                "memory_profile_isolation": True,
                "memory_sync_roles": [],
            }
        )
        canonical["memory"] = memory
        profile.seed_payload = upgraded_seed
        profile.seed_fingerprint = _digest(b"allies-profile-seed-v2\0", canonical)
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


def remove_memory_policy(apps, _schema_editor):
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
            *_MEMORY_SEED_FIELDS,
        }
        if (
            not isinstance(seed, dict)
            or not required.issubset(seed)
            or not isinstance(seed["credential_refs"], dict)
        ):
            continue
        memory = {
            "provider": seed["memory_provider"],
            "mode": seed["memory_mode"],
            "policy_version": seed["memory_policy_version"],
            "tools": seed["memory_tool_allowlist"],
            "profile_isolation": seed["memory_profile_isolation"],
            "sync_roles": seed["memory_sync_roles"],
        }
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
            "memory": memory,
        }
        if profile.seed_fingerprint != _digest(b"allies-profile-seed-v2\0", canonical):
            continue
        legacy_seed = dict(seed)
        for field in _MEMORY_SEED_FIELDS:
            legacy_seed.pop(field, None)
        canonical.pop("memory")
        profile.seed_payload = legacy_seed
        profile.seed_fingerprint = _digest(b"allies-profile-seed-v1\0", canonical)
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
    dependencies = [
        ("runtime", "0013_workspace_activation_claim"),
    ]

    operations = [
        migrations.RunPython(add_memory_policy, remove_memory_policy),
    ]
