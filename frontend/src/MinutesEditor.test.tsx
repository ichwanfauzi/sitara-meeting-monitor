import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MinutesEditor from './MinutesEditor';
import type { MinutesRevision } from './api';

const userId = '20000000-0000-4000-8000-000000000001';
const notetakerId = userId;
const otherUserId = '20000000-0000-4000-8000-000000000002';
const meetingId = '30000000-0000-4000-8000-000000000001';
const firstRevisionId = '40000000-0000-4000-8000-000000000001';
const latestRevisionId = '40000000-0000-4000-8000-000000000002';

const user = {
  id: userId,
  email: 'sekretariat@example.test',
  full_name: 'Sekretariat Uji',
  roles: ['SEKRETARIAT'],
};

const meeting = {
  id: meetingId,
  meeting_number: 'RAPIM-2026-001',
  title: 'Rapat koordinasi sintetis',
  meeting_type: 'RAPIM',
  meeting_date: '2026-10-15',
  start_time: '09:00:00',
  end_time: null,
  location: 'Ruang Uji',
  chairperson_id: otherUserId,
  notetaker_id: notetakerId,
  created_by_id: otherUserId,
  status: 'LIVE',
  created_at: '2026-10-15T08:00:00Z',
  updated_at: '2026-10-15T08:00:00Z',
  agendas: [
    {
      id: '50000000-0000-4000-8000-000000000001',
      meeting_id: meetingId,
      agenda_number: 1,
      title: 'Evaluasi sintetis',
      agenda_description: 'Agenda fixture untuk tes.',
      lead_user_id: otherUserId,
      duration_minutes: 30,
      sort_order: 1,
    },
  ],
  participants: [],
};

const firstRevision = {
  id: firstRevisionId,
  meeting_id: meetingId,
  revision_number: 1,
  format_version: 1 as const,
  content: 'Catatan awal sintetis',
  discussions: [],
  created_by_id: userId,
  created_at: '2026-10-15T08:30:00Z',
};

const structuredRevision: MinutesRevision = {
  ...firstRevision,
  format_version: 2,
  content: null,
  discussions: [
    {
      id: '60000000-0000-4000-8000-000000000001',
      agenda_id: meeting.agendas[0].id,
      discussion_number: 1,
      subject: 'Evaluasi triwulan',
      content: 'Pembahasan awal berdasarkan data sintetis.',
      decisions: [
        {
          id: '70000000-0000-4000-8000-000000000001',
          discussion_id: '60000000-0000-4000-8000-000000000001',
          decision_number: 1,
          decision_text: 'Lengkapi laporan',
          target_text: null,
          output_expected: 'Laporan revisi',
          target_date: '2026-11-30',
          is_action_item: true,
        },
      ],
    },
  ],
};
const newerStructuredRevision: MinutesRevision = {
  ...structuredRevision,
  id: '40000000-0000-4000-8000-000000000004',
  revision_number: 2,
  discussions: structuredRevision.discussions.map((discussion) => ({
    ...discussion,
    id: '60000000-0000-4000-8000-000000000002',
    content: 'Revisi server terbaru.',
    decisions: discussion.decisions.map((decision) => ({
      ...decision,
      id: '70000000-0000-4000-8000-000000000002',
      discussion_id: '60000000-0000-4000-8000-000000000002',
    })),
  })),
};
const secondMeeting = {
  ...meeting,
  id: '30000000-0000-4000-8000-000000000002',
  meeting_number: 'RAPIM-2026-002',
  title: 'Rapat kedua sintetis',
};
const secondMeetingRevision = {
  ...firstRevision,
  id: '40000000-0000-4000-8000-000000000003',
  meeting_id: secondMeeting.id,
  content: 'Notulen rapat kedua',
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function setupEditor({
  currentUser = user,
  meetings = [meeting],
  revisions = [structuredRevision],
  targetMeetingId = meetingId,
}: {
  currentUser?: typeof user;
  meetings?: (typeof meeting)[];
  revisions?: MinutesRevision[];
  targetMeetingId?: string | null;
} = {}) {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
  fetchMock
    .mockResolvedValueOnce(jsonResponse(currentUser))
    .mockResolvedValueOnce(jsonResponse(meetings))
    .mockResolvedValueOnce(jsonResponse(revisions));
  render(<MinutesEditor targetMeetingId={targetMeetingId ?? undefined} />);
  return fetchMock;
}

describe('MinutesEditor', () => {
  beforeEach(() => {
    document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows the Rapim list first and opens the chosen meeting minutes form', async () => {
    const fetchMock = setupEditor({
      meetings: [meeting, secondMeeting],
      targetMeetingId: null,
    });

    const firstMeetingLink = await screen.findByRole('link', {
      name: /RAPIM-2026-001 · Rapat koordinasi sintetis/,
    });
    expect(screen.getByRole('heading', { name: 'Notulensi rapat' })).toBeInTheDocument();
    expect(screen.queryByText('Pilih rapat untuk membuka notulensi rapat.')).toBeNull();
    expect(screen.getByText('RAPIM · NOTULENSI')).toBeInTheDocument();
    expect(screen.getByText('Buka salah satu rapat untuk melanjutkan.')).toBeInTheDocument();
    expect(screen.getByText('2 rapat ditampilkan')).toBeInTheDocument();
    expect(firstMeetingLink).toHaveAttribute('href', `#notulensi/${meeting.id}`);
    expect(screen.queryByRole('table', { name: 'Tabel pengisian hasil rapat' })).toBeNull();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain(
      `/api/v1/meetings/${meeting.id}/minutes-revisions`,
    );
  });

  it('clears meeting search and restores the document-selection list', async () => {
    const userActions = userEvent.setup();
    setupEditor({
      meetings: [meeting, secondMeeting],
      targetMeetingId: null,
    });

    const search = await screen.findByRole('searchbox', { name: 'Cari rapat' });
    await userActions.type(search, 'tidak ditemukan');
    expect(await screen.findByText('Tidak ada rapat yang cocok.')).toBeVisible();
    await userActions.click(screen.getByRole('button', { name: 'Hapus pencarian rapat' }));

    expect(search).toHaveValue('');
    expect(
      await screen.findByRole('link', { name: /RAPIM-2026-001 · Rapat koordinasi sintetis/ }),
    ).toBeVisible();
    expect(
      screen.getByRole('link', { name: /RAPIM-2026-002 · Rapat kedua sintetis/ }),
    ).toBeVisible();
  });

  it('loads only server meeting data and displays agenda and active revision metadata', async () => {
    const fetchMock = setupEditor();

    expect(
      await screen.findByRole('heading', { name: 'Notulensi rapat', level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Isi resmi' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Rapat terpilih' })).toBeInTheDocument();
    expect(screen.queryByRole('searchbox', { name: 'Pilih rapat' })).toBeNull();
    expect(screen.queryByText('RAPIM · NOTULENSI')).toBeNull();
    expect(
      screen.queryByText('Isi hasil rapat dalam tabel, lalu simpan setelah ditinjau.'),
    ).toBeNull();
    expect(screen.queryByText(/Satu baris mewakili satu pokok pembahasan/)).toBeNull();
    expect(screen.queryByText(/PIC pada tabel ini adalah usulan/)).toBeNull();
    expect(screen.queryByText('HASIL NOTULEN')).toBeNull();
    expect(screen.queryByText('Pratinjau mengikuti notulensi yang sudah tersimpan.')).toBeNull();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === 'STRONG' && element.textContent?.includes('RAPIM-2026-001') === true,
      ),
    ).toBeInTheDocument();
    const form = await screen.findByRole('region', { name: 'Form pengisian hasil rapat' });
    expect(within(form).getByRole('heading', { name: 'Evaluasi sintetis' })).toBeInTheDocument();
    expect(screen.getByLabelText('Judul pembahasan 1 agenda 1')).toHaveValue('Evaluasi triwulan');
    expect(screen.queryByText('Revisi aktif: 1')).not.toBeInTheDocument();
    expect(screen.queryByText(/Riwayat revisi/)).not.toBeInTheDocument();
    expect(
      screen.queryByText((_, element) => element?.textContent === `Pembuat (ID): ${userId}`),
    ).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      '/api/v1/auth/me',
      '/api/v1/meetings?limit=100&offset=0',
      `/api/v1/meetings/${meetingId}/minutes-revisions`,
    ]);
  });

  it('loads structured discussion and decision data under the matching agenda', async () => {
    setupEditor({ revisions: [structuredRevision] });

    expect(await screen.findByLabelText('Judul pembahasan 1 agenda 1')).toHaveValue(
      'Evaluasi triwulan',
    );
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Pembahasan awal berdasarkan data sintetis.',
    );
    expect(screen.getByLabelText('Isi putusan 1 pembahasan 1')).toHaveValue('Lengkapi laporan');
  });

  it('keeps the selected minutes workspace focused on its form and actions', async () => {
    setupEditor();

    const form = await screen.findByRole('region', { name: 'Form pengisian hasil rapat' });
    expect(form).toHaveAttribute('tabindex', '0');
    expect(screen.queryByRole('searchbox', { name: 'Pilih rapat' })).toBeNull();
    expect(screen.getByRole('heading', { name: 'Notulensi rapat' })).toBeVisible();
    expect(screen.getByText('Dapat menyunting')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Cetak hasil notulensi' })).toBeInTheDocument();
    const saveButton = screen.getByRole('button', { name: 'Simpan notulensi' });
    const previewHeading = screen.getByRole('heading', { name: 'Pratinjau tabel' });
    expect(
      saveButton.compareDocumentPosition(previewHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByText(/Satu baris mewakili satu pokok pembahasan/)).toBeNull();
    expect(screen.queryByText(/PIC pada tabel ini adalah usulan/)).toBeNull();
    expect(screen.queryByText('Pratinjau mengikuti notulensi yang sudah tersimpan.')).toBeNull();
  });

  it('shows an agenda form with decision fields and a formal table preview', async () => {
    const userActions = userEvent.setup();
    setupEditor({ revisions: [structuredRevision] });

    const entryForm = await screen.findByRole('region', { name: 'Form pengisian hasil rapat' });
    expect(within(entryForm).getByRole('heading', { name: 'Pokok bahasan 1' })).toBeInTheDocument();
    expect(within(entryForm).getByRole('heading', { name: 'Putusan 1' })).toBeInTheDocument();
    expect(within(entryForm).getByLabelText('Isi putusan 1 pembahasan 1')).toBeInTheDocument();

    const picSuggestion = within(entryForm).getByLabelText('PIC usulan');
    await userActions.type(picSuggestion, 'Warek bidang akademik');
    expect(picSuggestion).toHaveValue('Warek bidang akademik');

    const supportingPicSuggestion = within(entryForm).getByLabelText('PIC pendukung (opsional)');
    expect(supportingPicSuggestion).not.toBeRequired();
    await userActions.type(supportingPicSuggestion, 'Sekretariat teknis, Biro SDM');
    expect(supportingPicSuggestion).toHaveValue('Sekretariat teknis, Biro SDM');

    const printPreview = screen.getByRole('table', { name: 'Pratinjau hasil rapat' });
    expect(within(printPreview).getByText('Lengkapi laporan')).toBeInTheDocument();
    expect(within(printPreview).getByText('Sekretariat teknis, Biro SDM')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cetak hasil notulensi' })).toBeDisabled();
  });

  it('saves the optional supporting PIC suggestion with the structured minutes', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor({ revisions: [structuredRevision] });
    const savedRevision = {
      ...structuredRevision,
      id: latestRevisionId,
      revision_number: 2,
      discussions: structuredRevision.discussions.map((discussion) => ({
        ...discussion,
        id: '60000000-0000-4000-8000-000000000003',
        decisions: discussion.decisions.map((decision) => ({
          ...decision,
          id: '70000000-0000-4000-8000-000000000003',
          discussion_id: '60000000-0000-4000-8000-000000000003',
          supporting_pic_suggestion: 'Sekretariat teknis, Biro SDM',
        })),
      })),
    };
    fetchMock.mockResolvedValueOnce(jsonResponse(savedRevision, 201));

    const supportingPicSuggestion = await screen.findByLabelText('PIC pendukung (opsional)');
    await userActions.type(supportingPicSuggestion, 'Sekretariat teknis, Biro SDM');
    await userActions.click(screen.getByRole('button', { name: 'Simpan notulensi' }));

    expect(await screen.findByText('Notulensi tersimpan.')).toBeInTheDocument();
    const writeCall = fetchMock.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(
      JSON.parse(writeCall?.[1]?.body as string).discussions[0].decisions[0]
        .supporting_pic_suggestion,
    ).toBe('Sekretariat teknis, Biro SDM');
    expect(
      within(screen.getByRole('table', { name: 'Pratinjau hasil rapat' })).getByText(
        'Sekretariat teknis, Biro SDM',
      ),
    ).toBeInTheDocument();
  });

  it('groups agenda entry fields into a guided form while keeping the print preview table', async () => {
    setupEditor({ revisions: [structuredRevision] });

    const form = await screen.findByRole('region', { name: 'Form pengisian hasil rapat' });
    expect(within(form).getByRole('heading', { name: 'Evaluasi sintetis' })).toBeVisible();
    expect(within(form).getByLabelText('Isi pembahasan 1 agenda 1')).toBeVisible();
    expect(within(form).getByLabelText('Isi putusan 1 pembahasan 1')).toBeVisible();
    expect(within(form).getByLabelText('PIC usulan')).toBeVisible();
    expect(within(form).getByLabelText('PIC pendukung (opsional)')).toBeVisible();
    expect(within(form).getByLabelText('Output yang diharapkan')).toBeVisible();
    expect(within(form).getByLabelText('Target penyelesaian berupa tanggal')).toBeVisible();
    expect(screen.getByRole('table', { name: 'Pratinjau hasil rapat' })).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Tabel pengisian hasil rapat' })).toBeNull();
  });

  it('shows follow-up fields only when a decision requires an action item', async () => {
    const userActions = userEvent.setup();
    const decisionOnlyRevision: MinutesRevision = {
      ...structuredRevision,
      discussions: structuredRevision.discussions.map((discussion) => ({
        ...discussion,
        decisions: discussion.decisions.map((decision) => ({
          ...decision,
          is_action_item: false,
        })),
      })),
    };
    setupEditor({ revisions: [decisionOnlyRevision] });

    const form = await screen.findByRole('region', { name: 'Form pengisian hasil rapat' });
    const followUpToggle = within(form).getByRole('checkbox', {
      name: 'Memerlukan tindak lanjut',
    });

    expect(followUpToggle).not.toBeChecked();
    expect(within(form).queryByLabelText('PIC usulan')).not.toBeInTheDocument();
    expect(within(form).queryByLabelText('Output yang diharapkan')).not.toBeInTheDocument();
    expect(
      within(form).queryByLabelText('Target penyelesaian berupa tanggal'),
    ).not.toBeInTheDocument();

    await userActions.click(followUpToggle);

    expect(within(form).getByLabelText('PIC usulan')).toBeVisible();
    expect(within(form).getByLabelText('Output yang diharapkan')).toBeVisible();
    expect(within(form).getByLabelText('Target penyelesaian berupa tanggal')).toBeVisible();
  });

  it('shows archived minutes as a read-only result table without the entry form', async () => {
    const archivedMeeting = { ...meeting, status: 'ARCHIVED' };
    setupEditor({ meetings: [archivedMeeting], revisions: [structuredRevision] });

    const resultTable = await screen.findByRole('table', { name: 'Pratinjau hasil rapat' });
    expect(resultTable).toHaveTextContent('Pembahasan awal berdasarkan data sintetis.');
    expect(resultTable).toHaveTextContent('Lengkapi laporan');
    expect(screen.queryByRole('region', { name: 'Form pengisian hasil rapat' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Simpan notulensi' })).toBeNull();
    expect(screen.queryByLabelText('Isi pembahasan 1 agenda 1')).toBeNull();
  });

  it('opens the requested meeting from a meeting-specific route', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor({
      meetings: [meeting, secondMeeting],
      revisions: [secondMeetingRevision],
      targetMeetingId: secondMeeting.id,
    });

    expect(
      await screen.findByRole('region', { name: 'Form pengisian hasil rapat' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('searchbox', { name: 'Pilih rapat' })).toBeNull();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === 'STRONG' &&
          element.textContent?.includes(secondMeeting.meeting_number) === true,
      ),
    ).toBeInTheDocument();
    await userActions.click(screen.getByText('Buka catatan notulensi terdahulu'));
    expect(screen.getByText('Notulen rapat kedua')).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain(
      `/api/v1/meetings/${secondMeeting.id}/minutes-revisions`,
    );
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain(
      `/api/v1/meetings/${meeting.id}/minutes-revisions`,
    );
  });

  it('does not fall back to another meeting when the requested meeting is outside the accessible list', async () => {
    const inaccessibleMeetingId = '30000000-0000-4000-8000-000000000099';
    const fetchMock = setupEditor({
      meetings: [meeting],
      targetMeetingId: inaccessibleMeetingId,
    });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Rapat tidak termasuk dalam cakupan akses Anda.',
    );
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain(
      `/api/v1/meetings/${meeting.id}/minutes-revisions`,
    );
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain(
      `/api/v1/meetings/${inaccessibleMeetingId}/minutes-revisions`,
    );
  });

  it('uses the guided editor for legacy revisions and keeps their text as a readable source', async () => {
    const userActions = userEvent.setup();
    setupEditor({ revisions: [firstRevision] });

    const entryForm = await screen.findByRole('region', { name: 'Form pengisian hasil rapat' });
    expect(screen.queryByLabelText('Isi notulensi')).not.toBeInTheDocument();
    expect(
      within(entryForm).getByText('Belum ada pokok bahasan untuk agenda ini.'),
    ).toBeInTheDocument();
    await userActions.click(screen.getByText('Buka catatan notulensi terdahulu'));
    expect(screen.getByText('Catatan awal sintetis')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Simpan notulensi' })).toBeDisabled();
  });

  it('creates one complete structured snapshot from the agenda editor', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor({ revisions: [] });
    fetchMock.mockResolvedValueOnce(jsonResponse(structuredRevision, 201));

    await within(
      await screen.findByRole('region', { name: 'Form pengisian hasil rapat' }),
    ).findByText('Belum ada pokok bahasan untuk agenda ini.');
    await userActions.click(screen.getByRole('button', { name: 'Isi pokok bahasan' }));
    await userActions.type(
      screen.getByLabelText('Judul pembahasan 1 agenda 1'),
      'Evaluasi triwulan',
    );
    await userActions.type(
      screen.getByLabelText('Isi pembahasan 1 agenda 1'),
      'Pembahasan baru sintetis.',
    );
    await userActions.click(screen.getByRole('button', { name: 'Tambah putusan' }));
    await userActions.type(screen.getByLabelText('Isi putusan 1 pembahasan 1'), 'Lengkapi laporan');
    await userActions.click(screen.getByRole('button', { name: 'Simpan notulensi' }));

    expect(await screen.findByText('Notulensi tersimpan.')).toBeInTheDocument();
    const writeCall = fetchMock.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(JSON.parse(writeCall?.[1]?.body as string)).toEqual({
      format_version: 2,
      content: null,
      base_revision_id: null,
      discussions: [
        {
          agenda_id: meeting.agendas[0].id,
          subject: 'Evaluasi triwulan',
          content: 'Pembahasan baru sintetis.',
          decisions: [
            {
              decision_text: 'Lengkapi laporan',
              pic_suggestion: null,
              supporting_pic_suggestion: null,
              output_expected: null,
              target_date: null,
              target_text: null,
              is_action_item: false,
            },
          ],
        },
      ],
    });
  });

  it('saves a complete structured snapshot and retains the draft after a stale-base conflict', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor({ revisions: [structuredRevision] });
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Minutes changed since the supplied base revision' }, 409),
      )
      .mockResolvedValueOnce(jsonResponse([structuredRevision, newerStructuredRevision]));

    const discussionInput = await screen.findByLabelText('Isi pembahasan 1 agenda 1');
    await userActions.clear(discussionInput);
    await userActions.type(discussionInput, 'Draf terstruktur lokal yang dipertahankan');
    await userActions.click(screen.getByRole('button', { name: 'Simpan notulensi' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/notulensi terbaru/i);
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Draf terstruktur lokal yang dipertahankan',
    );
    const writeCalls = fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(writeCalls).toHaveLength(1);
    expect(JSON.parse(writeCalls[0][1]?.body as string)).toEqual({
      format_version: 2,
      content: null,
      base_revision_id: firstRevisionId,
      discussions: [
        {
          agenda_id: meeting.agendas[0].id,
          subject: 'Evaluasi triwulan',
          content: 'Draf terstruktur lokal yang dipertahankan',
          decisions: [
            {
              decision_text: 'Lengkapi laporan',
              pic_suggestion: null,
              supporting_pic_suggestion: null,
              output_expected: 'Laporan revisi',
              target_date: '2026-11-30',
              target_text: null,
              is_action_item: true,
            },
          ],
        },
      ],
    });

    await userActions.click(screen.getByRole('button', { name: 'Muat notulensi terbaru' }));
    expect(await screen.findByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Revisi server terbaru.',
    );
    expect(screen.getByText(/Draf terstruktur lokal yang dipertahankan/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );
  });

  it('keeps unsaved structured minutes and offers navigation back to the meeting list', async () => {
    const userActions = userEvent.setup();
    setupEditor({
      meetings: [meeting, secondMeeting],
      revisions: [structuredRevision],
    });

    const discussionInput = await screen.findByLabelText('Isi pembahasan 1 agenda 1');
    await userActions.clear(discussionInput);
    await userActions.type(discussionInput, 'Draf agenda yang belum disimpan');

    expect(screen.getByRole('link', { name: 'Kembali ke daftar rapat' })).toHaveAttribute(
      'href',
      '#notulensi',
    );
    expect(screen.queryByRole('searchbox', { name: 'Pilih rapat' })).toBeNull();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === 'STRONG' &&
          element.textContent?.includes(meeting.meeting_number) === true,
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Draf agenda yang belum disimpan',
    );
  });

  it('saves with the active base revision and uses the server response without duplicate submission', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();
    let resolveSave: (response: Response) => void = () => undefined;
    fetchMock.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        resolveSave = resolve;
      }),
    );

    const editor = await screen.findByLabelText('Isi pembahasan 1 agenda 1');
    await userActions.clear(editor);
    await userActions.type(editor, 'Notulen diperbarui secara eksplisit');
    const saveButton = screen.getByRole('button', { name: 'Simpan notulensi' });
    await userActions.click(saveButton);
    expect(saveButton).toBeDisabled();
    await userActions.click(saveButton);

    const saveCall = fetchMock.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(saveCall?.[0]).toBe(`/api/v1/meetings/${meetingId}/minutes-revisions`);
    expect(JSON.parse(saveCall?.[1]?.body as string)).toEqual({
      format_version: 2,
      base_revision_id: firstRevisionId,
      content: null,
      discussions: [
        {
          agenda_id: meeting.agendas[0].id,
          subject: 'Evaluasi triwulan',
          content: 'Notulen diperbarui secara eksplisit',
          decisions: [
            {
              decision_text: 'Lengkapi laporan',
              pic_suggestion: null,
              supporting_pic_suggestion: null,
              output_expected: 'Laporan revisi',
              target_date: '2026-11-30',
              target_text: null,
              is_action_item: true,
            },
          ],
        },
      ],
    });
    expect(new Headers(saveCall?.[1]?.headers as HeadersInit).get('X-CSRF-Token')).toBe(
      'csrf-test-token',
    );
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );

    resolveSave(
      jsonResponse(
        {
          ...structuredRevision,
          id: latestRevisionId,
          revision_number: 2,
          discussions: structuredRevision.discussions.map((discussion) => ({
            ...discussion,
            content: 'Notulen resmi dari response server',
          })),
        },
        201,
      ),
    );
    expect(await screen.findByText('Notulensi tersimpan.')).toBeInTheDocument();
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Notulen resmi dari response server',
    );
  });

  it('preserves a conflicted draft and advances its base only after explicitly loading the latest revision', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Minutes changed since the supplied base revision' }, 409),
      )
      .mockResolvedValueOnce(jsonResponse([structuredRevision, newerStructuredRevision]));

    const editor = await screen.findByLabelText('Isi pembahasan 1 agenda 1');
    await userActions.clear(editor);
    await userActions.type(editor, 'Draf lokal yang harus dipertahankan');
    await userActions.click(screen.getByRole('button', { name: 'Simpan notulensi' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/notulensi terbaru/i);
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Draf lokal yang harus dipertahankan',
    );
    expect(screen.getByRole('button', { name: 'Simpan notulensi' })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );

    await userActions.click(screen.getByRole('button', { name: 'Muat notulensi terbaru' }));
    expect(await screen.findByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Revisi server terbaru.',
    );
    expect(document.querySelector('.minutes-preserved-draft pre')).toHaveTextContent(
      /Draf lokal yang harus dipertahankan/,
    );
    expect(screen.queryByText('Revisi aktif: 2')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );

    await userActions.clear(screen.getByLabelText('Isi pembahasan 1 agenda 1'));
    await userActions.type(
      screen.getByLabelText('Isi pembahasan 1 agenda 1'),
      'Perubahan berdasarkan revisi terbaru',
    );
    await userActions.click(screen.getByRole('button', { name: 'Simpan notulensi' }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
        2,
      ),
    );
    const retryCall = fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')[1];
    expect(JSON.parse(retryCall[1]?.body as string)).toMatchObject({
      format_version: 2,
      content: null,
      base_revision_id: newerStructuredRevision.id,
      discussions: [
        {
          agenda_id: meeting.agendas[0].id,
          subject: 'Evaluasi triwulan',
          content: 'Perubahan berdasarkan revisi terbaru',
        },
      ],
    });
  });

  it('keeps a preserved conflict draft visible without a meeting picker', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();

    const editor = await screen.findByLabelText('Isi pembahasan 1 agenda 1');
    await userActions.clear(editor);
    await userActions.type(editor, 'Draf yang masih harus disimpan');
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Minutes changed since the supplied base revision' }, 409),
      )
      .mockResolvedValueOnce(jsonResponse([structuredRevision, newerStructuredRevision]));
    await userActions.click(screen.getByRole('button', { name: 'Simpan notulensi' }));
    await screen.findByRole('alert');
    await userActions.click(screen.getByRole('button', { name: 'Muat notulensi terbaru' }));
    expect(await screen.findByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Revisi server terbaru.',
    );

    expect(screen.queryByRole('searchbox', { name: 'Pilih rapat' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Kembali ke daftar rapat' })).toHaveAttribute(
      'href',
      '#notulensi',
    );
    expect(document.querySelector('.minutes-preserved-draft pre')).toHaveTextContent(
      /Draf yang masih harus disimpan/,
    );
  });

  it('distinguishes a 409 for a meeting that is no longer LIVE and refreshes its status', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Minutes can only be edited while the meeting is LIVE' }, 409),
      )
      .mockResolvedValueOnce(jsonResponse({ ...meeting, status: 'FINAL' }));

    const editor = await screen.findByLabelText('Isi pembahasan 1 agenda 1');
    await userActions.clear(editor);
    await userActions.type(editor, 'Draf ketika rapat ditutup');
    await userActions.click(screen.getByRole('button', { name: 'Simpan notulensi' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/rapat tidak lagi berlangsung/i);
    expect(await screen.findByText('FINAL')).toBeInTheDocument();
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toBeDisabled();
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Draf ketika rapat ditutup',
    );
    expect(document.querySelector('.minutes-preserved-draft pre')).toHaveTextContent(
      /Draf ketika rapat ditutup/,
    );
    expect(
      screen.queryByRole('button', { name: 'Muat notulensi terbaru' }),
    ).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(`/api/v1/meetings/${meetingId}`);
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );
  });

  it('keeps the editor locked if meeting status cannot be refreshed', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Minutes can only be edited while the meeting is LIVE' }, 409),
      )
      .mockRejectedValueOnce(new Error('Network unavailable'))
      .mockResolvedValueOnce(jsonResponse({ ...meeting, status: 'FINAL' }));

    const editor = await screen.findByLabelText('Isi pembahasan 1 agenda 1');
    await userActions.clear(editor);
    await userActions.type(editor, 'Draf tetap terlindungi');
    await userActions.click(screen.getByRole('button', { name: 'Simpan notulensi' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/coba muat ulang status rapat/i);
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toBeDisabled();
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Draf tetap terlindungi',
    );
    expect(screen.getByRole('button', { name: 'Muat ulang status rapat' })).toBeInTheDocument();

    await userActions.click(screen.getByRole('button', { name: 'Muat ulang status rapat' }));
    expect(await screen.findByText('FINAL')).toBeInTheDocument();
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(
      1,
    );
  });

  it('lets an in-scope Warek edit minutes while the meeting is live', async () => {
    setupEditor({ currentUser: { ...user, id: otherUserId, roles: ['WAREK'] } });

    expect(await screen.findByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Pembahasan awal berdasarkan data sintetis.',
    );
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toBeEnabled();
    expect(screen.getByText('Dapat menyunting')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Simpan notulensi' })).toBeInTheDocument();
  });

  it('does not offer editing after a meeting is finalized', async () => {
    setupEditor({ meetings: [{ ...meeting, status: 'FINAL' }] });

    expect(await screen.findByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Pembahasan awal berdasarkan data sintetis.',
    );
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toBeDisabled();
    expect(screen.getByText(/Rapat tidak sedang berlangsung/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Simpan notulensi' })).not.toBeInTheDocument();
  });

  it('does not request meeting data for a Super Admin session', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ ...user, roles: ['SEKRETARIAT', 'SUPER_ADMIN'] }));
    vi.stubGlobal('fetch', fetchMock);
    render(<MinutesEditor />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/tidak memiliki akses/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('reports an expired session without requesting meetings', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: 'Authentication required' }, 401));
    vi.stubGlobal('fetch', fetchMock);
    render(<MinutesEditor />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/sesi tidak aktif/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('shows API validation errors without discarding the structured draft', async () => {
    const userActions = userEvent.setup();
    const fetchMock = setupEditor();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: 'Minutes content must not be blank' }, 422),
    );

    const editor = await screen.findByLabelText('Isi pembahasan 1 agenda 1');
    await userActions.clear(editor);
    await userActions.type(editor, 'Pembahasan valid yang ditolak server');
    await userActions.click(screen.getByRole('button', { name: 'Simpan notulensi' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Minutes content must not be blank');
    expect(screen.getByLabelText('Isi pembahasan 1 agenda 1')).toHaveValue(
      'Pembahasan valid yang ditolak server',
    );
  });

  it('shows an empty state when the meeting has no revision history', async () => {
    setupEditor({ revisions: [] });

    expect(await screen.findByText('Belum ada notulensi tersimpan.')).toBeInTheDocument();
    expect(screen.queryByText(/Riwayat revisi/)).not.toBeInTheDocument();
    expect(
      within(screen.getByRole('region', { name: 'Form pengisian hasil rapat' })).getByText(
        'Belum ada pokok bahasan untuk agenda ini.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Belum ada notulensi tersimpan.')).toBeInTheDocument();
  });
});
