import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AuthenticatedUser, MeetingParticipant, MeetingRecord } from './api';
import App from './App';
import MeetingManagement from './MeetingManagement';

const secretary: AuthenticatedUser = {
  id: '20000000-0000-4000-8000-000000000001',
  email: 'sekretariat@example.test',
  full_name: 'Sekretariat Uji',
  roles: ['SEKRETARIAT'],
};

const meeting: MeetingRecord = {
  id: '30000000-0000-4000-8000-000000000001',
  meeting_number: 'RAPIM-2026-030',
  title: 'Rapat Evaluasi Sintetis',
  meeting_type: 'RAPIM',
  meeting_date: '2026-11-20',
  start_time: '09:00:00',
  end_time: '10:30:00',
  location: 'Ruang Uji',
  created_by_id: secretary.id,
  status: 'DRAFT',
  version: 1,
  created_at: '2026-11-01T10:00:00Z',
  updated_at: '2026-11-01T10:00:00Z',
  agendas: [
    {
      id: '31000000-0000-4000-8000-000000000001',
      meeting_id: '30000000-0000-4000-8000-000000000001',
      agenda_number: 1,
      title: 'Evaluasi Program Uji',
      agenda_description: 'Pembahasan sintetis',
      pic_suggestion: null,
      supporting_pic_suggestion: null,
      duration_minutes: 30,
      sort_order: 1,
    },
  ],
  participants: [
    {
      user_id: '20000000-0000-4000-8000-000000000003',
      participant_name: 'Peserta Sintetis',
      participant_title: 'Wakil Rektor',
    },
  ],
  external_participants: [],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    try {
      return Promise.resolve(handler(url, init));
    } catch (error) {
      if (url.endsWith('/dispositions?limit=100&offset=0'))
        return Promise.resolve(jsonResponse([]));
      if (url.endsWith('/notetaker-handovers')) return Promise.resolve(jsonResponse([]));
      throw error;
    }
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
  window.history.replaceState(null, '', '#dashboard');
});

describe('Meeting management', () => {
  it('keeps the meeting search but removes redundant page guidance', async () => {
    stubFetch((url) => {
      if (url.startsWith('/api/v1/meetings?')) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    expect(await screen.findByText('Tidak ada rapat yang cocok.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Daftar rapat' })).toBeVisible();
    expect(screen.getByLabelText('Cari rapat')).toBeVisible();
    expect(screen.queryByText('RAPIM', { selector: '.eyebrow' })).toBeNull();
    expect(screen.queryByText('Cari rapat berdasarkan nomor atau judul.')).toBeNull();
  });

  it('clears the meeting search and reloads the unfiltered first page', async () => {
    const fetchMock = stubFetch((url) => {
      if (url.startsWith('/api/v1/meetings?')) return jsonResponse([meeting]);
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    const searchInput = await screen.findByLabelText('Cari rapat');
    fireEvent.change(searchInput, { target: { value: 'Evaluasi' } });
    expect(await screen.findByRole('button', { name: 'Hapus pencarian rapat' })).toBeVisible();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        '/api/v1/meetings?limit=20&offset=0&query=Evaluasi',
        expect.objectContaining({ credentials: 'include', cache: 'no-store' }),
      ),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Hapus pencarian rapat' }));

    expect(searchInput).toHaveValue('');
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        '/api/v1/meetings?limit=20&offset=0',
        expect.objectContaining({ credentials: 'include', cache: 'no-store' }),
      ),
    );
    expect(
      screen.getByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    ).toBeInTheDocument();
  });

  it('opens the integrated meeting page from authenticated workspace navigation', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch((url) => {
      if (url === '/api/v1/auth/me') return jsonResponse(secretary);
      if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([]);
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([]);
      if (url === '/api/v1/action-items?limit=100&offset=0') return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<App />);

    await user.click(await screen.findByRole('link', { name: 'Rapat' }));
    expect(await screen.findByRole('heading', { name: 'Daftar rapat' })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/meetings?limit=20&offset=0',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('loads the authorized meeting list and paginates with API limit and offset', async () => {
    const fetchMock = stubFetch((url) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') {
        return jsonResponse(
          Array.from({ length: 20 }, (_, index) => ({
            ...meeting,
            id: `30000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
            title: `Rapat Sintetis ${index + 1}`,
          })),
        );
      }
      if (url === '/api/v1/meetings?limit=20&offset=20') return jsonResponse([meeting]);
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    expect(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Sintetis 1' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Halaman 1')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /^Lihat detail Rapat Sintetis/ })).toHaveLength(
      20,
    );
    expect(screen.getAllByText('Draf')).toHaveLength(20);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/meetings?limit=20&offset=0',
      expect.objectContaining({ credentials: 'include', cache: 'no-store' }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Berikutnya' }));
    expect(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/meetings?limit=20&offset=20',
      expect.anything(),
    );
  });

  it('shows an empty state and does not fabricate meetings', async () => {
    stubFetch((url) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    expect(await screen.findByText('Tidak ada rapat yang cocok.')).toBeInTheDocument();
    expect(screen.queryByText('Rapat Evaluasi Sintetis')).not.toBeInTheDocument();
  });

  it('keeps pagination usable when the final page follows a full page', async () => {
    const fetchMock = stubFetch((url) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') {
        return jsonResponse(
          Array.from({ length: 20 }, (_, index) => ({
            ...meeting,
            id: `30000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
            title: `Rapat Sintetis ${index + 1}`,
          })),
        );
      }
      if (url === '/api/v1/meetings?limit=20&offset=20') return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);
    await screen.findByRole('button', { name: 'Lihat detail Rapat Sintetis 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Berikutnya' }));

    expect(await screen.findByText('Tidak ada lagi rapat pada halaman ini.')).toBeInTheDocument();
    const previousButton = screen.getByRole('button', { name: 'Sebelumnya' });
    expect(previousButton).toBeEnabled();
    fireEvent.click(previousButton);
    expect(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Sintetis 1' }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/meetings?limit=20&offset=20',
      expect.anything(),
    );
  });

  it('shows a retryable list error', async () => {
    let failed = true;
    const fetchMock = stubFetch((url) => {
      if (url !== '/api/v1/meetings?limit=20&offset=0') {
        throw new Error(`Unexpected request: ${url}`);
      }
      return failed ? jsonResponse({ detail: 'Unavailable' }, 503) : jsonResponse([meeting]);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Daftar rapat gagal dimuat: Unavailable',
    );
    failed = false;
    fireEvent.click(screen.getByRole('button', { name: 'Coba lagi' }));
    expect(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it('creates a meeting using backend fields and follows with authorized detail', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const notetakerOption = {
      id: '20000000-0000-4000-8000-000000000003',
      full_name: 'Notulis Uji',
      job_title: 'Sekretariat',
      roles: ['SEKRETARIAT'],
    };
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([]);
      if (url === '/api/v1/meetings' && init?.method === 'POST') {
        return jsonResponse({ ...meeting, notetaker_id: notetakerOption.id }, 201);
      }
      if (url === `/api/v1/meetings/${meeting.id}`) return jsonResponse(meeting);
      if (url === '/api/v1/meetings/participant-options') return jsonResponse([notetakerOption]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);
    await user.click(await screen.findByRole('button', { name: 'Buat rapat' }));

    await user.type(screen.getByLabelText('Nomor rapat'), 'RAPIM-2026-030');
    await user.type(screen.getByLabelText('Judul rapat'), meeting.title);
    await user.clear(screen.getByLabelText('Jenis rapat'));
    await user.type(screen.getByLabelText('Jenis rapat'), 'RAPIM');
    await user.type(screen.getByLabelText('Tanggal'), '2026-11-20');
    await user.type(screen.getByLabelText('Waktu mulai'), '09:00');
    await user.type(screen.getByLabelText('Waktu selesai'), '10:30');
    await user.type(screen.getByLabelText('Lokasi atau media'), 'Ruang Uji');
    const notetakerSelect = screen.getByLabelText('Notulis rapat (opsional)');
    expect(
      within(notetakerSelect).getByRole('option', { name: 'Sekretariat' }),
    ).toBeInTheDocument();
    expect(notetakerSelect).not.toHaveTextContent(notetakerOption.full_name);
    await user.selectOptions(notetakerSelect, notetakerOption.id);
    await user.click(screen.getByRole('button', { name: 'Simpan rapat' }));

    expect(await screen.findByRole('heading', { name: meeting.title })).toBeInTheDocument();
    const createCall = fetchMock.mock.calls.find(
      ([url, init]) => url === '/api/v1/meetings' && init?.method === 'POST',
    );
    expect(createCall?.[1]).toMatchObject({
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({
        meeting_number: 'RAPIM-2026-030',
        title: meeting.title,
        meeting_type: 'RAPIM',
        meeting_date: '2026-11-20',
        start_time: '09:00',
        end_time: '10:30',
        location: 'Ruang Uji',
        notetaker_id: notetakerOption.id,
      }),
    });
    expect(new Headers(createCall?.[1]?.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
    expect(screen.getByText(/Evaluasi Program Uji/)).toBeInTheDocument();
    expect(screen.getByText('Wakil Rektor')).toBeInTheDocument();
  });

  it('links meeting detail to the matching minutes and Decision Brief views', async () => {
    const user = userEvent.setup();
    stubFetch((url) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([meeting]);
      if (url === `/api/v1/meetings/${meeting.id}`) return jsonResponse(meeting);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/dispositions?limit=100&offset=0`) {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    await user.click(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    );

    expect(screen.getByRole('link', { name: 'Buka notulensi' })).toHaveAttribute(
      'href',
      `#notulensi/${meeting.id}`,
    );
    expect(screen.getByRole('link', { name: 'Buka Decision Brief' })).toHaveAttribute(
      'href',
      `#decision-briefs/${meeting.id}`,
    );
  });

  it('renders archived meeting records without any edit controls', async () => {
    const archivedMeeting: MeetingRecord = { ...meeting, status: 'ARCHIVED' };
    stubFetch((url) => {
      if (url === `/api/v1/meetings/${meeting.id}`) return jsonResponse(archivedMeeting);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) {
        return jsonResponse([]);
      }
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    window.history.replaceState(null, '', `#meetings/${meeting.id}`);

    render(<MeetingManagement authenticatedUser={secretary} />);

    expect(await screen.findByRole('heading', { name: meeting.title })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ubah informasi' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Tambah agenda' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit agenda' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Hapus agenda' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Tambah peserta' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Hapus' })).not.toBeInTheDocument();
  });

  it('shows an agenda number once instead of duplicating the ordered-list number', async () => {
    stubFetch((url) => {
      if (url === `/api/v1/meetings/${meeting.id}`) return jsonResponse(meeting);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    window.history.replaceState(null, '', `#meetings/${meeting.id}`);

    render(<MeetingManagement authenticatedUser={secretary} />);

    await screen.findByRole('heading', { name: meeting.title });
    const agendaTitle = screen.getByText('Evaluasi Program Uji');
    expect(agendaTitle).toBeInTheDocument();
    expect(agendaTitle.closest('li')?.parentElement?.tagName).toBe('OL');
    expect(agendaTitle).not.toHaveTextContent(/^1\./);
  });

  it('allows in-scope Secretariat to edit allowlisted metadata during LIVE with version checks', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const liveMeeting = { ...meeting, status: 'LIVE' as const, version: 4 };
    let updatedMeeting: MeetingRecord = liveMeeting;
    const fetchMock = stubFetch((url, init) => {
      if (url === `/api/v1/meetings/${meeting.id}` && init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        updatedMeeting = { ...updatedMeeting, ...body, version: 5 };
        return jsonResponse(updatedMeeting);
      }
      if (url === `/api/v1/meetings/${meeting.id}`) return jsonResponse(updatedMeeting);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    window.history.replaceState(null, '', `#meetings/${meeting.id}`);
    render(<MeetingManagement authenticatedUser={secretary} />);

    await screen.findByRole('heading', { name: meeting.title });
    await user.click(screen.getByRole('button', { name: 'Ubah informasi' }));
    const titleInput = screen.getByLabelText('Judul rapat');
    await user.clear(titleInput);
    await user.type(titleInput, 'Judul LIVE diperbarui');
    await user.click(screen.getByRole('button', { name: 'Simpan informasi' }));

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Judul LIVE diperbarui' })).toBeVisible(),
    );
    const patchCall = fetchMock.mock.calls.find(
      ([url, init]) => url === `/api/v1/meetings/${meeting.id}` && init?.method === 'PATCH',
    );
    expect(JSON.parse(String(patchCall?.[1]?.body))).toMatchObject({
      expected_version: 4,
      title: 'Judul LIVE diperbarui',
    });
    expect(await screen.findByRole('heading', { name: 'Agenda' })).toBeInTheDocument();
  });

  it('validates required meeting fields and rejects end time before start time', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch((url) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([]);
      if (url === '/api/v1/meetings/participant-options') return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);
    await user.click(await screen.findByRole('button', { name: 'Buat rapat' }));
    await user.click(screen.getByRole('button', { name: 'Simpan rapat' }));

    expect(screen.getByLabelText('Nomor rapat')).toBeInvalid();
    expect(screen.getByLabelText('Judul rapat')).toBeInvalid();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    await user.type(screen.getByLabelText('Nomor rapat'), 'RAPIM-2026-030');
    await user.type(screen.getByLabelText('Judul rapat'), meeting.title);
    await user.type(screen.getByLabelText('Tanggal'), '2026-11-20');
    await user.type(screen.getByLabelText('Waktu mulai'), '10:00');
    await user.type(screen.getByLabelText('Waktu selesai'), '09:00');
    await user.click(screen.getByRole('button', { name: 'Simpan rapat' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Waktu selesai harus sama atau setelah waktu mulai.',
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('shows backend duplicate-number errors without showing false success', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([]);
      if (url === '/api/v1/meetings/participant-options') return jsonResponse([]);
      if (url === '/api/v1/meetings' && init?.method === 'POST') {
        return jsonResponse(
          { detail: 'Meeting number, agenda number, or participant already exists' },
          409,
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    render(<MeetingManagement authenticatedUser={secretary} />);
    await user.click(await screen.findByRole('button', { name: 'Buat rapat' }));
    await user.type(screen.getByLabelText('Nomor rapat'), 'RAPIM-2026-030');
    await user.type(screen.getByLabelText('Judul rapat'), meeting.title);
    await user.type(screen.getByLabelText('Tanggal'), '2026-11-20');
    await user.click(screen.getByRole('button', { name: 'Simpan rapat' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Meeting number, agenda number, or participant already exists',
    );
    expect(screen.queryByRole('heading', { name: meeting.title })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('adds an agenda only through the supported draft agenda endpoint', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    let agendaAdded = false;
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([meeting]);
      if (url === `/api/v1/meetings/${meeting.id}`) {
        return jsonResponse(
          agendaAdded
            ? {
                ...meeting,
                agendas: [
                  ...meeting.agendas,
                  {
                    ...meeting.agendas[0],
                    id: '31000000-0000-4000-8000-000000000002',
                    agenda_number: 2,
                    title: 'Agenda Kedua',
                  },
                ],
              }
            : meeting,
        );
      }
      if (url === `/api/v1/meetings/${meeting.id}/agendas` && init?.method === 'POST') {
        agendaAdded = true;
        return jsonResponse(
          {
            ...meeting.agendas[0],
            id: '31000000-0000-4000-8000-000000000002',
            agenda_number: 2,
            title: 'Agenda Kedua',
          },
          201,
        );
      }
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<MeetingManagement authenticatedUser={secretary} />);
    await user.click(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    );
    await user.click(await screen.findByRole('button', { name: 'Tambah agenda' }));
    await user.type(screen.getByLabelText('Judul agenda'), 'Agenda Kedua');
    await user.click(screen.getByRole('button', { name: 'Simpan agenda' }));

    expect(await screen.findByText(/Agenda Kedua/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/meetings/${meeting.id}/agendas`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          expected_version: 1,
          title: 'Agenda Kedua',
          agenda_description: null,
          pic_suggestion: null,
          supporting_pic_suggestion: null,
          duration_minutes: null,
        }),
      }),
    );
  });

  it('adds a participant through the supported draft participant endpoint', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const newParticipant: MeetingParticipant = {
      user_id: '20000000-0000-4000-8000-000000000004',
      participant_name: 'Peserta Baru Sintetis',
      participant_title: 'Dekan Uji',
    };
    let participantAdded = false;
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([meeting]);
      if (url === '/api/v1/meetings/participant-options') {
        return jsonResponse([
          {
            id: newParticipant.user_id,
            full_name: newParticipant.participant_name,
            job_title: newParticipant.participant_title,
            roles: ['WAREK'],
          },
        ]);
      }
      if (url === `/api/v1/meetings/${meeting.id}`) {
        return jsonResponse({
          ...meeting,
          participants: participantAdded
            ? [...meeting.participants, newParticipant]
            : meeting.participants,
        });
      }
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/participants` && init?.method === 'POST') {
        participantAdded = true;
        return jsonResponse(newParticipant, 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);
    await user.click(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    );
    await user.click(await screen.findByRole('button', { name: 'Tambah peserta' }));
    await user.selectOptions(screen.getByLabelText('Pilih peserta'), newParticipant.user_id);
    await user.click(screen.getByRole('button', { name: 'Tambahkan peserta' }));

    expect(await screen.findByText('Dekan Uji')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/meetings/${meeting.id}/participants`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          expected_version: 1,
          user_id: newParticipant.user_id,
        }),
      }),
    );
  });

  it('adds a named external participant from the Lainnya option', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const externalParticipant = {
      id: '32000000-0000-4000-8000-000000000001',
      participant_name: 'Narasumber Eksternal',
    };
    let participantAdded = false;
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([meeting]);
      if (url === '/api/v1/meetings/participant-options') {
        return jsonResponse([
          {
            id: '20000000-0000-4000-8000-000000000004',
            full_name: 'Pengguna Lain',
            job_title: 'Dekan Uji',
            roles: ['WAREK'],
          },
        ]);
      }
      if (url === `/api/v1/meetings/${meeting.id}`) {
        return jsonResponse({
          ...meeting,
          external_participants: participantAdded ? [externalParticipant] : [],
        });
      }
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      if (
        url === `/api/v1/meetings/${meeting.id}/participants/external` &&
        init?.method === 'POST'
      ) {
        participantAdded = true;
        return jsonResponse(externalParticipant, 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);
    await user.click(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    );
    await user.click(await screen.findByRole('button', { name: 'Tambah peserta' }));
    await user.selectOptions(screen.getByLabelText('Pilih peserta'), 'other');

    const nameInput = screen.getByLabelText('Nama peserta lainnya');
    await user.type(nameInput, externalParticipant.participant_name);
    await user.click(screen.getByRole('button', { name: 'Tambahkan peserta' }));

    expect(await screen.findByText('Narasumber Eksternal')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/meetings/${meeting.id}/participants/external`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          expected_version: 1,
          participant_name: 'Narasumber Eksternal',
        }),
      }),
    );
  });

  it.each([
    ['PIC', false, false],
    ['SUPER_ADMIN', false, false],
    ['SEKRETARIAT', true, true],
    ['MANAGER_LEGAL', true, true],
    ['REKTOR', true, false],
    ['WAREK', true, true],
  ])(
    'exposes meeting routes for %s according to the existing meeting roles',
    async (role, canRead, canEdit) => {
      const user: AuthenticatedUser = { ...secretary, roles: [role] };
      const fetchMock = stubFetch((url) => {
        if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([]);
        if (url === '/api/v1/meetings') return jsonResponse(meeting, 201);
        throw new Error(`Unexpected request: ${url}`);
      });
      render(<MeetingManagement authenticatedUser={user} />);

      if (canRead) {
        expect(await screen.findByText('Tidak ada rapat yang cocok.')).toBeInTheDocument();
        if (canEdit) {
          expect(screen.getByRole('button', { name: 'Buat rapat' })).toBeInTheDocument();
        } else {
          expect(screen.queryByRole('button', { name: 'Buat rapat' })).not.toBeInTheDocument();
        }
      } else {
        expect(await screen.findByRole('alert')).toHaveTextContent(
          'Peran Anda tidak memiliki akses ke pengelolaan rapat.',
        );
        expect(fetchMock).not.toHaveBeenCalled();
      }
    },
  );

  it('starts a draft meeting and refreshes its detail and the meeting list', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    let currentMeeting: MeetingRecord = meeting;
    let listRequests = 0;
    let detailRequests = 0;
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') {
        listRequests += 1;
        return jsonResponse([currentMeeting]);
      }
      if (url === `/api/v1/meetings/${meeting.id}/transition` && init?.method === 'POST') {
        currentMeeting = { ...currentMeeting, status: 'LIVE' };
        return jsonResponse(currentMeeting);
      }
      if (url === `/api/v1/meetings/${meeting.id}`) {
        detailRequests += 1;
        return jsonResponse(currentMeeting);
      }
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    await user.click(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    );
    await user.click(await screen.findByRole('button', { name: 'Mulai rapat' }));

    expect(await screen.findAllByText('Berlangsung')).not.toHaveLength(0);
    await waitFor(() => {
      expect(listRequests).toBe(2);
      expect(detailRequests).toBe(2);
    });
    const transitionRequest = fetchMock.mock.calls.find(
      ([url]) => url === `/api/v1/meetings/${meeting.id}/transition`,
    )?.[1];
    expect(transitionRequest).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ to_status: 'LIVE' }),
    });
    const transitionHeaders = new Headers(transitionRequest?.headers);
    expect(transitionHeaders.get('Content-Type')).toBe('application/json');
    expect(transitionHeaders.get('X-CSRF-Token')).toBe('csrf-test-token');
  });

  it('shows transition loading, prevents duplicate submission, and reports backend errors', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    let resolveTransition: (response: Response) => void = () => {
      throw new Error('Transition request was not started');
    };
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([meeting]);
      if (url === `/api/v1/meetings/${meeting.id}`) return jsonResponse(meeting);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/transition` && init?.method === 'POST') {
        return new Promise<Response>((resolve) => {
          resolveTransition = resolve;
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    await user.click(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    );
    await user.click(await screen.findByRole('button', { name: 'Mulai rapat' }));
    const pendingButton = screen.getByRole('button', { name: 'Mulai rapat' });
    expect(pendingButton).toBeDisabled();
    await user.click(pendingButton);
    expect(
      fetchMock.mock.calls.filter(([url]) => url === `/api/v1/meetings/${meeting.id}/transition`),
    ).toHaveLength(1);

    resolveTransition(jsonResponse({ detail: 'Meeting status transition is not allowed' }, 409));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Meeting status transition is not allowed',
    );
    expect(screen.getAllByText('Draf')).not.toHaveLength(0);
  });

  it('reviews the active minutes revision and finalizes only after a valid review', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    let liveMeeting: MeetingRecord = { ...meeting, status: 'LIVE' };
    const revision = {
      id: '32000000-0000-4000-8000-000000000001',
      meeting_id: meeting.id,
      revision_number: 1,
      format_version: 1 as const,
      content: 'Notulensi sintetis',
      discussions: [],
      created_by_id: secretary.id,
      created_at: '2026-11-20T10:00:00Z',
    };
    const reviews: {
      id: string;
      meeting_id: string;
      minutes_revision_id: string | null;
      reviewer_user_id: string;
      review_number: number;
      result: 'VALID' | 'INVALID';
      review_note: string | null;
      reviewed_at: string;
    }[] = [];
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([liveMeeting]);
      if (url === `/api/v1/meetings/${meeting.id}`) return jsonResponse(liveMeeting);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) {
        return jsonResponse([revision]);
      }
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) {
        if (init?.method === 'POST') {
          const submitted = JSON.parse(String(init.body)) as {
            minutes_revision_id: string;
            result: 'VALID' | 'INVALID';
            review_note: string | null;
          };
          const review = {
            id: '33000000-0000-4000-8000-000000000001',
            meeting_id: meeting.id,
            minutes_revision_id: submitted.minutes_revision_id,
            reviewer_user_id: secretary.id,
            review_number: 1,
            result: submitted.result,
            review_note: submitted.review_note,
            reviewed_at: '2026-11-20T11:00:00Z',
          };
          reviews.push(review);
          return jsonResponse(review, 201);
        }
        return jsonResponse(reviews);
      }
      if (url === `/api/v1/meetings/${meeting.id}/transition` && init?.method === 'POST') {
        liveMeeting = { ...liveMeeting, status: 'FINAL' };
        return jsonResponse({ ...liveMeeting, status: 'FINAL' });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    await user.click(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    );
    expect(screen.getByRole('button', { name: 'Tandai notulensi valid' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Selesaikan rapat' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Tandai notulensi valid' }));

    expect(await screen.findByText('Notulensi sudah ditandai valid.')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Selesaikan rapat' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Selesaikan rapat' }));

    expect(await screen.findAllByText('Selesai')).not.toHaveLength(0);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/meetings/${meeting.id}/minutes-reviews`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          minutes_revision_id: revision.id,
          result: 'VALID',
          review_note: null,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/meetings/${meeting.id}/transition`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ to_status: 'FINAL' }),
      }),
    );
  });

  it('does not allow finalization when the latest review of the active revision is invalid', async () => {
    const user = userEvent.setup();
    const liveMeeting: MeetingRecord = { ...meeting, status: 'LIVE' };
    const revision = {
      id: '32000000-0000-4000-8000-000000000003',
      meeting_id: meeting.id,
      revision_number: 1,
      format_version: 1 as const,
      content: 'Notulensi perlu koreksi',
      discussions: [],
      created_by_id: secretary.id,
      created_at: '2026-11-20T10:00:00Z',
    };
    const invalidReview = {
      id: '33000000-0000-4000-8000-000000000002',
      meeting_id: meeting.id,
      minutes_revision_id: revision.id,
      reviewer_user_id: secretary.id,
      review_number: 1,
      result: 'INVALID' as const,
      review_note: 'Perlu koreksi',
      reviewed_at: '2026-11-20T11:00:00Z',
    };
    stubFetch((url) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([liveMeeting]);
      if (url === `/api/v1/meetings/${meeting.id}`) return jsonResponse(liveMeeting);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) {
        return jsonResponse([revision]);
      }
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) {
        return jsonResponse([invalidReview]);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    await user.click(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    );
    expect(screen.getByRole('button', { name: 'Tandai notulensi valid' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Selesaikan rapat' })).not.toBeInTheDocument();
  });

  it('reloads the active revision after a concurrent-review conflict', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const liveMeeting: MeetingRecord = { ...meeting, status: 'LIVE' };
    const firstRevision = {
      id: '32000000-0000-4000-8000-000000000004',
      meeting_id: meeting.id,
      revision_number: 1,
      format_version: 1 as const,
      content: 'Revisi pertama',
      discussions: [],
      created_by_id: secretary.id,
      created_at: '2026-11-20T10:00:00Z',
    };
    let activeRevision = firstRevision;
    let reviewAttempts = 0;
    let successfulReview: { minutes_revision_id: string; result: 'VALID' } | null = null;
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([liveMeeting]);
      if (url === `/api/v1/meetings/${meeting.id}`) return jsonResponse(liveMeeting);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) {
        return jsonResponse([activeRevision]);
      }
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) {
        if (init?.method === 'POST') {
          reviewAttempts += 1;
          if (reviewAttempts === 1) {
            activeRevision = {
              ...firstRevision,
              id: '32000000-0000-4000-8000-000000000005',
              revision_number: 2,
              content: 'Revisi kedua',
            };
            return jsonResponse(
              { detail: 'Minutes review must reference the active revision' },
              409,
            );
          }
          successfulReview = { minutes_revision_id: activeRevision.id, result: 'VALID' };
          return jsonResponse(
            {
              id: '33000000-0000-4000-8000-000000000002',
              meeting_id: meeting.id,
              minutes_revision_id: activeRevision.id,
              reviewer_user_id: secretary.id,
              review_number: 1,
              result: 'VALID',
              review_note: null,
              reviewed_at: '2026-11-20T11:00:00Z',
            },
            201,
          );
        }
        return jsonResponse(successfulReview ? [successfulReview] : []);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    await user.click(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    );
    await user.click(screen.getByRole('button', { name: 'Tandai notulensi valid' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Minutes review must reference the active revision',
    );
    await user.click(screen.getByRole('button', { name: 'Tandai notulensi valid' }));
    expect(await screen.findByText('Notulensi sudah ditandai valid.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Selesaikan rapat' })).toBeInTheDocument();
    const reviewPosts = fetchMock.mock.calls.filter(
      ([url, init]) =>
        url === `/api/v1/meetings/${meeting.id}/minutes-reviews` && init?.method === 'POST',
    );
    expect(JSON.parse(String(reviewPosts[1][1]?.body))).toMatchObject({
      minutes_revision_id: activeRevision.id,
      result: 'VALID',
      review_note: null,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/meetings/${meeting.id}/minutes-reviews`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          minutes_revision_id: firstRevision.id,
          result: 'VALID',
          review_note: null,
        }),
      }),
    );
  });

  it('does not allow finalization when the latest valid review is for an older revision', async () => {
    const oldRevision = {
      id: '32000000-0000-4000-8000-000000000001',
      meeting_id: meeting.id,
      revision_number: 1,
      format_version: 1 as const,
      content: 'Revisi lama',
      discussions: [],
      created_by_id: secretary.id,
      created_at: '2026-11-20T10:00:00Z',
    };
    const activeRevision = {
      ...oldRevision,
      id: '32000000-0000-4000-8000-000000000002',
      revision_number: 2,
    };
    stubFetch((url) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') {
        return jsonResponse([{ ...meeting, status: 'LIVE' }]);
      }
      if (url === `/api/v1/meetings/${meeting.id}`) {
        return jsonResponse({ ...meeting, status: 'LIVE' });
      }
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) {
        return jsonResponse([oldRevision, activeRevision]);
      }
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) {
        return jsonResponse([
          {
            id: '33000000-0000-4000-8000-000000000001',
            meeting_id: meeting.id,
            minutes_revision_id: oldRevision.id,
            reviewer_user_id: secretary.id,
            review_number: 1,
            result: 'VALID',
            review_note: null,
            reviewed_at: '2026-11-20T11:00:00Z',
          },
        ]);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    await userEvent
      .setup()
      .click(await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }));

    expect(screen.getByRole('button', { name: 'Tandai notulensi valid' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Selesaikan rapat' })).not.toBeInTheDocument();
  });

  it('archives only a final meeting through the supported transition endpoint', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    let currentMeeting: MeetingRecord = { ...meeting, status: 'FINAL' };
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/v1/meetings?limit=20&offset=0') return jsonResponse([currentMeeting]);
      if (url === `/api/v1/meetings/${meeting.id}`) return jsonResponse(currentMeeting);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-revisions`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/minutes-reviews`) return jsonResponse([]);
      if (url === `/api/v1/meetings/${meeting.id}/transition` && init?.method === 'POST') {
        currentMeeting = { ...currentMeeting, status: 'ARCHIVED' };
        return jsonResponse(currentMeeting);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<MeetingManagement authenticatedUser={secretary} />);

    await user.click(
      await screen.findByRole('button', { name: 'Lihat detail Rapat Evaluasi Sintetis' }),
    );
    expect(screen.queryByRole('button', { name: 'Mulai rapat' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Selesaikan rapat' })).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Arsipkan' }));

    expect(await screen.findAllByText('Diarsipkan')).not.toHaveLength(0);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/meetings/${meeting.id}/transition`,
      expect.objectContaining({ body: JSON.stringify({ to_status: 'ARCHIVED' }) }),
    );
  });

  it('keeps lifecycle actions unavailable to mixed PIC and managerial roles', async () => {
    const mixedRoleUser: AuthenticatedUser = {
      ...secretary,
      roles: ['SEKRETARIAT', 'PIC'],
    };
    const fetchMock = stubFetch(() => {
      throw new Error('Meeting API should not be called for this restricted role combination');
    });
    render(<MeetingManagement authenticatedUser={mixedRoleUser} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Peran Anda tidak memiliki akses ke pengelolaan rapat.',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('returns to login when a meeting API request reports an expired session', async () => {
    window.history.replaceState(null, '', '#meetings');
    const fetchMock = stubFetch((url) => {
      if (url === '/api/v1/auth/me') {
        return jsonResponse({ ...secretary });
      }
      if (url === '/api/v1/meetings?limit=20&offset=0') {
        return jsonResponse({ detail: 'Authentication required' }, 401);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Masuk ke SITARA' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Sesi Anda telah berakhir. Silakan masuk kembali.',
    );
  });
});
