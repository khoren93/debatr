"""Views by day, place and source: view_days

Revision ID: 000000000016
Revises: 000000000015
Create Date: 2026-10-20 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '000000000016'
down_revision: Union[str, None] = '000000000015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'view_days',
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('debate_id', sa.UUID(), nullable=False),
        sa.Column('place', sa.String(8), nullable=False),
        sa.Column('source', sa.String(16), nullable=False),
        sa.Column('views', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['debate_id'], ['debates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('day', 'debate_id', 'place', 'source'),
    )
    op.create_index('ix_view_days_debate_id', 'view_days', ['debate_id'])


def downgrade() -> None:
    op.drop_index('ix_view_days_debate_id', table_name='view_days')
    op.drop_table('view_days')
