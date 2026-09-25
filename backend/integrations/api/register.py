from ninja_extra import NinjaExtraAPI

from integrations.api.controllers import GmailCallbackController, GmailController


def register(api: NinjaExtraAPI) -> None:
    api.register_controllers(GmailController, GmailCallbackController)
