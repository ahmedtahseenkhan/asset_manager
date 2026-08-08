import { apiClient } from './client';
import type {
  DashboardSummary, CoverageGapSummary, APIResponse, DeviceListOut, Device, ConnectorStatus,
  LicenseStatus, Asset, AssetDetail, AssetListOut, UnlinkedDevice,
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
