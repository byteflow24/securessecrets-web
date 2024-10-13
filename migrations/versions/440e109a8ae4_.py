from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision = '440e109a8ae4'
down_revision = 'e0ce9967201e'
branch_labels = None
depends_on = None


def column_exists(connection, table_name, column_name):
    inspector = Inspector.from_engine(connection)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():

    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.add_column(sa.Column('storage_limit', sa.Integer(), nullable=False, server_default='500'))



    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('storage_used', sa.Integer(), nullable=True))

    # After upgrading the database, populate the column
    op.execute('UPDATE users SET storage_used = 0 WHERE storage_used IS NULL')

    # Now make the column non-nullable
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('storage_used', existing_type=sa.Integer(), nullable=False)



def downgrade():
    connection = op.get_bind()

    # Check if 'storage_used' column exists in 'users' table
    if column_exists(connection, 'users', 'storage_used'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('storage_used')

    # Check if 'storage_limit' column exists in 'plans' table
    if column_exists(connection, 'plans', 'storage_limit'):
        with op.batch_alter_table('plans', schema=None) as batch_op:
            batch_op.drop_column('storage_limit')
