import { useMemo, useState } from 'react';
import type { MeetingSummary } from './api';

const PAGE_SIZE = 20;

const statusLabels: Record<MeetingSummary['status'], string> = {
  DRAFT: 'Draf',
  LIVE: 'Berlangsung',
  FINAL: 'Selesai',
  ARCHIVED: 'Diarsipkan',
};

function dateLabel(value: string): string {
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(parsed);
}

function MeetingDocumentSelection({
  meetings,
  documentName,
  routePrefix,
}: {
  meetings: MeetingSummary[];
  documentName: 'Notulensi rapat' | 'Decision Brief';
  routePrefix: '#notulensi' | '#decision-briefs';
}) {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const filteredMeetings = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase('id-ID');
    return meetings.filter((meeting) =>
      `${meeting.meeting_number} ${meeting.title}`.toLocaleLowerCase('id-ID').includes(normalized),
    );
  }, [meetings, search]);
  const pageCount = Math.ceil(filteredMeetings.length / PAGE_SIZE);
  const visibleMeetings = filteredMeetings.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="meeting-management-page meeting-list-page meeting-document-selection">
      <div className="meeting-list-hero">
        <section className="page-heading meeting-page-heading">
          <div>
            <p className="eyebrow">
              RAPIM · {documentName === 'Notulensi rapat' ? 'NOTULENSI' : 'DECISION BRIEF'}
            </p>
            <h1 id="meeting-document-title">{documentName}</h1>
            <p className="page-description">Buka salah satu rapat untuk melanjutkan.</p>
          </div>
        </section>
        <section className="surface-panel meeting-search-panel" aria-label="Pencarian rapat">
          <label className="meeting-search-field">
            <span>Cari rapat</span>
            <input
              type="search"
              value={search}
              autoComplete="off"
              placeholder="Nomor atau judul rapat"
              onChange={(event) => {
                setSearch(event.currentTarget.value);
                setPage(0);
              }}
            />
          </label>
          {search && (
            <button
              className="secondary-button meeting-search-clear"
              type="button"
              aria-label="Hapus pencarian rapat"
              onClick={() => {
                setSearch('');
                setPage(0);
              }}
            >
              Hapus
            </button>
          )}
        </section>
      </div>
      {visibleMeetings.length === 0 ? (
        <p className="dashboard-empty">Tidak ada rapat yang cocok.</p>
      ) : (
        <section className="surface-panel meeting-results-panel" aria-label="Daftar rapat">
          <div className="meeting-list-heading">
            <div>
              <p className="section-kicker">DAFTAR RAPIM</p>
              <h2>Rapat sesuai pencarian</h2>
            </div>
            <span className="meeting-result-count">
              {filteredMeetings.length} rapat ditampilkan
            </span>
          </div>
          <div className="meeting-list">
            {visibleMeetings.map((meeting) => (
              <a
                key={meeting.id}
                className="meeting-list-row"
                href={`${routePrefix}/${encodeURIComponent(meeting.id)}`}
              >
                <span className="meeting-list-copy">
                  <small className="meeting-list-number">{meeting.meeting_number} ·</small>
                  <strong className="meeting-list-title">{meeting.title}</strong>
                  <small className="meeting-list-date">{dateLabel(meeting.meeting_date)}</small>
                </span>
                <span className="meeting-list-meta">
                  <span
                    className={`meeting-status meeting-status--${meeting.status.toLowerCase()}`}
                  >
                    {statusLabels[meeting.status]}
                  </span>
                  <span className="meeting-list-open" aria-hidden="true">
                    Buka {documentName} <span>→</span>
                  </span>
                </span>
              </a>
            ))}
          </div>
          {pageCount > 1 && (
            <nav className="meeting-pagination" aria-label="Navigasi daftar rapat">
              <button
                className="secondary-button"
                type="button"
                disabled={page === 0}
                onClick={() => setPage((current) => current - 1)}
              >
                Sebelumnya
              </button>
              <span className="meeting-page-indicator">
                Halaman {page + 1} dari {pageCount}
              </span>
              <button
                className="secondary-button"
                type="button"
                disabled={page + 1 >= pageCount}
                onClick={() => setPage((current) => current + 1)}
              >
                Berikutnya
              </button>
            </nav>
          )}
        </section>
      )}
    </div>
  );
}

export default MeetingDocumentSelection;
