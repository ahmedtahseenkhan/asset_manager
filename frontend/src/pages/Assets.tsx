import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getAssets, createAsset, updateAsset } from '../api';
import type { Asset } from '../types';
import { Boxes, Plus, Search, ChevronLeft, ChevronRight, Pencil, X } from 'lucide-react';
import clsx from 'clsx';
import { useAuth } from '../context/AuthContext';

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

interface FormState {
  name: string;
  category: string;
  asset_type: string;
  serial_number: string;
  vendor: string;
  model: string;
  location: string;
  department: string;
  purchase_date: string;
  purchase_cost: string;
  warranty_end: string;
  notes: string;
}

const EMPTY_FORM: FormState = {
  name: '', category: 'hardware', asset_type: '', serial_number: '', vendor: '',
  model: '', location: '', department: '', purchase_date: '', purchase_cost: '',
  warranty_end: '', notes: '',
};

function toPayload(form: FormState): Partial<Asset> {
  const val = (s: string) => (s.trim() === '' ? null : s.trim());
  return {
    name: form.name.trim(),
    category: form.category as Asset['category'],
    asset_type: val(form.asset_type),
    serial_number: val(form.serial_number),
    vendor: val(form.vendor),
    model: val(form.model),
    location: val(form.location),
    department: val(form.department),
    purchase_date: val(form.purchase_date),
    purchase_cost: val(form.purchase_cost),
    warranty_end: val(form.warranty_end),
    notes: val(form.notes),
  };
}

export default function Assets() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canEdit = user?.role === 'admin' || user?.role === 'asset_manager';

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [state, setState] = useState('');
  const [modal, setModal] = useState<{ mode: 'create' } | { mode: 'edit'; asset: Asset } | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState('');

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

  const saveMutation = useMutation({
    mutationFn: () =>
      modal?.mode === 'edit'
        ? updateAsset(modal.asset.id, toPayload(form))
        : createAsset(toPayload(form)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assets'] });
      queryClient.invalidateQueries({ queryKey: ['license'] });
      setModal(null);
    },
    onError: (err: unknown) => {
      const data = (err as { response?: { data?: { detail?: unknown; message?: string } } })?.response?.data;
      const detail = typeof data?.detail === 'string' ? data.detail : data?.message;
      setError(detail ?? 'Save failed');
    },
  });

  const openCreate = () => { setForm(EMPTY_FORM); setError(''); setModal({ mode: 'create' }); };
  const openEdit = (a: Asset) => {
    setForm({
      name: a.name, category: a.category, asset_type: a.asset_type ?? '',
      serial_number: a.serial_number ?? '', vendor: a.vendor ?? '', model: a.model ?? '',
      location: a.location ?? '', department: a.department ?? '',
      purchase_date: a.purchase_date ?? '', purchase_cost: a.purchase_cost ?? '',
      warranty_end: a.warranty_end ?? '', notes: a.notes ?? '',
    });
    setError('');
    setModal({ mode: 'edit', asset: a });
  };

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
        {canEdit && (
          <button
            onClick={openCreate}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" /> New asset
          </button>
        )}
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
                <th className="px-6 py-4">Category</th>
                <th className="px-6 py-4">State</th>
                <th className="px-6 py-4">Vendor / Model</th>
                <th className="px-6 py-4">Assigned</th>
                <th className="px-6 py-4" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {isLoading ? (
                <tr><td colSpan={7} className="px-6 py-12 text-center text-slate-500">Loading…</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={7} className="px-6 py-12 text-center text-slate-500">No assets yet.</td></tr>
              ) : items.map((a) => (
                <tr
                  key={a.id}
                  onClick={() => navigate(`/assets/${a.id}`)}
                  className="hover:bg-slate-800/40 transition-colors cursor-pointer"
                >
                  <td className="px-6 py-4 font-mono text-xs text-indigo-300">{a.asset_tag}</td>
                  <td className="px-6 py-4 font-medium text-slate-200">{a.name}</td>
                  <td className="px-6 py-4 text-sm text-slate-300">{a.category}</td>
                  <td className="px-6 py-4"><StateBadge state={a.lifecycle_state} /></td>
                  <td className="px-6 py-4 text-sm text-slate-400">
                    {[a.vendor, a.model].filter(Boolean).join(' / ') || '—'}
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-400">{a.assignee_username ?? '—'}</td>
                  <td className="px-6 py-4 text-right">
                    {canEdit && (
                      <button
                        onClick={(e) => { e.stopPropagation(); openEdit(a); }}
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

      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setModal(null)}>
          <div
            className="bg-slate-800 border border-slate-700 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-xl font-semibold text-white">
                {modal.mode === 'edit' ? `Edit ${modal.asset.asset_tag}` : 'New asset'}
              </h2>
              <button onClick={() => setModal(null)} className="p-1.5 text-slate-400 hover:text-white rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form
              onSubmit={(e) => { e.preventDefault(); setError(''); saveMutation.mutate(); }}
              className="grid grid-cols-1 sm:grid-cols-2 gap-4"
            >
              <label className="sm:col-span-2 text-sm text-slate-400">Name *
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Category *
                <select
                  value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}
                  disabled={modal.mode === 'edit'}
                  className={`${input} mt-1 disabled:opacity-50`}
                >
                  {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
              <label className="text-sm text-slate-400">Type
                <input value={form.asset_type} onChange={(e) => setForm({ ...form, asset_type: e.target.value })} placeholder="laptop, server, vm…" className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Serial number
                <input value={form.serial_number} onChange={(e) => setForm({ ...form, serial_number: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Vendor
                <input value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Model
                <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Location
                <input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Department
                <input value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Purchase date
                <input type="date" value={form.purchase_date} onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Purchase cost
                <input type="number" step="0.01" min="0" value={form.purchase_cost} onChange={(e) => setForm({ ...form, purchase_cost: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="text-sm text-slate-400">Warranty end
                <input type="date" value={form.warranty_end} onChange={(e) => setForm({ ...form, warranty_end: e.target.value })} className={`${input} mt-1`} />
              </label>
              <label className="sm:col-span-2 text-sm text-slate-400">Notes
                <textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={`${input} mt-1`} />
              </label>

              {error && <p className="sm:col-span-2 text-sm text-rose-400">{error}</p>}

              <div className="sm:col-span-2 flex justify-end gap-3 mt-1">
                <button type="button" onClick={() => setModal(null)}
                  className="px-4 py-2 text-sm text-slate-300 bg-slate-700/60 hover:bg-slate-700 rounded-lg transition-colors">
                  Cancel
                </button>
                <button type="submit" disabled={saveMutation.isPending}
                  className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg transition-colors">
                  {saveMutation.isPending ? 'Saving…' : 'Save'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
