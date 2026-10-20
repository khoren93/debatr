"""AI covers: cover_status / cover_json on debates

Revision ID: 000000000015
Revises: 000000000014
Create Date: 2026-10-20 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '000000000015'
down_revision: Union[str, None] = '000000000014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'debates',
        sa.Column('cover_status', sa.String(16), nullable=False, server_default='none'),
    )
    op.add_column(
        'debates',
        sa.Column('cover_json', sa.JSON(), nullable=False, server_default='{}'),
    )
    op.create_index('ix_debates_cover_status', 'debates', ['cover_status'])


def downgrade() -> None:
    op.drop_index('ix_debates_cover_status', table_name='debates')
    op.drop_column('debates', 'cover_json')
    op.drop_column('debates', 'cover_status')
