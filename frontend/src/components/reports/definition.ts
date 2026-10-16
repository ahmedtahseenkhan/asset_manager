import { format } from 'date-fns';
import type { ReportDefinition, ReportEntity } from '../../types';

export function emptyDefinition(entity: ReportEntity): ReportDefinition {
  return { entity: entity.key, columns: [...entity.default_columns], filters: [], match: 'all',
           group_by: null, sort: entity.default_sort, sort_dir: 'asc', chart: 'none' };
}

/** Display text for a report cell by field type. */
export function formatCell(value: unknown, type: string): string {
  if (value === null || value === undefined || value === '') return '—';
  if (type === 'bool') return value ? 'Yes' : 'No';
  if (type === 'date' && typeof value === 'string') return format(new Date(`${value}T00:00:00`), 'PP');
  if (type === 'datetime' && typeof value === 'string') return format(new Date(value), 'PP p');
  if (type === 'number' && typeof value === 'number') return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}
