"""Visits of the site and what happened in them: visits, visit_events

Revision ID: 000000000018
Revises: 000000000017
Create Date: 2026-10-21 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '000000000018'
down_revision: Union[str, None] = '000000000017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'visits',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('visitor_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('staff', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ip', sa.String(64), nullable=True),
        sa.Column('user_agent', sa.String(300), nullable=True),
        sa.Column('country', sa.String(2), nullable=True),
        sa.Column('region', sa.String(80), nullable=True),
        sa.Column('city', sa.String(80), nullable=True),
        sa.Column('source', sa.String(16), nullable=False),
        sa.Column('referrer_host', sa.String(253), nullable=True),
        sa.Column('referrer', sa.String(300), nullable=True),
        sa.Column('utm_source', sa.String(100), nullable=True),
        sa.Column('utm_medium', sa.String(100), nullable=True),
        sa.Column('utm_campaign', sa.String(100), nullable=True),
        sa.Column('ref', sa.String(40), nullable=True),
        sa.Column('landing', sa.String(300), nullable=False),
        sa.Column('exit_path', sa.String(300), nullable=False),
        sa.Column('pageviews', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('actions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('engaged_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('device', sa.String(8), nullable=False),
        sa.Column('browser', sa.String(24), nullable=True),
        sa.Column('os', sa.String(24), nullable=True),
        sa.Column('screen', sa.String(16), nullable=True),
        sa.Column('language', sa.String(16), nullable=True),
        sa.Column('timezone', sa.String(48), nullable=True),
        sa.Column('new_visitor', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_visits_visitor_id', 'visits', ['visitor_id'])
    op.create_index('ix_visits_user_id', 'visits', ['user_id'])
    op.create_index('ix_visits_started_at', 'visits', ['started_at'])
    op.create_index('ix_visits_last_at', 'visits', ['last_at'])
    op.create_index('ix_visits_ip', 'visits', ['ip'])
    op.create_index('ix_visits_visitor_started', 'visits', ['visitor_id', 'started_at'])

    op.create_table(
        'visit_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('visit_id', sa.UUID(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('kind', sa.String(8), nullable=False),
        sa.Column('name', sa.String(32), nullable=False),
        sa.Column('path', sa.String(300), nullable=False),
        sa.Column('debate_id', sa.UUID(), nullable=True),
        sa.Column('engaged_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('props', sa.JSON(), nullable=False, server_default='{}'),
        sa.ForeignKeyConstraint(['visit_id'], ['visits.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['debate_id'], ['debates.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_visit_events_at', 'visit_events', ['at'])
    op.create_index('ix_visit_events_debate_id', 'visit_events', ['debate_id'])
    op.create_index('ix_visit_events_visit_at', 'visit_events', ['visit_id', 'at'])


def downgrade() -> None:
    op.drop_index('ix_visit_events_visit_at', table_name='visit_events')
    op.drop_index('ix_visit_events_debate_id', table_name='visit_events')
    op.drop_index('ix_visit_events_at', table_name='visit_events')
    op.drop_table('visit_events')
    op.drop_index('ix_visits_visitor_started', table_name='visits')
    op.drop_index('ix_visits_ip', table_name='visits')
    op.drop_index('ix_visits_last_at', table_name='visits')
    op.drop_index('ix_visits_started_at', table_name='visits')
    op.drop_index('ix_visits_user_id', table_name='visits')
    op.drop_index('ix_visits_visitor_id', table_name='visits')
    op.drop_table('visits')
