import { useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getLicenseStatus, uploadLicense } from '../api';
import { BadgeCheck, AlertTriangle, XCircle, Upload, KeyRound } from 'lucide-react';
import clsx from 'clsx';
import { useAuth } from '../context/AuthContext';

const STATUS_STYLES: Record<string, { badge: string; icon: typeof BadgeCheck; label: string }> = {
  valid:   { badge: 'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30', icon: BadgeCheck,    label: 'Valid' },
  grace:   { badge: 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',    icon: AlertTriangle, label: 'Grace period' },
  expired: { badge: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',          icon: XCircle,       label: 'Expired' },
  invalid: { badge: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',          icon: XCircle,       label: 'Invalid' },
  missing: { badge: 'bg-slate-500/20 text-slate-400 ring-slate-500/30',       icon: XCircle,       label: 'Not installed' },
};

function UsageBar({ label, used, max }: { label: string; used: number; max: number }) {
  const pct = max > 0 ? Math.min(100, Math.round((used / max) * 100)) : 0;
  const color = pct >= 90 ? 'bg-rose-500' : pct >= 70 ? 'bg-yellow-500' : 'bg-indigo-500';
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-300">{used} / {max}</span>
      </div>
      <div className="bg-slate-700/50 rounded-full h-2 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function License() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const { data: res, isLoading } = useQuery({ queryKey: ['license'], queryFn: getLicenseStatus });
  const lic = res?.data;

  const upload = useMutation({
    mutationFn: (file: File) => uploadLicense(file),
    onSuccess: (r) => {
      setMessage({ ok: true, text: r.message || 'License activated' });
      queryClient.invalidateQueries({ queryKey: ['license'] });
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMessage({ ok: false, text: detail ?? 'Upload failed' });
    },
  });

  if (isLoading || !lic) {
    return <div className="flex items-center justify-center h-64 text-slate-400">Loading license…</div>;
  }

  const style = STATUS_STYLES[lic.status] ?? STATUS_STYLES.missing;
  const Icon = style.icon;

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
          <KeyRound className="w-8 h-8 text-indigo-400" />
          License
        </h1>
        <p className="text-slate-400 mt-1">Application license status and activation.</p>
      </div>

      <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Icon className={clsx('w-8 h-8', lic.operational ? 'text-emerald-400' : 'text-rose-400')} />
            <div>
              <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold uppercase ring-1 ring-inset ${style.badge}`}>
                {style.label}
              </span>
              {lic.reason && <p className="text-sm text-slate-400 mt-1">{lic.reason}</p>}
            </div>
          </div>
        </div>

        {lic.customer && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div><p className="text-slate-500">Licensed to</p><p className="text-slate-200 font-medium">{lic.customer}</p></div>
            <div><p className="text-slate-500">Expires</p><p className="text-slate-200 font-medium">{lic.expires_at}</p></div>
            <div><p className="text-slate-500">Grace period</p><p className="text-slate-200 font-medium">{lic.grace_days} days</p></div>
            <div><p className="text-slate-500">License ID</p><p className="text-slate-200 font-mono text-xs mt-1">{lic.license_id}</p></div>
          </div>
        )}

        {lic.operational && (
          <div className="grid md:grid-cols-2 gap-6">
            <UsageBar label="Managed assets" used={lic.usage.assets ?? 0} max={lic.max_assets ?? 0} />
            <UsageBar label="Users" used={lic.usage.users ?? 0} max={lic.max_users ?? 0} />
          </div>
        )}

        {lic.modules.length > 0 && (
          <div>
            <p className="text-sm text-slate-500 mb-2">Enabled modules</p>
            <div className="flex flex-wrap gap-2">
              {lic.modules.map((m) => (
                <span key={m} className="px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-500/15 text-indigo-300 ring-1 ring-inset ring-indigo-500/30">
                  {m}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {user?.role === 'admin' && (
        <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
          <h2 className="text-lg font-medium text-slate-50 mb-2">Install a new license</h2>
          <p className="text-sm text-slate-400 mb-4">
            Upload the <code className="text-slate-300">.lic</code> file provided by your vendor.
            Validation happens fully offline — no internet connection required.
          </p>
          <input
            ref={fileRef}
            type="file"
            accept=".lic,application/json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload.mutate(f);
              e.target.value = '';
            }}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={upload.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <Upload className="w-4 h-4" />
            {upload.isPending ? 'Validating…' : 'Upload license file'}
          </button>
          {message && (
            <p className={clsx('text-sm mt-3', message.ok ? 'text-emerald-400' : 'text-rose-400')}>
              {message.text}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
