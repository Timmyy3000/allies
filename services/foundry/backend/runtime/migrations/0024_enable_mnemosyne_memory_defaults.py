# ruff: noqa: RUF012

import hashlib
import json

from django.db import migrations

_LEGACY_MEMORY = {
    "provider": "allies_mnemosyne",
    "mode": "context_only",
    "policy_version": "allies-mnemosyne-v1",
    "tools": [],
    "profile_isolation": True,
    "sync_roles": [],
}
_DEFAULT_MEMORY = {
    **_LEGACY_MEMORY,
    "mode": "narrow_tools",
    "tools": [
        "mnemosyne_forget",
        "mnemosyne_forget_canonical",
        "mnemosyne_invalidate",
        "mnemosyne_recall",
        "mnemosyne_recall_canonical",
        "mnemosyne_remember",
        "mnemosyne_remember_canonical",
        "mnemosyne_update",
    ],
}


def _fingerprint(profile, seed, memory):
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
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(b"allies-profile-seed-v2\0" + encoded).hexdigest()


def enable_mnemosyne_memory_defaults(apps, _schema_editor):
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
        if {
            "provider": seed["memory_provider"],
            "mode": seed["memory_mode"],
            "policy_version": seed["memory_policy_version"],
            "tools": seed["memory_tool_allowlist"],
            "profile_isolation": seed["memory_profile_isolation"],
            "sync_roles": seed["memory_sync_roles"],
        } != _LEGACY_MEMORY or profile.seed_fingerprint != _fingerprint(
            profile, seed, _LEGACY_MEMORY
        ):
            continue
        upgraded_seed = dict(seed)
        upgraded_seed.update(
            {
                "memory_mode": _DEFAULT_MEMORY["mode"],
                "memory_tool_allowlist": _DEFAULT_MEMORY["tools"],
            }
        )
        profile.seed_payload = upgraded_seed
        profile.seed_fingerprint = _fingerprint(profile, upgraded_seed, _DEFAULT_MEMORY)
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
    dependencies = [("runtime", "0023_merge_0020_routine_run_session_0022_approval_request")]

    operations = [migrations.RunPython(enable_mnemosyne_memory_defaults, migrations.RunPython.noop)]
