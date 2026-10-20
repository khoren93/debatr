"""Trending topics per show format: trending_topics.format

Revision ID: 000000000017
Revises: 000000000016
Create Date: 2026-10-20 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '000000000017'
down_revision: Union[str, None] = '000000000016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Earlier batches hold debate topics only.
    op.add_column(
        'trending_topics',
        sa.Column('format', sa.String(20), nullable=False, server_default='debate'),
    )


def downgrade() -> None:
    op.drop_column('trending_topics', 'format')
