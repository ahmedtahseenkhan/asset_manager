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
  serial_number?: string | null;
  hardware_uuid?: string | null;
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
  target_type: 'cidr' | 'range' | 'hosts' | 'ad';
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
  credential_name?: string | null;
  device_id: number | null;
  error_code: string | null;
  error_message: string | null;
  duration_ms: number | null;
}

export interface ScanRunDetail extends ScanRun {
  hosts: ScanHostResult[];
}

// ── Device inventory (agent / credentialed scans) ────
export interface InventorySummary {
  source: string | null;
  collector_version: string | null;
  collected_at: string | null;
  sections_collected: string[];
  manufacturer: string | null; model: string | null; chassis_type: string | null; is_virtual: boolean | null;
  cpu: string | null; cpu_cores: number | null; cpu_logical: number | null; ram_gb: number | null; disk_gb: number | null;
  bios_vendor: string | null; bios_version: string | null; bios_date: string | null; motherboard: string | null;
  os_name: string | null; os_version: string | null; os_build: string | null; architecture: string | null;
  last_boot: string | null; logged_in_user: string | null; pending_reboot: boolean | null;
  tpm_present: boolean | null; tpm_ready: boolean | null; secure_boot: boolean | null;
  firewall_profiles: { profile: string; enabled: boolean | null }[] | null;
  firewall_ok: boolean | null; antivirus_ok: boolean | null; disk_encrypted: boolean | null;
  local_admin_count: number | null;
}

export interface DeviceInventoryData {
  summary: InventorySummary | null;
  patches?: { patch_id: string; description: string | null; installed_on: string | null; first_seen: string | null }[];
  services?: { name: string; display_name: string | null; state: string | null; start_mode: string | null; account: string | null }[];
  local_accounts?: { name: string; enabled: boolean | null; is_admin: boolean | null; last_logon: string | null }[];
  antivirus?: { name: string; enabled: boolean | null; up_to_date: boolean | null; definitions_date: string | null }[];
  volumes?: {
    name: string; filesystem: string | null; size_gb: number | null; free_gb: number | null;
    encryption_method: string | null; encrypted: boolean | null; encryption_status: string | null;
  }[];
  network_adapters?: {
    name: string; mac: string | null; ip_addresses: string[]; speed_mbps: number | null;
    dhcp: boolean | null; gateway: string | null; dns_servers: string[];
  }[];
  monitors?: { manufacturer: string | null; model: string | null; serial_number: string | null }[];
  printers?: { name: string; driver: string | null; port: string | null; is_network: boolean | null; is_default: boolean | null }[];
}

export interface DeviceChange {
  id: number;
  device_id: number;
  hostname?: string;
  category: 'software' | 'patch' | 'hardware' | 'os' | 'account' | 'security' | 'service' | 'monitor';
  change_type: 'added' | 'removed' | 'changed';
  item: string;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  severity: 'info' | 'warning';
  source: string | null;
  detected_at: string;
}

export interface EndpointHealth {
  inventoried: number;
  counts: Record<string, number>;
  labels: Record<string, string>;
  warnings_7d: number;
}

export interface AgentFleet {
  latest_version: string;
  agents: {
    device_id: number; hostname: string | null; status: string; os_name: string | null;
    version: string | null; outdated: boolean; last_report: string | null;
  }[];
}

export interface SshHostKey {
  id: number; host: string; port: number; key_type: string; fingerprint: string;
  first_seen: string | null; last_seen: string | null;
}

export interface CredentialTestResult {
  ok: boolean; host: string; method?: string; hostname?: string | null; os?: string | null;
  vendor?: string | null; note?: string; error_code?: string; message?: string;
}

// ── Report builder ───────────────────────────────────
export type ReportFieldType = 'string' | 'number' | 'date' | 'datetime' | 'bool' | 'enum' | 'list' | 'relation';

export interface ReportField {
  key: string; label: string; type: ReportFieldType; choices: string[] | null; filter_only: boolean;
}

export interface ReportEntity {
  key: string; label: string; category: string; description: string; licensed: boolean;
  default_columns: string[]; default_sort: string; link: 'device' | 'asset' | null; fields: ReportField[];
}

export interface ReportOperator { op: string; label: string; value: 'text' | 'list' | 'choice' | 'choices' | 'number' | 'date' | 'days' | 'none' }

export interface ReportCatalog { entities: ReportEntity[]; operators: Record<ReportFieldType, ReportOperator[]> }

export interface ReportFilter { field: string; op: string; value: string | number | null }

export interface ReportDefinition {
  entity: string;
  columns: string[];
  filters: ReportFilter[];
  match: 'all' | 'any';
  search?: string | null;
  group_by: string | null;
  sort: string | null;
  sort_dir: 'asc' | 'desc';
  chart: 'none' | 'bar' | 'pie';
}

export interface ReportRowsResult {
  kind: 'rows'; total: number; page: number; size: number; link: 'device' | 'asset' | null;
  columns: { key: string; label: string; type: ReportFieldType }[];
  rows: Record<string, unknown>[];
  summary: [string, string][];
}

export interface ReportGroupsResult {
  kind: 'groups'; total: number;
  group_field: { key: string; label: string; type: ReportFieldType };
  groups: { value: string | number | boolean | null; count: number }[];
  summary: [string, string][];
}

export type ReportResult = ReportRowsResult | ReportGroupsResult;

export interface LibraryReport {
  id: string; category: string; name: string; description: string; licensed: boolean; definition: ReportDefinition;
}

export interface SavedReport {
  id: number; name: string; description: string | null; definition: ReportDefinition;
  owner_id: number | null; shared: boolean; pinned: boolean; can_edit: boolean;
  schedule_cron: string | null; recipients: string[]; export_format: 'xlsx' | 'csv';
  last_sent_at: string | null; last_status: string | null;
}

export interface PinnedReport {
  id: number; name: string; chart: 'none' | 'bar' | 'pie';
  result: ReportResult | { kind: 'error'; message: string };
}

// ── Topology ─────────────────────────────────────────
export type TopologyRole = 'switch' | 'router' | 'windows' | 'mac' | 'linux' | 'printer' | 'phone' | 'device';

export interface TopologyNode {
  id: string; device_id: number | null; label: string; ip: string | null;
  kind: 'infrastructure' | 'endpoint' | 'external'; role: TopologyRole; model: string | null;
}

export interface TopologyEdge {
  id: string; source: string; target: string; kind: 'link' | 'access'; protocols: string[];
  source_port: string | null; target_port: string | null; vlan?: number | null;
}

export interface TopologyGraph {
  nodes: TopologyNode[]; edges: TopologyEdge[];
  stats: { infrastructure: number; external: number; endpoints: number; links: number; endpoints_capped: boolean;
           macs: number; last_collected: string | null };
}

export interface SwitchPort {
  id: number; if_index: number; name: string | null; alias: string | null; oper_up: boolean | null;
  admin_up: boolean | null; speed_mbps: number | null; vlan: number | null; mac_count: number; uplink: boolean;
  neighbors: { name: string | null; port: string | null; device_id: number | null; protocol: string }[];
  connected: { mac: string; ip: string | null; device_id: number | null; hostname: string | null }[];
}

export interface DeviceLocation {
  switch_id: number; switch: string | null; port: string | null; port_alias: string | null; port_id: number;
  vlan: number | null; mac: string; uplink: boolean; macs_on_port: number; last_seen: string | null;
}

// ── Virtualisation ──────────────────────────────────────
export type VmPowerState = 'on' | 'off' | 'suspended' | string;
export interface VmPlacementInfo {
  device_id: number; hostname: string | null; vm_name: string; platform: 'hyperv' | 'vmware' | string;
  instance_id: string | null; power_state: VmPowerState | null; guest_os: string | null; vcpus: number | null;
  memory_gb: number | null; disk_gb: number | null; tools_status: string | null; cluster: string | null;
  datacenter: string | null; last_seen: string | null;
}
export interface VmGuest extends VmPlacementInfo { ip: string | null; inventoried: boolean }
export interface DeviceVirtualization {
  host: VmPlacementInfo | null;
  guests: VmGuest[];
  totals: { guests: number; running: number; vcpus_running: number; memory_gb_running: number };
}

// ── Lifecycle (end of life, warranty) ───────────────────
export type EolStatus = 'unsupported' | 'ending_soon' | 'supported';
export interface LifecycleItem {
  kind: 'os' | 'software'; product_id: string; product: string; cycle: string; title: string;
  eol: string | null; support_end: string | null; extended: string | null; detail: string | null;
  status: EolStatus; days_left: number | null;
}
export interface DeviceWarranty {
  asset_id: number; asset_tag: string; warranty_end: string | null; purchase_date: string | null;
  status: 'expired' | 'ending_soon' | 'active' | null;
}
export interface DeviceLifecycleInfo { os: LifecycleItem | null; software: LifecycleItem[]; warranty: DeviceWarranty | null }
export interface LifecycleGroup {
  product_id: string; product: string; cycle: string; title: string; eol: string | null; extended: string | null;
  devices: number; status: EolStatus; days_left: number | null;
}
export interface LifecycleCatalogInfo {
  version: string; published: string; origin: 'bundled' | 'uploaded'; bundled_version: string; products: number;
  last_upload: { version: string; published: string; uploaded_at: string } | null;
}
export interface LifecycleSummary {
  counts: {
    active_devices: number; os_identified: number; os_unidentified: number; os_unsupported: number;
    os_ending_soon: number; software_unsupported_devices: number; warranty_expired: number;
    warranty_ending_soon: number; warranty_unknown: number;
  };
  ending_soon_days: number; warranty_soon_days: number;
  os: LifecycleGroup[]; software: LifecycleGroup[]; catalog: LifecycleCatalogInfo;
}
export interface LifecycleDeviceRow {
  device_id: number; hostname: string | null; last_seen: string | null; title: string; detail: string | null; eol: string | null;
}
export interface WarrantyImportResult {
  rows: number; updated: number; unchanged: number;
  device_only: { serial: string; device_id: number; hostname: string | null }[]; device_only_count: number;
  not_found: string[]; not_found_count: number; errors: { row: number; message: string }[];
}
export interface SoftwareCatalogInfo { version: string; categories: string[]; hidden_by_default: string[] }
export interface SoftwareProduct { product: string; installs: number; copies: number; vendor: string | null; category: string | null }

