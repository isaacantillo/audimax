import uuid

from app.schemas.base import ApiModel


class MindMapNode(ApiModel):
    id: uuid.UUID
    label: str
    summary: str

class MindMapEdge(ApiModel):
    source: str
    target: str
    relation: str

class MindMapResponse(ApiModel):
    nodes: list[MindMapNode]
    edges: list[MindMapEdge]