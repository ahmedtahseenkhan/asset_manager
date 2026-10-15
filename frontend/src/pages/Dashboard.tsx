import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { getDashboardSummary, getEndpointHealth, getRecentChanges } from '../api';
import { Laptop, Activity, MoonStar, RefreshCw, ShieldAlert, ArrowUpRight, HeartPulse, Radar } from 'lucide-react';
import { formatDistanceToNowStrict } from 'date-fns';
import { describeChange } from '../lib/changes';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts';

const CHART_COLORS = ['#16a34a', '#0ea5e9', '#f59e0b', '#ec4899', '#8b5cf6'];

const TOOLTIP = {
  contentStyle: {
    backgroundColor: '#ffffff', border: '1px solid #e6e9ef', borderRadius: '10px',
    color: '#0f1419', fontSize: '12px', boxShadow: '0 8px 24px -10px rgba(16,24,40,0.18)',
  },
  itemStyle: { color: '#414b58' },
  labelStyle: { color: '#67717f' },
};

function Stat({ label, value, icon: Icon, tint, hint, onClick }: {
  label: string; value: number; icon: typeof Laptop; tint: string; hint?: string; onClick?: () => void;
}) {
  const Cmp = onClick ? 'button' : 'div';
  return (
    <Cmp
      onClick={onClick}
      className={`group text-left w-full bg-slate-800/70 backdrop-blur-sm p-5 rounded-xl border border-slate-700/60 transition-all duration-200 ${
        onClick ? 'hover:border-slate-600 hover:-translate-y-0.5' : ''}`}
    >
      <div className="flex items-center justify-between mb-4">
        <span className={`w-9 h-9 rounded-lg grid place-items-center ${tint}`}><Icon className="w-[18px] h-[18px]" /></span>
        {onClick && <ArrowUpRight className="w-4 h-4 text-slate-600 group-hover:text-slate-300 transition-colors" />}
      </div>
      <p className="text-3xl font-semibold text-slate-50 tracking-tight tabular-nums">{value.toLocaleString()}</p>
      <p className="text-sm text-slate-400 mt-1">{label}</p>
      {hint && <p className="text-xs text-slate-500 mt-0.5">{hint}</p>}
    </Cmp>
  );
}

const HEALTH_ORDER = ['no_antivirus', 'firewall_off', 'not_encrypted', 'admin_sprawl', 'pending_reboot', 'stale_inventory'];

function EndpointHealthPanel() {
  const navigate = useNavigate();
  const { data: healthRes } = useQuery({ queryKey: ['endpoint-health'], queryFn: getEndpointHealth });
  const { data: changesRes } = useQuery({
    queryKey: ['recent-warnings'], queryFn: () => getRecentChanges({ severity: 'warning', days: 7, limit: 8 }),
  });
  const health = healthRes?.data;
  if (!health) return null;

  if (health.inventoried === 0) {
    return (
      <div className="bg-slate-800/70 backdrop-blur-sm p-6 rounded-xl border border-slate-700/60 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="w-9 h-9 rounded-lg grid place-items-center bg-indigo-500/15 text-indigo-400"><HeartPulse className="w-[18px] h-[18px]" /></span>
          <div>
            <p className="text-sm font-semibold text-slate-200">Endpoint health</p>
            <p className="text-sm text-slate-500">Install the agent on your computers to see antivirus, firewall, encryption and local-admin status here.</p>
          </div>
        </div>
        <Link to="/agents" className="inline-flex items-center gap-2 px-3 py-2 text-sm text-slate-200 bg-slate-700/60 rounded-lg hover:bg-slate-700 shrink-0">
          <Radar className="w-4 h-4" /> Deploy agents
        </Link>
      </div>
    );
  }

  const warnings = changesRes?.data ?? [];
  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
      <div className="lg:col-span-3 bg-slate-800/70 backdrop-blur-sm p-6 rounded-xl border border-slate-700/60">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2"><HeartPulse className="w-4 h-4" /> Endpoint health</h2>
          <span className="text-xs text-slate-500">{health.inventoried} device{health.inventoried === 1 ? '' : 's'} with inventory</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {HEALTH_ORDER.map((key) => {
            const n = health.counts[key] ?? 0;
            return (
              <button key={key} onClick={() => navigate(`/devices?health=${key}`)}
                className={`group text-left p-4 rounded-lg border transition-colors ${n > 0
                  ? 'border-rose-500/30 bg-rose-500/10 hover:border-rose-500/50'
                  : 'border-slate-700/60 bg-slate-900/30 hover:border-slate-600'}`}>
                <p className={`text-2xl font-semibold tabular-nums ${n > 0 ? 'text-rose-400' : 'text-slate-300'}`}>{n}</p>
                <p className="text-xs text-slate-400 mt-1">{health.labels[key]}</p>
              </button>
            );
          })}
        </div>
      </div>

      <div className="lg:col-span-2 bg-slate-800/70 backdrop-blur-sm p-6 rounded-xl border border-slate-700/60">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2"><ShieldAlert className="w-4 h-4" /> Risky changes</h2>
          <span className="text-xs text-slate-500">last 7 days · {health.warnings_7d}</span>
        </div>
        {warnings.length === 0 ? (
          <p className="text-sm text-slate-500">No new local admins, and no antivirus, firewall or encryption turned off.</p>
        ) : (
          <ul className="space-y-2">
            {warnings.map((c) => (
              <li key={c.id} className="text-sm">
                <Link to={`/devices/${c.device_id}`} className="font-medium text-slate-200 hover:text-indigo-400">{c.hostname || `#${c.device_id}`}</Link>
                <span className="text-slate-400"> — {describeChange(c)}</span>
                <span className="block text-xs text-slate-500">{formatDistanceToNowStrict(new Date(c.detected_at))} ago</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: res, isLoading: loading, refetch, isFetching } = useQuery({
    queryKey: ['dashboard'], queryFn: getDashboardSummary,
  });
  const data = res?.data;

  if (loading && !data) return <div className="text-slate-400">Loading…</div>;
  if (!data) return <div className="text-rose-400">Failed to load stats.</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-50">Overview</h1>
          <p className="text-sm text-slate-500 mt-1">Unified state of the estate across all connectors.</p>
        </div>
        <button onClick={() => refetch()}
          className="inline-flex items-center gap-2 px-3 py-2 text-sm text-slate-300 bg-slate-800/70 border border-slate-700/60 rounded-lg hover:border-slate-600 hover:text-slate-50 transition-colors">
          <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Stat label="Total devices" value={data.total_devices} icon={Laptop} tint="bg-indigo-500/15 text-indigo-400" />
        <Stat label="Active" value={data.active_devices} icon={Activity} tint="bg-emerald-500/15 text-emerald-400" />
        <Stat label="Stale" value={data.stale_devices} icon={MoonStar} tint="bg-slate-500/15 text-slate-400" />
        <Stat label="Coverage gaps" value={data.coverage_gap_count ?? 0} icon={ShieldAlert}
          tint="bg-amber-500/15 text-amber-400" hint="without full coverage" onClick={() => navigate('/coverage-gaps')} />
      </div>

      <EndpointHealthPanel />

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* OS distribution */}
        <div className="lg:col-span-2 bg-slate-800/70 backdrop-blur-sm p-6 rounded-xl border border-slate-700/60">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-slate-200">OS Distribution</h2>
            <span className="text-xs text-slate-500">{data.total_devices} devices</span>
          </div>
          <div className="h-[280px]">
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie data={data.os_distribution} cx="50%" cy="50%" innerRadius={62} outerRadius={100}
                  paddingAngle={3} dataKey="value" stroke="none">
                  {data.os_distribution.map((_e, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Pie>
                <Tooltip {...TOOLTIP} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-2">
            {data.os_distribution.map((e, i) => (
              <div key={e.name} className="flex items-center gap-1.5 text-xs text-slate-400">
                <span className="w-2 h-2 rounded-sm" style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />
                {e.name} <span className="text-slate-500 tabular-nums">{e.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Devices by source */}
        <div className="lg:col-span-3 bg-slate-800/70 backdrop-blur-sm p-6 rounded-xl border border-slate-700/60">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-slate-200">Devices by Source</h2>
            <span className="text-xs text-slate-500">{data.source_distribution.length} connectors</span>
          </div>
          <div className="h-[280px]">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={data.source_distribution} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e6e9ef" vertical={false} />
                <XAxis dataKey="name" stroke="#8b95a3" tick={{ fontSize: 12 }} tickLine={false} axisLine={{ stroke: '#e6e9ef' }} />
                <YAxis stroke="#8b95a3" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip {...TOOLTIP} cursor={{ fill: 'rgba(34,197,94,0.08)' }} />
                <Bar dataKey="value" fill="#22c55e" radius={[5, 5, 0, 0]} maxBarSize={56} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
