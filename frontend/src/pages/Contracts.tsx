import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getContracts, getContractById, createContract, updateContract, deleteContract,
  attachContractAsset, detachContractAsset, getAssets,
} from '../api';
import type { Contract } from '../types';
import { FileText, Plus, Search, X, Trash2, Pencil, Link2, RefreshCw } from 'lucide-react';
import { differenceInDays, format } from 'date-fns';
import clsx from 'clsx';
import { useAuth } from '../context/AuthContext';

const TYPES = ['lease', 'support', 'maintenance', 'subscription'] as const;

function EndDateBadge({ end, noticeDays }: { end: string | null; noticeDays: number }) {
  if (!end) return <span className="text-slate-500">—</span>;
  const days = differenceInDays(new Date(end), new Date());
  const cls = days < 0
    ? 'bg-rose-500/20 text-rose-400 ring-rose-500/30'
    : days <= noticeDays
      ? 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30'
      : 'bg-emerald-500/20 text-emerald-400 ring-emerald-500/30';
  const label = days < 0 ? `expired ${-days}d ago` : `${days}d left`;
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-300">
      {format(new Date(end), 'PP')}
      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ring-1 ring-inset ${cls}`}>{label}</span>
    </span>
  );
}

interface FormState {
  name: string; contract_type: string; vendor: string; reference_no: string;
  start_date: string; end_date: string; notice_days: string; cost: string; auto_renews: boolean;
}
const EMPTY: FormState = {
  name: '', contract_type: 'support', vendor: '', reference_no: '',
  start_date: '', end_date: '', notice_days: '30', cost: '', auto_renews: false,
};

export default function Contracts() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canEdit = user?.role === 'admin' || user?.role === 'asset_manager';

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [openId, setOpenId] = useState<number | null>(null);
  const [modal, setModal] = useState<{ mode: 'create' } | { mode: 'edit'; contract: Contract } | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState('');
  const [attachSearch, setAttachSearch] = useState('');

  const size = 25;
  const { data: res, isLoading } = useQuery({
    queryKey: ['contracts', page, search, typeFilter],
    queryFn: () => getContracts(page, size, {
      ...(search ? { search } : {}), ...(typeFilter ? { contract_type: typeFilter } : {}),
    }),
  });
  const items = res?.data?.items ?? [];
  const total = res?.data?.total ?? 0;

  const { data: detailRes } = useQuery({
    queryKey: ['contract', openId],
    queryFn: () => getContractById(openId!),
    enabled: openId !== null,
  });
  const detail = detailRes?.data;

  const { data: candidates } = useQuery({
    queryKey: ['asset-search', attachSearch],
    queryFn: () => getAssets(1, 10, attachSearch ? { search: attachSearch } : {}),
    enabled: canEdit && openId !== null,
  });

  const invalidate = () => {
    setError('');
    queryClient.invalidateQueries({ queryKey: ['contracts'] });
    if (openId !== null) queryClient.invalidateQueries({ queryKey: ['contract', openId] });
  };
  const onError = (err: unknown) => {
    const data = (err as { response?: { data?: { detail?: unknown; message?: string } } })?.response?.data;
    const detailMsg = typeof data?.detail === 'string' ? data.detail : data?.message;
    setError(detailMsg ?? 'Operation failed');
  };

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: form.name.trim(),
        contract_type: form.contract_type as Contract['contract_type'],
        vendor: form.vendor.trim() || null,
        reference_no: form.reference_no.trim() || null,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
        notice_days: Number(form.notice_days) || 30,
        cost: form.cost || null,
        auto_renews: form.auto_renews,
      };
      return modal?.mode === 'edit' ? updateContract(modal.contract.id, payload) : createContract(payload);
    },
    onSuccess: () => { setModal(null); invalidate(); },
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteContract(id),
    onSuccess: () => { setOpenId(null); invalidate(); },
    onError,
  });
  const attach = useMutation({
    mutationFn: (assetId: number) => attachContractAsset(openId!, assetId),
    onSuccess: () => { setAttachSearch(''); invalidate(); },
    onError,
  });
  const detach = useMutation({
    mutationFn: (assetId: number) => detachContractAsset(openId!, assetId),
    onSuccess: invalidate,
    onError,
  });

  const openEdit = (c: Contract) => {
    setForm({
      name: c.name, contract_type: c.contract_type, vendor: c.vendor ?? '',
      reference_no: c.reference_no ?? '', start_date: c.start_date ?? '',
      end_date: c.end_date ?? '', notice_days: String(c.notice_days),
      cost: c.cost ?? '', auto_renews: c.auto_renews,
    });
    setError('');
    setModal({ mode: 'edit', contract: c });
  };

  const input = 'w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
            <FileText className="w-8 h-8 text-indigo-400" />
            Contracts
          </h1>
          <p className="text-slate-400 mt-1">Support, lease, maintenance and subscription agreements — {total} total.</p>
        </div>
        {canEdit && (
          <button onClick={() => { setForm(EMPTY); setError(''); setModal({ mode: 'create' }); }}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors">
            <Plus className="w-4 h-4" /> New contract
          </button>
        )}
      </div>

      <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl overflow-hidden">
        <div className="p-4 border-b border-slate-700/50 flex flex-col sm:flex-row gap-3 bg-slate-800/50">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input placeholder="Search name, vendor, reference…" value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }} className={`${input} pl-9`} />
          </div>
          <select value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }} className={clsx(input, 'sm:w-44')}>
            <option value="">All types</option>
            {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-700/50 bg-slate-800/30 text-xs font-semibold text-slate-400 tracking-wider">
              <th className="px-6 py-4">Name</th>
              <th className="px-6 py-4">Type</th>
              <th className="px-6 py-4">Vendor</th>
              <th className="px-6 py-4">Ends</th>
              <th className="px-6 py-4">Cost</th>
              <th className="px-6 py-4">Assets</th>
              <th className="px-6 py-4" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {isLoading ? (
              <tr><td colSpan={7} className="px-6 py-12 text-center text-slate-500">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={7} className="px-6 py-12 text-center text-slate-500">No contracts yet.</td></tr>
            ) : items.map((c) => (
              <tr key={c.id} onClick={() => setOpenId(c.id)} className="hover:bg-slate-800/40 transition-colors cursor-pointer">
                <td className="px-6 py-4 font-medium text-slate-200">
                  {c.name}
                  {c.auto_renews && <RefreshCw className="inline w-3.5 h-3.5 ml-2 text-slate-500" aria-label="Auto-renews" />}
                </td>
                <td className="px-6 py-4 text-sm text-slate-300">{c.contract_type}</td>
                <td className="px-6 py-4 text-sm text-slate-400">{c.vendor ?? '—'}</td>
                <td className="px-6 py-4"><EndDateBadge end={c.end_date} noticeDays={c.notice_days} /></td>
                <td className="px-6 py-4 text-sm text-slate-400">{c.cost ? `${c.cost} ${c.currency}` : '—'}</td>
                <td className="px-6 py-4 text-sm text-slate-400">{c.asset_count}</td>
                <td className="px-6 py-4 text-right">
                  {canEdit && (
                    <button onClick={(e) => { e.stopPropagation(); openEdit(c); }}
                      className="p-1.5 text-slate-500 hover:text-slate-50 hover:bg-slate-700 rounded-lg transition-colors" title="Edit">
                      <Pencil className="w-4 h-4" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Detail drawer */}
      {openId !== null && detail && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={() => setOpenId(null)}>
          <div className="w-full max-w-xl bg-slate-800 border-l border-slate-700 h-full overflow-y-auto p-6"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-slate-50">{detail.name}</h2>
              <div className="flex gap-2">
                {user?.role === 'admin' && (
                  <button
                    onClick={() => { if (confirm(`Delete contract "${detail.name}"?`)) remove.mutate(detail.id); }}
                    className="p-2 text-rose-400 bg-rose-500/10 hover:bg-rose-500/20 rounded-lg transition-colors" title="Delete">
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
                <button onClick={() => setOpenId(null)} className="p-2 text-slate-400 hover:text-slate-50 rounded-lg">
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 text-sm mb-6">
              <div><p className="text-slate-500">Type</p><p className="text-slate-200">{detail.contract_type}</p></div>
              <div><p className="text-slate-500">Vendor</p><p className="text-slate-200">{detail.vendor ?? '—'}</p></div>
              <div><p className="text-slate-500">Reference</p><p className="text-slate-200">{detail.reference_no ?? '—'}</p></div>
              <div><p className="text-slate-500">Term</p><p className="text-slate-200">{detail.start_date ?? '?'} → {detail.end_date ?? '?'}</p></div>
              <div><p className="text-slate-500">Cost</p><p className="text-slate-200">{detail.cost ? `${detail.cost} ${detail.currency}` : '—'}</p></div>
              <div><p className="text-slate-500">Renewal notice</p><p className="text-slate-200">{detail.notice_days} days{detail.auto_renews ? ' · auto-renews' : ''}</p></div>
            </div>

            <h3 className="text-sm font-semibold text-slate-300 mb-2">Covered assets ({detail.assets.length})</h3>
            <ul className="space-y-1.5 mb-4">
              {detail.assets.map((a) => (
                <li key={a.id} className="flex items-center gap-2 text-sm">
                  <span className="font-mono text-xs text-indigo-300">{a.asset_tag}</span>
                  <span className="text-slate-200">{a.name}</span>
                  {canEdit && (
                    <button onClick={() => detach.mutate(a.id)}
                      className="ml-auto p-1 text-slate-600 hover:text-rose-400 rounded" title="Detach">
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </li>
              ))}
              {detail.assets.length === 0 && <li className="text-sm text-slate-500">None attached.</li>}
            </ul>

            {canEdit && (
              <div className="relative mb-6">
                <input value={attachSearch} onChange={(e) => setAttachSearch(e.target.value)}
                  placeholder="Attach asset — search by name or tag…" className={input} />
                {attachSearch && (
                  <div className="absolute z-10 mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg shadow-xl max-h-44 overflow-y-auto">
                    {(candidates?.data?.items ?? [])
                      .filter((a) => !detail.assets.some((x) => x.id === a.id))
                      .map((a) => (
                        <button key={a.id} onClick={() => attach.mutate(a.id)}
                          className="w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-slate-700/60 flex items-center gap-2">
                          <Link2 className="w-3.5 h-3.5 text-slate-500" />
                          <span className="font-mono text-xs text-indigo-300">{a.asset_tag}</span>{a.name}
                        </button>
                      ))}
                  </div>
                )}
              </div>
            )}

            <h3 className="text-sm font-semibold text-slate-300 mb-2">Entitlements under this contract</h3>
            <ul className="space-y-1.5">
              {detail.entitlements.map((e) => (
                <li key={e.id} className="text-sm text-slate-200">
                  {e.product} <span className="text-slate-500">· {e.license_model}{e.seats_purchased ? ` · ${e.seats_purchased} seats` : ''}{e.expires_on ? ` · expires ${e.expires_on}` : ''}</span>
                </li>
              ))}
              {detail.entitlements.length === 0 && <li className="text-sm text-slate-500">None.</li>}
            </ul>

            {error && <p className="text-sm text-rose-400 mt-4">{error}</p>}
          </div>
        </div>
      )}

      {/* Create / edit modal */}
      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setModal(null)}>
          <div className="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-xl max-h-[90vh] overflow-y-auto p-6"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-xl font-semibold text-slate-50">
                {modal.mode === 'edit' ? `Edit ${modal.contract.name}` : 'New contract'}
              </h2>
              <button onClick={() => setModal(null)} className="p-1.5 text-slate-400 hover:text-slate-50 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="sm:col-span-2 text-sm text-slate-400">Name *
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Type *
                <select value={form.contract_type} disabled={modal.mode === 'edit'}
                  onChange={(e) => setForm({ ...form, contract_type: e.target.value })} className={`${input} mt-1 disabled:opacity-50`}>
                  {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <label className="text-sm text-slate-400">Vendor
                <input value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Reference no.
                <input value={form.reference_no} onChange={(e) => setForm({ ...form, reference_no: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Cost
                <input type="number" step="0.01" min="0" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Start date
                <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">End date
                <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Renewal notice (days)
                <input type="number" min="0" max="365" value={form.notice_days} onChange={(e) => setForm({ ...form, notice_days: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-400 mt-6">
                <input type="checkbox" checked={form.auto_renews} onChange={(e) => setForm({ ...form, auto_renews: e.target.checked })} className="accent-indigo-500" />
                Auto-renews
              </label>
              {error && <p className="sm:col-span-2 text-sm text-rose-400">{error}</p>}
              <div className="sm:col-span-2 flex justify-end gap-3">
                <button type="button" onClick={() => setModal(null)}
                  className="px-4 py-2 text-sm text-slate-300 bg-slate-700/60 hover:bg-slate-700 rounded-lg transition-colors">Cancel</button>
                <button type="submit" disabled={save.isPending}
                  className="px-4 py-2 text-sm font-medium text-slate-50 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg transition-colors">
                  {save.isPending ? 'Saving…' : 'Save'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
