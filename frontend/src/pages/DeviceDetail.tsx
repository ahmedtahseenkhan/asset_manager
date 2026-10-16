import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getDeviceById, getDeviceInventory, getDeviceVirtualization } from '../api';
import type { DeviceSource } from '../types';
import {
  ChangesTab, Flag, HardwareTab, PatchesTab, SecurityTab, ServicesTab, SoftwareTab, UsersTab,
  VirtualMachinesTab, VmHostCard,
} from '../components/device/InventoryTabs';
import clsx from 'clsx';
import NetworkLocation from '../components/topology/NetworkLocation';
import SwitchPorts from '../components/topology/SwitchPorts';
import { getSwitchPorts } from '../api';
import {
  ArrowLeft, Laptop, Clock, Globe, Network, Cpu, Radar,
  ChevronDown, ChevronRight, CheckCircle2, XCircle, AlertCircle,
} from 'lucide-react';
import { format } from 'date-fns';

const SOURCE_COLORS: Record<string, string> = {
  ad:          'bg-blue-500/20 text-blue-400 ring-blue-500/30',
  crowdstrike: 'bg-red-500/20 text-red-400 ring-red-500/30',
  defender:    'bg-cyan-500/20 text-cyan-400 ring-cyan-500/30',
  mcafee:      'bg-orange-500/20 text-orange-400 ring-orange-500/30',
  symantec:    'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
  mock:        'bg-slate-500/20 text-slate-400 ring-slate-500/30',
};

const STATUS_CONFIG = {
  active:   { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10 ring-emerald-500/20', label: 'Active' },
  inactive: { icon: XCircle,      color: 'text-slate-400',   bg: 'bg-slate-500/10 ring-slate-500/20',   label: 'Inactive' },
  retired:  { icon: AlertCircle,  color: 'text-rose-400',    bg: 'bg-rose-500/10 ring-rose-500/20',     label: 'Retired' },
};

function SourceBadge({ name }: { name: string }) {
  const style = SOURCE_COLORS[name] ?? 'bg-purple-500/20 text-purple-400 ring-purple-500/30';
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold uppercase ring-1 ring-inset ${style}`}>
      {name}
    </span>
  );
}

function RawDataAccordion({ source }: { source: DeviceSource }) {
  const [open, setOpen] = useState(false);
  const style = SOURCE_COLORS[source.source_name] ?? 'bg-purple-500/20 text-purple-400 ring-purple-500/30';

  return (
    <div className="border border-slate-700/50 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-5 py-4 bg-slate-800/60 hover:bg-slate-800 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold uppercase ring-1 ring-inset ${style}`}>
            {source.source_name}
          </span>
          {source.source_uid && (
            <span className="text-xs text-slate-500 font-mono">uid: {source.source_uid}</span>
          )}
          {source.last_synced && (
            <span className="text-xs text-slate-500">
              Last synced {format(new Date(source.last_synced), 'MMM d, yyyy HH:mm')}
            </span>
          )}
        </div>
        {open ? (
          <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-400 shrink-0" />
        )}
      </button>

      {open && (
        <div className="bg-slate-900/60 border-t border-slate-700/50 p-5">
          <pre className="text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
            {JSON.stringify(source.raw_data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between py-3 border-b border-slate-700/40 last:border-0">
      <span className="text-sm text-slate-400 shrink-0 w-32">{label}</span>
      <span className="text-sm text-slate-200 text-right">{value ?? <span className="text-slate-600">—</span>}</span>
    </div>
  );
}

export default function DeviceDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data: res, isLoading, isError } = useQuery({
    queryKey: ['device', id],
    queryFn: () => getDeviceById(Number(id)),
    enabled: !!id,
  });

  const device = res?.data;
  const { data: invRes } = useQuery({
    queryKey: ['device-inventory', id],
    queryFn: () => getDeviceInventory(Number(id)),
    enabled: !!id,
  });
  const inv = invRes?.data;
  const { data: portsRes } = useQuery({
    queryKey: ['switch-ports', Number(id)], queryFn: () => getSwitchPorts(Number(id)), enabled: !!id, retry: false,
  });
  const { data: virtRes } = useQuery({
    queryKey: ['device-virtualization', id],
    queryFn: () => getDeviceVirtualization(Number(id)),
    enabled: !!id,
  });
  const virt = virtRes?.data;
  const [tab, setTab] = useState('overview');

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400">
        <div className="text-center space-y-3">
          <div className="animate-spin w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full mx-auto" />
          <p>Loading device…</p>
        </div>
      </div>
    );
  }

  if (isError || !device) {
    return (
      <div className="text-center py-24 text-slate-400">
        <Laptop className="w-12 h-12 mx-auto mb-4 opacity-30" />
        <p className="text-lg">Device not found.</p>
        <button onClick={() => navigate('/devices')} className="mt-4 text-indigo-400 hover:underline text-sm">
          Back to inventory
        </button>
      </div>
    );
  }

  const statusCfg = STATUS_CONFIG[device.status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.active;
  const StatusIcon = statusCfg.icon;

  // Surface the network-scan enrichment (stored per-source in raw_data.extra).
  const scanSource = device.sources.find((s) => s.source_name === 'network_scan')
    ?? device.sources.find((s) => s.raw_data?.extra && 'open_ports' in (s.raw_data.extra as object));
  const extra = scanSource?.raw_data?.extra as Record<string, unknown> | undefined;
  const hasAgent = device.sources.some((s) => s.source_name === 'agent');
  const summary = inv?.summary ?? null;
  // A VM seen only through its hypervisor has a summary but no inventory of its own
  const fullInventory = (summary?.sections_collected.length ?? 0) > 0;
  const hasPorts = (portsRes?.data?.length ?? 0) > 0;
  const tabs = [
    { id: 'overview', label: 'Overview', show: true },
    { id: 'hardware', label: 'Hardware', show: !!summary },
    { id: 'software', label: 'Software', show: hasAgent || fullInventory },
    { id: 'patches', label: 'Updates', show: !!summary?.sections_collected.includes('patches') },
    { id: 'services', label: 'Services', show: !!summary?.sections_collected.includes('services') },
    { id: 'users', label: 'Users', show: !!summary?.sections_collected.includes('local_accounts') },
    { id: 'vms', label: `Virtual machines (${virt?.totals.guests ?? 0})`, show: (virt?.totals.guests ?? 0) > 0 },
    { id: 'security', label: 'Security', show: fullInventory },
    { id: 'changes', label: 'Changes', show: fullInventory },
    { id: 'ports', label: 'Ports', show: hasPorts },
  ].filter((t) => t.show);
  const activeTab = tabs.some((t) => t.id === tab) ? tab : 'overview';

  return (
    <div className="space-y-6">
      {/* Back button */}
      <button
        onClick={() => navigate('/devices')}
        className="flex items-center gap-2 text-slate-400 hover:text-slate-50 transition-colors text-sm"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Device Inventory
      </button>

      {/* Hero */}
      <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="p-4 bg-indigo-500/10 rounded-2xl">
              <Laptop className="w-10 h-10 text-indigo-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-50">
                {device.hostname ?? <span className="text-slate-500">Unknown Host</span>}
              </h1>
              {device.fqdn && device.fqdn !== device.hostname && (
                <p className="text-slate-400 text-sm mt-0.5">{device.fqdn}</p>
              )}
              <div className="flex flex-wrap gap-2 mt-2">
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ring-1 ring-inset capitalize ${statusCfg.bg} ${statusCfg.color}`}>
                  <StatusIcon className="w-3 h-3" />
                  {statusCfg.label}
                </span>
                {device.os_name && (
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-500/10 text-indigo-400 ring-1 ring-inset ring-indigo-500/20">
                    <Cpu className="w-3 h-3 mr-1" />
                    {device.os_name}{device.os_version ? ` ${device.os_version}` : ''}
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {device.sources.map((s) => (
              <SourceBadge key={s.source_name} name={s.source_name} />
            ))}
          </div>
        </div>
        {summary && (
          <div className="flex flex-wrap gap-x-6 gap-y-2 mt-5 pt-4 border-t border-slate-700/40">
            {fullInventory ? <>
              <Flag value={summary.antivirus_ok} good="Antivirus OK" bad="No working antivirus" unknown="Antivirus unknown" />
              <Flag value={summary.firewall_ok} good="Firewall on" bad="Firewall off" unknown="Firewall unknown" />
              <Flag value={summary.disk_encrypted} good="Disk encrypted" bad="Disk not encrypted" unknown="Encryption unknown" />
              {summary.pending_reboot && <Flag value={true} good="Reboot pending" bad="" invert />}
            </> : virt?.host && (
              <span className="text-sm text-slate-500">
                Only what the hypervisor reports. Install the agent or scan this machine for software, updates and security.
              </span>
            )}
            {summary.collected_at && (
              <span className="text-xs text-slate-500 self-center ml-auto">
                Inventory {format(new Date(summary.collected_at), 'MMM d, yyyy HH:mm')} · {summary.source} {summary.collector_version ?? ''}
              </span>
            )}
          </div>
        )}
      </div>

      {tabs.length > 1 && (
        <div className="flex gap-1 border-b border-slate-700/60 overflow-x-auto">
          {tabs.map((t) => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={clsx('px-4 py-2.5 text-sm font-medium border-b-2 -mb-px whitespace-nowrap',
                activeTab === t.id ? 'border-indigo-500 text-slate-50' : 'border-transparent text-slate-400 hover:text-slate-200')}>
              {t.label}
            </button>
          ))}
        </div>
      )}

      {activeTab === 'hardware' && inv && <HardwareTab inv={inv} serial={device.serial_number} />}
      {activeTab === 'software' && <SoftwareTab deviceId={device.id} />}
      {activeTab === 'patches' && inv && <PatchesTab inv={inv} />}
      {activeTab === 'services' && inv && <ServicesTab inv={inv} />}
      {activeTab === 'users' && inv && <UsersTab inv={inv} />}
      {activeTab === 'security' && inv && <SecurityTab inv={inv} />}
      {activeTab === 'vms' && virt && <VirtualMachinesTab virt={virt} />}
      {activeTab === 'changes' && <ChangesTab deviceId={device.id} />}
      {activeTab === 'ports' && (
        <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6"><SwitchPorts deviceId={device.id} /></div>
      )}

      {activeTab === 'overview' && <>
      {virt?.host && <VmHostCard host={virt.host} />}
      <NetworkLocation deviceId={device.id} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Identity */}
        <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
            <Globe className="w-4 h-4" /> Identity
          </h2>
          <div>
            <InfoRow label="Hostname"  value={device.hostname} />
            <InfoRow label="FQDN"      value={device.fqdn} />
            <InfoRow label="Domain"    value={device.domain} />
            <InfoRow label="OU"        value={device.ou} />
            <InfoRow label="Device ID" value={<span className="font-mono text-xs">{device.id}</span>} />
          </div>
        </div>

        {/* Timeline */}
        <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
            <Clock className="w-4 h-4" /> Timeline
          </h2>
          <div>
            <InfoRow
              label="First Seen"
              value={device.first_seen ? format(new Date(device.first_seen), 'MMM d, yyyy HH:mm') : null}
            />
            <InfoRow
              label="Last Seen"
              value={device.last_seen ? format(new Date(device.last_seen), 'MMM d, yyyy HH:mm') : null}
            />
            <InfoRow label="Sources"   value={`${device.sources.length} connector${device.sources.length !== 1 ? 's' : ''}`} />
            <InfoRow
              label="Last Synced"
              value={
                device.sources.length > 0 && device.sources[0].last_synced
                  ? format(new Date(device.sources[0].last_synced), 'MMM d, yyyy HH:mm')
                  : null
              }
            />
          </div>
        </div>

        {/* Network */}
        <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
            <Network className="w-4 h-4" /> Network
          </h2>
          {device.ip_addresses?.length > 0 ? (
            <div className="space-y-1 mb-4">
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">IP Addresses</p>
              {device.ip_addresses.map((ip) => (
                <span key={ip} className="block font-mono text-sm text-slate-200">{ip}</span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500 mb-4">No IP addresses recorded</p>
          )}
          {device.mac_addresses?.length > 0 && (
            <div className="space-y-1 border-t border-slate-700/40 pt-4">
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">MAC Addresses</p>
              {device.mac_addresses.map((mac) => (
                <span key={mac} className="block font-mono text-sm text-slate-200">{mac}</span>
              ))}
            </div>
          )}
        </div>

        {/* Per-source last sync times */}
        <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
            Source Coverage
          </h2>
          {device.sources.length === 0 ? (
            <p className="text-sm text-slate-500">No sources have reported this device.</p>
          ) : (
            <div>
              {device.sources.map((s) => (
                <div key={s.source_name} className="flex items-center justify-between py-2.5 border-b border-slate-700/40 last:border-0">
                  <SourceBadge name={s.source_name} />
                  <span className="text-xs text-slate-400">
                    {s.last_synced
                      ? format(new Date(s.last_synced), 'MMM d, yyyy HH:mm')
                      : 'Never'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Discovery details — network scan enrichment, surfaced from raw_data.extra */}
      {extra && (
        <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
            <Radar className="w-4 h-4" /> Discovery Details
            <span className="text-xs font-normal text-slate-500 normal-case">via {scanSource!.source_name}</span>
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
            <div>
              <InfoRow label="Operating System" value={device.os_name} />
              <InfoRow label="Role / Type" value={extra.role as string} />
              <InfoRow label="Model" value={extra.model as string} />
              <InfoRow label="Open Ports" value={
                Array.isArray(extra.open_ports) && extra.open_ports.length
                  ? <span className="font-mono">{(extra.open_ports as number[]).join(', ')}</span> : null
              } />
              <InfoRow label="SSDP Server" value={extra.ssdp_server as string} />
              <InfoRow label="SNMP" value={extra.snmp_descr as string} />
            </div>
            <div>
              <InfoRow label="Name Source" value={extra.name_source as string} />
              <InfoRow label="TTL" value={extra.ttl != null ? String(extra.ttl) : null} />
              <InfoRow label="Responded to Ping" value={
                extra.ping != null ? (extra.ping ? 'Yes' : 'No') : null
              } />
              <InfoRow label="In ARP Table" value={
                extra.arp != null ? (extra.arp ? 'Yes' : 'No') : null
              } />
              <InfoRow label="Method" value={extra.method as string} />
            </div>
          </div>
          <p className="text-xs text-slate-500 mt-4">
            A network scan reports presence and best-effort classification. OS version,
            serial number and installed software require an agent — not available from a scan.
          </p>
        </div>
      )}

      {/* Raw source data */}
      {device.sources.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
            Raw Source Data
          </h2>
          <div className="space-y-3">
            {device.sources.map((s) => (
              <RawDataAccordion key={s.source_name} source={s} />
            ))}
          </div>
        </div>
      )}
      </>}
    </div>
  );
}
