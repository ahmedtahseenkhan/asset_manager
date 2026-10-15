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
  firmware_version: string | null;
  // Technical identity (auto-filled from linked device)
  ip_address: string | null;
  mac_address: string | null;
  os_name: string | null;
  os_version: string | null;
  applications: string | null;
  // Network & ownership
  network_zone: string | null;
  location: string | null;
  department: string | null;
  assigned_to: number | null;
  assignee_username: string | null;
  point_of_contact: string | null;
  // Security / compliance
  criticality: 'critical' | 'high' | 'medium' | 'low' | null;
  data_classification: 'restricted' | 'confidential' | 'internal' | 'public' | null;
  compliance: string | null;
  // Log source / monitoring
  log_source_status: 'onboarded' | 'not_onboarded' | 'inactive' | null;
  log_source_type: string | null;
  log_forwarding_destination: string | null;
  last_log_received: string | null;
  monitoring_status: 'monitored' | 'not_monitored' | 'degraded' | null;
  backup_status: 'protected' | 'unprotected' | 'failed' | 'unknown' | null;
  last_vulnerability_scan: string | null;
  // Procurement / lifecycle / governance
  purchase_date: string | null;
  purchase_cost: string | null;
  currency: string;
  warranty_end: string | null;
  eol_eos_date: string | null;
  last_reviewed_date: string | null;
  reviewer: string | null;
  // Misc
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

// ── ITAM: contracts & entitlements ────────────────────
export interface Contract {
  id: number;
  name: string;
  contract_type: 'lease' | 'support' | 'maintenance' | 'subscription';
  vendor: string | null;
  reference_no: string | null;
  start_date: string | null;
  end_date: string | null;
  notice_days: number;
  cost: string | null;
  currency: string;
  auto_renews: boolean;
  custom_fields: Record<string, unknown>;
  asset_count: number;
  created_at: string;
  updated_at: string;
}

export interface ContractDetail extends Contract {
  assets: { id: number; asset_tag: string; name: string; category: string; lifecycle_state: string }[];
  entitlements: { id: number; product: string; license_model: string; seats_purchased: number | null; expires_on: string | null }[];
}

export interface ContractListOut {
  items: Contract[];
  total: number;
  page: number;
  size: number;
}

export interface Entitlement {
  id: number;
  product: string;
  vendor: string | null;
  license_model: 'per_seat' | 'per_device' | 'site' | 'subscription';
  seats_purchased: number | null;
  seats_used: number;
  has_key: boolean;
  key_hint: string | null;
  contract_id: number | null;
  contract_name: string | null;
  expires_on: string | null;
  custom_fields: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface EntitlementAssignment {
  id: number;
  asset_id: number | null;
  asset_tag: string | null;
  asset_name: string | null;
  user_id: number | null;
  username: string | null;
  assigned_at: string;
}

export interface EntitlementDetail extends Entitlement {
  assignments: EntitlementAssignment[];
  license_key: string | null;
}

export interface EntitlementListOut {
  items: Entitlement[];
  total: number;
  page: number;
  size: number;
}

// ── ITAM: notifications ───────────────────────────────
export interface SmtpSettingsOut {
  configured: boolean;
  host?: string;
  port?: number;
  username?: string | null;
  has_password?: boolean;
  from_address?: string;
  use_starttls?: boolean;
  enabled?: boolean;
}

export interface AlertRule {
  rule_type: string;
  days_before: number;
  recipients: string[];
  enabled: boolean;
}

export interface NotificationLogEntry {
  id: number;
  rule_type: string;
  subject: string;
  recipients: string[];
  item_count: number;
  status: 'sent' | 'failed';
  error: string | null;
  created_at: string;
}

// ── Scanning ─────────────────────────────────────────
export interface CredentialTypeSpec {
  label: string;
  username: 'required' | 'none';
  secrets: { name: string; required: boolean }[];
  params: Record<string, string[] | null>;   // allowed values, or null for free text
}

export interface ScanCredential {
  id: number;
  name: string;
  cred_type: string;
  type_label: string;
  username: string | null;
  params: Record<string, string | number>;
  secrets_set: string[];
  description: string | null;
  target_count?: number;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  last_success_at: string | null;
}

export type ScanRunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface ScanTarget {
  id: number;
  name: string;
  enabled: boolean;
  target_type: 'cidr' | 'range' | 'hosts';
  value: string;
  exclusions: string;
  schedule_cron: string | null;
  methods: string[];
  concurrency: number;
  timeout_ms: number;
  deep_probe: boolean;
  credential_ids: number[];
  last_run_at: string | null;
  last_status: ScanRunStatus | null;
  running: boolean;
}

export interface ScanRun {
  id: number;
  target_id: number | null;
  target_name: string;
  trigger: 'manual' | 'schedule';
  status: ScanRunStatus;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  hosts_total: number;
  hosts_alive: number;
  hosts_inventoried: number;
  hosts_failed: number;
}

export interface ScanHostResult {
  id: number;
  ip: string;
  hostname: string | null;
  status: 'alive' | 'inventoried' | 'failed';
  method: string | null;
  credential_id: number | null;
  device_id: number | null;
  error_code: string | null;
  error_message: string | null;
  duration_ms: number | null;
}

export interface ScanRunDetail extends ScanRun {
  hosts: ScanHostResult[];
}
