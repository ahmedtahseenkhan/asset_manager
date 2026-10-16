import clsx from 'clsx';
import type { EolStatus } from '../../types';

const STATUS: Record<EolStatus, { label: string; cls: string }> = {
  unsupported: { label: 'Out of support', cls: 'bg-rose-500/15 text-rose-400 ring-rose-500/30' },
  ending_soon: { label: 'Ending soon', cls: 'bg-amber-500/15 text-amber-400 ring-amber-500/30' },
  supported: { label: 'Supported', cls: 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30' },
};

export function EolBadge({ status }: { status: EolStatus }) {
  const s = STATUS[status];
  return (
    <span className={clsx('inline-flex px-2 py-0.5 rounded-full text-[11px] font-semibold ring-1 ring-inset whitespace-nowrap', s.cls)}>
      {s.label}
    </span>
  );
}
