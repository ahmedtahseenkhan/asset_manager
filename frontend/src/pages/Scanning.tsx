import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getScanTargets, createScanTarget, updateScanTarget, deleteScanTarget, runScanTarget, previewScanTarget,
  getScanCredentials, getCredentialTypes, createScanCredential, updateScanCredential, deleteScanCredential,
  getScanRuns, getScanRun, cancelScanRun, testScanCredential, getSshHostKeys, forgetSshHostKey,
} from '../api';
import type { ScanTarget, ScanCredential, ScanRun, ScanRunStatus, CredentialTypeSpec } from '../types';
import {
  ScanSearch, Plus, Play, Pencil, Trash2, KeyRound, History, Target, X, Square, Lock, PlugZap, CheckCircle2, XCircle,
} from 'lucide-react';
import { format, formatDistanceStrict } from 'date-fns';
import clsx from 'clsx';

const INPUT = 'w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/60';
const LABEL = 'block text-sm text-slate-300 mb-1';
const BTN_PRIMARY = 'inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg';
const BTN_GHOST = 'inline-flex items-center gap-2 px-4 py-2 text-sm text-slate-300 hover:text-slate-50 rounded-lg border border-slate-700';
const ICON_BTN = 'p-1.5 text-slate-500 hover:text-slate-50 rounded disabled:opacity-40';

const SCHEDULES = [
  { label: 'Manual only', cron: '' },
  { label: 'Daily at 02:00', cron: '0 2 * * *' },
  { label: 'Every 6 hours', cron: '0 */6 * * *' },
  { label: 'Weekly (Sun 03:00)', cron: '0 3 * * 0' },
];
const CREDENTIALED_METHODS = [
  { id: 'winrm', label: 'WinRM', hint: 'Windows' },
  { id: 'ssh', label: 'SSH', hint: 'Linux, macOS, Unix' },
  { id: 'snmp', label: 'SNMP', hint: 'switches, routers, printers' },
];
const KNOWN_METHODS = new Set(['ping', ...CREDENTIALED_METHODS.map((m) => m.id)]);
const SECRET_LABELS: Record<string, string> = {
  password: 'Password', private_key: 'Private key (PEM)', passphrase: 'Key passphrase',
  community: 'Community string', auth_password: 'Auth password', priv_password: 'Privacy password',
};
const PARAM_LABELS: Record<string, string> = {
  port: 'Port', version: 'Version', security_level: 'Security level',
  auth_protocol: 'Auth protocol', priv_protocol: 'Privacy protocol',
  transport: 'WinRM transport', verify_tls: 'Verify TLS certificate', sudo: 'Use sudo (needs NOPASSWD for python3)',
};

function errorText(err: unknown): string {
  const e = err as { message?: string; response?: { data?: { detail?: unknown; message?: string } } };
  const body = e?.response?.data;
  const detail = body?.detail ?? body?.message ?? e?.message ?? 'Request failed';
  return typeof detail === 'string' ? detail : JSON.stringify(detail);
}

function StatusBadge({ status }: { status: ScanRunStatus | null }) {
  if (!status) return <span className="text-slate-500 text-sm">never run</span>;
  const cls: Record<ScanRunStatus, string> = {
    completed: 'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30',
    running: 'bg-indigo-500/20 text-indigo-300 ring-indigo-500/30 animate-pulse',
    queued: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
    failed: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',
    cancelled: 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
  };
  return (
    <span className={clsx('px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset', cls[status])}>
      {status}
    </span>
  );
}

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  // Portal to <body>: the cards use backdrop-blur, which would otherwise
  // confine a fixed-position overlay to the card.
  return createPortal(
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-[100]" onClick={onClose}>
      <div className={clsx('bg-slate-900 border border-slate-700 rounded-2xl w-full p-6 shadow-2xl max-h-[90vh] overflow-y-auto', wide ? 'max-w-4xl' : 'max-w-xl')}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-xl font-bold text-slate-50">{title}</h2>
          <button onClick={onClose} className={ICON_BTN} aria-label="Close"><X className="w-5 h-5" /></button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">{children}</div>;
}

// ── Targets ─────────────────────────────────────────────────────────────────
interface TargetForm {
  name: string; enabled: boolean; target_type: ScanTarget['target_type']; value: string; exclusions: string;
  schedule_cron: string; methods: string[]; credential_ids: number[];
  concurrency: number; timeout_ms: number; deep_probe: boolean;
}
const EMPTY_TARGET: TargetForm = {
  name: '', enabled: true, target_type: 'cidr', value: '', exclusions: '', schedule_cron: '',
  methods: ['ping'], credential_ids: [], concurrency: 32, timeout_ms: 1000, deep_probe: true,
};
const VALUE_HINTS: Record<ScanTarget['target_type'], string> = {
  cidr: '192.168.1.0/24  (several allowed, comma or newline separated)',
  range: '10.0.0.10-10.0.0.50  or  10.0.0.10-50',
  hosts: 'srv01, srv02.corp.local, 10.0.0.7',
  ad: 'OU=Workstations,DC=corp,DC=local  or  * for the whole directory',
};

function TargetModal({ target, credentials, onClose }: { target: ScanTarget | null; credentials: ScanCredential[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<TargetForm>(() => target ? {
    name: target.name, enabled: target.enabled, target_type: target.target_type, value: target.value,
    exclusions: target.exclusions, schedule_cron: target.schedule_cron ?? '',
    methods: target.methods.filter((m) => KNOWN_METHODS.has(m)),   // drops the retired "wmi"
    credential_ids: target.credential_ids, concurrency: target.concurrency,
    timeout_ms: target.timeout_ms, deep_probe: target.deep_probe,
  } : EMPTY_TARGET);
  const [preview, setPreview] = useState<{ count: number; sample: string[] } | null>(null);
  const [error, setError] = useState('');
  const set = <K extends keyof TargetForm>(k: K, v: TargetForm[K]) => {
    setForm((f) => ({ ...f, [k]: v }));
    if (k === 'target_type' || k === 'value' || k === 'exclusions') setPreview(null);
  };

  const previewMut = useMutation({
    mutationFn: () => previewScanTarget({ target_type: form.target_type, value: form.value, exclusions: form.exclusions }),
    onSuccess: (r) => { setPreview(r.data); setError(''); },
    onError: (e) => { setPreview(null); setError(errorText(e)); },
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, schedule_cron: form.schedule_cron || null };
      if (!target) return createScanTarget(body);
      return updateScanTarget(target.id, { ...body, clear_schedule: !form.schedule_cron });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['scan-targets'] }); queryClient.invalidateQueries({ queryKey: ['scan-credentials'] }); onClose(); },
    onError: (e) => setError(errorText(e)),
  });

  const toggleMethod = (m: string) =>
    set('methods', form.methods.includes(m) ? form.methods.filter((x) => x !== m) : [...form.methods, m]);
  const toggleCred = (id: number) =>
    set('credential_ids', form.credential_ids.includes(id) ? form.credential_ids.filter((x) => x !== id) : [...form.credential_ids, id]);
  const moveCred = (id: number, dir: -1 | 1) => {
    const ids = [...form.credential_ids];
    const i = ids.indexOf(id);
    const j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    set('credential_ids', ids);
  };
  const credName = (id: number) => credentials.find((c) => c.id === id)?.name ?? `#${id}`;
  const presetMatch = SCHEDULES.some((s) => s.cron === form.schedule_cron);

  return (
    <Modal title={target ? `Edit ${target.name}` : 'New scan target'} onClose={onClose}>
      <div className="space-y-4">
        <div>
          <label className={LABEL}>Name *</label>
          <input className={INPUT} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="HQ office LAN" />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={LABEL}>Type</label>
            <select className={INPUT} value={form.target_type} onChange={(e) => set('target_type', e.target.value as TargetForm['target_type'])}>
              <option value="cidr">Subnet (CIDR)</option>
              <option value="range">IP range</option>
              <option value="hosts">Host list</option>
              <option value="ad">Active Directory computers</option>
            </select>
          </div>
          <div className="col-span-2">
            <label className={LABEL}>Addresses *</label>
            <textarea className={clsx(INPUT, 'font-mono')} rows={2} value={form.value}
              onChange={(e) => set('value', e.target.value)} placeholder={VALUE_HINTS[form.target_type]} />
          </div>
        </div>

        <div>
          <label className={LABEL}>Exclude (optional)</label>
          <input className={clsx(INPUT, 'font-mono')} value={form.exclusions} onChange={(e) => set('exclusions', e.target.value)}
            placeholder="10.0.0.1, 10.0.0.200-254" />
        </div>

        <div className="flex items-center gap-3">
          <button type="button" className={BTN_GHOST} disabled={!form.value.trim() || previewMut.isPending} onClick={() => previewMut.mutate()}>
            Check addresses
          </button>
          {preview && (
            <span className="text-sm text-slate-300">
              <b>{preview.count}</b> address{preview.count === 1 ? '' : 'es'}
              <span className="text-slate-500 font-mono"> — {preview.sample.slice(0, 4).join(', ')}{preview.count > 4 ? ', …' : ''}</span>
            </span>
          )}
        </div>

        <div>
          <label className={LABEL}>Schedule</label>
          <div className="flex gap-3">
            <select className={INPUT} value={presetMatch ? form.schedule_cron : 'custom'}
              onChange={(e) => set('schedule_cron', e.target.value === 'custom' ? '0 1 * * *' : e.target.value)}>
              {SCHEDULES.map((s) => <option key={s.label} value={s.cron}>{s.label}</option>)}
              <option value="custom">Custom (cron)…</option>
            </select>
            {!presetMatch && (
              <input className={clsx(INPUT, 'font-mono')} value={form.schedule_cron}
                onChange={(e) => set('schedule_cron', e.target.value)} placeholder="m h dom mon dow" />
            )}
          </div>
          <p className="text-xs text-slate-500 mt-1">Times are in the server's timezone (UTC in the standard install).</p>
        </div>

        <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-4 space-y-3">
          <div>
            <p className="text-sm text-slate-200 font-medium">Credentialed scanning</p>
            <p className="text-xs text-slate-500 mt-0.5">
              After the network sweep, each responding host is inventoried with the methods ticked here, using only the
              credentials below — at most 3 per method per host, stopping at the first that works.
            </p>
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {CREDENTIALED_METHODS.map((m) => (
              <label key={m.id} className="inline-flex items-center gap-2 text-sm text-slate-300">
                <input type="checkbox" checked={form.methods.includes(m.id)} onChange={() => toggleMethod(m.id)}
                  className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500" />
                {m.label} <span className="text-xs text-slate-500">{m.hint}</span>
              </label>
            ))}
          </div>
          <div>
            <p className={LABEL}>Credentials, tried in this order</p>
            {form.credential_ids.length > 0 && (
              <ol className="mb-2 space-y-1">
                {form.credential_ids.map((id, i) => (
                  <li key={id} className="flex items-center gap-2 text-sm text-slate-200">
                    <span className="text-slate-500 w-5">{i + 1}.</span>
                    <span className="flex-1">{credName(id)}</span>
                    <button type="button" className={ICON_BTN} disabled={i === 0} onClick={() => moveCred(id, -1)} aria-label="Move up">↑</button>
                    <button type="button" className={ICON_BTN} disabled={i === form.credential_ids.length - 1} onClick={() => moveCred(id, 1)} aria-label="Move down">↓</button>
                    <button type="button" className={ICON_BTN} onClick={() => toggleCred(id)} aria-label="Remove"><X className="w-4 h-4" /></button>
                  </li>
                ))}
              </ol>
            )}
            <select className={INPUT} value="" onChange={(e) => e.target.value && toggleCred(Number(e.target.value))}>
              <option value="">{credentials.length ? 'Add a credential…' : 'No credentials yet — add them on the Credentials tab'}</option>
              {credentials.filter((c) => !form.credential_ids.includes(c.id)).map((c) => (
                <option key={c.id} value={c.id}>{c.name} ({c.type_label})</option>
              ))}
            </select>
          </div>
        </div>

        <details className="text-sm">
          <summary className="cursor-pointer text-slate-400 hover:text-slate-200">Advanced</summary>
          <div className="grid grid-cols-2 gap-3 mt-3">
            <div>
              <label className={LABEL}>Parallel hosts</label>
              <input type="number" min={1} max={128} className={INPUT} value={form.concurrency}
                onChange={(e) => set('concurrency', Number(e.target.value))} />
            </div>
            <div>
              <label className={LABEL}>Ping timeout (ms)</label>
              <input type="number" min={200} max={10000} step={100} className={INPUT} value={form.timeout_ms}
                onChange={(e) => set('timeout_ms', Number(e.target.value))} />
            </div>
            <label className="col-span-2 inline-flex items-center gap-2 text-slate-300">
              <input type="checkbox" checked={form.deep_probe} onChange={(e) => set('deep_probe', e.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500" />
              Deep probe (port scan, SNMP, SSDP) — slower, more detail
            </label>
            <label className="col-span-2 inline-flex items-center gap-2 text-slate-300">
              <input type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-indigo-500" />
              Enabled (scheduled runs only happen while enabled)
            </label>
          </div>
        </details>

        {error && <p className="text-sm text-rose-400">{error}</p>}
        <div className="flex justify-end gap-3 pt-2">
          <button className={BTN_GHOST} onClick={onClose}>Cancel</button>
          <button className={BTN_PRIMARY} disabled={!form.name.trim() || !form.value.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? 'Saving…' : 'Save target'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function TargetsTab({ onOpenRun }: { onOpenRun: (id: number) => void }) {
  const queryClient = useQueryClient();
  const [modal, setModal] = useState<{ target: ScanTarget | null } | null>(null);
  const [error, setError] = useState('');
  const { data, isLoading } = useQuery({
    queryKey: ['scan-targets'], queryFn: getScanTargets,
    refetchInterval: (q) => (q.state.data?.data?.some((t) => t.running) ? 3000 : false),
  });
  const { data: creds } = useQuery({ queryKey: ['scan-credentials'], queryFn: getScanCredentials });
  const targets = data?.data ?? [];
  const credentials = creds?.data ?? [];

  const run = useMutation({
    mutationFn: (id: number) => runScanTarget(id),
    onSuccess: (r) => {
      setError('');
      queryClient.invalidateQueries({ queryKey: ['scan-targets'] });
      queryClient.invalidateQueries({ queryKey: ['scan-runs'] });
      onOpenRun(r.data.run_id);
    },
    onError: (e) => setError(errorText(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteScanTarget(id),
    onSuccess: () => { setError(''); queryClient.invalidateQueries({ queryKey: ['scan-targets'] }); },
    onError: (e) => setError(errorText(e)),
  });

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-slate-400">Each target is a set of addresses scanned together, on its own schedule.</p>
        <button className={BTN_PRIMARY} onClick={() => setModal({ target: null })}><Plus className="w-4 h-4" /> New target</button>
      </div>
      {error && <p className="text-sm text-rose-400 mb-3">{error}</p>}
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
            <th className="py-2">Name</th><th className="py-2">Addresses</th><th className="py-2">Schedule</th>
            <th className="py-2">Credentials</th><th className="py-2">Last run</th><th />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {targets.map((t) => (
            <tr key={t.id} className={clsx(!t.enabled && 'opacity-50')}>
              <td className="py-2.5 text-sm text-slate-200 font-medium">{t.name}{!t.enabled && <span className="ml-2 text-xs text-slate-500">(disabled)</span>}</td>
              <td className="py-2.5 text-sm text-slate-400 font-mono max-w-[16rem] truncate" title={t.value}>{t.value}</td>
              <td className="py-2.5 text-sm text-slate-400">
                {t.schedule_cron ? (SCHEDULES.find((s) => s.cron === t.schedule_cron)?.label ?? <span className="font-mono">{t.schedule_cron}</span>) : 'Manual'}
              </td>
              <td className="py-2.5 text-sm text-slate-400">{t.credential_ids.length || '—'}</td>
              <td className="py-2.5 text-sm">
                <div className="flex items-center gap-2">
                  <StatusBadge status={t.running ? 'running' : t.last_status} />
                  {t.last_run_at && !t.running && <span className="text-slate-500 text-xs">{format(new Date(t.last_run_at), 'PP p')}</span>}
                </div>
              </td>
              <td className="py-2.5 text-right whitespace-nowrap">
                <button className={ICON_BTN} title="Run now" disabled={t.running || run.isPending} onClick={() => run.mutate(t.id)}><Play className="w-4 h-4" /></button>
                <button className={ICON_BTN} title="Edit" onClick={() => setModal({ target: t })}><Pencil className="w-4 h-4" /></button>
                <button className={ICON_BTN} title="Delete" disabled={t.running}
                  onClick={() => window.confirm(`Delete scan target "${t.name}"? Its run history is kept.`) && remove.mutate(t.id)}>
                  <Trash2 className="w-4 h-4" />
                </button>
              </td>
            </tr>
          ))}
          {!isLoading && targets.length === 0 && (
            <tr><td colSpan={6} className="py-8 text-center text-slate-500 text-sm">No scan targets yet. Add your first subnet to start discovering devices.</td></tr>
          )}
        </tbody>
      </table>
      {modal && <TargetModal target={modal.target} credentials={credentials} onClose={() => setModal(null)} />}
    </Card>
  );
}

// ── Credentials ─────────────────────────────────────────────────────────────
function CredentialModal({ cred, types, onClose }: { cred: ScanCredential | null; types: Record<string, CredentialTypeSpec>; onClose: () => void }) {
  const queryClient = useQueryClient();
  const typeIds = Object.keys(types);
  const [credType, setCredType] = useState(cred?.cred_type ?? typeIds[0] ?? 'windows');
  const [name, setName] = useState(cred?.name ?? '');
  const [username, setUsername] = useState(cred?.username ?? '');
  const [description, setDescription] = useState(cred?.description ?? '');
  const [params, setParams] = useState<Record<string, string>>(
    () => Object.fromEntries(Object.entries(cred?.params ?? {}).map(([k, v]) => [k, String(v)])));
  const [secret, setSecret] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const spec = types[credType];

  const save = useMutation({
    mutationFn: () => {
      const cleanParams = Object.fromEntries(Object.entries(params).filter(([k, v]) => v !== '' && spec?.params && k in spec.params));
      const cleanSecret = Object.fromEntries(Object.entries(secret).filter(([, v]) => v !== ''));
      const body = { name, username: username || null, params: cleanParams, secret: cleanSecret, description: description || null };
      return cred ? updateScanCredential(cred.id, body) : createScanCredential({ ...body, cred_type: credType });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['scan-credentials'] }); onClose(); },
    onError: (e) => setError(errorText(e)),
  });

  if (!spec) return null;
  return (
    <Modal title={cred ? `Edit ${cred.name}` : 'New credential'} onClose={onClose}>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL}>Name *</label>
            <input className={INPUT} value={name} onChange={(e) => setName(e.target.value)} placeholder="Domain scan account" />
          </div>
          <div>
            <label className={LABEL}>Type</label>
            <select className={INPUT} value={credType} disabled={!!cred}
              onChange={(e) => { setCredType(e.target.value); setParams({}); setSecret({}); }}>
              {typeIds.map((t) => <option key={t} value={t}>{types[t].label}</option>)}
            </select>
          </div>
        </div>

        {spec.username === 'required' && (
          <div>
            <label className={LABEL}>{credType === 'snmp_v3' ? 'Security name *' : 'Username *'}</label>
            <input className={INPUT} value={username} onChange={(e) => setUsername(e.target.value)}
              placeholder={credType === 'windows' ? 'CORP\\svc-scan  or  svc-scan@corp.local' : 'username'} autoComplete="off" />
          </div>
        )}

        {Object.entries(spec.params).length > 0 && (
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(spec.params).map(([key, allowed]) => (
              <div key={key}>
                <label className={LABEL}>{PARAM_LABELS[key] ?? key}</label>
                {allowed ? (
                  <select className={INPUT} value={params[key] ?? ''} onChange={(e) => setParams((p) => ({ ...p, [key]: e.target.value }))}>
                    <option value="">Default</option>
                    {allowed.map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                ) : (
                  <input className={INPUT} value={params[key] ?? ''} onChange={(e) => setParams((p) => ({ ...p, [key]: e.target.value }))}
                    placeholder={key === 'port' ? (credType === 'vmware' ? '443' : '22') : ''} />
                )}
              </div>
            ))}
          </div>
        )}

        {spec.secrets.map(({ name: key, required }) => {
          const isSet = cred?.secrets_set.includes(key);
          const multiline = key === 'private_key';
          const props = {
            className: clsx(INPUT, multiline && 'font-mono text-xs'),
            value: secret[key] ?? '',
            autoComplete: 'new-password',
            placeholder: isSet ? '•••••••• saved — leave blank to keep' : '',
            onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setSecret((s) => ({ ...s, [key]: e.target.value })),
          };
          return (
            <div key={key}>
              <label className={LABEL}>{SECRET_LABELS[key] ?? key}{required && !cred ? ' *' : ''}</label>
              {multiline ? <textarea rows={4} {...props} /> : <input type="password" {...props} />}
            </div>
          );
        })}

        <div>
          <label className={LABEL}>Notes</label>
          <input className={INPUT} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Which systems this account can reach" />
        </div>

        <p className="text-xs text-slate-500 flex items-center gap-1.5">
          <Lock className="w-3.5 h-3.5" /> Secrets are encrypted at rest and never shown again after saving.
        </p>
        {error && <p className="text-sm text-rose-400">{error}</p>}
        <div className="flex justify-end gap-3 pt-2">
          <button className={BTN_GHOST} onClick={onClose}>Cancel</button>
          <button className={BTN_PRIMARY} disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? 'Saving…' : 'Save credential'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function TestCredentialModal({ cred, onClose }: { cred: ScanCredential; onClose: () => void }) {
  const [host, setHost] = useState('');
  const [error, setError] = useState('');
  const test = useMutation({
    mutationFn: () => testScanCredential(cred.id, host.trim()),
    onSuccess: () => setError(''),
    onError: (e) => setError(errorText(e)),
  });
  const result = test.data?.data;
  return (
    <Modal title={`Test ${cred.name}`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-slate-400">
          Signs in to one host and runs a harmless query; nothing is stored. The host must be inside a scan target
          that uses this credential.
        </p>
        <div className="flex gap-3">
          <input className={clsx(INPUT, 'font-mono')} value={host} onChange={(e) => setHost(e.target.value)}
            placeholder="10.0.0.25 or server01.corp.local" autoFocus
            onKeyDown={(e) => e.key === 'Enter' && host.trim() && test.mutate()} />
          <button className={BTN_PRIMARY} disabled={!host.trim() || test.isPending} onClick={() => test.mutate()}>
            {test.isPending ? 'Testing…' : 'Test'}
          </button>
        </div>
        {error && <p className="text-sm text-rose-400">{error}</p>}
        {result && (result.ok ? (
          <div className="rounded-lg p-3 bg-emerald-500/10 ring-1 ring-inset ring-emerald-500/30 text-sm">
            <p className="text-emerald-400 font-medium flex items-center gap-2"><CheckCircle2 className="w-4 h-4" /> Signed in over {result.method?.toUpperCase()}</p>
            <p className="text-slate-300 mt-1">{[result.hostname, result.os, result.vendor].filter(Boolean).join(' · ')}</p>
            {result.note && <p className="text-yellow-400 mt-1">{result.note}</p>}
          </div>
        ) : (
          <div className="rounded-lg p-3 bg-rose-500/10 ring-1 ring-inset ring-rose-500/30 text-sm">
            <p className="text-rose-400 font-medium flex items-center gap-2"><XCircle className="w-4 h-4" /> {result.host}</p>
            <p className="text-slate-300 mt-1">{result.message}</p>
          </div>
        ))}
      </div>
    </Modal>
  );
}

function HostKeysCard() {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ['ssh-host-keys'], queryFn: getSshHostKeys });
  const keys = data?.data ?? [];
  const forget = useMutation({
    mutationFn: (id: number) => forgetSshHostKey(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ssh-host-keys'] }),
  });
  return (
    <Card>
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-1">Trusted SSH host keys</h2>
      <p className="text-xs text-slate-500 mb-3">
        Remembered the first time each host is scanned. If a host later shows a different key, no credentials are sent to it.
        Forget a key only after confirming the host was rebuilt or re-keyed.
      </p>
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
            <th className="py-2">Host</th><th className="py-2">Key</th><th className="py-2">Fingerprint</th><th className="py-2">First seen</th><th />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {keys.map((k) => (
            <tr key={k.id}>
              <td className="py-2 text-sm text-slate-200 font-mono">{k.host}{k.port !== 22 ? `:${k.port}` : ''}</td>
              <td className="py-2 text-sm text-slate-400">{k.key_type}</td>
              <td className="py-2 text-xs text-slate-400 font-mono">{k.fingerprint}</td>
              <td className="py-2 text-sm text-slate-500">{k.first_seen ? format(new Date(k.first_seen), 'PP') : '—'}</td>
              <td className="py-2 text-right">
                <button className={clsx(BTN_GHOST, 'py-1 px-2 text-xs')} disabled={forget.isPending}
                  onClick={() => window.confirm(`Forget the trusted key for ${k.host}? The next scan will trust whatever key it presents.`) && forget.mutate(k.id)}>
                  Forget
                </button>
              </td>
            </tr>
          ))}
          {keys.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-slate-500 text-sm">No SSH hosts scanned yet.</td></tr>}
        </tbody>
      </table>
    </Card>
  );
}

function CredentialsTab() {
  const queryClient = useQueryClient();
  const [modal, setModal] = useState<{ cred: ScanCredential | null } | null>(null);
  const [testing, setTesting] = useState<ScanCredential | null>(null);
  const [error, setError] = useState('');
  const { data, isLoading } = useQuery({ queryKey: ['scan-credentials'], queryFn: getScanCredentials });
  const { data: typesRes } = useQuery({ queryKey: ['credential-types'], queryFn: getCredentialTypes, staleTime: Infinity });
  const creds = data?.data ?? [];
  const types = typesRes?.data ?? {};

  const remove = useMutation({
    mutationFn: (id: number) => deleteScanCredential(id),
    onSuccess: () => { setError(''); queryClient.invalidateQueries({ queryKey: ['scan-credentials'] }); queryClient.invalidateQueries({ queryKey: ['scan-targets'] }); },
    onError: (e) => setError(errorText(e)),
  });

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-slate-400">Accounts the scanner may use to read inventory from hosts. Use least-privilege accounts.</p>
        <button className={BTN_PRIMARY} disabled={!Object.keys(types).length} onClick={() => setModal({ cred: null })}>
          <Plus className="w-4 h-4" /> New credential
        </button>
      </div>
      {error && <p className="text-sm text-rose-400 mb-3">{error}</p>}
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
            <th className="py-2">Name</th><th className="py-2">Type</th><th className="py-2">Username</th>
            <th className="py-2">Secrets</th><th className="py-2">Used by</th><th className="py-2">Updated</th><th />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {creds.map((c) => (
            <tr key={c.id}>
              <td className="py-2.5 text-sm text-slate-200 font-medium">{c.name}</td>
              <td className="py-2.5 text-sm text-slate-400">{c.type_label}</td>
              <td className="py-2.5 text-sm text-slate-400 font-mono">{c.username ?? '—'}</td>
              <td className="py-2.5 text-sm">
                <div className="flex flex-wrap gap-1">
                  {c.secrets_set.map((s) => (
                    <span key={s} className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-400 ring-1 ring-inset ring-emerald-500/30">
                      {SECRET_LABELS[s] ?? s}
                    </span>
                  ))}
                </div>
              </td>
              <td className="py-2.5 text-sm text-slate-400">{c.target_count ? `${c.target_count} target${c.target_count === 1 ? '' : 's'}` : '—'}</td>
              <td className="py-2.5 text-sm text-slate-500">{format(new Date(c.updated_at), 'PP')}</td>
              <td className="py-2.5 text-right whitespace-nowrap">
                {c.cred_type !== 'vmware' && (
                  <button className={ICON_BTN} title="Test against a host" onClick={() => setTesting(c)}><PlugZap className="w-4 h-4" /></button>
                )}
                <button className={ICON_BTN} title="Edit" onClick={() => setModal({ cred: c })}><Pencil className="w-4 h-4" /></button>
                <button className={ICON_BTN} title="Delete"
                  onClick={() => window.confirm(
                    `Delete credential "${c.name}"?${c.target_count ? ` It will be removed from ${c.target_count} scan target(s).` : ''}`,
                  ) && remove.mutate(c.id)}>
                  <Trash2 className="w-4 h-4" />
                </button>
              </td>
            </tr>
          ))}
          {!isLoading && creds.length === 0 && (
            <tr><td colSpan={7} className="py-8 text-center text-slate-500 text-sm">No credentials yet.</td></tr>
          )}
        </tbody>
      </table>
      {modal && <CredentialModal cred={modal.cred} types={types} onClose={() => setModal(null)} />}
      {testing && <TestCredentialModal cred={testing} onClose={() => setTesting(null)} />}
    </Card>
  );
}

// ── History ─────────────────────────────────────────────────────────────────
function duration(r: ScanRun): string {
  if (!r.started_at) return '—';
  return formatDistanceStrict(new Date(r.finished_at ?? Date.now()), new Date(r.started_at));
}

function RunModal({ runId, onClose }: { runId: number; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ['scan-run', runId], queryFn: () => getScanRun(runId),
    refetchInterval: (q) => (['queued', 'running'].includes(q.state.data?.data?.status ?? '') ? 2000 : false),
  });
  const cancel = useMutation({
    mutationFn: () => cancelScanRun(runId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['scan-run', runId] }); queryClient.invalidateQueries({ queryKey: ['scan-runs'] }); },
  });
  const run = data?.data;
  const active = run && ['queued', 'running'].includes(run.status);

  return (
    <Modal title={run ? `${run.target_name} — run #${run.id}` : 'Scan run'} onClose={onClose} wide>
      {!run ? <p className="text-slate-400 text-sm">Loading…</p> : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <StatusBadge status={run.status} />
            <span className="text-slate-400">Started <span className="text-slate-200">{run.started_at ? format(new Date(run.started_at), 'PP p') : '—'}</span></span>
            <span className="text-slate-400">Duration <span className="text-slate-200">{duration(run)}</span></span>
            <span className="text-slate-400">Responding <span className="text-slate-200">{run.hosts_alive}</span> of {run.hosts_total}</span>
            {(run.hosts_inventoried > 0 || run.hosts_failed > 0) && (
              <span className="text-slate-400">
                Inventoried <span className="text-emerald-400">{run.hosts_inventoried}</span>
                {run.hosts_failed > 0 && <> · failed <span className="text-rose-400">{run.hosts_failed}</span></>}
              </span>
            )}
            <span className="text-slate-400 capitalize">{run.trigger}</span>
            {active && (
              <button className={clsx(BTN_GHOST, 'ml-auto')} disabled={cancel.isPending} onClick={() => cancel.mutate()}>
                <Square className="w-4 h-4" /> Cancel
              </button>
            )}
          </div>
          {run.error && <p className="text-sm text-rose-400 bg-rose-500/10 border border-rose-500/30 rounded-lg p-3">{run.error}</p>}
          {active && <p className="text-sm text-slate-400">Sweeping {run.hosts_total} addresses… results appear when the sweep finishes.</p>}
          {run.hosts.length > 0 && (
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
                  <th className="py-2">IP</th><th className="py-2">Hostname</th><th className="py-2">Result</th><th className="py-2">Method · credential</th><th className="py-2">Device</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {run.hosts.map((h) => (
                  <tr key={h.id} className="align-top">
                    <td className="py-2 text-sm text-slate-200 font-mono">{h.ip}</td>
                    <td className="py-2 text-sm text-slate-300">{h.hostname ?? <span className="text-slate-500">unknown</span>}</td>
                    <td className="py-2 text-sm max-w-md">
                      <span className={clsx(
                        h.status === 'failed' ? 'text-rose-400' : h.status === 'inventoried' ? 'text-emerald-400' : 'text-slate-400')}>
                        {h.status === 'alive' ? 'responding (sweep only)' : h.status}
                      </span>
                      {h.error_message && (
                        <span className={clsx('block text-xs mt-0.5', h.status === 'failed' ? 'text-slate-400' : 'text-yellow-400')}>
                          {h.error_message}
                          {h.error_code === 'host_key_changed' && ' Trusted keys are listed on the Credentials tab.'}
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-sm text-slate-400">
                      {h.method === 'ping' ? 'sweep' : h.method?.toUpperCase() ?? '—'}
                      {h.credential_name && <span className="block text-xs text-slate-500">{h.credential_name}</span>}
                    </td>
                    <td className="py-2 text-sm">
                      {h.device_id ? <Link to={`/devices/${h.device_id}`} className="text-indigo-400 hover:text-indigo-300">View</Link> : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!active && run.status === 'completed' && run.hosts.length === 0 && (
            <p className="text-sm text-slate-400">No hosts responded. If you expected devices here, check the addresses and that the server can reach that network.</p>
          )}
        </div>
      )}
    </Modal>
  );
}

function HistoryTab({ onOpenRun }: { onOpenRun: (id: number) => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['scan-runs'], queryFn: () => getScanRuns({ limit: 100 }),
    refetchInterval: (q) => (q.state.data?.data?.some((r) => ['queued', 'running'].includes(r.status)) ? 3000 : false),
  });
  const runs = data?.data ?? [];
  return (
    <Card>
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
            <th className="py-2">Target</th><th className="py-2">Status</th><th className="py-2">Started</th>
            <th className="py-2">Duration</th><th className="py-2">Responding</th><th className="py-2">Trigger</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {runs.map((r) => (
            <tr key={r.id} className="cursor-pointer hover:bg-slate-700/20" onClick={() => onOpenRun(r.id)}>
              <td className="py-2.5 text-sm text-slate-200 font-medium">{r.target_name}</td>
              <td className="py-2.5"><StatusBadge status={r.status} /></td>
              <td className="py-2.5 text-sm text-slate-400">{format(new Date(r.started_at ?? r.created_at), 'PP p')}</td>
              <td className="py-2.5 text-sm text-slate-400">{duration(r)}</td>
              <td className="py-2.5 text-sm text-slate-300">
                {r.status === 'completed' ? `${r.hosts_alive} / ${r.hosts_total}` : '—'}
                {(r.hosts_inventoried > 0 || r.hosts_failed > 0) && (
                  <span className="block text-xs text-slate-500">
                    {r.hosts_inventoried} inventoried{r.hosts_failed > 0 && <span className="text-rose-400"> · {r.hosts_failed} failed</span>}
                  </span>
                )}
              </td>
              <td className="py-2.5 text-sm text-slate-500 capitalize">{r.trigger}</td>
            </tr>
          ))}
          {!isLoading && runs.length === 0 && (
            <tr><td colSpan={6} className="py-8 text-center text-slate-500 text-sm">No scans have run yet.</td></tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────
const TABS = [
  { id: 'targets', label: 'Scan targets', icon: Target },
  { id: 'credentials', label: 'Credentials', icon: KeyRound },
  { id: 'history', label: 'Scan history', icon: History },
] as const;

export default function Scanning() {
  const [tab, setTab] = useState<(typeof TABS)[number]['id']>('targets');
  const [openRun, setOpenRun] = useState<number | null>(null);

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
          <ScanSearch className="w-8 h-8 text-indigo-400" /> Scanning
        </h1>
        <p className="text-slate-400 mt-1">Define the networks to discover, the credentials to inventory them with, and review every scan.</p>
      </div>

      <div className="flex gap-1 border-b border-slate-700/60">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className={clsx('inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px',
              tab === id ? 'border-indigo-500 text-slate-50' : 'border-transparent text-slate-400 hover:text-slate-200')}>
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>

      {tab === 'targets' && <TargetsTab onOpenRun={setOpenRun} />}
      {tab === 'credentials' && <><CredentialsTab /><HostKeysCard /></>}
      {tab === 'history' && <HistoryTab onOpenRun={setOpenRun} />}

      {openRun !== null && <RunModal runId={openRun} onClose={() => setOpenRun(null)} />}
    </div>
  );
}
