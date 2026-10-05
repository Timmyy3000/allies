from ninja_extra import NinjaExtraAPI

from chat.api.controllers import ConversationController


def register(api: NinjaExtraAPI) -> None:
    api.register_controllers(ConversationController)
