from ninja_extra import NinjaExtraAPI

from .controllers import WaitlistController


def register(api: NinjaExtraAPI) -> None:
    api.register_controllers(WaitlistController)
