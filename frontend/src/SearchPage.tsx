import { useEffect, useMemo, useState } from 'react';
import { getMeetings, type AuthenticatedUser, type MeetingSummary } from './api';
import RepositoryMeetingDetail from './RepositoryMeetingDetail';

type RepositoryScope = 'REPOSITORY' | 'SEMUA';

const meetingStatusLabels: Record<MeetingSummary['status'], string> = {
  DRAFT: 'Draf',
  LIVE: 'Berlangsung',
  FINAL: 'Final',
  ARCHIVED: 'Diarsipkan',
};

function canReadMeetingRepository(userRoles: string[]): boolean {
  return (
    !userRoles.includes('SUPER_ADMIN') &&
    !userRoles.includes('PIC') &&
    userRoles.some((role) => ['SEKRETARIAT', 'MANAGER_LEGAL', 'REKTOR', 'WAREK'].includes(role))
  );
}

function selectedMeetingIdFromHash(): string | null {
  const [route, id] = window.location.hash.slice(1).split('/');
  if (route !== 'search' || !id) return null;
  try {
    return decodeURIComponent(id);
  } catch {
    return null;
  }
}

function dateLabel(value: string): string {
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(parsed);
}

function monthLabel(value: string): string {
  const parsed = new Date(`${value}-01T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat('id-ID', { month: 'long', year: 'numeric' }).format(parsed);
}

function meetingSearchText(meeting: MeetingSummary): string {
  return [
    meeting.meeting_number,
    meeting.title,
    ...meeting.agendas.flatMap((agenda) => [agenda.title, agenda.agenda_description]),
  ]
    .filter((value): value is string => Boolean(value))
    .join(' ')
    .toLocaleLowerCase('id-ID');
}

function SearchPage({ authenticatedUser }: { authenticatedUser: AuthenticatedUser }) {
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<RepositoryScope>('REPOSITORY');
  const [month, setMonth] = useState('SEMUA');
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [selectedMeetingId, setSelectedMeetingId] = useState(selectedMeetingIdFromHash);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const canReadMeetings = canReadMeetingRepository(authenticatedUser.roles);

  useEffect(() => {
    const syncSelection = () => setSelectedMeetingId(selectedMeetingIdFromHash());
    window.addEventListener('hashchange', syncSelection);
    window.addEventListener('popstate', syncSelection);
    return () => {
      window.removeEventListener('hashchange', syncSelection);
      window.removeEventListener('popstate', syncSelection);
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    if (!canReadMeetings) {
      setMeetings([]);
      setLoading(false);
      return () => {
        active = false;
      };
    }

    void getMeetings()
      .then((result) => {
        if (active) setMeetings(result);
      })
      .catch(() => {
        if (active) {
          setMeetings([]);
          setError('Daftar rapat gagal dimuat. Coba muat ulang.');
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [canReadMeetings, reload]);

  const availableMonths = useMemo(
    () =>
      [...new Set(meetings.map((meeting) => meeting.meeting_date.slice(0, 7)))].sort((a, b) =>
        b.localeCompare(a),
      ),
    [meetings],
  );
  const normalizedQuery = query.trim().toLocaleLowerCase('id-ID');
  const visibleMeetings = meetings
    .filter((meeting) => {
      const statusMatches = scope === 'SEMUA' || ['FINAL', 'ARCHIVED'].includes(meeting.status);
      const monthMatches = month === 'SEMUA' || meeting.meeting_date.slice(0, 7) === month;
      const queryMatches = !normalizedQuery || meetingSearchText(meeting).includes(normalizedQuery);
      return statusMatches && monthMatches && queryMatches;
    })
    .sort((left, right) => right.meeting_date.localeCompare(left.meeting_date));
  const selectedMeeting = meetings.find((meeting) => meeting.id === selectedMeetingId) ?? null;

  if (!canReadMeetings) {
    return (
      <div className="dashboard-content repository-page">
        <section className="page-heading" aria-labelledby="repository-title">
          <div>
            <p className="eyebrow">ARSIP RAPAT</p>
            <h1 id="repository-title">Repository</h1>
          </div>
        </section>
        <p className="minutes-alert" role="alert">
          Repository rapat hanya tersedia untuk Rektor, Warek, Sekretariat, dan Manager Legal.
        </p>
      </div>
    );
  }

  if (selectedMeetingId) {
    return (
      <div className="dashboard-content repository-page">
        <a className="repository-back-link" href="#search">
          ← Kembali ke daftar rapat
        </a>
        {loading ? (
          <p className="dashboard-state" role="status">
            Memuat rapat...
          </p>
        ) : error ? (
          <p className="minutes-alert" role="alert">
            {error}
          </p>
        ) : selectedMeeting ? (
          <RepositoryMeetingDetail key={selectedMeeting.id} meeting={selectedMeeting} />
        ) : (
          <p className="dashboard-empty">Rapat tidak ditemukan di Repository.</p>
        )}
      </div>
    );
  }

  return (
    <div className="dashboard-content repository-page meeting-management-page meeting-list-page">
      <div className="meeting-list-hero">
        <section className="page-heading meeting-page-heading" aria-labelledby="repository-title">
          <div>
            <p className="eyebrow">RAPIM · REPOSITORY</p>
            <h1 id="repository-title">Repository Rapim</h1>
            <p className="page-description">Temukan arsip rapat dan dokumen terkait.</p>
          </div>
        </section>

        <section className="surface-panel meeting-search-panel" aria-label="Pencarian Repository">
          <label className="meeting-search-field" htmlFor="repository-query">
            <span>Cari rapat</span>
            <input
              id="repository-query"
              type="search"
              value={query}
              autoComplete="off"
              placeholder="Nomor, judul rapat, atau agenda"
              onChange={(event) => setQuery(event.currentTarget.value)}
            />
          </label>
        </section>
      </div>

      <section
        className="surface-panel meeting-results-panel repository-result-section"
        aria-labelledby="meeting-list"
      >
        <div className="meeting-list-heading">
          <div>
            <p className="section-kicker">ARSIP RAPIM</p>
            <h2 id="meeting-list">Daftar rapat</h2>
          </div>
          <span className="meeting-result-count">
            {loading ? 'Memuat rapat...' : `${visibleMeetings.length} rapat ditampilkan`}
          </span>
        </div>

        <div className="repository-filters repository-filter-bar" aria-label="Filter daftar rapat">
          <label htmlFor="repository-scope">
            Status rapat
            <select
              id="repository-scope"
              value={scope}
              onChange={(event) => setScope(event.target.value as RepositoryScope)}
            >
              <option value="REPOSITORY">Final dan diarsipkan</option>
              <option value="SEMUA">Semua rapat yang dapat diakses</option>
            </select>
          </label>
          <label htmlFor="repository-month">
            Bulan rapat
            <select
              id="repository-month"
              value={month}
              onChange={(event) => setMonth(event.target.value)}
            >
              <option value="SEMUA">Semua bulan</option>
              {availableMonths.map((availableMonth) => (
                <option key={availableMonth} value={availableMonth}>
                  {monthLabel(availableMonth)}
                </option>
              ))}
            </select>
          </label>
          {(normalizedQuery || scope !== 'REPOSITORY' || month !== 'SEMUA') && (
            <button
              className="text-button repository-clear-filters"
              type="button"
              onClick={() => {
                setQuery('');
                setScope('REPOSITORY');
                setMonth('SEMUA');
              }}
            >
              Hapus filter
            </button>
          )}
        </div>

        {error && (
          <div className="minutes-alert" role="alert">
            <span>{error}</span>
            <button
              className="secondary-button"
              type="button"
              onClick={() => setReload((count) => count + 1)}
            >
              Muat ulang
            </button>
          </div>
        )}

        {loading ? (
          <p className="dashboard-state" role="status">
            Memuat daftar rapat...
          </p>
        ) : visibleMeetings.length ? (
          <ul className="meeting-list">
            {visibleMeetings.map((meeting) => (
              <li key={meeting.id}>
                <a
                  className="meeting-list-row repository-meeting-row"
                  href={`#search/${encodeURIComponent(meeting.id)}`}
                >
                  <span className="meeting-list-copy">
                    <span className="meeting-list-number">{meeting.meeting_number}</span>
                    <strong className="meeting-list-title">{meeting.title}</strong>
                    <span className="meeting-list-date">
                      {dateLabel(meeting.meeting_date)} · {meeting.agendas.length} agenda
                    </span>
                  </span>
                  <span className="meeting-list-meta">
                    <span
                      className={`meeting-status meeting-status--${meeting.status.toLowerCase()}`}
                    >
                      {meetingStatusLabels[meeting.status]}
                    </span>
                    <span className="meeting-list-open" aria-hidden="true">
                      Lihat arsip <span>→</span>
                    </span>
                  </span>
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="dashboard-empty">Tidak ada rapat yang cocok dengan filter ini.</p>
        )}
      </section>
    </div>
  );
}

export default SearchPage;
