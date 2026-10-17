"""Personal API tokens (CLI, scripts, MCP agents) and the token that started a run

Revision ID: 000000000009
Revises: 000000000008
Create Date: 2026-10-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '000000000009'
down_revision: Union[str, None] = '000000000008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'api_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('token_last4', sa.String(length=8), nullable=False),
        sa.Column('spend_limit_usd', sa.Numeric(14, 6), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_api_tokens_user_id', 'api_tokens', ['user_id'])
    op.create_index('ix_api_tokens_token_hash', 'api_tokens', ['token_hash'], unique=True)

    op.add_column(
        'debates', sa.Column('api_token_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        'debates_api_token_id_fkey',
        'debates',
        'api_tokens',
        ['api_token_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_debates_api_token_id', 'debates', ['api_token_id'])


def downgrade() -> None:
    op.drop_index('ix_debates_api_token_id', table_name='debates')
    op.drop_constraint('debates_api_token_id_fkey', 'debates', type_='foreignkey')
    op.drop_column('debates', 'api_token_id')
    op.drop_index('ix_api_tokens_token_hash', table_name='api_tokens')
    op.drop_index('ix_api_tokens_user_id', table_name='api_tokens')
    op.drop_table('api_tokens')
