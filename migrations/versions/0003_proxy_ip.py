"""account proxy ip

Revision ID: 0003_proxy_ip
Revises: 0002_account_profile
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_proxy_ip"
down_revision = "0002_account_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("proxy_ip", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "proxy_ip")
