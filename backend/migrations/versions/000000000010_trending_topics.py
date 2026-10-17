"""Trending topics from the news: one batch per refresh, topics with their source articles

Revision ID: 000000000010
Revises: 000000000009
Create Date: 2026-10-17 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '000000000010'
down_revision: Union[str, None] = '000000000009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'trending_batches',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('topic_count', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Numeric(14, 6), nullable=False),
        sa.Column('stats_json', sa.JSON(), server_default='{}', nullable=False),
    )
    op.create_index('ix_trending_batches_created_at', 'trending_batches', ['created_at'])

    op.create_table(
        'trending_topics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=80), nullable=False),
        sa.Column('question', sa.String(length=300), nullable=False),
        sa.Column('brief', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('heat', sa.Integer(), nullable=False),
        sa.Column('outlets', sa.Integer(), nullable=False),
        sa.Column('sources_json', sa.JSON(), nullable=False),
        sa.Column('is_hidden', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['batch_id'], ['trending_batches.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_trending_topics_batch_id', 'trending_topics', ['batch_id'])


def downgrade() -> None:
    op.drop_index('ix_trending_topics_batch_id', table_name='trending_topics')
    op.drop_table('trending_topics')
    op.drop_index('ix_trending_batches_created_at', table_name='trending_batches')
    op.drop_table('trending_batches')
