"""add User.created_at for trending account-age gate

Revision ID: 1dab4f32bde6
Revises: a9aca3a8ec38
Create Date: 2026-05-06 10:00:45.590116

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1dab4f32bde6'
down_revision = 'a9aca3a8ec38'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))

    # Backfill existing accounts to 30 days ago so they pass the 1-day age
    # gate immediately. We don't know their real signup date, so erring on
    # the older side avoids accidentally locking long-time users out of
    # the Trending page.
    op.execute("""
        UPDATE users
        SET created_at = datetime('now', '-30 days')
        WHERE created_at IS NULL
    """)


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('created_at')
