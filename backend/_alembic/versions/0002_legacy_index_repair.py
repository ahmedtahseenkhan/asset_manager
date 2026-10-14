"""repair indexes that create_all-era installs never received

Before Alembic, the schema came from create_all, which adds new tables but
never alters existing ones. Installs created then can have stale indexes.
Idempotent: a no-op on databases built from the baseline.

Revision ID: 0002_legacy_index_repair
Revises: 0001_baseline
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op


revision: str = '0002_legacy_index_repair'
down_revision: Union[str, None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Added to the model after audit_logs.row_hash existed.
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_row_hash ON audit_logs (row_hash)")
    # Superseded by ix_installed_software_device_id.
    op.execute("DROP INDEX IF EXISTS ix_software_device")


def downgrade() -> None:
    # Nothing to undo: the baseline already defines the resulting state.
    pass
