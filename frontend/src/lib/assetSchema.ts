// Single source of truth for the asset attribute set — drives both the
// create/edit form and the read-only detail view so they never drift.

export type FieldType = 'text' | 'number' | 'date' | 'datetime' | 'textarea' | 'select';

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  options?: string[];       // for select
  placeholder?: string;
  fromDevice?: boolean;     // auto-filled from a linked discovered device
  full?: boolean;           // span both columns
}

export interface FieldGroup {
  title: string;
  fields: FieldDef[];
}

export const CATEGORY_OPTIONS = ['hardware', 'software', 'cloud', 'peripheral'];
export const CRITICALITY_OPTIONS = ['critical', 'high', 'medium', 'low'];
export const DATA_CLASS_OPTIONS = ['restricted', 'confidential', 'internal', 'public'];
export const LOG_STATUS_OPTIONS = ['onboarded', 'not_onboarded', 'inactive'];
export const MONITORING_OPTIONS = ['monitored', 'not_monitored', 'degraded'];
export const BACKUP_OPTIONS = ['protected', 'unprotected', 'failed', 'unknown'];

// name + category are handled specially in the form header; everything else here.
export const ASSET_GROUPS: FieldGroup[] = [
  {
    title: 'Identity',
    fields: [
      { key: 'asset_type', label: 'Asset Type', type: 'text', placeholder: 'firewall, laptop, server, vm…' },
      { key: 'serial_number', label: 'Serial Number', type: 'text' },
      { key: 'vendor', label: 'Manufacturer / Vendor', type: 'text' },
      { key: 'model', label: 'Model Number', type: 'text' },
      { key: 'firmware_version', label: 'Firmware Version', type: 'text' },
    ],
  },
  {
    title: 'Technical',
    fields: [
      { key: 'ip_address', label: 'IP Address', type: 'text', fromDevice: true },
      { key: 'mac_address', label: 'MAC Address', type: 'text', fromDevice: true },
      { key: 'os_name', label: 'Operating System', type: 'text', fromDevice: true },
      { key: 'os_version', label: 'OS Version', type: 'text', fromDevice: true },
      { key: 'applications', label: 'Applications / Services', type: 'textarea', full: true,
        placeholder: 'comma-separated' },
    ],
  },
  {
    title: 'Network & Ownership',
    fields: [
      { key: 'network_zone', label: 'Network Zone / VLAN', type: 'text' },
      { key: 'location', label: 'Physical Location / Cloud Region', type: 'text' },
      { key: 'department', label: 'Department / Owner', type: 'text' },
      { key: 'point_of_contact', label: 'Point of Contact', type: 'text' },
    ],
  },
  {
    title: 'Security & Compliance',
    fields: [
      { key: 'criticality', label: 'Criticality', type: 'select', options: CRITICALITY_OPTIONS },
      { key: 'data_classification', label: 'Data Classification', type: 'select', options: DATA_CLASS_OPTIONS },
      { key: 'compliance', label: 'Compliance Requirement', type: 'text', placeholder: 'PCI-DSS, ISO 27001…' },
    ],
  },
  {
    title: 'Log Source & Monitoring',
    fields: [
      { key: 'log_source_status', label: 'Log Source Status', type: 'select', options: LOG_STATUS_OPTIONS },
      { key: 'log_source_type', label: 'Log Source Type', type: 'text', placeholder: 'Syslog, WinEventLog, CEF…' },
      { key: 'log_forwarding_destination', label: 'Log Forwarding Destination', type: 'text', placeholder: 'siem.corp.local:514' },
      { key: 'last_log_received', label: 'Last Log Received', type: 'datetime' },
      { key: 'monitoring_status', label: 'Monitoring Status', type: 'select', options: MONITORING_OPTIONS },
      { key: 'backup_status', label: 'Backup Status', type: 'select', options: BACKUP_OPTIONS },
      { key: 'last_vulnerability_scan', label: 'Last Vulnerability Scan', type: 'date' },
    ],
  },
  {
    title: 'Procurement & Lifecycle',
    fields: [
      { key: 'purchase_date', label: 'Purchase Date', type: 'date' },
      { key: 'purchase_cost', label: 'Purchase Cost', type: 'number' },
      { key: 'warranty_end', label: 'Warranty End', type: 'date' },
      { key: 'eol_eos_date', label: 'EOL / EOS Date', type: 'date' },
    ],
  },
  {
    title: 'Governance',
    fields: [
      { key: 'last_reviewed_date', label: 'Last Reviewed Date', type: 'date' },
      { key: 'reviewer', label: 'Reviewer', type: 'text' },
      { key: 'notes', label: 'Notes', type: 'textarea', full: true },
    ],
  },
];

// All editable keys (excludes name/category which the form handles in its header).
export const ASSET_FIELD_KEYS = ASSET_GROUPS.flatMap((g) => g.fields.map((f) => f.key));

// Colour classes for the badge-style enum fields.
export const ENUM_BADGE: Record<string, Record<string, string>> = {
  criticality: {
    critical: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',
    high: 'bg-orange-500/20 text-orange-400 ring-orange-500/30',
    medium: 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
    low: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
  },
  data_classification: {
    restricted: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',
    confidential: 'bg-orange-500/20 text-orange-400 ring-orange-500/30',
    internal: 'bg-blue-500/20 text-blue-400 ring-blue-500/30',
    public: 'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30',
  },
  log_source_status: {
    onboarded: 'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30',
    not_onboarded: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',
    inactive: 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
  },
  monitoring_status: {
    monitored: 'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30',
    not_monitored: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',
    degraded: 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
  },
  backup_status: {
    protected: 'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30',
    unprotected: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',
    failed: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',
    unknown: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
  },
};
