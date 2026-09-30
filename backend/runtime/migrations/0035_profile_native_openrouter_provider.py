import hashlib
import json
from typing import ClassVar

from django.db import migrations

MODEL = "openai/gpt-6-luna"
BASE_URL = "https://openrouter.ai/api/v1"
CREDENTIAL_REF = "file:///run/secrets/openai-api-key"
OLD_PROVIDER = "openai-api"
OLD_CREDENTIAL_REFS = {"OPENAI_API_KEY": CREDENTIAL_REF}
NEW_PROVIDER = "openrouter"
NEW_CREDENTIAL_REFS = {"OPENROUTER_API_KEY": CREDENTIAL_REF}


def _fingerprint(profile, seed):
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
        "compression": {"threshold_tokens": seed["compression_threshold_tokens"]},
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(b"allies-profile-seed-v2\0" + encoded).hexdigest()


def _reset_materialization(profile):
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


def _matches(seed, provider, credential_refs):
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
        "compression_threshold_tokens",
    }
    return (
        isinstance(seed, dict)
        and required.issubset(seed)
        and seed["provider"] == provider
        and seed["model"] == MODEL
        and seed.get("base_url") == BASE_URL
        and seed["credential_refs"] == credential_refs
    )


def _switch(apps, provider_from, refs_from, provider_to, refs_to):
    runtime_profile = apps.get_model("runtime", "RuntimeProfile")
    for profile in runtime_profile.objects.iterator():
        seed = profile.seed_payload
        if not _matches(seed, provider_from, refs_from):
            continue
        if profile.seed_fingerprint != _fingerprint(profile, seed):
            continue
        upgraded_seed = dict(seed)
        upgraded_seed["provider"] = provider_to
        upgraded_seed["credential_refs"] = dict(refs_to)
        profile.seed_payload = upgraded_seed
        profile.seed_fingerprint = _fingerprint(profile, upgraded_seed)
        _reset_materialization(profile)


def switch_to_native_openrouter(apps, _schema_editor):
    _switch(apps, OLD_PROVIDER, OLD_CREDENTIAL_REFS, NEW_PROVIDER, NEW_CREDENTIAL_REFS)


def switch_back_to_openai_api(apps, _schema_editor):
    _switch(apps, NEW_PROVIDER, NEW_CREDENTIAL_REFS, OLD_PROVIDER, OLD_CREDENTIAL_REFS)


class Migration(migrations.Migration):
    dependencies: ClassVar = [
        ("runtime", "0034_profile_default_model_openrouter"),
    ]

    operations: ClassVar = [
        migrations.RunPython(
            switch_to_native_openrouter,
            switch_back_to_openai_api,
        )
    ]
