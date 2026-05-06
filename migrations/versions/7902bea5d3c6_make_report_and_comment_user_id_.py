"""make report and comment user_id nullable to anonymise on account delete

Revision ID: 7902bea5d3c6
Revises: 216561a7caf7
Create Date: 2026-05-06 09:17:52.487934

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7902bea5d3c6'
down_revision = '216561a7caf7'
branch_labels = None
depends_on = None


def upgrade():
    # Drop NOT NULL on the FK so deleting a user can NULL these out instead of
    # cascading into the report / comment rows themselves.
    with op.batch_alter_table('comments', schema=None) as batch_op:
        batch_op.alter_column('user_id',
               existing_type=sa.INTEGER(),
               nullable=True)

    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.alter_column('user_id',
               existing_type=sa.INTEGER(),
               nullable=True)


def downgrade():
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.alter_column('user_id',
               existing_type=sa.INTEGER(),
               nullable=False)

    with op.batch_alter_table('comments', schema=None) as batch_op:
        batch_op.alter_column('user_id',
               existing_type=sa.INTEGER(),
               nullable=False)
