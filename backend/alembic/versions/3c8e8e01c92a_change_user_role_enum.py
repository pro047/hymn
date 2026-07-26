"""change user role enum"""

revision = '3c8e8e01c92a'
down_revision = '1c1a4b9b2e7c'
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute("ALTER TYPE user_role RENAME TO user_role_old")

    op.execute("CREATE TYPE user_role AS ENUM ('admin', 'leader', 'member')")

    op.execute("""
        ALTER TABLE users
        ALTER COLUMN role TYPE user_role
        USING (
            CASE role
                WHEN 'editor' THEN 'leader'
                WHEN 'viewer' THEN 'member'
                ELSE role::text
            END
        )::text::user_role
    """)

    op.execute("DROP TYPE user_role_old")


def downgrade() -> None:
    op.execute("ALTER TYPE user_role RENAME TO user_role_new")
    op.execute("CREATE TYPE user_role AS ENUM ('admin', 'editor', 'viewer')")

    op.execute("""
        UPDATE users
        SET role = CASE role
            WHEN 'leader' THEN 'editor'
            WHEN 'member' THEN 'viewer'
            ELSE role
        END
    """)

    op.execute("""
        ALTER TABLE users
        ALTER COLUMN role TYPE user_role
        USING role::text::user_role
    """)

    op.execute("DROP TYPE user_role_new")
