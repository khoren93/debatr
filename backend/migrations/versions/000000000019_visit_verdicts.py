"""A person, a bot or an AI agent per visit: visits.verdict, bot_score, bot_reasons, signals,
network, network_kind

Revision ID: 000000000019
Revises: 000000000018
Create Date: 2026-10-21 23:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "000000000019"
down_revision: Union[str, None] = "000000000018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Earlier visits stay "unclear" until `python -m app.manage audience classify` looks at them.
    op.add_column(
        "visits", sa.Column("verdict", sa.String(12), nullable=False, server_default="unclear")
    )
    op.add_column(
        "visits", sa.Column("bot_score", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "visits", sa.Column("bot_reasons", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column("visits", sa.Column("signals", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("visits", sa.Column("network", sa.String(120), nullable=True))
    op.add_column("visits", sa.Column("network_kind", sa.String(8), nullable=True))
    op.create_index("ix_visits_verdict", "visits", ["verdict"])


def downgrade() -> None:
    op.drop_index("ix_visits_verdict", table_name="visits")
    for column in ("network_kind", "network", "signals", "bot_reasons", "bot_score", "verdict"):
        op.drop_column("visits", column)
