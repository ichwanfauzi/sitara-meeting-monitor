import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DecisionBriefEditor from './DecisionBriefEditor';

const meetingId = '30000000-0000-4000-8000-000000000001';
const revisionId = '40000000-0000-4000-8000-000000000001';
const decisionId = '70000000-0000-4000-8000-000000000001';

const user = {
  id: '20000000-0000-4000-8000-000000000001',
  email: 'sekretariat@example.test',
  full_name: 'Sekretariat Uji',
  roles: ['SEKRETARIAT'],
};

const meeting = {
  id: meetingId,
  meeting_number: 'RAPIM-2026-001',
  title: 'Rapat sintetis Decision Brief',
  meeting_date: '2026-10-15',
  notetaker_id: user.id,
  status: 'FINAL',
  agendas: [
    {
      id: '50000000-0000-4000-8000-000000000001',
      agenda_number: 1,
      title: 'Evaluasi layanan',
      agenda_description: null,
      sort_order: 1,
    },
  ],
};

const revisions = [
  {
    id: revisionId,
    meeting_id: meetingId,
    revision_number: 3,
    format_version: 2,
    content: null,
    discussions: [
      {
        id: '60000000-0000-4000-8000-000000000001',
        agenda_id: meeting.agendas[0].id,
        discussion_number: 1,
        subject: 'Evaluasi triwulan',
        content: 'Catatan pembahasan sintetis',
        decisions: [
          {
            id: decisionId,
            discussion_id: '60000000-0000-4000-8000-000000000001',
            decision_number: 1,
            decision_text: 'Lengkapi laporan triwulan',
            pic_suggestion: 'Wakil Rektor I',
            output_expected: 'Laporan revisi',
            target_date: '2026-11-30',
            is_action_item: true,
          },
        ],
      },
    ],
    created_by_id: user.id,
    created_at: '2026-10-15T09:00:00Z',
  },
];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
});

describe('DecisionBriefEditor', () => {
  it('shows the Rapim list first and opens the chosen Decision Brief form', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
      if (url.endsWith('/minutes-revisions')) return jsonResponse(revisions);
      if (url.endsWith('/decision-briefs')) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} />);

    expect(await screen.findByRole('heading', { name: 'Decision Brief' })).toBeInTheDocument();
    expect(screen.queryByText('Pilih rapat untuk membuka decision brief.')).toBeNull();
    expect(screen.getByText('RAPIM · DECISION BRIEF')).toBeInTheDocument();
    expect(screen.getByText('Buka salah satu rapat untuk melanjutkan.')).toBeInTheDocument();
    expect(screen.getByText('1 rapat ditampilkan')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /RAPIM-2026-001 · Rapat sintetis Decision Brief/ }),
    ).toHaveAttribute('href', `#decision-briefs/${meetingId}`);
    expect(screen.queryByRole('region', { name: 'Isi Decision Brief' })).toBeNull();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain(
      `/api/v1/meetings/${meetingId}/minutes-revisions`,
    );
  });

  it('opens an archived meeting read-only and does not render an entry form', async () => {
    const archivedMeeting = { ...meeting, status: 'ARCHIVED' };
    const fetchMock = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url === '/api/v1/meetings?limit=100&offset=0') {
        return jsonResponse([archivedMeeting]);
      }
      if (url.endsWith('/minutes-revisions')) return jsonResponse(revisions);
      if (url.endsWith('/decision-briefs')) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} targetMeetingId={meetingId} />);

    expect(await screen.findByText('Rapat arsip · hanya dapat dilihat dan dicetak.')).toBeVisible();
    expect(screen.getByRole('banner')).toHaveTextContent(
      `${meeting.meeting_number} · ${meeting.title}`,
    );
    expect(screen.queryByRole('form', { name: 'Isi Decision Brief' })).toBeNull();
    expect(screen.queryByRole('table', { name: 'Form tabel Decision Brief' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Simpan Decision Brief' })).toBeNull();
  });

  it('keeps the requested meeting as the source for minutes and Decision Brief data', async () => {
    const secondMeetingId = '30000000-0000-4000-8000-000000000002';
    const secondMeeting = {
      ...meeting,
      id: secondMeetingId,
      meeting_number: 'RAPIM-2026-002',
      title: 'Rapat kedua sintetis',
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url === '/api/v1/meetings?limit=100&offset=0') {
        return jsonResponse([meeting, secondMeeting]);
      }
      if (url.endsWith(`/meetings/${secondMeetingId}/minutes-revisions`)) {
        return jsonResponse([]);
      }
      if (url.endsWith(`/meetings/${secondMeetingId}/decision-briefs`)) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} targetMeetingId={secondMeetingId} />);

    expect(screen.queryByRole('searchbox', { name: 'Pilih rapat' })).toBeNull();
    expect(screen.queryByText('RINGKASAN KEPUTUSAN RAPAT')).toBeNull();
    expect(screen.queryByText(/Bahasan, PIC, output, dan target mengikuti notulensi/)).toBeNull();
    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(requestedUrls).toContain(`/api/v1/meetings/${secondMeetingId}/minutes-revisions`);
      expect(requestedUrls).toContain(`/api/v1/meetings/${secondMeetingId}/decision-briefs`);
    });
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain(
      `/api/v1/meetings/${meetingId}/minutes-revisions`,
    );
  });

  it('does not load restricted document endpoints for a meeting outside the accessible list', async () => {
    const inaccessibleMeetingId = '30000000-0000-4000-8000-000000000099';
    const fetchMock = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(
      <DecisionBriefEditor authenticatedUser={user} targetMeetingId={inaccessibleMeetingId} />,
    );

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Rapat tidak termasuk dalam cakupan akses Anda.',
    );
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  it('surfaces meeting-list failures instead of reporting an access denial', async () => {
    const fetchMock = vi.fn(async (): Promise<Response> => {
      return jsonResponse({ detail: 'Rapat tidak dapat dimuat saat ini.' }, 503);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} targetMeetingId={meetingId} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Rapat tidak dapat dimuat saat ini.',
    );
    expect(screen.queryByText('Rapat tidak termasuk dalam cakupan akses Anda.')).toBeNull();
  });

  it('renders and prints each brief as a table using its exact source revision', async () => {
    const userActions = userEvent.setup();
    const newerRevision = {
      ...revisions[0],
      id: '40000000-0000-4000-8000-000000000002',
      revision_number: 4,
      discussions: [
        {
          ...revisions[0].discussions[0],
          id: '60000000-0000-4000-8000-000000000002',
          decisions: [
            {
              ...revisions[0].discussions[0].decisions[0],
              id: '70000000-0000-4000-8000-000000000002',
              decision_text: 'Putusan pada revisi terbaru',
              pic_suggestion: 'PIC revisi terbaru',
              output_expected: 'Output revisi terbaru',
              target_date: '2027-01-15',
            },
          ],
        },
      ],
    };
    const savedBrief = {
      id: '80000000-0000-4000-8000-000000000004',
      meeting_id: meetingId,
      source_minutes_revision_id: newerRevision.id,
      version_number: 2,
      summary: 'Prioritaskan pelaporan triwulan.',
      notes: 'Catatan editorial sintetis.',
      created_by_id: user.id,
      created_at: '2026-10-15T10:00:00Z',
      is_stale: false,
      approval_state: 'DRAFT',
      approval_events: [],
      decisions: [
        {
          decision_id: newerRevision.discussions[0].decisions[0].id,
          source_decision_text: 'Putusan pada revisi terbaru',
          source_agenda_id: meeting.agendas[0].id,
          source_agenda_title: 'Evaluasi layanan',
          source_discussion_id: newerRevision.discussions[0].id,
          source_discussion_subject: 'Evaluasi triwulan',
          brief_text: 'Gunakan indikator layanan terbaru.',
          priority: 'Prioritas utama',
          editorial_note: 'Koordinasikan antarunit.',
          position: 1,
        },
      ],
    };
    const printSpy = vi.fn();
    vi.stubGlobal('print', printSpy);
    const fetchMock = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
      if (url.endsWith('/minutes-revisions')) return jsonResponse([revisions[0], newerRevision]);
      if (url.endsWith('/decision-briefs')) return jsonResponse([savedBrief]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} targetMeetingId={meetingId} />);

    const briefForm = await screen.findByRole('region', { name: 'Isi Decision Brief' });
    expect(
      within(briefForm).getByRole('heading', { name: 'DECISION BRIEF RAPAT PIMPINAN' }),
    ).toBeVisible();
    expect(within(briefForm).getByText('Rapim 15 Oktober 2026')).toBeVisible();
    expect(
      within(briefForm).getByRole('region', { name: 'Gulir Form tabel Decision Brief' }),
    ).toHaveAttribute('tabindex', '0');
    const table = within(briefForm).getByRole('table', { name: 'Form tabel Decision Brief' });
    for (const heading of [
      'No.',
      'Bahasan',
      'Putusan/Tindak Lanjut',
      'PIC',
      'Output',
      'Target Penyelesaian',
    ]) {
      expect(within(table).getByRole('columnheader', { name: heading })).toBeVisible();
    }
    expect(table).toHaveTextContent('Evaluasi triwulan');
    expect(table).toHaveTextContent('PIC revisi terbaru');
    expect(table).toHaveTextContent('Output revisi terbaru');
    expect(table).toHaveTextContent('15 Januari 2027');
    const decisionInput = screen.getByRole('textbox', {
      name: 'Putusan atau tindak lanjut untuk Evaluasi triwulan',
    });
    await waitFor(() => expect(decisionInput).toHaveValue('Gunakan indikator layanan terbaru.'));

    await userActions.click(screen.getByRole('button', { name: 'Cetak Decision Brief' }));
    await waitFor(() => expect(printSpy).toHaveBeenCalledOnce());
  });

  it('opens the latest brief for direct editing without showing internal version history', async () => {
    const userActions = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const savedBrief = {
      id: '80000000-0000-4000-8000-000000000005',
      meeting_id: meetingId,
      source_minutes_revision_id: revisionId,
      version_number: 2,
      summary: 'Ringkasan sintetis.',
      notes: null,
      created_by_id: user.id,
      created_at: '2026-10-15T10:00:00Z',
      is_stale: false,
      approval_state: 'DRAFT',
      approval_events: [],
      decisions: [
        {
          decision_id: decisionId,
          source_decision_text: 'Lengkapi laporan triwulan',
          source_agenda_id: meeting.agendas[0].id,
          source_agenda_title: 'Evaluasi layanan',
          source_discussion_id: revisions[0].discussions[0].id,
          source_discussion_subject: 'Evaluasi triwulan',
          brief_text: 'Pastikan laporan triwulan diterima tepat waktu.',
          priority: '',
          editorial_note: null,
          position: 1,
        },
      ],
    };
    const updatedBrief = {
      ...savedBrief,
      id: '80000000-0000-4000-8000-000000000006',
      version_number: 3,
      decisions: [
        {
          ...savedBrief.decisions[0],
          brief_text: 'Laporan triwulan diselesaikan tepat waktu.',
        },
      ],
    };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url.endsWith('/minutes-revisions')) return jsonResponse(revisions);
        if (url.endsWith('/decision-briefs') && init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>;
          expect(body.source_minutes_revision_id).toBe(revisionId);
          expect(body.decisions).toEqual([
            {
              decision_id: decisionId,
              brief_text: 'Laporan triwulan diselesaikan tepat waktu.',
              priority: '',
              editorial_note: null,
            },
          ]);
          return jsonResponse(updatedBrief, 201);
        }
        if (url.endsWith('/decision-briefs')) return jsonResponse([savedBrief]);
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} targetMeetingId={meetingId} />);

    const decisionInput = await screen.findByRole('textbox', {
      name: 'Putusan atau tindak lanjut untuk Evaluasi triwulan',
    });
    expect(decisionInput).toHaveValue('Pastikan laporan triwulan diterima tepat waktu.');
    expect(screen.getByRole('button', { name: 'Simpan perubahan' })).toBeVisible();
    expect(screen.queryByText('Histori versi')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Versi 2' })).not.toBeInTheDocument();
    expect(screen.queryByText('Draf')).not.toBeInTheDocument();

    await userActions.clear(decisionInput);
    await userActions.type(decisionInput, 'Laporan triwulan diselesaikan tepat waktu.');
    await userActions.click(screen.getByRole('button', { name: 'Simpan perubahan' }));
    expect(await screen.findByText('Perubahan Decision Brief tersimpan.')).toBeVisible();
    expect(decisionInput).toHaveValue('Laporan triwulan diselesaikan tepat waktu.');
  });

  it('saves the editable Decision Brief table and keeps internal versions out of the interface', async () => {
    const userActions = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const savedBrief = {
      id: '80000000-0000-4000-8000-000000000001',
      meeting_id: meetingId,
      source_minutes_revision_id: revisionId,
      version_number: 1,
      summary: `${meeting.meeting_number} · ${meeting.title}`,
      notes: null,
      created_by_id: user.id,
      created_at: '2026-10-15T10:00:00Z',
      is_stale: false,
      approval_state: 'DRAFT',
      approval_events: [],
      decisions: [
        {
          decision_id: decisionId,
          source_decision_text: 'Lengkapi laporan triwulan',
          source_agenda_id: meeting.agendas[0].id,
          source_agenda_title: 'Evaluasi layanan',
          source_discussion_id: revisions[0].discussions[0].id,
          source_discussion_subject: 'Evaluasi triwulan',
          brief_text: 'Prioritaskan pelaporan triwulan.',
          priority: '',
          editorial_note: null,
          position: 1,
        },
      ],
    };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url.endsWith('/minutes-revisions')) return jsonResponse(revisions);
        if (url.endsWith('/decision-briefs') && init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>;
          expect(body.source_minutes_revision_id).toBe(revisionId);
          expect(body.summary).toContain(meeting.meeting_number);
          expect(body.notes).toBeNull();
          expect(body.decisions).toEqual([
            {
              decision_id: decisionId,
              brief_text: 'Prioritaskan pelaporan triwulan.',
              priority: '',
              editorial_note: null,
            },
          ]);
          expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
          return jsonResponse(savedBrief, 201);
        }
        if (url.endsWith('/decision-briefs')) return jsonResponse([]);
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} targetMeetingId={meetingId} />);

    const decisionInput = await screen.findByRole('textbox', {
      name: 'Putusan atau tindak lanjut untuk Evaluasi triwulan',
    });
    expect(decisionInput).toHaveAttribute('rows', '2');
    expect(screen.queryByText(/putusan diringkas/)).not.toBeInTheDocument();
    await userActions.type(decisionInput, 'Prioritaskan pelaporan triwulan.');
    expect(screen.queryByText(/putusan diringkas/)).not.toBeInTheDocument();
    await userActions.click(screen.getByRole('button', { name: 'Simpan Decision Brief' }));

    expect(await screen.findByText('Perubahan Decision Brief tersimpan.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Simpan perubahan' })).toBeVisible();
    expect(screen.getByText('Belum diajukan')).toBeVisible();
    expect(screen.queryByText('Histori versi')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Versi 1' })).not.toBeInTheDocument();
    expect(screen.queryByText('Draf')).not.toBeInTheDocument();
  });
  it('preserves unsaved changes after a source conflict without resubmitting them', async () => {
    const userActions = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const latestRevision = {
      ...revisions[0],
      id: '40000000-0000-4000-8000-000000000002',
      revision_number: 4,
      discussions: [
        {
          ...revisions[0].discussions[0],
          id: '60000000-0000-4000-8000-000000000002',
          decisions: [
            {
              ...revisions[0].discussions[0].decisions[0],
              id: '70000000-0000-4000-8000-000000000002',
              decision_text: 'Gunakan indikator layanan terbaru',
            },
          ],
        },
      ],
    };
    let minutesReads = 0;
    let briefWrites = 0;
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url.endsWith('/minutes-revisions')) {
          minutesReads += 1;
          return jsonResponse(minutesReads === 1 ? revisions : [latestRevision]);
        }
        if (url.endsWith('/decision-briefs') && init?.method === 'POST') {
          briefWrites += 1;
          return jsonResponse({ detail: 'Notulensi telah berubah.' }, 409);
        }
        if (url.endsWith('/decision-briefs')) return jsonResponse([]);
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} targetMeetingId={meetingId} />);

    const decisionInput = await screen.findByRole('textbox', {
      name: 'Putusan atau tindak lanjut untuk Evaluasi triwulan',
    });
    await userActions.type(decisionInput, 'Ringkasan yang sedang diperbaiki.');
    await userActions.click(screen.getByRole('button', { name: 'Simpan Decision Brief' }));

    expect(
      await screen.findByRole('heading', { name: 'Perubahan yang belum tersimpan' }),
    ).toBeVisible();
    expect(screen.getByText('Isi Decision Brief: Ringkasan yang sedang diperbaiki.')).toBeVisible();
    expect(
      screen.getByText(
        'Notulensi berubah sejak halaman dibuka. Sumber terbaru sudah dimuat ulang; periksa setiap putusan lalu simpan kembali.',
      ),
    ).toBeVisible();
    expect(briefWrites).toBe(1);
    expect(minutesReads).toBe(2);
  });
  it.each([
    {
      roleCode: 'REKTOR',
      roleLabel: 'Rektor',
      email: 'rektor@example.test',
      fullName: 'Rektor Uji',
      canCreateBrief: false,
    },
    {
      roleCode: 'MANAGER_LEGAL',
      roleLabel: 'Manager Legal',
      email: 'manager-legal@example.test',
      fullName: 'Manager Legal Uji',
      canCreateBrief: true,
    },
  ])(
    'allows $roleLabel to review a pending Decision Brief without editing its content',
    async ({ roleCode, email, fullName, canCreateBrief }) => {
      const userActions = userEvent.setup();
      document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
      const reviewer = {
        ...user,
        id: '20000000-0000-4000-8000-000000000010',
        email,
        full_name: fullName,
        roles: [roleCode],
      };
      const pendingBrief = {
        id: '80000000-0000-4000-8000-000000000003',
        meeting_id: meetingId,
        source_minutes_revision_id: revisionId,
        version_number: 1,
        summary: 'Ringkasan keputusan sintetis.',
        notes: null,
        created_by_id: user.id,
        created_at: '2026-10-15T10:00:00Z',
        is_stale: false,
        approval_state: 'PENDING_APPROVAL',
        approval_events: [],
        decisions: [
          {
            decision_id: decisionId,
            source_decision_text: 'Lengkapi laporan triwulan',
            source_agenda_id: meeting.agendas[0].id,
            source_agenda_title: 'Evaluasi layanan',
            source_discussion_id: revisions[0].discussions[0].id,
            source_discussion_subject: 'Evaluasi triwulan',
            brief_text: null,
            priority: '',
            editorial_note: null,
            position: 1,
          },
        ],
      };
      const approvedBrief = { ...pendingBrief, approval_state: 'APPROVED' };
      const fetchMock = vi.fn(
        async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
          const url = String(input);
          if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
          if (url.endsWith('/minutes-revisions')) return jsonResponse(revisions);
          if (
            url.endsWith(`/decision-briefs/${pendingBrief.id}/approve`) &&
            init?.method === 'POST'
          ) {
            expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
            return jsonResponse(approvedBrief);
          }
          if (url.endsWith('/decision-briefs')) return jsonResponse([pendingBrief]);
          throw new Error(`Unexpected request: ${url}`);
        },
      );
      vi.stubGlobal('fetch', fetchMock);
      render(<DecisionBriefEditor authenticatedUser={reviewer} targetMeetingId={meetingId} />);

      expect(await screen.findByText('Menunggu persetujuan')).toBeVisible();
      expect(screen.getByRole('button', { name: 'Cetak Decision Brief' })).toBeVisible();
      const newVersionInput = screen.queryByRole('textbox', {
        name: 'Putusan atau tindak lanjut untuk Evaluasi triwulan',
      });
      if (canCreateBrief) {
        expect(newVersionInput).toBeVisible();
      } else {
        expect(newVersionInput).not.toBeInTheDocument();
      }
      const briefTable = screen.getByRole('table', {
        name: canCreateBrief ? 'Form tabel Decision Brief' : 'Tabel Decision Brief',
      });
      expect(briefTable).not.toHaveTextContent('Lengkapi laporan triwulan');
      expect(screen.queryByRole('button', { name: 'Ajukan persetujuan' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Setujui' })).toBeVisible();
      expect(screen.getByLabelText('Alasan penolakan')).toBeVisible();
      expect(
        screen.queryByText('Akun ini hanya dapat membaca Decision Brief.'),
      ).not.toBeInTheDocument();
      expect(screen.queryByText('Histori versi')).not.toBeInTheDocument();

      await userActions.click(screen.getByRole('button', { name: 'Setujui' }));

      expect(await screen.findByText('Disetujui')).toBeVisible();
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/v1/meetings/${meetingId}/decision-briefs/${pendingBrief.id}/approve`,
        expect.objectContaining({ method: 'POST', credentials: 'include' }),
      );
    },
  );
  it('requires a rejection reason and updates the approval history', async () => {
    const userActions = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const pendingBrief = {
      id: '80000000-0000-4000-8000-000000000002',
      meeting_id: meetingId,
      source_minutes_revision_id: revisionId,
      version_number: 1,
      summary: 'Ringkasan untuk ditinjau.',
      notes: null,
      created_by_id: '20000000-0000-4000-8000-000000000009',
      created_at: '2026-10-15T10:00:00Z',
      is_stale: false,
      approval_state: 'PENDING_APPROVAL',
      approval_events: [
        {
          id: '90000000-0000-4000-8000-000000000001',
          event_number: 1,
          event_type: 'SUBMITTED',
          actor_user_id: '20000000-0000-4000-8000-000000000009',
          actor_roles: ['WAREK'],
          reason: null,
          correlation_id: null,
          occurred_at: '2026-10-15T10:00:00Z',
        },
      ],
      decisions: [],
    };
    const rejectedBrief = {
      ...pendingBrief,
      approval_state: 'REJECTED',
      approval_events: [
        ...pendingBrief.approval_events,
        {
          id: '90000000-0000-4000-8000-000000000002',
          event_number: 2,
          event_type: 'REJECTED',
          actor_user_id: user.id,
          actor_roles: ['SEKRETARIAT'],
          reason: 'Perlu diperjelas.',
          correlation_id: null,
          occurred_at: '2026-10-15T11:00:00Z',
        },
      ],
    };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url.endsWith('/minutes-revisions')) return jsonResponse(revisions);
        if (url.endsWith(`/decision-briefs/${pendingBrief.id}/reject`) && init?.method === 'POST') {
          expect(url).toBe(
            `/api/v1/meetings/${meetingId}/decision-briefs/${pendingBrief.id}/reject`,
          );
          expect(JSON.parse(String(init.body))).toEqual({ reason: 'Perlu diperjelas.' });
          expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
          return jsonResponse(rejectedBrief);
        }
        if (url.endsWith('/decision-briefs')) return jsonResponse([pendingBrief]);
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<DecisionBriefEditor authenticatedUser={user} targetMeetingId={meetingId} />);

    expect(await screen.findByText('Menunggu persetujuan')).toBeVisible();
    const rejectButton = screen.getByRole('button', { name: 'Tolak' });
    expect(rejectButton).toBeDisabled();
    await userActions.type(
      screen.getByRole('textbox', { name: 'Alasan penolakan' }),
      'Perlu diperjelas.',
    );
    expect(rejectButton).toBeEnabled();
    await userActions.click(rejectButton);

    expect(await screen.findByText('Ditolak')).toBeVisible();
    expect(screen.getByText('Catatan penolakan: Perlu diperjelas.')).toBeVisible();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  });
});
