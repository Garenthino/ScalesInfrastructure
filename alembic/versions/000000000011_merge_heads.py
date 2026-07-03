"""merge billing_events and admin audit log heads

Revision ID: 000000000011
Revises: 000000000010, c879d7db7567
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '000000000011'
down_revision: Union[str, Sequence[str], None] = ('000000000010', 'c879d7db7567')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
