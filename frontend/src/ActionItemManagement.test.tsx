import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  ActionItemDetail,
  ActionItemSummary,
  AuthenticatedUser,
  MeetingSummary,
  MinutesRevision,
} from './api';
import { SESSION_EXPIRED_EVENT } from './api';
import ActionItemManagement from './ActionItemManagement';

const secretaryId = '20000000-0000-4000-8000-000000000001';
const picId = '20000000-0000-4000-8000-000000000002';
const otherPicId = '20000000-0000-4000-8000-000000000003';
const meetingId = '30000000-0000-4000-8000-000000000001';
const revisionId = '40000000-0000-4000-8000-000000000001';
const decisionId = '70000000-0000-4000-8000-000000000001';
const taskId = '80000000-0000-4000-8000-000000000001';
const assignmentId = '90000000-0000-4000-8000-000000000001';
const unitId = 'a1000000-0000-4000-8000-000000000001';
const otherUnitId = 'a2000000-0000-4000-8000-000000000001';
const unitSummary = { id: unitId, unit_code: 'UNIT-UJI', name: 'Unit Uji' };
const otherUnitSummary = { id: otherUnitId, unit_code: 'UNIT-LAIN', name: 'Unit Lain' };

const secretary: AuthenticatedUser = {
  id: secretaryId,
  email: 'secretariat@example.test',
  full_name: 'Sekretariat Uji',
  roles: ['SEKRETARIAT'],
};

const pic: AuthenticatedUser = {
  id: picId,
  email: 'pic@example.test',
  full_name: 'PIC Uji',
  roles: ['PIC'],
};

const meeting: MeetingSummary = {
  id: meetingId,
  meeting_number: 'RAPIM-2026-041',
  title: 'Rapat sintetis Stage 5',
  meeting_date: '2026-11-05',
  status: 'FINAL',
  version: 1,
  agendas: [],
};

const decisionRevision: MinutesRevision = {
  id: revisionId,
  meeting_id: meetingId,
  revision_number: 4,
  format_version: 2,
  content: null,
  discussions: [
    {
      id: '60000000-0000-4000-8000-000000000001',
      agenda_id: '50000000-0000-4000-8000-000000000001',
      discussion_number: 1,
      subject: 'Evaluasi layanan',
      content: 'Pembahasan sintetis.',
      decisions: [
        {
          id: decisionId,
          discussion_id: '60000000-0000-4000-8000-000000000001',
          decision_number: 1,
          decision_text: 'Susun laporan evaluasi',
          target_text: null,
          output_expected: 'Laporan evaluasi',
          target_date: '2026-12-01',
          is_action_item: true,
        },
      ],
    },
  ],
  created_by_id: secretaryId,
  created_at: '2026-11-05T10:00:00Z',
};

const assignment = {
  id: assignmentId,
  action_item_id: taskId,
  assignee_user_id: picId,
  assignee_display_name: null,
  assignee_name: 'PIC Uji',
  assignee_job_title: null,
  pic_origin_unit: unitSummary,
  assigned_by_user_id: secretaryId,
  assignment_role: 'MAIN' as const,
  started_at: '2026-11-05T10:30:00Z',
  ended_at: null,
  ended_by_user_id: null,
  end_reason: null,
};

const task: ActionItemSummary = {
  id: taskId,
  meeting_id: meetingId,
  source_minutes_revision_id: revisionId,
  source_decision_id: decisionId,
  disposition_id: null,
  responsible_unit: unitSummary,
  source_revision_is_stale: false,
  title: 'Siapkan laporan sintetis',
  description: 'Menyusun laporan evaluasi layanan.',
  output_expected: 'Laporan evaluasi',
  due_date: '2026-12-01',
  priority: 'Tinggi',
  official_status: 'BERPROSES',
  version: 2,
  created_by_id: secretaryId,
  created_at: '2026-11-05T10:30:00Z',
  updated_at: '2026-11-06T09:00:00Z',
  completed_at: null,
  deleted_at: null,
  active_assignments: [assignment],
};

const detail: ActionItemDetail = {
  ...task,
  assignment_history: [assignment],
  progress_updates: [
    {
      id: 'a0000000-0000-4000-8000-000000000001',
      action_item_id: taskId,
      assignment_id: assignmentId,
      actor_user_id: picId,
      submitted_as: 'PIC',
      report_text: 'Pengumpulan data dimulai.',
      blocker_text: null,
      progress_percent: 35,
      completion_requested: false,
      submitted_at: '2026-11-06T09:00:00Z',
      evidence: [],
    },
  ],
  status_history: [
    {
      id: 'b0000000-0000-4000-8000-000000000001',
      event_number: 1,
      old_status: null,
      new_status: 'BELUM_DIMULAI',
      changed_by_id: secretaryId,
      verification_id: null,
      change_note: 'Action Item dibuat',
      changed_at: '2026-11-05T10:30:00Z',
    },
  ],
  completion_verifications: [],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function actionFetch({
  items = [task],
  itemDetail = detail,
  onRequest,
}: {
  items?: ActionItemSummary[];
  itemDetail?: ActionItemDetail;
  onRequest?: (url: string, init?: RequestInit) => Response | undefined;
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const overridden = onRequest?.(url, init);
    if (overridden) return overridden;
    if (url === '/api/v1/action-items?limit=100&offset=0') return jsonResponse(items);
    if (url.startsWith('/api/v1/action-items/') && !url.includes('/pic-directory')) {
      const requestedId = url.split('/').at(-1);
      return jsonResponse({ ...itemDetail, id: requestedId ?? taskId });
    }
    if (url.startsWith('/api/v1/action-items/pic-directory?')) {
      const requestUrl = new URL(url, window.location.origin);
      const query = requestUrl.searchParams.get('query') ?? '';
      const candidates = [
        { id: picId, full_name: 'PIC Uji A', job_title: 'Analis Uji', active_units: [unitSummary] },
        {
          id: otherPicId,
          full_name: 'PIC Uji B',
          job_title: 'Koordinator Uji',
          active_units: [unitSummary, otherUnitSummary],
        },
      ];
      return jsonResponse({
        query,
        pics: candidates.filter((candidate) =>
          candidate.full_name.toLowerCase().includes(query.toLowerCase()),
        ),
        units: [unitSummary],
        more_pics: false,
      });
    }
    if (url === '/api/v1/meetings/participant-options') {
      return jsonResponse([
        { id: picId, full_name: 'PIC Uji A', job_title: 'Analis Uji', roles: ['PIC'] },
        { id: otherPicId, full_name: 'PIC Uji B', job_title: 'Koordinator Uji', roles: ['PIC'] },
      ]);
    }
    if (url.endsWith('/dispositions?limit=100&offset=0')) return jsonResponse([]);
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

async function openTask(title = task.title): Promise<void> {
  await userEvent.click(
    await screen.findByRole('button', { name: (accessibleName) => accessibleName.includes(title) }),
  );
  await screen.findByRole('heading', { name: title });
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
});

describe('ActionItemManagement', () => {
  it('treats task titles with regex punctuation literally', async () => {
    const title = 'Siapkan laporan [sintetis]';
    const specialTask = { ...task, title };
    const specialDetail = { ...detail, title };
    actionFetch({ items: [specialTask], itemDetail: specialDetail });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    await openTask(title);

    expect(screen.getByRole('heading', { name: title })).toBeVisible();
  });

  it('shows the task list without details until a task is selected', async () => {
    const user = userEvent.setup();
    actionFetch();
    render(<ActionItemManagement authenticatedUser={secretary} />);

    const list = await screen.findByRole('region', { name: 'Daftar tugas' });
    expect(screen.getByText('RAPIM · TINDAK LANJUT')).toBeVisible();
    expect(list).toHaveClass('meeting-results-panel');
    expect(within(list).getByRole('list')).toHaveClass('meeting-list');
    expect(within(list).getByText('Siapkan laporan sintetis')).toBeVisible();
    const taskStatus = within(list).getByRole('status', { name: 'Status: Berproses' });
    expect(taskStatus).toHaveClass('action-item-list-status', 'action-item-list-status--berproses');
    expect(taskStatus).toHaveTextContent('Berproses');
    expect(screen.queryByRole('dialog', { name: 'Detail tindak lanjut' })).not.toBeInTheDocument();
    expect(screen.queryByText('Menyusun laporan evaluasi layanan.')).not.toBeInTheDocument();

    await user.click(within(list).getByRole('button', { name: /Siapkan laporan sintetis/ }));
    expect(await screen.findByRole('dialog', { name: 'Detail tindak lanjut' })).toBeVisible();
    expect(screen.getByText('Menyusun laporan evaluasi layanan.')).toBeVisible();
  });

  it('filters active tasks by official status while keeping each status label visible', async () => {
    const user = userEvent.setup();
    const blockedTask: ActionItemSummary = {
      ...task,
      id: '80000000-0000-4000-8000-000000000003',
      title: 'Tindak lanjut terkendala',
      official_status: 'TERKENDALA',
    };
    actionFetch({ items: [task, blockedTask] });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    const list = await screen.findByRole('region', { name: 'Daftar tugas' });
    await user.selectOptions(
      within(list).getByRole('combobox', { name: 'Status tugas' }),
      'TERKENDALA',
    );

    expect(within(list).getByRole('button', { name: /Tindak lanjut terkendala/ })).toBeVisible();
    expect(within(list).getByRole('status', { name: 'Status: Terkendala' })).toHaveTextContent(
      'Terkendala',
    );
    expect(
      within(list).queryByRole('button', { name: /Siapkan laporan sintetis/ }),
    ).not.toBeInTheDocument();
  });

  it('opens the Action Item linked from the dashboard directly', async () => {
    const linkedTaskId = '80000000-0000-4000-8000-000000000002';
    const linkedTask: ActionItemSummary = {
      ...task,
      id: linkedTaskId,
      title: 'Tindak lanjut dari dashboard',
    };
    actionFetch({
      items: [task, linkedTask],
      itemDetail: { ...detail, id: linkedTaskId, title: linkedTask.title },
    });
    render(
      <ActionItemManagement authenticatedUser={secretary} targetActionItemId={linkedTaskId} />,
    );

    expect(
      await screen.findByRole('button', { name: /Tindak lanjut dari dashboard/ }),
    ).toHaveAttribute('aria-current', 'true');
    expect(
      await screen.findByRole('heading', { name: 'Tindak lanjut dari dashboard' }),
    ).toBeVisible();
  });

  it('shows the creation form in place of the active task list and returns to the list', async () => {
    const user = userEvent.setup();
    actionFetch({
      onRequest: (url) => {
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url === `/api/v1/meetings/${meetingId}/minutes-revisions`) {
          return jsonResponse([decisionRevision]);
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    expect(await screen.findByRole('heading', { name: 'Daftar tugas' })).toBeVisible();
    expect(screen.queryByText('MONITORING OPERASIONAL')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Daftar dan detail mengikuti cakupan akses yang ditetapkan API.'),
    ).not.toBeInTheDocument();
    expect(screen.getByText('1 tugas')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Buat Action Item' }));

    expect(
      await screen.findByRole('heading', { name: 'Buat Action Item dari keputusan' }),
    ).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'Daftar tugas' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: 'Siapkan laporan sintetis' }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Kembali ke daftar tindak lanjut' }));
    expect(await screen.findByRole('heading', { name: 'Daftar tugas' })).toBeVisible();
  });

  it('shows five active tasks initially and reveals the rest with Lainnya', async () => {
    const user = userEvent.setup();
    const items = Array.from({ length: 7 }, (_, index) => ({
      ...task,
      id: `80000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
      title: `Tugas ${index + 1}`,
    }));
    actionFetch({ items });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    const list = await screen.findByRole('region', { name: 'Daftar tugas' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
    expect(within(list).queryByText('Tugas 6')).not.toBeInTheDocument();
    await user.click(within(list).getByRole('button', { name: 'Lainnya (2)' }));
    expect(within(list).getAllByRole('listitem')).toHaveLength(7);
    expect(within(list).getByText('Tugas 6')).toBeInTheDocument();
  });

  it('expands the task list when a dashboard link targets an item beyond the first five', async () => {
    const items = Array.from({ length: 7 }, (_, index) => ({
      ...task,
      id: `80000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
      title: `Tugas ${index + 1}`,
    }));
    const target = items[6];
    actionFetch({ itemDetail: { ...detail, id: target.id, title: target.title }, items });
    render(<ActionItemManagement authenticatedUser={secretary} targetActionItemId={target.id} />);

    const list = await screen.findByRole('region', { name: 'Daftar tugas' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(7);
    expect(await within(list).findByRole('button', { name: /Tugas 7/ })).toHaveAttribute(
      'aria-current',
      'true',
    );
  });

  it('loads readable task details and progress without exposing internal source identifiers', async () => {
    const fetchMock = actionFetch();
    render(<ActionItemManagement authenticatedUser={secretary} targetActionItemId={taskId} />);

    expect(await screen.findByRole('heading', { name: 'Siapkan laporan sintetis' })).toBeVisible();
    expect(screen.getByText('Menyusun laporan evaluasi layanan.')).toBeInTheDocument();
    expect(screen.getByText('Laporan evaluasi')).toBeInTheDocument();
    expect(screen.queryByText(meetingId)).not.toBeInTheDocument();
    expect(screen.queryByText(decisionId)).not.toBeInTheDocument();
    expect(screen.getByText('Analis Uji')).toBeInTheDocument();
    expect(screen.getByText('Pengumpulan data dimulai.')).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === 'SPAN' && element.textContent?.includes('35%') === true,
      ),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/action-items/${taskId}`,
      expect.objectContaining({ credentials: 'include', cache: 'no-store' }),
    );
  });

  it('shows an honest empty state when the authorized API returns no tasks', async () => {
    actionFetch({ items: [] });
    render(<ActionItemManagement authenticatedUser={pic} />);

    expect(
      await screen.findByText('Belum ada Action Item dalam cakupan akses Anda.'),
    ).toBeVisible();
  });

  it('shows loading and a retryable detail error independently from the task list', async () => {
    let resolveList: (response: Response) => void = () => undefined;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/action-items?limit=100&offset=0') {
        return new Promise<Response>((resolve) => {
          resolveList = resolve;
        });
      }
      if (url === `/api/v1/action-items/${taskId}`) {
        return Promise.resolve(jsonResponse({ detail: 'Unavailable' }, 503));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<ActionItemManagement authenticatedUser={secretary} targetActionItemId={taskId} />);

    expect(screen.getByRole('status')).toHaveTextContent('Memuat Action Item...');
    resolveList(jsonResponse([task]));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Detail Action Item tidak dapat dimuat: Unavailable',
    );
    expect(screen.getByRole('button', { name: 'Coba lagi' })).toBeInTheDocument();
  });

  it('shows a retryable list error', async () => {
    let fail = true;
    const fetchMock = actionFetch({
      onRequest: (url) =>
        url === '/api/v1/action-items?limit=100&offset=0' && fail
          ? jsonResponse({ detail: 'Unavailable' }, 503)
          : undefined,
    });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Daftar Action Item tidak dapat dimuat: Unavailable',
    );
    fail = false;
    await userEvent.click(screen.getByRole('button', { name: 'Coba lagi' }));
    await openTask();
    expect(await screen.findByRole('heading', { name: 'Siapkan laporan sintetis' })).toBeVisible();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([url]) => url === '/api/v1/action-items?limit=100&offset=0'),
      ).toHaveLength(2),
    );
  });

  it('creates a task from an actionable decision and sends only the backend contract', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const createdTask: ActionItemDetail = { ...detail, id: taskId, title: 'Laporan baru sintetis' };
    const fetchMock = actionFetch({
      items: [],
      itemDetail: createdTask,
      onRequest: (url, init) => {
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url === `/api/v1/meetings/${meetingId}/minutes-revisions`) {
          return jsonResponse([decisionRevision]);
        }
        if (url === '/api/v1/action-items' && init?.method === 'POST') {
          expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
          return jsonResponse(createdTask, 201);
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    await user.click(await screen.findByRole('button', { name: 'Buat Action Item' }));
    expect(
      await screen.findByRole('option', { name: /Susun laporan evaluasi/ }),
    ).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Pilih keputusan dari notulensi'), decisionId);
    await user.type(screen.getByLabelText('Judul tugas'), 'Laporan baru sintetis');
    await user.type(screen.getByLabelText('Deskripsi tugas'), 'Deskripsi tugas sintetis');
    await user.type(screen.getByLabelText('Output yang diharapkan'), 'Hasil laporan');
    await user.type(screen.getByLabelText('Tenggat waktu'), '2026-12-20');
    await user.selectOptions(screen.getByLabelText('Prioritas'), 'Segera');
    expect(screen.queryByLabelText('Unit penanggung jawab')).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('PIC utama'), picId);
    await user.selectOptions(screen.getByLabelText('Unit asal PIC utama'), unitId);
    await user.click(screen.getByRole('button', { name: 'Simpan Action Item' }));

    expect(await screen.findByRole('button', { name: /Laporan baru sintetis/ })).toBeVisible();
    const createCall = fetchMock.mock.calls.find(
      ([url, init]) => url === '/api/v1/action-items' && init?.method === 'POST',
    );
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      meeting_id: meetingId,
      source_minutes_revision_id: revisionId,
      source_decision_id: decisionId,
      disposition_id: null,
      title: 'Laporan baru sintetis',
      description: 'Deskripsi tugas sintetis',
      output_expected: 'Hasil laporan',
      due_date: '2026-12-20',
      priority: 'Segera',
      main_pic_user_id: picId,
      main_pic_display_name: null,
      main_pic_origin_unit_id: unitId,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/action-items',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('selects the main PIC from the authorized meeting participant options', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const createdTask: ActionItemDetail = { ...detail, id: taskId, title: 'Tugas PIC bernama' };
    const fetchMock = actionFetch({
      items: [],
      itemDetail: createdTask,
      onRequest: (url, init) => {
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url === `/api/v1/meetings/${meetingId}/minutes-revisions`) {
          return jsonResponse([decisionRevision]);
        }
        if (url === '/api/v1/action-items' && init?.method === 'POST') {
          expect(JSON.parse(String(init.body))).toMatchObject({
            main_pic_user_id: picId,
          });
          return jsonResponse(createdTask, 201);
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    await user.click(await screen.findByRole('button', { name: 'Buat Action Item' }));
    await user.selectOptions(
      await screen.findByLabelText('Pilih keputusan dari notulensi'),
      decisionId,
    );
    await user.type(screen.getByLabelText('Judul tugas'), 'Tugas PIC bernama');
    await user.type(screen.getByLabelText('Deskripsi tugas'), 'Deskripsi sintetis');
    await user.selectOptions(screen.getByLabelText('Prioritas'), 'Segera');
    expect(
      within(screen.getByLabelText('PIC utama')).getByRole('option', { name: 'Analis Uji' }),
    ).toBeInTheDocument();
    await user.selectOptions(await screen.findByLabelText('PIC utama'), picId);
    await user.selectOptions(screen.getByLabelText('Unit asal PIC utama'), unitId);
    await user.click(screen.getByRole('button', { name: 'Simpan Action Item' }));

    expect(await screen.findByRole('button', { name: /Tugas PIC bernama/ })).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/meetings/participant-options',
      expect.anything(),
    );
  });

  it('prevents assigning the same user as both main and supporting PIC', async () => {
    const user = userEvent.setup();
    actionFetch({
      items: [],
      onRequest: (url) => {
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url === `/api/v1/meetings/${meetingId}/minutes-revisions`) {
          return jsonResponse([decisionRevision]);
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    await user.click(await screen.findByRole('button', { name: 'Buat Action Item' }));
    await user.selectOptions(
      await screen.findByLabelText('Pilih keputusan dari notulensi'),
      decisionId,
    );
    const mainPicker = screen.getByLabelText('PIC utama');
    const supportingPicker = screen.getByLabelText('PIC pendukung (opsional)');
    await user.selectOptions(mainPicker, picId);
    expect(within(supportingPicker).queryByRole('option', { name: 'Analis Uji' })).toBeNull();
    await user.selectOptions(supportingPicker, otherPicId);
    expect(within(mainPicker).queryByRole('option', { name: 'Koordinator Uji' })).toBeNull();
  });

  it('creates an Action Item from its source decision without loading dispositions', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const createdTask: ActionItemDetail = {
      ...detail,
      id: taskId,
      title: 'Tugas dari keputusan',
    };
    const fetchMock = actionFetch({
      items: [],
      itemDetail: createdTask,
      onRequest: (url, init) => {
        if (url === '/api/v1/meetings?limit=100&offset=0') return jsonResponse([meeting]);
        if (url === `/api/v1/meetings/${meetingId}/minutes-revisions`) {
          return jsonResponse([decisionRevision]);
        }
        if (url === '/api/v1/action-items' && init?.method === 'POST') {
          expect(JSON.parse(String(init.body))).toMatchObject({
            meeting_id: meetingId,
            source_minutes_revision_id: revisionId,
            source_decision_id: decisionId,
          });
          return jsonResponse(createdTask, 201);
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    await user.click(await screen.findByRole('button', { name: 'Buat Action Item' }));
    await user.selectOptions(
      await screen.findByLabelText('Pilih keputusan dari notulensi'),
      decisionId,
    );
    await user.type(screen.getByLabelText('Judul tugas'), 'Tugas dari keputusan');
    await user.type(screen.getByLabelText('Deskripsi tugas'), 'Deskripsi sintetis');
    await user.selectOptions(screen.getByLabelText('Prioritas'), 'Segera');
    await user.selectOptions(screen.getByLabelText('PIC utama'), picId);
    await user.selectOptions(screen.getByLabelText('Unit asal PIC utama'), unitId);
    await user.click(screen.getByRole('button', { name: 'Simpan Action Item' }));

    expect(await screen.findByRole('button', { name: /Tugas dari keputusan/ })).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalledWith(
      `/api/v1/meetings/${meetingId}/dispositions?limit=100&offset=0`,
      expect.anything(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/action-items',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('does not allow a meeting leader to create a task from a source decision', async () => {
    const rector: AuthenticatedUser = {
      ...secretary,
      id: '20000000-0000-4000-8000-000000000004',
      full_name: 'Rektor Uji',
      roles: ['REKTOR'],
    };
    const fetchMock = actionFetch({
      items: [],
    });
    render(<ActionItemManagement authenticatedUser={rector} />);

    expect(
      await screen.findByText('Belum ada Action Item dalam cakupan akses Anda.'),
    ).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Buat Action Item' })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      '/api/v1/action-items',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('lets an assigned PIC submit progress without exposing meeting or minutes APIs or status controls', async () => {
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const updatedDetail: ActionItemDetail = {
      ...detail,
      progress_updates: [
        ...detail.progress_updates,
        {
          ...detail.progress_updates[0],
          id: 'a0000000-0000-4000-8000-000000000002',
          report_text: 'Progres tambahan sintetis.',
          progress_percent: 55,
          submitted_at: '2026-11-07T09:00:00Z',
        },
      ],
    };
    const fetchMock = actionFetch({
      onRequest: (url, init) => {
        if (url === `/api/v1/action-items/${taskId}/progress-updates` && init?.method === 'POST') {
          expect(JSON.parse(String(init.body))).toEqual({
            assignment_id: assignmentId,
            report_text: 'Progres tambahan sintetis.',
            blocker_text: 'Menunggu data unit.',
            progress_percent: 55,
            completion_requested: false,
          });
          expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
          return jsonResponse(updatedDetail.progress_updates[1], 201);
        }
        if (url === `/api/v1/action-items/${taskId}` && init?.method !== 'POST') {
          return jsonResponse(updatedDetail);
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={pic} />);
    const user = userEvent.setup();

    await openTask();
    await user.type(await screen.findByLabelText('Laporan progres'), 'Progres tambahan sintetis.');
    await user.type(screen.getByLabelText('Kendala'), 'Menunggu data unit.');
    await user.clear(screen.getByLabelText('Progres (%)'));
    await user.type(screen.getByLabelText('Progres (%)'), '55');
    await user.click(screen.getByRole('button', { name: 'Simpan progres dan bukti' }));

    expect(await screen.findByText('Pembaruan progres tersimpan.')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/v1\/meetings|minutes-revisions|decision-briefs/),
      expect.anything(),
    );
    expect(screen.queryByRole('button', { name: 'Ubah status resmi' })).not.toBeInTheDocument();
  });

  it('lets an assigned PIC upload progress evidence through the protected API', async () => {
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const progressId = 'a0000000-0000-4000-8000-000000000003';
    const evidence = {
      id: 'c0000000-0000-4000-8000-000000000001',
      progress_update_id: progressId,
      evidence_kind: 'FILE' as const,
      original_filename: 'hasil.txt',
      content_type: 'text/plain',
      size_bytes: 17,
      sha256: 'a'.repeat(64),
      external_url: null,
      link_label: null,
      download_url: `/api/v1/action-items/${taskId}/evidence/c0000000-0000-4000-8000-000000000001`,
      scan_status: 'PENDING' as const,
      uploaded_by_user_id: picId,
      created_at: '2026-11-07T10:00:00Z',
    };
    let updatedDetail = detail;
    const fetchMock = actionFetch({
      onRequest: (url, init) => {
        if (url === `/api/v1/action-items/${taskId}/progress-updates` && init?.method === 'POST') {
          return jsonResponse({ ...detail.progress_updates[0], id: progressId }, 201);
        }
        if (
          url ===
            `/api/v1/action-items/${taskId}/progress-updates/` + `${progressId}/evidence/files` &&
          init?.method === 'POST'
        ) {
          expect(init.body).toBeInstanceOf(FormData);
          expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
          expect(new Headers(init.headers).get('Content-Type')).toBeNull();
          updatedDetail = {
            ...detail,
            progress_updates: [
              { ...detail.progress_updates[0], id: progressId, evidence: [evidence] },
            ],
          };
          return jsonResponse(evidence, 201);
        }
        if (url === `/api/v1/action-items/${taskId}` && init?.method !== 'POST') {
          return jsonResponse(updatedDetail);
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={pic} />);
    const user = userEvent.setup();

    await openTask();
    const fileInput = await screen.findByLabelText(/Bukti pendukung/);
    await user.upload(
      fileInput,
      new File(['synthetic evidence'], 'hasil.txt', { type: 'text/plain' }),
    );
    expect((fileInput as HTMLInputElement).files).toHaveLength(1);
    await user.type(screen.getByLabelText('Laporan progres'), 'Hasil sudah disiapkan.');
    await user.click(screen.getByRole('button', { name: 'Simpan progres dan bukti' }));

    expect(await screen.findByText(/Menunggu pemeriksaan keamanan/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/action-items/${taskId}/progress-updates/${progressId}/evidence/files`,
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('does not allow a PIC to request completion before evidence has a clean scan', async () => {
    actionFetch();
    render(<ActionItemManagement authenticatedUser={pic} />);

    await openTask();
    expect(await screen.findByRole('heading', { name: 'Siapkan laporan sintetis' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Ajukan penyelesaian' })).toBeDisabled();
    expect(
      screen.getByText(
        'Bukti bersih hasil pemeriksaan diperlukan sebelum mengajukan penyelesaian.',
      ),
    ).toBeVisible();
  });

  it('lets a PIC submit a completion request after the server reports clean evidence', async () => {
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const requestId = 'a0000000-0000-4000-8000-000000000005';
    const cleanDetail: ActionItemDetail = {
      ...detail,
      progress_updates: [
        {
          ...detail.progress_updates[0],
          evidence: [
            {
              id: 'c0000000-0000-4000-8000-000000000003',
              progress_update_id: detail.progress_updates[0].id,
              evidence_kind: 'FILE',
              original_filename: 'hasil.pdf',
              content_type: 'application/pdf',
              size_bytes: 14,
              sha256: 'c'.repeat(64),
              external_url: null,
              link_label: null,
              download_url: `/api/v1/action-items/${taskId}/evidence/c0000000-0000-4000-8000-000000000003`,
              scan_status: 'CLEAN',
              uploaded_by_user_id: picId,
              created_at: '2026-11-07T10:00:00Z',
            },
          ],
        },
      ],
    };
    const request = {
      ...detail.progress_updates[0],
      id: requestId,
      completion_requested: true,
    };
    let updatedDetail = cleanDetail;
    const fetchMock = actionFetch({
      itemDetail: cleanDetail,
      onRequest: (url, init) => {
        if (url === `/api/v1/action-items/${taskId}/progress-updates` && init?.method === 'POST') {
          expect(JSON.parse(String(init.body))).toEqual({
            assignment_id: assignmentId,
            report_text: 'Pekerjaan sudah siap ditinjau.',
            blocker_text: null,
            progress_percent: null,
            completion_requested: true,
          });
          updatedDetail = {
            ...cleanDetail,
            progress_updates: [...cleanDetail.progress_updates, request],
          };
          return jsonResponse(request, 201);
        }
        if (url === `/api/v1/action-items/${taskId}` && init?.method !== 'POST') {
          return jsonResponse(updatedDetail);
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={pic} />);
    const user = userEvent.setup();

    await openTask();
    await screen.findByRole('heading', { name: 'Siapkan laporan sintetis' });
    expect(
      screen.getByRole('link', { name: 'Unduh melalui endpoint terotorisasi' }),
    ).toHaveAttribute(
      'href',
      `/api/v1/action-items/${taskId}/evidence/c0000000-0000-4000-8000-000000000003`,
    );
    await user.type(screen.getByLabelText('Catatan pengajuan'), 'Pekerjaan sudah siap ditinjau.');
    await user.click(screen.getByRole('button', { name: 'Ajukan penyelesaian' }));

    expect(await screen.findByText('Pengajuan penyelesaian: menunggu verifikasi')).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/action-items/${taskId}/progress-updates`,
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('rejects oversized evidence files in the UI before making an upload request', async () => {
    actionFetch();
    render(<ActionItemManagement authenticatedUser={pic} />);
    const user = userEvent.setup();

    await openTask();
    const fileInput = await screen.findByLabelText(/Bukti pendukung/);
    await user.upload(
      fileInput,
      new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'hasil.txt', {
        type: 'text/plain',
      }),
    );
    await user.click(screen.getByRole('button', { name: 'Simpan progres dan bukti' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('ukuran melebihi 10 MiB');
    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      `/api/v1/action-items/${taskId}/progress-updates`,
      expect.anything(),
    );
  });

  it('surfaces upload failure and signals an expired session', async () => {
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const progressId = 'a0000000-0000-4000-8000-000000000006';
    const sessionExpired = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, sessionExpired);
    const fetchMock = actionFetch({
      onRequest: (url, init) => {
        if (url === `/api/v1/action-items/${taskId}/progress-updates` && init?.method === 'POST') {
          return jsonResponse({ ...detail.progress_updates[0], id: progressId }, 201);
        }
        if (
          url === `/api/v1/action-items/${taskId}/progress-updates/${progressId}/evidence/files`
        ) {
          return jsonResponse({ detail: 'Authentication required' }, 401);
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={pic} />);
    const user = userEvent.setup();

    await openTask();
    await user.upload(
      await screen.findByLabelText(/Bukti pendukung/),
      new File(['synthetic evidence'], 'hasil.txt', { type: 'text/plain' }),
    );
    await user.click(screen.getByRole('button', { name: 'Simpan progres dan bukti' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'File yang gagal diunggah: hasil.txt: Authentication required',
    );
    expect(sessionExpired).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/action-items/${taskId}/progress-updates/${progressId}/evidence/files`,
      expect.objectContaining({ method: 'POST' }),
    );
    window.removeEventListener(SESSION_EXPIRED_EVENT, sessionExpired);
  });

  it('lets Secretariat review an outstanding completion request using the versioned API', async () => {
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const requestId = 'a0000000-0000-4000-8000-000000000004';
    const requestDetail: ActionItemDetail = {
      ...detail,
      progress_updates: [
        {
          ...detail.progress_updates[0],
          id: requestId,
          completion_requested: true,
          evidence: [
            {
              id: 'c0000000-0000-4000-8000-000000000002',
              progress_update_id: requestId,
              evidence_kind: 'FILE',
              original_filename: 'hasil.pdf',
              content_type: 'application/pdf',
              size_bytes: 14,
              sha256: 'b'.repeat(64),
              external_url: null,
              link_label: null,
              download_url: `/api/v1/action-items/${taskId}/evidence/c0000000-0000-4000-8000-000000000002`,
              scan_status: 'CLEAN',
              uploaded_by_user_id: picId,
              created_at: '2026-11-07T10:00:00Z',
            },
          ],
        },
      ],
    };
    let verificationPayload: unknown;
    const fetchMock = actionFetch({
      itemDetail: requestDetail,
      onRequest: (url, init) => {
        if (
          url === `/api/v1/action-items/${taskId}/completion-verifications` &&
          init?.method === 'POST'
        ) {
          verificationPayload = JSON.parse(String(init.body));
          expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
          return jsonResponse({ ...task, official_status: 'SELESAI' });
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={secretary} />);
    const user = userEvent.setup();

    await openTask();
    await screen.findByRole('heading', { name: 'Siapkan laporan sintetis' });
    await user.selectOptions(screen.getByLabelText(`Hasil verifikasi ${requestId}`), 'VERIFIED');
    await user.click(screen.getByRole('button', { name: `Simpan verifikasi ${requestId}` }));

    expect(verificationPayload).toEqual({
      expected_version: detail.version,
      progress_update_id: requestId,
      outcome: 'VERIFIED',
      review_note: null,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/action-items/${taskId}/completion-verifications`,
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('allows Secretariat to change only non-completion official statuses', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    let statusPayload: unknown;
    let detailReads = 0;
    const fetchMock = actionFetch({
      onRequest: (url, init) => {
        if (url === `/api/v1/action-items/${taskId}/status` && init?.method === 'PATCH') {
          statusPayload = JSON.parse(String(init.body));
          return jsonResponse({ ...task, official_status: 'TERKENDALA', version: 3 });
        }
        if (url === `/api/v1/action-items/${taskId}`) {
          detailReads += 1;
          return jsonResponse(
            detailReads === 1 ? detail : { ...detail, official_status: 'TERKENDALA', version: 3 },
          );
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    await openTask();
    await screen.findByRole('heading', { name: 'Siapkan laporan sintetis' });
    const statusSelect = screen.getByLabelText('Status resmi');
    expect(within(statusSelect).queryByRole('option', { name: 'Selesai' })).not.toBeInTheDocument();
    await user.selectOptions(statusSelect, 'TERKENDALA');
    await user.type(screen.getByLabelText('Catatan perubahan status'), 'Menunggu konfirmasi.');
    await user.click(screen.getByRole('button', { name: 'Ubah status resmi' }));

    expect(await screen.findByText('Status resmi diperbarui.')).toBeInTheDocument();
    expect(statusPayload).toEqual({
      expected_version: 2,
      to_status: 'TERKENDALA',
      note: 'Menunggu konfirmasi.',
    });
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/action-items/${taskId}/status`,
      expect.objectContaining({ method: 'PATCH' }),
    );
  });

  it('lets Secretariat replace the main PIC through the versioned assignment endpoint', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    let assignmentPayload: unknown;
    const fetchMock = actionFetch({
      onRequest: (url, init) => {
        if (url === `/api/v1/action-items/${taskId}/assignments` && init?.method === 'POST') {
          assignmentPayload = JSON.parse(String(init.body));
          expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-test-token');
          return jsonResponse(
            {
              ...assignment,
              id: '90000000-0000-4000-8000-000000000002',
              assignee_user_id: otherPicId,
              assignment_reason: 'Alih tugas',
            },
            201,
          );
        }
        return undefined;
      },
    });
    render(<ActionItemManagement authenticatedUser={secretary} />);

    await openTask();
    await screen.findByRole('heading', { name: 'Siapkan laporan sintetis' });
    await user.click(screen.getByRole('button', { name: 'Edit tindak lanjut' }));
    await user.selectOptions(screen.getByLabelText('Pilih jabatan PIC'), otherPicId);
    await user.selectOptions(screen.getByLabelText('Unit asal PIC'), unitId);
    await user.selectOptions(screen.getByLabelText('Peran penugasan'), 'MAIN');
    await user.click(screen.getByRole('button', { name: 'Simpan penugasan' }));

    expect(await screen.findByText('Penugasan PIC diperbarui.')).toBeInTheDocument();
    expect(assignmentPayload).toEqual({
      assignee_user_id: otherPicId,
      assignee_display_name: null,
      pic_origin_unit_id: unitId,
      reason: null,
      assignment_role: 'MAIN',
      expected_version: 2,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/action-items/${taskId}/assignments`,
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('does not allow a meeting leader to manage PIC assignments in the UI', async () => {
    const rector: AuthenticatedUser = {
      ...secretary,
      id: '20000000-0000-4000-8000-000000000004',
      full_name: 'Rektor Uji',
      roles: ['REKTOR'],
    };
    const fetchMock = actionFetch();
    render(<ActionItemManagement authenticatedUser={rector} />);

    await openTask();
    expect(screen.queryByLabelText('Cari PIC')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Simpan penugasan' })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      `/api/v1/action-items/${taskId}/assignments`,
      expect.anything(),
    );
  });

  it('does not expose Action Item management to a mixed PIC and meeting-leader account', async () => {
    actionFetch();
    const mixedLeader: AuthenticatedUser = {
      ...secretary,
      roles: ['REKTOR', 'PIC'],
    };
    render(<ActionItemManagement authenticatedUser={mixedLeader} />);

    await openTask();

    expect(screen.queryByRole('button', { name: 'Buat Action Item' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Cari PIC')).not.toBeInTheDocument();
  });

  it('does not request Action Item data for Super Admin, including a mixed-role account', async () => {
    const fetchMock = actionFetch();
    const superAdmin: AuthenticatedUser = {
      ...secretary,
      roles: ['SEKRETARIAT', 'SUPER_ADMIN'],
    };
    render(<ActionItemManagement authenticatedUser={superAdmin} />);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Peran Anda tidak memiliki akses ke Action Item.',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
