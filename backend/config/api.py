from ninja_extra import NinjaExtraAPI

from auths.api.register import register as register_auths_api
from workspaces.api.register import register as register_workspaces_api

api = NinjaExtraAPI(
    title="Allies Cloud API",
    version="0.1.0",
)


def register_all_apis() -> None:
    register_auths_api(api)
    register_workspaces_api(api)


register_all_apis()
