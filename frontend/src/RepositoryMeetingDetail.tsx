import { useEffect, useState } from 'react';
import {
  getActionItems,
  getDecisionBriefHistory,
  getMinutesRevisions,
  type ActionItemStatus,
  type ActionItemSummary,
  type DecisionBriefVersion,
  type MeetingSummary,
  type MinutesRevision,
} from './api';

const actionStatusLabels: Record<ActionItemStatus, string> = {
  BELUM_DIMULAI: 'Belum dimulai',
  BERPROSES: 'Berproses',
  TERKENDALA: 'Terkendala',
  MENUNGGU_ACC: 'Menunggu persetujuan',
  SELESAI: 'Selesai',
};

function dateLabel(value: string | null): string {
  if (!value) return 'Belum ditentukan';
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(parsed);
}

function dateTimeLabel(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed);
}

function RepositoryMeetingDetail({ meeting }: { meeting: MeetingSummary }) {
  const [minutes, setMinutes] = useState<MinutesRevision[]>([]);
  const [briefs, setBriefs] = useState<DecisionBriefVersion[]>([]);
  const [actionItems, setActionItems] = useState<ActionItemSummary[]>([]);
  const [minutesError, setMinutesError] = useState(false);
  const [briefsError, setBriefsError] = useState(false);
  const [actionItemsError, setActionItemsError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [printingDocument, setPrintingDocument] = useState<'minutes' | 'brief' | null>(null);

  useEffect(() => {
    const resetPrintMode = () => {
      document.body.classList.remove('sitara-print-mode');
      setPrintingDocument(null);
    };
    window.addEventListener('afterprint', resetPrintMode);
    return () => {
      window.removeEventListener('afterprint', resetPrintMode);
      document.body.classList.remove('sitara-print-mode');
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setMinutesError(false);
    setBriefsError(false);
    setActionItemsError(false);

    void Promise.allSettled([
      getMinutesRevisions(meeting.id),
      getDecisionBriefHistory(meeting.id),
      getActionItems(true, meeting.id),
    ]).then(([minutesResult, briefsResult, actionItemsResult]) => {
      if (!active) return;
      if (minutesResult.status === 'fulfilled') {
        setMinutes(minutesResult.value);
      } else {
        setMinutes([]);
        setMinutesError(true);
      }
      if (briefsResult.status === 'fulfilled') {
        setBriefs(briefsResult.value);
      } else {
        setBriefs([]);
        setBriefsError(true);
      }
      if (actionItemsResult.status === 'fulfilled') {
        setActionItems(actionItemsResult.value);
      } else {
        setActionItems([]);
        setActionItemsError(true);
      }
      setLoading(false);
    });

    return () => {
      active = false;
    };
  }, [meeting.id]);

  const currentMinutes =
    [...minutes].sort((left, right) => right.revision_number - left.revision_number)[0] ?? null;
  const currentBrief =
    [...briefs]
      .filter((brief) => brief.source_minutes_revision_id === currentMinutes?.id)
      .sort((left, right) => right.version_number - left.version_number)[0] ?? null;

  function printDocument(documentType: 'minutes' | 'brief'): void {
    document.body.classList.add('sitara-print-mode');
    setPrintingDocument(documentType);
    window.setTimeout(() => window.print(), 0);
  }

  return (
    <div className="repository-meeting-detail">
      <header className="repository-detail-heading">
        <div>
          <p className="eyebrow">DETAIL RAPAT</p>
          <h1>{meeting.title}</h1>
          <p>
            {meeting.meeting_number} · {dateLabel(meeting.meeting_date)} · {meeting.status}
          </p>
        </div>
        <a
          className="button button--secondary"
          href={`#meetings/${encodeURIComponent(meeting.id)}`}
        >
          Buka pengelolaan rapat
        </a>
      </header>

      <nav className="repository-section-nav" aria-label="Bagian rapat">
        <a href="#repo-agenda">Agenda</a>
        <a href="#repo-minutes">Notulensi</a>
        <a href="#repo-briefs">Decision Brief</a>
        <a href="#repo-actions">Tindak lanjut</a>
      </nav>

      <section className="surface-panel repository-detail-section" aria-labelledby="repo-agenda">
        <h2 id="repo-agenda">Agenda</h2>
        {meeting.agendas.length ? (
          <details className="repository-document-version">
            <summary>Lihat {meeting.agendas.length} agenda</summary>
            <ol className="repository-agenda-list">
              {meeting.agendas.map((agenda) => (
                <li key={agenda.id}>
                  <strong>{agenda.title}</strong>
                  {agenda.agenda_description && <p>{agenda.agenda_description}</p>}
                </li>
              ))}
            </ol>
          </details>
        ) : (
          <p className="dashboard-empty">Belum ada agenda.</p>
        )}
      </section>

      <section className="surface-panel repository-detail-section" aria-labelledby="repo-minutes">
        <div className="repository-section-heading">
          <h2 id="repo-minutes">Notulensi</h2>
        </div>
        {loading ? (
          <p className="dashboard-state">Memuat notulensi...</p>
        ) : minutesError ? (
          <p className="minutes-alert" role="alert">
            Notulensi rapat gagal dimuat.
          </p>
        ) : currentMinutes ? (
          <details className="repository-document-version">
            <summary>Buka notulensi</summary>
            <p className="repository-status">
              Notulensi tersimpan · {dateTimeLabel(currentMinutes.created_at)}
            </p>
            <button
              className="button button--secondary"
              onClick={() => printDocument('minutes')}
              type="button"
            >
              Cetak notulensi
            </button>
            <article
              className={`minutes-final-output${printingDocument === 'minutes' ? ' sitara-print-target' : ''}`}
              data-print-target={printingDocument === 'minutes' ? 'true' : undefined}
            >
              <header className="minutes-print-heading">
                <p className="minutes-print-institution">INSTITUT TEKNOLOGI PLN</p>
                <h2>NOTULA RAPAT</h2>
                <p className="minutes-print-meeting-title">{meeting.title}</p>
                <dl>
                  <div>
                    <dt>Nomor</dt>
                    <dd>{meeting.meeting_number}</dd>
                  </div>
                  <div>
                    <dt>Hari/Tanggal</dt>
                    <dd>{dateLabel(meeting.meeting_date)}</dd>
                  </div>
                </dl>
              </header>
              {currentMinutes.format_version === 1 ? (
                <table className="minutes-preview-table" aria-label="Tabel cetak notulensi">
                  <thead>
                    <tr>
                      <th scope="col">Catatan notulensi terdahulu</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="repository-preserved-text">{currentMinutes.content}</td>
                    </tr>
                  </tbody>
                </table>
              ) : (
                <div className="minutes-table-scroll minutes-preview-scroll">
                  <table className="minutes-preview-table" aria-label="Tabel cetak notulensi">
                    <thead>
                      <tr>
                        <th scope="col">No.</th>
                        <th scope="col">Agenda/Pokok Bahasan</th>
                        <th scope="col">Putusan/Arahan &amp; Tindak Lanjut</th>
                        <th scope="col">PIC</th>
                        <th scope="col">Output</th>
                        <th scope="col">Target</th>
                      </tr>
                    </thead>
                    <tbody>
                      {currentMinutes.discussions.map((discussion, index) => {
                        const agenda = meeting.agendas.find(
                          (item) => item.id === discussion.agenda_id,
                        );
                        const targetText = (
                          decision: MinutesRevision['discussions'][number]['decisions'][number],
                        ) =>
                          decision.target_date
                            ? dateLabel(decision.target_date)
                            : decision.target_text || 'Belum ditentukan';
                        return (
                          <tr key={discussion.id}>
                            <td className="minutes-print-number">{index + 1}</td>
                            <td>
                              <strong>{agenda?.title ?? 'Agenda tidak tersedia'}</strong>
                              {discussion.subject && <h3>{discussion.subject}</h3>}
                              <p>{discussion.content}</p>
                            </td>
                            <td className="minutes-preview-cell-list">
                              {discussion.decisions.length ? (
                                discussion.decisions.map((decision, decisionIndex) => (
                                  <p key={decision.id}>
                                    <strong>{decisionIndex + 1}.</strong> {decision.decision_text}
                                  </p>
                                ))
                              ) : (
                                <p>Belum ada putusan/arahan.</p>
                              )}
                            </td>
                            <td className="minutes-preview-cell-list">
                              {discussion.decisions.length ? (
                                discussion.decisions.map((decision) => (
                                  <p key={decision.id}>
                                    {decision.pic_suggestion || 'Belum ditentukan'}
                                  </p>
                                ))
                              ) : (
                                <p>Belum ditentukan</p>
                              )}
                            </td>
                            <td className="minutes-preview-cell-list">
                              {discussion.decisions.length ? (
                                discussion.decisions.map((decision) => (
                                  <p key={decision.id}>
                                    {decision.output_expected || 'Belum ditentukan'}
                                  </p>
                                ))
                              ) : (
                                <p>Belum ditentukan</p>
                              )}
                            </td>
                            <td className="minutes-preview-cell-list">
                              {discussion.decisions.length ? (
                                discussion.decisions.map((decision) => (
                                  <p key={decision.id}>{targetText(decision)}</p>
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
              )}
            </article>
          </details>
        ) : (
          <p className="dashboard-empty">Belum ada notulensi tersimpan.</p>
        )}
      </section>

      <section className="surface-panel repository-detail-section" aria-labelledby="repo-briefs">
        <div className="repository-section-heading">
          <h2 id="repo-briefs">Decision Brief</h2>
        </div>
        {loading ? (
          <p className="dashboard-state">Memuat Decision Brief...</p>
        ) : briefsError ? (
          <p className="minutes-alert" role="alert">
            Decision Brief gagal dimuat.
          </p>
        ) : currentBrief ? (
          <details className="repository-document-version">
            <summary>Buka Decision Brief</summary>
            <p className="repository-status">
              Brief terakhir tersimpan · {dateTimeLabel(currentBrief.created_at)}
            </p>
            <button
              className="button button--secondary"
              onClick={() => printDocument('brief')}
              type="button"
            >
              Cetak Decision Brief
            </button>
            <article
              className={`decision-brief-printable${printingDocument === 'brief' ? ' sitara-print-target' : ''}`}
              data-print-target={printingDocument === 'brief' ? 'true' : undefined}
            >
              <header className="decision-brief-document-heading">
                <h4>DECISION BRIEF RAPAT PIMPINAN</h4>
                <p>
                  {meeting.meeting_number} · {meeting.title}
                </p>
                <p>Rapim {dateLabel(meeting.meeting_date)}</p>
              </header>
              {currentBrief.decisions.length > 0 && (
                <div className="repository-brief-table-wrap">
                  <table className="repository-brief-table" aria-label="Tabel cetak Decision Brief">
                    <colgroup>
                      <col className="repository-brief-column-number" />
                      <col className="repository-brief-column-topic" />
                      <col className="repository-brief-column-decision" />
                      <col className="repository-brief-column-pic" />
                      <col className="repository-brief-column-output" />
                      <col className="repository-brief-column-target" />
                    </colgroup>
                    <thead>
                      <tr>
                        <th scope="col">No.</th>
                        <th scope="col">Bahasan</th>
                        <th scope="col">Putusan/Tindak Lanjut</th>
                        <th scope="col">PIC</th>
                        <th scope="col">Output</th>
                        <th scope="col">Target Penyelesaian</th>
                      </tr>
                    </thead>
                    <tbody>
                      {currentBrief.decisions.map((decision, index) => {
                        const sourceDecision = currentMinutes?.discussions
                          .flatMap((discussion) => discussion.decisions)
                          .find((candidate) => candidate.id === decision.decision_id);
                        return (
                          <tr key={decision.decision_id}>
                            <td>{index + 1}</td>
                            <td>
                              <strong>{decision.source_agenda_title}</strong>
                              {decision.source_discussion_subject && (
                                <p>{decision.source_discussion_subject}</p>
                              )}
                            </td>
                            <td>
                              <p className="repository-preserved-text">
                                {decision.brief_text || 'Ringkasan putusan belum diisi.'}
                              </p>
                              <small>Prioritas: {decision.priority || 'Belum ditentukan'}</small>
                            </td>
                            <td>{sourceDecision?.pic_suggestion || 'Belum ditentukan'}</td>
                            <td>{sourceDecision?.output_expected || 'Belum ditentukan'}</td>
                            <td>
                              {sourceDecision?.target_date
                                ? dateLabel(sourceDecision.target_date)
                                : sourceDecision?.target_text || 'Belum ditentukan'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </article>
          </details>
        ) : (
          <p className="dashboard-empty">Belum ada Decision Brief untuk notulensi saat ini.</p>
        )}
      </section>

      <section className="surface-panel repository-detail-section" aria-labelledby="repo-actions">
        <div className="repository-section-heading">
          <h2 id="repo-actions">Tindak lanjut ({actionItems.length})</h2>
          <a href="#action-items">Buka menu tindak lanjut</a>
        </div>
        {loading ? (
          <p className="dashboard-state">Memuat tindak lanjut...</p>
        ) : actionItemsError ? (
          <p className="minutes-alert" role="alert">
            Tindak lanjut rapat gagal dimuat.
          </p>
        ) : actionItems.length ? (
          <div className="repository-action-list">
            {actionItems.map((item) => (
              <details className="repository-document-version repository-action-card" key={item.id}>
                <summary className="repository-action-summary">
                  <strong>{item.title}</strong>
                  <span className="repository-status">
                    {item.deleted_at
                      ? 'Dihapus dari daftar aktif'
                      : actionStatusLabels[item.official_status]}
                  </span>
                </summary>
                <p className="repository-preserved-text">{item.description}</p>
                {item.output_expected && (
                  <p className="repository-preserved-text">
                    <strong>Output:</strong> {item.output_expected}
                  </p>
                )}
                <dl className="repository-action-meta">
                  <div>
                    <dt>PIC</dt>
                    <dd>
                      {item.active_assignments.length
                        ? item.active_assignments
                            .map((assignment) => {
                              const name =
                                assignment.assignee_display_name ??
                                assignment.assignee_name ??
                                'Belum ditentukan';
                              return `${name} (${assignment.assignment_role === 'MAIN' ? 'utama' : 'pendukung'})`;
                            })
                            .join(', ')
                        : 'Belum ditentukan'}
                    </dd>
                  </div>
                  <div>
                    <dt>Tenggat</dt>
                    <dd>{dateLabel(item.due_date)}</dd>
                  </div>
                  <div>
                    <dt>Prioritas</dt>
                    <dd>{item.priority}</dd>
                  </div>
                </dl>
              </details>
            ))}
          </div>
        ) : (
          <p className="dashboard-empty">
            Belum ada tindak lanjut yang tersedia dalam cakupan akses Anda.
          </p>
        )}
      </section>
    </div>
  );
}

export default RepositoryMeetingDetail;
