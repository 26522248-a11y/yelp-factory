"""account profile fields

Revision ID: 0002_account_profile
Revises: 0001_initial
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_account_profile"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("gender", sa.String(length=24), nullable=True))
    op.add_column("accounts", sa.Column("birth_date", sa.String(length=16), nullable=True))
    op.add_column("accounts", sa.Column("address_line", sa.String(length=300), nullable=True))
    op.add_column("accounts", sa.Column("avatar_path", sa.String(length=400), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "avatar_path")
    op.drop_column("accounts", "address_line")
    op.drop_column("accounts", "birth_date")
    op.drop_column("accounts", "gender")
