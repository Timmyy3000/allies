from ninja_extra import NinjaExtraAPI

api = NinjaExtraAPI(
    title="Allies Foundry API",
    version="0.1.0",
)

from runtime.api.register import register

register(api)
