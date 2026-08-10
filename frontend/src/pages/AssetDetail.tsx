import { useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getAssetById, transitionAsset, deleteAsset, getAssets, addRelationship, removeRelationship, getAssetVulns } from '../api';
import { StateBadge } from './Assets';
import { ASSET_GROUPS, ENUM_BADGE } from '../lib/assetSchema';
import { ArrowLeft, ArrowRight, Trash2, Laptop, History, Share2, X, Bug, Plus, Search } from 'lucide-react';
import { format } from 'date-fns';
import clsx from 'clsx';
import { useAuth } from '../context/AuthContext';

const REL_TYPES = ['depends_on', 'installed_on', 'connected_to', 'hosts', 'part_of', 'backs_up'];
const REL_LABELS: Record<string, string> = {
  depends_on: 'Depends on', installed_on: 'Installed on', connected_to: 'Connected to',
  hosts: 'Hosts', part_of: 'Part of', backs_up: 'Backs up',
};

// Canonical lifecycle order for the visual stepper.
const LIFECYCLE_FLOW = ['requested', 'ordered', 'in_stock', 'deployed', 'maintenance', 'retired'];
const STATE_DOT: Record<string, string> = {
  requested: 'bg-slate-400', ordered: 'bg-blue-400', in_stock: 'bg-cyan-400',
  deployed: 'bg-emerald-400', maintenance: 'bg-yellow-400', retired: 'bg-rose-400',
};

function LifecycleCard({
  current, allowed, canEdit, note, setNote, pending, onTransition, error,
}: {
  current: string; allowed: string[]; canEdit: boolean;
  note: string; setNote: (v: string) => void; pending: boolean;
  onTransition: (s: string) => void; error: string;
}) {
  const curIdx = LIFECYCLE_FLOW.indexOf(current);
  return (
    <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-5">Lifecycle</h2>

      {/* Stepper */}
      <div className="flex items-center mb-6 overflow-x-auto pb-1">
        {LIFECYCLE_FLOW.map((s, i) => {
          const done = i < curIdx;
          const active = s === current;
          return (
            <div key={s} className="flex items-center shrink-0">
              <div className="flex flex-col items-center gap-1.5">
                <div className={clsx(
                  'w-3.5 h-3.5 rounded-full ring-2 transition-colors',
                  active ? `${STATE_DOT[s]} ring-white/30 scale-125`
                    : done ? `${STATE_DOT[s]} ring-transparent`
                    : 'bg-slate-700 ring-transparent',
                )} />
                <span className={clsx('text-[11px] whitespace-nowrap',
                  active ? 'text-slate-50 font-semibold' : done ? 'text-slate-300' : 'text-slate-600')}>
                  {s.replace('_', ' ')}
                </span>
              </div>
              {i < LIFECYCLE_FLOW.length - 1 && (
                <div className={clsx('h-0.5 w-8 sm:w-14 mx-1 mb-5', i < curIdx ? 'bg-emerald-500/50' : 'bg-slate-700')} />
              )}
            </div>
          );
        })}
      </div>

      {/* Actions */}
      {canEdit && allowed.length > 0 ? (
        <div className="pt-5 border-t border-slate-700/50">
          <p className="text-xs text-slate-500 mb-3">Move this asset to its next state:</p>
          <div className="flex flex-col lg:flex-row gap-3">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Optional note for the audit trail…"
              className="flex-1 px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <div className="flex flex-wrap gap-2">
              {allowed.map((s) => (
                <button key={s} disabled={pending} onClick={() => onTransition(s)}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-slate-50 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg transition-colors">
                  <ArrowRight className="w-4 h-4" />
                  <span className={`w-2 h-2 rounded-full ${STATE_DOT[s]}`} />
                  {s.replace('_', ' ')}
                </button>
              ))}
            </div>
          </div>
          {error && <p className="text-sm text-rose-400 mt-3">{error}</p>}
        </div>
      ) : (
        <p className="text-xs text-slate-500 pt-5 border-t border-slate-700/50">
          {allowed.length === 0 ? 'This is a terminal state — no further transitions.' : 'Read-only — you cannot change lifecycle state.'}
        </p>
      )}
    </div>
  );
}

function RelationshipsCard({ assetId, canEdit }: { assetId: number; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [relType, setRelType] = useState('depends_on');
  const [targetSearch, setTargetSearch] = useState('');
  const [targetId, setTargetId] = useState<number | null>(null);
  const [error, setError] = useState('');

  const { data: res } = useQuery({ queryKey: ['asset', assetId], queryFn: () => getAssetById(assetId) });
  const rels = res?.data?.relationships;

  const { data: candidates } = useQuery({
    queryKey: ['asset-search', targetSearch],
    queryFn: () => getAssets(1, 10, targetSearch ? { search: targetSearch } : {}),
    enabled: canEdit,
  });

  const refresh = () => {
    setError('');
    queryClient.invalidateQueries({ queryKey: ['asset', assetId] });
  };
  const onError = (err: unknown) => {
    const data = (err as { response?: { data?: { detail?: unknown; message?: string } } })?.response?.data;
    const detail = typeof data?.detail === 'string' ? data.detail : data?.message;
    setError(detail ?? 'Operation failed');
  };

  const add = useMutation({
    mutationFn: () => addRelationship(assetId, targetId!, relType),
    onSuccess: () => { setTargetId(null); setTargetSearch(''); refresh(); },
    onError,
  });
  const remove = useMutation({
    mutationFn: (relId: number) => removeRelationship(assetId, relId),
    onSuccess: refresh,
    onError,
  });

  const input = 'px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500';
  const outgoing = rels?.outgoing ?? [];
  const incoming = rels?.incoming ?? [];
  const [adding, setAdding] = useState(false);

  const EdgeRow = ({ e, dir }: { e: any; dir: 'out' | 'in' }) => (
    <div className="group flex items-center gap-3 px-3 py-2.5 rounded-xl bg-slate-900/40 border border-slate-700/40 hover:border-slate-600 transition-colors">
      <span className={clsx('px-2 py-0.5 rounded-md text-[10px] font-bold uppercase ring-1 ring-inset',
        dir === 'out' ? 'bg-indigo-500/15 text-indigo-300 ring-indigo-500/25' : 'bg-purple-500/15 text-purple-300 ring-purple-500/25')}>
        {e.label}
      </span>
      <Link to={`/assets/${e.asset.id}`} className="flex items-center gap-2 min-w-0 hover:underline">
        <span className="text-slate-200 truncate">{e.asset.name}</span>
        <span className="font-mono text-xs text-slate-500 shrink-0">{e.asset.asset_tag}</span>
      </Link>
      <StateBadge state={e.asset.lifecycle_state} />
      {canEdit && (
        <button onClick={() => remove.mutate(e.id)}
          className="ml-auto p-1 text-slate-600 hover:text-rose-400 opacity-0 group-hover:opacity-100 transition-opacity" title="Remove">
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );

  return (
    <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <Share2 className="w-4 h-4" /> Relationships
          <span className="text-slate-500 normal-case font-normal">({outgoing.length + incoming.length})</span>
        </h2>
        {canEdit && !adding && (
          <button onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-300 bg-indigo-500/10 hover:bg-indigo-500/20 rounded-lg ring-1 ring-inset ring-indigo-500/25 transition-colors">
            <Plus className="w-3.5 h-3.5" /> Add relationship
          </button>
        )}
      </div>

      {/* Add form (collapsible) */}
      {canEdit && adding && (
        <div className="mb-4 p-4 rounded-xl bg-slate-900/40 border border-slate-700/50">
          <div className="flex flex-col lg:flex-row gap-2 items-stretch">
            <span className="self-center text-sm text-slate-400 shrink-0">This asset</span>
            <select value={relType} onChange={(e) => setRelType(e.target.value)} className={`${input} lg:w-44`}>
              {REL_TYPES.map((t) => <option key={t} value={t}>{REL_LABELS[t]}</option>)}
            </select>
            <div className="relative flex-1">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                <input value={targetSearch}
                  onChange={(e) => { setTargetSearch(e.target.value); setTargetId(null); }}
                  placeholder="Search target asset…" className={`${input} w-full pl-9`} autoFocus />
              </div>
              {targetSearch && !targetId && (
                <div className="absolute z-10 mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg shadow-xl max-h-48 overflow-y-auto">
                  {(candidates?.data?.items ?? []).filter((a) => a.id !== assetId).map((a) => (
                    <button key={a.id} onClick={() => { setTargetId(a.id); setTargetSearch(`${a.asset_tag} — ${a.name}`); }}
                      className="w-full text-left px-3 py-2 text-sm text-slate-200 hover:bg-slate-700/60">
                      <span className="font-mono text-xs text-indigo-300 mr-2">{a.asset_tag}</span>{a.name}
                    </button>
                  ))}
                  {(candidates?.data?.items ?? []).filter((a) => a.id !== assetId).length === 0 &&
                    <p className="px-3 py-2 text-sm text-slate-500">No matches.</p>}
                </div>
              )}
            </div>
            <button disabled={!targetId || add.isPending} onClick={() => add.mutate()}
              className="px-4 py-2 text-sm font-medium text-slate-50 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg">Add</button>
            <button onClick={() => { setAdding(false); setTargetSearch(''); setTargetId(null); }}
              className="px-3 py-2 text-sm text-slate-400 hover:text-slate-50">Cancel</button>
          </div>
          {error && <p className="text-sm text-rose-400 mt-2">{error}</p>}
        </div>
      )}

      {outgoing.length + incoming.length === 0 ? (
        <div className="text-center py-8">
          <Share2 className="w-8 h-8 text-slate-600 mx-auto mb-2" />
          <p className="text-sm text-slate-500">No relationships mapped yet.</p>
          {canEdit && <p className="text-xs text-slate-600 mt-1">Map dependencies to build the CMDB graph.</p>}
        </div>
      ) : (
        <div className="space-y-4">
          {outgoing.length > 0 && (
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Outgoing</p>
              <div className="space-y-2">{outgoing.map((e) => <EdgeRow key={`o-${e.id}`} e={e} dir="out" />)}</div>
            </div>
          )}
          {incoming.length > 0 && (
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Incoming</p>
              <div className="space-y-2">{incoming.map((e) => <EdgeRow key={`i-${e.id}`} e={e} dir="in" />)}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const VSEV: Record<string, string> = {
  critical: 'bg-rose-500/20 text-rose-400 ring-rose-500/30',
  high: 'bg-orange-500/20 text-orange-400 ring-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
  low: 'bg-blue-500/20 text-blue-400 ring-blue-500/30',
  info: 'bg-slate-500/20 text-slate-400 ring-slate-500/30',
};

function VulnerabilitiesCard({ assetId }: { assetId: number }) {
  const { data } = useQuery({ queryKey: ['asset-vulns', assetId], queryFn: () => getAssetVulns(assetId) });
  const vulns = data?.data ?? [];
  if (vulns.length === 0) return null;
  return (
    <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
      <h2 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
        <Bug className="w-4 h-4" /> Vulnerabilities ({vulns.length})
      </h2>
      <ul className="space-y-2">
        {vulns.map((v: any) => (
          <li key={v.id} className="flex items-center gap-3 text-sm">
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset ${VSEV[v.severity]}`}>{v.severity}</span>
            {v.cve_id && <span className="font-mono text-xs text-slate-400">{v.cve_id}</span>}
            <span className="text-slate-200">{v.title}</span>
            {v.cvss && <span className="ml-auto text-xs text-slate-500">CVSS {v.cvss}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/assets" className="p-2 bg-slate-800 rounded-lg hover:bg-slate-700 transition-colors">
            <ArrowLeft className="w-5 h-5 text-slate-300" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-slate-50 flex items-center gap-3">
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

      <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6 space-y-6">
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-wider mb-3">Overview</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-5">
            <Field label="Category" value={asset.category} />
            <Field label="Assigned to" value={asset.assignee_username} />
            <Field label="Purchase cost" value={money} />
            <Field
              label="Linked device"
              value={asset.device_id
                ? <Link to={`/devices/${asset.device_id}`} className="text-indigo-400 hover:underline inline-flex items-center gap-1">
                    <Laptop className="w-3.5 h-3.5" />{asset.device_hostname ?? `#${asset.device_id}`}
                  </Link>
                : null}
            />
          </div>
        </div>

        {ASSET_GROUPS.map((group) => {
          const shown = group.fields.filter((f) => f.key !== 'notes');
          if (shown.length === 0) return null;
          return (
            <div key={group.title} className="border-t border-slate-700/50 pt-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-indigo-400 mb-3">{group.title}</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-5">
                {shown.map((f) => {
                  const raw = (asset as unknown as Record<string, unknown>)[f.key];
                  const empty = raw == null || raw === '';
                  const badge = !empty ? ENUM_BADGE[f.key]?.[String(raw)] : undefined;
                  return (
                    <Field key={f.key} label={f.label} value={
                      empty ? null
                        : badge
                          ? <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset ${badge}`}>{String(raw).replace(/_/g, ' ')}</span>
                          : String(raw)
                    } />
                  );
                })}
              </div>
            </div>
          );
        })}

        {asset.notes && (
          <div className="border-t border-slate-700/50 pt-5">
            <p className="text-xs font-semibold uppercase tracking-wider text-indigo-400 mb-2">Notes</p>
            <p className="text-sm text-slate-300 whitespace-pre-wrap">{asset.notes}</p>
          </div>
        )}
      </div>

      <LifecycleCard
        current={asset.lifecycle_state}
        allowed={asset.allowed_transitions}
        canEdit={canEdit}
        note={note}
        setNote={setNote}
        pending={transition.isPending}
        onTransition={(s) => transition.mutate(s)}
        error={error}
      />

      <VulnerabilitiesCard assetId={assetId} />

      <RelationshipsCard assetId={assetId} canEdit={canEdit} />

      <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-slate-700/50 p-6">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-5 flex items-center gap-2">
          <History className="w-4 h-4" /> Lifecycle history
          <span className="text-slate-500 normal-case font-normal">({asset.lifecycle_events.length})</span>
        </h2>
        <ol className="relative space-y-5 before:absolute before:left-[5px] before:top-1.5 before:bottom-1.5 before:w-px before:bg-slate-700/60">
          {[...asset.lifecycle_events].reverse().map((e, idx) => (
            <li key={e.id} className="relative flex items-start gap-4 text-sm">
              <span className={clsx('relative z-10 mt-1 w-3 h-3 rounded-full ring-4 ring-slate-800 shrink-0',
                idx === 0 ? STATE_DOT[e.to_state] ?? 'bg-indigo-500' : 'bg-slate-600')} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  {e.from_state && <><StateBadge state={e.from_state} /><ArrowRight className="w-3 h-3 text-slate-600" /></>}
                  <StateBadge state={e.to_state} />
                  {e.actor && <span className="text-xs text-slate-500">by {e.actor}</span>}
                </div>
                <p className="text-xs text-slate-500 mt-1">
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
