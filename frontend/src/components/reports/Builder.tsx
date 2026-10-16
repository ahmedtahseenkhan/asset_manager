import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createSavedReport, exportReport, runReport, updateSavedReport } from '../../api';
import type {
  ReportCatalog, ReportDefinition, ReportEntity, ReportField, ReportFilter, ReportGroupsResult, ReportOperator,
  ReportRowsResult,
} from '../../types';
import { errorText } from '../../lib/errors';
import Modal from '../Modal';
import { BTN_GHOST, BTN_PRIMARY, CARD, ICON_BTN, INPUT, LABEL, SELECT } from './ui';
import { emptyDefinition, formatCell } from './definition';
import { Download, Plus, Save, X, ChevronLeft, ChevronRight, ArrowUp, ArrowDown } from 'lucide-react';
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from 'recharts';
import clsx from 'clsx';

export interface Draft {
  definition: ReportDefinition;
  name: string;
  description?: string | null;
  savedId?: number;
  canEdit?: boolean;
}

const CHART_COLORS = ['#16a34a', '#0ea5e9', '#f59e0b', '#ec4899', '#8b5cf6', '#14b8a6', '#f97316', '#64748b'];
const PAGE_SIZE = 50;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

// ── Filter row ──────────────────────────────────────────────────────────────
function FilterRow({ filter, entity, operators, onChange, onRemove }: {
  filter: ReportFilter; entity: ReportEntity; operators: ReportCatalog['operators'];
  onChange: (f: ReportFilter) => void; onRemove: () => void;
}) {
  const field = entity.fields.find((f) => f.key === filter.field) ?? entity.fields[0];
  const ops = operators[field.type] ?? [];
  const op: ReportOperator | undefined = ops.find((o) => o.op === filter.op) ?? ops[0];
  const value = filter.value ?? '';

  const setField = (key: string) => {
    const f = entity.fields.find((x) => x.key === key)!;
    onChange({ field: key, op: (operators[f.type] ?? [])[0]?.op ?? 'eq', value: null });
  };

  let input: React.ReactNode = null;
  if (op?.value === 'choice') {
    input = (
      <select className={SELECT} value={String(value)} onChange={(e) => onChange({ ...filter, value: e.target.value })}>
        <option value="">Choose…</option>
        {(field.choices ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    );
  } else if (op?.value === 'date') {
    input = <input type="date" className={INPUT} value={String(value)} onChange={(e) => onChange({ ...filter, value: e.target.value })} />;
  } else if (op?.value === 'number' || op?.value === 'days') {
    input = (
      <div className="flex items-center gap-2">
        <input type="number" className={INPUT} value={String(value)} onChange={(e) => onChange({ ...filter, value: e.target.value })} />
        {op.value === 'days' && <span className="text-xs text-slate-500">days</span>}
      </div>
    );
  } else if (op && op.value !== 'none') {
    const hint = op.value === 'choices' ? (field.choices ?? []).join(', ') : op.value === 'list' ? 'comma, separated' : '';
    input = <input className={INPUT} value={String(value)} placeholder={hint} onChange={(e) => onChange({ ...filter, value: e.target.value })} />;
  }

  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/30 p-2.5 space-y-2">
      <div className="flex gap-2">
        <select className={SELECT} value={field.key} onChange={(e) => setField(e.target.value)}>
          {entity.fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
        </select>
        <button className={ICON_BTN} onClick={onRemove} aria-label="Remove filter"><X className="w-4 h-4" /></button>
      </div>
      <select className={SELECT} value={op?.op ?? ''} onChange={(e) => onChange({ ...filter, op: e.target.value })}>
        {ops.map((o) => <option key={o.op} value={o.op}>{o.label}</option>)}
      </select>
      {input}
    </div>
  );
}

// ── Results ─────────────────────────────────────────────────────────────────
function GroupsView({ result, chart }: { result: ReportGroupsResult; chart: ReportDefinition['chart'] }) {
  const data = result.groups.map((g) => ({ name: formatCell(g.value, result.group_field.type), value: g.count }));
  const top = data.slice(0, 15);
  return (
    <div className="space-y-5">
      {chart !== 'none' && top.length > 0 && (
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            {chart === 'pie' ? (
              <PieChart>
                <Pie data={top} dataKey="value" nameKey="name" innerRadius={60} outerRadius={110} paddingAngle={2} stroke="none">
                  {top.map((_d, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            ) : (
              <BarChart data={top} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e6e9ef" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={60} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="value" fill="#22c55e" radius={[4, 4, 0, 0]} maxBarSize={48} />
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
            <th className="py-2">{result.group_field.label}</th><th className="py-2 text-right">Count</th><th className="py-2 w-1/3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/40">
          {result.groups.map((g, i) => {
            const max = result.groups[0]?.count || 1;
            return (
              <tr key={i}>
                <td className="py-2 text-sm text-slate-200">{formatCell(g.value, result.group_field.type)}</td>
                <td className="py-2 text-sm text-slate-300 text-right tabular-nums">{g.count.toLocaleString()}</td>
                <td className="py-2 pl-4"><div className="h-1.5 rounded-full bg-indigo-500/70" style={{ width: `${(g.count / max) * 100}%` }} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RowsView({ result, page, setPage }: { result: ReportRowsResult; page: number; setPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(result.total / result.size));
  const linkTo = (id: unknown) => (result.link === 'device' ? `/devices/${id}` : result.link === 'asset' ? `/assets/${id}` : null);
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
              {result.columns.map((c) => <th key={c.key} className="py-2 pr-4 whitespace-nowrap">{c.label}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/40">
            {result.rows.map((row, i) => (
              <tr key={i} className="hover:bg-slate-700/10">
                {result.columns.map((c, j) => {
                  const text = formatCell(row[c.key], c.type);
                  const href = j === 0 && row._link_id ? linkTo(row._link_id) : null;
                  return (
                    <td key={c.key} className={clsx('py-2 pr-4 text-sm', j === 0 ? 'text-slate-200' : 'text-slate-400')}>
                      {href ? <Link to={href} className="hover:text-indigo-400">{text}</Link> : text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result.rows.length === 0 && <p className="py-8 text-center text-sm text-slate-500">Nothing matches these filters.</p>}
      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 mt-4 text-sm text-slate-400">
          <button className={ICON_BTN} disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft className="w-4 h-4" /></button>
          Page {page} of {pages}
          <button className={ICON_BTN} disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight className="w-4 h-4" /></button>
        </div>
      )}
    </div>
  );
}

// ── Save dialog ─────────────────────────────────────────────────────────────
function SaveModal({ draft, asCopy, onClose, onSaved }: {
  draft: Draft; asCopy: boolean; onClose: () => void; onSaved: (id: number, name: string) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(asCopy ? `${draft.name} (copy)` : draft.name);
  const [description, setDescription] = useState(draft.description ?? '');
  const [shared, setShared] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [error, setError] = useState('');
  const save = useMutation({
    mutationFn: () => (draft.savedId && !asCopy
      ? updateSavedReport(draft.savedId, { name, description, definition: draft.definition })
      : createSavedReport({ name, description, definition: draft.definition, shared, pinned })),
    onSuccess: (r) => { queryClient.invalidateQueries({ queryKey: ['saved-reports'] }); queryClient.invalidateQueries({ queryKey: ['pinned-reports'] }); onSaved(r.data.id, r.data.name); },
    onError: (e) => setError(errorText(e)),
  });
  const updating = !!draft.savedId && !asCopy;
  return (
    <Modal title={updating ? 'Save changes' : 'Save report'} onClose={onClose}>
      <div className="space-y-4">
        <div>
          <label className={LABEL}>Name</label>
          <input className={INPUT} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </div>
        <div>
          <label className={LABEL}>Description</label>
          <input className={INPUT} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What this report is for" />
        </div>
        {!updating && (
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} className="accent-indigo-500" />
              Share with everyone
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} className="accent-indigo-500" />
              Pin to the dashboard
            </label>
          </div>
        )}
        {error && <p className="text-sm text-rose-400">{error}</p>}
        <div className="flex justify-end gap-3">
          <button className={BTN_GHOST} onClick={onClose}>Cancel</button>
          <button className={BTN_PRIMARY} disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ── Builder ─────────────────────────────────────────────────────────────────
export default function Builder({ catalog, draft, setDraft }: {
  catalog: ReportCatalog; draft: Draft; setDraft: (d: Draft) => void;
}) {
  const { definition: defn } = draft;
  const entity = catalog.entities.find((e) => e.key === defn.entity) ?? catalog.entities[0];
  const [page, setPage] = useState(1);
  const [saving, setSaving] = useState<null | 'save' | 'copy'>(null);
  const [exportError, setExportError] = useState('');
  const debounced = useDebounced(defn, 400);

  const set = (patch: Partial<ReportDefinition>) => { setPage(1); setDraft({ ...draft, definition: { ...defn, ...patch } }); };

  const { data, error, isFetching } = useQuery({
    queryKey: ['report-run', debounced, page],
    queryFn: () => runReport(debounced, page, PAGE_SIZE),
    placeholderData: (prev) => prev,
    retry: false,
  });
  const result = data?.data;

  const selectable = useMemo(() => entity.fields.filter((f) => !f.filter_only), [entity]);
  const fieldLabel = (k: string) => entity.fields.find((f) => f.key === k)?.label ?? k;
  const unusedColumns = selectable.filter((f) => !defn.columns.includes(f.key));

  const changeEntity = (key: string) => {
    const e = catalog.entities.find((x) => x.key === key)!;
    setPage(1);
    setDraft({ ...draft, definition: emptyDefinition(e) });
  };
  const moveColumn = (i: number, dir: -1 | 1) => {
    const cols = [...defn.columns];
    const j = i + dir;
    if (j < 0 || j >= cols.length) return;
    [cols[i], cols[j]] = [cols[j], cols[i]];
    set({ columns: cols });
  };
  const addFilter = () => {
    const f: ReportField = entity.fields[0];
    set({ filters: [...defn.filters, { field: f.key, op: (catalog.operators[f.type] ?? [])[0]?.op ?? 'eq', value: null }] });
  };

  const doExport = async (fmt: 'xlsx' | 'csv') => {
    setExportError('');
    try { await exportReport(defn, draft.name || 'Report', fmt); } catch (e) { setExportError(errorText(e)); }
  };

  const groupable = selectable.filter((f) => f.type !== 'list');
  const entitiesByCategory = catalog.entities.reduce<Record<string, ReportEntity[]>>((acc, e) => {
    (acc[e.category] ??= []).push(e);
    return acc;
  }, {});

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[22rem_1fr] gap-6 items-start">
      {/* ── configuration ── */}
      <div className={clsx(CARD, 'space-y-6')}>
        <div>
          <label className={LABEL}>Data</label>
          <select className={SELECT} value={entity.key} onChange={(e) => changeEntity(e.target.value)}>
            {Object.entries(entitiesByCategory).map(([cat, list]) => (
              <optgroup key={cat} label={cat}>
                {list.map((e) => <option key={e.key} value={e.key} disabled={!e.licensed}>{e.label}{e.licensed ? '' : ' (not licensed)'}</option>)}
              </optgroup>
            ))}
          </select>
          <p className="text-xs text-slate-500 mt-1.5">{entity.description}</p>
        </div>

        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className={clsx(LABEL, 'mb-0')}>Filters</span>
            {defn.filters.length > 1 && (
              <select className="text-xs bg-transparent text-slate-400 focus:outline-none" value={defn.match}
                onChange={(e) => set({ match: e.target.value as 'all' | 'any' })}>
                <option value="all">match all</option>
                <option value="any">match any</option>
              </select>
            )}
          </div>
          <div className="space-y-2">
            {defn.filters.map((f, i) => (
              <FilterRow key={i} filter={f} entity={entity} operators={catalog.operators}
                onChange={(nf) => set({ filters: defn.filters.map((x, j) => (j === i ? nf : x)) })}
                onRemove={() => set({ filters: defn.filters.filter((_x, j) => j !== i) })} />
            ))}
          </div>
          <button className={clsx(BTN_GHOST, 'mt-2 w-full justify-center')} onClick={addFilter}><Plus className="w-4 h-4" /> Add filter</button>
        </div>

        <div>
          <label className={LABEL}>Group by</label>
          <select className={SELECT} value={defn.group_by ?? ''} onChange={(e) => set({ group_by: e.target.value || null, chart: e.target.value ? (defn.chart === 'none' ? 'bar' : defn.chart) : 'none' })}>
            <option value="">No grouping — list rows</option>
            {groupable.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
          {defn.group_by && (
            <div className="flex gap-2 mt-2">
              {(['bar', 'pie', 'none'] as const).map((c) => (
                <button key={c} onClick={() => set({ chart: c })}
                  className={clsx('flex-1 py-1.5 text-xs rounded-lg border', defn.chart === c ? 'border-indigo-500 text-slate-50 bg-indigo-500/10' : 'border-slate-700 text-slate-400')}>
                  {c === 'none' ? 'Table only' : c === 'bar' ? 'Bar chart' : 'Pie chart'}
                </button>
              ))}
            </div>
          )}
        </div>

        {!defn.group_by && (
          <>
            <div>
              <label className={LABEL}>Columns</label>
              <ul className="space-y-1 mb-2">
                {defn.columns.map((k, i) => (
                  <li key={k} className="flex items-center gap-1 text-sm text-slate-200 bg-slate-900/30 rounded-md px-2 py-1">
                    <span className="flex-1 truncate">{fieldLabel(k)}</span>
                    <button className={ICON_BTN} disabled={i === 0} onClick={() => moveColumn(i, -1)} aria-label="Move up"><ArrowUp className="w-3.5 h-3.5" /></button>
                    <button className={ICON_BTN} disabled={i === defn.columns.length - 1} onClick={() => moveColumn(i, 1)} aria-label="Move down"><ArrowDown className="w-3.5 h-3.5" /></button>
                    <button className={ICON_BTN} disabled={defn.columns.length === 1} onClick={() => set({ columns: defn.columns.filter((c) => c !== k) })} aria-label="Remove column"><X className="w-3.5 h-3.5" /></button>
                  </li>
                ))}
              </ul>
              {unusedColumns.length > 0 && (
                <select className={SELECT} value="" onChange={(e) => e.target.value && set({ columns: [...defn.columns, e.target.value] })}>
                  <option value="">Add a column…</option>
                  {unusedColumns.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                </select>
              )}
            </div>
            <div>
              <label className={LABEL}>Sort by</label>
              <div className="flex gap-2">
                <select className={SELECT} value={defn.sort ?? entity.default_sort} onChange={(e) => set({ sort: e.target.value })}>
                  {selectable.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                </select>
                <select className={clsx(SELECT, 'w-32')} value={defn.sort_dir} onChange={(e) => set({ sort_dir: e.target.value as 'asc' | 'desc' })}>
                  <option value="asc">A → Z</option>
                  <option value="desc">Z → A</option>
                </select>
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── results ── */}
      <div className={clsx(CARD, 'min-w-0')}>
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div className="min-w-0 flex-1">
            <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              className="w-full bg-transparent text-lg font-semibold text-slate-50 focus:outline-none border-b border-transparent focus:border-slate-600" />
            <p className="text-sm text-slate-500 mt-1">
              {result ? `${result.total.toLocaleString()} ${result.total === 1 ? 'row' : 'rows'}${result.kind === 'groups' ? ' grouped' : ''}` : '…'}
              {isFetching && <span className="ml-2 text-slate-600">updating…</span>}
            </p>
          </div>
          <div className="flex gap-2">
            {draft.savedId && draft.canEdit && (
              <button className={BTN_GHOST} onClick={() => setSaving('save')}><Save className="w-4 h-4" /> Save</button>
            )}
            <button className={BTN_GHOST} onClick={() => setSaving(draft.savedId ? 'copy' : 'save')}>
              <Save className="w-4 h-4" /> {draft.savedId ? 'Save as new' : 'Save'}
            </button>
            <button className={BTN_PRIMARY} onClick={() => doExport('xlsx')}><Download className="w-4 h-4" /> Excel</button>
            <button className={BTN_GHOST} onClick={() => doExport('csv')}>CSV</button>
          </div>
        </div>
        {exportError && <p className="text-sm text-rose-400 mb-3">{exportError}</p>}
        {error ? (
          <p className="text-sm text-rose-400 bg-rose-500/10 border border-rose-500/30 rounded-lg p-3">{errorText(error)}</p>
        ) : result?.kind === 'groups' ? (
          <GroupsView result={result} chart={defn.chart} />
        ) : result?.kind === 'rows' ? (
          <RowsView result={result} page={page} setPage={setPage} />
        ) : (
          <p className="text-sm text-slate-500">Running…</p>
        )}
      </div>

      {saving && (
        <SaveModal draft={draft} asCopy={saving === 'copy'} onClose={() => setSaving(null)}
          onSaved={(id, name) => { setSaving(null); setDraft({ ...draft, savedId: id, name, canEdit: true }); }} />
      )}
    </div>
  );
}
