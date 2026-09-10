from ninja_extra import NinjaExtraAPI

from files.api.controllers import (
    AcceptedFileController,
    FileAdmissionController,
    FilePublicationController,
    OwnerPublicationController,
    PrivateFileController,
)


def register(api: NinjaExtraAPI) -> None:
    api.register_controllers(FileAdmissionController)
    api.register_controllers(AcceptedFileController)
    api.register_controllers(FilePublicationController)
    api.register_controllers(OwnerPublicationController)
    api.register_controllers(PrivateFileController)
