import type { ReportDefinition, ReportFilter } from '../types';

// Dashboard health tiles (?health=…) as report filters; mirrors backend/services/endpoint_health.py.
const HEALTH_FILTERS: Record<string, ReportFilter> = {
  no_antivirus: { field: 'antivirus_ok', op: 'is_false', value: null },
  firewall_off: { field: 'firewall_ok', op: 'is_false', value: null },
  not_encrypted: { field: 'disk_encrypted', op: 'is_false', value: null },
  pending_reboot: { field: 'pending_reboot', op: 'is_true', value: null },
  admin_sprawl: { field: 'local_admin_count', op: 'gte', value: 3 },
  stale_inventory: { field: 'collected_at', op: 'older_than_days', value: 7 },
};

export function devicesExport(opts: { search?: string; os?: string; health?: string }): ReportDefinition {
  const filters: ReportFilter[] = [];
  if (opts.os) filters.push({ field: 'os_family', op: 'contains', value: opts.os });
  if (opts.health && HEALTH_FILTERS[opts.health]) filters.push(HEALTH_FILTERS[opts.health]);
  return {
    entity: 'devices', match: 'all', filters, search: opts.search || null, group_by: null,
    columns: ['hostname', 'fqdn', 'ip_addresses', 'os_name', 'os_version', 'domain', 'serial_number',
              'manufacturer', 'model', 'status', 'last_seen'],
    sort: 'hostname', sort_dir: 'asc', chart: 'none',
  };
}

export function assetsExport(opts: { search?: string; category?: string; state?: string }): ReportDefinition {
  const filters: ReportFilter[] = [];
  if (opts.category) filters.push({ field: 'category', op: 'eq', value: opts.category });
  if (opts.state) filters.push({ field: 'lifecycle_state', op: 'eq', value: opts.state });
  return {
    entity: 'assets', match: 'all', filters, search: opts.search || null, group_by: null,
    columns: ['asset_tag', 'name', 'category', 'asset_type', 'lifecycle_state', 'serial_number', 'vendor', 'model',
              'department', 'location', 'point_of_contact', 'purchase_date', 'purchase_cost', 'warranty_end'],
    sort: 'asset_tag', sort_dir: 'asc', chart: 'none',
  };
}
