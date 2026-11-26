import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  ApiError,
  addMeetingParticipant,
  canAccessMinutes,
  createAgenda,
  createMinutesReview,
  createMeeting,
  deleteAgenda,
  deleteMeetingParticipant,
  getMeeting,
  getMeetingParticipantOptions,
  getMeetingsPage,
  getMinutesReviews,
  getMinutesRevisions,
  transitionMeeting,
  updateAgenda,
  updateMeetingMetadata,
  type AuthenticatedUser,
  type MeetingAgenda,
  type MeetingCreateInput,
  type MeetingMetadataUpdateInput,
  type MeetingParticipantOption,
  type MeetingRecord,
  type MeetingStatus,
  type MeetingSummary,
  type MinutesReview,
  type MinutesRevision,
} from './api';

const PAGE_SIZE = 20;
const statusLabels: Record<MeetingStatus, string> = {
  DRAFT: 'Draf',
  LIVE: 'Berlangsung',
  FINAL: 'Selesai',
  ARCHIVED: 'Diarsipkan',
};

type MeetingRoute = { page: 'list' } | { page: 'create' } | { page: 'detail'; id: string };

function routeFromHash(): MeetingRoute {
  const [section, id] = window.location.hash.slice(1).split('/');
  if (section !== 'meetings') return { page: 'list' };
  if (id === 'create') return { page: 'create' };
  return id ? { page: 'detail', id } : { page: 'list' };
}

function dateLabel(value: string): string {
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(date);
}

function hasInvalidTimeRange(startTime: string | null, endTime: string | null): boolean {
  return Boolean(startTime && endTime && endTime < startTime);
}

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function canEditMeetings(user: AuthenticatedUser): boolean {
  return (
    !user.roles.includes('SUPER_ADMIN') &&
    !user.roles.includes('PIC') &&
    user.roles.some((role) => ['SEKRETARIAT', 'MANAGER_LEGAL', 'WAREK'].includes(role))
  );
}

function canReadMeetingList(user: AuthenticatedUser): boolean {
  return (
    !user.roles.includes('SUPER_ADMIN') &&
    !user.roles.includes('PIC') &&
    user.roles.some((role) => ['SEKRETARIAT', 'MANAGER_LEGAL', 'WAREK', 'REKTOR'].includes(role))
  );
}

function canChangeStatus(user: AuthenticatedUser): boolean {
  return (
    user.roles.some((role) => ['SEKRETARIAT', 'MANAGER_LEGAL'].includes(role)) &&
    !user.roles.includes('SUPER_ADMIN') &&
    !user.roles.includes('PIC')
  );
}

function activeRevision(revisions: MinutesRevision[]): MinutesRevision | null {
  return (
    [...revisions].sort((left, right) => right.revision_number - left.revision_number)[0] ?? null
  );
}

function reviewIsValid(reviews: MinutesReview[], revision: MinutesRevision | null): boolean {
  const latest = [...reviews].sort((left, right) => right.review_number - left.review_number)[0];
  return Boolean(
    revision && latest?.minutes_revision_id === revision.id && latest.result === 'VALID',
  );
}

function MeetingManagement({ authenticatedUser }: { authenticatedUser: AuthenticatedUser }) {
  const [route, setRoute] = useState<MeetingRoute>(routeFromHash);
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState('');
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [detail, setDetail] = useState<MeetingRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [options, setOptions] = useState<MeetingParticipantOption[]>([]);
  const [participantId, setParticipantId] = useState('');
  const [metadataOpen, setMetadataOpen] = useState(false);
  const [agendaOpen, setAgendaOpen] = useState(false);
  const [participantOpen, setParticipantOpen] = useState(false);
  const [editingAgendaId, setEditingAgendaId] = useState<string | null>(null);
  const [minutesRevision, setMinutesRevision] = useState<MinutesRevision | null>(null);
  const [hasValidReview, setHasValidReview] = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);

  const navigate = useCallback((next: MeetingRoute) => {
    const hash =
      next.page === 'detail'
        ? `#meetings/${encodeURIComponent(next.id)}`
        : next.page === 'create'
          ? '#meetings/create'
          : '#meetings';
    if (window.location.hash !== hash) window.history.pushState(null, '', hash);
    setRoute(next);
    setFormError(null);
    setNotice(null);
  }, []);

  const loadList = useCallback(async () => {
    if (!canReadMeetingList(authenticatedUser)) {
      setMeetings([]);
      setListError('Peran Anda tidak memiliki akses ke pengelolaan rapat.');
      setListLoading(false);
      return;
    }
    setListLoading(true);
    setListError(null);
    try {
      setMeetings(await getMeetingsPage(PAGE_SIZE, page * PAGE_SIZE, search));
    } catch (error) {
      setMeetings([]);
      setListError(`Daftar rapat gagal dimuat: ${message(error, 'terjadi kesalahan')}`);
    } finally {
      setListLoading(false);
    }
  }, [authenticatedUser, page, search]);

  useEffect(() => {
    const syncRoute = () => setRoute(routeFromHash());
    window.addEventListener('hashchange', syncRoute);
    window.addEventListener('popstate', syncRoute);
    return () => {
      window.removeEventListener('hashchange', syncRoute);
      window.removeEventListener('popstate', syncRoute);
    };
  }, []);

  useEffect(() => {
    if (route.page === 'list') void loadList();
  }, [loadList, route.page]);

  useEffect(() => {
    if (route.page !== 'create') return;
    let active = true;
    void getMeetingParticipantOptions()
      .then((participantOptions) => {
        if (active) setOptions(participantOptions);
      })
      .catch((error: unknown) => {
        if (active) setFormError(message(error, 'Daftar notulis gagal dimuat.'));
      });
    return () => {
      active = false;
    };
  }, [route.page]);

  useEffect(() => {
    if (route.page !== 'detail') {
      setDetail(null);
      setMinutesRevision(null);
      setHasValidReview(false);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setFormError(null);
    void Promise.all([
      getMeeting(route.id),
      getMeetingParticipantOptions().catch(() => []),
      canChangeStatus(authenticatedUser)
        ? Promise.all([getMinutesRevisions(route.id), getMinutesReviews(route.id)])
        : Promise.resolve(null),
    ])
      .then(([meeting, participantOptions, reviewData]) => {
        if (!active) return;
        setDetail(meeting);
        setOptions(participantOptions);
        if (reviewData) {
          const revision = activeRevision(reviewData[0]);
          setMinutesRevision(revision);
          setHasValidReview(reviewIsValid(reviewData[1], revision));
        }
      })
      .catch((error: unknown) => {
        if (active) setFormError(message(error, 'Detail rapat gagal dimuat.'));
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [authenticatedUser, route]);

  async function reloadDetail(meetingId: string) {
    const [meeting, reviewData] = await Promise.all([
      getMeeting(meetingId),
      canChangeStatus(authenticatedUser)
        ? Promise.all([getMinutesRevisions(meetingId), getMinutesReviews(meetingId)])
        : Promise.resolve(null),
    ]);
    setDetail(meeting);
    if (reviewData) {
      const revision = activeRevision(reviewData[0]);
      setMinutesRevision(revision);
      setHasValidReview(reviewIsValid(reviewData[1], revision));
    }
  }

  async function submitMeeting(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const data: MeetingCreateInput = {
      meeting_number: String(form.get('meeting_number') ?? '').trim(),
      title: String(form.get('title') ?? '').trim(),
      meeting_type: String(form.get('meeting_type') ?? 'RAPIM').trim(),
      meeting_date: String(form.get('meeting_date') ?? ''),
      start_time: String(form.get('start_time') ?? '') || null,
      end_time: String(form.get('end_time') ?? '') || null,
      location: String(form.get('location') ?? '').trim() || null,
      notetaker_id: String(form.get('notetaker_id') ?? '') || null,
    };
    if (hasInvalidTimeRange(data.start_time, data.end_time)) {
      setFormError('Waktu selesai harus sama atau setelah waktu mulai.');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const created = await createMeeting(data);
      navigate({ page: 'detail', id: created.id });
    } catch (error) {
      setFormError(message(error, 'Rapat gagal dibuat.'));
    } finally {
      setSaving(false);
    }
  }

  async function submitMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail) return;
    const form = new FormData(event.currentTarget);
    const data: MeetingMetadataUpdateInput = {
      expected_version: detail.version,
      meeting_number: String(form.get('meeting_number') ?? '').trim(),
      ...(detail.status === 'DRAFT' || detail.status === 'LIVE'
        ? {
            title: String(form.get('title') ?? '').trim(),
            meeting_type: String(form.get('meeting_type') ?? '').trim(),
            meeting_date: String(form.get('meeting_date') ?? ''),
            start_time: String(form.get('start_time') ?? '') || null,
            end_time: String(form.get('end_time') ?? '') || null,
            location: String(form.get('location') ?? '').trim() || null,
          }
        : {}),
    };
    if (hasInvalidTimeRange(data.start_time ?? null, data.end_time ?? null)) {
      setFormError('Waktu selesai harus sama atau setelah waktu mulai.');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      setDetail(await updateMeetingMetadata(detail.id, data));
      setMetadataOpen(false);
      setNotice('Informasi rapat tersimpan.');
      await loadList();
    } catch (error) {
      setFormError(message(error, 'Informasi rapat gagal diperbarui.'));
    } finally {
      setSaving(false);
    }
  }

  async function submitAgenda(event: FormEvent<HTMLFormElement>, agenda?: MeetingAgenda) {
    event.preventDefault();
    if (!detail) return;
    const form = new FormData(event.currentTarget);
    const duration = String(form.get('duration_minutes') ?? '');
    const data = {
      expected_version: detail.version,
      title: String(form.get('title') ?? '').trim(),
      agenda_description: String(form.get('agenda_description') ?? '').trim() || null,
      pic_suggestion: String(form.get('pic_suggestion') ?? '').trim() || null,
      supporting_pic_suggestion: String(form.get('supporting_pic_suggestion') ?? '').trim() || null,
      duration_minutes: duration ? Number(duration) : null,
    };
    setSaving(true);
    setFormError(null);
    try {
      if (agenda) await updateAgenda(detail.id, agenda.id, data);
      else await createAgenda(detail.id, data);
      setAgendaOpen(false);
      setEditingAgendaId(null);
      await reloadDetail(detail.id);
    } catch (error) {
      setFormError(message(error, 'Agenda gagal disimpan.'));
    } finally {
      setSaving(false);
    }
  }

  async function removeAgenda(agenda: MeetingAgenda) {
    if (!detail || !window.confirm(`Hapus agenda “${agenda.title}”?`)) return;
    setSaving(true);
    try {
      await deleteAgenda(detail.id, agenda.id, detail.version);
      await reloadDetail(detail.id);
    } catch (error) {
      setFormError(message(error, 'Agenda gagal dihapus.'));
    } finally {
      setSaving(false);
    }
  }

  async function addParticipant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail || !participantId) return;
    setSaving(true);
    setFormError(null);
    try {
      await addMeetingParticipant(detail.id, {
        expected_version: detail.version,
        user_id: participantId,
      });
      setParticipantId('');
      setParticipantOpen(false);
      await reloadDetail(detail.id);
    } catch (error) {
      setFormError(message(error, 'Peserta gagal ditambahkan.'));
    } finally {
      setSaving(false);
    }
  }

  async function removeParticipant(userId: string) {
    if (!detail || !window.confirm('Hapus peserta dari rapat ini?')) return;
    setSaving(true);
    try {
      await deleteMeetingParticipant(detail.id, userId, detail.version);
      await reloadDetail(detail.id);
    } catch (error) {
      setFormError(message(error, 'Peserta gagal dihapus.'));
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(status: MeetingStatus) {
    if (!detail || !canChangeStatus(authenticatedUser)) return;
    setStatusBusy(true);
    setFormError(null);
    setNotice(null);
    try {
      setDetail(await transitionMeeting(detail.id, status));
      await reloadDetail(detail.id);
      await loadList();
      setNotice(`Status rapat sekarang: ${statusLabels[status]}.`);
    } catch (error) {
      setFormError(message(error, 'Status rapat gagal diperbarui.'));
    } finally {
      setStatusBusy(false);
    }
  }

  async function validateMinutes() {
    if (!detail || !minutesRevision) return;
    setStatusBusy(true);
    setFormError(null);
    try {
      await createMinutesReview(detail.id, {
        minutes_revision_id: minutesRevision.id,
        result: 'VALID',
        review_note: null,
      });
      await reloadDetail(detail.id);
      setNotice('Notulensi sudah ditandai valid.');
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          await reloadDetail(detail.id);
          setFormError(message(error, 'Notulensi berubah. Periksa status rapat lalu coba lagi.'));
        } catch (reloadError) {
          setFormError(
            `${message(error, 'Validasi notulensi gagal disimpan.')} ${message(
              reloadError,
              'Detail rapat gagal dimuat ulang.',
            )}`,
          );
        }
      } else {
        setFormError(message(error, 'Validasi notulensi gagal disimpan.'));
      }
    } finally {
      setStatusBusy(false);
    }
  }

  if (route.page === 'create') {
    return (
      <div className="dashboard-content meeting-management-page meeting-create-page">
        <button type="button" className="text-button" onClick={() => navigate({ page: 'list' })}>
          Kembali ke rapat
        </button>
        <section className="page-heading meeting-page-heading">
          <div>
            <p className="eyebrow">RAPIM · PENGELOLAAN</p>
            <h1>Buat rapat</h1>
            <p className="page-description">
              Isi informasi dasar dan pilih notulis bila sudah ditentukan.
            </p>
          </div>
        </section>
        {formError && (
          <p className="meeting-error" role="alert">
            {formError}
          </p>
        )}
        <form
          className="surface-panel meeting-form"
          onSubmit={(event) => void submitMeeting(event)}
        >
          <label>
            Nomor rapat
            <input name="meeting_number" required maxLength={150} />
          </label>
          <label>
            Judul rapat
            <input name="title" required maxLength={300} />
          </label>
          <label>
            Jenis rapat
            <input name="meeting_type" defaultValue="RAPIM" required maxLength={100} />
          </label>
          <label>
            Tanggal
            <input name="meeting_date" type="date" required />
          </label>
          <label>
            Waktu mulai
            <input name="start_time" type="time" />
          </label>
          <label>
            Waktu selesai
            <input name="end_time" type="time" />
          </label>
          <label>
            Lokasi atau media
            <input name="location" maxLength={300} />
          </label>
          <label>
            Notulis rapat (opsional)
            <select name="notetaker_id" defaultValue="">
              <option value="">Belum ditentukan</option>
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.job_title || 'Jabatan belum diisi'}
                </option>
              ))}
            </select>
          </label>
          <div className="meeting-form-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={() => navigate({ page: 'list' })}
            >
              Batal
            </button>
            <button type="submit" className="primary-button" disabled={saving}>
              {saving ? 'Menyimpan…' : 'Simpan rapat'}
            </button>
          </div>
        </form>
      </div>
    );
  }

  if (route.page === 'detail') {
    if (detailLoading)
      return (
        <div className="dashboard-content meeting-management-page">
          <p className="dashboard-state" role="status">
            Memuat rapat…
          </p>
        </div>
      );
    if (!detail)
      return (
        <div className="dashboard-content meeting-management-page">
          <button className="text-button" onClick={() => navigate({ page: 'list' })}>
            Kembali
          </button>
          <p className="meeting-error" role="alert">
            {formError ?? 'Rapat tidak ditemukan.'}
          </p>
        </div>
      );
    const meetingEditor = canEditMeetings(authenticatedUser);
    const editable = meetingEditor && ['DRAFT', 'LIVE'].includes(detail.status);
    const meetingMutable = meetingEditor && detail.status !== 'ARCHIVED';
    const availableParticipants = options.filter(
      (option) => !detail.participants.some((p) => p.user_id === option.id),
    );
    return (
      <div className="dashboard-content meeting-management-page meeting-detail-page">
        <button type="button" className="text-button" onClick={() => navigate({ page: 'list' })}>
          Kembali ke daftar rapat
        </button>
        <section className="page-heading meeting-detail-heading meeting-page-heading">
          <div>
            <p className="eyebrow">
              {detail.meeting_number} · {detail.meeting_type}
            </p>
            <h1>{detail.title}</h1>
            <p className="page-description">
              {dateLabel(detail.meeting_date)}
              {detail.start_time ? ` · ${detail.start_time.slice(0, 5)}` : ''}
              {detail.end_time ? `–${detail.end_time.slice(0, 5)}` : ''}
              {detail.location ? ` · ${detail.location}` : ''}
            </p>
          </div>
          <span className={`meeting-status meeting-status--${detail.status.toLowerCase()}`}>
            {statusLabels[detail.status]}
          </span>
        </section>
        {formError && (
          <p className="meeting-error" role="alert">
            {formError}
          </p>
        )}
        {notice && (
          <p className="minutes-status" role="status">
            {notice}
          </p>
        )}
        <section
          className="surface-panel meeting-detail-panel"
          aria-labelledby="meeting-info-title"
        >
          <div className="section-heading">
            <h2 id="meeting-info-title">Informasi rapat</h2>
            {meetingMutable && (
              <button
                className="secondary-button"
                type="button"
                onClick={() => setMetadataOpen(!metadataOpen)}
              >
                {metadataOpen ? 'Tutup' : 'Ubah informasi'}
              </button>
            )}
          </div>
          <dl className="meeting-detail-grid">
            <div>
              <dt>Nomor rapat</dt>
              <dd>{detail.meeting_number}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{statusLabels[detail.status]}</dd>
            </div>
          </dl>
          {metadataOpen && meetingMutable && (
            <form className="meeting-inline-form" onSubmit={(event) => void submitMetadata(event)}>
              {!editable && (
                <p className="field-hint">
                  Nomor rapat dapat diubah kapan saja. Informasi lain hanya dapat diubah saat rapat
                  berstatus Draf atau Berlangsung.
                </p>
              )}
              <label>
                Nomor rapat
                <input
                  name="meeting_number"
                  defaultValue={detail.meeting_number}
                  maxLength={150}
                  required
                />
              </label>
              {editable && (
                <>
                  <label>
                    Judul rapat
                    <input name="title" defaultValue={detail.title} maxLength={300} required />
                  </label>
                  <label>
                    Jenis rapat
                    <input
                      name="meeting_type"
                      defaultValue={detail.meeting_type}
                      maxLength={100}
                      required
                    />
                  </label>
                  <label>
                    Tanggal
                    <input
                      name="meeting_date"
                      type="date"
                      defaultValue={detail.meeting_date.slice(0, 10)}
                      required
                    />
                  </label>
                  <label>
                    Waktu mulai
                    <input
                      name="start_time"
                      type="time"
                      defaultValue={detail.start_time?.slice(0, 5) ?? ''}
                    />
                  </label>
                  <label>
                    Waktu selesai
                    <input
                      name="end_time"
                      type="time"
                      defaultValue={detail.end_time?.slice(0, 5) ?? ''}
                    />
                  </label>
                  <label>
                    Lokasi atau media
                    <input name="location" defaultValue={detail.location ?? ''} maxLength={300} />
                  </label>
                </>
              )}
              <button className="primary-button" type="submit" disabled={saving}>
                {saving ? 'Menyimpan…' : 'Simpan informasi'}
              </button>
            </form>
          )}
          {canAccessMinutes(authenticatedUser) && (
            <div className="meeting-document-links">
              <a className="secondary-button" href={`#notulensi/${detail.id}`}>
                Buka notulensi
              </a>
              <a className="secondary-button" href={`#decision-briefs/${detail.id}`}>
                Buka Decision Brief
              </a>
            </div>
          )}
          {canChangeStatus(authenticatedUser) && (
            <div
              className="meeting-status-controls"
              aria-label="Pengelolaan status oleh Sekretariat dan Manager Legal"
            >
              <strong>Status rapat · Sekretariat / Manager Legal</strong>
              <div className="meeting-form-actions">
                {detail.status === 'DRAFT' && (
                  <button
                    type="button"
                    className="primary-button"
                    disabled={statusBusy}
                    onClick={() => void changeStatus('LIVE')}
                  >
                    Mulai rapat
                  </button>
                )}
                {detail.status === 'LIVE' && minutesRevision && !hasValidReview && (
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={statusBusy}
                    onClick={() => void validateMinutes()}
                  >
                    Tandai notulensi valid
                  </button>
                )}
                {detail.status === 'LIVE' && hasValidReview && (
                  <button
                    type="button"
                    className="primary-button"
                    disabled={statusBusy}
                    onClick={() => void changeStatus('FINAL')}
                  >
                    Selesaikan rapat
                  </button>
                )}
                {detail.status === 'FINAL' && (
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={statusBusy}
                    onClick={() => void changeStatus('ARCHIVED')}
                  >
                    Arsipkan
                  </button>
                )}
              </div>
              {detail.status === 'LIVE' && !minutesRevision && (
                <small>Tambahkan notulensi sebelum rapat dapat diselesaikan.</small>
              )}
            </div>
          )}
        </section>
        <section className="surface-panel meeting-detail-panel" aria-labelledby="agenda-title">
          <div className="section-heading">
            <h2 id="agenda-title">Agenda</h2>
            {editable && (
              <button
                className="secondary-button"
                type="button"
                onClick={() => setAgendaOpen(!agendaOpen)}
              >
                {agendaOpen ? 'Tutup form' : 'Tambah agenda'}
              </button>
            )}
          </div>
          {detail.agendas.length === 0 ? (
            <p className="dashboard-empty">Belum ada agenda.</p>
          ) : (
            <ol className="meeting-agenda-list">
              {detail.agendas.map((agenda) => (
                <li key={agenda.id}>
                  <strong>{agenda.title}</strong>
                  {agenda.agenda_description && <p>{agenda.agenda_description}</p>}
                  {agenda.pic_suggestion && (
                    <p>
                      <b>PIC:</b> {agenda.pic_suggestion}
                    </p>
                  )}
                  {agenda.supporting_pic_suggestion && (
                    <p>
                      <b>PIC pendukung:</b> {agenda.supporting_pic_suggestion}
                    </p>
                  )}
                  {editable && (
                    <div className="meeting-form-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() =>
                          setEditingAgendaId(editingAgendaId === agenda.id ? null : agenda.id)
                        }
                      >
                        {editingAgendaId === agenda.id ? 'Tutup edit' : 'Edit agenda'}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={saving}
                        onClick={() => void removeAgenda(agenda)}
                      >
                        Hapus agenda
                      </button>
                    </div>
                  )}
                  {editingAgendaId === agenda.id && editable && (
                    <form
                      className="meeting-inline-form"
                      onSubmit={(event) => void submitAgenda(event, agenda)}
                    >
                      <label>
                        Judul agenda
                        <input name="title" defaultValue={agenda.title} maxLength={500} required />
                      </label>
                      <label>
                        Deskripsi agenda
                        <textarea
                          name="agenda_description"
                          defaultValue={agenda.agenda_description ?? ''}
                          maxLength={10000}
                          rows={3}
                        />
                      </label>
                      <label>
                        PIC utama
                        <input
                          name="pic_suggestion"
                          defaultValue={agenda.pic_suggestion ?? ''}
                          maxLength={300}
                        />
                      </label>
                      <label>
                        PIC pendukung
                        <input
                          name="supporting_pic_suggestion"
                          defaultValue={agenda.supporting_pic_suggestion ?? ''}
                          maxLength={2000}
                        />
                      </label>
                      <label>
                        Durasi (menit)
                        <input
                          name="duration_minutes"
                          type="number"
                          min="1"
                          max="1440"
                          defaultValue={agenda.duration_minutes ?? ''}
                        />
                      </label>
                      <button className="primary-button" type="submit" disabled={saving}>
                        Simpan agenda
                      </button>
                    </form>
                  )}
                </li>
              ))}
            </ol>
          )}
          {agendaOpen && editable && (
            <form className="meeting-inline-form" onSubmit={(event) => void submitAgenda(event)}>
              <p className="page-description">Nomor agenda dibuat otomatis.</p>
              <label>
                Judul agenda
                <input name="title" maxLength={500} required />
              </label>
              <label>
                Deskripsi agenda
                <textarea name="agenda_description" maxLength={10000} rows={3} />
              </label>
              <label>
                PIC utama
                <input name="pic_suggestion" maxLength={300} />
              </label>
              <label>
                PIC pendukung
                <input name="supporting_pic_suggestion" maxLength={2000} />
              </label>
              <label>
                Durasi (menit)
                <input name="duration_minutes" type="number" min="1" max="1440" />
              </label>
              <button className="primary-button" type="submit" disabled={saving}>
                {saving ? 'Menyimpan…' : 'Simpan agenda'}
              </button>
            </form>
          )}
        </section>
        <section
          className="surface-panel meeting-detail-panel"
          aria-labelledby="participants-title"
        >
          <div className="section-heading">
            <h2 id="participants-title">Peserta</h2>
            {editable && (
              <button
                className="secondary-button"
                type="button"
                onClick={() => setParticipantOpen(!participantOpen)}
              >
                {participantOpen ? 'Tutup' : 'Tambah peserta'}
              </button>
            )}
          </div>
          {detail.participants.length === 0 ? (
            <p className="dashboard-empty">Belum ada peserta.</p>
          ) : (
            <ul className="meeting-participant-list">
              {detail.participants.map((participant) => {
                const title =
                  participant.participant_title?.trim() ||
                  options.find((option) => option.id === participant.user_id)?.job_title?.trim() ||
                  participant.participant_name;
                return (
                  <li key={participant.user_id}>
                    <strong>{title}</strong>
                    {editable && (
                      <button
                        type="button"
                        className="text-button"
                        disabled={saving}
                        onClick={() => void removeParticipant(participant.user_id)}
                      >
                        Hapus
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {participantOpen && editable && (
            <form className="meeting-inline-form" onSubmit={(event) => void addParticipant(event)}>
              <label>
                Pilih peserta
                <select
                  value={participantId}
                  onChange={(event) => setParticipantId(event.currentTarget.value)}
                  required
                >
                  <option value="">Pilih pengguna inti</option>
                  {availableParticipants.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.job_title?.trim() || option.full_name}
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit" className="primary-button" disabled={saving || !participantId}>
                {saving ? 'Menyimpan…' : 'Tambahkan peserta'}
              </button>
            </form>
          )}
        </section>
      </div>
    );
  }

  return (
    <div className="dashboard-content meeting-management-page meeting-list-page">
      <div className="meeting-list-hero">
        <section className="page-heading meeting-page-heading">
          <div>
            <p className="eyebrow">RAPIM · PENGELOLAAN</p>
            <h1>Daftar rapat</h1>
            <p className="page-description">
              Temukan rapat dan kelola informasinya sesuai hak akses Anda.
            </p>
          </div>
          {canEditMeetings(authenticatedUser) && (
            <button
              className="primary-button"
              type="button"
              onClick={() => navigate({ page: 'create' })}
            >
              Buat rapat
            </button>
          )}
        </section>
        <section className="surface-panel meeting-search-panel" aria-label="Pencarian rapat">
          <label className="meeting-search-field">
            <span>Cari rapat</span>
            <input
              type="search"
              value={search}
              onChange={(event) => {
                setSearch(event.currentTarget.value);
                setPage(0);
              }}
              placeholder="Nomor atau judul rapat"
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
      {listLoading ? (
        <p className="dashboard-state" role="status">
          Memuat daftar rapat…
        </p>
      ) : listError ? (
        <div className="meeting-error" role="alert">
          <span>{listError}</span>
          <button type="button" className="secondary-button" onClick={() => void loadList()}>
            Coba lagi
          </button>
        </div>
      ) : meetings.length === 0 ? (
        page === 0 ? (
          <p className="dashboard-empty">Tidak ada rapat yang cocok.</p>
        ) : (
          <section className="surface-panel meeting-results-panel">
            <p className="dashboard-empty">Tidak ada lagi rapat pada halaman ini.</p>
            <nav className="meeting-pagination" aria-label="Navigasi daftar rapat">
              <button
                className="secondary-button"
                type="button"
                onClick={() => setPage((value) => value - 1)}
              >
                Sebelumnya
              </button>
            </nav>
          </section>
        )
      ) : (
        <section className="surface-panel meeting-results-panel">
          <div className="meeting-list-heading">
            <div>
              <p className="section-kicker">DAFTAR RAPIM</p>
              <h2>Rapat sesuai pencarian</h2>
            </div>
            <span className="meeting-result-count">{meetings.length} rapat ditampilkan</span>
          </div>
          <div className="meeting-list">
            {meetings.map((meeting) => (
              <button
                key={meeting.id}
                type="button"
                className="meeting-list-row"
                aria-label={`Lihat detail ${meeting.title}`}
                onClick={() => navigate({ page: 'detail', id: meeting.id })}
              >
                <span className="meeting-list-copy">
                  <small className="meeting-list-number">{meeting.meeting_number}</small>
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
                    Buka detail <span>→</span>
                  </span>
                </span>
              </button>
            ))}
          </div>
          <nav className="meeting-pagination" aria-label="Navigasi daftar rapat">
            <button
              className="secondary-button"
              type="button"
              disabled={page === 0}
              onClick={() => setPage((value) => value - 1)}
            >
              Sebelumnya
            </button>
            <span className="meeting-page-indicator">Halaman {page + 1}</span>
            <button
              className="secondary-button"
              type="button"
              disabled={meetings.length < PAGE_SIZE}
              onClick={() => setPage((value) => value + 1)}
            >
              Berikutnya
            </button>
          </nav>
        </section>
      )}
    </div>
  );
}

export default MeetingManagement;
