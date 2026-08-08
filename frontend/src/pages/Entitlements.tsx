import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getEntitlements, getEntitlementById, createEntitlement, updateEntitlement,
  deleteEntitlement, assignEntitlement, unassignEntitlement, getAssets, getContracts,
} from '../api';
import type { Entitlement } from '../types';
import { KeySquare, Plus, Search, X, Trash2, Pencil, Laptop, User as UserIcon, Eye, EyeOff } from 'lucide-react';
import clsx from 'clsx';
import { useAuth } from '../context/AuthContext';

const MODELS = ['per_seat', 'per_device', 'site', 'subscription'] as const;

function SeatsBar({ used, max }: { used: number; max: number | null }) {
  if (max === null) return <span className="text-sm text-slate-400">{used} assigned · unlimited</span>;
  const pct = max > 0 ? Math.min(100, Math.round((used / max) * 100)) : 0;
  const color = pct >= 100 ? 'bg-rose-500' : pct >= 80 ? 'bg-yellow-500' : 'bg-emerald-500';
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 bg-slate-700/50 rounded-full h-1.5 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm text-slate-400">{used}/{max}</span>
    </div>
  );
}

interface FormState {
  product: string; vendor: string; license_model: string; seats_purchased: string;
  license_key: string; contract_id: string; expires_on: string;
}
const EMPTY: FormState = {
  product: '', vendor: '', license_model: 'per_seat', seats_purchased: '',
  license_key: '', contract_id: '', expires_on: '',
};

export default function Entitlements() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canEdit = user?.role === 'admin' || user?.role === 'asset_manager';

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [openId, setOpenId] = useState<number | null>(null);
  const [modal, setModal] = useState<{ mode: 'create' } | { mode: 'edit'; ent: Entitlement } | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [assignAssetSearch, setAssignAssetSearch] = useState('');

  const size = 25;
  const { data: res, isLoading } = useQuery({
    queryKey: ['entitlements', page, search],
    queryFn: () => getEntitlements(page, size, search ? { search } : {}),
  });
  const items = res?.data?.items ?? [];
  const total = res?.data?.total ?? 0;

  const { data: detailRes } = useQuery({
    queryKey: ['entitlement', openId],
    queryFn: () => getEntitlementById(openId!),
    enabled: openId !== null,
  });
  const detail = detailRes?.data;

  const { data: assetCandidates } = useQuery({
    queryKey: ['asset-search', assignAssetSearch],
    queryFn: () => getAssets(1, 10, assignAssetSearch ? { search: assignAssetSearch } : {}),
    enabled: canEdit && openId !== null && assignAssetSearch.length > 0,
  });
  const { data: contractsRes } = useQuery({
    queryKey: ['contracts-all'],
    queryFn: () => getContracts(1, 200),
    enabled: canEdit && modal !== null,
  });

  const invalidate = () => {
    setError('');
    queryClient.invalidateQueries({ queryKey: ['entitlements'] });
    if (openId !== null) queryClient.invalidateQueries({ queryKey: ['entitlement', openId] });
  };
  const onError = (err: unknown) => {
    const data = (err as { response?: { data?: { detail?: unknown; message?: string } } })?.response?.data;
    const detailMsg = typeof data?.detail === 'string' ? data.detail : data?.message;
    setError(detailMsg ?? 'Operation failed');
  };

  const save = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        product: form.product.trim(),
        vendor: form.vendor.trim() || null,
        license_model: form.license_model,
        seats_purchased: form.seats_purchased ? Number(form.seats_purchased) : null,
        contract_id: form.contract_id ? Number(form.contract_id) : null,
        expires_on: form.expires_on || null,
      };
      if (form.license_key.trim()) payload.license_key = form.license_key.trim();
      return modal?.mode === 'edit' ? updateEntitlement(modal.ent.id, payload) : createEntitlement(payload);
    },
    onSuccess: () => { setModal(null); invalidate(); },
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteEntitlement(id),
    onSuccess: () => { setOpenId(null); invalidate(); },
    onError,
  });
  const assign = useMutation({
    mutationFn: (target: { asset_id?: number; user_id?: number }) => assignEntitlement(openId!, target),
    onSuccess: () => { setAssignAssetSearch(''); invalidate(); },
    onError,
  });
  const unassign = useMutation({
    mutationFn: (assignmentId: number) => unassignEntitlement(openId!, assignmentId),
    onSuccess: invalidate,
    onError,
  });

  const openEdit = (e: Entitlement) => {
    setForm({
      product: e.product, vendor: e.vendor ?? '', license_model: e.license_model,
      seats_purchased: e.seats_purchased ? String(e.seats_purchased) : '',
      license_key: '', contract_id: e.contract_id ? String(e.contract_id) : '',
      expires_on: e.expires_on ?? '',
    });
    setError('');
    setModal({ mode: 'edit', ent: e });
  };

  const input = 'w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
            <KeySquare className="w-8 h-8 text-indigo-400" />
            Software Entitlements
          </h1>
          <p className="text-slate-400 mt-1">Licenses your organisation owns, with seat tracking — {total} total.</p>
        </div>
        {canEdit && (
          <button onClick={() => { setForm(EMPTY); setError(''); setModal({ mode: 'create' }); }}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors">
            <Plus className="w-4 h-4" /> New entitlement
          </button>
        )}
      </div>

      <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl overflow-hidden">
        <div className="p-4 border-b border-slate-700/50 bg-slate-800/50">
          <div className="relative max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input placeholder="Search product or vendor…" value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }} className={`${input} pl-9`} />
          </div>
        </div>
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-700/50 bg-slate-800/30 text-xs font-semibold text-slate-400 tracking-wider">
              <th className="px-6 py-4">Product</th>
              <th className="px-6 py-4">Model</th>
              <th className="px-6 py-4">Seats</th>
              <th className="px-6 py-4">Key</th>
              <th className="px-6 py-4">Contract</th>
              <th className="px-6 py-4">Expires</th>
              <th className="px-6 py-4" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {isLoading ? (
              <tr><td colSpan={7} className="px-6 py-12 text-center text-slate-500">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={7} className="px-6 py-12 text-center text-slate-500">No entitlements yet.</td></tr>
            ) : items.map((e) => (
              <tr key={e.id} onClick={() => { setOpenId(e.id); setShowKey(false); }} className="hover:bg-slate-800/40 transition-colors cursor-pointer">
                <td className="px-6 py-4">
                  <p className="font-medium text-slate-200">{e.product}</p>
                  <p className="text-xs text-slate-500">{e.vendor ?? ''}</p>
                </td>
                <td className="px-6 py-4 text-sm text-slate-300">{e.license_model.replace('_', ' ')}</td>
                <td className="px-6 py-4"><SeatsBar used={e.seats_used} max={e.seats_purchased} /></td>
                <td className="px-6 py-4 font-mono text-xs text-slate-400">{e.has_key ? e.key_hint : '—'}</td>
                <td className="px-6 py-4 text-sm text-slate-400">{e.contract_name ?? '—'}</td>
                <td className="px-6 py-4 text-sm text-slate-400">{e.expires_on ?? '—'}</td>
                <td className="px-6 py-4 text-right">
                  {canEdit && (
                    <button onClick={(ev) => { ev.stopPropagation(); openEdit(e); }}
                      className="p-1.5 text-slate-500 hover:text-white hover:bg-slate-700 rounded-lg transition-colors" title="Edit">
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
              <div>
                <h2 className="text-xl font-semibold text-white">{detail.product}</h2>
                <p className="text-sm text-slate-500">{detail.vendor ?? ''} · {detail.license_model.replace('_', ' ')}</p>
              </div>
              <div className="flex gap-2">
                {user?.role === 'admin' && (
                  <button onClick={() => { if (confirm(`Delete entitlement "${detail.product}"?`)) remove.mutate(detail.id); }}
                    className="p-2 text-rose-400 bg-rose-500/10 hover:bg-rose-500/20 rounded-lg transition-colors" title="Delete">
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
                <button onClick={() => setOpenId(null)} className="p-2 text-slate-400 hover:text-white rounded-lg">
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            <div className="mb-5"><SeatsBar used={detail.seats_used} max={detail.seats_purchased} /></div>

            {detail.has_key && (
              <div className="mb-6 p-3 bg-slate-900/50 border border-slate-700 rounded-lg flex items-center gap-3">
                <span className="font-mono text-sm text-slate-200 flex-1 break-all">
                  {user?.role === 'admin' && showKey ? detail.license_key : detail.key_hint}
                </span>
                {user?.role === 'admin' && (
                  <button onClick={() => setShowKey((s) => !s)}
                    className="p-1.5 text-slate-400 hover:text-white rounded" title={showKey ? 'Hide key' : 'Reveal key'}>
                    {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                )}
              </div>
            )}

            <h3 className="text-sm font-semibold text-slate-300 mb-2">Assignments ({detail.assignments.length})</h3>
            <ul className="space-y-1.5 mb-4">
              {detail.assignments.map((a) => (
                <li key={a.id} className="flex items-center gap-2 text-sm">
                  {a.asset_id ? <Laptop className="w-3.5 h-3.5 text-slate-500" /> : <UserIcon className="w-3.5 h-3.5 text-slate-500" />}
                  <span className="text-slate-200">
                    {a.asset_id ? `${a.asset_tag} — ${a.asset_name}` : a.username}
                  </span>
                  {canEdit && (
                    <button onClick={() => unassign.mutate(a.id)}
                      className="ml-auto p-1 text-slate-600 hover:text-rose-400 rounded" title="Unassign">
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </li>
              ))}
              {detail.assignments.length === 0 && <li className="text-sm text-slate-500">No seats assigned.</li>}
            </ul>

            {canEdit && (
              <div className="relative">
                <input value={assignAssetSearch} onChange={(e) => setAssignAssetSearch(e.target.value)}
                  placeholder="Assign to asset — search by name or tag…" className={input} />
                {assignAssetSearch && (
                  <div className="absolute z-10 mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg shadow-xl max-h-44 overflow-y-auto">
                    {(assetCandidates?.data?.items ?? [])
                      .filter((a) => !detail.assignments.some((x) => x.asset_id === a.id))
                      .map((a) => (
                        <button key={a.id} onClick={() => assign.mutate({ asset_id: a.id })}
                          className="w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-slate-700/60">
                          <span className="font-mono text-xs text-indigo-300 mr-2">{a.asset_tag}</span>{a.name}
                        </button>
                      ))}
                  </div>
                )}
              </div>
            )}
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
              <h2 className="text-xl font-semibold text-white">
                {modal.mode === 'edit' ? `Edit ${modal.ent.product}` : 'New entitlement'}
              </h2>
              <button onClick={() => setModal(null)} className="p-1.5 text-slate-400 hover:text-white rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="sm:col-span-2 text-sm text-slate-400">Product *
                <input required value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Vendor
                <input value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">License model *
                <select value={form.license_model} disabled={modal.mode === 'edit'}
                  onChange={(e) => setForm({ ...form, license_model: e.target.value })} className={`${input} mt-1 disabled:opacity-50`}>
                  {MODELS.map((m) => <option key={m} value={m}>{m.replace('_', ' ')}</option>)}
                </select>
              </label>
              <label className="text-sm text-slate-400">Seats purchased
                <input type="number" min="1" value={form.seats_purchased}
                  onChange={(e) => setForm({ ...form, seats_purchased: e.target.value })}
                  placeholder="blank = unlimited" className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Expires on
                <input type="date" value={form.expires_on} onChange={(e) => setForm({ ...form, expires_on: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Contract
                <select value={form.contract_id} onChange={(e) => setForm({ ...form, contract_id: e.target.value })} className={`${input} mt-1`}>
                  <option value="">None</option>
                  {(contractsRes?.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>
              <label className="text-sm text-slate-400">License key {modal.mode === 'edit' && <span className="text-slate-600">(blank = keep current)</span>}
                <input value={form.license_key} onChange={(e) => setForm({ ...form, license_key: e.target.value })}
                  placeholder="stored encrypted" className={clsx(input, 'mt-1 font-mono')} />
              </label>
              {error && <p className="sm:col-span-2 text-sm text-rose-400">{error}</p>}
              <div className="sm:col-span-2 flex justify-end gap-3">
                <button type="button" onClick={() => setModal(null)}
                  className="px-4 py-2 text-sm text-slate-300 bg-slate-700/60 hover:bg-slate-700 rounded-lg transition-colors">Cancel</button>
                <button type="submit" disabled={save.isPending}
                  className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg transition-colors">
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
