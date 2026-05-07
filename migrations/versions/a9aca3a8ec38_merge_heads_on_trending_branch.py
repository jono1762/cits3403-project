"""merge heads on trending branch

Revision ID: a9aca3a8ec38
Revises: 1d01e3afdf12, b7c8d9e0f1a2
Create Date: 2026-05-06 10:00:36.859279

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9aca3a8ec38'
down_revision = ('1d01e3afdf12', 'b7c8d9e0f1a2')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
