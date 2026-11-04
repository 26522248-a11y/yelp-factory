"""email/proxy pools

Revision ID: 0005_pools
Revises: 0004_warming_trust
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from db.models import EmailPool, ProxyPool

revision = "0005_pools"
down_revision = "0004_warming_trust"
branch_labels = None
depends_on = None


def upgrade() -> None:
    EmailPool.__table__.create(bind=op.get_bind(), checkfirst=True)
    ProxyPool.__table__.create(bind=op.get_bind(), checkfirst=True)
    op.add_column("accounts", sa.Column("email_pool_id", sa.Uuid(), nullable=True))
    op.add_column("accounts", sa.Column("proxy_pool_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_accounts_email_pool", "accounts", "email_pool", ["email_pool_id"], ["id"])
    op.create_foreign_key("fk_accounts_proxy_pool", "accounts", "proxy_pool", ["proxy_pool_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_accounts_proxy_pool", "accounts", type_="foreignkey")
    op.drop_constraint("fk_accounts_email_pool", "accounts", type_="foreignkey")
    op.drop_column("accounts", "proxy_pool_id")
    op.drop_column("accounts", "email_pool_id")
    ProxyPool.__table__.drop(bind=op.get_bind(), checkfirst=True)
    EmailPool.__table__.drop(bind=op.get_bind(), checkfirst=True)
