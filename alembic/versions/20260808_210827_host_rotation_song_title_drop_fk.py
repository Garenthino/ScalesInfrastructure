"""Host rotation: add song_title, drop song_id FK

Revision ID: 20260808210827
Revises: 20260808193649
Create Date: 2026-08-08T21:08:27.206932+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260808210827"
down_revision: Union[str, None] = "20260808193649"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "host_rotation",
        sa.Column("song_title", sa.Text, nullable=True),
    )
    # Drop the actual DB-level FK enforcement so local/integer song ids from
    # the KJ desktop do not fail, while keeping the SQLAlchemy relationship.
    with op.batch_alter_table("host_rotation") as batch_op:
        batch_op.drop_constraint("host_rotation_song_id_fkey", type_="foreignkey")


def downgrade() -> None:
    with op.batch_alter_table("host_rotation") as batch_op:
        batch_op.create_foreign_key(
            "host_rotation_song_id_fkey",
            "songs",
            ["song_id"],
            ["id"],
        )
    op.drop_column("host_rotation", "song_title")
