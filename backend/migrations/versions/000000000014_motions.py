"""Topics (motions): every debate becomes a version of a topic; remix lineage

Revision ID: 000000000014
Revises: 000000000013
Create Date: 2026-10-19 20:00:00.000000

"""
import re
import secrets
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '000000000014'
down_revision: Union[str, None] = '000000000013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SLUG_ALPHABET = 'abcdefghijkmnpqrstuvwxyz23456789'
_NOT_WORD = re.compile(r'[\W_]+')


def _normalize(topic: str) -> str:
    """Frozen copy of app.services.motions.normalize_topic (as of this revision)."""
    text = unicodedata.normalize('NFKC', topic).casefold()
    return _NOT_WORD.sub(' ', text).strip()[:600]


def _slug(taken: set[str]) -> str:
    while True:
        slug = ''.join(secrets.choice(_SLUG_ALPHABET) for _ in range(10))
        if slug not in taken:
            taken.add(slug)
            return slug


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    op.create_table(
        'motions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('slug', sa.String(length=32), nullable=False, unique=True),
        sa.Column('key', sa.String(length=600), nullable=True, unique=True),
        sa.Column(
            'merged_into_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('motions.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_motions_key_trgm',
        'motions',
        ['key'],
        postgresql_using='gin',
        postgresql_ops={'key': 'gin_trgm_ops'},
    )
    op.add_column(
        'debates',
        sa.Column(
            'motion_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('motions.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index('ix_debates_motion_id', 'debates', ['motion_id'])
    op.add_column(
        'debates',
        sa.Column(
            'remix_of_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('debates.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index('ix_debates_remix_of_id', 'debates', ['remix_of_id'])

    # Every existing debate joins the topic of its normalized text (earlier remixes copied the
    # text word for word, so they land with their originals).
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, COALESCE(config_json->>'topic', title, '') AS topic, created_at "
            'FROM debates'
        )
    ).fetchall()
    taken: set[str] = set()
    by_key: dict[str, dict[str, object]] = {}
    motions: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    for debate_id, topic, created_at in rows:
        key = _normalize(str(topic or ''))
        motion = by_key.get(key) if key else None
        if motion is None:
            motion = {
                'id': uuid.uuid4(),
                'slug': _slug(taken),
                'key': key or None,
                'created_at': created_at or datetime.now(UTC),
            }
            motions.append(motion)
            if key:
                by_key[key] = motion
        elif created_at is not None and created_at < motion['created_at']:  # type: ignore[operator]
            motion['created_at'] = created_at
        links.append({'debate_id': debate_id, 'motion_id': motion['id']})
    if motions:
        bind.execute(
            sa.text(
                'INSERT INTO motions (id, slug, key, created_at) '
                'VALUES (:id, :slug, :key, :created_at)'
            ),
            motions,
        )
        bind.execute(
            sa.text('UPDATE debates SET motion_id = :motion_id WHERE id = :debate_id'), links
        )


def downgrade() -> None:
    op.drop_index('ix_debates_remix_of_id', table_name='debates')
    op.drop_column('debates', 'remix_of_id')
    op.drop_index('ix_debates_motion_id', table_name='debates')
    op.drop_column('debates', 'motion_id')
    op.drop_index('ix_motions_key_trgm', table_name='motions')
    op.drop_table('motions')
