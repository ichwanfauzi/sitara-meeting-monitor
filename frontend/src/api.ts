export type MeetingStatus = 'DRAFT' | 'LIVE' | 'FINAL' | 'ARCHIVED';
export type ActionItemStatus =
  'BELUM_DIMULAI' | 'BERPROSES' | 'TERKENDALA' | 'MENUNGGU_ACC' | 'SELESAI';
export type NotificationType =
  | 'ACTION_ITEM_STATUS_CHANGED'
  | 'DECISION_BRIEF_REVIEW_NEEDED'
  | 'DECISION_BRIEF_REVIEW_WITHDRAWN'
  | 'DECISION_BRIEF_REVIEW_COMPLETED';

export interface NotificationRecord {
  id: string;
  notification_type: NotificationType;
  message: string;
  target_type: 'ACTION_ITEM' | 'MEETING';
  target_id: string;
  created_at: string;
  read_at: string | null;
}

export interface NotificationPage {
  items: NotificationRecord[];
  unread_count: number;
}

export interface ActionItemAssignment {
  id: string;
  action_item_id: string;
  assignee_user_id: string | null;
  assignee_display_name: string | null;
  assignee_name: string | null;
  pic_origin_unit: OrganizationUnitReference | null;
  assigned_by_user_id: string;
  assignment_role: 'MAIN' | 'SUPPORTING';
  started_at: string;
  ended_at: string | null;
  ended_by_user_id: string | null;
  end_reason: string | null;
  assignment_reason?: string | null;
}

export interface ActionItemSummary {
  id: string;
  meeting_id: string;
  source_minutes_revision_id: string;
  source_decision_id: string;
  disposition_id: string | null;
  responsible_unit: OrganizationUnitReference | null;
  source_revision_is_stale: boolean;
  title: string;
  description: string;
  output_expected: string | null;
  due_date: string | null;
  priority: string;
  official_status: ActionItemStatus;
  version: number;
  created_by_id: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  deleted_at: string | null;
  active_assignments: ActionItemAssignment[];
}

export interface ActionItemEvidence {
  id: string;
  progress_update_id: string;
  evidence_kind: 'FILE' | 'LINK';
  original_filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  sha256: string | null;
  external_url: string | null;
  link_label: string | null;
  download_url: string | null;
  scan_status: 'PENDING' | 'CLEAN' | 'REJECTED' | null;
  uploaded_by_user_id: string;
  created_at: string;
}

export interface ActionItemProgressUpdate {
  id: string;
  action_item_id: string;
  assignment_id: string | null;
  actor_user_id: string;
  submitted_as: 'PIC' | 'LEADERSHIP';
  report_text: string | null;
  blocker_text: string | null;
  progress_percent: number | null;
  completion_requested: boolean;
  submitted_at: string;
  evidence: ActionItemEvidence[];
}

export interface ActionItemCompletionVerificationInput {
  expected_version: number;
  progress_update_id: string;
  outcome: 'VERIFIED' | 'NEEDS_REVISION';
  review_note: string | null;
}

export interface ActionItemDetail extends ActionItemSummary {
  assignment_history: ActionItemAssignment[];
  progress_updates: ActionItemProgressUpdate[];
  status_history: {
    id: string;
    event_number: number;
    old_status: ActionItemStatus | null;
    new_status: ActionItemStatus;
    changed_by_id: string;
    verification_id: string | null;
    change_note: string | null;
    changed_at: string;
  }[];
  completion_verifications: {
    id: string;
    action_item_id: string;
    progress_update_id: string;
    reviewer_user_id: string;
    outcome: 'VERIFIED' | 'NEEDS_REVISION';
    review_note: string | null;
    reviewed_at: string;
  }[];
}

export interface ActionItemCreateInput {
  meeting_id: string;
  source_minutes_revision_id: string;
  source_decision_id: string;
  disposition_id: string | null;
  responsible_unit_id?: string | null;
  title: string;
  description: string;
  output_expected: string | null;
  due_date: string | null;
  priority: string;
  main_pic_user_id: string | null;
  main_pic_display_name: string | null;
  main_pic_origin_unit_id: string | null;
}

export interface ActionItemUpdateInput {
  expected_version: number;
  title: string;
  description: string;
  output_expected: string | null;
  due_date: string | null;
  priority: string;
}

export type DispositionTargetInput =
  | { target_type: 'USER'; user_id: string }
  | { target_type: 'UNIT'; unit_id: string }
  | { target_type: 'ROLE'; role_id: string };

export interface DispositionTarget {
  id: string;
  target_type: 'USER' | 'UNIT' | 'ROLE';
  target_user_id: string | null;
  target_unit_id: string | null;
  target_role_id: string | null;
  target_label: string;
}

export interface Disposition {
  id: string;
  meeting_id: string;
  source_minutes_revision_id: string;
  source_decision_id: string;
  issued_by_user_id: string;
  instruction: string;
  created_at: string;
  targets: DispositionTarget[];
}

export interface DispositionTargetDirectory {
  query: string;
  users: { id: string; full_name: string; job_title: string | null }[];
  units: { id: string; unit_code: string; name: string }[];
  roles: { id: string; role_code: string; role_name: string }[];
  more_users: boolean;
  more_units: boolean;
  more_roles: boolean;
}

export interface AssignablePicDirectory {
  query: string;
  pics: {
    id: string;
    full_name: string;
    job_title: string | null;
    active_units: OrganizationUnitReference[];
  }[];
  units: OrganizationUnitReference[];
  more_pics: boolean;
}

export interface OrganizationUnitReference {
  id: string;
  unit_code: string;
  name: string;
}

export interface OrganizationUnitDirectory {
  units: OrganizationUnitReference[];
}

export interface DispositionCreateInput {
  source_minutes_revision_id: string;
  source_decision_id: string;
  instruction: string;
  targets: DispositionTargetInput[];
}

export interface ActionItemAssignmentCreateInput {
  assignee_user_id: string | null;
  assignee_display_name: string | null;
  pic_origin_unit_id: string | null;
  reason?: string | null;
  assignment_role: 'MAIN' | 'SUPPORTING';
  expected_version: number;
}

export interface ActionItemAssignmentEndInput {
  expected_version: number;
  reason?: string | null;
}

export interface ActionItemProgressUpdateInput {
  assignment_id: string | null;
  report_text: string | null;
  blocker_text: string | null;
  progress_percent: number | null;
  completion_requested: boolean;
}

export interface ActionItemStatusChangeInput {
  expected_version: number;
  to_status: ActionItemStatus;
  note: string | null;
}

export interface AuthenticatedUser {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
}

export interface MeetingAgenda {
  id: string;
  meeting_id?: string;
  agenda_number: number;
  title: string;
  agenda_description: string | null;
  pic_suggestion: string | null;
  supporting_pic_suggestion: string | null;
  duration_minutes?: number | null;
  sort_order: number;
}

export interface MeetingParticipant {
  user_id: string;
  participant_name: string;
  participant_title?: string | null;
}

export interface MeetingExternalParticipant {
  id: string;
  participant_name: string;
}

export interface MeetingParticipantOption {
  id: string;
  full_name: string;
  job_title: string | null;
  roles: string[];
}

export interface MeetingSummary {
  id: string;
  meeting_number: string;
  title: string;
  meeting_date: string;
  status: MeetingStatus;
  version: number;
  agendas: MeetingAgenda[];
  meeting_type?: string;
  start_time?: string | null;
  end_time?: string | null;
  location?: string | null;
  created_by_id?: string;
  notetaker_id?: string | null;
  participants?: MeetingParticipant[];
  external_participants?: MeetingExternalParticipant[];
}

export interface MeetingRecord extends MeetingSummary {
  meeting_type: string;
  start_time: string | null;
  end_time: string | null;
  location: string | null;
  created_by_id: string;
  created_at: string;
  updated_at: string;
  participants: MeetingParticipant[];
  external_participants: MeetingExternalParticipant[];
}

export interface MeetingCreateInput {
  meeting_number: string;
  title: string;
  meeting_type: string;
  meeting_date: string;
  start_time: string | null;
  end_time: string | null;
  location: string | null;
  notetaker_id: string | null;
}

export interface AgendaCreateInput {
  expected_version?: number;
  title: string;
  agenda_description: string | null;
  pic_suggestion: string | null;
  supporting_pic_suggestion: string | null;
  duration_minutes: number | null;
}

export interface AgendaUpdateInput extends Omit<AgendaCreateInput, 'expected_version'> {
  expected_version: number;
}

export interface MeetingParticipantCreateInput {
  expected_version: number;
  user_id: string;
}

export interface MeetingExternalParticipantCreateInput {
  expected_version: number;
  participant_name: string;
}

export interface MeetingMetadataUpdateInput {
  expected_version: number;
  meeting_number?: string;
  title?: string;
  meeting_type?: string;
  meeting_date?: string;
  start_time?: string | null;
  end_time?: string | null;
  location?: string | null;
}

export interface MinutesDecision {
  id: string;
  discussion_id: string;
  decision_number: number;
  decision_text: string;
  pic_suggestion?: string | null;
  output_expected: string | null;
  target_date: string | null;
  target_text: string | null;
  is_action_item: boolean;
}

export interface MinutesDiscussion {
  id: string;
  agenda_id: string;
  discussion_number: number;
  subject: string | null;
  content: string;
  decisions: MinutesDecision[];
}

export interface MinutesRevision {
  id: string;
  meeting_id: string;
  revision_number: number;
  format_version: 1 | 2;
  content: string | null;
  discussions: MinutesDiscussion[];
  created_by_id: string;
  created_at: string;
}

export type MinutesReviewResult = 'VALID' | 'INVALID';

export interface MinutesReview {
  id: string;
  meeting_id: string;
  minutes_revision_id: string | null;
  reviewer_user_id: string;
  review_number: number;
  result: MinutesReviewResult;
  review_note: string | null;
  reviewed_at: string;
}

export interface MinutesReviewCreateInput {
  minutes_revision_id: string;
  result: MinutesReviewResult;
  review_note: string | null;
}

export interface DecisionBriefDecision {
  decision_id: string;
  source_decision_text: string;
  source_agenda_id: string;
  source_agenda_title: string;
  source_discussion_id: string;
  source_discussion_subject: string | null;
  brief_text: string | null;
  priority: string;
  editorial_note: string | null;
  position: number;
}

export type DecisionBriefApprovalState =
  'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'WITHDRAWN';

export interface DecisionBriefApprovalEvent {
  id: string;
  event_number: number;
  event_type: 'SUBMITTED' | 'WITHDRAWN' | 'APPROVED' | 'REJECTED';
  actor_user_id: string;
  actor_roles: string[];
  reason: string | null;
  correlation_id: string | null;
  occurred_at: string;
}

export interface DecisionBriefVersion {
  id: string;
  meeting_id: string;
  source_minutes_revision_id: string;
  version_number: number;
  summary: string;
  notes: string | null;
  created_by_id: string;
  created_at: string;
  is_stale: boolean;
  approval_state: DecisionBriefApprovalState;
  approval_events: DecisionBriefApprovalEvent[];
  decisions: DecisionBriefDecision[];
}

export interface DecisionBriefVersionInput {
  source_minutes_revision_id: string;
  summary: string;
  notes: string | null;
  decisions: {
    decision_id: string;
    brief_text: string;
    priority: string;
    editorial_note: string | null;
  }[];
}

export interface StructuredMinutesDiscussionInput {
  agenda_id: string;
  subject: string | null;
  content: string;
  decisions: {
    decision_text: string;
    pic_suggestion?: string | null;
    output_expected: string | null;
    target_date: string | null;
    target_text: string | null;
    is_action_item: boolean;
  }[];
}

export interface StructuredMinutesRevisionInput {
  format_version: 2;
  content: null;
  discussions: StructuredMinutesDiscussionInput[];
}

export function canAccessMinutes(user: AuthenticatedUser): boolean {
  const restrictedRoles = new Set(['PIC', 'SUPER_ADMIN']);
  const meetingRoles = new Set(['SEKRETARIAT', 'MANAGER_LEGAL', 'REKTOR', 'WAREK']);
  return (
    !user.roles.some((role) => restrictedRoles.has(role)) &&
    user.roles.some((role) => meetingRoles.has(role))
  );
}

export function canCreateDecisionBrief(user: AuthenticatedUser): boolean {
  const restrictedRoles = new Set(['PIC', 'SUPER_ADMIN']);
  const authorRoles = new Set(['SEKRETARIAT', 'MANAGER_LEGAL', 'WAREK']);
  return (
    !user.roles.some((role) => restrictedRoles.has(role)) &&
    user.roles.some((role) => authorRoles.has(role))
  );
}

export function canReviewDecisionBrief(user: AuthenticatedUser): boolean {
  const restrictedRoles = new Set(['PIC', 'SUPER_ADMIN']);
  const reviewerRoles = new Set(['SEKRETARIAT', 'MANAGER_LEGAL', 'REKTOR', 'WAREK']);
  return (
    !user.roles.some((role) => restrictedRoles.has(role)) &&
    user.roles.some((role) => reviewerRoles.has(role))
  );
}

export function canManageDispositions(user: AuthenticatedUser): boolean {
  const restrictedRoles = new Set(['PIC', 'SUPER_ADMIN']);
  const managerRoles = new Set(['SEKRETARIAT', 'MANAGER_LEGAL', 'REKTOR', 'WAREK']);
  return (
    !user.roles.some((role) => restrictedRoles.has(role)) &&
    user.roles.some((role) => managerRoles.has(role))
  );
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export const SESSION_EXPIRED_EVENT = 'sitara:session-expired';

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  const cookie = document.cookie.split('; ').find((item) => item.startsWith(prefix));
  if (!cookie) return null;
  return decodeURIComponent(cookie.slice(prefix.length));
}

function validationMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'object' && item !== null && 'msg' in item) {
          return String(item.msg);
        }
        return null;
      })
      .filter((item): item is string => item !== null);
    return messages.length > 0 ? messages.join(' · ') : null;
  }
  return null;
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  if (init.method && init.method !== 'GET' && path !== '/api/v1/auth/login') {
    const csrfToken = readCookie('sitara_csrf');
    if (!csrfToken) {
      throw new ApiError('Token keamanan CSRF tidak tersedia. Silakan login kembali.', 403);
    }
    headers.set('X-CSRF-Token', csrfToken);
  }

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers,
      credentials: 'include',
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'TimeoutError') {
      throw new ApiError('Permintaan ke server melewati batas waktu. Coba lagi.', 0);
    }
    throw new ApiError(
      'Tidak dapat terhubung ke server SITARA. Periksa koneksi lalu coba lagi.',
      0,
    );
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/v1/auth/login' && path !== '/api/v1/auth/me') {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    const detail =
      typeof payload === 'object' && payload !== null && 'detail' in payload
        ? validationMessage(payload.detail)
        : null;
    throw new ApiError(detail ?? `Permintaan gagal (HTTP ${response.status}).`, response.status);
  }
  return payload as T;
}

function isAuthenticatedUser(payload: unknown): payload is AuthenticatedUser {
  if (typeof payload !== 'object' || payload === null) return false;
  return (
    'id' in payload &&
    typeof payload.id === 'string' &&
    'email' in payload &&
    typeof payload.email === 'string' &&
    'full_name' in payload &&
    typeof payload.full_name === 'string' &&
    'roles' in payload &&
    Array.isArray(payload.roles) &&
    payload.roles.every((role) => typeof role === 'string')
  );
}

async function requestAuthenticatedUser(
  path: string,
  init?: RequestInit,
): Promise<AuthenticatedUser> {
  const payload = await requestJson<unknown>(path, init);
  if (!isAuthenticatedUser(payload)) {
    throw new ApiError('Respons autentikasi server tidak valid.', 502);
  }
  return payload;
}

export function getCurrentUser(): Promise<AuthenticatedUser> {
  return requestAuthenticatedUser('/api/v1/auth/me');
}

export function login(email: string, password: string): Promise<AuthenticatedUser> {
  return requestAuthenticatedUser('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<void> {
  return requestJson<void>('/api/v1/auth/logout', { method: 'POST' });
}

export async function getActionItems(
  includeDeleted = false,
  meetingId?: string,
): Promise<ActionItemSummary[]> {
  const allItems: ActionItemSummary[] = [];
  const pageSize = 100;
  let offset = 0;

  while (true) {
    const query = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
    if (includeDeleted) query.set('include_deleted', 'true');
    if (meetingId) query.set('meeting_id', meetingId);
    const page = await requestJson<ActionItemSummary[]>(`/api/v1/action-items?${query.toString()}`);
    allItems.push(...page);
    if (page.length < pageSize) return allItems;
    offset += page.length;
  }
}

export function getActionItem(actionItemId: string): Promise<ActionItemDetail> {
  return requestJson<ActionItemDetail>(`/api/v1/action-items/${encodeURIComponent(actionItemId)}`);
}

export function getNotifications(): Promise<NotificationPage> {
  return requestJson<NotificationPage>('/api/v1/notifications?limit=50');
}

export function markNotificationRead(notificationId: string): Promise<NotificationRecord> {
  return requestJson<NotificationRecord>(
    `/api/v1/notifications/${encodeURIComponent(notificationId)}/read`,
    { method: 'POST' },
  );
}

export function searchAssignablePics(
  meetingId: string,
  query: string,
): Promise<AssignablePicDirectory> {
  return requestJson<AssignablePicDirectory>(
    `/api/v1/action-items/pic-directory?meeting_id=${encodeURIComponent(meetingId)}&query=${encodeURIComponent(query)}&limit=100`,
  );
}

export function getActionItemUnits(meetingId: string): Promise<OrganizationUnitDirectory> {
  return requestJson<OrganizationUnitDirectory>(
    `/api/v1/action-items/units?meeting_id=${encodeURIComponent(meetingId)}`,
  );
}

export function createActionItem(data: ActionItemCreateInput): Promise<ActionItemDetail> {
  return requestJson<ActionItemDetail>('/api/v1/action-items', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function updateActionItem(
  actionItemId: string,
  data: ActionItemUpdateInput,
): Promise<ActionItemSummary> {
  return requestJson<ActionItemSummary>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(data),
    },
  );
}

export function deleteActionItem(
  actionItemId: string,
  expectedVersion: number,
): Promise<ActionItemSummary> {
  return requestJson<ActionItemSummary>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}?expected_version=${expectedVersion}`,
    { method: 'DELETE' },
  );
}

export async function getMeetingDispositions(meetingId: string): Promise<Disposition[]> {
  const dispositions: Disposition[] = [];
  const pageSize = 100;
  let offset = 0;
  while (true) {
    const page = await requestJson<Disposition[]>(
      `/api/v1/meetings/${encodeURIComponent(meetingId)}/dispositions?limit=${pageSize}&offset=${offset}`,
    );
    dispositions.push(...page);
    if (page.length < pageSize) return dispositions;
    offset += page.length;
  }
}

export function searchDispositionTargets(
  meetingId: string,
  query: string,
): Promise<DispositionTargetDirectory> {
  return requestJson<DispositionTargetDirectory>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/disposition-targets?query=${encodeURIComponent(query)}&limit=100`,
  );
}

export function createMeetingDisposition(
  meetingId: string,
  data: DispositionCreateInput,
): Promise<Disposition> {
  return requestJson<Disposition>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/dispositions`,
    { method: 'POST', body: JSON.stringify(data) },
  );
}

export function createActionItemAssignment(
  actionItemId: string,
  data: ActionItemAssignmentCreateInput,
): Promise<ActionItemAssignment> {
  return requestJson<ActionItemAssignment>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/assignments`,
    { method: 'POST', body: JSON.stringify(data) },
  );
}

export function endActionItemAssignment(
  actionItemId: string,
  assignmentId: string,
  data: ActionItemAssignmentEndInput,
): Promise<ActionItemAssignment> {
  return requestJson<ActionItemAssignment>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/assignments/${encodeURIComponent(assignmentId)}/end`,
    { method: 'POST', body: JSON.stringify(data) },
  );
}

export function createActionItemProgressUpdate(
  actionItemId: string,
  data: ActionItemProgressUpdateInput,
): Promise<ActionItemProgressUpdate> {
  return requestJson<ActionItemProgressUpdate>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/progress-updates`,
    { method: 'POST', body: JSON.stringify(data) },
  );
}

export function uploadActionItemEvidenceFile(
  actionItemId: string,
  progressUpdateId: string,
  file: File,
): Promise<ActionItemEvidence> {
  const form = new FormData();
  form.append('file', file);
  return requestJson<ActionItemEvidence>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/progress-updates/` +
      `${encodeURIComponent(progressUpdateId)}/evidence/files`,
    { method: 'POST', body: form },
  );
}

export function reviewActionItemCompletion(
  actionItemId: string,
  data: ActionItemCompletionVerificationInput,
): Promise<ActionItemDetail> {
  return requestJson<ActionItemDetail>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/completion-verifications`,
    { method: 'POST', body: JSON.stringify(data) },
  );
}

export function changeActionItemStatus(
  actionItemId: string,
  data: ActionItemStatusChangeInput,
): Promise<ActionItemSummary> {
  return requestJson<ActionItemSummary>(
    `/api/v1/action-items/${encodeURIComponent(actionItemId)}/status`,
    { method: 'PATCH', body: JSON.stringify(data) },
  );
}

export async function getMeetings(query = ''): Promise<MeetingSummary[]> {
  const allMeetings: MeetingSummary[] = [];
  const pageSize = 100;
  let offset = 0;

  while (true) {
    const page = await getMeetingsPage(pageSize, offset, query);
    allMeetings.push(...page);
    if (page.length < pageSize) return allMeetings;
    offset += page.length;
  }
}

export function getMeetingsPage(
  limit: number,
  offset: number,
  query = '',
): Promise<MeetingSummary[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (query.trim()) params.set('query', query.trim());
  return requestJson<MeetingSummary[]>(`/api/v1/meetings?${params.toString()}`);
}

export function getMeetingParticipantOptions(): Promise<MeetingParticipantOption[]> {
  return requestJson<MeetingParticipantOption[]>('/api/v1/meetings/participant-options');
}

export function createMeeting(data: MeetingCreateInput): Promise<MeetingRecord> {
  return requestJson<MeetingRecord>('/api/v1/meetings', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function getMeeting(meetingId: string): Promise<MeetingRecord> {
  return requestJson<MeetingRecord>(`/api/v1/meetings/${encodeURIComponent(meetingId)}`);
}

export function updateMeetingMetadata(
  meetingId: string,
  data: MeetingMetadataUpdateInput,
): Promise<MeetingRecord> {
  return requestJson<MeetingRecord>(`/api/v1/meetings/${encodeURIComponent(meetingId)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export function transitionMeeting(
  meetingId: string,
  toStatus: MeetingStatus,
): Promise<MeetingRecord> {
  return requestJson<MeetingRecord>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/transition`,
    {
      method: 'POST',
      body: JSON.stringify({ to_status: toStatus }),
    },
  );
}

export function createAgenda(meetingId: string, data: AgendaCreateInput): Promise<MeetingAgenda> {
  return requestJson<MeetingAgenda>(`/api/v1/meetings/${encodeURIComponent(meetingId)}/agendas`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function updateAgenda(
  meetingId: string,
  agendaId: string,
  data: AgendaUpdateInput,
): Promise<MeetingAgenda> {
  return requestJson<MeetingAgenda>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/agendas/${encodeURIComponent(agendaId)}`,
    { method: 'PUT', body: JSON.stringify(data) },
  );
}

export async function deleteAgenda(
  meetingId: string,
  agendaId: string,
  expectedVersion: number,
): Promise<void> {
  await requestJson<null>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/agendas/${encodeURIComponent(agendaId)}` +
      `?expected_version=${expectedVersion}`,
    { method: 'DELETE' },
  );
}

export function addMeetingParticipant(
  meetingId: string,
  data: MeetingParticipantCreateInput,
): Promise<MeetingParticipant> {
  return requestJson<MeetingParticipant>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/participants`,
    { method: 'POST', body: JSON.stringify(data) },
  );
}

export function addExternalMeetingParticipant(
  meetingId: string,
  data: MeetingExternalParticipantCreateInput,
): Promise<MeetingExternalParticipant> {
  return requestJson<MeetingExternalParticipant>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/participants/external`,
    { method: 'POST', body: JSON.stringify(data) },
  );
}

export async function deleteMeetingParticipant(
  meetingId: string,
  participantUserId: string,
  expectedVersion: number,
): Promise<void> {
  await requestJson<null>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/participants/` +
      `${encodeURIComponent(participantUserId)}?expected_version=${expectedVersion}`,
    { method: 'DELETE' },
  );
}

export async function deleteExternalMeetingParticipant(
  meetingId: string,
  externalParticipantId: string,
  expectedVersion: number,
): Promise<void> {
  await requestJson<null>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/participants/external/` +
      `${encodeURIComponent(externalParticipantId)}?expected_version=${expectedVersion}`,
    { method: 'DELETE' },
  );
}

export function getMinutesRevisions(meetingId: string): Promise<MinutesRevision[]> {
  return requestJson<MinutesRevision[]>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/minutes-revisions`,
  );
}

export function getMinutesReviews(meetingId: string): Promise<MinutesReview[]> {
  return requestJson<MinutesReview[]>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/minutes-reviews`,
  );
}

export function createMinutesReview(
  meetingId: string,
  data: MinutesReviewCreateInput,
): Promise<MinutesReview> {
  return requestJson<MinutesReview>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/minutes-reviews`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    },
  );
}

export function createMinutesRevision(
  meetingId: string,
  snapshot: string | StructuredMinutesRevisionInput,
  baseRevisionId: string | null,
): Promise<MinutesRevision> {
  const body =
    typeof snapshot === 'string'
      ? { content: snapshot, base_revision_id: baseRevisionId }
      : { ...snapshot, base_revision_id: baseRevisionId };
  return requestJson<MinutesRevision>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/minutes-revisions`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  );
}

export function getDecisionBriefHistory(meetingId: string): Promise<DecisionBriefVersion[]> {
  return requestJson<DecisionBriefVersion[]>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/decision-briefs`,
  );
}

export function createDecisionBriefVersion(
  meetingId: string,
  input: DecisionBriefVersionInput,
): Promise<DecisionBriefVersion> {
  return requestJson<DecisionBriefVersion>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/decision-briefs`,
    { method: 'POST', body: JSON.stringify(input) },
  );
}

export function submitDecisionBriefVersion(
  meetingId: string,
  briefVersionId: string,
): Promise<DecisionBriefVersion> {
  return requestJson<DecisionBriefVersion>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/decision-briefs/${encodeURIComponent(briefVersionId)}/submit`,
    { method: 'POST' },
  );
}

export function approveDecisionBriefVersion(
  meetingId: string,
  briefVersionId: string,
): Promise<DecisionBriefVersion> {
  return requestJson<DecisionBriefVersion>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/decision-briefs/${encodeURIComponent(briefVersionId)}/approve`,
    { method: 'POST' },
  );
}

export function rejectDecisionBriefVersion(
  meetingId: string,
  briefVersionId: string,
  reason: string,
): Promise<DecisionBriefVersion> {
  return requestJson<DecisionBriefVersion>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/decision-briefs/${encodeURIComponent(briefVersionId)}/reject`,
    { method: 'POST', body: JSON.stringify({ reason }) },
  );
}

export function withdrawDecisionBriefVersion(
  meetingId: string,
  briefVersionId: string,
): Promise<DecisionBriefVersion> {
  return requestJson<DecisionBriefVersion>(
    `/api/v1/meetings/${encodeURIComponent(meetingId)}/decision-briefs/${encodeURIComponent(briefVersionId)}/withdraw`,
    { method: 'POST' },
  );
}
