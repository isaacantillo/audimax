"""course owner and admin flag

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27 13:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: every course belongs to one user, who alone sees it and its lectures; admins see
    all. The oldest user (the one created from ADMIN_USERNAME on first start) becomes the admin and
    owns the existing courses; move them with an UPDATE afterwards if they belong to someone else."""
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.execute("UPDATE users SET is_admin = true WHERE id = (SELECT id FROM users ORDER BY created_at, id LIMIT 1)")
    op.add_column('courses', sa.Column('user_id', sa.Uuid(), nullable=True))
    op.execute("UPDATE courses SET user_id = (SELECT id FROM users ORDER BY created_at, id LIMIT 1)")
    orphans = op.get_bind().scalar(sa.text("SELECT count(*) FROM courses WHERE user_id IS NULL"))
    if orphans:
        raise RuntimeError(f"{orphans} courses but no users to own them: create a user first, then migrate again")
    op.alter_column('courses', 'user_id', nullable=False)
    op.create_index(op.f('ix_courses_user_id'), 'courses', ['user_id'], unique=False)
    op.create_foreign_key(op.f('courses_user_id_fkey'), 'courses', 'users', ['user_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('courses_user_id_fkey'), 'courses', type_='foreignkey')
    op.drop_index(op.f('ix_courses_user_id'), table_name='courses')
    op.drop_column('courses', 'user_id')
    op.drop_column('users', 'is_admin')
