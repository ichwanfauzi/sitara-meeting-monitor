import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import {
  changeActionItemStatus,
  createActionItem,
  createActionItemAssignment,
  createActionItemProgressUpdate,
  deleteActionItem,
  endActionItemAssignment,
  getActionItem,
  getActionItems,
  getMeetings,
  getMeetingParticipantOptions,
  getMinutesRevisions,
  reviewActionItemCompletion,
  searchAssignablePics,
  updateActionItem,
  uploadActionItemEvidenceFile,
  type ActionItemCompletionVerificationInput,
  type ActionItemAssignment,
  type ActionItemDetail,
  type ActionItemStatus,
  type ActionItemSummary,
  type AssignablePicDirectory,
  type AuthenticatedUser,
  type MeetingParticipantOption,
  type MeetingSummary,
  type MinutesRevision,
} from './api';
import MeetingPicker from './MeetingPicker';
import { isOperationalActionItem } from './actionItemVisibility';

type SourceDecision = {
  meeting: MeetingSummary;
  revision: MinutesRevision;
  decisionId: string;
  decisionText: string;
  agendaTitle: string;
  discussionSubject: string | null;
};

const officialStatuses: ActionItemStatus[] = [
  'BELUM_DIMULAI',
  'BERPROSES',
  'TERKENDALA',
  'MENUNGGU_ACC',
];

const actionItemPriorities = ['Sangat Segera', 'Segera', 'Normal', 'Rendah'];

const allowedEvidenceExtensions = new Set([
  '.pdf',
  '.jpg',
  '.jpeg',
  '.png',
  '.heic',
  '.heif',
  '.docx',
  '.xlsx',
  '.pptx',
  '.csv',
  '.txt',
]);

const statusLabels: Record<ActionItemStatus, string> = {
  BELUM_DIMULAI: 'Belum dimulai',
  BERPROSES: 'Berproses',
  TERKENDALA: 'Terkendala',
  MENUNGGU_ACC: 'Menunggu ACC',
  SELESAI: 'Selesai',
};

function canCreateActionItems(user: AuthenticatedUser): boolean {
  return (
    !user.roles.includes('SUPER_ADMIN') &&
    !user.roles.includes('PIC') &&
    user.roles.some((role) => ['SEKRETARIAT', 'MANAGER_LEGAL'].includes(role))
  );
}

function canManageActionItemAssignments(user: AuthenticatedUser): boolean {
  return canCreateActionItems(user);
}

function canOpenActionItems(user: AuthenticatedUser): boolean {
  return (
    !user.roles.includes('SUPER_ADMIN') &&
    user.roles.some((role) =>
      ['SEKRETARIAT', 'MANAGER_LEGAL', 'PIC', 'REKTOR', 'WAREK'].includes(role),
    )
  );
}

function formatDate(value: string | null): string {
  if (!value) return 'Belum ditentukan';
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(date);
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('id-ID', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function evidenceStatusLabel(status: string | null): string {
  if (status === 'CLEAN') return 'Lolos pemeriksaan keamanan';
  if (status === 'REJECTED') return 'Ditolak pemeriksaan keamanan';
  return 'Menunggu pemeriksaan keamanan';
}

function completionOutcomeLabel(detail: ActionItemDetail, progressUpdateId: string): string {
  const verification = detail.completion_verifications.find(
    (item) => item.progress_update_id === progressUpdateId,
  );
  if (!verification) return 'menunggu verifikasi';
  return verification.outcome === 'VERIFIED' ? 'disetujui' : 'perlu revisi';
}

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message;
  return 'Terjadi kesalahan saat memuat Action Item.';
}

function sourceDecisions(meeting: MeetingSummary, revisions: MinutesRevision[]): SourceDecision[] {
  const active = revisions.reduce<MinutesRevision | null>(
    (current, revision) =>
      current === null || revision.revision_number > current.revision_number ? revision : current,
    null,
  );
  if (!active || active.format_version !== 2) return [];
  return active.discussions.flatMap((discussion) => {
    const agenda = meeting.agendas.find((item) => item.id === discussion.agenda_id);
    return discussion.decisions
      .filter((decision) => decision.is_action_item)
      .map((decision) => ({
        meeting,
        revision: active,
        decisionId: decision.id,
        decisionText: decision.decision_text,
        agendaTitle: agenda?.title ?? 'Agenda sumber',
        discussionSubject: discussion.subject,
      }));
  });
}

function ActionItemPicPicker({
  enabled,
  options,
  onChange,
  onOtherChange,
  otherValue,
  label,
  required = true,
  value,
}: {
  enabled: boolean;
  options: MeetingParticipantOption[];
  onChange: (value: string) => void;
  onOtherChange: (value: string) => void;
  otherValue: string;
  label: string;
  required?: boolean;
  value: string;
}) {
  return (
    <div className="action-item-pic-picker">
      <label>
        {label}
        <select
          aria-label={label}
          value={value}
          onChange={(event) => {
            const selection = event.currentTarget.value;
            onChange(selection);
            if (selection !== '__OTHER__') onOtherChange('');
          }}
          disabled={!enabled}
          required={required}
        >
          <option value="">Pilih PIC</option>
          {options.map((person) => (
            <option key={person.id} value={person.id}>
              {picTitle(person)}
            </option>
          ))}
          <option value="__OTHER__">Lainnya</option>
        </select>
      </label>
      {value === '__OTHER__' && (
        <label>
          Nama/jabatan PIC lainnya
          <input
            maxLength={200}
            required
            value={otherValue}
            onChange={(event) => onOtherChange(event.currentTarget.value)}
          />
        </label>
      )}
    </div>
  );
}

function picTitle(person: MeetingParticipantOption): string {
  if (person.roles.includes('SEKRETARIAT')) return 'Direktur Sekretariat';
  if (person.job_title?.trim()) return person.job_title.trim();
  if (person.roles.includes('REKTOR')) return 'Rektor';
  if (person.roles.includes('WAREK')) return 'Wakil Rektor';
  if (person.roles.includes('MANAGER_LEGAL')) return 'Manager Legal';
  return person.full_name;
}

function picPickerOptions(directory: AssignablePicDirectory | null): MeetingParticipantOption[] {
  return (
    directory?.pics.map((person) => ({
      id: person.id,
      full_name: person.full_name,
      job_title: person.job_title,
      roles: ['PIC'],
    })) ?? []
  );
}

function ActionItemManagement({
  authenticatedUser,
  targetActionItemId,
}: {
  authenticatedUser: AuthenticatedUser;
  targetActionItemId?: string;
}) {
  const [items, setItems] = useState<ActionItemSummary[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [showAllItems, setShowAllItems] = useState(false);
  const [listQuery, setListQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [detail, setDetail] = useState<ActionItemDetail | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createNotice, setCreateNotice] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [creationMeetings, setCreationMeetings] = useState<MeetingSummary[]>([]);
  const [creationMeetingId, setCreationMeetingId] = useState('');
  const [creationRevisions, setCreationRevisions] = useState<MinutesRevision[]>([]);
  const [creationRevisionsLoading, setCreationRevisionsLoading] = useState(false);
  const [creationDecisionId, setCreationDecisionId] = useState('');
  const [creationPicDirectory, setCreationPicDirectory] = useState<AssignablePicDirectory | null>(
    null,
  );
  const [creationPicDirectoryLoading, setCreationPicDirectoryLoading] = useState(false);
  const [mainPicUserId, setMainPicUserId] = useState('');
  const [mainPicDisplayName, setMainPicDisplayName] = useState('');
  const [mainPicOriginUnitId, setMainPicOriginUnitId] = useState('');
  const [supportingPicUserId, setSupportingPicUserId] = useState('');
  const [supportingPicDisplayName, setSupportingPicDisplayName] = useState('');
  const [supportingPicOriginUnitId, setSupportingPicOriginUnitId] = useState('');
  const [assignmentPicUserId, setAssignmentPicUserId] = useState('');
  const [assignmentPicDisplayName, setAssignmentPicDisplayName] = useState('');
  const [assignmentPicOriginUnitId, setAssignmentPicOriginUnitId] = useState('');
  const [assignmentPicDirectory, setAssignmentPicDirectory] =
    useState<AssignablePicDirectory | null>(null);
  const [assignmentPicDirectoryLoading, setAssignmentPicDirectoryLoading] = useState(false);
  const [statusValue, setStatusValue] = useState<ActionItemStatus>('BELUM_DIMULAI');
  const [statusNote, setStatusNote] = useState('');
  const [statusSaving, setStatusSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [progressSaving, setProgressSaving] = useState(false);
  const [selectedEvidenceFiles, setSelectedEvidenceFiles] = useState<File[]>([]);
  const [completionSaving, setCompletionSaving] = useState(false);
  const [verificationSaving, setVerificationSaving] = useState(false);
  const [assignmentSaving, setAssignmentSaving] = useState(false);
  const [participantOptions, setParticipantOptions] = useState<MeetingParticipantOption[]>([]);
  const [participantOptionsError, setParticipantOptionsError] = useState<string | null>(null);
  const detailRequest = useRef(0);

  const canCreate = canCreateActionItems(authenticatedUser);
  const canAssign = canManageActionItemAssignments(authenticatedUser);
  const canReviewAndManage = canCreate;
  const restricted = authenticatedUser.roles.includes('SUPER_ADMIN');
  const rolesAllowProgress =
    !restricted &&
    !canReviewAndManage &&
    (authenticatedUser.roles.includes('PIC') || authenticatedUser.roles.includes('WAREK'));
  const userAssignment =
    detail?.active_assignments.find(
      (assignment) => assignment.assignee_user_id === authenticatedUser.id,
    ) ?? null;
  const canSubmitProgress = Boolean(
    detail &&
    rolesAllowProgress &&
    ((authenticatedUser.roles.includes('PIC') && userAssignment) ||
      authenticatedUser.roles.includes('WAREK')),
  );
  const hasCleanFileEvidence = Boolean(
    detail?.progress_updates.some((update) =>
      update.evidence.some(
        (evidence) => evidence.evidence_kind === 'FILE' && evidence.scan_status === 'CLEAN',
      ),
    ),
  );
  const unreviewedCompletionRequests =
    detail?.progress_updates.filter(
      (update) =>
        update.completion_requested &&
        !detail.completion_verifications.some(
          (verification) => verification.progress_update_id === update.id,
        ),
    ) ?? [];
  const hasPendingCompletionRequest = unreviewedCompletionRequests.length > 0;
  const activeCreationMeeting =
    creationMeetings.find((meeting) => meeting.id === creationMeetingId) ?? null;
  const creationSources = activeCreationMeeting
    ? sourceDecisions(activeCreationMeeting, creationRevisions)
    : [];
  const selectedSource =
    creationSources.find((source) => source.decisionId === creationDecisionId) ?? null;
  const mainPicActiveUnits =
    creationPicDirectory?.pics.find((pic) => pic.id === mainPicUserId)?.active_units ?? [];
  const supportingPicActiveUnits =
    creationPicDirectory?.pics.find((pic) => pic.id === supportingPicUserId)?.active_units ?? [];
  const assignmentPicActiveUnits =
    assignmentPicDirectory?.pics.find((pic) => pic.id === assignmentPicUserId)?.active_units ?? [];
  const targetIndex = items.findIndex((item) => item.id === targetActionItemId);
  const normalizedListQuery = listQuery.trim().toLocaleLowerCase('id-ID');
  const filteredItems = items.filter((item) => {
    const statusMatches = statusFilter === 'ALL' || item.official_status === statusFilter;
    const searchableText = [
      item.title,
      item.description,
      item.output_expected,
      ...item.active_assignments.map((assignment) => assignment.assignee_name),
    ]
      .filter((value): value is string => Boolean(value))
      .join(' ')
      .toLocaleLowerCase('id-ID');
    return statusMatches && (!normalizedListQuery || searchableText.includes(normalizedListQuery));
  });
  const listedItems = showAllItems || targetIndex >= 5 ? filteredItems : filteredItems.slice(0, 5);
  const refreshList = useCallback(async (): Promise<void> => {
    setListLoading(true);
    setListError(null);
    try {
      const nextItems = (await getActionItems()).filter(isOperationalActionItem);
      setItems(nextItems);
      setSelectedId((current) =>
        targetActionItemId && nextItems.some((item) => item.id === targetActionItemId)
          ? targetActionItemId
          : current && nextItems.some((item) => item.id === current)
            ? current
            : '',
      );
    } catch (error) {
      setItems([]);
      setSelectedId('');
      setListError(`Daftar Action Item tidak dapat dimuat: ${errorText(error)}`);
    } finally {
      setListLoading(false);
    }
  }, [targetActionItemId]);

  async function refreshDetail(actionItemId: string): Promise<void> {
    const requestId = ++detailRequest.current;
    setDetailLoading(true);
    setDetailError(null);
    try {
      const nextDetail = await getActionItem(actionItemId);
      if (requestId === detailRequest.current) {
        setDetail(nextDetail);
        setStatusValue(
          nextDetail.official_status === 'SELESAI' ? 'BELUM_DIMULAI' : nextDetail.official_status,
        );
      }
    } catch (error) {
      if (requestId === detailRequest.current) {
        setDetail(null);
        setDetailError(`Detail Action Item tidak dapat dimuat: ${errorText(error)}`);
      }
    } finally {
      if (requestId === detailRequest.current) setDetailLoading(false);
    }
  }

  useEffect(() => {
    if (!canOpenActionItems(authenticatedUser)) return;
    void refreshList();
  }, [authenticatedUser, refreshList]);

  useEffect(() => {
    if (!canCreate && !canAssign) return;
    let active = true;
    setParticipantOptionsError(null);
    void getMeetingParticipantOptions()
      .then((options) => {
        if (active) {
          setParticipantOptions(options);
          setParticipantOptionsError(null);
        }
      })
      .catch((error: unknown) => {
        if (active)
          setParticipantOptionsError(`Daftar jabatan PIC gagal dimuat: ${errorText(error)}`);
      });
    return () => {
      active = false;
    };
  }, [canAssign, canCreate]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setAssignmentPicUserId('');
      setAssignmentPicDisplayName('');
      return;
    }
    setEditOpen(false);
    setEditError(null);
    setAssignmentPicUserId('');
    setAssignmentPicDisplayName('');
    setAssignmentPicOriginUnitId('');
    void refreshDetail(selectedId);
    return () => {
      detailRequest.current += 1;
    };
  }, [selectedId]);

  useEffect(() => {
    if (targetActionItemId && targetIndex >= 0) {
      setSelectedId(targetActionItemId);
      if (targetIndex >= 5) setShowAllItems(true);
    }
  }, [items, targetActionItemId, targetIndex]);

  useEffect(() => {
    if (!selectedId || createOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelectedId('');
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [createOpen, selectedId]);

  useEffect(() => {
    if (!createOpen || !creationMeetingId) {
      setCreationRevisions([]);
      return;
    }
    let active = true;
    setCreationRevisionsLoading(true);
    setCreationRevisions([]);
    setCreationDecisionId('');
    void getMinutesRevisions(creationMeetingId)
      .then((revisions) => {
        if (active) setCreationRevisions(revisions);
      })
      .catch((error: unknown) => {
        if (active) setCreateError(`Notulensi tidak dapat dimuat: ${errorText(error)}`);
      })
      .finally(() => {
        if (active) setCreationRevisionsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [createOpen, creationMeetingId]);

  useEffect(() => {
    if (!createOpen || !creationMeetingId || !canAssign) {
      setCreationPicDirectory(null);
      return;
    }
    let active = true;
    setCreationPicDirectoryLoading(true);
    void searchAssignablePics(creationMeetingId, '')
      .then((directory) => {
        if (active) {
          setCreationPicDirectory(directory);
        }
      })
      .catch((error: unknown) => {
        if (active) setCreateError(`Pilihan unit dan PIC gagal dimuat: ${errorText(error)}`);
      })
      .finally(() => {
        if (active) setCreationPicDirectoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [canAssign, createOpen, creationMeetingId]);

  useEffect(() => {
    if (!detail?.meeting_id || !canAssign) {
      setAssignmentPicDirectory(null);
      return;
    }
    let active = true;
    setAssignmentPicDirectoryLoading(true);
    void searchAssignablePics(detail.meeting_id, '')
      .then((directory) => {
        if (active) setAssignmentPicDirectory(directory);
      })
      .catch((error: unknown) => {
        if (active) setActionError(`Pilihan PIC gagal dimuat: ${errorText(error)}`);
      })
      .finally(() => {
        if (active) setAssignmentPicDirectoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [canAssign, detail?.meeting_id]);

  async function openCreateForm(): Promise<void> {
    setSelectedId('');
    setDetail(null);
    setCreateOpen(true);
    setCreateError(null);
    setCreateNotice(null);
    setCreationPicDirectory(null);
    setMainPicUserId('');
    setMainPicDisplayName('');
    setMainPicOriginUnitId('');
    setSupportingPicUserId('');
    setSupportingPicDisplayName('');
    setSupportingPicOriginUnitId('');
    setCreateLoading(true);
    try {
      const meetings = await getMeetings();
      setCreationMeetings(meetings);
      setCreationMeetingId(meetings[0]?.id ?? '');
    } catch (error) {
      setCreateError(`Daftar rapat tidak dapat dimuat: ${errorText(error)}`);
    } finally {
      setCreateLoading(false);
    }
  }

  async function submitCreate(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!selectedSource) {
      setCreateError('Pilih keputusan yang tercatat pada notulensi terbaru.');
      return;
    }
    if (!mainPicUserId && !mainPicDisplayName.trim()) {
      setCreateError('Pilih jabatan PIC utama atau isi PIC lainnya.');
      return;
    }
    if (mainPicUserId !== '__OTHER__' && !mainPicOriginUnitId) {
      setCreateError('Pilih unit asal PIC utama dari keanggotaan aktifnya.');
      return;
    }
    if (supportingPicUserId && supportingPicUserId !== '__OTHER__' && !supportingPicOriginUnitId) {
      setCreateError('Pilih unit asal PIC pendukung dari keanggotaan aktifnya.');
      return;
    }
    const formData = new FormData(event.currentTarget);
    setCreateSaving(true);
    setCreateError(null);
    setCreateNotice(null);
    try {
      const created = await createActionItem({
        meeting_id: selectedSource.meeting.id,
        source_minutes_revision_id: selectedSource.revision.id,
        source_decision_id: selectedSource.decisionId,
        disposition_id: null,
        title: String(formData.get('title')).trim(),
        description: String(formData.get('description')).trim(),
        output_expected: String(formData.get('output_expected')).trim() || null,
        due_date: String(formData.get('due_date')) || null,
        priority: String(formData.get('priority')).trim(),
        main_pic_user_id: mainPicUserId && mainPicUserId !== '__OTHER__' ? mainPicUserId : null,
        main_pic_display_name: mainPicUserId === '__OTHER__' ? mainPicDisplayName.trim() : null,
        main_pic_origin_unit_id:
          mainPicUserId && mainPicUserId !== '__OTHER__' ? mainPicOriginUnitId : null,
      });
      let notice = 'Action Item berhasil dibuat dari keputusan rapat.';
      let result = created;
      if (supportingPicUserId) {
        try {
          await createActionItemAssignment(created.id, {
            assignee_user_id: supportingPicUserId !== '__OTHER__' ? supportingPicUserId : null,
            assignee_display_name:
              supportingPicUserId === '__OTHER__' ? supportingPicDisplayName.trim() : null,
            pic_origin_unit_id:
              supportingPicUserId === '__OTHER__' ? null : supportingPicOriginUnitId,
            reason: null,
            assignment_role: 'SUPPORTING',
            expected_version: created.version,
          });
          notice = 'Action Item berhasil dibuat beserta PIC pendukung.';
          try {
            result = await getActionItem(created.id);
          } catch {
            notice = 'Action Item dan PIC pendukung tersimpan. Buka detail untuk memuat ulang.';
          }
        } catch (supportingError) {
          notice = `Action Item dibuat, tetapi PIC pendukung belum tersimpan: ${errorText(supportingError)}`;
        }
      }
      setItems((previous) => [result, ...previous.filter((item) => item.id !== result.id)]);
      setSelectedId('');
      setShowAllItems(true);
      setDetail(null);
      setCreateOpen(false);
      setMainPicUserId('');
      setMainPicDisplayName('');
      setMainPicOriginUnitId('');
      setSupportingPicUserId('');
      setSupportingPicDisplayName('');
      setSupportingPicOriginUnitId('');
      setCreateNotice(notice);
    } catch (error) {
      setCreateError(errorText(error));
    } finally {
      setCreateSaving(false);
    }
  }

  async function submitStatus(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!detail || !canReviewAndManage) return;
    setStatusSaving(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const updated = await changeActionItemStatus(detail.id, {
        expected_version: detail.version,
        to_status: statusValue,
        note: statusNote.trim() || null,
      });
      setItems((previous) => previous.map((item) => (item.id === updated.id ? updated : item)));
      setStatusNote('');
      setActionNotice('Status resmi diperbarui.');
      await refreshDetail(detail.id);
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setStatusSaving(false);
    }
  }

  async function submitProgress(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!detail || !canSubmitProgress) return;
    const form = event.currentTarget;
    const formData = new FormData(form);
    const files = Array.from(
      form.querySelector<HTMLInputElement>('input[name="evidence_files"]')?.files ?? [],
    );
    if (files.length > 5) {
      setActionError('Maksimal lima file bukti dapat ditambahkan pada satu pembaruan.');
      return;
    }
    const invalidFile = files.find((file) => {
      const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
      return (
        file.size === 0 || file.size > 10 * 1024 * 1024 || !allowedEvidenceExtensions.has(extension)
      );
    });
    if (invalidFile) {
      setActionError(
        'Format bukti tidak didukung atau ukuran melebihi 10 MiB. Server tetap memvalidasi isi setiap file.',
      );
      return;
    }
    setProgressSaving(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const progress = await createActionItemProgressUpdate(detail.id, {
        assignment_id: userAssignment?.id ?? null,
        report_text: String(formData.get('report_text')).trim() || null,
        blocker_text: String(formData.get('blocker_text')).trim() || null,
        progress_percent:
          String(formData.get('progress_percent')) === ''
            ? null
            : Number(formData.get('progress_percent')),
        completion_requested: false,
      });
      form.reset();
      setSelectedEvidenceFiles([]);
      const failedUploads: string[] = [];
      let uploadedCount = 0;
      for (const file of files) {
        try {
          await uploadActionItemEvidenceFile(detail.id, progress.id, file);
          uploadedCount += 1;
        } catch (error) {
          failedUploads.push(`${file.name}: ${errorText(error)}`);
        }
      }
      if (failedUploads.length > 0) {
        setActionNotice(
          `Pembaruan tersimpan. ${uploadedCount} dari ${files.length} file berhasil diunggah.`,
        );
        setActionError(`File yang gagal diunggah: ${failedUploads.join(' · ')}`);
      } else {
        setActionNotice(
          files.length > 0
            ? `${uploadedCount} file bukti diunggah dan menunggu pemeriksaan keamanan.`
            : 'Pembaruan progres tersimpan.',
        );
      }
      await refreshDetail(detail.id);
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setProgressSaving(false);
    }
  }

  async function submitCompletionRequest(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!detail || !canSubmitProgress || !hasCleanFileEvidence || hasPendingCompletionRequest) {
      return;
    }
    const form = event.currentTarget;
    const formData = new FormData(form);
    setCompletionSaving(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await createActionItemProgressUpdate(detail.id, {
        assignment_id: userAssignment?.id ?? null,
        report_text: String(formData.get('completion_note')).trim() || null,
        blocker_text: null,
        progress_percent: null,
        completion_requested: true,
      });
      form.reset();
      setActionNotice(
        'Pengajuan penyelesaian terkirim untuk ditinjau Sekretariat atau Manager Legal.',
      );
      await refreshDetail(detail.id);
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setCompletionSaving(false);
    }
  }

  async function submitCompletionReview(
    event: FormEvent<HTMLFormElement>,
    progressUpdateId: string,
  ): Promise<void> {
    event.preventDefault();
    if (!detail || !canReviewAndManage) return;
    const formData = new FormData(event.currentTarget);
    const outcome = formData.get('outcome');
    const reviewNote = String(formData.get('review_note')).trim();
    if (outcome !== 'VERIFIED' && outcome !== 'NEEDS_REVISION') return;
    if (outcome === 'NEEDS_REVISION' && !reviewNote) {
      setActionError('Catatan wajib diisi saat meminta revisi.');
      return;
    }
    setVerificationSaving(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const request: ActionItemCompletionVerificationInput = {
        expected_version: detail.version,
        progress_update_id: progressUpdateId,
        outcome,
        review_note: reviewNote || null,
      };
      await reviewActionItemCompletion(detail.id, request);
      if (outcome === 'VERIFIED') {
        setCreateNotice('Penyelesaian diverifikasi; tindak lanjut kini tersedia di Repository.');
        setActionNotice(null);
      } else {
        setActionNotice('Catatan revisi terkirim kepada PIC.');
      }
      await refreshList();
      if (outcome === 'VERIFIED') {
        setDetail(null);
      } else {
        await refreshDetail(detail.id);
      }
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setVerificationSaving(false);
    }
  }

  async function submitAssignment(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!detail || !canAssign) return;
    if (!assignmentPicUserId && !assignmentPicDisplayName.trim()) {
      setActionError('Pilih PIC utama/pendukung atau isi nama PIC lainnya.');
      return;
    }
    if (assignmentPicUserId !== '__OTHER__' && !assignmentPicOriginUnitId) {
      setActionError('Pilih unit asal PIC dari keanggotaan aktifnya.');
      return;
    }
    const form = event.currentTarget;
    const formData = new FormData(form);
    setAssignmentSaving(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await createActionItemAssignment(detail.id, {
        assignee_user_id:
          assignmentPicUserId && assignmentPicUserId !== '__OTHER__' ? assignmentPicUserId : null,
        assignee_display_name:
          assignmentPicUserId === '__OTHER__' ? assignmentPicDisplayName.trim() : null,
        pic_origin_unit_id: assignmentPicUserId === '__OTHER__' ? null : assignmentPicOriginUnitId,
        reason: String(formData.get('reason') ?? '').trim() || null,
        assignment_role: String(formData.get('assignment_role')) as 'MAIN' | 'SUPPORTING',
        expected_version: detail.version,
      });
      form.reset();
      setAssignmentPicUserId('');
      setAssignmentPicDisplayName('');
      setAssignmentPicOriginUnitId('');
      setActionNotice('Penugasan PIC diperbarui.');
      await refreshList();
      await refreshDetail(detail.id);
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setAssignmentSaving(false);
    }
  }

  async function submitEdit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!detail || !canReviewAndManage || detail.official_status === 'SELESAI') return;
    const formData = new FormData(event.currentTarget);
    setEditSaving(true);
    setEditError(null);
    setActionNotice(null);
    try {
      await updateActionItem(detail.id, {
        expected_version: detail.version,
        title: String(formData.get('title')).trim(),
        description: String(formData.get('description')).trim(),
        output_expected: String(formData.get('output_expected')).trim() || null,
        due_date: String(formData.get('due_date')) || null,
        priority: String(formData.get('priority')),
      });
      setEditOpen(false);
      setActionNotice('Tindak lanjut berhasil diperbarui.');
      await refreshList();
      await refreshDetail(detail.id);
    } catch (error) {
      setEditError(errorText(error));
    } finally {
      setEditSaving(false);
    }
  }

  async function removeActionItem(): Promise<void> {
    if (!detail || !canReviewAndManage || detail.official_status === 'SELESAI') return;
    if (
      !window.confirm(
        'Hapus tindak lanjut ini dari daftar aktif? Catatan dan riwayatnya tetap disimpan di Repository.',
      )
    ) {
      return;
    }
    setEditSaving(true);
    setEditError(null);
    try {
      await deleteActionItem(detail.id, detail.version);
      const remainingItems = items.filter((item) => item.id !== detail.id);
      setItems(remainingItems);
      setSelectedId('');
      setDetail(null);
      setEditOpen(false);
      setCreateNotice('Tindak lanjut dipindahkan dari daftar aktif ke Repository.');
      setActionNotice(null);
    } catch (error) {
      setEditError(errorText(error));
    } finally {
      setEditSaving(false);
    }
  }

  async function endSupportingAssignment(assignment: ActionItemAssignment): Promise<void> {
    if (!detail || !canAssign) return;
    const firstConfirmation = window.confirm(
      'Akhiri penugasan PIC pendukung untuk tindak lanjut ini? PIC tersebut tidak lagi menjadi penanggung jawab aktif.',
    );
    if (!firstConfirmation) return;

    const finalConfirmation = window.confirm(
      'Konfirmasi kedua: penugasan PIC pendukung akan diakhiri dan dicatat dalam riwayat. Lanjutkan?',
    );
    if (!finalConfirmation) return;

    setAssignmentSaving(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await endActionItemAssignment(detail.id, assignment.id, {
        expected_version: detail.version,
      });
      setActionNotice('Penugasan PIC pendukung diakhiri.');
      await refreshList();
      await refreshDetail(detail.id);
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setAssignmentSaving(false);
    }
  }

  if (!canOpenActionItems(authenticatedUser)) {
    return (
      <div className="dashboard-content">
        <p className="minutes-alert" role="alert">
          Peran Anda tidak memiliki akses ke Action Item.
        </p>
      </div>
    );
  }

  return (
    <div className="dashboard-content meeting-management-page meeting-list-page action-items-page">
      {!createOpen && (
        <div className="meeting-list-hero">
          <section
            className="page-heading meeting-page-heading"
            aria-labelledby="action-items-title"
          >
            <div>
              <p className="eyebrow">RAPIM · TINDAK LANJUT</p>
              <h1 id="action-items-title">
                {authenticatedUser.roles.includes('PIC') ? 'Tugas saya' : 'Action Item'}
              </h1>
              <p className="page-description">Pantau status, PIC, dan tenggat tindak lanjut.</p>
            </div>
            {canCreate && (
              <button
                type="button"
                className="primary-button"
                onClick={() => void openCreateForm()}
              >
                Buat Action Item
              </button>
            )}
          </section>
          <section className="surface-panel meeting-search-panel" aria-label="Cari tindak lanjut">
            <label className="meeting-search-field" htmlFor="action-item-query">
              <span>Cari tindak lanjut</span>
              <input
                id="action-item-query"
                type="search"
                value={listQuery}
                autoComplete="off"
                placeholder="Judul, uraian, output, atau PIC"
                onChange={(event) => setListQuery(event.currentTarget.value)}
              />
            </label>
          </section>
        </div>
      )}

      {!createOpen && createNotice && (
        <p className="meeting-notice" role="status">
          {createNotice}
        </p>
      )}
      {!createOpen &&
        (listLoading ? (
          <p className="dashboard-state" role="status">
            Memuat Action Item...
          </p>
        ) : listError ? (
          <div className="meeting-error" role="alert">
            <span>{listError}</span>
            <button type="button" className="secondary-button" onClick={() => void refreshList()}>
              Coba lagi
            </button>
          </div>
        ) : items.length === 0 ? (
          <section
            className="surface-panel meeting-results-panel action-items-list"
            aria-labelledby="task-list-title"
          >
            <div className="meeting-list-heading">
              <div>
                <p className="section-kicker">DAFTAR TUGAS</p>
                <h2 id="task-list-title">Daftar tugas</h2>
              </div>
              <span className="meeting-result-count">0 tugas</span>
            </div>
            <p className="dashboard-empty">Belum ada Action Item dalam cakupan akses Anda.</p>
          </section>
        ) : (
          <>
            <div className="action-items-layout">
              <section
                className="surface-panel meeting-results-panel action-items-list"
                aria-labelledby="task-list-title"
              >
                <div className="meeting-list-heading">
                  <div>
                    <p className="section-kicker">DAFTAR TUGAS</p>
                    <h2 id="task-list-title">Daftar tugas</h2>
                  </div>
                  <span className="meeting-result-count">
                    {filteredItems.length}
                    {filteredItems.length !== items.length ? ` dari ${items.length}` : ''} tugas
                  </span>
                </div>
                <div className="action-item-filter-bar">
                  <label htmlFor="action-item-status-filter">
                    Status tugas
                    <select
                      id="action-item-status-filter"
                      value={statusFilter}
                      onChange={(event) => setStatusFilter(event.currentTarget.value)}
                    >
                      <option value="ALL">Semua status</option>
                      {Object.entries(statusLabels).map(([status, label]) => (
                        <option key={status} value={status}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {(listQuery || statusFilter !== 'ALL') && (
                    <button
                      className="text-button action-item-filter-reset"
                      type="button"
                      onClick={() => {
                        setListQuery('');
                        setStatusFilter('ALL');
                      }}
                    >
                      Hapus filter
                    </button>
                  )}
                </div>
                {filteredItems.length === 0 ? (
                  <p className="dashboard-empty">
                    Tidak ada tugas yang cocok. Ubah kata kunci atau status.
                  </p>
                ) : (
                  <ul className="meeting-list">
                    {listedItems.map((item) => (
                      <li key={item.id}>
                        <button
                          className={`meeting-list-row action-item-list-button${selectedId === item.id ? ' is-selected' : ''}`}
                          type="button"
                          aria-current={selectedId === item.id ? 'true' : undefined}
                          onClick={() => {
                            setSelectedId(item.id);
                            setDetail(null);
                            setActionError(null);
                            setActionNotice(null);
                          }}
                        >
                          <span className="meeting-list-copy action-item-list-copy">
                            <strong className="meeting-list-title">{item.title}</strong>
                            <small className="meeting-list-date">
                              Tenggat: {formatDate(item.due_date)}
                            </small>
                          </span>
                          <span className="meeting-list-meta">
                            <span
                              className={`meeting-status meeting-status--${item.official_status.toLowerCase()} action-item-list-status action-item-list-status--${item.official_status.toLowerCase()}`}
                              role="status"
                              aria-label={`Status: ${statusLabels[item.official_status]}`}
                            >
                              {statusLabels[item.official_status]}
                            </span>
                            <span className="meeting-list-open" aria-hidden="true">
                              Buka detail <span>→</span>
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {filteredItems.length > 5 && (
                  <button
                    className="text-button"
                    type="button"
                    aria-expanded={showAllItems}
                    onClick={() => setShowAllItems((expanded) => !expanded)}
                  >
                    {showAllItems
                      ? 'Tampilkan lebih sedikit'
                      : `Lainnya (${filteredItems.length - 5})`}
                  </button>
                )}
              </section>
            </div>

            {selectedId && !createOpen && (
              <div
                className="action-item-modal-backdrop"
                onMouseDown={(event) => {
                  if (event.target === event.currentTarget) setSelectedId('');
                }}
              >
                <section
                  className="surface-panel action-item-detail action-item-detail--modal"
                  role="dialog"
                  aria-modal="true"
                  aria-label="Detail tindak lanjut"
                >
                  <button
                    className="action-item-modal-close"
                    type="button"
                    onClick={() => setSelectedId('')}
                  >
                    Tutup detail
                  </button>
                  {detailLoading ? (
                    <p className="dashboard-state" role="status">
                      Memuat detail Action Item...
                    </p>
                  ) : detailError ? (
                    <div className="meeting-error" role="alert">
                      <span>{detailError}</span>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => void refreshDetail(selectedId)}
                      >
                        Coba lagi
                      </button>
                    </div>
                  ) : detail ? (
                    <>
                      <div className="action-item-detail-heading">
                        <div className="action-item-detail-heading-copy">
                          <div>
                            <p className="section-kicker">DETAIL ACTION ITEM</p>
                            <h2 id="task-detail-title">{detail.title}</h2>
                          </div>
                          <span
                            className={`action-item-status action-item-status--${detail.official_status.toLowerCase()}`}
                          >
                            {statusLabels[detail.official_status]}
                          </span>
                        </div>
                        <div className="action-item-detail-heading-actions">
                          <button
                            className="text-button"
                            type="button"
                            disabled={detailLoading}
                            onClick={() => void refreshDetail(detail.id)}
                          >
                            {detailLoading ? 'Memuat...' : 'Perbarui detail'}
                          </button>
                          {canReviewAndManage && detail.official_status !== 'SELESAI' && (
                            <button
                              className="secondary-button"
                              type="button"
                              onClick={() => {
                                setEditOpen((open) => !open);
                                setEditError(null);
                              }}
                            >
                              {editOpen ? 'Tutup edit' : 'Edit tindak lanjut'}
                            </button>
                          )}
                        </div>
                      </div>
                      {editOpen && canReviewAndManage && detail.official_status !== 'SELESAI' && (
                        <section
                          className="action-item-edit-panel"
                          aria-labelledby="edit-action-title"
                        >
                          <h3 id="edit-action-title">Edit tindak lanjut</h3>
                          <form
                            className="action-item-inline-form"
                            key={detail.version}
                            onSubmit={(event) => void submitEdit(event)}
                          >
                            <label>
                              Judul tugas
                              <input
                                name="title"
                                defaultValue={detail.title}
                                maxLength={300}
                                required
                              />
                            </label>
                            <label>
                              Deskripsi tugas
                              <textarea
                                name="description"
                                defaultValue={detail.description}
                                maxLength={20000}
                                rows={4}
                                required
                              />
                            </label>
                            <label>
                              Output yang diharapkan
                              <textarea
                                name="output_expected"
                                defaultValue={detail.output_expected ?? ''}
                                maxLength={20000}
                                rows={2}
                              />
                            </label>
                            <label>
                              Tenggat waktu
                              <input
                                name="due_date"
                                type="date"
                                defaultValue={detail.due_date ?? ''}
                              />
                            </label>
                            <label>
                              Prioritas
                              <select name="priority" defaultValue={detail.priority} required>
                                {!actionItemPriorities.includes(detail.priority) && (
                                  <option value={detail.priority}>
                                    {detail.priority} (saat ini)
                                  </option>
                                )}
                                {actionItemPriorities.map((priority) => (
                                  <option key={priority} value={priority}>
                                    {priority}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <div className="action-item-form-actions">
                              <button
                                className="primary-button"
                                type="submit"
                                disabled={editSaving}
                              >
                                {editSaving ? 'Menyimpan...' : 'Simpan perubahan'}
                              </button>
                              <button
                                className="secondary-button"
                                type="button"
                                disabled={editSaving}
                                onClick={() => setEditOpen(false)}
                              >
                                Batal
                              </button>
                            </div>
                          </form>
                          {canAssign && (
                            <form
                              className="action-item-inline-form"
                              onSubmit={(event) => void submitAssignment(event)}
                            >
                              <h4>Tambah PIC pendukung atau ganti PIC utama</h4>
                              {assignmentPicDirectoryLoading ? (
                                <p className="dashboard-state" role="status">
                                  Memuat pilihan PIC...
                                </p>
                              ) : (
                                <ActionItemPicPicker
                                  enabled
                                  options={picPickerOptions(assignmentPicDirectory)}
                                  label="Pilih jabatan PIC"
                                  value={assignmentPicUserId}
                                  onChange={(value) => {
                                    setAssignmentPicUserId(value);
                                    setAssignmentPicOriginUnitId('');
                                  }}
                                  otherValue={assignmentPicDisplayName}
                                  onOtherChange={setAssignmentPicDisplayName}
                                />
                              )}
                              {assignmentPicUserId && assignmentPicUserId !== '__OTHER__' && (
                                <label>
                                  Unit asal PIC
                                  <select
                                    value={assignmentPicOriginUnitId}
                                    onChange={(event) =>
                                      setAssignmentPicOriginUnitId(event.target.value)
                                    }
                                    required
                                    disabled={assignmentPicDirectoryLoading}
                                  >
                                    <option value="">Pilih unit asal</option>
                                    {assignmentPicActiveUnits.map((unit) => (
                                      <option key={unit.id} value={unit.id}>
                                        {unit.unit_code} · {unit.name}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                              )}
                              <label>
                                Peran penugasan
                                <select name="assignment_role" defaultValue="SUPPORTING">
                                  <option value="SUPPORTING">PIC pendukung</option>
                                  <option value="MAIN">Ganti PIC utama</option>
                                </select>
                              </label>
                              <label>
                                Alasan penugasan
                                <input name="reason" maxLength={4000} />
                              </label>
                              <button
                                className="secondary-button"
                                type="submit"
                                disabled={
                                  assignmentSaving ||
                                  assignmentPicDirectoryLoading ||
                                  (assignmentPicUserId !== '__OTHER__' &&
                                    Boolean(assignmentPicUserId) &&
                                    !assignmentPicOriginUnitId) ||
                                  (!assignmentPicUserId && !assignmentPicDisplayName.trim())
                                }
                              >
                                {assignmentSaving ? 'Menyimpan...' : 'Simpan penugasan'}
                              </button>
                            </form>
                          )}
                          <button
                            className="button button--secondary action-item-delete-button"
                            type="button"
                            disabled={editSaving}
                            onClick={() => void removeActionItem()}
                          >
                            Hapus dari daftar aktif
                          </button>
                          {editError && (
                            <p className="minutes-alert" role="alert">
                              {editError}
                            </p>
                          )}
                        </section>
                      )}
                      {detail.source_revision_is_stale && (
                        <p className="minutes-readonly-note">
                          Tugas ini mengacu pada notulensi sebelumnya. Periksa kembali sumber rapat
                          bila ada perubahan.
                        </p>
                      )}
                      <p className="action-item-description">{detail.description}</p>
                      <dl className="action-item-metadata">
                        <div>
                          <dt>Output yang diharapkan</dt>
                          <dd>{detail.output_expected ?? 'Belum ditentukan'}</dd>
                        </div>
                        <div>
                          <dt>Tenggat waktu</dt>
                          <dd>{formatDate(detail.due_date)}</dd>
                        </div>
                        <div>
                          <dt>Prioritas</dt>
                          <dd>{detail.priority}</dd>
                        </div>
                      </dl>

                      <section
                        className="action-item-subsection"
                        aria-labelledby="assignment-title"
                      >
                        <h3 id="assignment-title">PIC aktif</h3>
                        {detail.active_assignments.length > 0 ? (
                          <ul className="action-item-assignment-list">
                            {detail.active_assignments.map((activeAssignment) => {
                              const person = participantOptions.find(
                                (candidate) => candidate.id === activeAssignment.assignee_user_id,
                              );
                              return (
                                <li key={activeAssignment.id}>
                                  <span>
                                    <strong>
                                      {person
                                        ? picTitle(person)
                                        : activeAssignment.assignee_display_name || 'PIC lainnya'}
                                    </strong>
                                    {' · '}
                                    {activeAssignment.assignment_role === 'MAIN'
                                      ? 'PIC utama'
                                      : 'PIC pendukung'}
                                  </span>
                                  {canAssign &&
                                    activeAssignment.assignment_role === 'SUPPORTING' && (
                                      <div className="action-item-end-assignment">
                                        <button
                                          className="text-button"
                                          type="button"
                                          disabled={assignmentSaving}
                                          onClick={() =>
                                            void endSupportingAssignment(activeAssignment)
                                          }
                                        >
                                          Akhiri penugasan
                                        </button>
                                      </div>
                                    )}
                                </li>
                              );
                            })}
                          </ul>
                        ) : (
                          <p className="dashboard-empty">
                            Tidak ada PIC aktif pada data tugas ini.
                          </p>
                        )}
                      </section>

                      <section
                        className="action-item-subsection"
                        aria-labelledby="progress-history-title"
                      >
                        <h3 id="progress-history-title">Riwayat progres</h3>
                        {detail.progress_updates.length > 0 ? (
                          <ol className="action-item-progress-list">
                            {detail.progress_updates
                              .slice()
                              .reverse()
                              .map((update) => (
                                <li key={update.id}>
                                  <strong>{formatTimestamp(update.submitted_at)}</strong>
                                  {update.completion_requested && (
                                    <span>
                                      Pengajuan penyelesaian:{' '}
                                      {completionOutcomeLabel(detail, update.id)}
                                    </span>
                                  )}
                                  <span>
                                    Progres dilaporkan:{' '}
                                    {update.progress_percent === null
                                      ? 'Tidak diisi'
                                      : `${update.progress_percent}%`}
                                  </span>
                                  {update.report_text && <p>{update.report_text}</p>}
                                  {update.blocker_text && <p>Kendala: {update.blocker_text}</p>}
                                  {update.evidence.length > 0 && (
                                    <ul className="action-item-evidence-list">
                                      {update.evidence.map((evidence) => (
                                        <li key={evidence.id}>
                                          {evidence.evidence_kind === 'FILE' ? (
                                            <>
                                              <span>
                                                {evidence.original_filename ?? 'Bukti file'} ·{' '}
                                                {evidenceStatusLabel(evidence.scan_status)}
                                              </span>
                                              {evidence.scan_status === 'CLEAN' &&
                                                evidence.download_url && (
                                                  <a href={evidence.download_url} download>
                                                    Unduh melalui endpoint terotorisasi
                                                  </a>
                                                )}
                                            </>
                                          ) : evidence.external_url ? (
                                            <>
                                              <span>
                                                {evidence.link_label ?? 'Tautan bukti'} · tautan
                                                eksternal (tidak dipindai)
                                              </span>
                                              <a
                                                href={evidence.external_url}
                                                target="_blank"
                                                rel="noreferrer"
                                              >
                                                Buka tautan
                                              </a>
                                            </>
                                          ) : null}
                                        </li>
                                      ))}
                                    </ul>
                                  )}
                                </li>
                              ))}
                          </ol>
                        ) : (
                          <p className="dashboard-empty">Belum ada pembaruan progres.</p>
                        )}
                        {canSubmitProgress && (
                          <form
                            className="action-item-inline-form"
                            onSubmit={(event) => void submitProgress(event)}
                          >
                            <h4>Kirim pembaruan progres</h4>
                            <label>
                              Laporan progres
                              <textarea name="report_text" maxLength={20000} rows={3} />
                            </label>
                            <label>
                              Kendala
                              <textarea name="blocker_text" maxLength={20000} rows={2} />
                            </label>
                            <label>
                              Progres (%)
                              <input name="progress_percent" type="number" min="0" max="100" />
                            </label>
                            <label>
                              Bukti pendukung (maksimal 5 file)
                              <input
                                name="evidence_files"
                                type="file"
                                multiple
                                accept=".pdf,.jpg,.jpeg,.png,.heic,.heif,.docx,.xlsx,.pptx,.csv,.txt"
                                aria-describedby="evidence-files-help evidence-files-selected"
                                onChange={(event) =>
                                  setSelectedEvidenceFiles(
                                    Array.from(event.currentTarget.files ?? []),
                                  )
                                }
                              />
                            </label>
                            <small id="evidence-files-help">
                              Maksimal lima file per pembaruan, masing-masing 10 MiB. Server
                              memvalidasi isi dan menjalankan pemeriksaan keamanan. Pilih beberapa
                              file sekaligus dari jendela pemilih file.
                            </small>
                            <div
                              id="evidence-files-selected"
                              className="evidence-file-selection"
                              aria-live="polite"
                            >
                              {selectedEvidenceFiles.length === 0 ? (
                                <span>Belum ada file yang dipilih.</span>
                              ) : (
                                <>
                                  <strong>
                                    {selectedEvidenceFiles.length} dari 5 file dipilih
                                  </strong>
                                  <ul>
                                    {selectedEvidenceFiles.map((file, index) => (
                                      <li key={`${file.name}-${file.lastModified}-${index}`}>
                                        {file.name}
                                      </li>
                                    ))}
                                  </ul>
                                </>
                              )}
                            </div>
                            <p>
                              Pembaruan tidak mengubah status resmi. Status hanya dapat diubah
                              Sekretariat atau Manager Legal.
                            </p>
                            <button
                              className="primary-button"
                              type="submit"
                              disabled={progressSaving}
                            >
                              {progressSaving ? 'Menyimpan...' : 'Simpan progres dan bukti'}
                            </button>
                          </form>
                        )}
                      </section>

                      {canSubmitProgress && (
                        <form
                          className="action-item-inline-form"
                          onSubmit={(event) => void submitCompletionRequest(event)}
                        >
                          <h3>Ajukan penyelesaian</h3>
                          <label>
                            Catatan pengajuan
                            <textarea name="completion_note" maxLength={20000} rows={3} />
                          </label>
                          {!hasCleanFileEvidence && (
                            <p className="minutes-readonly-note">
                              Bukti bersih hasil pemeriksaan diperlukan sebelum mengajukan
                              penyelesaian.
                            </p>
                          )}
                          {hasPendingCompletionRequest && (
                            <p className="minutes-readonly-note">
                              Pengajuan penyelesaian sebelumnya masih menunggu verifikasi.
                            </p>
                          )}
                          <p>
                            Pengajuan tidak mengubah status resmi menjadi Selesai. Sekretariat atau
                            Manager Legal harus meninjau pengajuan.
                          </p>
                          <button
                            className="primary-button"
                            type="submit"
                            disabled={
                              completionSaving ||
                              !hasCleanFileEvidence ||
                              hasPendingCompletionRequest
                            }
                          >
                            {completionSaving ? 'Mengirim...' : 'Ajukan penyelesaian'}
                          </button>
                        </form>
                      )}

                      {canReviewAndManage && (
                        <section
                          className="action-item-subsection"
                          aria-labelledby="completion-review-title"
                        >
                          <h3 id="completion-review-title">Verifikasi penyelesaian</h3>
                          {unreviewedCompletionRequests.length === 0 ? (
                            <p className="dashboard-empty">
                              Tidak ada pengajuan penyelesaian yang menunggu verifikasi.
                            </p>
                          ) : (
                            <ul className="action-item-review-list">
                              {unreviewedCompletionRequests.map((update) => (
                                <li key={update.id}>
                                  <strong>Pengajuan {formatTimestamp(update.submitted_at)}</strong>
                                  {update.report_text && <p>{update.report_text}</p>}
                                  <form
                                    className="action-item-inline-form"
                                    onSubmit={(event) =>
                                      void submitCompletionReview(event, update.id)
                                    }
                                  >
                                    <label>
                                      Hasil verifikasi {update.id}
                                      <select name="outcome" defaultValue="NEEDS_REVISION">
                                        <option value="NEEDS_REVISION">Minta revisi</option>
                                        <option value="VERIFIED" disabled={!hasCleanFileEvidence}>
                                          Verifikasi selesai
                                        </option>
                                      </select>
                                    </label>
                                    <label>
                                      Catatan verifikasi
                                      <textarea name="review_note" maxLength={4000} rows={2} />
                                    </label>
                                    {!hasCleanFileEvidence && (
                                      <p className="minutes-readonly-note">
                                        Verifikasi selesai hanya aktif setelah bukti lolos
                                        pemeriksaan keamanan.
                                      </p>
                                    )}
                                    <button
                                      className="secondary-button"
                                      type="submit"
                                      disabled={verificationSaving}
                                    >
                                      {verificationSaving
                                        ? 'Menyimpan...'
                                        : `Simpan verifikasi ${update.id}`}
                                    </button>
                                  </form>
                                </li>
                              ))}
                            </ul>
                          )}
                        </section>
                      )}

                      {canReviewAndManage && detail.official_status !== 'SELESAI' && (
                        <form
                          className="action-item-inline-form"
                          onSubmit={(event) => void submitStatus(event)}
                        >
                          <h3>Ubah status resmi</h3>
                          <label>
                            Status resmi
                            <select
                              value={statusValue}
                              onChange={(event) =>
                                setStatusValue(event.target.value as ActionItemStatus)
                              }
                            >
                              {officialStatuses.map((status) => (
                                <option key={status} value={status}>
                                  {statusLabels[status]}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            Catatan perubahan status
                            <textarea
                              value={statusNote}
                              maxLength={4000}
                              rows={2}
                              onChange={(event) => setStatusNote(event.target.value)}
                            />
                          </label>
                          <p>
                            Status Selesai memerlukan alur verifikasi penyelesaian dan tidak diubah
                            dari formulir ini.
                          </p>
                          <button
                            className="secondary-button"
                            type="submit"
                            disabled={statusSaving}
                          >
                            {statusSaving ? 'Menyimpan...' : 'Ubah status resmi'}
                          </button>
                        </form>
                      )}

                      {detail.status_history.length > 0 && (
                        <details className="action-item-subsection">
                          <summary>Riwayat status resmi ({detail.status_history.length})</summary>
                          <ol className="action-item-progress-list">
                            {detail.status_history
                              .slice()
                              .reverse()
                              .map((entry) => (
                                <li key={entry.id}>
                                  <strong>{statusLabels[entry.new_status]}</strong>
                                  <span>{formatTimestamp(entry.changed_at)}</span>
                                  {entry.change_note && <p>{entry.change_note}</p>}
                                </li>
                              ))}
                          </ol>
                        </details>
                      )}
                      {actionError && (
                        <p className="minutes-alert" role="alert">
                          {actionError}
                        </p>
                      )}
                      {actionNotice && (
                        <p className="meeting-notice" role="status">
                          {actionNotice}
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="dashboard-empty">Pilih Action Item untuk melihat detail.</p>
                  )}
                </section>
              </div>
            )}
          </>
        ))}

      {createOpen && canCreate && (
        <section
          className="surface-panel action-item-create-panel"
          aria-labelledby="create-action-title"
        >
          <div className="section-heading">
            <h2 id="create-action-title">Buat Action Item dari keputusan</h2>
            <button type="button" className="text-button" onClick={() => setCreateOpen(false)}>
              Kembali ke daftar tindak lanjut
            </button>
          </div>
          {createLoading ? (
            <p className="dashboard-state" role="status">
              Memuat rapat...
            </p>
          ) : creationMeetings.length === 0 ? (
            <>
              {createError && (
                <p className="minutes-alert" role="alert">
                  {createError}
                </p>
              )}
              <p className="dashboard-empty">Tidak ada rapat dalam cakupan untuk membuat tugas.</p>
            </>
          ) : (
            <form
              className="action-item-create-form"
              onSubmit={(event) => void submitCreate(event)}
            >
              <MeetingPicker
                id="action-item-meeting-picker"
                label="Cari rapat sumber"
                meetings={creationMeetings}
                selectedMeetingId={creationMeetingId}
                disabled={createSaving}
                onSelect={(meetingId) => {
                  setCreationMeetingId(meetingId);
                  setCreationDecisionId('');
                  setMainPicUserId('');
                  setMainPicDisplayName('');
                  setMainPicOriginUnitId('');
                  setSupportingPicUserId('');
                  setSupportingPicDisplayName('');
                  setSupportingPicOriginUnitId('');
                }}
              />
              <label>
                Pilih keputusan dari notulensi
                <select
                  value={creationDecisionId}
                  onChange={(event) => {
                    setCreationDecisionId(event.target.value);
                    setMainPicUserId('');
                    setMainPicDisplayName('');
                    setMainPicOriginUnitId('');
                    setSupportingPicUserId('');
                    setSupportingPicDisplayName('');
                    setSupportingPicOriginUnitId('');
                  }}
                  required
                  disabled={creationRevisionsLoading || creationSources.length === 0}
                >
                  <option value="">Pilih keputusan</option>
                  {creationSources.map((source) => (
                    <option key={source.decisionId} value={source.decisionId}>
                      {source.decisionText} · {source.agendaTitle}
                      {source.discussionSubject ? ` · ${source.discussionSubject}` : ''}
                    </option>
                  ))}
                </select>
              </label>
              {creationRevisionsLoading && (
                <p className="dashboard-state" role="status">
                  Memuat notulensi...
                </p>
              )}
              {!creationRevisionsLoading && creationRevisions.length === 0 && (
                <p className="dashboard-empty">
                  Notulensi belum tersedia. Tindak lanjut harus merujuk keputusan rapat.
                </p>
              )}
              {!creationRevisionsLoading &&
                creationRevisions.length > 0 &&
                creationSources.length === 0 && (
                  <p className="dashboard-empty">
                    Notulensi belum mencatat keputusan yang memerlukan tindak lanjut.
                  </p>
                )}
              {selectedSource && (
                <p className="action-item-source-note">
                  Sumber: {selectedSource.meeting.meeting_number} · {selectedSource.decisionText}
                </p>
              )}
              <label>
                Judul tugas
                <input name="title" maxLength={300} required />
              </label>
              <label>
                Deskripsi tugas
                <textarea name="description" maxLength={20000} rows={4} required />
              </label>
              <label>
                Output yang diharapkan
                <textarea name="output_expected" maxLength={20000} rows={2} />
              </label>
              <label>
                Tenggat waktu
                <input name="due_date" type="date" />
              </label>
              <label>
                Prioritas
                <select name="priority" defaultValue="Normal" required>
                  {actionItemPriorities.map((priority) => (
                    <option key={priority} value={priority}>
                      {priority}
                    </option>
                  ))}
                </select>
              </label>
              {participantOptionsError && (
                <p className="minutes-alert" role="alert">
                  {participantOptionsError}
                </p>
              )}
              {creationPicDirectoryLoading ? (
                <p className="dashboard-state" role="status">
                  Memuat pilihan unit dan PIC...
                </p>
              ) : (
                <ActionItemPicPicker
                  enabled={Boolean(selectedSource) && !createSaving}
                  options={picPickerOptions(creationPicDirectory).filter(
                    (person) =>
                      person.id !== supportingPicUserId || supportingPicUserId === '__OTHER__',
                  )}
                  label="PIC utama"
                  value={mainPicUserId}
                  onChange={(value) => {
                    setMainPicUserId(value);
                    setMainPicOriginUnitId('');
                    if (value && value !== '__OTHER__' && value === supportingPicUserId) {
                      setSupportingPicUserId('');
                      setSupportingPicDisplayName('');
                      setSupportingPicOriginUnitId('');
                    }
                  }}
                  otherValue={mainPicDisplayName}
                  onOtherChange={setMainPicDisplayName}
                />
              )}
              {mainPicUserId && mainPicUserId !== '__OTHER__' && (
                <label>
                  Unit asal PIC utama
                  <select
                    value={mainPicOriginUnitId}
                    onChange={(event) => setMainPicOriginUnitId(event.target.value)}
                    required
                    disabled={creationPicDirectoryLoading || createSaving}
                  >
                    <option value="">Pilih unit asal</option>
                    {mainPicActiveUnits.map((unit) => (
                      <option key={unit.id} value={unit.id}>
                        {unit.unit_code} · {unit.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {!creationPicDirectoryLoading && (
                <ActionItemPicPicker
                  enabled={Boolean(selectedSource) && !createSaving}
                  options={picPickerOptions(creationPicDirectory).filter(
                    (person) => person.id !== mainPicUserId || mainPicUserId === '__OTHER__',
                  )}
                  label="PIC pendukung (opsional)"
                  value={supportingPicUserId}
                  onChange={(value) => {
                    setSupportingPicUserId(value);
                    setSupportingPicOriginUnitId('');
                  }}
                  otherValue={supportingPicDisplayName}
                  onOtherChange={setSupportingPicDisplayName}
                  required={false}
                />
              )}
              {supportingPicUserId && supportingPicUserId !== '__OTHER__' && (
                <label>
                  Unit asal PIC pendukung
                  <select
                    value={supportingPicOriginUnitId}
                    onChange={(event) => setSupportingPicOriginUnitId(event.target.value)}
                    required
                    disabled={creationPicDirectoryLoading || createSaving}
                  >
                    <option value="">Pilih unit asal</option>
                    {supportingPicActiveUnits.map((unit) => (
                      <option key={unit.id} value={unit.id}>
                        {unit.unit_code} · {unit.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {createError && (
                <p className="minutes-alert" role="alert">
                  {createError}
                </p>
              )}
              <div className="action-item-form-actions">
                <button
                  className="primary-button"
                  type="submit"
                  disabled={
                    createSaving ||
                    !selectedSource ||
                    creationPicDirectoryLoading ||
                    (!mainPicUserId && !mainPicDisplayName.trim()) ||
                    (mainPicUserId !== '__OTHER__' &&
                      Boolean(mainPicUserId) &&
                      !mainPicOriginUnitId) ||
                    (supportingPicUserId === '__OTHER__' && !supportingPicDisplayName.trim()) ||
                    (supportingPicUserId !== '__OTHER__' &&
                      Boolean(supportingPicUserId) &&
                      !supportingPicOriginUnitId) ||
                    creationRevisionsLoading
                  }
                >
                  {createSaving ? 'Menyimpan...' : 'Simpan Action Item'}
                </button>
              </div>
            </form>
          )}
        </section>
      )}
    </div>
  );
}

export default ActionItemManagement;
