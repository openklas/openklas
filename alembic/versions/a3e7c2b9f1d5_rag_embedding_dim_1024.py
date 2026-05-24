"""resize document_chunks.embedding from 384 to 1024 (voyage-3)

Revision ID: a3e7c2b9f1d5
Revises: f7a2b9c4d1e3
Create Date: 2026-05-24 00:00:00.000000

The RAG embedder swapped from local sentence-transformers (bge-small-en-v1.5,
384-dim) to Voyage AI (voyage-3, 1024-dim). pgvector requires the column
dimension to match the embedding being inserted, so all existing rows have to
be cleared and the column resized.

Existing ingested PDFs need to be re-uploaded after this migration runs. For
the personal/single-user deployment this is acceptable; PDFs are kept locally
by the user.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "a3e7c2b9f1d5"
down_revision: Union[str, Sequence[str], None] = "f7a2b9c4d1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_DIM = 1024
OLD_DIM = 384


def upgrade() -> None:
    # Existing 384-dim embeddings are incompatible. Wipe them so the column
    # resize is valid and so users get prompted to re-ingest with the new
    # embedder.
    op.execute("TRUNCATE TABLE document_chunks RESTART IDENTITY")
    op.execute("UPDATE documents SET total_chunks = 0")

    op.alter_column(
        "document_chunks",
        "embedding",
        existing_type=Vector(OLD_DIM),
        type_=Vector(NEW_DIM),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute("TRUNCATE TABLE document_chunks RESTART IDENTITY")
    op.execute("UPDATE documents SET total_chunks = 0")

    op.alter_column(
        "document_chunks",
        "embedding",
        existing_type=Vector(NEW_DIM),
        type_=Vector(OLD_DIM),
        existing_nullable=False,
    )
