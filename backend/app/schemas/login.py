import uuid

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    username: str


class ApiTokenRequest(BaseModel):
    name: str  # e.g. "iPhone Shortcut"


class ApiTokenResponse(BaseModel):
    name: str
    token: str  # shown once; only its hash is stored
