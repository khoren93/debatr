"""Admin console levers (runtime_settings) and passkeys (admin_passkeys)

Revision ID: 000000000013
Revises: 000000000012
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '000000000013'
down_revision: Union[str, None] = '000000000012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'runtime_settings',
        sa.Column('key', sa.String(length=64), primary_key=True),
        sa.Column('value_json', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_by', sa.String(length=320), nullable=True),
    )
    op.create_table(
        'admin_passkeys',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('credential_id', sa.String(length=1400), nullable=False, unique=True),
        sa.Column('public_key', sa.LargeBinary(), nullable=False),
        sa.Column('sign_count', sa.Integer(), nullable=False),
        sa.Column('transports', sa.JSON(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('aaguid', sa.String(length=36), nullable=True),
        sa.Column('backed_up', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_admin_passkeys_user_id', 'admin_passkeys', ['user_id'])
    # The audit page filters by action and actor over the whole log.
    op.create_index('ix_admin_audit_log_actor_email', 'admin_audit_log', ['actor_email'])


def downgrade() -> None:
    op.drop_index('ix_admin_audit_log_actor_email', table_name='admin_audit_log')
    op.drop_index('ix_admin_passkeys_user_id', table_name='admin_passkeys')
    op.drop_table('admin_passkeys')
    op.drop_table('runtime_settings')
