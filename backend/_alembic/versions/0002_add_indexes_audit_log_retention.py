"""Add indexes, constraints, audit_log table, and retention fields

Revision ID: 0002_indexes_audit_retention
Revises: 6025a3e0fcc5
Create Date: 2026-05-02

Changes from initial schema:
- devices.fqdn: unique constraint
- devices: indexes on os_name, last_seen, status; composite (hostname, status)
- device_sources.source_uid: nullable (was NOT NULL)
- device_sources: drop stale source_uid index, add unique (device_id, source_name),
                  add composite (source_name, last_synced)
- New table: audit_logs
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0002_indexes_audit_retention'
down_revision: Union[str, None] = '6025a3e0fcc5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── devices: new indexes & unique constraint on fqdn ────────────────────
    op.create_index('ix_devices_os_name',  'devices', ['os_name'],  unique=False)
    op.create_index('ix_devices_last_seen', 'devices', ['last_seen'], unique=False)
    op.create_index('ix_devices_status',   'devices', ['status'],   unique=False)
    op.create_index('ix_devices_hostname_status', 'devices', ['hostname', 'status'], unique=False)

    # Make fqdn unique (was just indexed).
    # Drop the old plain index first, then recreate as unique.
    op.drop_index('ix_devices_fqdn', table_name='devices')
    op.create_index('ix_devices_fqdn', 'devices', ['fqdn'], unique=True)

    # ── device_sources: nullable source_uid, new unique + composite index ───
    op.alter_column('device_sources', 'source_uid', nullable=True)

    # Drop old plain source_uid index (column is now nullable, lookup less useful alone)
    op.drop_index('ix_device_sources_source_uid', table_name='device_sources')

    # Unique constraint on (device_id, source_name) — one row per connector per device
    op.create_unique_constraint('uq_device_source', 'device_sources', ['device_id', 'source_name'])

    # Composite index for staleness queries
    op.create_index('ix_device_sources_last_synced', 'device_sources', ['source_name', 'last_synced'], unique=False)

    # ── audit_logs table ────────────────────────────────────────────────────
    op.create_table(
        'audit_logs',
        sa.Column('id',            sa.Integer(),                  nullable=False),
        sa.Column('user_id',       sa.Integer(),                  nullable=True),
        sa.Column('username',      sa.String(length=255),         nullable=True),
        sa.Column('action',        sa.String(length=100),         nullable=False),
        sa.Column('resource_type', sa.String(length=100),         nullable=True),
        sa.Column('resource_id',   sa.String(length=255),         nullable=True),
        sa.Column('detail',        sa.JSON(),                     nullable=True),
        sa.Column('ip_address',    sa.String(length=64),          nullable=True),
        sa.Column('created_at',    sa.DateTime(timezone=True),
                  server_default=sa.text('now()'),                nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_id',        'audit_logs', ['id'],        unique=False)
    op.create_index('ix_audit_logs_user_id',   'audit_logs', ['user_id'],   unique=False)
    op.create_index('ix_audit_logs_action',    'audit_logs', ['action'],    unique=False)
    op.create_index('ix_audit_logs_created_at','audit_logs', ['created_at'],unique=False)


def downgrade() -> None:
    op.drop_table('audit_logs')

    op.drop_index('ix_device_sources_last_synced',  table_name='device_sources')
    op.drop_constraint('uq_device_source',           table_name='device_sources', type_='unique')
    op.create_index('ix_device_sources_source_uid',  'device_sources', ['source_uid'], unique=False)
    op.alter_column('device_sources', 'source_uid', nullable=False)

    op.drop_index('ix_devices_hostname_status', table_name='devices')
    op.drop_index('ix_devices_status',          table_name='devices')
    op.drop_index('ix_devices_last_seen',       table_name='devices')
    op.drop_index('ix_devices_os_name',         table_name='devices')
    op.drop_index('ix_devices_fqdn',            table_name='devices')
    op.create_index('ix_devices_fqdn', 'devices', ['fqdn'], unique=False)
