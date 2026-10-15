import { apiClient } from './client';
import type {
  DashboardSummary, CoverageGapSummary, APIResponse, DeviceListOut, Device, ConnectorStatus,
  LicenseStatus, Asset, AssetDetail, AssetListOut, UnlinkedDevice,
  Contract, ContractDetail, ContractListOut, EntitlementDetail, EntitlementListOut,
  SmtpSettingsOut, AlertRule, NotificationLogEntry,
  CredentialTypeSpec, ScanCredential, ScanTarget, ScanRun, ScanRunDetail,
  DeviceInventoryData, DeviceChange, EndpointHealth, AgentFleet,
} from '../types';

export const getDashboardSummary = () => {
  return apiClient.get<never, APIResponse<DashboardSummary>>('/dashboard/summary');
};

export const getCoverageGaps = () => {
  return apiClient.get<never, APIResponse<CoverageGapSummary>>('/dashboard/coverage-gaps');
};

export const getAdminUsers = () =>
  apiClient.get<never, APIResponse<any[]>>('/admin/users');

export const setUserStatus = (id: number, active: boolean) =>
  apiClient.patch<never, APIResponse<any>>(`/admin/users/${id}/status`, null, { params: { active } });

export const getAuditLogs = (page = 1, size = 50, params = {}) =>
  apiClient.get<never, APIResponse<any>>('/admin/audit-logs', { params: { page, size, ...params } });

export const runRetention = () =>
  apiClient.post<never, APIResponse<any>>('/admin/retention/run');

export const getDevices = (page = 1, size = 50, params = {}) => {
  return apiClient.get<never, APIResponse<DeviceListOut>>('/devices', {
    params: { page, size, ...params },
  });
};

export const getDeviceById = (id: number) => {
  return apiClient.get<never, APIResponse<Device>>(`/devices/${id}`);
};

export const getConnectors = () => {
  return apiClient.get<never, APIResponse<ConnectorStatus[]>>('/connectors');
};

export const saveConnectorConfig = (name: string, data: any) => {
  return apiClient.post<never, APIResponse<any>>(`/connectors/${name}/config`, data);
};

export const testConnectorConnection = (name: string, config: any) => {
  return apiClient.post<never, APIResponse<boolean>>(`/connectors/${name}/test`, config);
};

export const triggerConnectorSync = (name: string) => {
  return apiClient.post<never, APIResponse<string>>(`/connectors/${name}/sync`);
};

// ── ITAM: license ─────────────────────────────────────
export const getLicenseStatus = () =>
  apiClient.get<never, APIResponse<LicenseStatus>>('/license/status');

export const uploadLicense = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return apiClient.post<never, APIResponse<any>>('/license/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

// ── ITAM: assets ──────────────────────────────────────
export const getAssets = (page = 1, size = 50, params = {}) =>
  apiClient.get<never, APIResponse<AssetListOut>>('/assets', { params: { page, size, ...params } });

export const getAssetById = (id: number) =>
  apiClient.get<never, APIResponse<AssetDetail>>(`/assets/${id}`);

export const createAsset = (data: Partial<Asset>) =>
  apiClient.post<never, APIResponse<AssetDetail>>('/assets', data);

export const updateAsset = (id: number, data: Partial<Asset>) =>
  apiClient.patch<never, APIResponse<AssetDetail>>(`/assets/${id}`, data);

export const transitionAsset = (id: number, to_state: string, note?: string) =>
  apiClient.post<never, APIResponse<AssetDetail>>(`/assets/${id}/transition`, { to_state, note });

export const deleteAsset = (id: number) =>
  apiClient.delete<never, APIResponse<boolean>>(`/assets/${id}`);

// ── ITAM: reconciliation & relationships ──────────────
export const getUnlinkedDevices = () =>
  apiClient.get<never, APIResponse<UnlinkedDevice[]>>('/reconciliation/devices');

export const adoptDevices = (device_ids: number[]) =>
  apiClient.post<never, APIResponse<{ id: number; asset_tag: string; name: string }[]>>('/reconciliation/adopt', { device_ids });

export const linkDevice = (device_id: number, asset_id: number) =>
  apiClient.post<never, APIResponse<any>>('/reconciliation/link', { device_id, asset_id });

export const addRelationship = (assetId: number, target_asset_id: number, relationship_type: string) =>
  apiClient.post<never, APIResponse<AssetDetail>>(`/assets/${assetId}/relationships`, { target_asset_id, relationship_type });

export const removeRelationship = (assetId: number, relId: number) =>
  apiClient.delete<never, APIResponse<AssetDetail>>(`/assets/${assetId}/relationships/${relId}`);

// ── ITAM: contracts ───────────────────────────────────
export const getContracts = (page = 1, size = 50, params = {}) =>
  apiClient.get<never, APIResponse<ContractListOut>>('/contracts', { params: { page, size, ...params } });

export const getContractById = (id: number) =>
  apiClient.get<never, APIResponse<ContractDetail>>(`/contracts/${id}`);

export const createContract = (data: Partial<Contract>) =>
  apiClient.post<never, APIResponse<ContractDetail>>('/contracts', data);

export const updateContract = (id: number, data: Partial<Contract>) =>
  apiClient.patch<never, APIResponse<ContractDetail>>(`/contracts/${id}`, data);

export const deleteContract = (id: number) =>
  apiClient.delete<never, APIResponse<boolean>>(`/contracts/${id}`);

export const attachContractAsset = (id: number, asset_id: number) =>
  apiClient.post<never, APIResponse<ContractDetail>>(`/contracts/${id}/assets`, { asset_id });

export const detachContractAsset = (id: number, assetId: number) =>
  apiClient.delete<never, APIResponse<ContractDetail>>(`/contracts/${id}/assets/${assetId}`);

// ── ITAM: entitlements ────────────────────────────────
export const getEntitlements = (page = 1, size = 50, params = {}) =>
  apiClient.get<never, APIResponse<EntitlementListOut>>('/entitlements', { params: { page, size, ...params } });

export const getEntitlementById = (id: number) =>
  apiClient.get<never, APIResponse<EntitlementDetail>>(`/entitlements/${id}`);

export const createEntitlement = (data: Record<string, unknown>) =>
  apiClient.post<never, APIResponse<EntitlementDetail>>('/entitlements', data);

export const updateEntitlement = (id: number, data: Record<string, unknown>) =>
  apiClient.patch<never, APIResponse<EntitlementDetail>>(`/entitlements/${id}`, data);

export const deleteEntitlement = (id: number) =>
  apiClient.delete<never, APIResponse<boolean>>(`/entitlements/${id}`);

export const assignEntitlement = (id: number, target: { asset_id?: number; user_id?: number }) =>
  apiClient.post<never, APIResponse<EntitlementDetail>>(`/entitlements/${id}/assign`, target);

export const unassignEntitlement = (id: number, assignmentId: number) =>
  apiClient.delete<never, APIResponse<EntitlementDetail>>(`/entitlements/${id}/assign/${assignmentId}`);

// ── ITAM: notifications ───────────────────────────────
export const getSmtpSettings = () =>
  apiClient.get<never, APIResponse<SmtpSettingsOut>>('/notifications/smtp');

export const saveSmtpSettings = (data: Record<string, unknown>) =>
  apiClient.put<never, APIResponse<SmtpSettingsOut>>('/notifications/smtp', data);

export const testSmtp = (recipient: string) =>
  apiClient.post<never, APIResponse<boolean>>('/notifications/smtp/test', { recipient });

export const getAlertRules = () =>
  apiClient.get<never, APIResponse<AlertRule[]>>('/notifications/rules');

export const updateAlertRule = (ruleType: string, data: { days_before: number; recipients: string[]; enabled: boolean }) =>
  apiClient.patch<never, APIResponse<AlertRule>>(`/notifications/rules/${ruleType}`, data);

export const runNotifications = () =>
  apiClient.post<never, APIResponse<Record<string, string>>>('/notifications/run');

export const getNotificationLog = (limit = 50) =>
  apiClient.get<never, APIResponse<NotificationLogEntry[]>>('/notifications/log', { params: { limit } });

// ── Phase 1: Agents ───────────────────────────────────────
export const getAgentTokens = () => apiClient.get<never, APIResponse<any[]>>('/agents/tokens');
export const createAgentToken = (name: string) => apiClient.post<never, APIResponse<any>>('/agents/tokens', { name });
export const toggleAgentToken = (id: number) => apiClient.patch<never, APIResponse<boolean>>(`/agents/tokens/${id}`);
export const getDeviceSoftware = (id: number) => apiClient.get<never, APIResponse<any[]>>(`/devices/${id}/software`);

// ── Phase 2: SAM ──────────────────────────────────────────
export const getSoftwareInventory = () => apiClient.get<never, APIResponse<any[]>>('/sam/software');
export const getLicensePosition = () => apiClient.get<never, APIResponse<any>>('/sam/license-position');

// ── Phase 3: CMDB audit ───────────────────────────────────
export const getCmdbAudit = () => apiClient.get<never, APIResponse<any>>('/cmdb/audit');

// ── Phase 4: CAASM posture + vulnerabilities ──────────────
export const getPostureSummary = () => apiClient.get<never, APIResponse<any>>('/posture/summary');
export const getLogCoverage = () => apiClient.get<never, APIResponse<any>>('/posture/log-coverage');
export const getVulnSummary = () => apiClient.get<never, APIResponse<any>>('/vulnerabilities/summary');
export const getAssetVulns = (id: number) => apiClient.get<never, APIResponse<any[]>>(`/assets/${id}/vulnerabilities`);
export const importVulnerabilities = (file: File) => {
  const f = new FormData(); f.append('file', file);
  return apiClient.post<never, APIResponse<any>>('/vulnerabilities/import', f, { headers: { 'Content-Type': 'multipart/form-data' } });
};

// ── Phase 5: reports + import + bulk ──────────────────────
export const getCostReport = () => apiClient.get<never, APIResponse<any>>('/reports/cost');
export const getEolReport = () => apiClient.get<never, APIResponse<any>>('/reports/eol');
export const getComplianceReport = () => apiClient.get<never, APIResponse<any>>('/reports/compliance');
export const bulkUpdateAssets = (asset_ids: number[], fields: Record<string, unknown>) =>
  apiClient.post<never, APIResponse<any>>('/assets/bulk-update', { asset_ids, fields });
export const importAssets = (file: File) => {
  const f = new FormData(); f.append('file', file);
  return apiClient.post<never, APIResponse<any>>('/assets/import', f, { headers: { 'Content-Type': 'multipart/form-data' } });
};

// ── Scanning: credential vault, scan targets, runs ────
export const getCredentialTypes = () =>
  apiClient.get<never, APIResponse<Record<string, CredentialTypeSpec>>>('/scan/credential-types');
export const getScanCredentials = () =>
  apiClient.get<never, APIResponse<ScanCredential[]>>('/scan/credentials');
export const createScanCredential = (body: unknown) =>
  apiClient.post<never, APIResponse<ScanCredential>>('/scan/credentials', body);
export const updateScanCredential = (id: number, body: unknown) =>
  apiClient.patch<never, APIResponse<ScanCredential>>(`/scan/credentials/${id}`, body);
export const deleteScanCredential = (id: number) =>
  apiClient.delete<never, APIResponse<boolean>>(`/scan/credentials/${id}`);

export const getScanTargets = () =>
  apiClient.get<never, APIResponse<ScanTarget[]>>('/scan/targets');
export const previewScanTarget = (body: { target_type: string; value: string; exclusions: string }) =>
  apiClient.post<never, APIResponse<{ count: number; sample: string[] }>>('/scan/targets/preview', body);
export const createScanTarget = (body: unknown) =>
  apiClient.post<never, APIResponse<ScanTarget>>('/scan/targets', body);
export const updateScanTarget = (id: number, body: unknown) =>
  apiClient.patch<never, APIResponse<ScanTarget>>(`/scan/targets/${id}`, body);
export const deleteScanTarget = (id: number) =>
  apiClient.delete<never, APIResponse<boolean>>(`/scan/targets/${id}`);
export const runScanTarget = (id: number) =>
  apiClient.post<never, APIResponse<{ run_id: number }>>(`/scan/targets/${id}/run`);

export const getScanRuns = (params: { target_id?: number; limit?: number } = {}) =>
  apiClient.get<never, APIResponse<ScanRun[]>>('/scan/runs', { params });
export const getScanRun = (id: number) =>
  apiClient.get<never, APIResponse<ScanRunDetail>>(`/scan/runs/${id}`);
export const cancelScanRun = (id: number) =>
  apiClient.post<never, APIResponse<boolean>>(`/scan/runs/${id}/cancel`);

// ── Device inventory & change history ─────────────────
export const getDeviceInventory = (id: number) =>
  apiClient.get<never, APIResponse<DeviceInventoryData>>(`/devices/${id}/inventory`);
export const getDeviceChanges = (id: number, params: { category?: string; limit?: number; offset?: number } = {}) =>
  apiClient.get<never, APIResponse<{ total: number; items: DeviceChange[] }>>(`/devices/${id}/changes`, { params });
export const getRecentChanges = (params: { severity?: string; category?: string; days?: number; limit?: number } = {}) =>
  apiClient.get<never, APIResponse<DeviceChange[]>>('/changes', { params });
export const getEndpointHealth = () =>
  apiClient.get<never, APIResponse<EndpointHealth>>('/dashboard/endpoint-health');
export const getAgentFleet = () =>
  apiClient.get<never, APIResponse<AgentFleet>>('/agents/fleet');
