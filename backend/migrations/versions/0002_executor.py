"""Durable dispatch reservation and worker registration."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("execution", sa.Column("dispatch_after", sa.Float(), nullable=True))
    op.create_index("ix_execution_dispatch_after", "execution", ["dispatch_after"])
    op.create_table("executor_worker",
                    sa.Column("name", sa.String(length=255), primary_key=True),
                    sa.Column("last_seen", sa.Float(), nullable=False))


def downgrade():
    op.drop_table("executor_worker")
    op.drop_index("ix_execution_dispatch_after", table_name="execution")
    op.drop_column("execution", "dispatch_after")
