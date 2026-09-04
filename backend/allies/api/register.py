from ninja_extra import NinjaExtraAPI

from allies.api.controllers import (
    AllyController,
    OnboardingController,
    RuntimeIntentController,
)


def register(api: NinjaExtraAPI) -> None:
    api.register_controllers(
        OnboardingController, AllyController, RuntimeIntentController
    )
