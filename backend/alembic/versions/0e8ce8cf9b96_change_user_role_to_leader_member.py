"""change user_role to leader_member"""

revision = '0e8ce8cf9b96'
down_revision = '3c8e8e01c92a'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.execute("ALTER TYPE user_role RENAME TO user_role_old")

    op.execute("CREATE TYPE user_role AS ENUM ('leader', 'member')")

    op.execute("""
        ALTER TABLE users
        ALTER COLUMN role TYPE user_role
        USING (
            CASE role::text
                WHEN 'admin' THEN 'leader'
                WHEN 'leader' THEN 'leader'
                WHEN 'editor' THEN 'member'
                WHEN 'viewer' THEN 'member'
                ELSE 'member'
            END
        )::user_role
    """)

    op.execute("DROP TYPE user_role_old")


def downgrade() -> None:
    op.execute("ALTER TYPE user_role RENAME TO user_role_new")
    op.execute("CREATE TYPE user_role AS ENUM ('admin', 'editor', 'viewer')")

    op.execute("""
        ALTER TABLE users
        ALTER COLUMN role TYPE user_role
        USING (
            CASE role::text
                WHEN 'leader' THEN 'admin'
                WHEN 'member' THEN 'viewer'
                ELSE 'viewer'
            END
        )::user_role
    """)

    op.execute("DROP TYPE user_role_new")
