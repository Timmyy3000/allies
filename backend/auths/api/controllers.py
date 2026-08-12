"""Compatibility exports for the split authentication controllers.

New routes are implemented in capability-owned modules.  This module remains
as a narrow import surface for callers that imported the previous controller
helpers, while the registrar intentionally registers each module separately.
"""

from .authentication import AuthenticationController
from .avatar import AvatarController
from .common import (
    _client_identity,
    _domain_status,
    _origin_allowed,
    _require_origin,
)
from .identities import IdentityController
from .profile import ProfileController
from .sessions import SessionController

AuthController = AuthenticationController

__all__ = [
    "AuthController",
    "AuthenticationController",
    "AvatarController",
    "IdentityController",
    "ProfileController",
    "SessionController",
    "_client_identity",
    "_domain_status",
    "_origin_allowed",
    "_require_origin",
]
