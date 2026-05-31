"""add singer profile fields (bio, avatar_url, social_links)

Revision ID: 000000000006
Revises: 000000000005
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '000000000006'
down_revision: Union[str, None] = '000000000005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("singers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("bio", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("avatar_url", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("social_links", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("singers", schema=None) as batch_op:
        batch_op.drop_column("social_links")
        batch_op.drop_column("avatar_url")
        batch_op.drop_column("bio")
