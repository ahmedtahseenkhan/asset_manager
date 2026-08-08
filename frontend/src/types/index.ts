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

// ── ITAM: application license ─────────────────────────
export interface LicenseStatus {
  status: 'valid' | 'grace' | 'expired' | 'invalid' | 'missing';
  operational: boolean;
  reason: string;
  customer: string | null;
  license_id: string | null;
  issued_at: string | null;
  expires_at: string | null;
  grace_days: number | null;
  max_assets: number | null;
  max_users: number | null;
  modules: string[];
  usage: { users?: number; assets?: number };
}

// ── ITAM: managed assets ──────────────────────────────
export interface Asset {
  id: number;
  asset_tag: string;
  name: string;
  category: 'hardware' | 'software' | 'cloud' | 'peripheral';
  asset_type: string | null;
  lifecycle_state: string;
  serial_number: string | null;
  vendor: string | null;
  model: string | null;
  location: string | null;
  department: string | null;
  assigned_to: number | null;
  assignee_username: string | null;
  purchase_date: string | null;
  purchase_cost: string | null;
  currency: string;
  warranty_end: string | null;
  custom_fields: Record<string, unknown>;
  notes: string | null;
  device_id: number | null;
  device_hostname: string | null;
  created_at: string;
  updated_at: string;
}

export interface LifecycleEvent {
  id: number;
  from_state: string | null;
  to_state: string;
  actor: string | null;
  note: string | null;
  occurred_at: string;
}

export interface AssetDetail extends Asset {
  lifecycle_events: LifecycleEvent[];
  allowed_transitions: string[];
  relationships: AssetRelationships;
}

export interface AssetListOut {
  items: Asset[];
  total: number;
  page: number;
  size: number;
}

// ── ITAM: reconciliation & CMDB relationships ─────────
export interface UnlinkedDevice {
  id: number;
  hostname: string | null;
  fqdn: string | null;
  ip_addresses: string[];
  os_name: string | null;
  os_version: string | null;
  last_seen: string | null;
  suggested_asset: { id: number; asset_tag: string; name: string } | null;
}

export interface RelationshipEdge {
  id: number;
  type: string;
  label: string;
  asset: { id: number; asset_tag: string; name: string; category: string; lifecycle_state: string };
}

export interface AssetRelationships {
  outgoing: RelationshipEdge[];
  incoming: RelationshipEdge[];
}
