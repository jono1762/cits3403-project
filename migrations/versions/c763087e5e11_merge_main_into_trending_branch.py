"""merge main into trending branch

Revision ID: c763087e5e11
Revises: 1dab4f32bde6, 27967fcb6fe2
Create Date: 2026-05-06 18:42:08.099023

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c763087e5e11'
down_revision = ('1dab4f32bde6', '27967fcb6fe2')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
