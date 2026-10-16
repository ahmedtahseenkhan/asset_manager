export const CARD = 'bg-slate-800/80 backdrop-blur-sm p-6 rounded-2xl border border-slate-700/50';
export const INPUT = 'w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/60';
export const SELECT = INPUT;
export const LABEL = 'block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5';
export const BTN_PRIMARY = 'inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg';
export const BTN_GHOST = 'inline-flex items-center gap-2 px-3 py-2 text-sm text-slate-300 hover:text-slate-50 rounded-lg border border-slate-700 disabled:opacity-50';
export const ICON_BTN = 'p-1.5 text-slate-500 hover:text-slate-50 rounded disabled:opacity-40';

export const SCHEDULE_PRESETS = [
  { label: 'Every day at 07:00', cron: '0 7 * * *' },
  { label: 'Every Monday at 07:00', cron: '0 7 * * 1' },
  { label: 'First day of the month at 07:00', cron: '0 7 1 * *' },
];

export function scheduleLabel(cron: string | null): string {
  if (!cron) return '—';
  return SCHEDULE_PRESETS.find((p) => p.cron === cron)?.label ?? cron;
}
