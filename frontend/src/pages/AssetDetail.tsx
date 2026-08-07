import { useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getAssetById, transitionAsset, deleteAsset } from '../api';
import { StateBadge } from './Assets';
import { ArrowLeft, ArrowRight, Trash2, Laptop, History } from 'lucide-react';
import { format } from 'date-fns';
import { useAuth } from '../context/AuthContext';

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs text-slate-500 uppercase tracking-wider">{label}</p>
      <p className="text-sm text-slate-200 mt-1">{value ?? '—'}</p>
    </div>
  );
}

export default function AssetDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canEdit = user?.role === 'admin' || user?.role === 'asset_manager';
  const [note, setNote] = useState('');
  const [error, setError] = useState('');

  const assetId = Number(id);
  const { data: res, isLoading } = useQuery({
    queryKey: ['asset', assetId],
    queryFn: () => getAssetById(assetId),
    enabled: Number.isFinite(assetId),
  });
  const asset = res?.data;

  const onError = (err: unknown) => {
    const data = (err as { response?: { data?: { detail?: unknown; message?: string } } })?.response?.data;
    const detail = typeof data?.detail === 'string' ? data.detail : data?.message;
    setError(detail ?? 'Operation failed');
  };

  const transition = useMutation({
    mutationFn: (to_state: string) => transitionAsset(assetId, to_state, note || undefined),
    onSuccess: () => {
      setNote('');
      setError('');
      queryClient.invalidateQueries({ queryKey: ['asset', assetId] });
      queryClient.invalidateQueries({ queryKey: ['assets'] });
    },
    onError,
  });

  const remove = useMutation({
    mutationFn: () => deleteAsset(assetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assets'] });
      queryClient.invalidateQueries({ queryKey: ['license'] });
      navigate('/assets');
    },
    onError,
  });

  if (isLoading) return <div className="flex items-center justify-center h-64 text-slate-400">Loading…</div>;
  if (!asset) return <div className="text-rose-400 p-6">Asset not found.</div>;

  const money = asset.purchase_cost ? `${asset.purchase_cost} ${asset.currency}` : null;

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/assets" className="p-2 bg-slate-800 rounded-lg hover:bg-slate-700 transition-colors">
            <ArrowLeft className="w-5 h-5 text-slate-300" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              {asset.name}
              <StateBadge state={asset.lifecycle_state} />
            </h1>
            <p className="text-slate-400 text-sm font-mono mt-0.5">{asset.asset_tag}</p>
          </div>
        </div>
        {user?.role === 'admin' && (
          <button
            onClick={() => { if (confirm(`Delete ${asset.asset_tag}? This cannot be undone.`)) remove.mutate(); }}
            className="inline-flex items-center gap-2 px-3 py-2 text-sm text-rose-400 bg-rose-500/10 hover:bg-rose-500/20 rounded-lg transition-colors"
          >
            <Trash2 className="w-4 h-4" /> Delete
          </button>
        )}
      </div>

      <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-5">
          <Field label="Category" value={asset.category} />
          <Field label="Type" value={asset.asset_type} />
          <Field label="Serial number" value={asset.serial_number} />
          <Field label="Vendor" value={asset.vendor} />
          <Field label="Model" value={asset.model} />
          <Field label="Location" value={asset.location} />
          <Field label="Department" value={asset.department} />
          <Field label="Assigned to" value={asset.assignee_username} />
          <Field label="Purchase date" value={asset.purchase_date} />
          <Field label="Purchase cost" value={money} />
          <Field label="Warranty until" value={asset.warranty_end} />
          <Field
            label="Linked device"
            value={asset.device_id
              ? <Link to={`/devices/${asset.device_id}`} className="text-indigo-400 hover:underline inline-flex items-center gap-1">
                  <Laptop className="w-3.5 h-3.5" />{asset.device_hostname ?? `#${asset.device_id}`}
                </Link>
              : null}
          />
        </div>
        {asset.notes && (
          <p className="text-sm text-slate-300 mt-5 pt-5 border-t border-slate-700/50 whitespace-pre-wrap">{asset.notes}</p>
        )}
      </div>

      {canEdit && asset.allowed_transitions.length > 0 && (
        <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
          <h2 className="text-sm font-semibold text-slate-300 mb-3">Change lifecycle state</h2>
          <div className="flex flex-col sm:flex-row gap-3">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Optional note for the audit trail…"
              className="flex-1 px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <div className="flex gap-2">
              {asset.allowed_transitions.map((s) => (
                <button
                  key={s}
                  disabled={transition.isPending}
                  onClick={() => transition.mutate(s)}
                  className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg transition-colors"
                >
                  <ArrowRight className="w-4 h-4" /> {s.replace('_', ' ')}
                </button>
              ))}
            </div>
          </div>
          {error && <p className="text-sm text-rose-400 mt-3">{error}</p>}
        </div>
      )}

      <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
        <h2 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
          <History className="w-4 h-4" /> Lifecycle history
        </h2>
        <ol className="space-y-3">
          {[...asset.lifecycle_events].reverse().map((e) => (
            <li key={e.id} className="flex items-start gap-3 text-sm">
              <span className="mt-1.5 w-2 h-2 rounded-full bg-indigo-500 shrink-0" />
              <div>
                <p className="text-slate-200">
                  {e.from_state ? <>{e.from_state.replace('_', ' ')} <span className="text-slate-500">→</span> </> : null}
                  <span className="font-medium">{e.to_state.replace('_', ' ')}</span>
                  {e.actor && <span className="text-slate-500"> · by {e.actor}</span>}
                </p>
                <p className="text-xs text-slate-500">
                  {format(new Date(e.occurred_at), 'PPp')}{e.note ? ` — ${e.note}` : ''}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
