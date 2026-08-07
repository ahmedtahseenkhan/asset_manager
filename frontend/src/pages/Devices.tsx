import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { getDevices } from '../api';
import type { Device } from '../types';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
} from '@tanstack/react-table';
import type { ColumnDef } from '@tanstack/react-table';
import { Search, ChevronLeft, ChevronRight, Download } from 'lucide-react';
import { format } from 'date-fns';

function exportCsv(devices: Device[]) {
  const headers = ['Hostname', 'FQDN', 'IP Addresses', 'OS', 'OS Version', 'Domain', 'Status', 'Last Seen', 'Sources'];
  const rows = devices.map((d) => [
    d.hostname ?? '',
    d.fqdn ?? '',
    (d.ip_addresses ?? []).join('; '),
    d.os_name ?? '',
    d.os_version ?? '',
    d.domain ?? '',
    d.status,
    d.last_seen ? format(new Date(d.last_seen), 'yyyy-MM-dd HH:mm') : '',
    (d.sources ?? []).map((s) => s.source_name).join('; '),
  ]);

  const csv = [headers, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `devices_${format(new Date(), 'yyyyMMdd_HHmm')}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

const STATUS_STYLES: Record<string, string> = {
  active:   'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
  inactive: 'bg-slate-500/10 text-slate-400 ring-slate-500/20',
  retired:  'bg-rose-500/10 text-rose-400 ring-rose-500/20',
};

export default function Devices() {
  const navigate = useNavigate();

  // Pagination State
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(25);
  
  // Filter state
  const [search, setSearch] = useState("");
  const [osFilter, setOsFilter] = useState("");
  
  // Create a separate state for the submitted search query
  const [submittedSearch, setSubmittedSearch] = useState("");

  const { data: res, isLoading: loading } = useQuery({
    queryKey: ['devices', page, size, osFilter, submittedSearch],
    queryFn: () => getDevices(page, size, { search: submittedSearch, os_name: osFilter }),
  });
  
  const data = res?.data.items || [];
  const total = res?.data.total || 0;

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSubmittedSearch(search);
    setPage(1);
  };

  const columns = useMemo<ColumnDef<Device>[]>(
    () => [
      {
        header: 'Hostname',
        accessorKey: 'hostname',
        cell: (info) => (
          <div className="font-medium text-slate-200">
            {info.getValue() as string || 'Unknown'}
          </div>
        ),
      },
      {
        header: 'OS Family',
        accessorKey: 'os_name',
        cell: (info) => {
            const val = info.getValue() as string;
            if(!val) return <span className="text-slate-500">-</span>;
            return (
                <span className="inline-flex items-center rounded-md bg-indigo-500/10 px-2 py-1 text-xs font-medium text-indigo-400 ring-1 ring-inset ring-indigo-500/20">
                    {val} {info.row.original.os_version}
                </span>
            )
        }
      },
      {
        header: 'IP Addresses',
        accessorKey: 'ip_addresses',
        cell: (info) => {
            const ips = info.getValue() as string[];
            if (!ips || ips.length === 0) return <span className="text-slate-500">-</span>;
            return <div className="text-sm text-slate-300">{ips[0]}{ips.length > 1 ? ` (+${ips.length - 1})` : ''}</div>
        }
      },
      {
        header: 'Last Seen',
        accessorKey: 'last_seen',
        cell: (info) => {
            const val = info.getValue() as string;
            if (!val) return <span className="text-slate-500">Never</span>;
            return <span className="text-sm text-slate-300">{format(new Date(val), 'MMM d, yyyy HH:mm')}</span>
        }
      },
      {
        header: 'Status',
        accessorKey: 'status',
        cell: (info) => {
          const val = (info.getValue() as string) ?? 'active';
          const style = STATUS_STYLES[val] ?? STATUS_STYLES.active;
          return (
            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ring-1 ring-inset capitalize ${style}`}>
              {val}
            </span>
          );
        },
      },
      {
        header: 'Sources',
        accessorKey: 'sources',
        cell: (info) => {
            const sources = info.row.original.sources;
            return (
                <div className="flex gap-1">
                    {sources.map(s => (
                        <span key={s.source_name} className="px-1.5 py-0.5 rounded text-[10px] uppercase font-bold bg-slate-700 text-slate-300 pointer-events-none">
                            {s.source_name}
                        </span>
                    ))}
                </div>
            )
        }
      }
    ],
    []
  );

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
  });

  const totalPages = Math.ceil(total / size);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Device Inventory</h1>
          <p className="text-slate-400 mt-1">Unified view of all IT assets discovered across {total} records.</p>
        </div>
        
        <button
          onClick={() => exportCsv(data)}
          disabled={data.length === 0}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-700 text-slate-200 rounded-lg transition-colors"
        >
            <Download className="w-4 h-4" />
            Export CSV
        </button>
      </div>

      <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl overflow-hidden">
        {/* Toolbar */}
        <div className="p-4 border-b border-slate-700/50 flex flex-col sm:flex-row gap-4 justify-between bg-slate-800/50">
          <form onSubmit={handleSearch} className="flex-1 max-w-md relative flex gap-2">
            <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                <input
                type="text"
                placeholder="Search hostnames, IPs..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
            </div>
            <button type="submit" className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-colors">
                Search
            </button>
          </form>

          <div className="flex gap-2">
            <select
              className="bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500"
              value={osFilter}
              onChange={(e) => { setOsFilter(e.target.value); setPage(1); }}
            >
              <option value="">All OS Families</option>
              <option value="Windows">Windows</option>
              <option value="Linux">Linux</option>
              <option value="macOS">macOS</option>
            </select>
            <select
              className="bg-slate-900/50 border border-slate-700 rounded-lg text-sm text-slate-200 px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-500"
              value={size}
              onChange={(e) => { setSize(Number(e.target.value)); setPage(1); }}
            >
              <option value={10}>10 per page</option>
              <option value={25}>25 per page</option>
              <option value={50}>50 per page</option>
              <option value={100}>100 per page</option>
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id} className="border-b border-slate-700/50 bg-slate-800/30">
                  {headerGroup.headers.map((header) => (
                    <th key={header.id} className="px-6 py-4 text-xs font-semibold text-slate-400 tracking-wider">
                      {flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {loading ? (
                <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-slate-500">
                        <div className="animate-spin w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full mx-auto mb-4"></div>
                        Loading devices...
                    </td>
                </tr>
              ) : table.getRowModel().rows.length === 0 ? (
                <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-slate-500">
                        No devices found matching your criteria.
                    </td>
                </tr>
              ) : (
                table.getRowModel().rows.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => navigate(`/devices/${row.original.id}`)}
                    className="hover:bg-slate-800/40 transition-colors cursor-pointer"
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-6 py-4 whitespace-nowrap">
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext()
                        )}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Info */}
        <div className="px-6 py-4 border-t border-slate-700/50 flex items-center justify-between bg-slate-800/30">
            <span className="text-sm text-slate-400">
                Showing {total === 0 ? 0 : (page - 1) * size + 1} to {Math.min(page * size, total)} of {total} results
            </span>
            <div className="flex gap-2">
                <button 
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1 || loading}
                    className="p-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed border border-slate-700 rounded-lg transition-colors text-slate-300"
                >
                    <ChevronLeft className="w-4 h-4" />
                </button>
                <div className="px-4 py-2 border border-slate-700 bg-slate-900/50 rounded-lg text-sm text-slate-300 font-medium">
                    {page} / {totalPages || 1}
                </div>
                <button 
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages || loading}
                    className="p-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed border border-slate-700 rounded-lg transition-colors text-slate-300"
                >
                    <ChevronRight className="w-4 h-4" />
                </button>
            </div>
        </div>
      </div>
    </div>
  );
}
