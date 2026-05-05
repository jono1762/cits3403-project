"""add favourite_locations table

Revision ID: a1b2c3d4e6f1
Revises: 9304397c7f35
Create Date: 2026-05-05 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e6f1'
down_revision = '9304397c7f35'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'favourite_locations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('city_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['city_id'], ['cities.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'city_id', name='uq_user_city_fav')
    )


def downgrade():
    op.drop_table('favourite_locations')
