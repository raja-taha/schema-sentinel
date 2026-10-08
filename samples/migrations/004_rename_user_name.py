"""Alembic migration — risky in-place rename."""

from alembic import op
import sqlalchemy as sa


revision = "004_rename_user_name"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "name", new_column_name="full_name")
    # Equivalent SQL often emitted:
    op.execute('ALTER TABLE users RENAME COLUMN name TO full_name')


def downgrade() -> None:
    op.execute('ALTER TABLE users RENAME COLUMN full_name TO name')
