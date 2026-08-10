import { useState, useEffect } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getAssetById, createAsset, updateAsset } from '../api';
import {
  ASSET_GROUPS, CATEGORY_OPTIONS,
  EMPTY_ASSET_FORM, assetToForm, assetFormToPayload, type AssetFormState,
} from '../lib/assetSchema';
import { ArrowLeft, Cpu, Check } from 'lucide-react';
import clsx from 'clsx';

export default function AssetForm() {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [form, setForm] = useState<AssetFormState>({ ...EMPTY_ASSET_FORM });
  const [activeTab, setActiveTab] = useState(0);
  const [error, setError] = useState('');

  const { data: res } = useQuery({
    queryKey: ['asset', Number(id)],
    queryFn: () => getAssetById(Number(id)),
    enabled: isEdit,
  });
  const existing = res?.data;

  useEffect(() => {
    if (existing) setForm(assetToForm(existing));
  }, [existing]);

  const setField = (key: string, value: string) => setForm((f) => ({ ...f, [key]: value }));

  const save = useMutation({
    mutationFn: () =>
      isEdit
        ? updateAsset(Number(id), assetFormToPayload(form))
        : createAsset(assetFormToPayload(form)),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['assets'] });
      queryClient.invalidateQueries({ queryKey: ['license'] });
      const newId = r.data?.id ?? id;
      navigate(newId ? `/assets/${newId}` : '/assets');
    },
    onError: (err: unknown) => {
      const data = (err as { response?: { data?: { detail?: unknown; message?: string } } })?.response?.data;
      const detail = typeof data?.detail === 'string' ? data.detail
        : Array.isArray(data?.detail) ? (data.detail[0]?.msg ?? 'Validation error')
        : data?.message;
      setError(detail ?? 'Save failed');
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!form.name.trim()) { setActiveTab(0); setError('Name is required'); return; }
    save.mutate();
  };

  const input = 'w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500';
  const group = ASSET_GROUPS[activeTab];

  return (
    <form onSubmit={submit} className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to={isEdit ? `/assets/${id}` : '/assets'}
          className="p-2 bg-slate-800 rounded-lg hover:bg-slate-700 transition-colors">
          <ArrowLeft className="w-5 h-5 text-slate-300" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-50">
            {isEdit ? `Edit ${existing?.asset_tag ?? 'asset'}` : 'New asset'}
          </h1>
          <p className="text-slate-400 text-sm mt-0.5">
            {isEdit ? existing?.name : 'Register a new managed asset'}
          </p>
        </div>
      </div>

      {/* Always-visible identity header */}
      <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <label className="sm:col-span-2 text-sm text-slate-400">Hostname / Asset Name *
            <input required value={form.name} onChange={(e) => setField('name', e.target.value)}
              className={`${input} mt-1`} autoFocus={!isEdit} />
          </label>
          <label className="text-sm text-slate-400">Device Category *
            <select value={form.category} onChange={(e) => setField('category', e.target.value)}
              disabled={isEdit} className={`${input} mt-1 disabled:opacity-50`}>
              {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 overflow-hidden">
        <div className="flex gap-1 overflow-x-auto border-b border-slate-700/50 bg-slate-800/50 px-2">
          {ASSET_GROUPS.map((g, i) => (
            <button
              key={g.title}
              type="button"
              onClick={() => setActiveTab(i)}
              className={clsx(
                'px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors',
                i === activeTab
                  ? 'border-indigo-500 text-slate-50'
                  : 'border-transparent text-slate-400 hover:text-slate-200',
              )}
            >
              {g.title}
            </button>
          ))}
        </div>

        <div className="p-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
            {group.fields.map((f) => (
              <label key={f.key} className={clsx('text-sm text-slate-400', f.full && 'sm:col-span-2 lg:col-span-3')}>
                <span className="flex items-center gap-1.5">
                  {f.label}
                  {f.fromDevice && <Cpu className="w-3 h-3 text-slate-600" aria-label="auto-filled from linked device" />}
                </span>
                {f.type === 'select' ? (
                  <select value={form[f.key] ?? ''} onChange={(e) => setField(f.key, e.target.value)} className={`${input} mt-1`}>
                    <option value="">—</option>
                    {f.options!.map((o) => <option key={o} value={o}>{o.replace(/_/g, ' ')}</option>)}
                  </select>
                ) : f.type === 'textarea' ? (
                  <textarea rows={3} value={form[f.key] ?? ''} placeholder={f.placeholder}
                    onChange={(e) => setField(f.key, e.target.value)} className={`${input} mt-1`} />
                ) : (
                  <input
                    type={f.type === 'number' ? 'number' : f.type === 'date' ? 'date'
                      : f.type === 'datetime' ? 'datetime-local' : 'text'}
                    step={f.type === 'number' ? '0.01' : undefined}
                    value={form[f.key] ?? ''} placeholder={f.placeholder}
                    onChange={(e) => setField(f.key, e.target.value)} className={`${input} mt-1`} />
                )}
              </label>
            ))}
          </div>
          {group.fields.some((f) => f.fromDevice) && (
            <p className="text-xs text-slate-500 mt-4 flex items-center gap-1.5">
              <Cpu className="w-3 h-3" /> Fields marked with this icon auto-fill from a linked discovered device.
            </p>
          )}
        </div>
      </div>

      {/* Sticky action bar */}
      <div className="sticky bottom-0 bg-slate-900/80 backdrop-blur-sm border-t border-slate-700/50 py-4 flex items-center justify-between">
        <div className="text-sm">
          {error && <span className="text-rose-400">{error}</span>}
        </div>
        <div className="flex gap-3">
          <button type="button" onClick={() => navigate(isEdit ? `/assets/${id}` : '/assets')}
            className="px-4 py-2 text-sm text-slate-300 bg-slate-700/60 hover:bg-slate-700 rounded-lg transition-colors">
            Cancel
          </button>
          <button type="submit" disabled={save.isPending}
            className="inline-flex items-center gap-2 px-5 py-2 text-sm font-medium text-slate-50 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg transition-colors">
            <Check className="w-4 h-4" />
            {save.isPending ? 'Saving…' : isEdit ? 'Save changes' : 'Create asset'}
          </button>
        </div>
      </div>
    </form>
  );
}
