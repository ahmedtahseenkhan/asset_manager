import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getLifecycleDevices, getLifecycleSummary, importWarranty, refreshLifecycle, uploadLifecycleCatalog,
} from '../api';
import type { LifecycleGroup, WarrantyImportResult } from '../types';
import { useAuth } from '../context/AuthContext';
import { errorText } from '../lib/errors';
import { EolBadge } from '../components/lifecycle/ui';
import { fmtDay, relative } from '../lib/lifecycle';
import {
  ArrowUpRight, BookOpen, CalendarClock, ChevronDown, ChevronRight, Package, RefreshCw, ShieldCheck, Upload,
} from 'lucide-react';
import { formatDistanceToNowStrict } from 'date-fns';
import clsx from 'clsx';

const CARD = 'bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl';
const H2 = 'text-sm font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2';
const TH = 'px-5 py-2.5 text-xs font-semibold text-slate-400 tracking-wider';
const TD = 'px-5 py-2.5 text-sm text-slate-300';

function Tile({ value, label, hint, tone }: { value: number | string; label: string; hint?: string; tone: 'bad' | 'warn' | 'neutral' }) {
  const color = tone === 'bad' && value ? 'text-rose-400' : tone === 'warn' && value ? 'text-amber-400' : 'text-slate-200';
  return (
    <div className={clsx(CARD, 'p-5')}>
      <p className={clsx('text-3xl font-bold tabular-nums', color)}>{value}</p>
      <p className="text-sm text-slate-300 mt-1">{label}</p>
      {hint && <p className="text-xs text-slate-500 mt-0.5">{hint}</p>}
    </div>
  );
}

function DeviceList({ kind, group }: { kind: 'os' | 'software'; group: LifecycleGroup }) {
  const { data, isLoading } = useQuery({
    queryKey: ['lifecycle-devices', kind, group.product_id, group.cycle],
    queryFn: () => getLifecycleDevices(kind, group.product_id, group.cycle),
  });
  if (isLoading) return <p className="text-xs text-slate-500">Loading…</p>;
  const rows = (data?.data ?? []).filter((r) => r.title === group.title);
  return (
    <ul className="grid sm:grid-cols-2 xl:grid-cols-3 gap-x-6 gap-y-1">
      {rows.map((r) => (
        <li key={r.device_id} className="text-sm truncate">
          <Link to={`/devices/${r.device_id}`} className="text-indigo-400 hover:text-indigo-300">{r.hostname ?? `device ${r.device_id}`}</Link>
          {r.detail && <span className="text-xs text-slate-500"> · {r.detail}</span>}
        </li>
      ))}
    </ul>
  );
}

function ReleaseTable({ kind, rows, empty }: { kind: 'os' | 'software'; rows: LifecycleGroup[]; empty: string }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!rows.length) return <p className="px-5 pb-5 text-sm text-slate-500">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead><tr className="border-b border-slate-700/50">
          <th className={TH}>{kind === 'os' ? 'Release' : 'Product'}</th><th className={TH}>Support</th>
          <th className={TH}>End of support</th><th className={TH}>Paid extended support</th>
          <th className={clsx(TH, 'text-right')}>Devices</th>
        </tr></thead>
        <tbody className="divide-y divide-slate-700/40">
          {rows.map((g) => {
            const key = `${g.product_id}|${g.cycle}|${g.title}`;
            const expanded = open === key;
            return [
              <tr key={key} className="hover:bg-slate-800/40 cursor-pointer" onClick={() => setOpen(expanded ? null : key)}>
                <td className={clsx(TD, 'text-slate-100 font-medium')}>
                  <span className="inline-flex items-center gap-1.5">
                    {expanded ? <ChevronDown className="w-3.5 h-3.5 text-slate-500" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-500" />}
                    {g.title}
                  </span>
                </td>
                <td className={TD}><EolBadge status={g.status} /></td>
                <td className={TD}>
                  {g.eol ? fmtDay(g.eol) : '—'}
                  <span className="block text-xs text-slate-500">{relative(g.days_left)}</span>
                </td>
                <td className={clsx(TD, 'text-slate-400')}>{g.extended ? `until ${fmtDay(g.extended)}` : '—'}</td>
                <td className={clsx(TD, 'text-right tabular-nums text-slate-100')}>{g.devices}</td>
              </tr>,
              expanded && (
                <tr key={`${key}-devices`} className="bg-slate-900/30">
                  <td colSpan={5} className="px-10 py-3"><DeviceList kind={kind} group={g} /></td>
                </tr>
              ),
            ];
          })}
        </tbody>
      </table>
    </div>
  );
}

function WarrantyImport({ canEdit }: { canEdit: boolean }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [order, setOrder] = useState<'dmy' | 'mdy'>('dmy');
  const [result, setResult] = useState<WarrantyImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: (file: File) => importWarranty(file, order),
    onSuccess: (r) => { setResult(r.data); setError(null); queryClient.invalidateQueries({ queryKey: ['lifecycle-summary'] }); },
    onError: (e) => { setError(errorText(e)); setResult(null); },
  });
  if (!canEdit) return <p className="text-sm text-slate-500">Asset managers and administrators can import warranty dates.</p>;
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        Upload a CSV exported from Dell TechDirect, Lenovo or HP, from your reseller, or kept by hand. Rows match assets by
        serial number (or asset tag). Columns such as <i>Service Tag</i>, <i>Serial Number</i>, <i>Warranty End Date</i> and{' '}
        <i>Ship Date</i> are recognised; with several lines per serial, the latest end date is used.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <select value={order} onChange={(e) => setOrder(e.target.value as 'dmy' | 'mdy')}
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200">
          <option value="dmy">Dates like 31/12/2026</option>
          <option value="mdy">Dates like 12/31/2026</option>
        </select>
        <input ref={fileRef} type="file" accept=".csv" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ''; }} />
        <button onClick={() => fileRef.current?.click()} disabled={upload.isPending}
          className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg">
          <Upload className="w-4 h-4" /> {upload.isPending ? 'Importing…' : 'Import warranty CSV'}
        </button>
      </div>
      {error && <p className="text-sm text-rose-400">{error}</p>}
      {result && (
        <div className="text-sm space-y-1.5">
          <p className="text-emerald-400">
            {result.updated} asset{result.updated === 1 ? '' : 's'} updated{result.unchanged ? `, ${result.unchanged} already up to date` : ''}.
          </p>
          {result.device_only_count > 0 && (
            <p className="text-amber-400">
              {result.device_only_count === 1 ? '1 serial belongs' : `${result.device_only_count} serials belong`} to devices not registered as assets
              ({result.device_only.slice(0, 5).map((d) => d.hostname ?? d.serial).join(', ')}{result.device_only_count > 5 ? ', …' : ''}).{' '}
              <Link to="/assets/reconcile" className="underline">Register them</Link> and import again.
            </p>
          )}
          {result.not_found_count > 0 && (
            <p className="text-slate-400">
              {result.not_found_count} not found: {result.not_found.slice(0, 8).join(', ')}{result.not_found_count > 8 ? ', …' : ''}
            </p>
          )}
          {result.errors.length > 0 && (
            <p className="text-rose-400">Skipped rows: {result.errors.slice(0, 5).map((e) => `row ${e.row} (${e.message})`).join('; ')}</p>
          )}
        </div>
      )}
    </div>
  );
}

function CatalogPanel({ isAdmin }: { isAdmin: boolean }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const { data } = useQuery({ queryKey: ['lifecycle-summary'], queryFn: getLifecycleSummary });
  const cat = data?.data.catalog;
  const done = (text: string) => {
    setMsg({ ok: true, text });
    queryClient.invalidateQueries({ queryKey: ['lifecycle-summary'] });
    queryClient.invalidateQueries({ queryKey: ['lifecycle-devices'] });
  };
  const upload = useMutation({
    mutationFn: uploadLifecycleCatalog, onSuccess: (r) => done(r.message ?? 'Catalogue uploaded'),
    onError: (e) => setMsg({ ok: false, text: errorText(e) }),
  });
  const refresh = useMutation({
    mutationFn: refreshLifecycle, onSuccess: () => done('Recalculated'),
    onError: (e) => setMsg({ ok: false, text: errorText(e) }),
  });
  if (!cat) return null;
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-300">
        Version <span className="font-mono">{cat.version}</span> · published {fmtDay(cat.published)} ·{' '}
        {cat.origin === 'bundled' ? 'bundled with this release' : 'uploaded'} · {cat.products} products
      </p>
      <p className="text-sm text-slate-400">
        Support dates for Windows, Windows Server, macOS and the main Linux distributions, and for Office, SQL Server,
        Exchange, SharePoint, Visual Studio, .NET, Python, Node.js and others. Works offline. Newer catalogues ship with each
        release; an administrator can also upload one in between. The newest one is used.
      </p>
      {isAdmin && (
        <div className="flex flex-wrap gap-3">
          <input ref={fileRef} type="file" accept=".json,application/json" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ''; }} />
          <button onClick={() => fileRef.current?.click()} disabled={upload.isPending}
            className="inline-flex items-center gap-2 px-3 py-2 text-sm text-slate-200 bg-slate-700/60 rounded-lg hover:bg-slate-700 disabled:opacity-50">
            <Upload className="w-4 h-4" /> Upload catalogue (JSON)
          </button>
          <button onClick={() => refresh.mutate()} disabled={refresh.isPending}
            className="inline-flex items-center gap-2 px-3 py-2 text-sm text-slate-200 bg-slate-700/60 rounded-lg hover:bg-slate-700 disabled:opacity-50">
            <RefreshCw className={clsx('w-4 h-4', refresh.isPending && 'animate-spin')} /> Recalculate now
          </button>
        </div>
      )}
      {msg && <p className={clsx('text-sm', msg.ok ? 'text-emerald-400' : 'text-rose-400')}>{msg.text}</p>}
      {cat.last_upload && (
        <p className="text-xs text-slate-500">
          Last upload: {cat.last_upload.version}, {formatDistanceToNowStrict(new Date(cat.last_upload.uploaded_at))} ago
        </p>
      )}
    </div>
  );
}

export default function Lifecycle() {
  const { user } = useAuth();
  const { data, isLoading, error } = useQuery({ queryKey: ['lifecycle-summary'], queryFn: getLifecycleSummary });
  const s = data?.data;
  const c = s?.counts;
  const months = s ? Math.round(s.ending_soon_days / 30) : 6;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
            <CalendarClock className="w-8 h-8 text-indigo-400" /> Lifecycle
          </h1>
          <p className="text-slate-400 mt-1">Operating systems and software past or near their end of support, and hardware warranties.</p>
        </div>
        <Link to="/reports?tab=library" className="inline-flex items-center gap-1.5 text-sm text-indigo-400 hover:text-indigo-300">
          <BookOpen className="w-4 h-4" /> Lifecycle reports <ArrowUpRight className="w-4 h-4" />
        </Link>
      </div>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && <p className="text-sm text-rose-400">{errorText(error)}</p>}

      {s && c && <>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Tile value={c.os_unsupported} label="Devices on an unsupported OS" tone="bad"
            hint={`of ${c.os_identified} with an identified OS`} />
          <Tile value={c.os_ending_soon} label={`OS support ends within ${months} months`} tone="warn" />
          <Tile value={c.software_unsupported_devices} label="Devices with unsupported software" tone="bad" />
          <Tile value={c.warranty_expired} label="Assets with an expired warranty" tone="bad"
            hint={`${c.warranty_ending_soon} more end within ${s.warranty_soon_days} days · ${c.warranty_unknown} hardware assets without a date`} />
        </div>

        <div className={CARD}>
          <div className="p-5 pb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className={H2}><ShieldCheck className="w-4 h-4" /> Operating systems</h2>
            {c.os_unidentified > 0 && (
              <p className="text-xs text-slate-500">
                {c.os_unidentified} active device{c.os_unidentified === 1 ? '' : 's'} not identified: no agent, scan or directory record with an OS version.
              </p>
            )}
          </div>
          <ReleaseTable kind="os" rows={s.os}
            empty="No operating systems identified yet. Deploy the agent, run a credentialed scan, or sync Active Directory." />
        </div>

        <div className={CARD}>
          <div className="p-5 pb-3">
            <h2 className={H2}><Package className="w-4 h-4" /> Software out of support or ending within {months} months</h2>
          </div>
          <ReleaseTable kind="software" rows={s.software}
            empty="No installed software is past or near its end of support." />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className={clsx(CARD, 'p-5 space-y-3')}>
            <h2 className={H2}>Warranty dates</h2>
            <WarrantyImport canEdit={user?.role === 'admin' || user?.role === 'asset_manager'} />
          </div>
          <div className={clsx(CARD, 'p-5 space-y-3')}>
            <h2 className={H2}>End-of-life catalogue</h2>
            <CatalogPanel isAdmin={user?.role === 'admin'} />
          </div>
        </div>
      </>}
    </div>
  );
}
