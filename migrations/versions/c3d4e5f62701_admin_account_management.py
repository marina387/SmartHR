"""Require password replacement after an administrator reset."""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f62701'
down_revision = 'b2c3d4e52701'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('must_change_password')
