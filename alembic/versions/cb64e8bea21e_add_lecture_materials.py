"""add lecture_materials

Revision ID: cb64e8bea21e
Revises: 
Create Date: 2026-05-13 01:31:32.187323

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'cb64e8bea21e'
down_revision: Union[str, Sequence[str], None] = "0001_create_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lecture_materials',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('board_no', sa.Integer(), nullable=False),
        sa.Column('subject_code', sa.String(length=100), nullable=False),
        sa.Column('subject_name', sa.String(length=200), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('semester', sa.String(length=1), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('post_title', sa.String(length=300), nullable=False),
        sa.Column('atch_file_id', sa.String(length=100), nullable=False),
        sa.Column('file_sn', sa.Integer(), nullable=False),
        sa.Column('file_name', sa.String(length=300), nullable=False),
        sa.Column('extracted_text', sa.Text(), nullable=False),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('subject_code', 'atch_file_id', 'file_sn', name='uq_lecture_file'),
    )
    op.create_index('ix_lecture_board_no', 'lecture_materials', ['board_no'], unique=False)
    op.create_index('ix_lecture_subject_code', 'lecture_materials', ['subject_code'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_lecture_subject_code', table_name='lecture_materials')
    op.drop_index('ix_lecture_board_no', table_name='lecture_materials')
    op.drop_table('lecture_materials')
