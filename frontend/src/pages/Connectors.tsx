import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getConnectors, saveConnectorConfig, triggerConnectorSync, testConnectorConnection } from '../api';
import { Settings, Play, Database, CheckCircle2, XCircle, Clock, FlaskConical, Loader2 } from 'lucide-react';
import type { ConnectorStatus } from '../types';

type JsonSchemaField = {
  type?: 'string' | 'number' | 'integer' | 'boolean';
  title?: string;
  description?: string;
  default?: unknown;
  enum?: Array<string | number | boolean>;
  format?: string;
};

type ConfigFormState = {
  enabled: boolean;
  scheduleCron: string;
  config: Record<string, unknown>;
};

type TestResult = { success: boolean; message: string } | null;

const DEFAULT_CRON = '0 */6 * * *';

function buildInitialConfig(connector: ConnectorStatus): ConfigFormState {
  const schema = connector.schema_definition || {};
  const properties = (schema.properties || {}) as Record<string, JsonSchemaField>;
  const existingConfig = connector.config || {};
  const config: Record<string, unknown> = {};

  Object.entries(properties).forEach(([name, field]) => {
    if (Object.prototype.hasOwnProperty.call(existingConfig, name)) {
      config[name] = existingConfig[name];
      return;
    }
    if (field.default !== undefined) {
      config[name] = field.default;
      return;
    }
    if (field.type === 'boolean') {
      config[name] = false;
      return;
    }
    if (field.type === 'number' || field.type === 'integer') {
      config[name] = '';
      return;
    }
    config[name] = '';
  });

  return {
    enabled: connector.is_enabled,
    scheduleCron: DEFAULT_CRON,
    config,
  };
}

export default function Connectors() {
  const queryClient = useQueryClient();
  const [selectedConnector, setSelectedConnector] = useState<ConnectorStatus | null>(null);
  const [formState, setFormState] = useState<ConfigFormState | null>(null);
  const [testResult, setTestResult] = useState<TestResult>(null);
  const [isTesting, setIsTesting] = useState(false);

  const { data: res, isLoading } = useQuery({
    queryKey: ['connectors'],
    queryFn: getConnectors,
  });

  const connectors = res?.data || [];

  const syncMutation = useMutation({
    mutationFn: (name: string) => triggerConnectorSync(name),
    onSuccess: () => {
      // Invalidate and refetch
      queryClient.invalidateQueries({ queryKey: ['connectors'] });
      // Show success toast (mocked)
      alert("Sync triggered successfully!");
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string; message?: string } } })?.response?.data;
      alert(`Failed to trigger sync: ${detail?.detail ?? detail?.message ?? 'unknown error'}`);
    }
  });

  const handleSync = (name: string) => {
    syncMutation.mutate(name);
  };

  const saveMutation = useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: ConfigFormState }) =>
      saveConnectorConfig(name, {
        enabled: payload.enabled,
        schedule_cron: payload.scheduleCron,
        config: payload.config,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['connectors'] });
      setSelectedConnector(null);
      setFormState(null);
      alert('Connector configuration saved.');
    },
    onError: () => {
      alert('Failed to save connector configuration.');
    },
  });

  const openConfigModal = (connector: ConnectorStatus) => {
    setSelectedConnector(connector);
    setFormState(buildInitialConfig(connector));
    setTestResult(null);
  };

  const closeConfigModal = () => {
    setSelectedConnector(null);
    setFormState(null);
    setTestResult(null);
  };

  const handleTestConnection = async () => {
    if (!selectedConnector || !formState) return;
    setIsTesting(true);
    setTestResult(null);
    try {
      const res = await testConnectorConnection(selectedConnector.name, formState.config);
      const ok = res?.data === true;
      setTestResult({
        success: ok,
        message: ok ? 'Connection successful.' : 'Connection test returned false — check credentials.',
      });
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? err?.message ?? 'Unknown error';
      setTestResult({ success: false, message: `Connection failed: ${detail}` });
    } finally {
      setIsTesting(false);
    }
  };

  const schemaProperties = useMemo(() => {
    if (!selectedConnector) {
      return [] as Array<[string, JsonSchemaField]>;
    }
    const schema = selectedConnector.schema_definition || {};
    const properties = (schema.properties || {}) as Record<string, JsonSchemaField>;
    return Object.entries(properties);
  }, [selectedConnector]);

  const requiredFields = useMemo(() => {
    if (!selectedConnector) {
      return new Set<string>();
    }
    const required = (selectedConnector.schema_definition?.required || []) as string[];
    return new Set(required);
  }, [selectedConnector]);

  const updateConfigField = (fieldName: string, nextValue: unknown) => {
    setFormState((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        config: {
          ...prev.config,
          [fieldName]: nextValue,
        },
      };
    });
  };

  const handleSave = () => {
    if (!selectedConnector || !formState) {
      return;
    }
    saveMutation.mutate({
      name: selectedConnector.name,
      payload: formState,
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white">Data Connectors</h1>
        <p className="text-slate-400 mt-1">Configure sources like Active Directory, McAfee, and mock data generators.</p>
      </div>

      {isLoading ? (
        <div className="text-slate-500 py-12 text-center">Loading connectors...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {connectors.map((c) => (
            <div key={c.name} className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6 flex flex-col hover:border-slate-600 transition-colors shadow-sm">
              <div className="flex justify-between items-start mb-4">
                <div className="p-3 bg-indigo-500/10 text-indigo-400 rounded-xl">
                  <Database className="w-6 h-6" />
                </div>
                <div className="flex gap-2">
                  <button 
                    onClick={() => openConfigModal(c)}
                    className="p-2 text-slate-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors"
                    title="Configure"
                  >
                    <Settings className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleSync(c.name)}
                    disabled={!c.is_configured || (syncMutation.isPending && syncMutation.variables === c.name)}
                    className="p-2 text-slate-400 hover:text-emerald-400 hover:bg-emerald-400/10 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:text-slate-400 disabled:hover:bg-transparent"
                    title={c.is_configured ? 'Manual Sync' : 'Configure this connector before syncing'}
                  >
                    <Play className="w-4 h-4" />
                  </button>
                </div>
              </div>
              
              <h3 className="text-xl font-semibold text-white mb-1">{c.display_name}</h3>
              <p className="text-slate-400 text-sm mb-6 flex-1">{c.name}</p>

              <div className="space-y-3 border-t border-slate-700/50 pt-4">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-slate-400 flex items-center gap-1">Status</span>
                  {c.is_enabled ? (
                    <span className="inline-flex items-center gap-1 text-emerald-400 font-medium">
                      <CheckCircle2 className="w-3 h-3" /> Enabled
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-slate-500 font-medium">
                      <XCircle className="w-3 h-3" /> Disabled
                    </span>
                  )}
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-slate-400 flex items-center gap-1"><Clock className="w-3 h-3" /> Last Run</span>
                  <span className="text-slate-300">
                    {c.last_run ? new Date(c.last_run).toLocaleString() : 'Never'}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedConnector && formState && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-xl p-6 shadow-2xl max-h-[90vh] overflow-y-auto">
            <h2 className="text-xl font-bold text-white mb-4">Configure {selectedConnector.display_name}</h2>
            <p className="text-slate-400 text-sm mb-6">Configuration schemas are dynamically loaded from the connector registry.</p>

            <div className="space-y-4">
              <label className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/50 p-3">
                <span className="text-slate-200 font-medium">Enable connector</span>
                <input
                  type="checkbox"
                  checked={formState.enabled}
                  onChange={(e) => setFormState((prev) => (prev ? { ...prev, enabled: e.target.checked } : prev))}
                  className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
                />
              </label>

              <div>
                <label className="block text-sm text-slate-300 mb-1">Schedule (cron)</label>
                <input
                  type="text"
                  value={formState.scheduleCron}
                  onChange={(e) => setFormState((prev) => (prev ? { ...prev, scheduleCron: e.target.value } : prev))}
                  className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/60"
                  placeholder="0 */6 * * *"
                />
              </div>

              {schemaProperties.map(([fieldName, field]) => {
                const value = formState.config[fieldName];
                const label = field.title || fieldName;
                const isRequired = requiredFields.has(fieldName);

                return (
                  <div key={fieldName}>
                    <label className="block text-sm text-slate-300 mb-1">
                      {label}
                      {isRequired ? ' *' : ''}
                    </label>

                    {field.enum ? (
                      <select
                        value={String(value ?? '')}
                        onChange={(e) => updateConfigField(fieldName, e.target.value)}
                        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/60"
                      >
                        <option value="">Select...</option>
                        {field.enum.map((opt) => (
                          <option key={String(opt)} value={String(opt)}>
                            {String(opt)}
                          </option>
                        ))}
                      </select>
                    ) : field.type === 'boolean' ? (
                      <label className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-slate-200">
                        <input
                          type="checkbox"
                          checked={Boolean(value)}
                          onChange={(e) => updateConfigField(fieldName, e.target.checked)}
                          className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500"
                        />
                        <span>Enabled</span>
                      </label>
                    ) : (
                      <input
                        type={field.format === 'password' ? 'password' : field.type === 'number' || field.type === 'integer' ? 'number' : 'text'}
                        step={field.type === 'integer' ? '1' : undefined}
                        value={String(value ?? '')}
                        onChange={(e) => {
                          if (field.type === 'number') {
                            updateConfigField(fieldName, e.target.value === '' ? '' : Number(e.target.value));
                            return;
                          }
                          if (field.type === 'integer') {
                            updateConfigField(fieldName, e.target.value === '' ? '' : parseInt(e.target.value, 10));
                            return;
                          }
                          updateConfigField(fieldName, e.target.value);
                        }}
                        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/60"
                      />
                    )}

                    {field.description && <p className="text-xs text-slate-500 mt-1">{field.description}</p>}
                  </div>
                );
              })}
            </div>
            
            {/* Test result banner */}
            {testResult && (
              <div className={`mt-6 flex items-start gap-3 rounded-lg px-4 py-3 text-sm ring-1 ring-inset ${
                testResult.success
                  ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/20'
                  : 'bg-rose-500/10 text-rose-300 ring-rose-500/20'
              }`}>
                {testResult.success
                  ? <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
                  : <XCircle className="w-4 h-4 shrink-0 mt-0.5" />
                }
                {testResult.message}
              </div>
            )}

            <div className="flex flex-wrap justify-between items-center gap-3 mt-6">
              <button
                onClick={handleTestConnection}
                disabled={isTesting}
                className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg transition-colors text-sm disabled:opacity-60"
              >
                {isTesting
                  ? <Loader2 className="w-4 h-4 animate-spin" />
                  : <FlaskConical className="w-4 h-4" />
                }
                {isTesting ? 'Testing…' : 'Test Connection'}
              </button>

              <div className="flex gap-3">
                <button
                  onClick={closeConfigModal}
                  className="px-4 py-2 text-slate-300 hover:text-white transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={saveMutation.isPending}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors font-medium disabled:opacity-60"
                >
                  {saveMutation.isPending ? 'Saving…' : 'Save Changes'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
