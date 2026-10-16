import { format, parseISO } from 'date-fns';

/** "14 Oct 2025" from a YYYY-MM-DD date (parsed as a local date, not UTC midnight). */
export const fmtDay = (d: string | null | undefined) => (d ? format(parseISO(d), 'd MMM yyyy') : '—');

function span(days: number): string {
  const n = Math.abs(days);
  if (n < 45) return `${n} day${n === 1 ? '' : 's'}`;
  if (n < 548) return `${Math.round(n / 30.4)} months`;
  const years = Math.round(n / 365.25 * 10) / 10;
  return `${years} year${years === 1 ? '' : 's'}`;
}

/** "ended 1 year ago", "ends in 30 days", "no end date announced". */
export function relative(days: number | null, noun = 'support'): string {
  if (days == null) return `no end of ${noun} announced`;
  if (days < 0) return `ended ${span(days)} ago`;
  if (days === 0) return 'ends today';
  return `ends in ${span(days)}`;
}
