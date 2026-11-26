import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  getActionItem,
  getActionItems,
  getMeetings,
  type ActionItemStatus,
  type ActionItemDetail,
  type ActionItemSummary,
  type AuthenticatedUser,
  type MeetingSummary,
} from './api';
import { isOperationalActionItem } from './actionItemVisibility';

type DashboardData = {
  meetings: MeetingSummary[] | null;
  actionItems: ActionItemSummary[];
};

type DashboardCalendarEvent = {
  id: string;
  date: string;
  kind: 'Rapat' | 'Tenggat';
  title: string;
  href: string;
};

const actionStatuses: ActionItemStatus[] = [
  'BELUM_DIMULAI',
  'BERPROSES',
  'TERKENDALA',
  'MENUNGGU_ACC',
  'SELESAI',
];

const actionStatusLabels: Record<ActionItemStatus, string> = {
  BELUM_DIMULAI: 'Belum dimulai',
  BERPROSES: 'Berproses',
  TERKENDALA: 'Terkendala',
  MENUNGGU_ACC: 'Menunggu ACC',
  SELESAI: 'Selesai',
};

function dashboardTitle(user: AuthenticatedUser): string {
  if (user.roles.includes('SUPER_ADMIN')) return 'Ringkasan administrasi';
  if (user.roles.includes('PIC')) return 'Ringkasan tugas saya';
  if (user.roles.includes('REKTOR')) return 'Ringkasan strategis';
  if (user.roles.includes('WAREK')) return 'Tugas dan keputusan dalam cakupan';
  return 'Beranda Rapim';
}

function dashboardDescription(user: AuthenticatedUser): string {
  if (user.roles.includes('SUPER_ADMIN')) {
    return 'Informasi administrasi sistem mengikuti kewenangan yang tersedia.';
  }
  if (user.roles.includes('PIC')) {
    return 'Pantau tugas dan tenggat yang memerlukan perhatian Anda.';
  }
  if (user.roles.includes('REKTOR')) {
    return 'Pantau perkembangan Rapim dan tindak lanjut sesuai akses Anda.';
  }
  if (user.roles.includes('WAREK')) {
    return 'Akses rapat, keputusan, dan tindak lanjut dalam cakupan Anda.';
  }
  return 'Kelola Rapim dan pantau tindak lanjut dalam satu ringkasan.';
}

function canReadMeetings(user: AuthenticatedUser): boolean {
  return (
    !user.roles.includes('SUPER_ADMIN') &&
    !user.roles.includes('PIC') &&
    user.roles.some((role) => ['SEKRETARIAT', 'MANAGER_LEGAL', 'REKTOR', 'WAREK'].includes(role))
  );
}

function canCreateMeetings(user: AuthenticatedUser): boolean {
  return (
    !user.roles.includes('SUPER_ADMIN') &&
    !user.roles.includes('PIC') &&
    user.roles.some((role) => ['SEKRETARIAT', 'MANAGER_LEGAL', 'WAREK'].includes(role))
  );
}

function localDateKey(date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatDate(value: string | null): string {
  if (!value) return 'Belum ditentukan';
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return 'Tanggal tidak valid';
  return new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(date);
}

function monthLabel(value: string): string {
  const date = new Date(`${value}-01T00:00:00`);
  return new Intl.DateTimeFormat('id-ID', { month: 'long', year: 'numeric' }).format(date);
}

function daysUntilDue(dueDate: string, today: string): number {
  return Math.floor(
    (Date.parse(`${dueDate.slice(0, 10)}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) /
      86_400_000,
  );
}

async function loadDashboard(user: AuthenticatedUser): Promise<DashboardData> {
  if (user.roles.includes('SUPER_ADMIN')) {
    return { meetings: null, actionItems: [] };
  }

  const [meetings, actionItems] = await Promise.all([
    canReadMeetings(user) ? getMeetings() : Promise.resolve(null),
    getActionItems(),
  ]);
  return { meetings, actionItems };
}

function Dashboard({ authenticatedUser }: { authenticatedUser: AuthenticatedUser }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selectedMonth, setSelectedMonth] = useState('SEMUA');
  const [calendarMonth, setCalendarMonth] = useState(() => localDateKey().slice(0, 7));
  const [selectedStatus, setSelectedStatus] = useState<ActionItemStatus | 'SEMUA'>('SEMUA');
  const [showAllActionItems, setShowAllActionItems] = useState(false);
  const [selectedActionItemId, setSelectedActionItemId] = useState('');
  const [selectedActionItemDetail, setSelectedActionItemDetail] = useState<ActionItemDetail | null>(
    null,
  );
  const [actionItemDetailLoading, setActionItemDetailLoading] = useState(false);
  const [actionItemDetailError, setActionItemDetailError] = useState<string | null>(null);
  const [actionItemDetailRetry, setActionItemDetailRetry] = useState(0);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await loadDashboard(authenticatedUser);
      setData(result);
    } catch (loadError) {
      setData(null);
      setError(
        loadError instanceof ApiError
          ? 'Data dashboard tidak dapat dimuat. Coba lagi.'
          : 'Terjadi kesalahan saat memuat dashboard. Coba lagi.',
      );
    } finally {
      setLoading(false);
    }
  }, [authenticatedUser]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedActionItemId) {
      setSelectedActionItemDetail(null);
      setActionItemDetailError(null);
      setActionItemDetailLoading(false);
      return;
    }
    let current = true;
    setActionItemDetailLoading(true);
    setActionItemDetailError(null);
    void getActionItem(selectedActionItemId)
      .then((detail) => {
        if (current) setSelectedActionItemDetail(detail);
      })
      .catch(() => {
        if (current) {
          setSelectedActionItemDetail(null);
          setActionItemDetailError('Detail tindak lanjut tidak dapat dimuat. Coba lagi.');
        }
      })
      .finally(() => {
        if (current) setActionItemDetailLoading(false);
      });
    return () => {
      current = false;
    };
  }, [actionItemDetailRetry, selectedActionItemId]);

  useEffect(() => {
    if (!selectedActionItemId) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelectedActionItemId('');
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [selectedActionItemId]);

  if (loading) {
    return (
      <div className="dashboard-content">
        <p className="dashboard-state" role="status">
          Memuat data dashboard...
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard-content">
        <div className="dashboard-error" role="alert">
          <span>{error}</span>
          <button type="button" className="dashboard-retry" onClick={() => void refresh()}>
            Coba lagi
          </button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const today = localDateKey();
  const meetingById = new Map<string, MeetingSummary>(
    (data.meetings ?? []).map((meeting) => [meeting.id, meeting]),
  );
  const availableMonths = [
    ...new Set((data.meetings ?? []).map((meeting) => meeting.meeting_date.slice(0, 7))),
  ].sort((left, right) => right.localeCompare(left));
  const normalizedSearch = search.trim().toLocaleLowerCase('id-ID');
  const matchingItems = data.actionItems
    .filter(isOperationalActionItem)
    .filter((item) => {
      const meeting = meetingById.get(item.meeting_id);
      const monthMatches =
        selectedMonth === 'SEMUA' || meeting?.meeting_date.slice(0, 7) === selectedMonth;
      const searchableText = [
        item.title,
        item.description,
        item.output_expected ?? '',
        meeting?.meeting_number ?? '',
        meeting?.title ?? '',
        ...(meeting?.agendas.map((agenda) => agenda.title) ?? []),
      ]
        .join(' ')
        .toLocaleLowerCase('id-ID');
      return monthMatches && (!normalizedSearch || searchableText.includes(normalizedSearch));
    })
    .sort((left, right) => {
      const leftDate = meetingById.get(left.meeting_id)?.meeting_date ?? '';
      const rightDate = meetingById.get(right.meeting_id)?.meeting_date ?? '';
      return (
        rightDate.localeCompare(leftDate) ||
        (left.due_date ?? '9999').localeCompare(right.due_date ?? '9999')
      );
    });
  const visibleItems = matchingItems.filter(
    (item) => selectedStatus === 'SEMUA' || item.official_status === selectedStatus,
  );
  const visibleMeetings =
    data.meetings
      ?.filter(
        (meeting) =>
          selectedMonth === 'SEMUA' || meeting.meeting_date.slice(0, 7) === selectedMonth,
      )
      .slice()
      .sort((left, right) => right.meeting_date.localeCompare(left.meeting_date)) ?? null;
  const calendarEvents: DashboardCalendarEvent[] = [
    ...(data.meetings ?? [])
      .filter((meeting) => meeting.meeting_date.slice(0, 7) === calendarMonth)
      .map((meeting) => ({
        id: `meeting-${meeting.id}`,
        date: meeting.meeting_date,
        kind: 'Rapat' as const,
        title: authenticatedUser.roles.includes('REKTOR') ? 'Rapim terjadwal' : meeting.title,
        href: `#meetings/${encodeURIComponent(meeting.id)}`,
      })),
    ...data.actionItems
      .filter(
        (item) => isOperationalActionItem(item) && item.due_date?.slice(0, 7) === calendarMonth,
      )
      .map((item) => ({
        id: `deadline-${item.id}`,
        date: item.due_date!,
        kind: 'Tenggat' as const,
        title: item.title,
        href: `#action-items/${encodeURIComponent(item.id)}`,
      })),
  ].sort(
    (left, right) =>
      left.date.localeCompare(right.date) ||
      left.kind.localeCompare(right.kind, 'id-ID') ||
      left.title.localeCompare(right.title, 'id-ID'),
  );
  const superAdmin = authenticatedUser.roles.includes('SUPER_ADMIN');
  const canShowMeetingDetails = canReadMeetings(authenticatedUser);
  const visibleActionCounts = Object.fromEntries(
    actionStatuses.map((status) => [
      status,
      matchingItems.filter((item) => item.official_status === status).length,
    ]),
  ) as Record<ActionItemStatus, number>;
  const attentionCount = visibleActionCounts.TERKENDALA + visibleActionCounts.MENUNGGU_ACC;
  const displayedItems = showAllActionItems ? visibleItems : visibleItems.slice(0, 5);
  const selectedActionItem = data.actionItems.find((item) => item.id === selectedActionItemId);
  const selectedActionMeeting = selectedActionItem
    ? meetingById.get(selectedActionItem.meeting_id)
    : null;
  const selectedMainPic = selectedActionItemDetail?.active_assignments.find(
    (assignment) => assignment.assignment_role === 'MAIN',
  );
  const selectedSupportingPics =
    selectedActionItemDetail?.active_assignments.filter(
      (assignment) => assignment.assignment_role === 'SUPPORTING',
    ) ?? [];
  const orderedProgressUpdates = [...(selectedActionItemDetail?.progress_updates ?? [])].sort(
    (left, right) => Date.parse(right.submitted_at) - Date.parse(left.submitted_at),
  );
  const picDeadlineItems = authenticatedUser.roles.includes('PIC')
    ? data.actionItems
        .filter(
          (item) =>
            isOperationalActionItem(item) &&
            item.due_date !== null &&
            item.active_assignments.some(
              (assignment) => assignment.assignee_user_id === authenticatedUser.id,
            ) &&
            daysUntilDue(item.due_date, today) <= 7,
        )
        .sort((left, right) => (left.due_date ?? '9999').localeCompare(right.due_date ?? '9999'))
    : [];

  return (
    <div className="dashboard-content dashboard-page">
      <div
        className={`dashboard-hero${canCreateMeetings(authenticatedUser) ? ' dashboard-hero--actions' : ''}`}
      >
        <section className="page-heading" aria-labelledby="page-title">
          <div>
            <p className="eyebrow">RUANG KERJA RAPIM</p>
            <h1 id="page-title">{dashboardTitle(authenticatedUser)}</h1>
            <p className="page-description">{dashboardDescription(authenticatedUser)}</p>
          </div>
          <time className="dashboard-today" dateTime={today}>
            {new Intl.DateTimeFormat('id-ID', {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
              year: 'numeric',
            }).format(new Date(`${today}T00:00:00`))}
          </time>
        </section>

        {canCreateMeetings(authenticatedUser) && (
          <section className="surface-panel dashboard-quick-actions" aria-label="Aksi Rapim">
            <div className="dashboard-quick-copy">
              <p className="section-kicker">AKSI CEPAT</p>
              <h2>Mulai pekerjaan Rapim</h2>
            </div>
            <div className="meeting-form-actions">
              <a className="primary-button" href="#meetings/create">
                Buat rapat
              </a>
              <a className="secondary-button" href="#meetings">
                Pilih rapat untuk tambah agenda
              </a>
            </div>
          </section>
        )}
      </div>

      {picDeadlineItems.length > 0 && (
        <section className="surface-panel pic-deadline-notice" aria-labelledby="pic-deadline-title">
          <div>
            <p className="section-kicker">PENGINGAT TENGGAT</p>
            <h2 id="pic-deadline-title">Tugas yang perlu diperhatikan</h2>
            <p>Daftar ini menampilkan tugas lewat tenggat atau jatuh tempo dalam tujuh hari.</p>
          </div>
          <ul>
            {picDeadlineItems.slice(0, 5).map((item) => {
              const days = daysUntilDue(item.due_date!, today);
              const reminder =
                days < 0
                  ? `Lewat tenggat ${Math.abs(days)} hari`
                  : days === 0
                    ? 'Tenggat hari ini'
                    : `Tenggat ${days} hari lagi`;
              return (
                <li key={item.id}>
                  <a href={`#action-items/${encodeURIComponent(item.id)}`}>{item.title}</a>
                  <span>
                    {reminder} · {formatDate(item.due_date)}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {superAdmin ? (
        <div className="dashboard-gap" role="status">
          Ringkasan administratif belum tersedia melalui API. Super Admin tidak otomatis memiliki
          akses ke data operasional Sekretariat.
        </div>
      ) : (
        <>
          <section className="metric-grid" aria-label="Ringkasan aktivitas">
            {data.meetings && (
              <Metric
                label="Rapim tercatat"
                value={visibleMeetings?.length ?? 0}
                detail="Sesuai bulan yang dipilih"
              />
            )}
            <Metric
              label="Tugas terpantau"
              value={visibleItems.length}
              detail="Dalam cakupan dan filter aktif"
            />
            <Metric
              label="Perlu perhatian"
              value={attentionCount}
              detail="Terkendala atau menunggu ACC"
            />
          </section>

          <div className="dashboard-insights-grid">
            <section
              className="surface-panel dashboard-calendar"
              aria-label="Kalender Rapim dan tenggat tugas"
            >
              <div className="section-heading">
                <div>
                  <p className="section-kicker">AGENDA</p>
                  <h2>Rapat dan tenggat tugas</h2>
                </div>
                <label>
                  <span>Bulan kalender</span>
                  <input
                    type="month"
                    value={calendarMonth}
                    onChange={(event) => setCalendarMonth(event.target.value)}
                  />
                </label>
              </div>
              {calendarEvents.length === 0 ? (
                <p className="dashboard-empty">Belum ada rapat atau tenggat pada bulan ini.</p>
              ) : (
                <ol className="dashboard-calendar-list">
                  {calendarEvents.map((event) => (
                    <li key={event.id}>
                      <time dateTime={event.date}>{formatDate(event.date)}</time>
                      <a href={event.href} aria-label={`${event.kind} · ${event.title}`}>
                        <span>{event.kind}</span>
                        <strong>{event.title}</strong>
                      </a>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section
              className="surface-panel live-status-panel"
              aria-labelledby="action-summary-title"
            >
              <div className="section-heading">
                <div>
                  <p className="section-kicker">TINDAK LANJUT</p>
                  <h2 id="action-summary-title">Status tugas</h2>
                </div>
                <span className="dashboard-status-hint">Pilih status untuk menyaring</span>
              </div>
              <div className="live-status-grid">
                {actionStatuses.map((status) => (
                  <button
                    className={`live-status-card live-status-card--${status.toLowerCase()}`}
                    key={status}
                    type="button"
                    aria-pressed={selectedStatus === status}
                    onClick={() =>
                      setSelectedStatus((current) => (current === status ? 'SEMUA' : status))
                    }
                  >
                    <span>{actionStatusLabels[status]}</span>
                    <strong>{visibleActionCounts[status]}</strong>
                  </button>
                ))}
              </div>
            </section>
          </div>

          <section
            className="surface-panel live-tasks-panel"
            id="action-items"
            aria-labelledby="tasks-title"
          >
            <div className="section-heading">
              <div>
                <p className="section-kicker">
                  {authenticatedUser.roles.includes('PIC') ? 'TUGAS SAYA' : 'MONITORING'}
                </p>
                <h2 id="tasks-title">Tindak lanjut lintas Rapim</h2>
              </div>
            </div>
            <div className="rapim-filter-bar" aria-label="Filter tindak lanjut">
              <label>
                <span>Cari rapat atau tindak lanjut</span>
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Ketik kata kunci"
                />
              </label>
              {availableMonths.length > 0 && (
                <label>
                  <span>Bulan Rapim</span>
                  <select
                    value={selectedMonth}
                    onChange={(event) => setSelectedMonth(event.target.value)}
                  >
                    <option value="SEMUA">Semua bulan</option>
                    {availableMonths.map((month) => (
                      <option value={month} key={month}>
                        {monthLabel(month)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                <span>Status tindak lanjut</span>
                <select
                  value={selectedStatus}
                  onChange={(event) =>
                    setSelectedStatus(event.target.value as ActionItemStatus | 'SEMUA')
                  }
                >
                  <option value="SEMUA">Semua status</option>
                  {actionStatuses.map((status) => (
                    <option value={status} key={status}>
                      {actionStatusLabels[status]}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {visibleItems.length === 0 ? (
              <p className="dashboard-empty">
                {data.actionItems.length === 0
                  ? 'Belum ada Action Item dalam cakupan akses Anda.'
                  : 'Tidak ada tindak lanjut yang cocok dengan filter ini.'}
              </p>
            ) : (
              <div className="rapim-action-list">
                {displayedItems.map((item) => {
                  const mainPic = item.active_assignments.find(
                    (assignment) => assignment.assignment_role === 'MAIN',
                  );
                  const mainPicName = mainPic
                    ? mainPic.assignee_display_name?.trim() ||
                      mainPic.assignee_name?.trim() ||
                      (mainPic.assignee_user_id === authenticatedUser.id
                        ? 'Anda'
                        : 'Nama belum tersedia')
                    : 'Belum ditugaskan';
                  return (
                    <article className="rapim-action-card" key={item.id}>
                      <button
                        className="rapim-action-summary"
                        type="button"
                        aria-label={`Lihat detail tindak lanjut: ${item.title}`}
                        onClick={() => {
                          setSelectedActionItemDetail(null);
                          setSelectedActionItemId(item.id);
                        }}
                      >
                        <span className="rapim-action-summary-heading">
                          <strong>{item.title}</strong>
                          <span
                            className={`status-pill status-pill--${item.official_status.toLowerCase()}`}
                          >
                            {actionStatusLabels[item.official_status]}
                          </span>
                        </span>
                        <span className="rapim-action-summary-pic">
                          <small>PIC utama</small>
                          <strong>{mainPicName}</strong>
                        </span>
                      </button>
                    </article>
                  );
                })}
              </div>
            )}
            {visibleItems.length > 5 && (
              <button
                className="text-button"
                type="button"
                aria-expanded={showAllActionItems}
                onClick={() => setShowAllActionItems((expanded) => !expanded)}
              >
                {showAllActionItems
                  ? 'Tampilkan lebih sedikit'
                  : `Lainnya (${visibleItems.length - 5})`}
              </button>
            )}
          </section>
        </>
      )}

      {selectedActionItemId && (
        <div
          className="action-item-modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setSelectedActionItemId('');
          }}
        >
          <section
            className="surface-panel action-item-detail action-item-detail--modal dashboard-action-detail-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Detail tindak lanjut"
          >
            <header className="action-item-detail-heading">
              <div>
                <p className="section-kicker">DETAIL TINDAK LANJUT</p>
                <h2>
                  {selectedActionItemDetail?.title ?? selectedActionItem?.title ?? 'Tindak lanjut'}
                </h2>
              </div>
              {selectedActionItem && (
                <span
                  className={`action-item-status action-item-status--${selectedActionItem.official_status.toLowerCase()}`}
                >
                  {actionStatusLabels[selectedActionItem.official_status]}
                </span>
              )}
              <button
                className="action-item-modal-close"
                type="button"
                onClick={() => setSelectedActionItemId('')}
              >
                Tutup detail
              </button>
            </header>
            {actionItemDetailLoading ? (
              <p className="dashboard-state" role="status">
                Memuat detail tindak lanjut...
              </p>
            ) : actionItemDetailError ? (
              <div className="meeting-error" role="alert">
                <span>{actionItemDetailError}</span>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => setActionItemDetailRetry((retry) => retry + 1)}
                >
                  Coba lagi
                </button>
              </div>
            ) : selectedActionItemDetail ? (
              <>
                <p className="action-item-description">{selectedActionItemDetail.description}</p>
                <dl className="action-item-modal-meta">
                  {canShowMeetingDetails && (
                    <div>
                      <dt>Rapim sumber</dt>
                      <dd>
                        {selectedActionMeeting
                          ? `${selectedActionMeeting.meeting_number} · ${selectedActionMeeting.title}`
                          : 'Rapat sumber tidak tersedia'}
                      </dd>
                    </div>
                  )}
                  <div>
                    <dt>PIC utama</dt>
                    <dd>
                      {selectedMainPic?.assignee_display_name?.trim() ||
                        selectedMainPic?.assignee_name?.trim() ||
                        (selectedMainPic?.assignee_user_id === authenticatedUser.id
                          ? 'Anda'
                          : 'Belum ditugaskan')}
                    </dd>
                  </div>
                  {selectedSupportingPics.length > 0 && (
                    <div>
                      <dt>PIC pendukung</dt>
                      <dd>
                        {selectedSupportingPics
                          .map(
                            (assignment) =>
                              assignment.assignee_display_name ||
                              assignment.assignee_name ||
                              'Belum ditentukan',
                          )
                          .join(', ')}
                      </dd>
                    </div>
                  )}
                  <div>
                    <dt>Output yang diharapkan</dt>
                    <dd>{selectedActionItemDetail.output_expected || 'Belum dicatat'}</dd>
                  </div>
                  <div>
                    <dt>Target penyelesaian</dt>
                    <dd>{formatDate(selectedActionItemDetail.due_date)}</dd>
                  </div>
                  <div>
                    <dt>Prioritas</dt>
                    <dd>{selectedActionItemDetail.priority}</dd>
                  </div>
                </dl>
                <section
                  className="action-item-subsection"
                  aria-labelledby="dashboard-progress-title"
                >
                  <h3 id="dashboard-progress-title">Riwayat progres</h3>
                  {orderedProgressUpdates.length ? (
                    <ol className="action-item-progress-list">
                      {orderedProgressUpdates.map((update) => (
                        <li key={update.id}>
                          <strong>{update.progress_percent}%</strong>
                          <span>{formatDate(update.submitted_at)}</span>
                          <p>{update.report_text}</p>
                          {update.blocker_text && (
                            <p>
                              <strong>Kendala:</strong> {update.blocker_text}
                            </p>
                          )}
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="dashboard-empty">Belum ada laporan progres.</p>
                  )}
                </section>
                <a
                  className="secondary-button dashboard-action-manage-link"
                  href={`#action-items/${encodeURIComponent(selectedActionItemDetail.id)}`}
                >
                  Buka menu tindak lanjut
                </a>
              </>
            ) : null}
          </section>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: number; detail: string }) {
  return (
    <div className="metric-item live-metric">
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
      <span className="metric-detail">{detail}</span>
    </div>
  );
}

export default Dashboard;
