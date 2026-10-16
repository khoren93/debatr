"""Gallery moderation status on debates

Revision ID: 000000000006
Revises: 000000000005
Create Date: 2026-10-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '000000000006'
down_revision: Union[str, None] = '000000000005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'debates',
        sa.Column('moderation_status', sa.String(length=16), nullable=False, server_default='none'),
    )
    op.add_column(
        'debates', sa.Column('moderation_json', sa.JSON(), nullable=False, server_default='{}')
    )
    op.create_index('ix_debates_moderation_status', 'debates', ['moderation_status'])
    # Debates that are already public were published by their owners before moderation existed.
    op.execute("UPDATE debates SET moderation_status = 'approved' WHERE is_public")


def downgrade() -> None:
    op.drop_index('ix_debates_moderation_status', table_name='debates')
    op.drop_column('debates', 'moderation_json')
    op.drop_column('debates', 'moderation_status')
