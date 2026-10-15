import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getAgentTokens, createAgentToken, toggleAgentToken, getAgentFleet } from '../api';
import { Link } from 'react-router-dom';
import { API_BASE } from '../api/client';
import { Radar, Plus, Copy, Power, Terminal, Download, MonitorCheck } from 'lucide-react';
import { format, formatDistanceToNowStrict, differenceInDays } from 'date-fns';
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

  const { data: fleetRes } = useQuery({ queryKey: ['agent-fleet'], queryFn: getAgentFleet });
  const fleet = fleetRes?.data;

  const tok = newToken ?? '<agent-token>';
  const dl = `${server}/api/agents/download`;
  const winInstall = `iwr -UseBasicParsing "${dl}/install_agent.ps1" -OutFile install_agent.ps1; powershell -ExecutionPolicy Bypass -File .\\install_agent.ps1 -Server "${server}" -Token "${tok}"`;
  const nixInstall = `curl -fsSL ${dl}/install_agent.sh | sudo sh -s -- --server ${server} --token ${tok}`;
  const win = `powershell -ExecutionPolicy Bypass -File itam_agent.ps1 -Server "${server}" -Token "${tok}"`;
  const nix = `python3 itam_agent.py --server ${server} --token ${tok}`;

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
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
                  <button onClick={() => toggle.mutate(t.id)} className="p-1.5 text-slate-500 hover:text-slate-50 rounded" title="Toggle">
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
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-1 flex items-center gap-2">
          <Terminal className="w-4 h-4" /> Install the agent
        </h2>
        <p className="text-xs text-slate-500 mb-4">
          Installs the agent, schedules a daily report plus one shortly after boot, and sends the first report right away.
          {!newToken && ' Create a token above and the commands below fill it in.'}
        </p>
        <div className="space-y-4">
          {[
            { label: 'Windows — in an elevated PowerShell', cmd: winInstall },
            { label: 'macOS / Linux — in a terminal (needs sudo)', cmd: nixInstall },
          ].map(({ label, cmd }) => (
            <div key={label}>
              <p className="text-sm text-slate-300 mb-1">{label}</p>
              <div className="flex gap-2">
                <pre className="flex-1 text-xs text-slate-300 bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 overflow-x-auto font-mono">{cmd}</pre>
                <button onClick={() => navigator.clipboard?.writeText(cmd)} className="p-2 text-slate-500 hover:text-slate-50 self-start" title="Copy">
                  <Copy className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
          <details className="text-sm">
            <summary className="cursor-pointer text-slate-400 hover:text-slate-200">Run once without installing, or deploy with GPO / Intune / MDM</summary>
            <div className="mt-3 space-y-3">
              <pre className="text-xs text-slate-300 bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 overflow-x-auto font-mono">{win}</pre>
              <pre className="text-xs text-slate-300 bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 overflow-x-auto font-mono">{nix}</pre>
              <p className="text-xs text-slate-500">
                For software deployment tools, ship the installer together with the agent script (it uses a copy found next to itself) and run it with the same arguments.
              </p>
              <div className="flex flex-wrap gap-3">
                {['install_agent.ps1', 'itam_agent.ps1', 'install_agent.sh', 'itam_agent.py'].map((f) => (
                  <a key={f} href={`${dl}/${f}`} className="inline-flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300">
                    <Download className="w-3.5 h-3.5" />{f}
                  </a>
                ))}
              </div>
            </div>
          </details>
        </div>
      </div>

      {/* Fleet */}
      <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
          <MonitorCheck className="w-4 h-4" /> Reporting devices ({fleet?.agents.length ?? 0})
          {fleet && <span className="text-xs font-normal text-slate-500 normal-case">current agent version {fleet.latest_version}</span>}
        </h2>
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
              <th className="py-2">Device</th><th className="py-2">Operating system</th><th className="py-2">Agent</th><th className="py-2">Last report</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {(fleet?.agents ?? []).map((a) => {
              const stale = a.last_report ? differenceInDays(new Date(), new Date(a.last_report)) >= 7 : true;
              return (
                <tr key={a.device_id}>
                  <td className="py-2.5 text-sm"><Link to={`/devices/${a.device_id}`} className="text-slate-200 hover:text-indigo-400">{a.hostname ?? `#${a.device_id}`}</Link></td>
                  <td className="py-2.5 text-sm text-slate-400">{a.os_name ?? '—'}</td>
                  <td className="py-2.5 text-sm">
                    <span className="font-mono text-slate-300">{a.version ?? 'unknown'}</span>
                    {a.outdated && <span className="ml-2 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset bg-yellow-500/15 text-yellow-400 ring-yellow-500/30">update</span>}
                  </td>
                  <td className={clsx('py-2.5 text-sm', stale ? 'text-yellow-400' : 'text-slate-400')}>
                    {a.last_report ? `${formatDistanceToNowStrict(new Date(a.last_report))} ago` : 'never'}
                  </td>
                </tr>
              );
            })}
            {fleet && fleet.agents.length === 0 && (
              <tr><td colSpan={4} className="py-6 text-center text-slate-500 text-sm">No device has reported yet. Install the agent above.</td></tr>
            )}
          </tbody>
        </table>
        <p className="text-xs text-slate-500 mt-3">Outdated agents keep working; reinstall with the command above to update them. Reports older than 7 days are highlighted.</p>
      </div>
    </div>
  );
}
