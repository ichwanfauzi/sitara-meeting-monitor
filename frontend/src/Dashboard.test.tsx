import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ActionItemDetail, ActionItemSummary, AuthenticatedUser, MeetingSummary } from './api';
import { getActionItems } from './api';
import Dashboard from './Dashboard';

const unitId = '50000000-0000-4000-8000-000000000001';

const secretary: AuthenticatedUser = {
  id: '20000000-0000-4000-8000-000000000001',
  email: 'sekretariat@example.test',
  full_name: 'Sekretariat Uji',
  roles: ['SEKRETARIAT'],
};

const meeting: MeetingSummary = {
  id: '30000000-0000-4000-8000-000000000001',
  meeting_number: 'RAPIM-2026-021',
  title: 'Rapat Evaluasi Sintetis',
  meeting_date: '2026-11-20',
  status: 'DRAFT',
  version: 1,
  agendas: [
    {
      id: '31000000-0000-4000-8000-000000000001',
      agenda_number: 1,
      title: 'Evaluasi Program Uji',
      agenda_description: null,
      pic_suggestion: null,
      supporting_pic_suggestion: null,
      sort_order: 1,
    },
  ],
};

const actionItem: ActionItemSummary = {
  id: '40000000-0000-4000-8000-000000000001',
  meeting_id: meeting.id,
  source_minutes_revision_id: '41000000-0000-4000-8000-000000000001',
  source_decision_id: '42000000-0000-4000-8000-000000000001',
  disposition_id: null,
  responsible_unit: { id: unitId, unit_code: 'UNIT-UJI', name: 'Unit Uji' },
  source_revision_is_stale: false,
  title: 'Menyiapkan laporan sintetis',
  description: 'Data uji saja',
  output_expected: 'Laporan',
  due_date: '2026-11-30',
  priority: 'TINGGI',
  official_status: 'BERPROSES',
  version: 1,
  created_by_id: secretary.id,
  created_at: '2026-11-04T10:00:00Z',
  updated_at: '2026-11-05T09:00:00Z',
  completed_at: null,
  deleted_at: null,
  active_assignments: [
    {
      id: '43000000-0000-4000-8000-000000000001',
      action_item_id: '40000000-0000-4000-8000-000000000001',
      assignee_user_id: '44000000-0000-4000-8000-000000000001',
      assignee_display_name: null,
      assignee_name: 'PIC Uji',
      pic_origin_unit: { id: unitId, unit_code: 'UNIT-UJI', name: 'Unit Uji' },
      assigned_by_user_id: secretary.id,
      assignment_role: 'MAIN',
      started_at: '2026-11-04T10:00:00Z',
      ended_at: null,
      ended_by_user_id: null,
      end_reason: null,
    },
  ],
};

const actionItemDetail: ActionItemDetail = {
  ...actionItem,
  assignment_history: actionItem.active_assignments,
  progress_updates: [
    {
      id: '45000000-0000-4000-8000-000000000001',
      action_item_id: actionItem.id,
      assignment_id: actionItem.active_assignments[0].id,
      actor_user_id: actionItem.active_assignments[0].assignee_user_id!,
      submitted_as: 'PIC',
      report_text: 'Progres sintetis',
      blocker_text: null,
      progress_percent: 67,
      completion_requested: false,
      submitted_at: '2026-11-05T09:00:00Z',
      evidence: [],
    },
  ],
  status_history: [],
  completion_verifications: [],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function apiFetch({
  meetings = [meeting],
  items = [actionItem],
  details = [actionItemDetail],
  failActionItems = false,
}: {
  meetings?: MeetingSummary[];
  items?: ActionItemSummary[];
  details?: ActionItemDetail[];
  failActionItems?: boolean;
} = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse(meetings);
    if (url === '/api/v1/action-items?limit=100&offset=0') {
      return failActionItems
        ? jsonResponse({ detail: 'Dashboard unavailable' }, 503)
        : jsonResponse(items);
    }
    const detailIndex = details.findIndex((detail) => url === `/api/v1/action-items/${detail.id}`);
    if (detailIndex !== -1) return jsonResponse(details[detailIndex]);
    throw new Error(`Unexpected dashboard request: ${url}`);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('API-backed dashboard', () => {
  it('keeps task cards brief, opens details on selection, and omits recent meetings', async () => {
    const fetchMock = apiFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(<Dashboard authenticatedUser={secretary} />);

    const taskButton = await screen.findByRole('button', {
      name: /Menyiapkan laporan sintetis/,
    });
    expect(taskButton).toHaveTextContent('PIC Uji');
    expect(taskButton).not.toHaveTextContent('Laporan');
    expect(screen.queryByText('67%')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Rapat terbaru' })).not.toBeInTheDocument();

    fireEvent.click(taskButton);
    expect(await screen.findByRole('dialog', { name: 'Detail tindak lanjut' })).toBeVisible();
    expect(screen.getByText('Progres sintetis')).toBeVisible();
    expect(screen.getByText('Laporan')).toBeVisible();
  });

  it('paginates through the complete authorized Action Item collection', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          Array.from({ length: 100 }, (_, index) => ({
            ...actionItem,
            id: `50000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
          })),
        ),
      )
      .mockResolvedValueOnce(jsonResponse([]));
    vi.stubGlobal('fetch', fetchMock);

    expect(await getActionItems()).toHaveLength(100);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/action-items?limit=100&offset=0',
      expect.objectContaining({ credentials: 'include' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/action-items?limit=100&offset=100',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('renders authorized meeting and action-item data from backend APIs', async () => {
    const fetchMock = apiFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(<Dashboard authenticatedUser={secretary} />);

    const taskList = await screen.findByRole('region', { name: 'Tindak lanjut lintas Rapim' });
    expect(within(taskList).getByText('Menyiapkan laporan sintetis')).toBeInTheDocument();
    const calendar = screen.getByRole('region', { name: 'Kalender Rapim dan tenggat tugas' });
    fireEvent.change(within(calendar).getByLabelText('Bulan kalender'), {
      target: { value: '2026-11' },
    });
    expect(screen.queryByText(/REKAP RAPIM/)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Satu rekap untuk memantau hasil dan tindak lanjut/),
    ).not.toBeInTheDocument();
    expect(
      within(calendar).getByRole('link', { name: 'Rapat · Rapat Evaluasi Sintetis' }),
    ).toBeInTheDocument();
    expect(screen.queryByText('Evaluasi Program Uji')).not.toBeInTheDocument();
    expect(screen.queryByText('67%')).not.toBeInTheDocument();
    expect(screen.getByText('PIC Uji')).toBeInTheDocument();
    expect(screen.queryByText('Rapim mendatang')).not.toBeInTheDocument();
    expect(screen.queryByText('Tindak lanjut', { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText('Belum selesai', { exact: true })).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Putusan tanpa tindak lanjut tetap ada di notulensi rapat asal/),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Belum dimulai 0' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Berproses 1' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Rapat terbaru' })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/meetings?limit=100&offset=0',
      expect.objectContaining({ credentials: 'include', cache: 'no-store' }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/action-items?limit=100&offset=0',
      expect.objectContaining({ credentials: 'include', cache: 'no-store' }),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      `/api/v1/action-items/${actionItem.id}`,
      expect.objectContaining({ credentials: 'include', cache: 'no-store' }),
    );
    expect(screen.queryByText('Evaluasi kerja sama industri')).not.toBeInTheDocument();
  });

  it('filters the task list when a status summary is selected', async () => {
    const notStartedItem: ActionItemSummary = {
      ...actionItem,
      id: '40000000-0000-4000-8000-000000000002',
      title: 'Meninjau dokumen sintetis',
      official_status: 'BELUM_DIMULAI',
    };
    vi.stubGlobal(
      'fetch',
      apiFetch({
        items: [actionItem, notStartedItem],
        details: [actionItemDetail, { ...actionItemDetail, id: notStartedItem.id }],
      }),
    );
    render(<Dashboard authenticatedUser={secretary} />);

    const taskList = await screen.findByRole('region', { name: 'Tindak lanjut lintas Rapim' });
    expect(within(taskList).getByText(actionItem.title)).toBeInTheDocument();
    expect(within(taskList).getByText(notStartedItem.title)).toBeInTheDocument();

    const summary = screen.getByRole('region', { name: 'Status tugas' });
    const notStartedFilter = within(summary).getByRole('button', { name: 'Belum dimulai 1' });
    fireEvent.click(notStartedFilter);

    expect(within(taskList).queryByText(actionItem.title)).not.toBeInTheDocument();
    expect(within(taskList).getByText(notStartedItem.title)).toBeInTheDocument();
    expect(notStartedFilter).toHaveAttribute('aria-pressed', 'true');
    expect(within(summary).getByRole('button', { name: 'Berproses 1' })).toBeInTheDocument();

    fireEvent.click(notStartedFilter);
    expect(within(taskList).getByText(actionItem.title)).toBeInTheDocument();
    expect(within(taskList).getByText(notStartedItem.title)).toBeInTheDocument();
    expect(notStartedFilter).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows explicit empty states when the APIs return no records', async () => {
    vi.stubGlobal('fetch', apiFetch({ meetings: [], items: [], details: [] }));
    render(<Dashboard authenticatedUser={secretary} />);

    expect(
      await screen.findByText('Belum ada Action Item dalam cakupan akses Anda.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Berproses 0' })).toBeInTheDocument();
    expect(screen.getByText('Rapim tercatat').closest('.metric-item')).toHaveTextContent('0');
  });

  it('shows API failures and retries without falling back to prototype data', async () => {
    let failed = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/action-items?limit=100&offset=0' && failed) {
        return jsonResponse({ detail: 'Unavailable' }, 503);
      }
      if (url === '/api/v1/action-items?limit=100&offset=0') return jsonResponse([]);
      if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([]);
      throw new Error(`Unexpected dashboard request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<Dashboard authenticatedUser={secretary} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Data dashboard tidak dapat dimuat. Coba lagi.',
    );
    expect(screen.queryByText('Evaluasi kerja sama industri')).not.toBeInTheDocument();
    failed = false;
    fireEvent.click(screen.getByRole('button', { name: 'Coba lagi' }));

    expect(
      await screen.findByText('Belum ada Action Item dalam cakupan akses Anda.'),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  });

  it('uses only scoped Action Item APIs for PIC and does not request meetings', async () => {
    const pic: AuthenticatedUser = {
      ...secretary,
      id: actionItem.active_assignments[0].assignee_user_id!,
      roles: ['PIC'],
    };
    const fetchMock = apiFetch({ meetings: [] });
    vi.stubGlobal('fetch', fetchMock);
    render(<Dashboard authenticatedUser={pic} />);

    expect(
      await screen.findByRole('button', {
        name: 'Lihat detail tindak lanjut: Menyiapkan laporan sintetis',
      }),
    ).toBeVisible();
    expect(screen.getByText('Ringkasan tugas saya')).toBeInTheDocument();
    expect(screen.queryByText('67%')).not.toBeInTheDocument();
    expect(screen.queryByText('Rapat Evaluasi Sintetis')).not.toBeInTheDocument();
    expect(screen.queryByText('Notulensi awal sintetis')).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      '/api/v1/meetings?limit=100&offset=0',
      expect.anything(),
    );
  });

  it('does not request business dashboard data for Super Admin', async () => {
    const superAdmin: AuthenticatedUser = {
      ...secretary,
      roles: ['SUPER_ADMIN'],
    };
    const fetchMock = apiFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(<Dashboard authenticatedUser={superAdmin} />);

    expect(
      await screen.findByText(/Ringkasan administratif belum tersedia melalui API/),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText('Menyiapkan laporan sintetis')).not.toBeInTheDocument();
  });

  it('shows role-scoped leadership summary without exposing restricted meeting content', async () => {
    const leader: AuthenticatedUser = {
      ...secretary,
      roles: ['REKTOR'],
    };
    vi.stubGlobal('fetch', apiFetch());
    render(<Dashboard authenticatedUser={leader} />);

    expect(await screen.findByText('Ringkasan strategis')).toBeInTheDocument();
    const calendar = screen.getByRole('region', { name: 'Kalender Rapim dan tenggat tugas' });
    fireEvent.change(within(calendar).getByLabelText('Bulan kalender'), {
      target: { value: '2026-11' },
    });
    expect(screen.queryByText('Rapat Evaluasi Sintetis')).not.toBeInTheDocument();
    expect(
      within(calendar).getByRole('link', { name: 'Rapat · Rapim terjadwal' }),
    ).toBeInTheDocument();
    expect(screen.queryByText('Progres sintetis')).not.toBeInTheDocument();
  });

  it('labels the Warek dashboard as its authorized task and decision scope', async () => {
    const warek: AuthenticatedUser = {
      ...secretary,
      roles: ['WAREK'],
    };
    vi.stubGlobal('fetch', apiFetch());
    render(<Dashboard authenticatedUser={warek} />);

    expect(await screen.findByText('Tugas dan keputusan dalam cakupan')).toBeInTheDocument();
    const taskList = screen.getByRole('region', { name: 'Tindak lanjut lintas Rapim' });
    expect(within(taskList).getByText('Menyiapkan laporan sintetis')).toBeInTheDocument();
  });

  it('filters monitoring by month and shows more Action Items on request', async () => {
    const nextMeeting: MeetingSummary = {
      ...meeting,
      id: '30000000-0000-4000-8000-000000000002',
      meeting_number: 'RAPIM-2026-022',
      title: 'Rapat Koordinasi Sintetis',
      meeting_date: '2026-12-05',
    };
    const decemberTask: ActionItemSummary = {
      ...actionItem,
      id: '40000000-0000-4000-8000-000000000002',
      meeting_id: nextMeeting.id,
      title: 'Tugas Desember',
    };
    const fetchMock = apiFetch({
      meetings: [meeting, nextMeeting],
      items: [actionItem, decemberTask],
      details: [actionItemDetail, { ...actionItemDetail, id: decemberTask.id }],
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<Dashboard authenticatedUser={secretary} />);

    const taskList = await screen.findByRole('region', { name: 'Tindak lanjut lintas Rapim' });
    expect(within(taskList).getByText('Tugas Desember')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Bulan Rapim' }), {
      target: { value: '2026-11' },
    });
    expect(within(taskList).getByText('Menyiapkan laporan sintetis')).toBeInTheDocument();
    expect(within(taskList).queryByText('Tugas Desember')).not.toBeInTheDocument();
  });

  it('shows a short Action Item list until the user asks for more', async () => {
    const items = Array.from({ length: 7 }, (_, index) => ({
      ...actionItem,
      id: `40000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
      title: `Tugas sintetis ${index + 1}`,
    }));
    const details = items.map((item) => ({ ...actionItemDetail, id: item.id }));
    vi.stubGlobal('fetch', apiFetch({ items, details }));
    render(<Dashboard authenticatedUser={secretary} />);

    const list = await screen.findByRole('region', { name: 'Tindak lanjut lintas Rapim' });
    expect(within(list).getAllByRole('article')).toHaveLength(5);
    expect(within(list).queryByText('Tugas sintetis 6')).not.toBeInTheDocument();
    fireEvent.click(within(list).getByRole('button', { name: 'Lainnya (2)' }));
    expect(within(list).getAllByRole('article')).toHaveLength(7);
    expect(within(list).getByText('Tugas sintetis 6')).toBeInTheDocument();
  });

  it('shows a month calendar with authorized meeting and task-deadline links', async () => {
    const decemberMeeting: MeetingSummary = {
      ...meeting,
      id: '30000000-0000-4000-8000-000000000002',
      meeting_number: 'RAPIM-2026-022',
      title: 'Rapat Desember Sintetis',
      meeting_date: '2026-12-05',
    };
    const decemberTask: ActionItemSummary = {
      ...actionItem,
      id: '40000000-0000-4000-8000-000000000002',
      meeting_id: decemberMeeting.id,
      title: 'Tugas Desember Sintetis',
      due_date: '2026-12-10',
    };
    vi.stubGlobal(
      'fetch',
      apiFetch({
        meetings: [meeting, decemberMeeting],
        items: [actionItem, decemberTask],
        details: [actionItemDetail, { ...actionItemDetail, id: decemberTask.id }],
      }),
    );
    render(<Dashboard authenticatedUser={secretary} />);

    const calendar = await screen.findByRole('region', {
      name: 'Kalender Rapim dan tenggat tugas',
    });
    fireEvent.change(within(calendar).getByLabelText('Bulan kalender'), {
      target: { value: '2026-12' },
    });

    expect(
      await within(calendar).findByRole('link', { name: 'Rapat · Rapat Desember Sintetis' }),
    ).toHaveAttribute('href', `#meetings/${decemberMeeting.id}`);
    expect(
      within(calendar).getByRole('link', { name: 'Tenggat · Tugas Desember Sintetis' }),
    ).toHaveAttribute('href', `#action-items/${decemberTask.id}`);
    expect(
      within(calendar).queryByRole('link', { name: 'Rapat · Rapat Evaluasi Sintetis' }),
    ).not.toBeInTheDocument();
  });
});
