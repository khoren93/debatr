"""Likes and audience votes on public debates

Revision ID: 000000000005
Revises: 000000000004
Create Date: 2026-10-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '000000000005'
down_revision: Union[str, None] = '000000000004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'debates', sa.Column('likes_count', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column(
        'debates', sa.Column('votes_count', sa.Integer(), nullable=False, server_default='0')
    )

    op.create_table(
        'debate_likes',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('debate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['debate_id'], ['debates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'debate_id'),
    )
    op.create_index('ix_debate_likes_debate_id', 'debate_likes', ['debate_id'])

    op.create_table(
        'debate_votes',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('debate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('participant_id', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['debate_id'], ['debates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'debate_id'),
    )
    op.create_index('ix_debate_votes_debate_id', 'debate_votes', ['debate_id'])


def downgrade() -> None:
    op.drop_index('ix_debate_votes_debate_id', table_name='debate_votes')
    op.drop_table('debate_votes')
    op.drop_index('ix_debate_likes_debate_id', table_name='debate_likes')
    op.drop_table('debate_likes')
    op.drop_column('debates', 'votes_count')
    op.drop_column('debates', 'likes_count')
