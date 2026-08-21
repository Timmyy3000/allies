from ninja_extra import NinjaExtraAPI

from .authentication import AuthenticationController
from .avatar import AvatarController
from .identities import IdentityController
from .native import NativeAuthenticationController
from .profile import ProfileController
from .sessions import SessionController


def register(api: NinjaExtraAPI) -> None:
    """Register capability-owned controllers without changing public paths."""

    api.register_controllers(
        AuthenticationController,
        NativeAuthenticationController,
        SessionController,
        IdentityController,
        ProfileController,
        AvatarController,
    )
