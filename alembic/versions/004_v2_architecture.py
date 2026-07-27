"""V2 architecture: dead_letter_jobs, rate_limits, idempotency columns

Revision ID: 004
Revises: 003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dead letter jobs (ticket 07)
    op.create_table(
        "dead_letter_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("audit_id", sa.String(64), nullable=False, index=True),
        sa.Column("error_message", sa.Text, nullable=False),
        sa.Column("original_payload", JSONB, nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Rate limit tracking (ticket 08)
    op.create_table(
        "rate_limit_hits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column("hit_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rate_limit_hits_key_endpoint_hit_at", "rate_limit_hits", ["key", "endpoint", "hit_at"])

    # Idempotency + versioning columns on audits (ticket 09)
    op.add_column("audits", sa.Column("file_hash", sa.String(64), nullable=True))
    op.add_column("audits", sa.Column("prompt_hash", sa.String(64), nullable=True))
    op.add_column("audits", sa.Column("model_version", sa.String(128), nullable=True))
    op.create_index("ix_audits_file_hash", "audits", ["file_hash"])


def downgrade() -> None:
    op.drop_index("ix_audits_file_hash", table_name="audits")
    op.drop_column("audits", "model_version")
    op.drop_column("audits", "prompt_hash")
    op.drop_column("audits", "file_hash")
    op.drop_index("ix_rate_limit_hits_key_endpoint_hit_at", table_name="rate_limit_hits")
    op.drop_table("rate_limit_hits")
    op.drop_table("dead_letter_jobs")
