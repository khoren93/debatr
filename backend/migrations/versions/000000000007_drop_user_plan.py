"""Drop users.plan: accounts only have a prepaid balance

Revision ID: 000000000007
Revises: 000000000006
Create Date: 2026-10-16 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '000000000007'
down_revision: Union[str, None] = '000000000006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('users', 'plan')


def downgrade() -> None:
    op.add_column(
        'users',
        sa.Column('plan', sa.String(length=32), nullable=False, server_default='free'),
    )
