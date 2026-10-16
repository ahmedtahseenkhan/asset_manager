import { useQuery } from '@tanstack/react-query';
import { getCostReport, getEolReport, getComplianceReport } from '../../api';
import { DollarSign, CalendarClock, ClipboardCheck } from 'lucide-react';

export default function ReportsOverview() {
  const { data: cost } = useQuery({ queryKey: ['report-cost'], queryFn: getCostReport });
  const { data: eol } = useQuery({ queryKey: ['report-eol'], queryFn: getEolReport });
  const { data: comp } = useQuery({ queryKey: ['report-compliance'], queryFn: getComplianceReport });

  const c = cost?.data; const e = eol?.data; const cp = comp?.data;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Cost */}
        <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
            <DollarSign className="w-4 h-4" /> Capital by category
          </h2>
          <p className="text-3xl font-bold text-slate-50 mb-4">${(c?.total_capital ?? 0).toLocaleString()}</p>
          <ul className="space-y-2">
            {(c?.by_category ?? []).map((x: any) => (
              <li key={x.category} className="flex justify-between text-sm">
                <span className="text-slate-300 capitalize">{x.category} <span className="text-slate-500">({x.count})</span></span>
                <span className="text-slate-200">${x.cost.toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* EOL forecast */}
        <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
            <CalendarClock className="w-4 h-4" /> Lifecycle forecast (12 mo)
          </h2>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <p className="text-xs text-slate-500 uppercase mb-1">Warranty</p>
              <p className="text-sm text-slate-300">{e?.warranty?.expired ?? 0} expired · {e?.warranty?.within_horizon ?? 0} upcoming</p>
            </div>
            <div>
              <p className="text-xs text-slate-500 uppercase mb-1">EOL / EOS</p>
              <p className="text-sm text-slate-300">{e?.eol_eos?.expired ?? 0} past · {e?.eol_eos?.within_horizon ?? 0} upcoming</p>
            </div>
          </div>
          <ul className="space-y-1.5 max-h-40 overflow-y-auto">
            {(e?.upcoming_eol ?? []).map((x: any) => (
              <li key={x.asset_tag} className="flex justify-between text-sm">
                <span className="text-slate-300">{x.name}</span>
                <span className="text-slate-500">{x.eol_eos_date}</span>
              </li>
            ))}
            {(e?.upcoming_eol ?? []).length === 0 && <li className="text-sm text-slate-500">No EOL dates within the horizon.</li>}
          </ul>
        </div>
      </div>

      {/* Compliance */}
      <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
          <ClipboardCheck className="w-4 h-4" /> Compliance & governance
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <div>
            <p className="text-xs text-slate-500 uppercase mb-2">By criticality</p>
            {Object.entries(cp?.by_criticality ?? {}).map(([k, v]) => (
              <div key={k} className="flex justify-between text-sm"><span className="text-slate-300 capitalize">{k}</span><span className="text-slate-400">{String(v)}</span></div>
            ))}
          </div>
          <div>
            <p className="text-xs text-slate-500 uppercase mb-2">Data classification</p>
            {Object.entries(cp?.by_data_classification ?? {}).map(([k, v]) => (
              <div key={k} className="flex justify-between text-sm"><span className="text-slate-300 capitalize">{k}</span><span className="text-slate-400">{String(v)}</span></div>
            ))}
          </div>
          <div>
            <p className="text-xs text-slate-500 uppercase mb-2">Ownership</p>
            <p className="text-2xl font-bold text-slate-50">{cp?.with_owner_pct ?? 0}%</p>
            <p className="text-xs text-slate-500">have a point of contact</p>
          </div>
          <div>
            <p className="text-xs text-slate-500 uppercase mb-2">Reviewed</p>
            <p className="text-2xl font-bold text-slate-50">{cp?.reviewed_pct ?? 0}%</p>
            <p className="text-xs text-slate-500">have a review date</p>
          </div>
        </div>
      </div>
    </div>
  );
}
