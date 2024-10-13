"""Add plan_id to users table

Revision ID: f8944db0821e
Revises: 
Create Date: 2024-09-04 10:49:40.243940

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'f8944db0821e'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Check if the column exists before trying to add it
    conn = op.get_bind()
    column_exists_query = text("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='plan_id'")
    result = conn.execute(column_exists_query).fetchone()

    if not result:
        op.add_column('users', sa.Column('plan_id', sa.Integer(), nullable=False))
        op.create_foreign_key(None, 'users', 'plans', ['plan_id'], ['id'])

    # ### end Alembic commands ###


def downgrade():
    conn = op.get_bind()
    column_exists_query = text("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='plan_id'")
    result = conn.execute(column_exists_query).fetchone()

    if result:
        op.drop_constraint(None, 'users', type_='foreignkey')
        op.drop_column('users', 'plan_id')

    # ### end Alembic commands ###
