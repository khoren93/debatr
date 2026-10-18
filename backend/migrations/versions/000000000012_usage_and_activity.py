"""Statistics data: provider usage log, user activity days, last seen, date indexes

Revision ID: 000000000012
Revises: 000000000011
Create Date: 2026-10-18 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '000000000012'
down_revision: Union[str, None] = '000000000011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index('ix_users_created_at', 'users', ['created_at'])
    op.create_index('ix_debates_created_at', 'debates', ['created_at'])
    op.create_index('ix_debates_user_id_created_at', 'debates', ['user_id', 'created_at'])

    op.create_table(
        'user_activity_days',
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            primary_key=True,
        ),
        sa.Column('day', sa.Date(), primary_key=True),
    )
    op.create_index('ix_user_activity_days_day', 'user_activity_days', ['day'])

    op.create_table(
        'provider_usage',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'debate_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('debates.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('purpose', sa.String(length=32), nullable=False),
        sa.Column('provider', sa.String(length=16), nullable=False),
        sa.Column('model', sa.String(length=160), nullable=False),
        sa.Column('key_owner', sa.String(length=8), nullable=False),
        sa.Column('tokens_in', sa.Integer(), nullable=False),
        sa.Column('tokens_out', sa.Integer(), nullable=False),
        sa.Column('chars', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Numeric(14, 6), nullable=False),
        sa.Column('ok', sa.Boolean(), nullable=False),
        sa.Column('error_kind', sa.String(length=24), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('meta_json', sa.JSON(), server_default='{}', nullable=False),
    )
    op.create_index('ix_provider_usage_created_at', 'provider_usage', ['created_at'])
    op.create_index('ix_provider_usage_debate_id', 'provider_usage', ['debate_id'])
    op.create_index('ix_provider_usage_user_id', 'provider_usage', ['user_id'])
    op.create_index('ix_provider_usage_purpose', 'provider_usage', ['purpose'])

    # Activity before this table existed, from what accounts did on a given day: signing up,
    # signing in, starting debates, liking, voting, creating API tokens.
    op.execute(
        """
        INSERT INTO user_activity_days (user_id, day)
        SELECT user_id, (moment AT TIME ZONE 'UTC')::date FROM (
            SELECT id AS user_id, created_at AS moment FROM users
            UNION ALL SELECT id, last_login_at FROM users WHERE last_login_at IS NOT NULL
            UNION ALL SELECT user_id, created_at FROM debates WHERE user_id IS NOT NULL
            UNION ALL SELECT user_id, created_at FROM debate_likes
            UNION ALL SELECT user_id, created_at FROM debate_votes
            UNION ALL SELECT user_id, updated_at FROM debate_votes
            UNION ALL SELECT user_id, created_at FROM api_tokens
        ) AS seen
        WHERE moment IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE users SET last_seen_at = GREATEST(
            last_login_at,
            (SELECT max(created_at) FROM debates WHERE debates.user_id = users.id)
        )
        """
    )


def downgrade() -> None:
    op.drop_index('ix_provider_usage_purpose', table_name='provider_usage')
    op.drop_index('ix_provider_usage_user_id', table_name='provider_usage')
    op.drop_index('ix_provider_usage_debate_id', table_name='provider_usage')
    op.drop_index('ix_provider_usage_created_at', table_name='provider_usage')
    op.drop_table('provider_usage')
    op.drop_index('ix_user_activity_days_day', table_name='user_activity_days')
    op.drop_table('user_activity_days')
    op.drop_index('ix_debates_user_id_created_at', table_name='debates')
    op.drop_index('ix_debates_created_at', table_name='debates')
    op.drop_index('ix_users_created_at', table_name='users')
    op.drop_column('users', 'last_seen_at')
