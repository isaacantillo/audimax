import uuid

from pydantic import BaseModel

class MindMapNode(BaseModel):
    id: uuid.UUID
    label: str
    summary: str

class MindMapEdge(BaseModel):
    source: str
    target: str
    relation: str

class MindMapResponse(BaseModel):
    nodes: list[MindMapNode]
    edges: list[MindMapEdge]