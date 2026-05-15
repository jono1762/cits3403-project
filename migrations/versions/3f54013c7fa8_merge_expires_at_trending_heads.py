"""merge expires_at + trending heads

Revision ID: 3f54013c7fa8
Revises: a15abbae8385, c763087e5e11
Create Date: 2026-05-12 18:29:46.441913

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f54013c7fa8'
down_revision = ('a15abbae8385', 'c763087e5e11')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
