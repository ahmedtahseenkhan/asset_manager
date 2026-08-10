import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getUnlinkedDevices, adoptDevices, linkDevice } from '../api';
import { ArrowLeft, GitMerge, Link2, PackagePlus } from 'lucide-react';
import { format } from 'date-fns';
import { useAuth } from '../context/AuthContext';

export default function Reconciliation() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canEdit = user?.role === 'admin' || user?.role === 'asset_manager';
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const { data: res, isLoading } = useQuery({
    queryKey: ['unlinked-devices'],
    queryFn: getUnlinkedDevices,
  });
  const devices = res?.data ?? [];

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['unlinked-devices'] });
    queryClient.invalidateQueries({ queryKey: ['assets'] });
    queryClient.invalidateQueries({ queryKey: ['license'] });
  };

  const onError = (err: unknown) => {
    const data = (err as { response?: { data?: { detail?: unknown; message?: string } } })?.response?.data;
    const detail = typeof data?.detail === 'string' ? data.detail : data?.message;
    setMessage({ ok: false, text: detail ?? 'Operation failed' });
  };

  const adopt = useMutation({
    mutationFn: (ids: number[]) => adoptDevices(ids),
    onSuccess: (r) => {
      setMessage({ ok: true, text: r.message });
      setSelected(new Set());
      invalidate();
    },
    onError,
  });

  const link = useMutation({
    mutationFn: ({ deviceId, assetId }: { deviceId: number; assetId: number }) =>
      linkDevice(deviceId, assetId),
    onSuccess: (r) => {
      setMessage({ ok: true, text: r.message });
      invalidate();
    },
    onError,
  });

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next);
  };
  const allSelected = devices.length > 0 && selected.size === devices.length;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/assets" className="p-2 bg-slate-800 rounded-lg hover:bg-slate-700 transition-colors">
          <ArrowLeft className="w-5 h-5 text-slate-300" />
        </Link>
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
            <GitMerge className="w-8 h-8 text-indigo-400" />
            Device Reconciliation
          </h1>
          <p className="text-slate-400 mt-1">
            Discovered devices that are not yet in the asset register. Adopt them to create
            asset records, or link them to an existing asset.
          </p>
        </div>
      </div>

      {message && (
        <p className={`text-sm ${message.ok ? 'text-emerald-400' : 'text-rose-400'}`}>{message.text}</p>
      )}

      <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl overflow-hidden">
        {canEdit && devices.length > 0 && (
          <div className="p-4 border-b border-slate-700/50 bg-slate-800/50 flex items-center justify-between">
            <span className="text-sm text-slate-400">{selected.size} of {devices.length} selected</span>
            <button
              disabled={selected.size === 0 || adopt.isPending}
              onClick={() => adopt.mutate([...selected])}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              <PackagePlus className="w-4 h-4" />
              {adopt.isPending ? 'Adopting…' : `Adopt ${selected.size || ''} selected`}
            </button>
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-800/30 text-xs font-semibold text-slate-400 tracking-wider">
                {canEdit && (
                  <th className="px-6 py-4 w-10">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={() => setSelected(allSelected ? new Set() : new Set(devices.map((d) => d.id)))}
                      className="accent-indigo-500"
                    />
                  </th>
                )}
                <th className="px-6 py-4">Hostname</th>
                <th className="px-6 py-4">OS</th>
                <th className="px-6 py-4">IP</th>
                <th className="px-6 py-4">Last seen</th>
                <th className="px-6 py-4">Suggested match</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {isLoading ? (
                <tr><td colSpan={6} className="px-6 py-12 text-center text-slate-500">Loading…</td></tr>
              ) : devices.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-emerald-400">
                    All discovered devices are reconciled with the asset register. 🎉
                  </td>
                </tr>
              ) : devices.map((d) => (
                <tr key={d.id} className="hover:bg-slate-800/40 transition-colors">
                  {canEdit && (
                    <td className="px-6 py-4">
                      <input type="checkbox" checked={selected.has(d.id)} onChange={() => toggle(d.id)} className="accent-indigo-500" />
                    </td>
                  )}
                  <td className="px-6 py-4 font-medium text-slate-200">{d.hostname ?? d.fqdn ?? `#${d.id}`}</td>
                  <td className="px-6 py-4 text-sm text-slate-400">{d.os_name ?? '—'}</td>
                  <td className="px-6 py-4 text-sm text-slate-400">{d.ip_addresses?.[0] ?? '—'}</td>
                  <td className="px-6 py-4 text-sm text-slate-400">
                    {d.last_seen ? format(new Date(d.last_seen), 'PP') : '—'}
                  </td>
                  <td className="px-6 py-4">
                    {d.suggested_asset ? (
                      <button
                        disabled={!canEdit || link.isPending}
                        onClick={() => link.mutate({ deviceId: d.id, assetId: d.suggested_asset!.id })}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 rounded-lg ring-1 ring-inset ring-emerald-500/30 transition-colors"
                        title={`Link to ${d.suggested_asset.name}`}
                      >
                        <Link2 className="w-3.5 h-3.5" />
                        Link to {d.suggested_asset.asset_tag}
                      </button>
                    ) : (
                      <span className="text-sm text-slate-600">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
