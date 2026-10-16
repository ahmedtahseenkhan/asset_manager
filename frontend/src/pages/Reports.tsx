import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getReportCatalog, getReportLibrary, getSavedReports } from '../api';
import type { LibraryReport, SavedReport } from '../types';
import { errorText } from '../lib/errors';
import ReportsOverview from '../components/reports/Overview';
import Builder, { type Draft } from '../components/reports/Builder';
import { emptyDefinition } from '../components/reports/definition';
import { LibraryTab, SavedTab } from '../components/reports/Lists';
import { BarChart3, BookOpen, FolderOpen, LayoutDashboard, SlidersHorizontal } from 'lucide-react';
import clsx from 'clsx';

const TABS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'library', label: 'Library', icon: BookOpen },
  { id: 'saved', label: 'Saved reports', icon: FolderOpen },
  { id: 'builder', label: 'Builder', icon: SlidersHorizontal },
] as const;
type Tab = (typeof TABS)[number]['id'];

export default function Reports() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get('tab') as Tab) || 'overview');
  const [draft, setDraft] = useState<Draft | null>(null);

  const { data: catalogRes, error: catalogError } = useQuery({ queryKey: ['report-catalog'], queryFn: getReportCatalog, staleTime: Infinity, retry: false });
  const { data: libraryRes } = useQuery({ queryKey: ['report-library'], queryFn: getReportLibrary, staleTime: Infinity, retry: false });
  const catalog = catalogRes?.data;
  const library = libraryRes?.data ?? [];

  // Deep links from the dashboard: /reports?saved=12
  const savedParam = params.get('saved');
  const { data: savedRes } = useQuery({ queryKey: ['saved-reports'], queryFn: getSavedReports, enabled: !!savedParam && !!catalog });
  useEffect(() => {
    if (!savedParam || !savedRes) return;
    const r = savedRes.data.find((x) => String(x.id) === savedParam);
    if (r) openSaved(r);
    setParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedParam, savedRes]);

  const openLibrary = (r: LibraryReport) => {
    setDraft({ definition: { ...r.definition }, name: r.name, description: r.description });
    setTab('builder');
  };
  const openSaved = (r: SavedReport) => {
    setDraft({ definition: { ...r.definition }, name: r.name, description: r.description, savedId: r.id, canEdit: r.can_edit });
    setTab('builder');
  };
  const startBlank = () => {
    if (!catalog) return;
    const e = catalog.entities.find((x) => x.key === 'devices') ?? catalog.entities[0];
    setDraft({ definition: emptyDefinition(e), name: 'New report' });
  };
  useEffect(() => {
    if (tab === 'builder' && !draft && catalog) startBlank();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, catalog]);

  const unlicensed = catalogError && (catalogError as { response?: { status?: number } }).response?.status === 403;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-50 flex items-center gap-3">
            <BarChart3 className="w-8 h-8 text-indigo-400" /> Reports
          </h1>
          <p className="text-slate-400 mt-1">Ready-made and custom reports over devices, software, security and assets — export to Excel or email on a schedule.</p>
        </div>
        {tab === 'builder' && (
          <button onClick={startBlank} className="px-3 py-2 text-sm text-slate-300 hover:text-slate-50 rounded-lg border border-slate-700">New blank report</button>
        )}
      </div>

      <div className="flex gap-1 border-b border-slate-700/60">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className={clsx('inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px',
              tab === id ? 'border-indigo-500 text-slate-50' : 'border-transparent text-slate-400 hover:text-slate-200')}>
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <ReportsOverview />}
      {tab !== 'overview' && unlicensed && (
        <p className="text-sm text-slate-400 bg-slate-800/60 border border-slate-700/60 rounded-xl p-4">
          The report builder needs the <b>reporting</b> licence module. {errorText(catalogError)}
        </p>
      )}
      {tab === 'library' && catalog && <LibraryTab library={library} catalog={catalog} onOpen={openLibrary} />}
      {tab === 'saved' && catalog && <SavedTab catalog={catalog} onOpen={openSaved} />}
      {tab === 'builder' && catalog && draft && <Builder catalog={catalog} draft={draft} setDraft={setDraft} />}
    </div>
  );
}
