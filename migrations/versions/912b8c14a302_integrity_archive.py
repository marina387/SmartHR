"""Add non-destructive archive for explicit database integrity repairs."""
from alembic import op
import sqlalchemy as sa

revision = "912b8c14a302"
down_revision = "7c24d3f180a1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "integrity_archive",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_table", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("original_row", sa.JSON(), nullable=False),
        sa.Column("archived_at", sa.String(40), nullable=False),
    )


def downgrade():
    # A downgrade must not silently discard the only remaining copies of old rows.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM integrity_archive")).scalar():
        raise RuntimeError("Export integrity_archive before downgrading")
    op.drop_table("integrity_archive")
