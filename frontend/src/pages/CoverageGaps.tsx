import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getCoverageGaps } from '../api';
import type { CoverageGapDevice } from '../types';
import { ShieldAlert, RefreshCw, Search, CheckCircle2 } from 'lucide-react';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  getFilteredRowModel,
} from '@tanstack/react-table';
import type { ColumnDef } from '@tanstack/react-table';

const SOURCE_COLORS: Record<string, string> = {
  ad:          'bg-blue-500/20 text-blue-400 ring-blue-500/30',
  crowdstrike: 'bg-red-500/20 text-red-400 ring-red-500/30',
  defender:    'bg-cyan-500/20 text-cyan-400 ring-cyan-500/30',
  mcafee:      'bg-orange-500/20 text-orange-400 ring-orange-500/30',
  symantec:    'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
  mock:        'bg-slate-500/20 text-slate-400 ring-slate-500/30',
};

function SourceBadge({ name, variant = 'known' }: { name: string; variant?: 'known' | 'missing' }) {
  const base = SOURCE_COLORS[name] ?? 'bg-purple-500/20 text-purple-400 ring-purple-500/30';
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset mr-1
        ${variant === 'missing' ? 'opacity-40 line-through' : ''} ${base}`}
    >
      {name}
    </span>
  );
}

export default function CoverageGaps() {
  const [search, setSearch] = useState('');
  const [filterSource, setFilterSource] = useState('');

  const { data: res, isLoading, refetch } = useQuery({
    queryKey: ['coverage-gaps'],
    queryFn: getCoverageGaps,
  });

  const summary = res?.data;

  const filteredGaps = useMemo(() => {
    if (!summary?.gaps) return [];
    return summary.gaps.filter((g) => {
      const matchSearch =
        !search ||
        g.hostname?.toLowerCase().includes(search.toLowerCase()) ||
        g.fqdn?.toLowerCase().includes(search.toLowerCase()) ||
        g.ip_addresses.some((ip) => ip.includes(search));
      const matchSource =
        !filterSource || g.missing_sources.includes(filterSource);
      return matchSearch && matchSource;
    });
  }, [summary?.gaps, search, filterSource]);

  const columns = useMemo<ColumnDef<CoverageGapDevice>[]>(
    () => [
      {
        header: 'Hostname',
        accessorKey: 'hostname',
        cell: (info) => (
          <div className="font-medium text-slate-200">
            {(info.getValue() as string) || <span className="text-slate-500">Unknown</span>}
          </div>
        ),
      },
      {
        header: 'IP Address',
        accessorKey: 'ip_addresses',
        cell: (info) => {
          const ips = info.getValue() as string[];
          if (!ips?.length) return <span className="text-slate-500">—</span>;
          return <span className="text-sm text-slate-300">{ips[0]}{ips.length > 1 ? ` +${ips.length - 1}` : ''}</span>;
        },
      },
      {
        header: 'OS',
        accessorKey: 'os_name',
        cell: (info) => {
          const val = info.getValue() as string;
          if (!val) return <span className="text-slate-500">—</span>;
          return (
            <span className="px-2 py-0.5 rounded-md bg-indigo-500/10 text-xs font-medium text-indigo-400 ring-1 ring-inset ring-indigo-500/20">
              {val}
            </span>
          );
        },
      },
      {
        header: 'Seen In',
        accessorKey: 'known_sources',
        cell: (info) => {
          const sources = info.getValue() as string[];
          return (
            <div className="flex flex-wrap gap-0.5">
              {sources.map((s) => <SourceBadge key={s} name={s} />)}
            </div>
          );
        },
      },
      {
        header: 'Missing From',
        accessorKey: 'missing_sources',
        cell: (info) => {
          const sources = info.getValue() as string[];
          return (
            <div className="flex flex-wrap gap-0.5">
              {sources.map((s) => (
                <span
                  key={s}
                  className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ring-1 ring-inset mr-1 bg-rose-500/20 text-rose-400 ring-rose-500/30"
                >
                  {s}
                </span>
              ))}
            </div>
          );
        },
      },
    ],
    []
  );

  const table = useReactTable({
    data: filteredGaps,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400">
        <div className="text-center space-y-3">
          <div className="animate-spin w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full mx-auto" />
          <p>Analysing coverage gaps…</p>
        </div>
      </div>
    );
  }

  if (!summary) {
    return <div className="text-rose-400 p-6">Failed to load coverage gap data.</div>;
  }

  const coveragePct =
    summary.total_active_devices > 0
      ? Math.round(((summary.total_active_devices - summary.devices_with_gaps) / summary.total_active_devices) * 100)
      : 100;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
            <ShieldAlert className="w-8 h-8 text-rose-400" />
            Coverage Gaps
          </h1>
          <p className="text-slate-400 mt-1">
            Active devices missing from one or more enabled security tools.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="p-2 bg-slate-800 rounded-lg hover:bg-slate-700 transition-colors"
        >
          <RefreshCw className="w-5 h-5 text-slate-300" />
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-800/80 backdrop-blur-sm p-5 rounded-2xl border border-slate-700/50">
          <p className="text-sm text-slate-400">Active Devices</p>
          <p className="text-3xl font-bold text-slate-50 mt-1">{summary.total_active_devices}</p>
        </div>
        <div className="bg-slate-800/80 backdrop-blur-sm p-5 rounded-2xl border border-rose-500/20">
          <p className="text-sm text-slate-400">Devices With Gaps</p>
          <p className="text-3xl font-bold text-rose-400 mt-1">{summary.devices_with_gaps}</p>
        </div>
        <div className="bg-slate-800/80 backdrop-blur-sm p-5 rounded-2xl border border-slate-700/50">
          <p className="text-sm text-slate-400">Coverage</p>
          <p className={`text-3xl font-bold mt-1 ${coveragePct >= 95 ? 'text-emerald-400' : coveragePct >= 80 ? 'text-yellow-400' : 'text-rose-400'}`}>
            {coveragePct}%
          </p>
        </div>
        <div className="bg-slate-800/80 backdrop-blur-sm p-5 rounded-2xl border border-slate-700/50">
          <p className="text-sm text-slate-400">Enabled Sources</p>
          <div className="flex flex-wrap gap-1 mt-2">
            {summary.enabled_sources.length === 0 ? (
              <span className="text-slate-500 text-sm">None configured</span>
            ) : (
              summary.enabled_sources.map((s) => <SourceBadge key={s} name={s} />)
            )}
          </div>
        </div>
      </div>

      {/* Per-source gap breakdown */}
      {summary.missing_per_source.length > 0 && (
        <div className="bg-slate-800/80 backdrop-blur-sm p-5 rounded-2xl border border-slate-700/50">
          <h2 className="text-sm font-semibold text-slate-300 mb-4">Unmanaged Devices per Source</h2>
          <div className="space-y-3">
            {summary.missing_per_source.map(({ source, count }) => {
              const pct = summary.total_active_devices > 0
                ? Math.round((count / summary.total_active_devices) * 100)
                : 0;
              return (
                <div key={source} className="flex items-center gap-4">
                  <div className="w-28 shrink-0">
                    <SourceBadge name={source} />
                  </div>
                  <div className="flex-1 bg-slate-700/50 rounded-full h-2 overflow-hidden">
                    <div
                      className="h-full bg-rose-500 rounded-full transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-sm text-slate-300 w-24 text-right">
                    {count} device{count !== 1 ? 's' : ''} ({pct}%)
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* No gaps state */}
      {summary.devices_with_gaps === 0 ? (
        <div className="bg-slate-800/80 backdrop-blur-sm rounded-2xl border border-emerald-500/20 p-12 text-center">
          <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto mb-4" />
          <p className="text-xl font-semibold text-slate-50">Full Coverage</p>
          <p className="text-slate-400 mt-2">All active devices are covered by every enabled security tool.</p>
        </div>
      ) : (
        <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl overflow-hidden">
          {/* Toolbar */}
          <div className="p-4 border-b border-slate-700/50 flex flex-col sm:flex-row gap-3 bg-slate-800/50">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input
                type="text"
                placeholder="Filter by hostname or IP…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <select
              value={filterSource}
              onChange={(e) => setFilterSource(e.target.value)}
              className="bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">All missing sources</option>
              {summary.enabled_sources.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <span className="self-center text-sm text-slate-400 shrink-0">
              {filteredGaps.length} device{filteredGaps.length !== 1 ? 's' : ''}
            </span>
          </div>

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id} className="border-b border-slate-700/50 bg-slate-800/30">
                    {hg.headers.map((h) => (
                      <th key={h.id} className="px-6 py-4 text-xs font-semibold text-slate-400 tracking-wider">
                        {flexRender(h.column.columnDef.header, h.getContext())}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {table.getRowModel().rows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-12 text-center text-slate-500">
                      No devices match the current filter.
                    </td>
                  </tr>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <tr key={row.id} className="hover:bg-slate-800/40 transition-colors">
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-6 py-4 whitespace-nowrap">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
