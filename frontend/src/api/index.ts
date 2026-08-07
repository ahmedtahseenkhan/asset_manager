import { apiClient } from './client';
import type { DashboardSummary, CoverageGapSummary, APIResponse, DeviceListOut, Device, ConnectorStatus } from '../types';

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
