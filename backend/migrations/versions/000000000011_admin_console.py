"""Admin console: roles and TOTP on users, session epoch, append-only audit log

Revision ID: 000000000011
Revises: 000000000010
Create Date: 2026-10-18 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '000000000011'
down_revision: Union[str, None] = '000000000010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('admin_role', sa.String(length=16), nullable=True))
    op.add_column('users', sa.Column('totp_secret_enc', sa.Text(), nullable=True))
    op.add_column(
        'users', sa.Column('totp_enabled_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'users',
        sa.Column('recovery_codes_json', sa.JSON(), server_default='[]', nullable=False),
    )
    op.add_column(
        'users', sa.Column('session_epoch', sa.Integer(), server_default='0', nullable=False)
    )

    op.create_table(
        'admin_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actor_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('actor_email', sa.String(length=320), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=True),
        sa.Column('target_id', sa.String(length=64), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('before_json', sa.JSON(), nullable=True),
        sa.Column('after_json', sa.JSON(), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=300), nullable=True),
        sa.Column('ok', sa.Boolean(), nullable=False),
    )
    op.create_index('ix_admin_audit_log_created_at', 'admin_audit_log', ['created_at'])
    op.create_index('ix_admin_audit_log_actor_user_id', 'admin_audit_log', ['actor_user_id'])
    op.create_index('ix_admin_audit_log_action', 'admin_audit_log', ['action'])
    op.create_index('ix_admin_audit_log_target', 'admin_audit_log', ['target_type', 'target_id'])

    # The log only grows: the application (and anyone with its credentials) cannot rewrite or
    # erase what was done. Clearing it on purpose means dropping this trigger in a migration.
    op.execute(
        """
        CREATE FUNCTION admin_audit_log_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'admin_audit_log is append-only';
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_audit_log_no_change
        BEFORE UPDATE OR DELETE ON admin_audit_log
        FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only();
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_audit_log_no_truncate
        BEFORE TRUNCATE ON admin_audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION admin_audit_log_append_only();
        """
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS admin_audit_log_no_truncate ON admin_audit_log')
    op.execute('DROP TRIGGER IF EXISTS admin_audit_log_no_change ON admin_audit_log')
    op.execute('DROP FUNCTION IF EXISTS admin_audit_log_append_only()')
    op.drop_index('ix_admin_audit_log_target', table_name='admin_audit_log')
    op.drop_index('ix_admin_audit_log_action', table_name='admin_audit_log')
    op.drop_index('ix_admin_audit_log_actor_user_id', table_name='admin_audit_log')
    op.drop_index('ix_admin_audit_log_created_at', table_name='admin_audit_log')
    op.drop_table('admin_audit_log')
    op.drop_column('users', 'session_epoch')
    op.drop_column('users', 'recovery_codes_json')
    op.drop_column('users', 'totp_enabled_at')
    op.drop_column('users', 'totp_secret_enc')
    op.drop_column('users', 'admin_role')
