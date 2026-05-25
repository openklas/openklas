"""create users table

Revision ID: 0001_create_users
Revises:
Create Date: 2026-05-26 00:00:00.000000

Initial migration — creates the users table that was previously created
manually and never tracked in Alembic.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_create_users"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("major", sa.String(length=100), nullable=True),
        sa.Column("date_of_birth", sa.String(length=50), nullable=True),
        sa.Column("gender", sa.String(length=20), nullable=True),
        sa.Column("nationality", sa.String(length=50), nullable=True),
        sa.Column("profile_image", sa.Text(), nullable=True),
        sa.Column("room_no", sa.String(length=50), nullable=True),
        sa.Column("nickname", sa.String(length=100), nullable=True),
        sa.Column("dept_name", sa.String(length=100), nullable=True),
        sa.Column("work_category", sa.String(length=100), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="worker"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'active')", name="users_status_check"),
        sa.CheckConstraint("role IN ('admin', 'worker')", name="users_role_check"),
    )


def downgrade() -> None:
    op.drop_table("users")
