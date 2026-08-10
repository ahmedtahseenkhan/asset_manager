import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getAgentTokens, createAgentToken, toggleAgentToken } from '../api';
import { API_BASE } from '../api/client';
import { Radar, Plus, Copy, Power, Terminal } from 'lucide-react';
import { format } from 'date-fns';
import clsx from 'clsx';

export default function Agents() {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [newToken, setNewToken] = useState<string | null>(null);
  const { data } = useQuery({ queryKey: ['agent-tokens'], queryFn: getAgentTokens });
  const tokens = data?.data ?? [];

  const server = API_BASE.replace(/\/api$/, '') || window.location.origin;

  const create = useMutation({
    mutationFn: () => createAgentToken(name.trim()),
    onSuccess: (r) => { setNewToken(r.data.token); setName(''); queryClient.invalidateQueries({ queryKey: ['agent-tokens'] }); },
  });
  const toggle = useMutation({
    mutationFn: (id: number) => toggleAgentToken(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-tokens'] }),
  });

  const tok = newToken ?? '<agent-token>';
  const win = `powershell -ExecutionPolicy Bypass -File itam_agent.ps1 -Server "${server}" -Token "${tok}"`;
  const nix = `python3 itam_agent.py --server ${server} --token ${tok}`;

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
          <Radar className="w-8 h-8 text-indigo-400" /> Agents
        </h1>
        <p className="text-slate-400 mt-1">Deploy the lightweight agent to collect full OS, serial, and installed-software inventory — even off-network.</p>
      </div>

      {/* Create token */}
      <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">Enrollment tokens</h2>
        <div className="flex gap-3">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Token label, e.g. laptops-2026"
            className="flex-1 px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          <button onClick={() => create.mutate()} disabled={!name.trim() || create.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg">
            <Plus className="w-4 h-4" /> Create
          </button>
        </div>
        {newToken && (
          <div className="mt-4 p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg flex items-center gap-3">
            <span className="font-mono text-sm text-emerald-300 flex-1 break-all">{newToken}</span>
            <button onClick={() => navigator.clipboard?.writeText(newToken)} className="p-1.5 text-emerald-400 hover:bg-emerald-500/20 rounded" title="Copy">
              <Copy className="w-4 h-4" />
            </button>
          </div>
        )}
        {newToken && <p className="text-xs text-slate-500 mt-2">Copy this now — it won't be shown again.</p>}

        <table className="w-full text-left border-collapse mt-5">
          <thead>
            <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
              <th className="py-2">Label</th><th className="py-2">Token</th><th className="py-2">Reports</th><th className="py-2">Last used</th><th className="py-2">Status</th><th />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {tokens.map((t: any) => (
              <tr key={t.id}>
                <td className="py-2.5 text-sm text-slate-200">{t.name}</td>
                <td className="py-2.5 text-sm text-slate-500 font-mono">{t.token_hint}</td>
                <td className="py-2.5 text-sm text-slate-400">{t.reports_count}</td>
                <td className="py-2.5 text-sm text-slate-400">{t.last_used_at ? format(new Date(t.last_used_at), 'PP p') : 'never'}</td>
                <td className="py-2.5">
                  <span className={clsx('px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset',
                    t.active ? 'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30' : 'bg-slate-500/20 text-slate-400 ring-slate-500/30')}>
                    {t.active ? 'active' : 'disabled'}
                  </span>
                </td>
                <td className="py-2.5 text-right">
                  <button onClick={() => toggle.mutate(t.id)} className="p-1.5 text-slate-500 hover:text-white rounded" title="Toggle">
                    <Power className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
            {tokens.length === 0 && <tr><td colSpan={6} className="py-6 text-center text-slate-500 text-sm">No tokens yet.</td></tr>}
          </tbody>
        </table>
      </div>

      {/* Install instructions */}
      <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
          <Terminal className="w-4 h-4" /> Deploy the agent
        </h2>
        <div className="space-y-4">
          <div>
            <p className="text-sm text-slate-300 mb-1">Windows (PowerShell) — <code className="text-slate-400">agent/itam_agent.ps1</code></p>
            <pre className="text-xs text-slate-300 bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 overflow-x-auto font-mono">{win}</pre>
          </div>
          <div>
            <p className="text-sm text-slate-300 mb-1">macOS / Linux (Python 3) — <code className="text-slate-400">agent/itam_agent.py</code></p>
            <pre className="text-xs text-slate-300 bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 overflow-x-auto font-mono">{nix}</pre>
          </div>
          <p className="text-xs text-slate-500">Schedule daily (Task Scheduler / cron / launchd) for continuous inventory. The agent needs no inbound access — it reports outbound to the server.</p>
        </div>
      </div>
    </div>
  );
}
