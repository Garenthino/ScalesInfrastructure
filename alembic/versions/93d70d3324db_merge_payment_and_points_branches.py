"""merge payment and points branches

Revision ID: 93d70d3324db
Revises: 000000000007, 000000000009
Create Date: 2026-05-31 19:23:14.334778

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '93d70d3324db'
down_revision: Union[str, None] = ('000000000007', '000000000009')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
