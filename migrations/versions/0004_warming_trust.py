"""warming trust tables

Revision ID: 0004_warming_trust
Revises: 0003_proxy_ip
Create Date: 2026-11-04
"""

from __future__ import annotations

from alembic import op

from db.models import ActionLog, ReviewAttempt, TrustScore, WarmingSession

revision = "0004_warming_trust"
down_revision = "0003_proxy_ip"
branch_labels = None
depends_on = None

TABLES = [TrustScore.__table__, ActionLog.__table__, WarmingSession.__table__, ReviewAttempt.__table__]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
