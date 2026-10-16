import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { getDeviceChanges, getDeviceSoftware } from '../../api';
import type { DeviceChange, DeviceInventoryData, DeviceVirtualization, InventorySummary, VmPlacementInfo } from '../../types';
import { CHANGE_CATEGORY_LABELS, describeChange } from '../../lib/changes';
import { AlertTriangle, CheckCircle2, HelpCircle, Layers, ShieldAlert, XCircle } from 'lucide-react';
import { format, formatDistanceToNowStrict } from 'date-fns';
import clsx from 'clsx';

const CARD = 'bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6';
const H2 = 'text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3';
const FILTER = 'px-3 py-1.5 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 w-56';
const TH = 'py-2 pr-4 text-xs font-semibold text-slate-400 tracking-wider';
const TD = 'py-2 pr-4 text-sm text-slate-300';

const fmtDate = (d: string | null | undefined, f = 'PP') => (d ? format(new Date(d), f) : null);
const gb = (v: number | null | undefined) => (v == null ? null : `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} GB`);

/** Tri-state flag: good / bad / unknown, with the wording supplied. */
export function Flag({ value, good, bad, unknown = 'Unknown', invert = false }: {
  value: boolean | null | undefined; good: string; bad: string; unknown?: string; invert?: boolean;
}) {
  if (value == null) {
    return <span className="inline-flex items-center gap-1.5 text-sm text-slate-500"><HelpCircle className="w-4 h-4" />{unknown}</span>;
  }
  const ok = invert ? !value : value;
  return (
    <span className={clsx('inline-flex items-center gap-1.5 text-sm', ok ? 'text-emerald-400' : 'text-rose-400')}>
      {ok ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}{value ? good : bad}
    </span>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 border-b border-slate-700/40 last:border-0">
      <span className="text-sm text-slate-400 shrink-0">{label}</span>
      <span className="text-sm text-slate-200 text-right">{value ?? <span className="text-slate-600">—</span>}</span>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-500 py-4">{children}</p>;
}

function useFilter<T>(rows: T[] | undefined, text: (r: T) => string) {
  const [q, setQ] = useState('');
  const filtered = useMemo(
    () => (rows ?? []).filter((r) => !q || text(r).toLowerCase().includes(q.toLowerCase())),
    [rows, q, text],
  );
  return { q, setQ, filtered };
}

// ── Hardware ────────────────────────────────────────────────────────────────
export function HardwareTab({ inv, serial }: { inv: DeviceInventoryData; serial?: string | null }) {
  const s = inv.summary as InventorySummary;
  const cpu = s.cpu ? `${s.cpu}${s.cpu_cores ? ` · ${s.cpu_cores} cores` : ''}${s.cpu_logical && s.cpu_logical !== s.cpu_cores ? ` / ${s.cpu_logical} threads` : ''}` : null;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className={CARD}>
          <h2 className={H2}>System</h2>
          <Row label="Manufacturer" value={s.manufacturer} />
          <Row label="Model" value={s.model} />
          <Row label="Serial number" value={serial && <span className="font-mono">{serial}</span>} />
          <Row label="Type" value={s.chassis_type && (s.chassis_type === 'vm' ? 'Virtual machine'
            : <span className="capitalize">{s.chassis_type}{s.is_virtual ? ' (virtual)' : ''}</span>)} />
          <Row label="Processor" value={cpu} />
          <Row label="Memory" value={gb(s.ram_gb)} />
          <Row label="Disk capacity" value={gb(s.disk_gb)} />
          <Row label="BIOS / firmware" value={[s.bios_vendor, s.bios_version, s.bios_date && `(${s.bios_date})`].filter(Boolean).join(' ') || null} />
          <Row label="Motherboard" value={s.motherboard} />
        </div>
        <div className={CARD}>
          <h2 className={H2}>Operating system</h2>
          <Row label="Name" value={s.os_name} />
          <Row label="Version" value={s.os_version} />
          <Row label="Build" value={s.os_build && <span className="font-mono">{s.os_build}</span>} />
          <Row label="Architecture" value={s.architecture} />
          <Row label="Last boot" value={s.last_boot && `${fmtDate(s.last_boot, 'PP p')} (up ${formatDistanceToNowStrict(new Date(s.last_boot))})`} />
          <Row label="Signed-in user" value={s.logged_in_user} />
          <Row label="Inventory" value={s.collected_at && `${s.source ?? ''} ${s.collector_version ?? ''} · ${fmtDate(s.collected_at, 'PP p')}`} />
        </div>
      </div>

      <div className={CARD}>
        <h2 className={H2}>Disks</h2>
        {!inv.volumes?.length ? <Empty>No disk information collected.</Empty> : (
          <table className="w-full text-left">
            <thead><tr className="border-b border-slate-700/50"><th className={TH}>Volume</th><th className={TH}>File system</th><th className={TH}>Capacity</th><th className={TH}>Free</th><th className={TH}>Encryption</th></tr></thead>
            <tbody className="divide-y divide-slate-700/40">
              {inv.volumes.map((v) => {
                const used = v.size_gb && v.free_gb != null ? 1 - v.free_gb / v.size_gb : null;
                return (
                  <tr key={v.name}>
                    <td className={clsx(TD, 'font-mono text-slate-200')}>{v.name}</td>
                    <td className={TD}>{v.filesystem ?? '—'}</td>
                    <td className={TD}>
                      {used == null ? '—' : (
                        <div className="flex items-center gap-2 min-w-[10rem]">
                          <div className="h-1.5 flex-1 rounded-full bg-slate-700/60 overflow-hidden">
                            <div className={clsx('h-full rounded-full', used > 0.9 ? 'bg-rose-500' : used > 0.75 ? 'bg-yellow-500' : 'bg-indigo-500')} style={{ width: `${Math.round(used * 100)}%` }} />
                          </div>
                          <span className="text-xs text-slate-400 w-16 text-right">{gb(v.size_gb)}</span>
                        </div>
                      )}
                    </td>
                    <td className={TD}>{gb(v.free_gb) ?? '—'}</td>
                    <td className={TD}><Flag value={v.encrypted} good={v.encryption_method ?? 'Encrypted'} bad="Not encrypted" /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className={CARD}>
        <h2 className={H2}>Network adapters</h2>
        {!inv.network_adapters?.length ? <Empty>No network adapters collected.</Empty> : (
          <table className="w-full text-left">
            <thead><tr className="border-b border-slate-700/50"><th className={TH}>Adapter</th><th className={TH}>MAC</th><th className={TH}>IP addresses</th><th className={TH}>Gateway</th><th className={TH}>Speed</th></tr></thead>
            <tbody className="divide-y divide-slate-700/40">
              {inv.network_adapters.map((n) => (
                <tr key={n.name}>
                  <td className={clsx(TD, 'text-slate-200')}>{n.name}{n.dhcp ? <span className="ml-2 text-xs text-slate-500">DHCP</span> : null}</td>
                  <td className={clsx(TD, 'font-mono')}>{n.mac ?? '—'}</td>
                  <td className={clsx(TD, 'font-mono')}>{n.ip_addresses.join(', ') || '—'}</td>
                  <td className={clsx(TD, 'font-mono')}>{n.gateway ?? '—'}</td>
                  <td className={TD}>{n.speed_mbps ? `${n.speed_mbps >= 1000 ? `${n.speed_mbps / 1000} Gb/s` : `${n.speed_mbps} Mb/s`}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className={CARD}>
          <h2 className={H2}>Monitors</h2>
          {!inv.monitors?.length ? <Empty>No monitors collected.</Empty> : inv.monitors.map((m, i) => (
            <Row key={i} label={[m.manufacturer, m.model].filter(Boolean).join(' ') || 'Monitor'} value={m.serial_number && <span className="font-mono text-xs">{m.serial_number}</span>} />
          ))}
        </div>
        <div className={CARD}>
          <h2 className={H2}>Printers</h2>
          {!inv.printers?.length ? <Empty>No printers collected.</Empty> : inv.printers.map((p) => (
            <Row key={p.name} label={p.name} value={<span className="text-xs text-slate-400">{[p.is_default && 'default', p.is_network && 'network', p.driver].filter(Boolean).join(' · ')}</span>} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Software ────────────────────────────────────────────────────────────────
type SoftwareRow = { id: number; name: string; version: string | null; publisher: string | null };

export function SoftwareTab({ deviceId }: { deviceId: number }) {
  const { data } = useQuery({ queryKey: ['device-software', deviceId], queryFn: () => getDeviceSoftware(deviceId) });
  const rows = (data?.data ?? []) as SoftwareRow[];
  const { q, setQ, filtered } = useFilter(rows, (r) => `${r.name} ${r.publisher ?? ''}`);
  return (
    <div className={CARD}>
      <div className="flex items-center justify-between mb-4">
        <h2 className={clsx(H2, 'mb-0')}>Installed software ({rows.length})</h2>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by name or publisher…" className={FILTER} />
      </div>
      <table className="w-full text-left">
        <thead><tr className="border-b border-slate-700/50"><th className={TH}>Name</th><th className={TH}>Version</th><th className={TH}>Publisher</th></tr></thead>
        <tbody className="divide-y divide-slate-700/40">
          {filtered.map((s) => (
            <tr key={s.id}>
              <td className={clsx(TD, 'text-slate-200')}>{s.name}</td>
              <td className={clsx(TD, 'font-mono text-xs')}>{s.version ?? ''}</td>
              <td className={clsx(TD, 'text-slate-400')}>{s.publisher ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {filtered.length === 0 && <Empty>{rows.length ? 'No matches.' : 'No software collected.'}</Empty>}
    </div>
  );
}

// ── Patches ─────────────────────────────────────────────────────────────────
export function PatchesTab({ inv }: { inv: DeviceInventoryData }) {
  const rows = inv.patches ?? [];
  const { q, setQ, filtered } = useFilter(rows, (r) => `${r.patch_id} ${r.description ?? ''}`);
  return (
    <div className={CARD}>
      <div className="flex items-center justify-between mb-4">
        <h2 className={clsx(H2, 'mb-0')}>Installed updates ({rows.length})</h2>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter, e.g. KB5034441…" className={FILTER} />
      </div>
      <table className="w-full text-left">
        <thead><tr className="border-b border-slate-700/50"><th className={TH}>Update</th><th className={TH}>Description</th><th className={TH}>Installed</th></tr></thead>
        <tbody className="divide-y divide-slate-700/40">
          {filtered.map((p) => (
            <tr key={p.patch_id}>
              <td className={clsx(TD, 'font-mono text-slate-200')}>{p.patch_id}</td>
              <td className={TD}>{p.description ?? ''}</td>
              <td className={TD}>{fmtDate(p.installed_on) ?? <span className="text-slate-500">unknown</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {filtered.length === 0 && <Empty>{rows.length ? 'No matches.' : 'No updates collected for this device.'}</Empty>}
    </div>
  );
}

// ── Services ────────────────────────────────────────────────────────────────
export function ServicesTab({ inv }: { inv: DeviceInventoryData }) {
  const rows = inv.services ?? [];
  const [runningOnly, setRunningOnly] = useState(false);
  const base = runningOnly ? rows.filter((r) => r.state === 'running') : rows;
  const { q, setQ, filtered } = useFilter(base, (r) => `${r.name} ${r.display_name ?? ''}`);
  const running = rows.filter((r) => r.state === 'running').length;
  return (
    <div className={CARD}>
      <div className="flex items-center justify-between mb-4 gap-4">
        <h2 className={clsx(H2, 'mb-0')}>Services ({running} running of {rows.length})</h2>
        <div className="flex items-center gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-slate-400">
            <input type="checkbox" checked={runningOnly} onChange={(e) => setRunningOnly(e.target.checked)} className="accent-indigo-500" />
            Running only
          </label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter…" className={FILTER} />
        </div>
      </div>
      <table className="w-full text-left">
        <thead><tr className="border-b border-slate-700/50"><th className={TH}>Service</th><th className={TH}>State</th><th className={TH}>Start mode</th><th className={TH}>Runs as</th></tr></thead>
        <tbody className="divide-y divide-slate-700/40">
          {filtered.map((s) => (
            <tr key={s.name}>
              <td className={TD}>
                <span className="text-slate-200">{s.display_name || s.name}</span>
                {s.display_name && s.display_name !== s.name && <span className="block text-xs text-slate-500 font-mono">{s.name}</span>}
              </td>
              <td className={TD}><span className={clsx(s.state === 'running' ? 'text-emerald-400' : 'text-slate-500')}>{s.state ?? '—'}</span></td>
              <td className={clsx(TD, 'capitalize')}>{s.start_mode ?? '—'}</td>
              <td className={clsx(TD, 'text-slate-400')}>{s.account ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {filtered.length === 0 && <Empty>{rows.length ? 'No matches.' : 'No services collected.'}</Empty>}
    </div>
  );
}

// ── Users ───────────────────────────────────────────────────────────────────
export function UsersTab({ inv }: { inv: DeviceInventoryData }) {
  const rows = inv.local_accounts ?? [];
  const admins = rows.filter((a) => a.is_admin);
  return (
    <div className={CARD}>
      <h2 className={H2}>Local accounts ({rows.length}) · {admins.length} with admin rights</h2>
      {rows.length === 0 ? <Empty>No accounts collected.</Empty> : (
        <table className="w-full text-left">
          <thead><tr className="border-b border-slate-700/50"><th className={TH}>Account</th><th className={TH}>Admin</th><th className={TH}>Status</th><th className={TH}>Last sign-in</th></tr></thead>
          <tbody className="divide-y divide-slate-700/40">
            {[...rows].sort((a, b) => Number(!!b.is_admin) - Number(!!a.is_admin) || a.name.localeCompare(b.name)).map((a) => (
              <tr key={a.name}>
                <td className={clsx(TD, 'text-slate-200 font-mono')}>{a.name}</td>
                <td className={TD}>
                  {a.is_admin
                    ? <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset bg-yellow-500/15 text-yellow-400 ring-yellow-500/30">admin</span>
                    : <span className="text-slate-500">—</span>}
                </td>
                <td className={TD}>{a.enabled == null ? <span className="text-slate-500">{a.name.includes('\\') ? 'domain' : 'unknown'}</span> : a.enabled ? 'Enabled' : <span className="text-slate-500">Disabled</span>}</td>
                <td className={TD}>{fmtDate(a.last_logon, 'PP p') ?? <span className="text-slate-500">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Security ────────────────────────────────────────────────────────────────
export function SecurityTab({ inv }: { inv: DeviceInventoryData }) {
  const s = inv.summary as InventorySummary;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Antivirus', node: <Flag value={s.antivirus_ok} good="Protected" bad="Not protected" /> },
          { label: 'Firewall', node: <Flag value={s.firewall_ok} good="On" bad="Off" /> },
          { label: 'Disk encryption', node: <Flag value={s.disk_encrypted} good="Encrypted" bad="Not encrypted" /> },
          { label: 'Reboot', node: <Flag value={s.pending_reboot} good="Pending" bad="Not pending" unknown="Unknown" invert /> },
        ].map(({ label, node }) => (
          <div key={label} className={clsx(CARD, 'p-4')}>
            <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">{label}</p>
            {node}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className={CARD}>
          <h2 className={H2}>Antivirus products</h2>
          {inv.antivirus == null || inv.antivirus.length === 0 ? <Empty>No antivirus product reported.</Empty> : inv.antivirus.map((a) => (
            <div key={a.name} className="py-2.5 border-b border-slate-700/40 last:border-0">
              <p className="text-sm text-slate-200">{a.name}</p>
              <div className="flex flex-wrap gap-4 mt-1">
                <Flag value={a.enabled} good="Enabled" bad="Disabled" unknown="State unknown" />
                <Flag value={a.up_to_date} good="Definitions current" bad="Definitions out of date" unknown="Definitions unknown" />
                {a.definitions_date && <span className="text-xs text-slate-500 self-center">updated {fmtDate(a.definitions_date)}</span>}
              </div>
            </div>
          ))}
        </div>
        <div className={CARD}>
          <h2 className={H2}>Platform</h2>
          <Row label="Firewall profiles" value={s.firewall_profiles?.length ? (
            <span className="flex flex-col items-end gap-1">
              {s.firewall_profiles.map((p) => <Flag key={p.profile} value={p.enabled} good={`${p.profile}: on`} bad={`${p.profile}: off`} />)}
            </span>
          ) : null} />
          <Row label="TPM" value={s.tpm_present == null ? null : <Flag value={s.tpm_present && (s.tpm_ready ?? true)} good={s.tpm_ready ? 'Present, ready' : 'Present'} bad={s.tpm_present ? 'Present, not ready' : 'Not present'} />} />
          <Row label="Secure Boot" value={s.secure_boot == null ? null : <Flag value={s.secure_boot} good="On" bad="Off" />} />
          <Row label="Local admins" value={s.local_admin_count} />
        </div>
      </div>
    </div>
  );
}

// ── Changes ─────────────────────────────────────────────────────────────────
export function ChangesTab({ deviceId }: { deviceId: number }) {
  const [category, setCategory] = useState('');
  const PAGE = 100;
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useInfiniteQuery({
    queryKey: ['device-changes', deviceId, category],
    queryFn: ({ pageParam }) => getDeviceChanges(deviceId, { category: category || undefined, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.data.items.length, 0);
      return loaded < last.data.total ? loaded : undefined;
    },
  });
  const items = useMemo(() => data?.pages.flatMap((p) => p.data.items) ?? [], [data]);
  const total = data?.pages[0]?.data.total ?? 0;

  const byDay = useMemo(() => {
    const groups: [string, DeviceChange[]][] = [];
    for (const c of items) {
      const day = format(new Date(c.detected_at), 'EEEE, PP');
      const last = groups[groups.length - 1];
      if (last && last[0] === day) last[1].push(c); else groups.push([day, [c]]);
    }
    return groups;
  }, [items]);

  return (
    <div className={CARD}>
      <div className="flex items-center justify-between mb-4">
        <h2 className={clsx(H2, 'mb-0')}>Change history ({total})</h2>
        <select value={category} onChange={(e) => setCategory(e.target.value)} className={FILTER}>
          <option value="">All changes</option>
          {Object.entries(CHANGE_CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {!isLoading && items.length === 0 && (
        <Empty>No changes recorded yet. Changes appear from the second inventory report onwards — the first one is the baseline.</Empty>
      )}
      <div className="space-y-6">
        {byDay.map(([day, changes]) => (
          <div key={day}>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">{day}</p>
            <ul className="space-y-1.5">
              {changes.map((c) => (
                <li key={c.id} className={clsx('flex items-start gap-3 rounded-lg px-3 py-2',
                  c.severity === 'warning' ? 'bg-rose-500/10 ring-1 ring-inset ring-rose-500/20' : 'bg-slate-900/30')}>
                  {c.severity === 'warning'
                    ? <ShieldAlert className="w-4 h-4 text-rose-400 mt-0.5 shrink-0" />
                    : <AlertTriangle className="w-4 h-4 text-slate-600 mt-0.5 shrink-0 opacity-0" />}
                  <span className="flex-1 text-sm text-slate-200">{describeChange(c)}</span>
                  <span className="text-xs text-slate-500 shrink-0">{CHANGE_CATEGORY_LABELS[c.category]} · {format(new Date(c.detected_at), 'p')}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {hasNextPage && (
        <button onClick={() => fetchNextPage()} disabled={isFetchingNextPage}
          className="mt-4 text-sm text-indigo-400 hover:text-indigo-300 disabled:opacity-50">
          {isFetchingNextPage ? 'Loading…' : 'Load older changes'}
        </button>
      )}
    </div>
  );
}

// ── Virtual machines ────────────────────────────────────────────────────────
const POWER: Record<string, { label: string; cls: string }> = {
  on: { label: 'Running', cls: 'text-emerald-400' },
  off: { label: 'Off', cls: 'text-slate-500' },
  suspended: { label: 'Suspended', cls: 'text-amber-400' },
};
const PLATFORM: Record<string, string> = { hyperv: 'Hyper-V', vmware: 'VMware' };

function PowerState({ state }: { state: string | null }) {
  const p = state ? POWER[state] : undefined;
  return <span className={p?.cls ?? 'text-slate-400'}>{p?.label ?? state ?? '—'}</span>;
}

const allocation = (v: { vcpus: number | null; memory_gb: number | null }) =>
  [v.vcpus != null && `${v.vcpus} vCPU`, gb(v.memory_gb)].filter(Boolean).join(' · ') || null;

/** Overview card on a VM: which host it runs on. */
export function VmHostCard({ host }: { host: VmPlacementInfo }) {
  return (
    <div className={CARD}>
      <h2 className={clsx(H2, 'flex items-center gap-2')}><Layers className="w-4 h-4" /> Virtual machine</h2>
      <p className="text-slate-200">
        {PLATFORM[host.platform] ?? host.platform} guest <span className="font-medium">{host.vm_name}</span> on{' '}
        <Link to={`/devices/${host.device_id}`} className="text-indigo-400 hover:text-indigo-300 font-medium">
          {host.hostname ?? `device ${host.device_id}`}
        </Link>
        {host.cluster && <span className="text-slate-400"> · cluster {host.cluster}</span>}
      </p>
      <p className="text-xs text-slate-500 mt-1">
        <PowerState state={host.power_state} />
        {allocation(host) && ` · ${allocation(host)}`}
        {host.disk_gb != null && ` · ${gb(host.disk_gb)} disk`}
        {host.tools_status && ` · integration services: ${host.tools_status}`}
        {host.last_seen && ` · reported ${formatDistanceToNowStrict(new Date(host.last_seen))} ago`}
      </p>
    </div>
  );
}

/** Guests on a hypervisor host. */
export function VirtualMachinesTab({ virt }: { virt: DeviceVirtualization }) {
  const [runningOnly, setRunningOnly] = useState(false);
  const base = runningOnly ? virt.guests.filter((g) => g.power_state === 'on') : virt.guests;
  const { q, setQ, filtered } = useFilter(base, (g) => `${g.vm_name} ${g.hostname ?? ''} ${g.guest_os ?? ''} ${g.ip ?? ''}`);
  const t = virt.totals;
  return (
    <div className={CARD}>
      <div className="flex flex-wrap items-center justify-between mb-4 gap-4">
        <div>
          <h2 className={clsx(H2, 'mb-0')}>Virtual machines ({t.running} running of {t.guests})</h2>
          <p className="text-xs text-slate-500 mt-1">
            Running guests use {t.vcpus_running} vCPU and {gb(t.memory_gb_running) ?? '0 GB'} of memory.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-slate-400">
            <input type="checkbox" checked={runningOnly} onChange={(e) => setRunningOnly(e.target.checked)} className="accent-indigo-500" />
            Running only
          </label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter…" className={FILTER} />
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead><tr className="border-b border-slate-700/50">
            <th className={TH}>Virtual machine</th><th className={TH}>State</th><th className={TH}>Guest OS</th>
            <th className={TH}>Allocation</th><th className={TH}>Disk</th><th className={TH}>IP address</th>
            <th className={TH}>Integration services</th><th className={TH}>Inventory</th>
          </tr></thead>
          <tbody className="divide-y divide-slate-700/40">
            {filtered.map((g) => (
              <tr key={g.device_id}>
                <td className={TD}>
                  <Link to={`/devices/${g.device_id}`} className="text-indigo-400 hover:text-indigo-300">{g.vm_name}</Link>
                  {g.hostname && g.hostname.toLowerCase() !== g.vm_name.toLowerCase() && (
                    <span className="block text-xs text-slate-500">{g.hostname}</span>
                  )}
                </td>
                <td className={TD}><PowerState state={g.power_state} /></td>
                <td className={clsx(TD, 'text-slate-400')}>{g.guest_os ?? '—'}</td>
                <td className={clsx(TD, 'whitespace-nowrap')}>{allocation(g) ?? '—'}</td>
                <td className={clsx(TD, 'whitespace-nowrap')}>{gb(g.disk_gb) ?? '—'}</td>
                <td className={clsx(TD, 'font-mono text-xs')}>{g.ip ?? '—'}</td>
                <td className={clsx(TD, 'text-slate-400')}>{g.tools_status ?? '—'}</td>
                <td className={TD}>
                  {g.inventoried
                    ? <span className="text-emerald-400">Full</span>
                    : <span className="text-slate-500" title="Only what the host reports. Install the agent or scan the guest for software, updates and security.">Host view only</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 && <Empty>{virt.guests.length ? 'No matches.' : 'No virtual machines.'}</Empty>}
    </div>
  );
}

