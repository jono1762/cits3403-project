"""merge heads on reports-expired branch

Revision ID: 216561a7caf7
Revises: 1d01e3afdf12, b7c8d9e0f1a2
Create Date: 2026-05-06 09:17:46.234426

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '216561a7caf7'
down_revision = ('1d01e3afdf12', 'b7c8d9e0f1a2')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
