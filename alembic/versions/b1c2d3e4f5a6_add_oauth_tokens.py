"""add oauth_tokens table

Revision ID: b1c2d3e4f5a6
Revises: a3e7c2b9f1d5
Create Date: 2026-05-25 00:00:00.000000

Stores long-lived OAuth access tokens with Fernet-encrypted KLAS credentials
so the server can silently re-authenticate when the 1-hour KLAS session expires.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a3e7c2b9f1d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("student_id", sa.String(length=50), nullable=False),
        sa.Column("encrypted_student_id", sa.Text(), nullable=False),
        sa.Column("encrypted_password", sa.Text(), nullable=False),
        sa.Column("klas_session_token", sa.Text(), nullable=True),
        sa.Column("klas_session_expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("access_token"),
        sa.UniqueConstraint("student_id"),
    )
    op.create_index("ix_oauth_tokens_access_token", "oauth_tokens", ["access_token"])
    op.create_index("ix_oauth_tokens_student_id", "oauth_tokens", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_tokens_student_id", table_name="oauth_tokens")
    op.drop_index("ix_oauth_tokens_access_token", table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
