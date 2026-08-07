import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getAdminUsers, setUserStatus, getAuditLogs, runRetention } from '../api';
import { Users, ScrollText, Shield, CheckCircle2, XCircle, ChevronLeft, ChevronRight, Trash2, Play } from 'lucide-react';
import { format } from 'date-fns';

type Tab = 'users' | 'audit';

const ACTION_COLORS: Record<string, string> = {
  'auth.login':           'text-emerald-400',
  'auth.login_failed':    'text-rose-400',
  'connector.config_saved':    'text-blue-400',
  'connector.sync_triggered':  'text-indigo-400',
};

function ActionBadge({ action }: { action: string }) {
  const color = ACTION_COLORS[action] ?? 'text-slate-400';
  return <span className={`font-mono text-xs ${color}`}>{action}</span>;
}

function UsersTab() {
  const queryClient = useQueryClient();
  const { data: res, isLoading } = useQuery({ queryKey: ['admin-users'], queryFn: getAdminUsers });
  const users = res?.data ?? [];

  const toggleMutation = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) => setUserStatus(id, active),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-users'] }),
  });

  if (isLoading) return <div className="text-slate-400 py-12 text-center">Loading users…</div>;

  return (
    <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl overflow-hidden">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-slate-700/50 bg-slate-800/30">
            {['Username', 'Email', 'Role', 'Status', 'Created', ''].map((h) => (
              <th key={h} className="px-6 py-4 text-xs font-semibold text-slate-400 tracking-wider">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {users.map((u: any) => (
            <tr key={u.id} className="hover:bg-slate-800/40 transition-colors">
              <td className="px-6 py-4 font-medium text-slate-200">{u.username}</td>
              <td className="px-6 py-4 text-sm text-slate-400">{u.email}</td>
              <td className="px-6 py-4">
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ring-1 ring-inset ${
                  u.role === 'admin'
                    ? 'bg-indigo-500/10 text-indigo-400 ring-indigo-500/20'
                    : 'bg-slate-500/10 text-slate-400 ring-slate-500/20'
                }`}>{u.role}</span>
              </td>
              <td className="px-6 py-4">
                {u.is_active ? (
                  <span className="flex items-center gap-1 text-emerald-400 text-xs font-medium">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Active
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-slate-500 text-xs font-medium">
                    <XCircle className="w-3.5 h-3.5" /> Inactive
                  </span>
                )}
              </td>
              <td className="px-6 py-4 text-sm text-slate-400">
                {u.created_at ? format(new Date(u.created_at), 'MMM d, yyyy') : '—'}
              </td>
              <td className="px-6 py-4">
                <button
                  onClick={() => toggleMutation.mutate({ id: u.id, active: !u.is_active })}
                  disabled={toggleMutation.isPending}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                    u.is_active
                      ? 'bg-rose-500/10 text-rose-400 hover:bg-rose-500/20'
                      : 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'
                  }`}
                >
                  {u.is_active ? 'Deactivate' : 'Activate'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AuditTab() {
  const [page, setPage] = useState(1);
  const [filterAction, setFilterAction] = useState('');
  const [filterUser, setFilterUser]  = useState('');

  const { data: res, isLoading } = useQuery({
    queryKey: ['audit-logs', page, filterAction, filterUser],
    queryFn: () => getAuditLogs(page, 50, { action: filterAction || undefined, username: filterUser || undefined }),
  });

  const logs   = res?.data?.items ?? [];
  const total  = res?.data?.total ?? 0;
  const totalPages = Math.ceil(total / 50);

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Filter by action…"
          value={filterAction}
          onChange={(e) => { setFilterAction(e.target.value); setPage(1); }}
          className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 w-52"
        />
        <input
          type="text"
          placeholder="Filter by username…"
          value={filterUser}
          onChange={(e) => { setFilterUser(e.target.value); setPage(1); }}
          className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 w-52"
        />
        <span className="self-center text-sm text-slate-500">{total} entries</span>
      </div>

      <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl overflow-hidden">
        {isLoading ? (
          <div className="py-12 text-center text-slate-400">Loading…</div>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-800/30">
                {['Time', 'User', 'Action', 'Resource', 'IP'].map((h) => (
                  <th key={h} className="px-6 py-4 text-xs font-semibold text-slate-400 tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {logs.length === 0 ? (
                <tr><td colSpan={5} className="px-6 py-12 text-center text-slate-500">No audit entries found.</td></tr>
              ) : logs.map((e: any) => (
                <tr key={e.id} className="hover:bg-slate-800/40 transition-colors">
                  <td className="px-6 py-3 text-xs text-slate-400 whitespace-nowrap">
                    {e.created_at ? format(new Date(e.created_at), 'MMM d HH:mm:ss') : '—'}
                  </td>
                  <td className="px-6 py-3 text-sm text-slate-300">{e.username ?? <span className="text-slate-600">—</span>}</td>
                  <td className="px-6 py-3"><ActionBadge action={e.action} /></td>
                  <td className="px-6 py-3 text-xs text-slate-400">
                    {e.resource_type && <span className="text-slate-500">{e.resource_type}/</span>}
                    {e.resource_id}
                  </td>
                  <td className="px-6 py-3 text-xs text-slate-500 font-mono">{e.ip_address ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {totalPages > 1 && (
          <div className="px-6 py-4 border-t border-slate-700/50 flex items-center justify-between bg-slate-800/30">
            <span className="text-sm text-slate-400">Page {page} of {totalPages}</span>
            <div className="flex gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}
                className="p-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 border border-slate-700 rounded-lg transition-colors text-slate-300">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
                className="p-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 border border-slate-700 rounded-lg transition-colors text-slate-300">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Admin() {
  const [tab, setTab] = useState<Tab>('users');
  const queryClient = useQueryClient();

  const retentionMutation = useMutation({
    mutationFn: runRetention,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      alert(`Retention complete — retired: ${res.data.retired}, purged: ${res.data.purged}`);
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
            <Shield className="w-8 h-8 text-indigo-400" />
            Administration
          </h1>
          <p className="text-slate-400 mt-1">User management, audit trail, and data retention.</p>
        </div>
        <button
          onClick={() => retentionMutation.mutate()}
          disabled={retentionMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 rounded-lg transition-colors text-sm disabled:opacity-60"
        >
          <Trash2 className="w-4 h-4" />
          {retentionMutation.isPending ? 'Running…' : 'Run Retention Now'}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-700/50">
        {([
          { key: 'users', label: 'Users', icon: Users },
          { key: 'audit', label: 'Audit Log', icon: ScrollText },
        ] as { key: Tab; label: string; icon: any }[]).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 transition-colors -mb-px ${
              tab === key
                ? 'border-indigo-500 text-indigo-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === 'users' && <UsersTab />}
      {tab === 'audit' && <AuditTab />}
    </div>
  );
}
