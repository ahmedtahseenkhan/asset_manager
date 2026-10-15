import type { DeviceChange } from '../types';

export const CHANGE_CATEGORY_LABELS: Record<DeviceChange['category'], string> = {
  software: 'Software', patch: 'Updates', hardware: 'Hardware', os: 'Operating system',
  account: 'Accounts', security: 'Security', service: 'Services', monitor: 'Monitors',
};

/** One-line summary of a change, phrased for people (mirrors describe_change on the server). */
export function describeChange(c: DeviceChange): string {
  if (c.category === 'account') {
    if (c.change_type === 'added') return `New local ${c.new_value === 'admin' ? 'admin' : 'account'} ${c.item}`;
    if (c.field === 'admin') return `${c.item} ${c.new_value === 'yes' ? 'became' : 'is no longer'} a local admin`;
    if (c.field === 'enabled') return `${c.item} ${c.new_value === 'yes' ? 'enabled' : 'disabled'}`;
    if (c.change_type === 'removed') return `Account ${c.item} removed`;
  }
  if (c.field === 'enabled') return `${c.item} ${c.new_value === 'yes' ? 'enabled' : 'disabled'}`;
  if (c.field === 'encrypted') return `${c.item} ${c.new_value === 'yes' ? 'encrypted' : 'no longer encrypted'}`;
  if (c.category === 'software') {
    if (c.change_type === 'changed') return `${c.item} updated ${c.old_value ?? '?'} → ${c.new_value ?? '?'}`;
    return `${c.item}${c.new_value ? ` ${c.new_value}` : c.old_value ? ` ${c.old_value}` : ''} ${c.change_type === 'added' ? 'installed' : 'uninstalled'}`;
  }
  if (c.category === 'patch') return `Update ${c.item} ${c.change_type === 'added' ? 'installed' : 'removed'}`;
  if (c.change_type === 'changed') return `${c.item}: ${c.old_value ?? '—'} → ${c.new_value ?? '—'}`;
  return `${c.item} ${c.change_type}`;
}
