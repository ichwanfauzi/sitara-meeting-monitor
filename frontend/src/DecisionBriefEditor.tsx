import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import {
  ApiError,
  approveDecisionBriefVersion,
  canCreateDecisionBrief,
  canReviewDecisionBrief,
  createDecisionBriefVersion,
  getDecisionBriefHistory,
  getMeetings,
  getMinutesRevisions,
  rejectDecisionBriefVersion,
  submitDecisionBriefVersion,
  withdrawDecisionBriefVersion,
  type AuthenticatedUser,
  type DecisionBriefApprovalState,
  type DecisionBriefVersion,
  type MeetingSummary,
  type MinutesDecision,
  type MinutesRevision,
} from './api';
import MeetingDocumentSelection from './MeetingDocumentSelection';

interface DecisionSource {
  decision: MinutesDecision;
  agendaTitle: string;
  discussionSubject: string | null;
}

interface DecisionBriefEditorProps {
  authenticatedUser: AuthenticatedUser;
  targetMeetingId?: string;
}

interface PreservedBriefChanges {
  summary: string;
  decisions: Array<{
    sourceText: string;
    agendaTitle: string;
    discussionSubject: string | null;
    briefText: string;
  }>;
}

interface DecisionBriefTableRow {
  id: string;
  agendaTitle: string;
  discussionSubject: string | null;
  briefText: string;
  picSuggestion: string | null;
  supportingPicSuggestion: string | null;
  outputExpected: string | null;
  targetDate: string | null;
  targetText: string | null;
}

const approvalStateLabels: Record<DecisionBriefApprovalState, string> = {
  DRAFT: 'Belum diajukan',
  PENDING_APPROVAL: 'Menunggu persetujuan',
  APPROVED: 'Disetujui',
  REJECTED: 'Ditolak',
  WITHDRAWN: 'Ditarik',
};

function activeRevisionOf(revisions: MinutesRevision[]): MinutesRevision | null {
  return revisions.reduce<MinutesRevision | null>(
    (active, revision) =>
      active === null || revision.revision_number > active.revision_number ? revision : active,
    null,
  );
}

function latestBriefForRevision(
  history: DecisionBriefVersion[],
  revisionId: string | null,
): DecisionBriefVersion | null {
  if (!revisionId) return null;
  return history
    .filter((brief) => brief.source_minutes_revision_id === revisionId)
    .reduce<DecisionBriefVersion | null>(
      (latest, brief) =>
        latest === null || brief.version_number > latest.version_number ? brief : latest,
      null,
    );
}

function briefTextsForSource(
  revision: MinutesRevision | null,
  brief: DecisionBriefVersion | null,
): Record<string, string> {
  const savedTexts = new Map(
    (brief?.decisions ?? []).map((decision) => [decision.decision_id, decision.brief_text ?? '']),
  );
  const decisionIds =
    revision?.format_version === 2
      ? revision.discussions.flatMap((discussion) =>
          discussion.decisions.map((decision) => decision.id),
        )
      : [];
  return Object.fromEntries(decisionIds.map((id) => [id, savedTexts.get(id) ?? '']));
}

function briefPrefillKey(
  revision: MinutesRevision | null,
  brief: DecisionBriefVersion | null,
  meetingId: string,
): string {
  return brief?.id ?? `minutes:${revision?.id ?? meetingId}`;
}

function readableDate(value: string | null | undefined): string {
  if (!value) return 'Belum ditentukan';
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('id-ID', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(date);
}

function rowsForBrief(
  version: DecisionBriefVersion,
  revisions: MinutesRevision[],
): DecisionBriefTableRow[] {
  const sourceRevision = revisions.find(
    (revision) => revision.id === version.source_minutes_revision_id,
  );
  const sourceDecisions = new Map(
    sourceRevision?.format_version === 2
      ? sourceRevision.discussions.flatMap((discussion) =>
          discussion.decisions.map((decision) => [decision.id, decision] as const),
        )
      : [],
  );

  return [...version.decisions]
    .sort((left, right) => left.position - right.position)
    .map((briefDecision) => {
      const sourceDecision = sourceDecisions.get(briefDecision.decision_id);
      return {
        id: briefDecision.decision_id,
        agendaTitle: briefDecision.source_agenda_title,
        discussionSubject: briefDecision.source_discussion_subject,
        briefText: briefDecision.brief_text ?? '',
        picSuggestion: sourceDecision?.pic_suggestion ?? null,
        supportingPicSuggestion: sourceDecision?.supporting_pic_suggestion ?? null,
        outputExpected: sourceDecision?.output_expected ?? null,
        targetDate: sourceDecision?.target_date ?? null,
        targetText: sourceDecision?.target_text ?? null,
      };
    });
}

function DecisionBriefTable({
  accessibleName,
  rows,
  editable = false,
  onBriefTextChange,
}: {
  accessibleName: string;
  rows: DecisionBriefTableRow[];
  editable?: boolean;
  onBriefTextChange?: (decisionId: string, value: string) => void;
}) {
  return (
    <div
      className="decision-brief-table-scroll"
      role="region"
      aria-label={`Gulir ${accessibleName}`}
      tabIndex={0}
    >
      <table className="decision-brief-table" aria-label={accessibleName}>
        <colgroup>
          <col className="decision-brief-column-number" />
          <col className="decision-brief-column-topic" />
          <col className="decision-brief-column-decision" />
          <col className="decision-brief-column-pic" />
          <col className="decision-brief-column-supporting-pic" />
          <col className="decision-brief-column-output" />
          <col className="decision-brief-column-target" />
        </colgroup>
        <thead>
          <tr>
            <th scope="col">No.</th>
            <th scope="col">Bahasan</th>
            <th scope="col">Putusan/Tindak Lanjut</th>
            <th scope="col">PIC</th>
            <th scope="col">PIC pendukung</th>
            <th scope="col">Output</th>
            <th scope="col">Target Penyelesaian</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const topic = row.discussionSubject?.trim() || row.agendaTitle;
            const showAgenda = Boolean(
              row.discussionSubject?.trim() && row.agendaTitle !== row.discussionSubject.trim(),
            );
            return (
              <tr key={row.id}>
                <td>{index + 1}</td>
                <td>
                  <strong>{topic}</strong>
                  {showAgenda && <small>{row.agendaTitle}</small>}
                </td>
                <td>
                  {editable ? (
                    <textarea
                      className="decision-brief-table-input"
                      aria-label={`Putusan atau tindak lanjut untuk ${topic}`}
                      maxLength={20_000}
                      required
                      rows={decisionBriefTextareaRows(row.briefText)}
                      value={row.briefText}
                      onChange={(event) => onBriefTextChange?.(row.id, event.target.value)}
                    />
                  ) : (
                    row.briefText || '—'
                  )}
                </td>
                <td>{row.picSuggestion || '—'}</td>
                <td>{row.supportingPicSuggestion || '—'}</td>
                <td>{row.outputExpected || '—'}</td>
                <td>{row.targetDate ? readableDate(row.targetDate) : row.targetText || '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function decisionBriefTextareaRows(value: string): number {
  return Math.max(2, Math.min(6, Math.ceil(value.trim().length / 50)));
}

function DecisionBriefEditor({ authenticatedUser, targetMeetingId }: DecisionBriefEditorProps) {
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [selectedMeetingId, setSelectedMeetingId] = useState('');
  const [revisions, setRevisions] = useState<MinutesRevision[]>([]);
  const [history, setHistory] = useState<DecisionBriefVersion[]>([]);
  const [meetingsLoading, setMeetingsLoading] = useState(true);
  const [dataLoading, setDataLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [workflowActionId, setWorkflowActionId] = useState<string | null>(null);
  const [printingBriefId, setPrintingBriefId] = useState<string | null>(null);
  const [rejectionReasons, setRejectionReasons] = useState<Record<string, string>>({});
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [briefTexts, setBriefTexts] = useState<Record<string, string>>({});
  const [preservedChanges, setPreservedChanges] = useState<PreservedBriefChanges | null>(null);
  const lastPrefilledSource = useRef<string | null>(null);

  const selectedMeeting = meetings.find((meeting) => meeting.id === selectedMeetingId) ?? null;
  const canCreate = Boolean(canCreateDecisionBrief(authenticatedUser) && selectedMeeting);
  const canEdit = Boolean(canCreate && selectedMeeting?.status !== 'ARCHIVED');
  const canReview = Boolean(
    canReviewDecisionBrief(authenticatedUser) && selectedMeeting?.status !== 'ARCHIVED',
  );
  const activeRevision = useMemo(() => activeRevisionOf(revisions), [revisions]);
  const activeSourceBrief = useMemo(
    () => latestBriefForRevision(history, activeRevision?.id ?? null),
    [activeRevision, history],
  );
  const prefillSourceKey = briefPrefillKey(activeRevision, activeSourceBrief, selectedMeetingId);
  const sourceDecisions = useMemo<DecisionSource[]>(() => {
    if (!selectedMeeting || activeRevision?.format_version !== 2) return [];
    return activeRevision.discussions.flatMap((discussion) => {
      const agenda = selectedMeeting.agendas.find((item) => item.id === discussion.agenda_id);
      return discussion.decisions.map((decision) => ({
        decision,
        agendaTitle: agenda?.title ?? 'Agenda sumber',
        discussionSubject: discussion.subject,
      }));
    });
  }, [activeRevision, selectedMeeting]);
  const selectedSources = sourceDecisions;
  const draftRows = useMemo<DecisionBriefTableRow[]>(
    () =>
      selectedSources.map(({ decision, agendaTitle, discussionSubject }) => ({
        id: decision.id,
        agendaTitle,
        discussionSubject,
        briefText: briefTexts[decision.id] ?? '',
        picSuggestion: decision.pic_suggestion ?? null,
        supportingPicSuggestion: decision.supporting_pic_suggestion ?? null,
        outputExpected: decision.output_expected,
        targetDate: decision.target_date,
        targetText: decision.target_text,
      })),
    [briefTexts, selectedSources],
  );
  useEffect(() => {
    if (lastPrefilledSource.current === prefillSourceKey) return;
    lastPrefilledSource.current = prefillSourceKey;
    setBriefTexts(briefTextsForSource(activeRevision, activeSourceBrief));
  }, [activeRevision, activeSourceBrief, prefillSourceKey]);

  useEffect(() => {
    let current = true;
    void getMeetings()
      .then((items) => {
        if (!current) return;
        setMeetings(items);
        const initialMeeting = targetMeetingId
          ? items.find((meeting) => meeting.id === targetMeetingId)
          : undefined;
        setSelectedMeetingId(initialMeeting?.id ?? '');
      })
      .catch((error: unknown) => {
        if (current) setErrorMessage(errorMessageOf(error));
      })
      .finally(() => {
        if (current) setMeetingsLoading(false);
      });
    return () => {
      current = false;
    };
  }, [targetMeetingId]);

  useEffect(() => {
    if (!selectedMeetingId) {
      setRevisions([]);
      setHistory([]);
      return;
    }
    let current = true;
    setDataLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    void Promise.all([
      getMinutesRevisions(selectedMeetingId),
      getDecisionBriefHistory(selectedMeetingId),
    ])
      .then(([nextRevisions, nextHistory]) => {
        if (!current) return;
        const nextActiveRevision = activeRevisionOf(nextRevisions);
        const nextActiveSourceBrief = latestBriefForRevision(
          nextHistory,
          nextActiveRevision?.id ?? null,
        );
        const nextPrefillKey = briefPrefillKey(
          nextActiveRevision,
          nextActiveSourceBrief,
          selectedMeetingId,
        );
        if (lastPrefilledSource.current !== nextPrefillKey) {
          lastPrefilledSource.current = nextPrefillKey;
          setBriefTexts(briefTextsForSource(nextActiveRevision, nextActiveSourceBrief));
        }
        setRevisions(nextRevisions);
        setHistory(nextHistory);
      })
      .catch((error: unknown) => {
        if (current) setErrorMessage(errorMessageOf(error));
      })
      .finally(() => {
        if (current) setDataLoading(false);
      });
    return () => {
      current = false;
    };
  }, [selectedMeetingId]);

  useEffect(() => {
    const resetPrintingBrief = () => {
      document.body.classList.remove('sitara-print-mode');
      setPrintingBriefId(null);
    };
    window.addEventListener('afterprint', resetPrintingBrief);
    return () => window.removeEventListener('afterprint', resetPrintingBrief);
  }, []);

  async function refreshSourceAndHistory(): Promise<void> {
    if (!selectedMeetingId) return;
    const [nextRevisions, nextHistory] = await Promise.all([
      getMinutesRevisions(selectedMeetingId),
      getDecisionBriefHistory(selectedMeetingId),
    ]);
    setRevisions(nextRevisions);
    setHistory(nextHistory);
  }

  async function handleWorkflowAction(
    version: DecisionBriefVersion,
    action: 'submit' | 'approve' | 'reject' | 'withdraw',
    reason?: string,
  ): Promise<void> {
    if (!selectedMeetingId) return;
    if (action === 'reject' && !reason?.trim()) {
      setErrorMessage('Alasan penolakan wajib diisi.');
      return;
    }

    setWorkflowActionId(version.id);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const updated =
        action === 'submit'
          ? await submitDecisionBriefVersion(selectedMeetingId, version.id)
          : action === 'approve'
            ? await approveDecisionBriefVersion(selectedMeetingId, version.id)
            : action === 'reject'
              ? await rejectDecisionBriefVersion(selectedMeetingId, version.id, reason!.trim())
              : await withdrawDecisionBriefVersion(selectedMeetingId, version.id);
      setHistory((previous) => previous.map((item) => (item.id === updated.id ? updated : item)));
      if (action === 'reject') {
        setRejectionReasons((previous) => ({ ...previous, [version.id]: '' }));
      }
      const messages = {
        submit: 'Decision Brief diajukan untuk persetujuan.',
        approve: 'Decision Brief disetujui.',
        reject: 'Decision Brief ditolak dan alasan dicatat.',
        withdraw: 'Pengajuan Decision Brief ditarik.',
      };
      setSuccessMessage(messages[action]);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          await refreshSourceAndHistory();
        } catch (refreshError: unknown) {
          setErrorMessage(`${errorMessageOf(error)} ${errorMessageOf(refreshError)}`);
        }
      } else {
        setErrorMessage(errorMessageOf(error));
      }
    } finally {
      setWorkflowActionId(null);
    }
  }

  function printBrief(briefId: string): void {
    document.body.classList.add('sitara-print-mode');
    setPrintingBriefId(briefId);
    window.setTimeout(() => window.print(), 0);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!selectedMeetingId || !activeRevision || !canEdit) return;
    if (selectedSources.length !== sourceDecisions.length || selectedSources.length === 0) {
      setErrorMessage('Decision Brief harus memuat seluruh keputusan dari notulensi terbaru.');
      return;
    }
    if (selectedSources.some(({ decision }) => !briefTexts[decision.id]?.trim())) {
      setErrorMessage('Isi Putusan/Tindak Lanjut pada setiap baris sebelum menyimpan perubahan.');
      return;
    }
    setSaving(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const created = await createDecisionBriefVersion(selectedMeetingId, {
        source_minutes_revision_id: activeRevision.id,
        summary: selectedMeeting
          ? `${selectedMeeting.meeting_number} · ${selectedMeeting.title}`
          : 'Decision Brief Rapat Pimpinan',
        notes: null,
        decisions: selectedSources.map(({ decision }) => ({
          decision_id: decision.id,
          brief_text: briefTexts[decision.id]?.trim() ?? '',
          priority: '',
          editorial_note: null,
        })),
      });
      setHistory((previous) => [...previous, created]);
      setSuccessMessage('Perubahan Decision Brief tersimpan.');
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 409) {
        setPreservedChanges({
          summary: selectedMeeting
            ? `${selectedMeeting.meeting_number} · ${selectedMeeting.title}`
            : 'Decision Brief Rapat Pimpinan',
          decisions: selectedSources.map(({ decision, agendaTitle, discussionSubject }) => ({
            sourceText: decision.decision_text,
            agendaTitle,
            discussionSubject,
            briefText: briefTexts[decision.id] ?? '',
          })),
        });
        setErrorMessage(
          'Notulensi berubah sejak halaman dibuka. Sumber terbaru sudah dimuat ulang; periksa setiap putusan lalu simpan kembali.',
        );
        try {
          await refreshSourceAndHistory();
        } catch (refreshError: unknown) {
          setErrorMessage(`${errorMessageOf(error)} ${errorMessageOf(refreshError)}`);
        }
      } else {
        setErrorMessage(errorMessageOf(error));
      }
    } finally {
      setSaving(false);
    }
  }

  if (meetingsLoading) {
    return (
      <p className="decision-brief-state" role="status">
        Memuat rapat...
      </p>
    );
  }
  if (
    targetMeetingId &&
    !errorMessage &&
    !meetings.some((meeting) => meeting.id === targetMeetingId)
  ) {
    return (
      <p className="minutes-alert" role="alert">
        Rapat tidak termasuk dalam cakupan akses Anda.
      </p>
    );
  }
  if (meetings.length === 0) {
    return (
      <>
        {errorMessage && (
          <p className="minutes-alert" role="alert">
            {errorMessage}
          </p>
        )}
        <p className="decision-brief-state">Tidak ada rapat yang dapat diakses.</p>
      </>
    );
  }

  if (!targetMeetingId && !selectedMeeting) {
    return (
      <MeetingDocumentSelection
        meetings={meetings}
        documentName="Decision Brief"
        routePrefix="#decision-briefs"
      />
    );
  }

  return (
    <section className="decision-brief-page" aria-labelledby="decision-brief-title">
      <header className="decision-brief-heading">
        <div>
          <h1 id="decision-brief-title">Decision Brief</h1>
          {selectedMeeting && (
            <p className="decision-brief-meeting-meta">
              {selectedMeeting.meeting_number} · {selectedMeeting.title} ·{' '}
              {readableDate(selectedMeeting.meeting_date)}
            </p>
          )}
        </div>
      </header>

      <a className="repository-back-link" href="#decision-briefs">
        Kembali ke daftar rapat
      </a>

      {errorMessage && (
        <p className="minutes-alert" role="alert">
          {errorMessage}
        </p>
      )}
      {successMessage && (
        <p className="minutes-notice" role="status">
          {successMessage}
        </p>
      )}

      {preservedChanges && (
        <section className="minutes-alert" aria-labelledby="preserved-brief-title">
          <h2 id="preserved-brief-title">Perubahan yang belum tersimpan</h2>
          <p>Periksa kembali sumber notulensi dan isi ringkasan sebelum menyimpan.</p>
          <p>{preservedChanges.summary}</p>
          <ul>
            {preservedChanges.decisions.map((decision, index) => (
              <li key={`${decision.sourceText}-${index}`}>
                <strong>{decision.discussionSubject || decision.agendaTitle}</strong>
                <span>Putusan pada notulensi: {decision.sourceText}</span>
                <span>Isi Decision Brief: {decision.briefText || 'belum diisi'}</span>
              </li>
            ))}
          </ul>
          <button
            className="button button--secondary"
            onClick={() => setPreservedChanges(null)}
            type="button"
          >
            Tutup ringkasan perubahan
          </button>
        </section>
      )}

      {selectedMeeting?.status === 'ARCHIVED' && (
        <p className="minutes-readonly-note">Rapat arsip · hanya dapat dilihat dan dicetak.</p>
      )}

      {dataLoading ? (
        <p className="decision-brief-state" role="status">
          Memuat sumber keputusan...
        </p>
      ) : (
        <div className="decision-brief-layout">
          <div className="surface-panel decision-brief-form-panel">
            <div className="decision-brief-source">
              <h2>Sumber keputusan</h2>
              {!activeRevision && <p>Rapat ini belum memiliki notulensi.</p>}
            </div>

            {!canEdit && !canReview && selectedMeeting?.status !== 'ARCHIVED' && (
              <p className="minutes-readonly-note">Akun ini hanya dapat membaca Decision Brief.</p>
            )}
            {activeRevision?.format_version === 1 && (
              <p className="minutes-readonly-note">
                Catatan lama tersedia, tetapi belum memiliki keputusan terstruktur untuk dipilih
                sebagai sumber.
              </p>
            )}
            {activeRevision?.format_version === 2 && sourceDecisions.length === 0 && (
              <p className="minutes-readonly-note">
                Notulensi belum mencatat keputusan terstruktur.
              </p>
            )}

            {canEdit && activeRevision?.format_version === 2 && sourceDecisions.length > 0 && (
              <form className="decision-brief-form" onSubmit={(event) => void handleSubmit(event)}>
                <section className="decision-brief-sources" aria-label="Isi Decision Brief">
                  <div className="decision-brief-document-heading">
                    <h4>DECISION BRIEF RAPAT PIMPINAN</h4>
                    <p>
                      {selectedMeeting?.meeting_number} · {selectedMeeting?.title}
                    </p>
                    <p>Rapim {readableDate(selectedMeeting?.meeting_date)}</p>
                  </div>
                  <DecisionBriefTable
                    accessibleName="Form tabel Decision Brief"
                    rows={draftRows}
                    editable
                    onBriefTextChange={(decisionId, value) =>
                      setBriefTexts((previous) => ({ ...previous, [decisionId]: value }))
                    }
                  />
                </section>
                <button className="button button--primary" disabled={saving} type="submit">
                  {saving
                    ? 'Menyimpan...'
                    : activeSourceBrief
                      ? 'Simpan perubahan'
                      : 'Simpan Decision Brief'}
                </button>
              </form>
            )}

            {!canEdit &&
              activeRevision?.format_version === 2 &&
              sourceDecisions.length > 0 &&
              (activeSourceBrief ? (
                <DecisionBriefTable
                  accessibleName="Tabel Decision Brief"
                  rows={rowsForBrief(activeSourceBrief, revisions)}
                />
              ) : (
                <p className="decision-brief-state">
                  Belum ada Decision Brief untuk notulensi ini.
                </p>
              ))}

            {activeSourceBrief && (
              <section className="decision-brief-approval" aria-label="Status pengesahan">
                <h2>Status pengesahan</h2>
                <p>
                  <strong>
                    {selectedMeeting?.status === 'ARCHIVED'
                      ? 'Tersimpan'
                      : approvalStateLabels[activeSourceBrief.approval_state]}
                  </strong>
                </p>
                {activeSourceBrief.approval_state === 'REJECTED' &&
                  activeSourceBrief.approval_events.at(-1)?.reason && (
                    <p>Catatan penolakan: {activeSourceBrief.approval_events.at(-1)?.reason}</p>
                  )}
                <button
                  className="button button--secondary"
                  onClick={() => printBrief(activeSourceBrief.id)}
                  type="button"
                >
                  Cetak Decision Brief
                </button>
                <article
                  className={`decision-brief-printable decision-brief-print-only${printingBriefId === activeSourceBrief.id ? ' sitara-print-target' : ''}`}
                  data-print-target={printingBriefId === activeSourceBrief.id ? 'true' : undefined}
                >
                  <header className="decision-brief-document-heading">
                    <h4>DECISION BRIEF RAPAT PIMPINAN</h4>
                    <p>
                      {selectedMeeting?.meeting_number} · {selectedMeeting?.title}
                    </p>
                    <p>Rapim {readableDate(selectedMeeting?.meeting_date)}</p>
                  </header>
                  <DecisionBriefTable
                    accessibleName="Tabel cetak Decision Brief"
                    rows={rowsForBrief(activeSourceBrief, revisions)}
                  />
                </article>
                {(canEdit || canReview) &&
                  selectedMeeting?.status === 'FINAL' &&
                  ['DRAFT', 'WITHDRAWN'].includes(activeSourceBrief.approval_state) && (
                    <button
                      className="button button--primary"
                      disabled={workflowActionId === activeSourceBrief.id}
                      onClick={() => void handleWorkflowAction(activeSourceBrief, 'submit')}
                      type="button"
                    >
                      {workflowActionId === activeSourceBrief.id
                        ? 'Mengirim...'
                        : 'Ajukan persetujuan'}
                    </button>
                  )}
                {canEdit &&
                  activeSourceBrief.created_by_id === authenticatedUser.id &&
                  activeSourceBrief.approval_state === 'PENDING_APPROVAL' && (
                    <button
                      className="button button--secondary"
                      disabled={workflowActionId === activeSourceBrief.id}
                      onClick={() => void handleWorkflowAction(activeSourceBrief, 'withdraw')}
                      type="button"
                    >
                      Tarik pengajuan
                    </button>
                  )}
                {canReview &&
                  activeSourceBrief.created_by_id !== authenticatedUser.id &&
                  activeSourceBrief.approval_state === 'PENDING_APPROVAL' && (
                    <div>
                      <button
                        className="button button--primary"
                        disabled={workflowActionId === activeSourceBrief.id}
                        onClick={() => void handleWorkflowAction(activeSourceBrief, 'approve')}
                        type="button"
                      >
                        Setujui
                      </button>
                      <label
                        className="minutes-field-label"
                        htmlFor={`brief-rejection-reason-${activeSourceBrief.id}`}
                      >
                        Alasan penolakan
                        <textarea
                          className="minutes-textarea"
                          id={`brief-rejection-reason-${activeSourceBrief.id}`}
                          maxLength={4_000}
                          value={rejectionReasons[activeSourceBrief.id] ?? ''}
                          onChange={(event) =>
                            setRejectionReasons((previous) => ({
                              ...previous,
                              [activeSourceBrief.id]: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <button
                        className="button button--secondary"
                        disabled={
                          workflowActionId === activeSourceBrief.id ||
                          !rejectionReasons[activeSourceBrief.id]?.trim()
                        }
                        onClick={() =>
                          void handleWorkflowAction(
                            activeSourceBrief,
                            'reject',
                            rejectionReasons[activeSourceBrief.id],
                          )
                        }
                        type="button"
                      >
                        Tolak
                      </button>
                    </div>
                  )}
              </section>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function errorMessageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Terjadi kesalahan saat memuat Decision Brief.';
}

export default DecisionBriefEditor;
