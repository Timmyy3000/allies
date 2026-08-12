from ninja_extra import NinjaExtraAPI

from .authentication import AuthenticationController
from .avatar import AvatarController
from .identities import IdentityController
from .profile import ProfileController
from .sessions import SessionController


def register(api: NinjaExtraAPI) -> None:
    """Register capability-owned controllers without changing public paths."""

    api.register_controllers(
        AuthenticationController,
        SessionController,
        IdentityController,
        ProfileController,
        AvatarController,
    )
