import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import NotificationCenter from './NotificationCenter';

const notification = {
  id: '51000000-0000-4000-8000-000000000001',
  notification_type: 'ACTION_ITEM_STATUS_CHANGED' as const,
  message: 'Status tindak lanjut yang Anda ikuti telah berubah.',
  target_type: 'ACTION_ITEM' as const,
  target_id: '40000000-0000-4000-8000-000000000001',
  created_at: '2026-11-25T10:00:00Z',
  read_at: null,
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
});

describe('NotificationCenter', () => {
  it('shows private notifications, links only to authorized target objects, and marks them read', async () => {
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/notifications?limit=50') {
        return jsonResponse({ items: [notification], unread_count: 1 });
      }
      if (url === `/api/v1/notifications/${notification.id}/read` && init?.method === 'POST') {
        return jsonResponse({ ...notification, read_at: '2026-11-25T10:05:00Z' });
      }
      throw new Error(`Unexpected notification request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<NotificationCenter />);

    const toggle = await screen.findByRole('button', { name: 'Notifikasi (1 belum dibaca)' });
    fireEvent.click(toggle);
    const panel = screen.getByRole('region', { name: 'Pusat notifikasi' });
    expect(
      within(panel).getByRole('link', {
        name: 'Status tindak lanjut yang Anda ikuti telah berubah.',
      }),
    ).toHaveAttribute('href', `#action-items/${notification.target_id}`);
    expect(within(panel).queryByText(/Rapat|Notulensi|Decision Brief/)).not.toBeInTheDocument();

    fireEvent.click(within(panel).getByRole('button', { name: 'Tandai dibaca' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Notifikasi' })).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/notifications/${notification.id}/read`,
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    );
  });
});
