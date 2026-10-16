import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getDeviceLocation } from '../../api';
import { Cable } from 'lucide-react';
import { formatDistanceToNowStrict } from 'date-fns';

/** "Plugged into SWITCH port X (VLAN n)" — hidden when topology isn't licensed or nothing is known. */
export default function NetworkLocation({ deviceId }: { deviceId: number }) {
  const { data } = useQuery({ queryKey: ['device-location', deviceId], queryFn: () => getDeviceLocation(deviceId), retry: false });
  const locs = data?.data ?? [];
  if (!locs.length) return null;
  const best = locs[0];
  return (
    <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6">
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
        <Cable className="w-4 h-4" /> Network location
      </h2>
      <p className="text-slate-200">
        {best.uplink ? 'Seen behind ' : 'Plugged into '}
        <Link to={`/devices/${best.switch_id}`} className="text-indigo-400 hover:text-indigo-300 font-medium">{best.switch}</Link>
        {' '}port <span className="font-mono">{best.port}</span>
        {best.port_alias && <span className="text-slate-400"> ({best.port_alias})</span>}
        {best.vlan != null && <span className="text-slate-400"> · VLAN {best.vlan}</span>}
      </p>
      <p className="text-xs text-slate-500 mt-1">
        MAC {best.mac}
        {best.last_seen && ` · seen ${formatDistanceToNowStrict(new Date(best.last_seen))} ago`}
        {best.uplink && ' · only seen on uplinks: the access switch has not been scanned'}
      </p>
    </div>
  );
}
