import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getSwitchPorts } from '../../api';
import clsx from 'clsx';

/** Port table of a switch/router: status, VLAN, LLDP/CDP neighbour and what is plugged in. */
export default function SwitchPorts({ deviceId }: { deviceId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['switch-ports', deviceId], queryFn: () => getSwitchPorts(deviceId),
  });
  const ports = data?.data ?? [];
  if (isLoading) return <p className="text-sm text-slate-500">Loading ports…</p>;
  if (!ports.length) return <p className="text-sm text-slate-500">No port data collected from this device.</p>;
  return (
    <table className="w-full text-left">
      <thead>
        <tr className="text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-700/50">
          <th className="py-1.5">Port</th><th className="py-1.5">VLAN</th><th className="py-1.5">Connected</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-700/40">
        {ports.map((p) => (
          <tr key={p.id} className="align-top">
            <td className="py-1.5 pr-2 text-xs">
              <span className="inline-flex items-center gap-1.5 text-slate-200">
                <span className={clsx('w-1.5 h-1.5 rounded-full', p.oper_up ? 'bg-emerald-400' : p.oper_up === false ? 'bg-slate-500' : 'bg-slate-700')} />
                {p.name ?? `if${p.if_index}`}
              </span>
              {p.alias && <span className="block text-[11px] text-slate-500">{p.alias}</span>}
            </td>
            <td className="py-1.5 pr-2 text-xs text-slate-400">{p.vlan ?? '—'}</td>
            <td className="py-1.5 text-xs text-slate-300">
              {p.neighbors.map((n, i) => (
                <span key={i} className="block">
                  {n.device_id ? <Link to={`/devices/${n.device_id}`} className="text-indigo-400 hover:text-indigo-300">{n.name}</Link> : n.name}
                  <span className="text-slate-500"> {n.port} · {n.protocol.toUpperCase()}</span>
                </span>
              ))}
              {p.uplink && !p.neighbors.length && <span className="text-slate-500">uplink · {p.mac_count} MACs</span>}
              {p.connected.map((c) => (
                <span key={c.mac} className="block">
                  {c.device_id ? <Link to={`/devices/${c.device_id}`} className="text-indigo-400 hover:text-indigo-300">{c.hostname ?? c.ip ?? c.mac}</Link>
                    : <span className="font-mono text-slate-400">{c.mac}</span>}
                  {c.ip && c.device_id && <span className="text-slate-500"> {c.ip}</span>}
                </span>
              ))}
              {!p.uplink && !p.neighbors.length && !p.connected.length && <span className="text-slate-600">—</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
