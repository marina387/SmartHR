"""Add personal accounts and actor audit without rewriting business records."""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d42701'
down_revision = '912b8c14a302'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users', sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('login',sa.String(120),nullable=False,unique=True),
        sa.Column('name',sa.String(200),nullable=False), sa.Column('password_hash',sa.Text(),nullable=False),
        sa.Column('role',sa.String(20),nullable=False), sa.Column('active',sa.Boolean(),nullable=False),
        sa.Column('session_version',sa.Integer(),nullable=False))
    op.create_table('auth_bootstrap',sa.Column('id',sa.Integer(),primary_key=True))
    op.create_table('audit_events',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('user_id',sa.String(64),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('user_name',sa.String(200),nullable=False),sa.Column('endpoint',sa.String(160),nullable=False),
        sa.Column('path',sa.String(400),nullable=False),sa.Column('method',sa.String(10),nullable=False),
        sa.Column('created_at',sa.String(40),nullable=False))


def downgrade():
    op.drop_table('audit_events')
    op.drop_table('auth_bootstrap')
    op.drop_table('users')
