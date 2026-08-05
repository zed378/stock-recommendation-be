"""a recommendation must state its language, not inherit a default

Revision ID: d5b2914c7ae0
Revises: c3f81a6e02b7
Create Date: 2026-08-05 18:52:40.771203
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd5b2914c7ae0'
down_revision: str | None = 'c3f81a6e02b7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- repair the rows the missing write mislabelled --------------------
    #
    # `_persist` never passed `language`, so every recommendation took the
    # default of 'id' whatever the prompt had asked for. Once the output
    # language became English the damage compounded: `render_translation` reads
    # the row's own language to decide what "the other one" is, saw 'id', and
    # translated English into English. The result is a translation byte-identical
    # to its source.
    #
    # That identity is what makes this repairable rather than guesswork. A
    # translator asked for English and returning its input verbatim was given
    # English, so the prose is English and the stored rendering is worth nothing.
    # The label is corrected and the empty rendering dropped; the interface then
    # falls back to the on-demand endpoint, which is a slower path rather than a
    # missing one.
    #
    # Rows whose translation genuinely differs are left alone - they were
    # written before the output language changed and are correctly labelled.
    op.execute(
        """
        UPDATE recommendations
           SET language = 'en',
               translations = '{}'::jsonb
         WHERE translations ? 'en'
           AND reasoning IS NOT DISTINCT FROM translations->'en'->'fields'->>'reasoning'
        """
    )

    # --- and stop the default from being available to inherit -------------
    #
    # A default here is a guess that looks like a fact. Removed so that a
    # writer which forgets fails at once, instead of producing a row nobody can
    # tell apart from a correct one.
    op.alter_column('recommendations', 'language', server_default=None)


def downgrade() -> None:
    op.alter_column('recommendations', 'language', server_default='id')
