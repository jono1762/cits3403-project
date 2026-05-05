"""add favourite_reports table

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e6f1
Create Date: 2026-05-05 16:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c8d9e0f1a2'
down_revision = 'a1b2c3d4e6f1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'favourite_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['report_id'], ['reports.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'report_id', name='uq_user_report_fav')
    )


def downgrade():
    op.drop_table('favourite_reports')
