import type { ActionItemSummary } from './api';

type OperationalActionItem = Pick<ActionItemSummary, 'official_status'> & {
  deleted_at?: string | null;
};

export function isOperationalActionItem(item: OperationalActionItem): boolean {
  const notDeleted = item.deleted_at === null || item.deleted_at === undefined;
  return notDeleted && item.official_status !== 'SELESAI';
}
