from ninja_extra import NinjaExtraAPI

from .controllers import AuthController


def register(api: NinjaExtraAPI) -> None:
    api.register_controllers(AuthController)
