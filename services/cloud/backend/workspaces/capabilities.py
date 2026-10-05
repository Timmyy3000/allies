"""Closed owner capability map for AUTH-001."""

from __future__ import annotations

from enum import StrEnum


class Capability(StrEnum):
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_WRITE = "workspace.write"
    PROFILE_READ = "profile.read"
    PROFILE_WRITE = "profile.write"
    AVATAR_READ = "avatar.read"
    AVATAR_WRITE = "avatar.write"


OWNER_CAPABILITIES = frozenset(Capability)
CAPABILITIES_BY_ROLE = {"owner": OWNER_CAPABILITIES}


def capabilities_for_role(role: str) -> tuple[str, ...]:
    return tuple(sorted(str(item) for item in CAPABILITIES_BY_ROLE.get(role, ())))
