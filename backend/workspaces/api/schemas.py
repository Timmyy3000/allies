from ninja import Schema


class WorkspaceContextResponse(Schema):
    id: str
    name: str
    role: str
    capabilities: list[str]
