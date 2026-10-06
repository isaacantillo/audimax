import uuid

from app.schemas.base import ApiModel


class LoginRequest(ApiModel):
    username: str
    password: str


class UserOut(ApiModel):
    id: uuid.UUID
    username: str


class ApiTokenRequest(ApiModel):
    name: str  # e.g. "iPhone Shortcut"


class ApiTokenResponse(ApiModel):
    name: str
    token: str  # shown once; only its hash is stored
