"""audit_jobs: Postgres-backed work queue (replaces Azure Storage Queue)

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_jobs_claimed_until", "audit_jobs", ["claimed_until"])


def downgrade() -> None:
    op.drop_index("ix_audit_jobs_claimed_until", table_name="audit_jobs")
    op.drop_table("audit_jobs")
