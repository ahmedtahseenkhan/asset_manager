import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getDeviceLifecycle } from '../../api';
import { EolBadge } from './ui';
import { fmtDay, relative } from '../../lib/lifecycle';
import { CalendarClock } from 'lucide-react';
import clsx from 'clsx';

const WARRANTY: Record<string, { label: string; cls: string }> = {
  expired: { label: 'Expired', cls: 'text-rose-400' },
  ending_soon: { label: 'Ending soon', cls: 'text-amber-400' },
  active: { label: 'Active', cls: 'text-emerald-400' },
};

/** OS end of support, warranty of the linked asset, and installed software past or near end of support. */
export default function DeviceLifecycleCard({ deviceId }: { deviceId: number }) {
  const { data } = useQuery({ queryKey: ['device-lifecycle', deviceId], queryFn: () => getDeviceLifecycle(deviceId) });
  const lc = data?.data;
  if (!lc || (!lc.os && !lc.warranty && lc.software.length === 0)) return null;
  const flagged = lc.software.filter((s) => s.status !== 'supported');
  const fine = lc.software.length - flagged.length;
  const w = lc.warranty;

  return (
    <div className="bg-slate-800/80 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6">
      <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
        <CalendarClock className="w-4 h-4" /> Lifecycle
      </h2>
      <div className="divide-y divide-slate-700/40">
        {lc.os && (
          <div className="py-2.5 flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-slate-200">{lc.os.title}</p>
              <p className="text-xs text-slate-500">
                Security updates {relative(lc.os.days_left)}{lc.os.eol && ` (${fmtDay(lc.os.eol)})`}
                {lc.os.extended && ` · paid extended support until ${fmtDay(lc.os.extended)}`}
              </p>
            </div>
            <EolBadge status={lc.os.status} />
          </div>
        )}
        {w && (
          <div className="py-2.5 flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-slate-200">
                Warranty · <Link to={`/assets/${w.asset_id}`} className="text-indigo-400 hover:text-indigo-300">{w.asset_tag}</Link>
              </p>
              <p className="text-xs text-slate-500">
                {w.warranty_end ? `Ends ${fmtDay(w.warranty_end)}` : 'No warranty end date recorded. Import one on the Lifecycle page.'}
                {w.purchase_date && ` · purchased ${fmtDay(w.purchase_date)}`}
              </p>
            </div>
            {w.status && <span className={clsx('text-sm font-medium', WARRANTY[w.status].cls)}>{WARRANTY[w.status].label}</span>}
          </div>
        )}
        {flagged.map((s) => (
          <div key={`${s.product_id}-${s.cycle}`} className="py-2.5 flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-slate-200">{s.title}</p>
              <p className="text-xs text-slate-500 truncate">
                {s.detail} · support {relative(s.days_left)}{s.eol && ` (${fmtDay(s.eol)})`}
              </p>
            </div>
            <EolBadge status={s.status} />
          </div>
        ))}
        {fine > 0 && (
          <p className="py-2.5 text-xs text-slate-500">
            {fine} other tracked application{fine === 1 ? ' is' : 's are'} supported ({lc.software.filter((s) => s.status === 'supported').map((s) => s.title).join(', ')}).
          </p>
        )}
      </div>
    </div>
  );
}
