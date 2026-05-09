"""add expires_at to reports for 7-day auto-expiry

Revision ID: a15abbae8385
Revises: 7902bea5d3c6
Create Date: 2026-05-06 09:25:12.903732

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a15abbae8385'
down_revision = '7902bea5d3c6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('expires_at', sa.DateTime(), nullable=True))

    # Backfill existing reports — set expires_at = created_at + 7 days so old
    # reports decay on the same schedule new ones do, rather than living forever.
    op.execute("""
        UPDATE reports
        SET expires_at = datetime(created_at, '+7 days')
        WHERE expires_at IS NULL
    """)


def downgrade():
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.drop_column('expires_at')
