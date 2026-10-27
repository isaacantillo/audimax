import datetime
import uuid

from app.schemas.base import ApiModel


class LoginRequest(ApiModel):
    username: str
    password: str


class UserOut(ApiModel):
    id: uuid.UUID
    username: str
    is_admin: bool


class SessionOut(ApiModel):
    """A signed-in browser or an API token, and where it is used from."""

    id: uuid.UUID
    username: str
    kind: str  # "browser" | "api"
    name: str | None  # an API token's name
    device: str  # e.g. "Mobile Safari on iOS · iPhone"
    ip: str | None
    location: str | None
    created_at: datetime.datetime
    last_seen_at: datetime.datetime | None
    current: bool  # the session making this request


class ApiTokenRequest(ApiModel):
    name: str  # e.g. "iPhone Shortcut"


class ApiTokenResponse(ApiModel):
    name: str
    token: str  # shown once; only its hash is stored
