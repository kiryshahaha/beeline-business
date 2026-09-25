"""Merge multiple heads from T15 and T07

Revision ID: 0d5647f7d664
Revises: 0023, 6a36204671b2
"""

from collections.abc import Sequence

revision: str = "0d5647f7d664"
down_revision: str | None = ("0023", "6a36204671b2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
