import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { deleteSavedReport, exportSavedReport, getSavedReports, sendSavedReport, updateSavedReport } from '../../api';
import type { LibraryReport, ReportCatalog, SavedReport } from '../../types';
import { useAuth } from '../../context/AuthContext';
import { errorText } from '../../lib/errors';
import Modal from '../Modal';
import { BTN_GHOST, BTN_PRIMARY, CARD, ICON_BTN, INPUT, LABEL, SCHEDULE_PRESETS, SELECT, scheduleLabel } from './ui';
import { CalendarClock, Download, FolderOpen, Lock, Mail, Pin, PinOff, Send, Trash2, Users } from 'lucide-react';
import { format } from 'date-fns';
import clsx from 'clsx';

export function LibraryTab({ library, catalog, onOpen }: {
  library: LibraryReport[]; catalog: ReportCatalog; onOpen: (r: LibraryReport) => void;
}) {
  const groups = library.reduce<Record<string, LibraryReport[]>>((acc, r) => {
    (acc[r.category] ??= []).push(r);
    return acc;
  }, {});
  const entityLabel = (k: string) => catalog.entities.find((e) => e.key === k)?.label ?? k;
  return (
    <div className="space-y-8">
      {Object.entries(groups).map(([category, items]) => (
        <section key={category}>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">{category}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {items.map((r) => (
              <button key={r.id} disabled={!r.licensed} onClick={() => onOpen(r)}
                className={clsx(CARD, 'p-5 text-left transition-colors', r.licensed ? 'hover:border-indigo-500/50' : 'opacity-50 cursor-not-allowed')}>
                <p className="text-sm font-semibold text-slate-100">{r.name}</p>
                <p className="text-xs text-slate-400 mt-1">{r.description}</p>
                <p className="text-[11px] text-slate-500 mt-3 uppercase tracking-wider">
                  {entityLabel(r.definition.entity)}{r.definition.group_by ? ' · chart' : ''}{r.licensed ? '' : ' · not licensed'}
                </p>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function ScheduleModal({ report, onClose }: { report: SavedReport; onClose: () => void }) {
  const queryClient = useQueryClient();
  const preset = SCHEDULE_PRESETS.find((p) => p.cron === report.schedule_cron);
  const [cron, setCron] = useState(report.schedule_cron ?? SCHEDULE_PRESETS[1].cron);
  const [custom, setCustom] = useState(!!report.schedule_cron && !preset);
  const [recipients, setRecipients] = useState(report.recipients.join(', '));
  const [fmt, setFmt] = useState(report.export_format);
  const [error, setError] = useState('');
  const done = () => { queryClient.invalidateQueries({ queryKey: ['saved-reports'] }); onClose(); };
  const save = useMutation({
    mutationFn: () => updateSavedReport(report.id, {
      recipients: recipients.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean), schedule_cron: cron, export_format: fmt,
    }),
    onSuccess: done, onError: (e) => setError(errorText(e)),
  });
  const stop = useMutation({ mutationFn: () => updateSavedReport(report.id, { clear_schedule: true }), onSuccess: done,
                             onError: (e) => setError(errorText(e)) });
  return (
    <Modal title={`Email "${report.name}"`} onClose={onClose}>
      <div className="space-y-4">
        <div>
          <label className={LABEL}>Recipients</label>
          <textarea className={INPUT} rows={2} value={recipients} onChange={(e) => setRecipients(e.target.value)}
            placeholder="it-team@corp.local, manager@corp.local" />
        </div>
        <div>
          <label className={LABEL}>When</label>
          <select className={SELECT} value={custom ? 'custom' : cron}
            onChange={(e) => { if (e.target.value === 'custom') setCustom(true); else { setCustom(false); setCron(e.target.value); } }}>
            {SCHEDULE_PRESETS.map((p) => <option key={p.cron} value={p.cron}>{p.label}</option>)}
            <option value="custom">Custom (cron)…</option>
          </select>
          {custom && <input className={clsx(INPUT, 'mt-2 font-mono')} value={cron} onChange={(e) => setCron(e.target.value)} placeholder="m h dom mon dow" />}
          <p className="text-xs text-slate-500 mt-1">Server time (UTC in the standard install).</p>
        </div>
        <div>
          <label className={LABEL}>Attachment</label>
          <select className={SELECT} value={fmt} onChange={(e) => setFmt(e.target.value as 'xlsx' | 'csv')}>
            <option value="xlsx">Excel (.xlsx)</option>
            <option value="csv">CSV</option>
          </select>
        </div>
        {error && <p className="text-sm text-rose-400">{error}</p>}
        <div className="flex justify-between gap-3">
          {report.schedule_cron
            ? <button className={BTN_GHOST} disabled={stop.isPending} onClick={() => stop.mutate()}>Stop emailing</button>
            : <span />}
          <div className="flex gap-3">
            <button className={BTN_GHOST} onClick={onClose}>Cancel</button>
            <button className={BTN_PRIMARY} disabled={save.isPending || !recipients.trim()} onClick={() => save.mutate()}>Save schedule</button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

export function SavedTab({ catalog, onOpen }: { catalog: ReportCatalog; onOpen: (r: SavedReport) => void }) {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['saved-reports'], queryFn: getSavedReports });
  const reports = data?.data ?? [];
  const [scheduling, setScheduling] = useState<SavedReport | null>(null);
  const [notice, setNotice] = useState('');
  const refresh = () => { queryClient.invalidateQueries({ queryKey: ['saved-reports'] }); queryClient.invalidateQueries({ queryKey: ['pinned-reports'] }); };

  const pin = useMutation({ mutationFn: (r: SavedReport) => updateSavedReport(r.id, { pinned: !r.pinned }), onSuccess: refresh,
                            onError: (e) => setNotice(errorText(e)) });
  const share = useMutation({ mutationFn: (r: SavedReport) => updateSavedReport(r.id, { shared: !r.shared }), onSuccess: refresh,
                              onError: (e) => setNotice(errorText(e)) });
  const remove = useMutation({ mutationFn: (id: number) => deleteSavedReport(id), onSuccess: refresh,
                               onError: (e) => setNotice(errorText(e)) });
  const send = useMutation({ mutationFn: (id: number) => sendSavedReport(id),
                             onSuccess: (r) => { setNotice(`Email ${r.data}`); refresh(); },
                             onError: (e) => setNotice(errorText(e)) });
  const download = async (r: SavedReport) => {
    try { await exportSavedReport(r.id, r.name); } catch (e) { setNotice(errorText(e)); }
  };
  const entityLabel = (k: string) => catalog.entities.find((e) => e.key === k)?.label ?? k;

  return (
    <div className={CARD}>
      {notice && <p className="text-sm text-slate-300 bg-slate-900/40 rounded-lg px-3 py-2 mb-4">{notice}</p>}
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-slate-700/50 text-xs font-semibold text-slate-400 tracking-wider">
            <th className="py-2">Report</th><th className="py-2">Data</th><th className="py-2">Visibility</th>
            <th className="py-2">Emailed</th><th />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/40">
          {reports.map((r) => (
            <tr key={r.id}>
              <td className="py-2.5 pr-4">
                <button className="text-sm font-medium text-slate-200 hover:text-indigo-400 text-left" onClick={() => onOpen(r)}>{r.name}</button>
                {r.description && <p className="text-xs text-slate-500">{r.description}</p>}
              </td>
              <td className="py-2.5 text-sm text-slate-400">{entityLabel(r.definition.entity)}</td>
              <td className="py-2.5 text-sm text-slate-400">
                <span className="inline-flex items-center gap-1.5">
                  {r.shared ? <><Users className="w-3.5 h-3.5" /> Shared</> : <><Lock className="w-3.5 h-3.5" /> Private</>}
                  {r.pinned && <span className="ml-2 inline-flex items-center gap-1 text-indigo-400"><Pin className="w-3.5 h-3.5" /> Dashboard</span>}
                </span>
              </td>
              <td className="py-2.5 text-sm text-slate-400">
                {r.schedule_cron ? (
                  <>
                    <span className="inline-flex items-center gap-1.5 text-slate-300"><CalendarClock className="w-3.5 h-3.5" />{scheduleLabel(r.schedule_cron)}</span>
                    <span className="block text-xs text-slate-500">{r.recipients.length} recipient{r.recipients.length === 1 ? '' : 's'}
                      {r.last_sent_at && ` · last ${format(new Date(r.last_sent_at), 'PP p')}`}</span>
                    {r.last_status?.startsWith('failed') && <span className="block text-xs text-rose-400">{r.last_status}</span>}
                  </>
                ) : '—'}
              </td>
              <td className="py-2.5 text-right whitespace-nowrap">
                <button className={ICON_BTN} title="Open" onClick={() => onOpen(r)}><FolderOpen className="w-4 h-4" /></button>
                <button className={ICON_BTN} title="Download Excel" onClick={() => download(r)}><Download className="w-4 h-4" /></button>
                {r.can_edit && (
                  <>
                    <button className={ICON_BTN} title={r.pinned ? 'Unpin from dashboard' : 'Pin to dashboard'} onClick={() => pin.mutate(r)}>
                      {r.pinned ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />}
                    </button>
                    <button className={ICON_BTN} title={r.shared ? 'Make private' : 'Share with everyone'} onClick={() => share.mutate(r)}>
                      {r.shared ? <Lock className="w-4 h-4" /> : <Users className="w-4 h-4" />}
                    </button>
                  </>
                )}
                {isAdmin && (
                  <>
                    <button className={ICON_BTN} title="Email on a schedule" onClick={() => setScheduling(r)}><Mail className="w-4 h-4" /></button>
                    <button className={ICON_BTN} title="Email now" disabled={!r.recipients.length || send.isPending} onClick={() => send.mutate(r.id)}><Send className="w-4 h-4" /></button>
                  </>
                )}
                {r.can_edit && (
                  <button className={ICON_BTN} title="Delete" onClick={() => window.confirm(`Delete "${r.name}"?`) && remove.mutate(r.id)}>
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </td>
            </tr>
          ))}
          {!isLoading && reports.length === 0 && (
            <tr><td colSpan={5} className="py-10 text-center text-sm text-slate-500">
              No saved reports yet. Open one from the library or build your own, then save it.
            </td></tr>
          )}
        </tbody>
      </table>
      {scheduling && <ScheduleModal report={scheduling} onClose={() => setScheduling(null)} />}
    </div>
  );
}
