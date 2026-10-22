"""The letters the site sends: mail_messages (the console's Mail page)

Revision ID: 000000000022
Revises: 000000000021
Create Date: 2026-10-23 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "000000000022"
down_revision: Union[str, None] = "000000000021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mail_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("to_address", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("message_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("provider_id", sa.String(64), nullable=True),
        sa.Column("delivery", sa.String(12), nullable=True),
        sa.Column("delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("events_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mail_messages_created_at", "mail_messages", ["created_at"])
    op.create_index("ix_mail_messages_user_id", "mail_messages", ["user_id"])
    op.create_index("ix_mail_messages_to_address", "mail_messages", ["to_address"])
    op.create_index("ix_mail_messages_provider_id", "mail_messages", ["provider_id"])


def downgrade() -> None:
    op.drop_table("mail_messages")
