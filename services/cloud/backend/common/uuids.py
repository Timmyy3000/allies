from typing import Annotated
from uuid import UUID

from pydantic import BeforeValidator


def canonical_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise TypeError("identifier must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("identifier must be a canonical UUID") from exc
    if str(parsed) != value:
        raise ValueError("identifier must be a canonical UUID")
    return parsed


CanonicalUUID = Annotated[UUID, BeforeValidator(canonical_uuid)]
