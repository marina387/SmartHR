"""Version candidate writes to prevent lost updates."""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e52701'
down_revision = 'a1b2c3d42701'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('candidates',sa.Column('revision',sa.Integer(),nullable=False,server_default='1'))


def downgrade():
    with op.batch_alter_table('candidates') as batch:
        batch.drop_column('revision')
