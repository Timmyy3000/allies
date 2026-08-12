from ninja_extra import NinjaExtraAPI

from .controllers import WorkspaceController


def register(api: NinjaExtraAPI) -> None:
    api.register_controllers(WorkspaceController)
