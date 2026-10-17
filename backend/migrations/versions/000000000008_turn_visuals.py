"""Visual scenes per turn: plan, hints, disputes and fact-checks (turns.visuals_json)

Revision ID: 000000000008
Revises: 000000000007
Create Date: 2026-10-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '000000000008'
down_revision: Union[str, None] = '000000000007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'turns',
        sa.Column('visuals_json', sa.JSON(), nullable=False, server_default='{}'),
    )


def downgrade() -> None:
    op.drop_column('turns', 'visuals_json')
