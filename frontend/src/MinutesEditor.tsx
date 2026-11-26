import { useEffect, useRef, useState } from 'react';
import {
  ApiError,
  canAccessMinutes,
  createMinutesRevision,
  getCurrentUser,
  getMeeting,
  getMeetings,
  getMinutesRevisions,
  type AuthenticatedUser,
  type MeetingSummary,
  type MinutesRevision,
  type StructuredMinutesRevisionInput,
} from './api';
import MeetingDocumentSelection from './MeetingDocumentSelection';

type LoadState = 'loading' | 'ready' | 'empty' | 'failed';
type SaveState = 'clean' | 'saved' | 'saving' | 'conflict' | 'statusChanged' | 'error' | 'reloaded';

interface DiscussionDraft {
  agenda_id: string;
  subject: string;
  content: string;
  decisions: DecisionDraft[];
}

interface DecisionDraft {
  decision_text: string;
  pic_suggestion: string;
  supporting_pic_suggestion: string;
  output_expected: string;
  target_kind: 'DATE' | 'TEXT';
  target_date: string;
  target_text: string;
  is_action_item: boolean;
}

const STALE_REVISION_DETAIL = 'Minutes changed since the supplied base revision';
const MEETING_NOT_LIVE_DETAIL = 'Minutes can only be edited while the meeting is LIVE';
export const UNSAVED_MINUTES_NAVIGATION_WARNING =
  'Perubahan notulensi belum disimpan. Tinggalkan halaman dan buang perubahan?';

const RESTRICTED_ROLES = new Set(['PIC', 'SUPER_ADMIN']);
const MINUTES_EDITOR_ROLES = new Set(['SEKRETARIAT', 'MANAGER_LEGAL', 'WAREK']);

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(date);
}

function accessErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Editor tidak dapat dimuat. Coba lagi.';
  if (error.status === 401) return 'Sesi tidak aktif. Silakan login kembali lalu buka editor.';
  if (error.status === 403 || error.status === 404) {
    return 'Akun ini tidak memiliki akses ke rapat atau notulensi tersebut.';
  }
  return error.message;
}

function sortRevisions(revisions: MinutesRevision[]): MinutesRevision[] {
  return [...revisions].sort((left, right) => left.revision_number - right.revision_number);
}

function activeRevision(revisions: MinutesRevision[]): MinutesRevision | null {
  return sortRevisions(revisions).at(-1) ?? null;
}

function structuredDraftFrom(revision: MinutesRevision | null): DiscussionDraft[] {
  if (revision?.format_version !== 2) return [];
  return revision.discussions.map((discussion) => ({
    agenda_id: discussion.agenda_id,
    subject: discussion.subject ?? '',
    content: discussion.content,
    decisions: discussion.decisions.map((decision) => ({
      decision_text: decision.decision_text,
      pic_suggestion: decision.pic_suggestion ?? '',
      supporting_pic_suggestion: decision.supporting_pic_suggestion ?? '',
      output_expected: decision.output_expected ?? '',
      target_kind: decision.target_text ? 'TEXT' : 'DATE',
      target_date: decision.target_date ?? '',
      target_text: decision.target_text ?? '',
      is_action_item: decision.is_action_item,
    })),
  }));
}

function structuredSnapshot(discussions: DiscussionDraft[]): StructuredMinutesRevisionInput {
  return {
    format_version: 2,
    content: null,
    discussions: discussions.map((discussion) => ({
      agenda_id: discussion.agenda_id,
      subject: discussion.subject.trim() || null,
      content: discussion.content,
      decisions: discussion.decisions.map((decision) => ({
        decision_text: decision.decision_text,
        pic_suggestion: decision.pic_suggestion.trim() || null,
        supporting_pic_suggestion: decision.supporting_pic_suggestion.trim() || null,
        output_expected: decision.output_expected.trim() || null,
        target_date: decision.target_kind === 'DATE' ? decision.target_date || null : null,
        target_text: decision.target_kind === 'TEXT' ? decision.target_text.trim() || null : null,
        is_action_item: decision.is_action_item,
      })),
    })),
  };
}

function structuredDraftText(discussions: DiscussionDraft[]): string {
  return JSON.stringify(structuredSnapshot(discussions), null, 2);
}

function isValidStructuredDraft(discussions: DiscussionDraft[]): boolean {
  return (
    discussions.length > 0 &&
    discussions.every(
      (discussion) =>
        discussion.content.trim().length > 0 &&
        discussion.decisions.every((decision) => decision.decision_text.trim().length > 0),
    )
  );
}

interface MinutesTableRow {
  agenda: MeetingSummary['agendas'][number];
  discussion: DiscussionDraft | null;
  discussionIndex: number | null;
}

function tableRowsForMeeting(
  meeting: MeetingSummary,
  discussions: DiscussionDraft[],
): MinutesTableRow[] {
  return meeting.agendas.flatMap<MinutesTableRow>((agenda) => {
    const agendaDiscussions = discussions
      .map((discussion, discussionIndex) => ({ discussion, discussionIndex }))
      .filter(({ discussion }) => discussion.agenda_id === agenda.id);
    if (agendaDiscussions.length === 0) {
      return [
        {
          agenda,
          discussion: null,
          discussionIndex: null,
        },
      ];
    }

    return agendaDiscussions.map(({ discussion, discussionIndex }) => ({
      agenda,
      discussion,
      discussionIndex,
    }));
  });
}

function updateDecision(
  discussion: DiscussionDraft,
  decisionIndex: number,
  update: (decision: DecisionDraft) => DecisionDraft,
): DiscussionDraft {
  return {
    ...discussion,
    decisions: discussion.decisions.map((decision, index) =>
      index === decisionIndex ? update(decision) : decision,
    ),
  };
}

function MinutesGuidedEditor({
  meeting,
  discussions,
  canEdit,
  loadingRevisions,
  saveState,
  onUpdateDiscussion,
  onAddDiscussion,
  onRemoveDiscussion,
}: {
  meeting: MeetingSummary;
  discussions: DiscussionDraft[];
  canEdit: boolean;
  loadingRevisions: boolean;
  saveState: SaveState;
  onUpdateDiscussion: (
    discussionIndex: number,
    update: (discussion: DiscussionDraft) => DiscussionDraft,
  ) => void;
  onAddDiscussion: (agendaId: string) => void;
  onRemoveDiscussion: (discussionIndex: number) => void;
}) {
  const fieldsDisabled = !canEdit || loadingRevisions || saveState === 'saving';
  const actionsDisabled = !canEdit || saveState === 'saving';

  return (
    <section className="minutes-guided-form" aria-label="Form pengisian hasil rapat" tabIndex={0}>
      {meeting.agendas.length === 0 ? (
        <p className="minutes-form-empty">
          Tambahkan agenda pada data rapat sebelum mengisi hasil rapat.
        </p>
      ) : (
        meeting.agendas.map((agenda) => {
          const agendaDiscussions = discussions.flatMap((discussion, discussionIndex) =>
            discussion.agenda_id === agenda.id ? [{ discussion, discussionIndex }] : [],
          );
          const agendaHeadingId = `minutes-agenda-heading-${agenda.id}`;

          return (
            <section
              className="minutes-agenda-card"
              key={agenda.id}
              aria-labelledby={agendaHeadingId}
            >
              <header className="minutes-agenda-heading">
                <span>Agenda {agenda.agenda_number}</span>
                <h3 id={agendaHeadingId}>{agenda.title}</h3>
              </header>
              {agendaDiscussions.length === 0 ? (
                <div className="minutes-agenda-empty">
                  <p>Belum ada pokok bahasan untuk agenda ini.</p>
                  <button
                    className="button button--secondary minutes-row-action"
                    disabled={actionsDisabled}
                    onClick={() => onAddDiscussion(agenda.id)}
                    type="button"
                  >
                    Isi pokok bahasan
                  </button>
                </div>
              ) : (
                <>
                  <div className="minutes-guided-discussions">
                    {agendaDiscussions.map(({ discussion, discussionIndex }, index) => {
                      const discussionHeadingId = `minutes-discussion-heading-${discussionIndex}`;

                      return (
                        <section
                          className="minutes-guided-discussion"
                          key={discussionIndex}
                          aria-labelledby={discussionHeadingId}
                        >
                          <div className="minutes-guided-heading">
                            <h4 id={discussionHeadingId}>Pokok bahasan {index + 1}</h4>
                            <button
                              className="button button--secondary minutes-row-action"
                              disabled={actionsDisabled}
                              onClick={() => onRemoveDiscussion(discussionIndex)}
                              type="button"
                            >
                              Hapus bahasan
                            </button>
                          </div>
                          <div className="minutes-guided-fields">
                            <label className="minutes-table-field">
                              Judul pokok pembahasan
                              <input
                                aria-label={
                                  'Judul pembahasan ' +
                                  (discussionIndex + 1) +
                                  ' agenda ' +
                                  agenda.agenda_number
                                }
                                className="minutes-input"
                                disabled={fieldsDisabled}
                                maxLength={500}
                                value={discussion.subject}
                                onChange={(event) =>
                                  onUpdateDiscussion(discussionIndex, (current) => ({
                                    ...current,
                                    subject: event.target.value,
                                  }))
                                }
                              />
                            </label>
                            <label className="minutes-table-field">
                              Isi pokok pembahasan
                              <textarea
                                aria-label={
                                  'Isi pembahasan ' +
                                  (discussionIndex + 1) +
                                  ' agenda ' +
                                  agenda.agenda_number
                                }
                                className="minutes-textarea minutes-entry-textarea"
                                disabled={fieldsDisabled}
                                maxLength={100_000}
                                rows={5}
                                value={discussion.content}
                                onChange={(event) =>
                                  onUpdateDiscussion(discussionIndex, (current) => ({
                                    ...current,
                                    content: event.target.value,
                                  }))
                                }
                              />
                            </label>
                          </div>

                          <section className="minutes-guided-decisions">
                            <h5>Putusan dan arahan</h5>
                            {discussion.decisions.length === 0 ? (
                              <p className="minutes-muted">
                                Belum ada putusan. Tambahkan putusan jika rapat menghasilkan
                                keputusan atau arahan.
                              </p>
                            ) : (
                              <div className="minutes-guided-decision-list">
                                {discussion.decisions.map((decision, decisionIndex) => {
                                  const decisionHeadingId = `minutes-decision-heading-${discussionIndex}-${decisionIndex}`;

                                  return (
                                    <section
                                      className="minutes-guided-decision"
                                      key={decisionIndex}
                                      aria-labelledby={decisionHeadingId}
                                    >
                                      <div className="minutes-guided-heading">
                                        <h6 id={decisionHeadingId}>Putusan {decisionIndex + 1}</h6>
                                        <button
                                          className="button button--secondary minutes-row-action"
                                          disabled={actionsDisabled}
                                          onClick={() =>
                                            onUpdateDiscussion(discussionIndex, (current) => ({
                                              ...current,
                                              decisions: current.decisions.filter(
                                                (_, itemIndex) => itemIndex !== decisionIndex,
                                              ),
                                            }))
                                          }
                                          type="button"
                                        >
                                          Hapus putusan
                                        </button>
                                      </div>
                                      <label className="minutes-table-field">
                                        Isi putusan/arahan
                                        <textarea
                                          aria-label={
                                            'Isi putusan ' +
                                            (decisionIndex + 1) +
                                            ' pembahasan ' +
                                            (discussionIndex + 1)
                                          }
                                          className="minutes-textarea minutes-entry-textarea"
                                          disabled={fieldsDisabled}
                                          maxLength={20_000}
                                          rows={4}
                                          value={decision.decision_text}
                                          onChange={(event) =>
                                            onUpdateDiscussion(discussionIndex, (current) =>
                                              updateDecision(current, decisionIndex, (item) => ({
                                                ...item,
                                                decision_text: event.target.value,
                                              })),
                                            )
                                          }
                                        />
                                      </label>
                                      <label className="minutes-checkbox-label">
                                        <input
                                          checked={decision.is_action_item}
                                          disabled={fieldsDisabled}
                                          onChange={(event) =>
                                            onUpdateDiscussion(discussionIndex, (current) =>
                                              updateDecision(current, decisionIndex, (item) => ({
                                                ...item,
                                                is_action_item: event.target.checked,
                                              })),
                                            )
                                          }
                                          type="checkbox"
                                        />
                                        Memerlukan tindak lanjut
                                      </label>
                                      {decision.is_action_item && (
                                        <div className="minutes-guided-follow-up">
                                          <h6>Rencana tindak lanjut</h6>
                                          <label className="minutes-table-field">
                                            PIC usulan
                                            <input
                                              aria-label="PIC usulan"
                                              className="minutes-input"
                                              disabled={fieldsDisabled}
                                              maxLength={300}
                                              value={decision.pic_suggestion}
                                              onChange={(event) =>
                                                onUpdateDiscussion(discussionIndex, (current) =>
                                                  updateDecision(
                                                    current,
                                                    decisionIndex,
                                                    (item) => ({
                                                      ...item,
                                                      pic_suggestion: event.target.value,
                                                    }),
                                                  ),
                                                )
                                              }
                                            />
                                          </label>
                                          <label className="minutes-table-field">
                                            PIC pendukung (opsional)
                                            <input
                                              aria-label="PIC pendukung (opsional)"
                                              className="minutes-input"
                                              disabled={fieldsDisabled}
                                              maxLength={2_000}
                                              value={decision.supporting_pic_suggestion}
                                              onChange={(event) =>
                                                onUpdateDiscussion(discussionIndex, (current) =>
                                                  updateDecision(
                                                    current,
                                                    decisionIndex,
                                                    (item) => ({
                                                      ...item,
                                                      supporting_pic_suggestion: event.target.value,
                                                    }),
                                                  ),
                                                )
                                              }
                                            />
                                          </label>
                                          <label className="minutes-table-field minutes-guided-output">
                                            Output yang diharapkan
                                            <textarea
                                              aria-label="Output yang diharapkan"
                                              className="minutes-textarea minutes-entry-textarea"
                                              disabled={fieldsDisabled}
                                              maxLength={20_000}
                                              rows={3}
                                              value={decision.output_expected}
                                              onChange={(event) =>
                                                onUpdateDiscussion(discussionIndex, (current) =>
                                                  updateDecision(
                                                    current,
                                                    decisionIndex,
                                                    (item) => ({
                                                      ...item,
                                                      output_expected: event.target.value,
                                                    }),
                                                  ),
                                                )
                                              }
                                            />
                                          </label>
                                          <div className="minutes-guided-target">
                                            <label className="minutes-table-field">
                                              Jenis target penyelesaian
                                              <select
                                                aria-label="Jenis target penyelesaian"
                                                className="minutes-input"
                                                disabled={fieldsDisabled}
                                                value={decision.target_kind}
                                                onChange={(event) =>
                                                  onUpdateDiscussion(discussionIndex, (current) =>
                                                    updateDecision(
                                                      current,
                                                      decisionIndex,
                                                      (item) => ({
                                                        ...item,
                                                        target_kind: event.target.value as
                                                          'DATE' | 'TEXT',
                                                      }),
                                                    ),
                                                  )
                                                }
                                              >
                                                <option value="DATE">Tanggal</option>
                                                <option value="TEXT">Teks manual</option>
                                              </select>
                                            </label>
                                            <label className="minutes-table-field">
                                              Target penyelesaian
                                              {decision.target_kind === 'DATE' ? (
                                                <input
                                                  aria-label="Target penyelesaian berupa tanggal"
                                                  className="minutes-input"
                                                  disabled={fieldsDisabled}
                                                  type="date"
                                                  value={decision.target_date}
                                                  onChange={(event) =>
                                                    onUpdateDiscussion(discussionIndex, (current) =>
                                                      updateDecision(
                                                        current,
                                                        decisionIndex,
                                                        (item) => ({
                                                          ...item,
                                                          target_date: event.target.value,
                                                        }),
                                                      ),
                                                    )
                                                  }
                                                />
                                              ) : (
                                                <input
                                                  aria-label="Target penyelesaian berupa teks manual"
                                                  className="minutes-input"
                                                  disabled={fieldsDisabled}
                                                  maxLength={500}
                                                  placeholder="Contoh: minggu kedua Desember"
                                                  type="text"
                                                  value={decision.target_text}
                                                  onChange={(event) =>
                                                    onUpdateDiscussion(discussionIndex, (current) =>
                                                      updateDecision(
                                                        current,
                                                        decisionIndex,
                                                        (item) => ({
                                                          ...item,
                                                          target_text: event.target.value,
                                                        }),
                                                      ),
                                                    )
                                                  }
                                                />
                                              )}
                                            </label>
                                          </div>
                                        </div>
                                      )}
                                    </section>
                                  );
                                })}
                              </div>
                            )}
                            <button
                              className="button button--secondary minutes-row-action"
                              disabled={actionsDisabled}
                              onClick={() =>
                                onUpdateDiscussion(discussionIndex, (current) => ({
                                  ...current,
                                  decisions: [
                                    ...current.decisions,
                                    {
                                      decision_text: '',
                                      pic_suggestion: '',
                                      supporting_pic_suggestion: '',
                                      output_expected: '',
                                      target_kind: 'DATE',
                                      target_date: '',
                                      target_text: '',
                                      is_action_item: false,
                                    },
                                  ],
                                }))
                              }
                              type="button"
                            >
                              Tambah putusan
                            </button>
                          </section>
                        </section>
                      );
                    })}
                  </div>
                  <button
                    className="button button--secondary minutes-row-action"
                    disabled={actionsDisabled}
                    onClick={() => onAddDiscussion(agenda.id)}
                    type="button"
                  >
                    Tambah pokok bahasan agenda {agenda.agenda_number}
                  </button>
                </>
              )}
            </section>
          );
        })
      )}
    </section>
  );
}

function MinutesEditor({
  authenticatedUser,
  onPendingDraftChange,
  targetMeetingId,
}: {
  authenticatedUser?: AuthenticatedUser;
  onPendingDraftChange?: (hasPendingDraft: boolean) => void;
  targetMeetingId?: string;
}) {
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<AuthenticatedUser | null>(null);
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [selectedMeetingId, setSelectedMeetingId] = useState('');
  const [revisions, setRevisions] = useState<MinutesRevision[]>([]);
  const [structuredDiscussions, setStructuredDiscussions] = useState<DiscussionDraft[]>([]);
  const [baselineStructuredSnapshot, setBaselineStructuredSnapshot] = useState('[]');
  const [structuredFormatChanged, setStructuredFormatChanged] = useState(false);
  const [baseRevisionId, setBaseRevisionId] = useState<string | null>(null);
  const [loadingRevisions, setLoadingRevisions] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>('clean');
  const [conflictDraft, setConflictDraft] = useState<string | null>(null);
  const [refreshingMeetingStatus, setRefreshingMeetingStatus] = useState(false);
  const [meetingStatusRefreshFailed, setMeetingStatusRefreshFailed] = useState(false);
  const [printingMinutes, setPrintingMinutes] = useState(false);
  const requestSequence = useRef(0);
  const selectedMeeting = meetings.find((meeting) => meeting.id === selectedMeetingId) ?? null;
  const latestRevision = activeRevision(revisions);
  const latestLegacyRevision =
    sortRevisions(revisions)
      .filter((revision) => revision.format_version === 1)
      .at(-1) ?? null;
  const hasRestrictedRole = currentUser?.roles.some((role) => RESTRICTED_ROLES.has(role)) ?? true;
  const canEdit = Boolean(
    currentUser &&
    selectedMeeting &&
    !hasRestrictedRole &&
    currentUser.roles.some((role) => MINUTES_EDITOR_ROLES.has(role)) &&
    selectedMeeting.status === 'LIVE' &&
    saveState !== 'statusChanged',
  );
  const structuredSnapshotValue = JSON.stringify(structuredDiscussions);
  const isDirty = structuredFormatChanged || structuredSnapshotValue !== baselineStructuredSnapshot;
  const structuredDraftIsValid = isValidStructuredDraft(structuredDiscussions);
  const structuredTableRows = selectedMeeting
    ? tableRowsForMeeting(selectedMeeting, structuredDiscussions)
    : [];
  const canPrintMinutes = Boolean(
    latestRevision?.format_version === 2 && !isDirty && conflictDraft === null,
  );
  const hasPendingDraft = isDirty || conflictDraft !== null;

  useEffect(() => {
    onPendingDraftChange?.(hasPendingDraft);
    return () => onPendingDraftChange?.(false);
  }, [hasPendingDraft, onPendingDraftChange]);

  useEffect(() => {
    const resetPrintMode = () => {
      document.body.classList.remove('sitara-print-mode');
      setPrintingMinutes(false);
    };
    window.addEventListener('afterprint', resetPrintMode);
    return () => window.removeEventListener('afterprint', resetPrintMode);
  }, []);

  useEffect(() => {
    let mounted = true;

    async function loadEditor(): Promise<void> {
      try {
        const user = authenticatedUser ?? (await getCurrentUser());
        if (!canAccessMinutes(user)) {
          throw new ApiError('Akun ini tidak memiliki akses ke editor notulensi.', 403);
        }
        const accessibleMeetings = await getMeetings();
        if (!mounted) return;
        setCurrentUser(user);
        setMeetings(accessibleMeetings);
        if (targetMeetingId) {
          const targetMeeting = accessibleMeetings.find(
            (meeting) => meeting.id === targetMeetingId,
          );
          if (!targetMeeting) {
            setErrorMessage('Rapat tidak termasuk dalam cakupan akses Anda.');
            setLoadState('failed');
            return;
          }
        } else if (accessibleMeetings.length === 0) {
          setLoadState('empty');
          return;
        } else {
          setSelectedMeetingId('');
          setLoadState('ready');
          return;
        }

        const initialMeeting = accessibleMeetings.find((meeting) => meeting.id === targetMeetingId);
        if (!initialMeeting) {
          setErrorMessage('Rapat tidak termasuk dalam cakupan akses Anda.');
          setLoadState('failed');
          return;
        }
        setSelectedMeetingId(initialMeeting.id);
        const meetingRevisions = sortRevisions(await getMinutesRevisions(initialMeeting.id));
        if (!mounted) return;
        setRevisions(meetingRevisions);
        const latest = activeRevision(meetingRevisions);
        const loadedStructured = structuredDraftFrom(latest);
        setStructuredDiscussions(loadedStructured);
        setBaselineStructuredSnapshot(JSON.stringify(loadedStructured));
        setStructuredFormatChanged(false);
        setBaseRevisionId(latest?.id ?? null);
        setLoadState('ready');
      } catch (error) {
        if (!mounted) return;
        setErrorMessage(accessErrorMessage(error));
        setLoadState('failed');
      }
    }

    void loadEditor();
    return () => {
      mounted = false;
      requestSequence.current += 1;
    };
  }, [authenticatedUser, targetMeetingId]);

  async function loadMeetingRevisions(meetingId: string, preserveDraft = false): Promise<void> {
    const requestId = ++requestSequence.current;
    const localDraft = preserveDraft ? structuredDraftText(structuredDiscussions) : null;
    setLoadingRevisions(true);
    setErrorMessage(null);
    try {
      const meetingRevisions = sortRevisions(await getMinutesRevisions(meetingId));
      if (requestId !== requestSequence.current) return;
      const latest = activeRevision(meetingRevisions);
      const loadedStructured = structuredDraftFrom(latest);
      setRevisions(meetingRevisions);
      setBaseRevisionId(latest?.id ?? null);
      setStructuredDiscussions(loadedStructured);
      setBaselineStructuredSnapshot(JSON.stringify(loadedStructured));
      setStructuredFormatChanged(false);
      setConflictDraft(localDraft);
      setSaveState(preserveDraft ? 'reloaded' : 'clean');
    } catch (error) {
      if (requestId !== requestSequence.current) return;
      setErrorMessage(accessErrorMessage(error));
      if (!preserveDraft) setSaveState('error');
    } finally {
      if (requestId === requestSequence.current) setLoadingRevisions(false);
    }
  }

  async function refreshMeetingStatus(meetingId: string): Promise<void> {
    setRefreshingMeetingStatus(true);
    setMeetingStatusRefreshFailed(false);
    try {
      const updatedMeeting = await getMeeting(meetingId);
      setMeetings((previousMeetings) =>
        previousMeetings.map((meeting) =>
          meeting.id === updatedMeeting.id ? { ...meeting, ...updatedMeeting } : meeting,
        ),
      );
    } catch {
      setMeetingStatusRefreshFailed(true);
      setErrorMessage(
        'Rapat tidak lagi berlangsung. Perubahan yang belum disimpan dipertahankan. Coba muat ulang status rapat.',
      );
    } finally {
      setRefreshingMeetingStatus(false);
    }
  }

  async function handleSave(): Promise<void> {
    if (
      !canEdit ||
      !selectedMeeting ||
      !isDirty ||
      !structuredDraftIsValid ||
      loadingRevisions ||
      saveState === 'saving'
    ) {
      return;
    }

    setSaveState('saving');
    setErrorMessage(null);
    try {
      const savedRevision = await createMinutesRevision(
        selectedMeeting.id,
        structuredSnapshot(structuredDiscussions),
        baseRevisionId,
      );
      const updatedRevisions = sortRevisions([...revisions, savedRevision]);
      const savedStructured = structuredDraftFrom(savedRevision);
      setRevisions(updatedRevisions);
      setBaseRevisionId(savedRevision.id);
      setStructuredDiscussions(savedStructured);
      setBaselineStructuredSnapshot(JSON.stringify(savedStructured));
      setStructuredFormatChanged(false);
      setConflictDraft(null);
      setSaveState('saved');
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        error.message === STALE_REVISION_DETAIL
      ) {
        setConflictDraft(structuredDraftText(structuredDiscussions));
        setErrorMessage(
          'Notulensi sudah diperbarui oleh pengguna lain. Perubahan Anda disimpan sementara; muat notulensi terbaru untuk melanjutkan.',
        );
        setSaveState('conflict');
      } else if (
        error instanceof ApiError &&
        error.status === 409 &&
        error.message === MEETING_NOT_LIVE_DETAIL
      ) {
        setConflictDraft(structuredDraftText(structuredDiscussions));
        setSaveState('statusChanged');
        setErrorMessage(
          'Rapat tidak lagi berlangsung. Perubahan Anda disimpan sementara dan belum tersimpan ke notulensi.',
        );
        await refreshMeetingStatus(selectedMeeting.id);
      } else {
        setErrorMessage(accessErrorMessage(error));
        setSaveState('error');
      }
    }
  }

  async function handleReloadLatest(): Promise<void> {
    if (!selectedMeeting || loadingRevisions || saveState === 'saving') return;
    await loadMeetingRevisions(selectedMeeting.id, true);
  }

  async function handleReloadMeetingStatus(): Promise<void> {
    if (!selectedMeeting || refreshingMeetingStatus) return;
    await refreshMeetingStatus(selectedMeeting.id);
  }

  function updateDiscussion(
    discussionIndex: number,
    update: (discussion: DiscussionDraft) => DiscussionDraft,
  ): void {
    const next = structuredDiscussions.map((discussion, index) =>
      index === discussionIndex ? update(discussion) : discussion,
    );
    setStructuredDiscussions(next);
    if (saveState === 'conflict') setConflictDraft(structuredDraftText(next));
    if (saveState === 'saved' || saveState === 'error' || saveState === 'reloaded') {
      setSaveState('clean');
      setErrorMessage(null);
    }
  }

  function addDiscussion(agendaId: string): void {
    const next = [
      ...structuredDiscussions,
      { agenda_id: agendaId, subject: '', content: '', decisions: [] },
    ];
    setStructuredDiscussions(next);
    if (saveState === 'conflict') setConflictDraft(structuredDraftText(next));
    if (saveState === 'saved' || saveState === 'error' || saveState === 'reloaded') {
      setSaveState('clean');
      setErrorMessage(null);
    }
  }

  function removeDiscussion(discussionIndex: number): void {
    const next = structuredDiscussions.filter((_, index) => index !== discussionIndex);
    setStructuredDiscussions(next);
    if (saveState === 'conflict') setConflictDraft(structuredDraftText(next));
    if (saveState === 'saved' || saveState === 'error' || saveState === 'reloaded') {
      setSaveState('clean');
      setErrorMessage(null);
    }
  }

  function printMinutes(): void {
    document.body.classList.add('sitara-print-mode');
    setPrintingMinutes(true);
    window.setTimeout(() => window.print(), 0);
  }

  if (loadState === 'ready' && !selectedMeeting) {
    return (
      <MeetingDocumentSelection
        meetings={meetings}
        documentName="Notulensi rapat"
        routePrefix="#notulensi"
      />
    );
  }

  return (
    <section className="minutes-page" aria-labelledby="minutes-page-title">
      <div className="page-heading">
        <div>
          <h1 id="minutes-page-title">Notulensi rapat</h1>
        </div>
      </div>

      {loadState === 'loading' && <p role="status">Memuat rapat dan notulensi…</p>}
      {loadState === 'failed' && (
        <p className="minutes-alert" role="alert">
          {errorMessage}
        </p>
      )}
      {loadState === 'empty' && (
        <div className="minutes-empty" role="status">
          Tidak ada rapat yang dapat diakses.
        </div>
      )}

      {loadState === 'ready' && selectedMeeting && (
        <>
          <a className="repository-back-link" href="#notulensi">
            Kembali ke daftar rapat
          </a>
          <div className="minutes-layout">
            <section
              className="surface-panel minutes-context"
              aria-labelledby="meeting-context-title"
            >
              <div className="section-heading">
                <div>
                  <h2 id="meeting-context-title">Rapat terpilih</h2>
                </div>
                <span
                  className={`meeting-status meeting-status--${selectedMeeting.status.toLowerCase()}`}
                >
                  {selectedMeeting.status}
                </span>
              </div>

              <div className="minutes-meeting-meta">
                <h3>{selectedMeeting.title}</h3>
                <p>
                  <strong>{selectedMeeting.meeting_number}</strong>
                  <span> · </span>
                  {formatDate(selectedMeeting.meeting_date)}
                </p>
              </div>

              <div className="minutes-agendas">
                <h3>Agenda</h3>
                {selectedMeeting.agendas.length > 0 ? (
                  <ol>
                    {selectedMeeting.agendas.map((agenda) => (
                      <li key={agenda.id}>
                        <span>{agenda.title}</span>
                        {agenda.agenda_description && <small>{agenda.agenda_description}</small>}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="minutes-muted">Belum ada agenda pada data rapat ini.</p>
                )}
              </div>
            </section>

            <section
              className="surface-panel minutes-editor-panel"
              aria-labelledby="minutes-editor-title"
            >
              <div className="section-heading">
                <div>
                  <h2 id="minutes-editor-title">Isi resmi</h2>
                </div>
                {canEdit ? (
                  <span className="minutes-role-badge">Dapat menyunting</span>
                ) : (
                  <span className="minutes-role-badge minutes-role-badge--readonly">Baca saja</span>
                )}
              </div>

              {errorMessage && (
                <p className="minutes-alert" role="alert">
                  {errorMessage}
                </p>
              )}
              {saveState === 'reloaded' && (
                <p className="minutes-notice" role="status">
                  Notulensi terbaru dimuat. Perubahan sebelumnya tetap tersedia sementara.
                </p>
              )}
              {conflictDraft !== null && (
                <details className="minutes-preserved-draft">
                  <summary>Perubahan lokal yang belum tersimpan</summary>
                  <pre>{conflictDraft}</pre>
                </details>
              )}

              {selectedMeeting.status !== 'ARCHIVED' && (
                <div className="minutes-structured-editor">
                  {latestLegacyRevision?.content && (
                    <details className="minutes-legacy-source">
                      <summary>Buka catatan notulensi terdahulu</summary>
                      <pre>{latestLegacyRevision.content}</pre>
                    </details>
                  )}
                  <MinutesGuidedEditor
                    meeting={selectedMeeting}
                    discussions={structuredDiscussions}
                    canEdit={canEdit}
                    loadingRevisions={loadingRevisions}
                    saveState={saveState}
                    onUpdateDiscussion={updateDiscussion}
                    onAddDiscussion={addDiscussion}
                    onRemoveDiscussion={removeDiscussion}
                  />
                </div>
              )}

              <div className="minutes-editor-footer">
                <p className={`minutes-save-state minutes-save-state--${saveState}`} role="status">
                  {loadingRevisions
                    ? 'Memuat notulensi…'
                    : saveState === 'saving'
                      ? 'Menyimpan notulensi…'
                      : saveState === 'saved'
                        ? 'Notulensi tersimpan.'
                        : saveState === 'conflict'
                          ? 'Penyimpanan tertahan karena ada perubahan yang lebih baru.'
                          : saveState === 'statusChanged'
                            ? 'Perubahan dipertahankan; rapat tidak lagi berlangsung.'
                            : saveState === 'error'
                              ? 'Penyimpanan gagal.'
                              : saveState === 'reloaded'
                                ? 'Notulensi terbaru sudah dimuat.'
                                : isDirty
                                  ? 'Perubahan belum disimpan.'
                                  : latestRevision
                                    ? 'Notulensi sudah tersimpan.'
                                    : 'Belum ada notulensi tersimpan.'}
                </p>
                <div className="minutes-actions">
                  {saveState === 'conflict' && (
                    <button
                      className="button button--secondary"
                      type="button"
                      disabled={loadingRevisions}
                      onClick={() => void handleReloadLatest()}
                    >
                      {loadingRevisions ? 'Memuat…' : 'Muat notulensi terbaru'}
                    </button>
                  )}
                  {meetingStatusRefreshFailed && (
                    <button
                      className="button button--secondary"
                      type="button"
                      disabled={refreshingMeetingStatus}
                      onClick={() => void handleReloadMeetingStatus()}
                    >
                      {refreshingMeetingStatus ? 'Memuat status…' : 'Muat ulang status rapat'}
                    </button>
                  )}
                  {canEdit && selectedMeeting.status === 'LIVE' && (
                    <button
                      className="button button--primary"
                      type="button"
                      disabled={
                        !isDirty ||
                        !structuredDraftIsValid ||
                        loadingRevisions ||
                        saveState === 'saving' ||
                        saveState === 'conflict'
                      }
                      onClick={() => void handleSave()}
                    >
                      {saveState === 'saving' ? 'Menyimpan…' : 'Simpan notulensi'}
                    </button>
                  )}
                </div>
              </div>

              <section
                className={`minutes-final-output${printingMinutes ? ' sitara-print-target' : ''}`}
                aria-labelledby="minutes-preview-title"
              >
                <div className="minutes-final-toolbar">
                  <div>
                    <h3 id="minutes-preview-title">Pratinjau tabel</h3>
                  </div>
                  <button
                    className="button button--primary"
                    disabled={!canPrintMinutes}
                    onClick={printMinutes}
                    type="button"
                  >
                    Cetak hasil notulensi
                  </button>
                </div>
                <header className="minutes-print-heading">
                  <p className="minutes-print-institution">INSTITUT TEKNOLOGI PLN</p>
                  <h2>NOTULA RAPAT</h2>
                  <p className="minutes-print-meeting-title">{selectedMeeting.title}</p>
                  <dl>
                    <div>
                      <dt>Nomor</dt>
                      <dd>{selectedMeeting.meeting_number}</dd>
                    </div>
                    <div>
                      <dt>Hari/Tanggal</dt>
                      <dd>{formatDate(selectedMeeting.meeting_date)}</dd>
                    </div>
                    <div>
                      <dt>Waktu</dt>
                      <dd>
                        {selectedMeeting.start_time ?? '—'}
                        {selectedMeeting.end_time ? `–${selectedMeeting.end_time}` : ''}
                      </dd>
                    </div>
                    <div>
                      <dt>Tempat</dt>
                      <dd>{selectedMeeting.location ?? '—'}</dd>
                    </div>
                  </dl>
                </header>
                <div className="minutes-table-scroll minutes-preview-scroll">
                  <table className="minutes-preview-table" aria-label="Pratinjau hasil rapat">
                    <thead>
                      <tr>
                        <th scope="col">No.</th>
                        <th scope="col">Agenda/Pokok Bahasan</th>
                        <th scope="col">Putusan/Arahan &amp; Tindak Lanjut</th>
                        <th scope="col">PIC</th>
                        <th scope="col">PIC pendukung</th>
                        <th scope="col">Output</th>
                        <th scope="col">Target</th>
                      </tr>
                    </thead>
                    <tbody>
                      {structuredTableRows.map((row, rowIndex) => {
                        const decisions = row.discussion?.decisions ?? [];
                        return (
                          <tr key={row.agenda.id + '-' + (row.discussionIndex ?? 'empty')}>
                            <td className="minutes-print-number">{rowIndex + 1}</td>
                            <td>
                              <strong>{row.agenda.title}</strong>
                              {row.discussion ? (
                                <>
                                  {row.discussion.subject && <h3>{row.discussion.subject}</h3>}
                                  <p>{row.discussion.content}</p>
                                </>
                              ) : (
                                <p>Belum ada pokok pembahasan.</p>
                              )}
                            </td>
                            <td className="minutes-preview-cell-list">
                              {decisions.length ? (
                                decisions.map((decision, decisionIndex) => (
                                  <div className="minutes-preview-decision" key={decisionIndex}>
                                    <p>
                                      <strong>{decisionIndex + 1}.</strong> {decision.decision_text}
                                    </p>
                                    <small>
                                      {decision.is_action_item
                                        ? 'Memerlukan tindak lanjut'
                                        : 'Tidak memerlukan tindak lanjut'}
                                    </small>
                                  </div>
                                ))
                              ) : (
                                <p>Belum ada putusan/arahan.</p>
                              )}
                            </td>
                            <td className="minutes-preview-cell-list">
                              {decisions.length ? (
                                decisions.map((decision, decisionIndex) => (
                                  <p key={decisionIndex}>
                                    {decision.pic_suggestion || 'Belum ditentukan'}
                                  </p>
                                ))
                              ) : (
                                <p>Belum ditentukan</p>
                              )}
                            </td>
                            <td className="minutes-preview-cell-list">
                              {decisions.length ? (
                                decisions.map((decision, decisionIndex) => (
                                  <p key={decisionIndex}>
                                    {decision.supporting_pic_suggestion || 'Belum ditentukan'}
                                  </p>
                                ))
                              ) : (
                                <p>Belum ditentukan</p>
                              )}
                            </td>
                            <td className="minutes-preview-cell-list">
                              {decisions.length ? (
                                decisions.map((decision, decisionIndex) => (
                                  <p key={decisionIndex}>
                                    {decision.output_expected || 'Belum ditentukan'}
                                  </p>
                                ))
                              ) : (
                                <p>Belum ditentukan</p>
                              )}
                            </td>
                            <td className="minutes-preview-cell-list">
                              {decisions.length ? (
                                decisions.map((decision, decisionIndex) => (
                                  <p key={decisionIndex}>
                                    {decision.target_kind === 'DATE'
                                      ? decision.target_date
                                        ? formatDate(decision.target_date)
                                        : 'Belum ditentukan'
                                      : decision.target_text || 'Belum ditentukan'}
                                  </p>
                                ))
                              ) : (
                                <p>Belum ditentukan</p>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="minutes-print-note">
                  PIC pada notulen merupakan usulan. Penetapan dan pemantauan tindak lanjut
                  dilakukan melalui Action Item. Decision Brief disusun sebagai ringkasan editorial
                  dari putusan sumber.
                </p>
              </section>

              {saveState === 'statusChanged' && (
                <p className="minutes-readonly-note">
                  Status rapat berubah. Perubahan yang belum tersimpan dipertahankan dan
                  penyuntingan dinonaktifkan.
                </p>
              )}
              {!canEdit && saveState !== 'statusChanged' && (
                <p className="minutes-readonly-note">
                  {selectedMeeting.status !== 'LIVE'
                    ? 'Rapat tidak sedang berlangsung; notulensi hanya dapat dibaca.'
                    : 'Penyuntingan saat rapat berlangsung tersedia untuk Warek, Sekretariat, dan Manager Legal.'}
                </p>
              )}
            </section>
          </div>
        </>
      )}
    </section>
  );
}

export default MinutesEditor;
