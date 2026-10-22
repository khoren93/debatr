"""Email confirmation: users.email_verified_at, users.email_check_required

Accounts that exist keep publishing and topping up without confirming (the column's server
default is false); new accounts get true from the model.

Revision ID: 000000000021
Revises: 000000000020
Create Date: 2026-10-22 23:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "000000000021"
down_revision: Union[str, None] = "000000000020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("email_check_required", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "email_check_required")
    op.drop_column("users", "email_verified_at")
