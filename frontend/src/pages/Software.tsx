import { useQuery } from '@tanstack/react-query';
import { getLicensePosition, getSoftwareInventory } from '../api';
import { Package, Scale } from 'lucide-react';

const STATUS_STYLE: Record<string, string> = {
  compliant: 'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30',
  'over-deployed': 'bg-rose-500/20 text-rose-400 ring-rose-500/30',
  'under-utilized': 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
  unlimited: 'bg-slate-500/20 text-slate-400 ring-slate-500/30',
};

export default function Software() {
  const { data: lp } = useQuery({ queryKey: ['license-position'], queryFn: getLicensePosition });
  const { data: inv } = useQuery({ queryKey: ['software-inventory'], queryFn: getSoftwareInventory });

  const positions = lp?.data?.positions ?? [];
  const summary = lp?.data?.summary ?? {};
  const software = inv?.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
          <Scale className="w-8 h-8 text-indigo-400" /> Software & Licensing
        </h1>
        <p className="text-slate-400 mt-1">Effective License Position — entitlements reconciled against discovered installs.</p>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          ['Entitlements', summary.entitlements, 'text-slate-50'],
          ['Compliant', summary.compliant, 'text-emerald-400'],
          ['Over-deployed', summary.over_deployed, 'text-rose-400'],
          ['True-up needed (seats)', summary.total_shortfall_seats, 'text-yellow-400'],
        ].map(([label, val, color]) => (
          <div key={label as string} className="bg-slate-800/80 backdrop-blur-sm p-5 rounded-2xl border border-slate-700/50">
            <p className="text-sm text-slate-400">{label}</p>
            <p className={`text-3xl font-bold mt-1 ${color}`}>{val ?? 0}</p>
          </div>
        ))}
      </div>

      {/* License position */}
      <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl overflow-hidden">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider p-5 pb-3">License Position</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-800/30 text-xs font-semibold text-slate-400 tracking-wider">
                <th className="px-6 py-3">Product</th><th className="px-6 py-3">Model</th>
                <th className="px-6 py-3">Purchased</th><th className="px-6 py-3">Installs</th>
                <th className="px-6 py-3">Consumed</th><th className="px-6 py-3">Status</th><th className="px-6 py-3">Gap</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {positions.length === 0 ? (
                <tr><td colSpan={7} className="px-6 py-10 text-center text-slate-500">No entitlements yet. Add one under Entitlements.</td></tr>
              ) : positions.map((p: any) => (
                <tr key={p.entitlement_id} className="hover:bg-slate-800/40">
                  <td className="px-6 py-3 text-slate-200 font-medium">{p.product}</td>
                  <td className="px-6 py-3 text-sm text-slate-400">{p.license_model?.replace('_', ' ')}</td>
                  <td className="px-6 py-3 text-sm text-slate-300">{p.seats_purchased ?? '∞'}</td>
                  <td className="px-6 py-3 text-sm text-slate-300">{p.installs_discovered}</td>
                  <td className="px-6 py-3 text-sm text-slate-300">{p.consumed}</td>
                  <td className="px-6 py-3">
                    <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset ${STATUS_STYLE[p.status]}`}>
                      {p.status.replace('-', ' ')}
                    </span>
                  </td>
                  <td className={`px-6 py-3 text-sm font-medium ${p.gap > 0 ? 'text-rose-400' : p.gap < 0 ? 'text-slate-500' : 'text-slate-400'}`}>
                    {p.gap > 0 ? `+${p.gap}` : p.gap}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Discovered software inventory */}
      <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl overflow-hidden">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider p-5 pb-3 flex items-center gap-2">
          <Package className="w-4 h-4" /> Discovered Software ({software.length} products)
        </h2>
        <div className="overflow-x-auto max-h-[28rem] overflow-y-auto">
          <table className="w-full text-left border-collapse">
            <thead className="sticky top-0 bg-slate-800">
              <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
                <th className="px-6 py-3">Product (normalized)</th><th className="px-6 py-3">Installs (devices)</th><th className="px-6 py-3">Copies</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {software.length === 0 ? (
                <tr><td colSpan={3} className="px-6 py-10 text-center text-slate-500">No software discovered yet — deploy the agent to devices.</td></tr>
              ) : software.map((s: any) => (
                <tr key={s.product} className="hover:bg-slate-800/40">
                  <td className="px-6 py-2.5 text-sm text-slate-200">{s.product}</td>
                  <td className="px-6 py-2.5 text-sm text-slate-300">{s.installs}</td>
                  <td className="px-6 py-2.5 text-sm text-slate-500">{s.copies}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
