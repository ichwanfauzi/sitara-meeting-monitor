import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AuthenticatedUser, MeetingSummary } from './api';
import SearchPage from './SearchPage';

const secretary: AuthenticatedUser = {
  id: '20000000-0000-4000-8000-000000000001',
  email: 'sekretariat@example.test',
  full_name: 'Sekretariat Uji',
  roles: ['SEKRETARIAT'],
};

const meetings: MeetingSummary[] = [
  {
    id: '30000000-0000-4000-8000-000000000001',
    meeting_number: 'RAPIM-2026-011',
    title: 'Rapim November',
    meeting_date: '2026-11-20',
    status: 'FINAL',
    version: 1,
    agendas: [],
  },
  {
    id: '30000000-0000-4000-8000-000000000002',
    meeting_number: 'RAPIM-2026-012',
    title: 'Rapim Desember',
    meeting_date: '2026-12-05',
    status: 'ARCHIVED',
    version: 1,
    agendas: [],
  },
];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

describe('SearchPage repository filters', () => {
  it('uses the shared meeting-page layout for repository meetings', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input) === '/api/v1/meetings?limit=100&offset=0') {
          return Response.json(meetings);
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );
    render(<SearchPage authenticatedUser={secretary} />);

    const meetingLink = await screen.findByRole('link', { name: /Rapim November/ });
    expect(
      screen.getByRole('heading', { name: 'Repository Rapim' }).closest('.repository-page'),
    ).toHaveClass('meeting-list-page');
    expect(meetingLink.closest('.meeting-list')).not.toBeNull();
    expect(meetingLink.closest('.meeting-list-row')).toBeVisible();
  });

  it('filters meetings by month and year together', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input) === '/api/v1/meetings?limit=100&offset=0') {
          return Response.json(meetings);
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );
    render(<SearchPage authenticatedUser={secretary} />);

    expect(await screen.findByText(/Rapim November/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Bulan rapat' }), {
      target: { value: '2026-11' },
    });

    expect(screen.getByText(/Rapim November/)).toBeInTheDocument();
    expect(screen.queryByText(/Rapim Desember/)).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'November 2026' })).toBeInTheDocument();
  });

  it('clears repository search and month filters together', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input) === '/api/v1/meetings?limit=100&offset=0') {
          return Response.json(meetings);
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );
    render(<SearchPage authenticatedUser={secretary} />);

    await screen.findByText(/Rapim November/);
    fireEvent.change(screen.getByRole('combobox', { name: 'Bulan rapat' }), {
      target: { value: '2026-11' },
    });
    fireEvent.change(screen.getByRole('searchbox', { name: 'Cari rapat' }), {
      target: { value: 'Rapim Desember' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Hapus filter' }));

    expect(screen.getByRole('searchbox', { name: 'Cari rapat' })).toHaveValue('');
    expect(screen.getByRole('combobox', { name: 'Bulan rapat' })).toHaveValue('SEMUA');
    expect(screen.getByText(/Rapim November/)).toBeInTheDocument();
    expect(screen.getByText(/Rapim Desember/)).toBeInTheDocument();
  });
});
