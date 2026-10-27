"""session device and location

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: remember each session's IP, browser and approximate location, and when it was last
    used. Existing sessions fill these in the next time they are used."""
    op.add_column('sessions', sa.Column('ip', sa.String(length=45), nullable=True))
    op.add_column('sessions', sa.Column('user_agent', sa.String(length=500), nullable=True))
    op.add_column('sessions', sa.Column('location', sa.String(length=200), nullable=True))
    op.add_column('sessions', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('sessions', 'last_seen_at')
    op.drop_column('sessions', 'location')
    op.drop_column('sessions', 'user_agent')
    op.drop_column('sessions', 'ip')
