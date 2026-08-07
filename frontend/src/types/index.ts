export interface APIResponse<T> {
  data: T;
  message: string;
  status: number;
}

export interface User {
  id: number;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface DeviceSource {
  id: number;
  source_name: string;
  source_uid: string;
  raw_data: Record<string, any>;
  last_synced: string;
}

export interface Device {
  id: number;
  hostname: string | null;
  fqdn: string | null;
  ip_addresses: string[];
  mac_addresses: string[];
  os_name: string | null;
  os_version: string | null;
  domain: string | null;
  ou: string | null;
  first_seen: string;
  last_seen: string | null;
  status: string;
  sources: DeviceSource[];
}

export interface DeviceListOut {
  items: Device[];
  total: number;
  page: number;
  size: number;
}

export interface ConnectorStatus {
  name: string;
  display_name: string;
  is_configured: boolean;
  is_enabled: boolean;
  last_run: string | null;
  last_status: string | null;
  schema_definition: Record<string, any>;
  config?: Record<string, any>;
}

export interface DashboardSummary {
  total_devices: number;
  active_devices: number;
  stale_devices: number;
  coverage_gap_count: number;
  os_distribution: { name: string; value: number }[];
  source_distribution: { name: string; value: number }[];
}

export interface CoverageGapDevice {
  device_id: number;
  hostname: string | null;
  fqdn: string | null;
  ip_addresses: string[];
  os_name: string | null;
  known_sources: string[];
  missing_sources: string[];
}

export interface CoverageGapSummary {
  enabled_sources: string[];
  total_active_devices: number;
  devices_with_gaps: number;
  missing_per_source: { source: string; count: number }[];
  gaps: CoverageGapDevice[];
}
