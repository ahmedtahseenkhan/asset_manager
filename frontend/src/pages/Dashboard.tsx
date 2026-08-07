import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { getDashboardSummary } from '../api';
import { Laptop, Activity, AlertCircle, RefreshCw, ShieldAlert } from 'lucide-react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts';

export default function Dashboard() {
  const navigate = useNavigate();
  const { data: res, isLoading: loading, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: getDashboardSummary,
  });

  const data = res?.data;

  if (loading && !data) return <div className="animate-pulse flex space-x-4 text-slate-400">Loading stats...</div>;
  if (!data) return <div className="text-rose-400">Failed to load stats.</div>;

  const COLORS = ['#6366f1', '#14b8a6', '#f59e0b', '#ec4899', '#8b5cf6'];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight text-white">Dashboard Overview</h1>
        <button onClick={() => refetch()} className="p-2 bg-slate-800 rounded-lg hover:bg-slate-700 transition-colors">
            <RefreshCw className="w-5 h-5 text-slate-300" />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50 flex items-center gap-4">
          <div className="p-3 bg-indigo-500/20 rounded-xl">
            <Laptop className="w-8 h-8 text-indigo-400" />
          </div>
          <div>
            <p className="text-sm font-medium text-slate-400">Total Devices</p>
            <p className="text-3xl font-bold text-white mt-1">{data.total_devices}</p>
          </div>
        </div>

        <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50 flex items-center gap-4">
          <div className="p-3 bg-emerald-500/20 rounded-xl">
            <Activity className="w-8 h-8 text-emerald-400" />
          </div>
          <div>
            <p className="text-sm font-medium text-slate-400">Active Assets</p>
            <p className="text-3xl font-bold text-white mt-1">{data.active_devices}</p>
          </div>
        </div>

        <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50 flex items-center gap-4">
          <div className="p-3 bg-rose-500/20 rounded-xl">
            <AlertCircle className="w-8 h-8 text-rose-400" />
          </div>
          <div>
            <p className="text-sm font-medium text-slate-400">Stale Devices</p>
            <p className="text-3xl font-bold text-white mt-1">{data.stale_devices}</p>
          </div>
        </div>

        <button
          onClick={() => navigate('/coverage-gaps')}
          className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-amber-500/30 hover:border-amber-400/60 flex items-center gap-4 transition-colors text-left w-full"
        >
          <div className="p-3 bg-amber-500/20 rounded-xl">
            <ShieldAlert className="w-8 h-8 text-amber-400" />
          </div>
          <div>
            <p className="text-sm font-medium text-slate-400">Coverage Gaps</p>
            <p className="text-3xl font-bold text-white mt-1">{data.coverage_gap_count ?? 0}</p>
            <p className="text-xs text-amber-400 mt-0.5">devices without full coverage →</p>
          </div>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
          <h2 className="text-lg font-medium text-white mb-6">OS Distribution</h2>
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={data.os_distribution}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {data.os_distribution.map((_entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip 
                    contentStyle={{ backgroundColor: '#1e293b', borderColor: '#334155', color: '#f8fafc' }}
                    itemStyle={{ color: '#e2e8f0' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50">
          <h2 className="text-lg font-medium text-white mb-6">Devices by Source</h2>
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={data.source_distribution} margin={{ top: 20, right: 30, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                <XAxis dataKey="name" stroke="#94a3b8" />
                <YAxis stroke="#94a3b8" />
                <Tooltip
                    contentStyle={{ backgroundColor: '#1e293b', borderColor: '#334155', color: '#f8fafc' }}
                    cursor={{fill: '#334155'}}
                />
                <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
