import { useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getPostureSummary, getVulnSummary, getLogCoverage, getCmdbAudit, importVulnerabilities } from '../api';
import { ShieldCheck, Upload, Bug, Radio, GitMerge } from 'lucide-react';
import clsx from 'clsx';
import { useAuth } from '../context/AuthContext';

const SEV_COLOR: Record<string, string> = {
  critical: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',
  high: 'bg-orange-500/20 text-orange-400 ring-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
  low: 'bg-blue-500/20 text-blue-400 ring-blue-500/30',
  info: 'bg-slate-500/20 text-slate-400 ring-slate-500/30',
};

function Ring({ pct }: { pct: number }) {
  const color = pct >= 80 ? 'text-emerald-400' : pct >= 40 ? 'text-yellow-400' : 'text-rose-400';
  return (
    <div className="flex items-center gap-3">
      <div className="w-14 h-14 rounded-full bg-slate-700/40 grid place-items-center relative">
        <span className={clsx('text-sm font-bold', color)}>{pct}%</span>
      </div>
    </div>
  );
}

export default function Posture() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const { data: p } = useQuery({ queryKey: ['posture'], queryFn: getPostureSummary });
  const { data: v } = useQuery({ queryKey: ['vuln-summary'], queryFn: getVulnSummary });
  const { data: lc } = useQuery({ queryKey: ['log-coverage'], queryFn: getLogCoverage });
  const { data: audit } = useQuery({ queryKey: ['cmdb-audit'], queryFn: getCmdbAudit });

  const controls = p?.data?.controls ?? {};
  const vuln = v?.data;
  const cov = lc?.data;
  const au = audit?.data;

  const upload = useMutation({
    mutationFn: (file: File) => importVulnerabilities(file),
    onSuccess: (r) => {
      setMsg({ ok: true, text: `${r.message}${r.data?.unmatched ? ` (${r.data.unmatched} unmatched)` : ''}` });
      ['posture', 'vuln-summary', 'cmdb-audit'].forEach((k) => queryClient.invalidateQueries({ queryKey: [k] }));
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMsg({ ok: false, text: d ?? 'Import failed' });
    },
  });

  const CONTROL_LABELS: Record<string, string> = {
    agent_coverage: 'Agent coverage',
    log_source_coverage: 'Log-source coverage',
    data_classified: 'Data classified',
    vuln_scanned: 'Vuln scanned',
    monitored: 'Monitored',
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
            <ShieldCheck className="w-8 h-8 text-indigo-400" /> Security Posture
          </h1>
          <p className="text-slate-400 mt-1">Cyber asset attack-surface view — control coverage, vulnerabilities, and gaps.</p>
        </div>
        {(user?.role === 'admin' || user?.role === 'asset_manager') && (
          <>
            <input ref={fileRef} type="file" accept=".csv" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ''; }} />
            <button onClick={() => fileRef.current?.click()} disabled={upload.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg">
              <Upload className="w-4 h-4" /> Import vulnerabilities (CSV)
            </button>
          </>
        )}
      </div>
      {msg && <p className={clsx('text-sm', msg.ok ? 'text-emerald-400' : 'text-rose-400')}>{msg.text}</p>}

      {/* Control coverage */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {Object.entries(CONTROL_LABELS).map(([key, label]) => {
          const c = controls[key] ?? { count: 0, pct: 0 };
          return (
            <div key={key} className="bg-slate-800/80 backdrop-blur-sm p-4 rounded-2xl border border-slate-700/50">
              <p className="text-xs text-slate-400 mb-2">{label}</p>
              <Ring pct={c.pct} />
              <p className="text-xs text-slate-500 mt-2">{c.count} of {p?.data?.total_assets ?? 0} assets</p>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Vulnerabilities */}
        <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Bug className="w-4 h-4" /> Open vulnerabilities ({vuln?.total_open ?? 0})
          </h2>
          <div className="flex flex-wrap gap-2 mb-5">
            {Object.entries(vuln?.open_by_severity ?? {}).map(([sev, n]) => (
              <span key={sev} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold ring-1 ring-inset ${SEV_COLOR[sev]}`}>
                {sev} {String(n)}
              </span>
            ))}
          </div>
          <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Top risk assets</p>
          <ul className="space-y-2">
            {(vuln?.top_risk_assets ?? []).slice(0, 6).map((a: any) => (
              <li key={a.asset_tag} className="flex items-center justify-between text-sm">
                <span className="text-slate-200">{a.name}</span>
                <span className="flex items-center gap-2">
                  {Object.entries(a.counts).map(([s, n]) => (
                    <span key={s} className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${SEV_COLOR[s]}`}>{String(n)} {s[0].toUpperCase()}</span>
                  ))}
                  <span className="text-slate-500 font-mono text-xs w-10 text-right">{a.score}</span>
                </span>
              </li>
            ))}
            {(vuln?.top_risk_assets ?? []).length === 0 && <li className="text-sm text-slate-500">No vulnerabilities imported yet.</li>}
          </ul>
        </div>

        {/* Log-source coverage */}
        <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Radio className="w-4 h-4" /> Log-source coverage
          </h2>
          <div className="flex items-baseline gap-3 mb-4">
            <span className="text-3xl font-bold text-slate-50">{cov?.coverage_pct ?? 0}%</span>
            <span className="text-sm text-slate-400">{cov?.onboarded ?? 0} of {cov?.total_deployed ?? 0} deployed assets onboarded</span>
          </div>
          <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Gaps (not sending logs)</p>
          <ul className="space-y-1.5 max-h-52 overflow-y-auto">
            {(cov?.gaps ?? []).slice(0, 10).map((g: any) => (
              <li key={g.asset_tag} className="flex items-center justify-between text-sm">
                <span className="text-slate-300">{g.name}</span>
                {g.criticality && <span className="text-xs text-slate-500">{g.criticality}</span>}
              </li>
            ))}
            {(cov?.gaps ?? []).length === 0 && <li className="text-sm text-emerald-400">All deployed assets onboarded.</li>}
          </ul>
        </div>
      </div>

      {/* CMDB audit */}
      <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
          <GitMerge className="w-4 h-4" /> CMDB health
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-center">
          {[
            ['Devices', au?.totals?.devices],
            ['Managed', `${au?.totals?.coverage_pct ?? 0}%`],
            ['Unmanaged', au?.unmanaged_count],
            ['Duplicate hosts', au?.duplicate_hostnames?.length],
            ['Stale assets', au?.stale_count],
          ].map(([label, val]) => (
            <div key={label as string}>
              <p className="text-2xl font-bold text-slate-50">{val ?? 0}</p>
              <p className="text-xs text-slate-400 mt-1">{label}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
