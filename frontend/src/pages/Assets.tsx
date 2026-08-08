import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getAssets, getUnlinkedDevices } from '../api';
import { Boxes, Plus, Search, ChevronLeft, ChevronRight, Pencil, GitMerge } from 'lucide-react';
import clsx from 'clsx';
import { useAuth } from '../context/AuthContext';
import { ENUM_BADGE } from '../lib/assetSchema';

const CATEGORIES = ['hardware', 'software', 'cloud', 'peripheral'] as const;
const STATES = ['requested', 'ordered', 'in_stock', 'deployed', 'maintenance', 'retired'] as const;

export const STATE_STYLES: Record<string, string> = {
  requested:   'bg-slate-500/20 text-slate-300 ring-slate-500/30',
  ordered:     'bg-blue-500/20 text-blue-400 ring-blue-500/30',
  in_stock:    'bg-cyan-500/20 text-cyan-400 ring-cyan-500/30',
  deployed:    'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30',
  maintenance: 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
  retired:     'bg-rose-500/20 text-rose-400 ring-rose-500/30',
};

export function StateBadge({ state }: { state: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset ${STATE_STYLES[state] ?? STATE_STYLES.requested}`}>
      {state.replace('_', ' ')}
    </span>
  );
}

export default function Assets() {
  const navigate = useNavigate();
  const { user } = useAuth();
  useQueryClient();
  const canEdit = user?.role === 'admin' || user?.role === 'asset_manager';

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [state, setState] = useState('');

  const size = 25;
  const { data: res, isLoading } = useQuery({
    queryKey: ['assets', page, search, category, state],
    queryFn: () => getAssets(page, size, {
      ...(search ? { search } : {}),
      ...(category ? { category } : {}),
      ...(state ? { lifecycle_state: state } : {}),
    }),
  });
  const items = res?.data?.items ?? [];
  const total = res?.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / size));

  const { data: unlinkedRes } = useQuery({
    queryKey: ['unlinked-devices'],
    queryFn: getUnlinkedDevices,
    staleTime: 60 * 1000,
  });
  const unlinkedCount = unlinkedRes?.data?.length ?? 0;

  const input = 'w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
            <Boxes className="w-8 h-8 text-indigo-400" />
            Assets
          </h1>
          <p className="text-slate-400 mt-1">Managed IT asset inventory — {total} record{total !== 1 ? 's' : ''}.</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => navigate('/assets/reconcile')}
            className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium rounded-lg border border-slate-700 transition-colors"
          >
            <GitMerge className="w-4 h-4" />
            Reconcile{unlinkedCount > 0 ? ` (${unlinkedCount})` : ''}
          </button>
          {canEdit && (
            <button
              onClick={() => navigate('/assets/new')}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
            >
              <Plus className="w-4 h-4" /> New asset
            </button>
          )}
        </div>
      </div>

      <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl overflow-hidden">
        <div className="p-4 border-b border-slate-700/50 flex flex-col sm:flex-row gap-3 bg-slate-800/50">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search name, tag, serial, vendor…"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              className={`${input} pl-9`}
            />
          </div>
          <select value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }} className={clsx(input, 'sm:w-44')}>
            <option value="">All categories</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={state} onChange={(e) => { setState(e.target.value); setPage(1); }} className={clsx(input, 'sm:w-44')}>
            <option value="">All states</option>
            {STATES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
          </select>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-800/30 text-xs font-semibold text-slate-400 tracking-wider">
                <th className="px-6 py-4">Tag</th>
                <th className="px-6 py-4">Name</th>
                <th className="px-6 py-4">IP</th>
                <th className="px-6 py-4">OS</th>
                <th className="px-6 py-4">Criticality</th>
                <th className="px-6 py-4">Log Source</th>
                <th className="px-6 py-4">State</th>
                <th className="px-6 py-4" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {isLoading ? (
                <tr><td colSpan={8} className="px-6 py-12 text-center text-slate-500">Loading…</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={8} className="px-6 py-12 text-center text-slate-500">No assets yet.</td></tr>
              ) : items.map((a) => (
                <tr
                  key={a.id}
                  onClick={() => navigate(`/assets/${a.id}`)}
                  className="hover:bg-slate-800/40 transition-colors cursor-pointer"
                >
                  <td className="px-6 py-4 font-mono text-xs text-indigo-300">{a.asset_tag}</td>
                  <td className="px-6 py-4 font-medium text-slate-200">{a.name}</td>
                  <td className="px-6 py-4 text-sm text-slate-400 font-mono">{a.ip_address ?? '—'}</td>
                  <td className="px-6 py-4 text-sm text-slate-400">{a.os_name ?? '—'}</td>
                  <td className="px-6 py-4">
                    {a.criticality
                      ? <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset ${ENUM_BADGE.criticality[a.criticality]}`}>{a.criticality}</span>
                      : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-6 py-4">
                    {a.log_source_status
                      ? <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset ${ENUM_BADGE.log_source_status[a.log_source_status]}`}>{a.log_source_status.replace(/_/g, ' ')}</span>
                      : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-6 py-4"><StateBadge state={a.lifecycle_state} /></td>
                  <td className="px-6 py-4 text-right">
                    {canEdit && (
                      <button
                        onClick={(e) => { e.stopPropagation(); navigate(`/assets/${a.id}/edit`); }}
                        className="p-1.5 text-slate-500 hover:text-white hover:bg-slate-700 rounded-lg transition-colors"
                        title="Edit"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {pages > 1 && (
          <div className="p-4 border-t border-slate-700/50 flex items-center justify-between text-sm text-slate-400">
            <span>Page {page} of {pages}</span>
            <div className="flex gap-2">
              <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
                className="p-2 bg-slate-700/50 rounded-lg disabled:opacity-40 hover:bg-slate-700">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)}
                className="p-2 bg-slate-700/50 rounded-lg disabled:opacity-40 hover:bg-slate-700">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
