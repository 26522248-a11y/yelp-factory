"""batch tracking

Revision ID: 0006_batches
Revises: 0005_pools
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from db.models import Batch

revision = "0006_batches"
down_revision = "0005_pools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Batch.__table__.create(bind=op.get_bind(), checkfirst=True)
    op.add_column("accounts", sa.Column("batch_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_accounts_batch", "accounts", "batches", ["batch_id"], ["id"])
    op.create_index("ix_accounts_batch_id", "accounts", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_accounts_batch_id", table_name="accounts")
    op.drop_constraint("fk_accounts_batch", "accounts", type_="foreignkey")
    op.drop_column("accounts", "batch_id")
    Batch.__table__.drop(bind=op.get_bind(), checkfirst=True)
