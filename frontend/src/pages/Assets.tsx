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

  const hasFilters = search || category || state;
  const rangeFrom = total === 0 ? 0 : (page - 1) * size + 1;
  const rangeTo = Math.min(page * size, total);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Assets</h1>
          <p className="text-sm text-slate-500 mt-1">Managed inventory — <span className="tabular-nums">{total}</span> record{total !== 1 ? 's' : ''}.</p>
        </div>
        <div className="flex gap-2.5">
          <button
            onClick={() => navigate('/assets/reconcile')}
            className="inline-flex items-center gap-2 px-3.5 py-2 bg-slate-800/70 hover:border-slate-600 text-slate-200 text-sm font-medium rounded-lg border border-slate-700/60 transition-colors"
          >
            <GitMerge className="w-4 h-4 text-slate-400" />
            Reconcile
            {unlinkedCount > 0 && <span className="ml-0.5 px-1.5 py-0.5 text-[10px] font-bold rounded-md bg-amber-500/20 text-amber-400 tabular-nums">{unlinkedCount}</span>}
          </button>
          {canEdit && (
            <button
              onClick={() => navigate('/assets/new')}
              className="inline-flex items-center gap-2 px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors shadow-glow"
            >
              <Plus className="w-4 h-4" /> New asset
            </button>
          )}
        </div>
      </div>

      <div className="bg-slate-800/70 backdrop-blur-sm border border-slate-700/60 rounded-xl overflow-hidden">
        <div className="p-3 border-b border-slate-700/60 flex flex-col sm:flex-row gap-2.5">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search name, tag, serial, vendor…"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              className={`${input} pl-9`}
            />
          </div>
          <select value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }} className={clsx(input, 'sm:w-40')}>
            <option value="">All categories</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={state} onChange={(e) => { setState(e.target.value); setPage(1); }} className={clsx(input, 'sm:w-40')}>
            <option value="">All states</option>
            {STATES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
          </select>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-700/60 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <th className="px-5 py-3 font-semibold">Asset</th>
                <th className="px-5 py-3 font-semibold">IP</th>
                <th className="px-5 py-3 font-semibold">OS</th>
                <th className="px-5 py-3 font-semibold">Criticality</th>
                <th className="px-5 py-3 font-semibold">Log Source</th>
                <th className="px-5 py-3 font-semibold">State</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {isLoading ? (
                [...Array(6)].map((_, i) => (
                  <tr key={i}><td colSpan={7} className="px-5 py-3.5">
                    <div className="h-5 bg-slate-800/70 rounded animate-pulse" style={{ width: `${70 - i * 6}%` }} />
                  </td></tr>
                ))
              ) : items.length === 0 ? (
                <tr><td colSpan={7} className="px-5 py-16 text-center">
                  <Boxes className="w-9 h-9 text-slate-700 mx-auto mb-3" />
                  <p className="text-sm text-slate-400">{hasFilters ? 'No assets match your filters.' : 'No assets yet.'}</p>
                  {!hasFilters && canEdit && <p className="text-xs text-slate-600 mt-1">Create one, or adopt discovered devices via Reconcile.</p>}
                </td></tr>
              ) : items.map((a) => (
                <tr
                  key={a.id}
                  onClick={() => navigate(`/assets/${a.id}`)}
                  className="group hover:bg-slate-800/50 transition-colors cursor-pointer"
                >
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <span className="w-8 h-8 rounded-lg bg-slate-800 ring-1 ring-slate-700 grid place-items-center text-[11px] font-semibold text-slate-300 shrink-0 uppercase">
                        {(a.name || '?').slice(0, 2)}
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-200 truncate group-hover:text-white transition-colors">{a.name}</p>
                        <p className="font-mono text-[11px] text-indigo-400/80">{a.asset_tag}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-3 text-sm text-slate-400 font-mono">{a.ip_address ?? <span className="text-slate-600">—</span>}</td>
                  <td className="px-5 py-3 text-sm text-slate-400">{a.os_name ?? <span className="text-slate-600">—</span>}</td>
                  <td className="px-5 py-3">
                    {a.criticality
                      ? <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold uppercase ring-1 ring-inset ${ENUM_BADGE.criticality[a.criticality]}`}>{a.criticality}</span>
                      : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-5 py-3">
                    {a.log_source_status
                      ? <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold uppercase ring-1 ring-inset ${ENUM_BADGE.log_source_status[a.log_source_status]}`}>{a.log_source_status.replace(/_/g, ' ')}</span>
                      : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-5 py-3"><StateBadge state={a.lifecycle_state} /></td>
                  <td className="px-5 py-3 text-right">
                    {canEdit && (
                      <button
                        onClick={(e) => { e.stopPropagation(); navigate(`/assets/${a.id}/edit`); }}
                        className="p-1.5 text-slate-600 hover:text-white hover:bg-slate-700 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
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

        <div className="px-5 py-3 border-t border-slate-700/60 flex items-center justify-between text-xs text-slate-500">
          <span className="tabular-nums">{rangeFrom}–{rangeTo} of {total}</span>
          {pages > 1 && (
            <div className="flex items-center gap-1">
              <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
                className="p-1.5 rounded-lg text-slate-400 disabled:opacity-30 hover:bg-slate-800 disabled:hover:bg-transparent transition-colors">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="px-2 tabular-nums">{page} / {pages}</span>
              <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)}
                className="p-1.5 rounded-lg text-slate-400 disabled:opacity-30 hover:bg-slate-800 disabled:hover:bg-transparent transition-colors">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
