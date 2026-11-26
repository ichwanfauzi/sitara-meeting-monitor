import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const secretary = {
  id: '20000000-0000-4000-8000-000000000001',
  email: 'sekretariat@example.test',
  full_name: 'Sekretariat Uji',
  roles: ['SEKRETARIAT'],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function authenticatedFetch(user = secretary): ReturnType<typeof vi.fn> {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === '/api/v1/auth/me') return jsonResponse(user);
    if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([]);
    if (url === '/api/v1/action-items?limit=100&offset=0') return jsonResponse([]);
    throw new Error(`Unexpected request: ${url}`);
  });
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(jsonResponse({ detail: 'Authentication required' }, 401)),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
  window.history.replaceState(null, '', '#dashboard');
});

describe('SITARA dashboard', () => {
  it('provides a collapsible workspace navigation that closes after selecting a page', async () => {
    vi.stubGlobal('fetch', authenticatedFetch());
    const user = userEvent.setup();
    render(<App />);

    const menuButton = await screen.findByRole('button', { name: 'Buka menu navigasi' });
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    expect(menuButton).toHaveAttribute('aria-controls', 'primary-navigation');

    await user.click(menuButton);
    expect(screen.getByRole('button', { name: 'Tutup menu navigasi' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );

    await user.click(screen.getByRole('link', { name: 'Rapat' }));
    expect(screen.getByRole('button', { name: 'Buka menu navigasi' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  });

  it('requires an authenticated session before showing the dashboard', async () => {
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Masuk ke SITARA' })).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: 'Ringkasan operasional' }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toBeRequired();
    expect(screen.getByLabelText('Kata sandi')).toBeRequired();
    expect(screen.getByLabelText('Email')).toHaveAttribute('name', 'username');
    expect(screen.getByLabelText('Email')).toHaveAttribute('autocomplete', 'username');
    expect(screen.getByLabelText('Kata sandi')).toHaveAttribute('name', 'password');
    expect(screen.getByLabelText('Kata sandi')).toHaveAttribute('autocomplete', 'current-password');
  });

  it('shows API-backed dashboard summaries with the authenticated identity', async () => {
    vi.stubGlobal('fetch', authenticatedFetch());
    render(<App />);

    expect(await screen.findByRole('link', { name: 'SITARA, ke dashboard' })).toBeInTheDocument();
    expect(screen.getByText('Sistem Informasi Tindak Lanjut dan Arsip Rapat')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Beranda Rapim' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Navigasi utama' })).toBeInTheDocument();
    expect(screen.getAllByText('Sekretariat Uji')).toHaveLength(2);
    expect(screen.getByText('Rapim tercatat')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Status tugas' })).toBeVisible();
    expect(screen.getByText('Belum ada Action Item dalam cakupan akses Anda.')).toBeInTheDocument();
    expect(screen.queryByText('Belum ada rapat dalam cakupan akses Anda.')).not.toBeInTheDocument();
    expect(screen.queryByText('Evaluasi kerja sama industri')).not.toBeInTheDocument();
  });

  it('opens the Action Item workspace and returns to login when its API session expires', async () => {
    window.history.replaceState(null, '', '#dashboard');
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/auth/me') return jsonResponse(secretary);
      if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([]);
      if (url === '/api/v1/action-items?limit=100&offset=0') return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    await user.click(await screen.findByRole('link', { name: 'Tindak lanjut' }));
    expect(await screen.findByRole('heading', { name: 'Action Item' })).toBeInTheDocument();

    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/auth/me') return jsonResponse(secretary);
      if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([]);
      if (url === '/api/v1/action-items?limit=100&offset=0') return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });

    await user.click(screen.getByRole('link', { name: 'Dashboard' }));
    expect(await screen.findByRole('heading', { name: 'Beranda Rapim' })).toBeInTheDocument();

    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/auth/me') return jsonResponse(secretary);
      if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([]);
      if (url === '/api/v1/action-items?limit=100&offset=0') {
        return jsonResponse({ detail: 'Authentication required' }, 401);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    await user.click(screen.getByRole('link', { name: 'Tindak lanjut' }));

    expect(await screen.findByRole('heading', { name: 'Masuk ke SITARA' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Sesi Anda telah berakhir. Silakan masuk kembali.',
    );
  });

  it('does not present prototype values as operational dashboard data', async () => {
    vi.stubGlobal('fetch', authenticatedFetch());
    render(<App />);

    await screen.findByRole('heading', { name: 'Beranda Rapim' });
    expect(
      screen.queryByText('Evaluasi tindak lanjut kerja sama industri'),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Penataan arsip keputusan semester genap')).not.toBeInTheDocument();
    expect(screen.queryByText('Data contoh')).not.toBeInTheDocument();
  });

  it('opens the notulensi editor from workspace navigation', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    vi.stubGlobal('fetch', authenticatedFetch());
    render(<App />);

    await user.click(await screen.findByRole('link', { name: 'Notulensi' }));

    expect(await screen.findByRole('heading', { name: 'Notulensi rapat' })).toBeInTheDocument();
    expect(await screen.findByText('Tidak ada rapat yang dapat diakses.')).toBeInTheDocument();
  });

  it('opens the selected Rapim directly in its minutes and Decision Brief workspaces', async () => {
    const user = userEvent.setup();
    const meetingId = '30000000-0000-4000-8000-000000000007';
    const meeting = {
      id: meetingId,
      meeting_number: 'RAPIM-2026-007',
      title: 'Rapat pilihan sintetis',
      meeting_date: '2026-11-20',
      notetaker_id: secretary.id,
      status: 'LIVE',
      agendas: [],
    };
    const revision = {
      id: '40000000-0000-4000-8000-000000000007',
      meeting_id: meetingId,
      revision_number: 1,
      format_version: 1,
      content: 'Notulen rapat pilihan sintetis.',
      discussions: [],
      created_by_id: secretary.id,
      created_at: '2026-11-20T09:00:00Z',
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/auth/me') return jsonResponse(secretary);
      if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
      if (url === `/api/v1/meetings/${meetingId}/minutes-revisions`) {
        return jsonResponse([revision]);
      }
      if (url === `/api/v1/meetings/${meetingId}/decision-briefs`) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    window.history.replaceState(null, '', '#notulensi');
    render(<App />);

    const minutesLink = await screen.findByRole('link', { name: /RAPIM-2026-007/ });
    const minutesSelection = minutesLink.closest('.meeting-document-selection');
    expect(minutesSelection).not.toBeNull();
    expect(minutesSelection).not.toHaveClass('dashboard-content');
    expect(minutesSelection?.parentElement).toHaveClass('dashboard-content');
    expect(minutesLink).toHaveAttribute('href', `#notulensi/${meetingId}`);
    window.location.hash = minutesLink.getAttribute('href')!;
    const minutesForm = await screen.findByRole('region', {
      name: 'Form pengisian hasil rapat',
    });
    expect(screen.getByRole('heading', { name: 'Notulensi rapat' })).toBeVisible();
    expect(minutesForm).toBeVisible();

    await user.click(screen.getByRole('link', { name: 'Decision Brief' }));
    const briefLink = await screen.findByRole('link', { name: /RAPIM-2026-007/ });
    const briefSelection = briefLink.closest('.meeting-document-selection');
    expect(briefSelection).not.toBeNull();
    expect(briefSelection).not.toHaveClass('dashboard-content');
    expect(briefSelection?.parentElement).toHaveClass('dashboard-content');
    expect(briefLink).toHaveAttribute('href', `#decision-briefs/${meetingId}`);
    window.location.hash = briefLink.getAttribute('href')!;
    await waitFor(() => {
      expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain(
        `/api/v1/meetings/${meetingId}/decision-briefs`,
      );
    });
  });

  it('preserves the meeting context in minutes and Decision Brief deep links', async () => {
    const firstMeetingId = '30000000-0000-4000-8000-000000000001';
    const targetMeetingId = '30000000-0000-4000-8000-000000000002';
    const meetings = [
      {
        id: firstMeetingId,
        meeting_number: 'RAPIM-2026-001',
        title: 'Rapat pertama sintetis',
        meeting_date: '2026-10-15',
        notetaker_id: secretary.id,
        status: 'LIVE',
        agendas: [],
      },
      {
        id: targetMeetingId,
        meeting_number: 'RAPIM-2026-002',
        title: 'Rapat target sintetis',
        meeting_date: '2026-10-16',
        notetaker_id: secretary.id,
        status: 'LIVE',
        agendas: [],
      },
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url === '/api/v1/auth/me') return jsonResponse(secretary);
      if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse(meetings);
      if (url === `/api/v1/meetings/${targetMeetingId}/minutes-revisions`) {
        return jsonResponse([
          {
            id: '40000000-0000-4000-8000-000000000002',
            meeting_id: targetMeetingId,
            revision_number: 1,
            format_version: 1,
            content: 'Notulen rapat target',
            discussions: [],
            created_by_id: secretary.id,
            created_at: '2026-10-16T09:00:00Z',
          },
        ]);
      }
      if (url === `/api/v1/meetings/${targetMeetingId}/decision-briefs`) {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    window.history.replaceState(null, '', `#notulensi/${targetMeetingId}`);
    render(<App />);

    expect(
      await screen.findByRole('region', { name: 'Form pengisian hasil rapat' }),
    ).toBeInTheDocument();
    await userEvent.setup().click(screen.getByText('Buka catatan notulensi terdahulu'));
    expect(screen.getByText('Notulen rapat target')).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain(
      `/api/v1/meetings/${targetMeetingId}/minutes-revisions`,
    );
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain(
      `/api/v1/meetings/${firstMeetingId}/minutes-revisions`,
    );

    window.location.hash = `#decision-briefs/${targetMeetingId}`;
    expect(await screen.findByRole('heading', { name: 'Decision Brief' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Sumber keputusan' })).toBeInTheDocument();
    expect(screen.queryByText(/Revisi notulensi 1/)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain(
      `/api/v1/meetings/${targetMeetingId}/decision-briefs`,
    );
  });

  it('opens the Decision Brief editor for an authenticated meeting reader', async () => {
    window.history.replaceState(null, '', '#dashboard');
    const userActions = userEvent.setup();
    const meetingId = '30000000-0000-4000-8000-000000000001';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/auth/me') {
          return new Response(
            JSON.stringify({
              id: '20000000-0000-4000-8000-000000000001',
              email: 'sekretariat@example.test',
              full_name: 'Sekretariat Uji',
              roles: ['SEKRETARIAT'],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url === '/api/v1/action-items?limit=100&offset=0') {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url === '/api/v1/meetings?limit=100&offset=0') {
          return new Response(
            JSON.stringify([
              {
                id: meetingId,
                meeting_number: 'RAPIM-2026-001',
                title: 'Rapat sintetis',
                meeting_date: '2026-10-15',
                notetaker_id: null,
                status: 'FINAL',
                agendas: [],
              },
            ]),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (url === '/api/v1/action-items?limit=100&offset=0') return jsonResponse([]);
        if (url.endsWith('/minutes-revisions') || url.endsWith('/decision-briefs')) {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(<App />);

    await userActions.click(await screen.findByRole('link', { name: 'Decision Brief' }));
    await userActions.click(
      await screen.findByRole('link', { name: /RAPIM-2026-001 · Rapat sintetis/ }),
    );

    expect(await screen.findByRole('heading', { name: 'Decision Brief' })).toBeInTheDocument();
    expect(await screen.findByText('Rapat ini belum memiliki notulensi.')).toBeInTheDocument();
  });

  it('does not show the notulensi menu to PIC', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/auth/me') {
        return new Promise<Response>((resolve) => {
          resolveAuth = resolve;
        });
      }
      if (url === '/api/v1/action-items?limit=100&offset=0') return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    let resolveAuth: (response: Response) => void = () => undefined;
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/me', expect.anything()),
    );

    await act(async () => {
      resolveAuth(
        new Response(
          JSON.stringify({
            id: '20000000-0000-4000-8000-000000000001',
            email: 'pic@example.test',
            full_name: 'PIC Uji',
            roles: ['PIC'],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      );
    });

    expect(screen.queryByRole('link', { name: 'Notulensi' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Decision Brief' })).not.toBeInTheDocument();
  });

  it('guards in-app and browser navigation while a minutes draft is unsaved', async () => {
    window.history.replaceState(null, '', '#dashboard');
    const userActions = userEvent.setup();
    const meetingId = '30000000-0000-4000-8000-000000000001';
    const revisionId = '40000000-0000-4000-8000-000000000001';
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/auth/me') {
        return new Response(
          JSON.stringify({
            id: '20000000-0000-4000-8000-000000000001',
            email: 'sekretariat@example.test',
            full_name: 'Sekretariat Uji',
            roles: ['SEKRETARIAT'],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url === '/api/v1/meetings?limit=100&offset=0') {
        return new Response(
          JSON.stringify([
            {
              id: meetingId,
              meeting_number: 'RAPIM-2026-001',
              title: 'Rapat sintetis',
              meeting_date: '2026-10-15T09:00:00Z',
              notetaker_id: '20000000-0000-4000-8000-000000000001',
              status: 'LIVE',
              agendas: [
                {
                  id: '50000000-0000-4000-8000-000000000001',
                  meeting_id: meetingId,
                  agenda_number: 1,
                  title: 'Agenda sintetis',
                  agenda_description: 'Agenda fixture untuk tes.',
                  lead_user_id: null,
                  duration_minutes: 30,
                  sort_order: 1,
                },
              ],
            },
          ]),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url === '/api/v1/action-items?limit=100&offset=0') return jsonResponse([]);
      if (url === `/api/v1/meetings/${meetingId}/minutes-revisions`) {
        return new Response(
          JSON.stringify([
            {
              id: revisionId,
              meeting_id: meetingId,
              revision_number: 1,
              content: 'Notulensi awal sintetis',
              created_by_id: '20000000-0000-4000-8000-000000000001',
              created_at: '2026-10-15T09:30:00Z',
            },
          ]),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    vi.stubGlobal('fetch', fetchMock);
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    render(<App />);

    await userActions.click(await screen.findByRole('link', { name: 'Notulensi' }));
    await userActions.click(
      await screen.findByRole('link', { name: /RAPIM-2026-001 · Rapat sintetis/ }),
    );
    await screen.findByRole('region', { name: 'Form pengisian hasil rapat' });
    await userActions.click(screen.getByRole('button', { name: 'Isi pokok bahasan' }));
    const editor = screen.getByLabelText('Isi pembahasan 1 agenda 1');
    await userActions.type(editor, 'Draf belum tersimpan');
    await userActions.click(screen.getByRole('link', { name: 'Dashboard' }));

    expect(confirmSpy).toHaveBeenCalled();
    expect(window.location.hash).toBe(`#notulensi/${meetingId}`);
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue('Draf belum tersimpan');

    window.location.hash = '#dashboard';
    await waitFor(() => expect(confirmSpy).toHaveBeenCalledTimes(2));
    expect(window.location.hash).toBe(`#notulensi/${meetingId}`);
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue('Draf belum tersimpan');

    const beforeUnload = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(beforeUnload);
    expect(beforeUnload.defaultPrevented).toBe(true);

    confirmSpy.mockReturnValueOnce(true);
    await userActions.click(screen.getByRole('link', { name: 'Dashboard' }));
    await waitFor(() =>
      expect(
        screen.queryByRole('region', { name: 'Form pengisian hasil rapat' }),
      ).not.toBeInTheDocument(),
    );
    expect(window.location.hash).toBe('#dashboard');
  });
});

describe('SITARA authentication', () => {
  it('logs in through the backend, confirms the session, and logs out', async () => {
    const user = userEvent.setup();
    let signedIn = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/v1/auth/me') {
        return signedIn
          ? jsonResponse(secretary)
          : jsonResponse({ detail: 'Authentication required' }, 401);
      }
      if (path === '/api/v1/auth/login') {
        signedIn = true;
        document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
        return jsonResponse(secretary);
      }
      if (path === '/api/v1/auth/logout') {
        signedIn = false;
        document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
        return new Response(null, { status: 204 });
      }
      if (
        path === '/api/v1/meetings?limit=100&offset=0' ||
        path === '/api/v1/action-items?limit=100&offset=0'
      ) {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected request: ${path} ${init?.method ?? 'GET'}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    await user.type(await screen.findByLabelText('Email'), secretary.email);
    await user.type(screen.getByLabelText('Kata sandi'), 'synthetic-password');
    await user.click(screen.getByRole('button', { name: 'Masuk' }));

    expect(await screen.findByRole('heading', { name: 'Beranda Rapim' })).toBeInTheDocument();
    const loginCall = fetchMock.mock.calls.find(([path]) => path === '/api/v1/auth/login');
    expect(loginCall?.[1]).toMatchObject({
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({ email: secretary.email, password: 'synthetic-password' }),
    });
    expect(new Headers(loginCall?.[1]?.headers).has('X-CSRF-Token')).toBe(false);
    expect(fetchMock.mock.calls.filter(([path]) => path === '/api/v1/auth/me')).toHaveLength(2);
    expect(window.localStorage.length).toBe(0);

    await user.click(screen.getByRole('button', { name: 'Keluar' }));

    expect(await screen.findByRole('heading', { name: 'Masuk ke SITARA' })).toBeInTheDocument();
    const logoutCall = fetchMock.mock.calls.find(([path]) => path === '/api/v1/auth/logout');
    expect(logoutCall?.[1]).toMatchObject({ method: 'POST', credentials: 'include' });
    expect(new Headers(logoutCall?.[1]?.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
  });

  it('shows backend login errors without exposing the dashboard', async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: 'Authentication required' }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: 'Email atau kata sandi tidak valid' }, 401));
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    await user.type(await screen.findByLabelText('Email'), 'invalid@example.test');
    await user.type(screen.getByLabelText('Kata sandi'), 'wrong-password');
    await user.click(screen.getByRole('button', { name: 'Masuk' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Email atau kata sandi tidak valid');
    expect(
      screen.queryByRole('heading', { name: 'Ringkasan operasional' }),
    ).not.toBeInTheDocument();
  });

  it('validates required fields and supports password visibility', async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'Authentication required' }, 401));
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    const password = await screen.findByLabelText('Kata sandi');
    await user.click(screen.getByRole('button', { name: 'Masuk' }));
    expect(screen.getByLabelText('Email')).toBeInvalid();
    expect(password).toBeInvalid();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.type(screen.getByLabelText('Email'), secretary.email);
    await user.type(password, 'synthetic-password');
    await user.click(screen.getByRole('button', { name: 'Tampilkan kata sandi' }));
    expect(screen.getByLabelText('Kata sandi')).toHaveAttribute('type', 'text');
    await user.click(screen.getByRole('button', { name: 'Sembunyikan kata sandi' }));
    expect(screen.getByLabelText('Kata sandi')).toHaveAttribute('type', 'password');
  });

  it('shows a loading state while verifying the existing session', async () => {
    let resolveSession: (response: Response) => void = () => undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            resolveSession = resolve;
          }),
      ),
    );
    render(<App />);

    expect(screen.getByRole('status')).toHaveTextContent('Memeriksa sesi');
    expect(
      screen.queryByRole('heading', { name: 'Ringkasan operasional' }),
    ).not.toBeInTheDocument();

    await act(async () => resolveSession(jsonResponse({ detail: 'Authentication required' }, 401)));
    expect(await screen.findByRole('heading', { name: 'Masuk ke SITARA' })).toBeInTheDocument();
  });

  it('shows a loading state while the login request is pending', async () => {
    const user = userEvent.setup();
    let signedIn = false;
    let resolveLogin: (response: Response) => void = () => undefined;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === '/api/v1/auth/me') {
        return Promise.resolve(
          signedIn
            ? jsonResponse(secretary)
            : jsonResponse({ detail: 'Authentication required' }, 401),
        );
      }
      if (path === '/api/v1/auth/login') {
        signedIn = true;
        document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
        return new Promise<Response>((resolve) => {
          resolveLogin = resolve;
        });
      }
      if (
        path === '/api/v1/meetings?limit=100&offset=0' ||
        path === '/api/v1/action-items?limit=100&offset=0'
      ) {
        return Promise.resolve(jsonResponse([]));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    await user.type(await screen.findByLabelText('Email'), secretary.email);
    await user.type(screen.getByLabelText('Kata sandi'), 'synthetic-password');
    await user.click(screen.getByRole('button', { name: 'Masuk' }));

    expect(await screen.findByRole('button', { name: 'Memverifikasi...' })).toBeDisabled();
    await act(async () => resolveLogin(jsonResponse(secretary)));
    expect(await screen.findByRole('heading', { name: 'Beranda Rapim' })).toBeInTheDocument();
  });

  it('shows a retryable service error when session verification is unavailable', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'Unavailable' }, 503));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Sesi tidak dapat diverifikasi. Periksa koneksi server lalu coba lagi.',
    );
    await user.click(screen.getByRole('button', { name: 'Coba lagi' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it('does not open the application for a malformed session response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ id: secretary.id, roles: 'SEKRETARIAT' })),
    );
    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Sesi tidak dapat diverifikasi. Periksa koneksi server lalu coba lagi.',
    );
    expect(
      screen.queryByRole('heading', { name: 'Ringkasan operasional' }),
    ).not.toBeInTheDocument();
  });

  it.each([
    ['SEKRETARIAT', 'Notulensi', 'Tindak lanjut'],
    ['REKTOR', 'Notulensi', 'Tindak lanjut'],
    ['WAREK', 'Notulensi', 'Tindak lanjut'],
    ['PIC', 'Tugas saya', null],
    ['SUPER_ADMIN', 'Ringkasan administratif belum tersedia melalui API', null],
  ])(
    'shows navigation for %s without granting other role access',
    async (role, expectedLink, hiddenLink) => {
      vi.stubGlobal('fetch', authenticatedFetch({ ...secretary, roles: [role] }));
      render(<App />);

      expect(await screen.findByRole('navigation', { name: 'Navigasi utama' })).toBeInTheDocument();
      if (role === 'SUPER_ADMIN') {
        expect(
          await screen.findByText(/Ringkasan administratif belum tersedia melalui API/),
        ).toBeInTheDocument();
      } else {
        expect(screen.getAllByText(expectedLink).length).toBeGreaterThan(0);
      }
      if (hiddenLink) {
        expect(screen.getByRole('link', { name: hiddenLink })).toBeInTheDocument();
      } else if (role === 'SUPER_ADMIN') {
        expect(screen.queryByRole('link', { name: 'Notulensi' })).not.toBeInTheDocument();
        expect(screen.queryByRole('link', { name: 'Decision Brief' })).not.toBeInTheDocument();
      } else if (role === 'PIC') {
        expect(screen.queryByRole('link', { name: 'Notulensi' })).not.toBeInTheDocument();
        expect(screen.queryByRole('link', { name: 'Decision Brief' })).not.toBeInTheDocument();
      } else {
        expect(screen.getByRole('link', { name: 'Notulensi' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Decision Brief' })).toBeInTheDocument();
      }
    },
  );

  it('does not grant Secretariat navigation to a mixed Super Admin account', async () => {
    vi.stubGlobal(
      'fetch',
      authenticatedFetch({ ...secretary, roles: ['SEKRETARIAT', 'SUPER_ADMIN'] }),
    );
    render(<App />);

    expect(await screen.findByRole('navigation', { name: 'Navigasi utama' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Notulensi' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Decision Brief' })).not.toBeInTheDocument();
    expect(screen.getAllByText('Sekretariat, Super Admin')).toHaveLength(2);
  });

  it('blocks direct editor navigation for a PIC session', async () => {
    window.history.replaceState(null, '', '/#notulensi');
    vi.stubGlobal('fetch', authenticatedFetch({ ...secretary, roles: ['PIC'] }));
    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Anda tidak memiliki akses ke Notulensi.',
    );
    expect(screen.queryByLabelText('Isi notulensi')).not.toBeInTheDocument();
    window.history.replaceState(null, '', '/#dashboard');
  });

  it('returns to login when a protected API request reports an expired session', async () => {
    const user = userEvent.setup();
    let meetingRequests = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === '/api/v1/auth/me') return jsonResponse(secretary);
      if (path === '/api/v1/meetings?limit=100&offset=0') {
        meetingRequests += 1;
        return meetingRequests === 1
          ? jsonResponse([])
          : jsonResponse({ detail: 'Authentication required' }, 401);
      }
      if (path === '/api/v1/action-items?limit=100&offset=0') {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    await user.click(await screen.findByRole('link', { name: 'Notulensi' }));

    expect(await screen.findByRole('heading', { name: 'Masuk ke SITARA' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Sesi Anda telah berakhir. Silakan masuk kembali.',
    );
  });

  it('returns to login when the dashboard API reports an expired session', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === '/api/v1/auth/me') return jsonResponse(secretary);
      if (path === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([]);
      if (path === '/api/v1/action-items?limit=100&offset=0') {
        return jsonResponse({ detail: 'Authentication required' }, 401);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Masuk ke SITARA' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Sesi Anda telah berakhir. Silakan masuk kembali.',
    );
    expect(screen.queryByText('Rapat Evaluasi Sintetis')).not.toBeInTheDocument();
  });
});
