"""merge migration heads

Revision ID: ca7def92012e
Revises: 277d7bee43b2, d52d948393f8
Create Date: 2026-05-15 17:30:28.373741

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ca7def92012e'
down_revision = ('277d7bee43b2', 'd52d948393f8')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
