import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import type { MeetingSummary } from './api';
import RepositoryMeetingDetail from './RepositoryMeetingDetail';

const meetingId = '30000000-0000-4000-8000-000000000001';
const currentRevisionId = '40000000-0000-4000-8000-000000000002';
const currentDecisionId = '70000000-0000-4000-8000-000000000002';

const meeting: MeetingSummary = {
  id: meetingId,
  meeting_number: 'RAPIM-2026-001',
  title: 'Rapat sintetis repository',
  meeting_date: '2026-11-20',
  status: 'ARCHIVED',
  version: 4,
  agendas: [
    {
      id: '50000000-0000-4000-8000-000000000001',
      agenda_number: 1,
      title: 'Evaluasi layanan',
      agenda_description: null,
      pic_suggestion: null,
      supporting_pic_suggestion: null,
      sort_order: 1,
    },
  ],
};

const oldRevision = {
  id: '40000000-0000-4000-8000-000000000001',
  meeting_id: meetingId,
  revision_number: 1,
  format_version: 1,
  content: 'NOTULENSI LAMA YANG SUDAH DIGANTI',
  discussions: [],
  created_by_id: '20000000-0000-4000-8000-000000000001',
  created_at: '2026-11-19T10:00:00Z',
};

const currentRevision = {
  id: currentRevisionId,
  meeting_id: meetingId,
  revision_number: 2,
  format_version: 2,
  content: null,
  discussions: [
    {
      id: '60000000-0000-4000-8000-000000000002',
      agenda_id: meeting.agendas[0].id,
      discussion_number: 1,
      subject: 'Pembahasan terbaru',
      content: 'Catatan terbaru',
      decisions: [
        {
          id: currentDecisionId,
          discussion_id: '60000000-0000-4000-8000-000000000002',
          decision_number: 1,
          decision_text: 'PUTUSAN LENGKAP TERBARU',
          pic_suggestion: 'Wakil Rektor I',
          output_expected: 'Laporan evaluasi',
          target_date: '2026-12-01',
          target_text: null,
          is_action_item: true,
        },
      ],
    },
  ],
  created_by_id: '20000000-0000-4000-8000-000000000001',
  created_at: '2026-11-20T10:00:00Z',
};

const briefs = [
  {
    id: '80000000-0000-4000-8000-000000000001',
    meeting_id: meetingId,
    source_minutes_revision_id: oldRevision.id,
    version_number: 1,
    summary: 'BRIEF LAMA YANG SUDAH DIGANTI',
    notes: null,
    created_by_id: '20000000-0000-4000-8000-000000000001',
    created_at: '2026-11-19T11:00:00Z',
    is_stale: true,
    approval_state: 'DRAFT',
    approval_events: [],
    decisions: [],
  },
  {
    id: '80000000-0000-4000-8000-000000000002',
    meeting_id: meetingId,
    source_minutes_revision_id: currentRevisionId,
    version_number: 2,
    summary: 'Brief saat ini',
    notes: null,
    created_by_id: '20000000-0000-4000-8000-000000000001',
    created_at: '2026-11-20T11:00:00Z',
    is_stale: false,
    approval_state: 'APPROVED',
    approval_events: [],
    decisions: [
      {
        decision_id: currentDecisionId,
        source_decision_text: 'PUTUSAN LENGKAP TERBARU',
        source_agenda_id: meeting.agendas[0].id,
        source_agenda_title: 'Evaluasi layanan',
        source_discussion_id: currentRevision.discussions[0].id,
        source_discussion_subject: 'Pembahasan terbaru',
        brief_text: 'Ringkasan keputusan saat ini',
        priority: '',
        editorial_note: null,
        position: 1,
      },
    ],
  },
];

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

describe('RepositoryMeetingDetail', () => {
  it('shows only print actions for the latest minutes and Decision Brief', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url.endsWith('/minutes-revisions')) {
        return Response.json([oldRevision, currentRevision]);
      }
      if (url.endsWith('/decision-briefs')) return Response.json(briefs);
      if (url.includes('/action-items?')) return Response.json([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<RepositoryMeetingDetail meeting={meeting} />);

    expect(screen.queryByRole('region', { name: 'Informasi rapat' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: meeting.title })).toBeInTheDocument();
    const sectionNavigation = screen.getByRole('navigation', { name: 'Bagian rapat' });
    expect(within(sectionNavigation).getByRole('link', { name: 'Agenda' })).toHaveAttribute(
      'href',
      '#repo-agenda',
    );
    expect(within(sectionNavigation).getByRole('link', { name: 'Notulensi' })).toHaveAttribute(
      'href',
      '#repo-minutes',
    );
    expect(within(sectionNavigation).getByRole('link', { name: 'Decision Brief' })).toHaveAttribute(
      'href',
      '#repo-briefs',
    );
    expect(within(sectionNavigation).getByRole('link', { name: 'Tindak lanjut' })).toHaveAttribute(
      'href',
      '#repo-actions',
    );
    const agendaSection = screen.getByRole('region', { name: 'Agenda' });
    expect(within(agendaSection).getByText('Lihat 1 agenda')).toBeInTheDocument();
    expect(within(agendaSection).getByText('Evaluasi layanan')).not.toBeVisible();

    const minutesSection = await screen.findByRole('region', { name: 'Notulensi' });
    expect(within(minutesSection).getByText(/Notulensi tersimpan/)).toBeInTheDocument();
    expect(within(minutesSection).getByText('Buka notulensi')).toBeInTheDocument();
    expect(
      within(minutesSection).getByRole('button', { name: 'Cetak notulensi' }),
    ).not.toBeVisible();
    await userEvent.click(within(minutesSection).getByText('Buka notulensi'));
    expect(within(minutesSection).getByRole('button', { name: 'Cetak notulensi' })).toBeVisible();
    expect(within(minutesSection).getByText('Catatan terbaru')).toBeVisible();
    expect(minutesSection).not.toHaveTextContent('NOTULENSI LAMA YANG SUDAH DIGANTI');

    const briefSection = screen.getByRole('region', { name: 'Decision Brief' });
    expect(briefSection).toHaveTextContent('Brief terakhir');
    expect(within(briefSection).getByText('Buka Decision Brief')).toBeInTheDocument();
    expect(
      within(briefSection).getByRole('button', { name: 'Cetak Decision Brief' }),
    ).not.toBeVisible();
    expect(within(briefSection).getByRole('table')).not.toBeVisible();
    expect(briefSection).not.toHaveTextContent('BRIEF LAMA YANG SUDAH DIGANTI');
    expect(screen.queryByText(/Revisi \d|Versi \d|DRAFT/)).not.toBeInTheDocument();

    await userEvent.click(within(briefSection).getByText('Buka Decision Brief'));
    const print = vi.fn();
    vi.stubGlobal('print', print);
    await userEvent.click(
      within(briefSection).getByRole('button', { name: 'Cetak Decision Brief' }),
    );
    const printTable = await screen.findByRole('table', { name: 'Tabel cetak Decision Brief' });
    expect([...printTable.querySelectorAll('col')].map((column) => column.className)).toEqual([
      'repository-brief-column-number',
      'repository-brief-column-topic',
      'repository-brief-column-decision',
      'repository-brief-column-pic',
      'repository-brief-column-output',
      'repository-brief-column-target',
    ]);
    expect(printTable.closest('[data-print-target="true"]')).not.toBeNull();
    expect(print).toHaveBeenCalledOnce();
  });

  it('scrolls to repository sections without replacing the active app route', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url.endsWith('/minutes-revisions')) return Response.json([]);
      if (url.endsWith('/decision-briefs')) return Response.json([]);
      if (url.includes('/action-items?')) return Response.json([]);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    window.history.replaceState(null, '', `#search/${meeting.id}`);

    render(<RepositoryMeetingDetail meeting={meeting} />);

    const sections = [
      ['Agenda', 'repo-agenda'],
      ['Notulensi', 'repo-minutes'],
      ['Decision Brief', 'repo-briefs'],
      ['Tindak lanjut', 'repo-actions'],
    ] as const;
    for (const [label, sectionId] of sections) {
      const target = document.getElementById(sectionId);
      expect(target).not.toBeNull();
      const scrollIntoView = vi.fn();
      Object.defineProperty(target, 'scrollIntoView', {
        configurable: true,
        value: scrollIntoView,
      });

      await userEvent.click(screen.getByRole('link', { name: label }));

      expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
      expect(window.location.hash).toBe(`#search/${meeting.id}`);
    }
  });
});
