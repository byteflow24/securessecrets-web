"""Add received_time column to SharedSecret

Revision ID: f1393e76e317
Revises: f545f9d0aa67
Create Date: 2024-09-05 15:00:46.901324

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1393e76e317'
down_revision = 'f545f9d0aa67'
branch_labels = None
depends_on = None


def upgrade():
    # Step 1: Add the column as nullable
    with op.batch_alter_table('shared_secrets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('received_time', sa.TIMESTAMP(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # Drop the column in case of downgrade
    with op.batch_alter_table('shared_secrets', schema=None) as batch_op:
        batch_op.drop_column('received_time')

    # ### end Alembic commands ###
