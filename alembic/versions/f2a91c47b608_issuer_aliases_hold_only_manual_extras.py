"""issuers.aliases holds only what a person typed

Revision ID: f2a91c47b608
Revises: e7d3b02f5a91
Create Date: 2026-08-06 11:40:18.902441
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = 'f2a91c47b608'
down_revision: str | None = 'e7d3b02f5a91'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The column's meaning changed, and the rows written under the old one are
    # now indistinguishable from human input.
    #
    # It used to hold the *effective* alias list, written by the importer from
    # the registered name. It now holds only the extras somebody typed: the
    # curated index and the derived names are resolved at match time, so an
    # issuer imported today picks up an index entry added next month.
    #
    # Left in place, the machine-derived values become permanent. They are
    # never recomputed - nothing recomputes an editable field - so a tightening
    # of the derivation rules cannot reach them. That is not hypothetical: the
    # rule that stopped deriving "kawasan industri" from "Kawasan Industri
    # Jababeka" shipped, and the stale row went on matching an article about an
    # industrial estate in Madura anyway.
    #
    # Safe to clear because every value here was machine-written: the column
    # and the endpoint that edits it are part of the same unreleased feature,
    # and the effective list is recomputed from the name and the index on the
    # next match either way.
    op.execute("UPDATE issuers SET aliases = '[]'")


def downgrade() -> None:
    # Nothing to restore. The previous contents were derivable from the
    # registered name, and are derived again on every match.
    pass
