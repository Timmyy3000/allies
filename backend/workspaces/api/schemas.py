from uuid import UUID

from ninja import Schema


class WorkspaceContextResponse(Schema):
    id: UUID
    name: str
    role: str
    capabilities: list[str]
