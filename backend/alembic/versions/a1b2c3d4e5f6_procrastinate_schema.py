"""procrastinate job queue schema

Revision ID: a1b2c3d4e5f6
Revises: 6c2f4fbf42fb
Create Date: 2026-10-06 10:05:00

The queue lives in the same Postgres, so one `alembic upgrade head` sets up everything.
Upgrading procrastinate itself later means adding its migration scripts here by hand.
"""
from typing import Sequence, Union

from alembic import op
from procrastinate.schema import SchemaManager

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "6c2f4fbf42fb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Raw driver cursor: the script has literal '%' characters, which SQLAlchemy would treat as params.
    cursor = op.get_bind().connection.cursor()
    cursor.execute(SchemaManager.get_schema().encode())


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers, procrastinate_jobs CASCADE;
        DROP TYPE IF EXISTS procrastinate_job_status, procrastinate_job_event_type CASCADE;
    """)
