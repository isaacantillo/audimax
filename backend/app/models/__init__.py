# Import every model so Alembic's autogenerate sees them on Base.metadata.
from app.models.user import AuthSession, User

__all__ = ["AuthSession", "User"]
