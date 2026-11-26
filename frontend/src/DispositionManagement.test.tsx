import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AuthenticatedUser, MeetingRecord, MinutesRevision } from './api';
import DispositionManagement from './DispositionManagement';

const userId = '20000000-0000-4000-8000-000000000001';
const meetingId = '30000000-0000-4000-8000-000000000001';
const revisionId = '40000000-0000-4000-8000-000000000001';
const decisionId = '50000000-0000-4000-8000-000000000001';
const targetId = '60000000-0000-4000-8000-000000000001';
const unitId = 'c0000000-0000-4000-8000-000000000001';
const roleId = '70000000-0000-4000-8000-000000000001';

const secretary: AuthenticatedUser = {
  id: userId,
  email: 'secretariat@example.test',
  full_name: 'Sekretariat Uji',
  roles: ['SEKRETARIAT'],
};

const meeting: MeetingRecord = {
  id: meetingId,
  meeting_number: 'RAPIM-2026-031',
  title: 'Rapat Disposisi Sintetis',
  meeting_type: 'RAPIM',
  meeting_date: '2026-11-20',
  start_time: null,
  end_time: null,
  location: null,
  created_by_id: userId,
  status: 'FINAL',
  version: 1,
  created_at: '2026-11-01T10:00:00Z',
  updated_at: '2026-11-01T10:00:00Z',
  agendas: [],
  participants: [],
};

const revision: MinutesRevision = {
  id: revisionId,
  meeting_id: meetingId,
  revision_number: 3,
  format_version: 2,
  content: null,
  discussions: [
    {
      id: '80000000-0000-4000-8000-000000000001',
      agenda_id: '90000000-0000-4000-8000-000000000001',
      discussion_number: 1,
      subject: 'Evaluasi',
      content: 'Pembahasan sintetis',
      decisions: [
        {
          id: decisionId,
          discussion_id: '80000000-0000-4000-8000-000000000001',
          decision_number: 1,
          decision_text: 'Susun laporan tindak lanjut',
          target_text: null,
          output_expected: 'Laporan tindak lanjut',
          target_date: '2026-12-01',
          is_action_item: true,
        },
      ],
    },
  ],
  created_by_id: userId,
  created_at: '2026-11-20T10:00:00Z',
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

describe('DispositionManagement', () => {
  it('creates a disposition from the active decision and selected authorized targets', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=csrf-test-token; Path=/';
    const disposition = {
      id: 'a0000000-0000-4000-8000-000000000001',
      meeting_id: meetingId,
      source_minutes_revision_id: revisionId,
      source_decision_id: decisionId,
      issued_by_user_id: userId,
      instruction: 'Koordinasikan pelaksanaan lintas unit.',
      created_at: '2026-11-20T11:00:00Z',
      targets: [
        {
          id: 'b0000000-0000-4000-8000-000000000001',
          target_type: 'USER',
          target_user_id: targetId,
          target_unit_id: null,
          target_role_id: null,
          target_label: 'PIC Uji',
        },
      ],
    };
    let dispositionCreated = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === `/api/v1/meetings/${meetingId}/minutes-revisions`) {
        return jsonResponse([revision]);
      }
      if (url === `/api/v1/meetings/${meetingId}/dispositions?limit=100&offset=0`) {
        return jsonResponse(dispositionCreated ? [disposition] : []);
      }
      if (url === `/api/v1/meetings/${meetingId}/disposition-targets?query=PIC&limit=100`) {
        return jsonResponse({
          query: 'PIC',
          users: [{ id: targetId, full_name: 'PIC Uji', job_title: 'Analis' }],
          units: [],
          roles: [{ id: roleId, role_code: 'PIC', role_name: 'PIC' }],
          more_users: false,
          more_units: false,
          more_roles: false,
        });
      }
      if (url === `/api/v1/meetings/${meetingId}/disposition-targets?query=TEST&limit=100`) {
        return jsonResponse({
          query: 'TEST',
          users: [],
          units: [{ id: unitId, unit_code: 'UNIT-UJI', name: 'Unit Uji' }],
          roles: [],
          more_users: false,
          more_units: false,
          more_roles: false,
        });
      }
      if (url === `/api/v1/meetings/${meetingId}/dispositions` && init?.method === 'POST') {
        dispositionCreated = true;
        return jsonResponse(disposition, 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<DispositionManagement authenticatedUser={secretary} meeting={meeting} />);
    await user.selectOptions(
      await screen.findByLabelText('Keputusan dari revisi aktif'),
      decisionId,
    );
    await user.type(screen.getByLabelText('Cari target'), 'PIC');
    await screen.findByRole('option', { name: 'PIC Uji · Analis' });
    await user.selectOptions(screen.getByLabelText('Jenis target'), 'USER');
    await user.selectOptions(screen.getByLabelText('Target'), targetId);
    await user.click(screen.getByRole('button', { name: 'Tambahkan target' }));
    await user.selectOptions(screen.getByLabelText('Jenis target'), 'UNIT');
    await user.clear(screen.getByLabelText('Cari target'));
    await user.type(screen.getByLabelText('Cari target'), 'TEST');
    await screen.findByRole('option', { name: 'UNIT-UJI · Unit Uji' });
    await user.selectOptions(screen.getByLabelText('Target'), unitId);
    await user.click(screen.getByRole('button', { name: 'Tambahkan target' }));
    await user.selectOptions(screen.getByLabelText('Jenis target'), 'ROLE');
    await user.clear(screen.getByLabelText('Cari target'));
    await user.type(screen.getByLabelText('Cari target'), 'PIC');
    await screen.findByRole('option', { name: 'PIC (PIC)' });
    await user.selectOptions(screen.getByLabelText('Target'), roleId);
    await user.click(screen.getByRole('button', { name: 'Tambahkan target' }));
    expect(screen.getByText('PIC Uji · Analis')).toBeVisible();
    expect(screen.getByText('UNIT-UJI · Unit Uji')).toBeVisible();
    expect(
      within(screen.getByRole('list', { name: 'Target disposisi terpilih' })).getByText(
        'PIC (PIC)',
      ),
    ).toBeVisible();
    await user.type(screen.getByLabelText('Instruksi disposisi'), disposition.instruction);
    await user.click(screen.getByRole('button', { name: 'Simpan disposisi' }));

    expect(await screen.findByText(disposition.instruction)).toBeVisible();
    expect(screen.getByText(/Target: PIC Uji/)).toBeVisible();
    await waitFor(() => {
      const createCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === `/api/v1/meetings/${meetingId}/dispositions` && init?.method === 'POST',
      );
      expect(createCall).toBeDefined();
      expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
        source_minutes_revision_id: revisionId,
        source_decision_id: decisionId,
        instruction: disposition.instruction,
        targets: [
          { target_type: 'USER', user_id: targetId },
          { target_type: 'UNIT', unit_id: unitId },
          { target_type: 'ROLE', role_id: roleId },
        ],
      });
    });
  });
});
