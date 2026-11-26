import { describe, expect, it } from 'vitest';
import { isOperationalActionItem } from './actionItemVisibility';

describe('isOperationalActionItem', () => {
  it('keeps an unfinished task when an older API response omits deleted_at', () => {
    expect(isOperationalActionItem({ official_status: 'BERPROSES' })).toBe(true);
  });

  it('keeps an unfinished task when deleted_at is explicitly null', () => {
    expect(isOperationalActionItem({ official_status: 'BELUM_DIMULAI', deleted_at: null })).toBe(
      true,
    );
  });

  it('hides completed and soft-deleted tasks from operational lists', () => {
    expect(isOperationalActionItem({ official_status: 'SELESAI', deleted_at: null })).toBe(false);
    expect(
      isOperationalActionItem({
        official_status: 'BERPROSES',
        deleted_at: '2026-11-24T10:00:00Z',
      }),
    ).toBe(false);
  });
});
