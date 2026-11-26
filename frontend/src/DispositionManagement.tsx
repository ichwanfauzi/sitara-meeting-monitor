import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  ApiError,
  canManageDispositions,
  createMeetingDisposition,
  getMeetingDispositions,
  getMinutesRevisions,
  searchDispositionTargets,
  type AuthenticatedUser,
  type Disposition,
  type DispositionTargetDirectory,
  type DispositionTargetInput,
  type MeetingRecord,
  type MinutesRevision,
} from './api';

type Props = {
  authenticatedUser: AuthenticatedUser;
  meeting: MeetingRecord;
};

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Terjadi kesalahan tidak terduga.';
}

function timestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short' }).format(
    parsed,
  );
}

function targetId(target: DispositionTargetInput): string {
  if (target.target_type === 'USER') return target.user_id;
  if (target.target_type === 'UNIT') return target.unit_id;
  return target.role_id;
}

function decisionLabel(
  revision: MinutesRevision,
  decisionId: string,
  meeting: MeetingRecord,
): string {
  for (const discussion of revision.discussions) {
    const decision = discussion.decisions.find((entry) => entry.id === decisionId);
    if (decision) {
      const agenda = meeting.agendas.find((entry) => entry.id === discussion.agenda_id);
      return agenda ? `${agenda.title} · ${decision.decision_text}` : decision.decision_text;
    }
  }
  return 'Keputusan tidak tersedia';
}

function DispositionManagement({ authenticatedUser, meeting }: Props) {
  const authorized = canManageDispositions(authenticatedUser);
  type SelectedTarget = { value: DispositionTargetInput; label: string };
  const [dispositions, setDispositions] = useState<Disposition[]>([]);
  const [directory, setDirectory] = useState<DispositionTargetDirectory | null>(null);
  const [revisions, setRevisions] = useState<MinutesRevision[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [targetSearchError, setTargetSearchError] = useState<string | null>(null);
  const [targetSearchLoading, setTargetSearchLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [sourceDecisionId, setSourceDecisionId] = useState('');
  const [instruction, setInstruction] = useState('');
  const [targetType, setTargetType] = useState<DispositionTargetInput['target_type']>('USER');
  const [targetValue, setTargetValue] = useState('');
  const [targetSearch, setTargetSearch] = useState('');
  const [targets, setTargets] = useState<SelectedTarget[]>([]);

  useEffect(() => {
    if (!authorized) return;
    let active = true;
    setLoading(true);
    setError(null);
    void Promise.all([getMeetingDispositions(meeting.id), getMinutesRevisions(meeting.id)])
      .then(([loadedDispositions, loadedRevisions]) => {
        if (!active) return;
        setDispositions(loadedDispositions);
        setRevisions(loadedRevisions);
      })
      .catch((loadError: unknown) => {
        if (active) setError(`Data disposisi tidak dapat dimuat: ${errorText(loadError)}`);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [authorized, meeting.id]);

  useEffect(() => {
    const query = targetSearch.trim();
    if (!authorized || query.length < 2) {
      setDirectory(null);
      setTargetSearchError(null);
      setTargetSearchLoading(false);
      return;
    }
    let active = true;
    setTargetSearchLoading(true);
    setTargetSearchError(null);
    const timeout = window.setTimeout(() => {
      void searchDispositionTargets(meeting.id, query)
        .then((result) => {
          if (active) setDirectory(result);
        })
        .catch((searchError: unknown) => {
          if (active) setTargetSearchError(`Target tidak dapat dicari: ${errorText(searchError)}`);
        })
        .finally(() => {
          if (active) setTargetSearchLoading(false);
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [authorized, meeting.id, targetSearch]);

  const activeRevision = useMemo(
    () => [...revisions].sort((left, right) => left.revision_number - right.revision_number).at(-1),
    [revisions],
  );
  const activeDecisions = useMemo(
    () =>
      activeRevision?.discussions.flatMap((discussion) =>
        discussion.decisions.map((decision) => ({
          ...decision,
          agendaTitle:
            meeting.agendas.find((agenda) => agenda.id === discussion.agenda_id)?.title ?? 'Agenda',
        })),
      ) ?? [],
    [activeRevision, meeting.agendas],
  );
  const displayedDirectory = directory?.query === targetSearch.trim() ? directory : null;
  const targetOptions =
    targetType === 'USER'
      ? (displayedDirectory?.users.map((user) => ({
          id: user.id,
          label: `${user.full_name}${user.job_title ? ` · ${user.job_title}` : ''}`,
        })) ?? [])
      : targetType === 'UNIT'
        ? (displayedDirectory?.units.map((unit) => ({
            id: unit.id,
            label: `${unit.unit_code} · ${unit.name}`,
          })) ?? [])
        : (displayedDirectory?.roles.map((role) => ({
            id: role.id,
            label: `${role.role_name} (${role.role_code})`,
          })) ?? []);

  if (!authorized) return null;

  function addTarget(): void {
    if (!targetValue) return;
    const selectedOption = targetOptions.find((option) => option.id === targetValue);
    if (!selectedOption) return;
    const candidate: DispositionTargetInput =
      targetType === 'USER'
        ? { target_type: 'USER', user_id: targetValue }
        : targetType === 'UNIT'
          ? { target_type: 'UNIT', unit_id: targetValue }
          : { target_type: 'ROLE', role_id: targetValue };
    if (
      targets.some(
        (target) =>
          target.value.target_type === candidate.target_type &&
          targetId(target.value) === targetValue,
      )
    ) {
      setError('Target yang sama tidak dapat ditambahkan dua kali.');
      return;
    }
    setTargets((current) => [...current, { value: candidate, label: selectedOption.label }]);
    setTargetValue('');
    setError(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!activeRevision || !activeDecisions.some((decision) => decision.id === sourceDecisionId)) {
      setError('Pilih keputusan dari revisi notulensi aktif.');
      return;
    }
    if (targets.length === 0) {
      setError('Tambahkan minimal satu target disposisi.');
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createMeetingDisposition(meeting.id, {
        source_minutes_revision_id: activeRevision.id,
        source_decision_id: sourceDecisionId,
        instruction: instruction.trim(),
        targets: targets.map((target) => target.value),
      });
      setDispositions((current) => [created, ...current]);
      setTargets([]);
      setInstruction('');
      setNotice('Disposisi berhasil disimpan.');
    } catch (submitError) {
      setError(`Disposisi tidak dapat disimpan: ${errorText(submitError)}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="surface-panel meeting-detail-panel" aria-labelledby="disposition-title">
      <h2 id="disposition-title">Disposisi</h2>
      {loading ? (
        <p className="dashboard-state" role="status">
          Memuat disposisi dan revisi notulensi...
        </p>
      ) : error ? (
        <p className="meeting-error" role="alert">
          {error}
        </p>
      ) : (
        <>
          {notice && (
            <p className="minutes-status" role="status">
              {notice}
            </p>
          )}
          {dispositions.length === 0 ? (
            <p className="dashboard-empty">Belum ada disposisi untuk rapat ini.</p>
          ) : (
            <ol className="meeting-agenda-list">
              {dispositions.map((disposition) => {
                const sourceRevision = revisions.find(
                  (revision) => revision.id === disposition.source_minutes_revision_id,
                );
                return (
                  <li key={disposition.id}>
                    <strong>{disposition.instruction}</strong>
                    <p>
                      Sumber:{' '}
                      {sourceRevision
                        ? `Revisi ${sourceRevision.revision_number} · ${decisionLabel(
                            sourceRevision,
                            disposition.source_decision_id,
                            meeting,
                          )}`
                        : 'Revisi notulensi tidak tersedia'}
                      {sourceRevision && sourceRevision.id !== activeRevision?.id
                        ? ' · historis'
                        : ''}
                    </p>
                    <span>
                      Target: {disposition.targets.map((target) => target.target_label).join(', ')}
                    </span>
                    <small> · {timestamp(disposition.created_at)}</small>
                  </li>
                );
              })}
            </ol>
          )}
          <form className="meeting-inline-form" onSubmit={(event) => void submit(event)}>
            <h3>Buat disposisi</h3>
            <label>
              Keputusan dari revisi aktif
              <select
                aria-label="Keputusan dari revisi aktif"
                value={sourceDecisionId}
                onChange={(event) => setSourceDecisionId(event.currentTarget.value)}
                required
                disabled={!activeRevision || activeDecisions.length === 0}
              >
                <option value="">Pilih keputusan</option>
                {activeDecisions.map((decision) => (
                  <option key={decision.id} value={decision.id}>
                    {decision.agendaTitle} · {decision.decision_text}
                  </option>
                ))}
              </select>
            </label>
            {!activeRevision && (
              <p className="dashboard-empty">Belum ada revisi notulensi aktif.</p>
            )}
            {activeRevision && activeDecisions.length === 0 && (
              <p className="dashboard-empty">Revisi aktif belum memiliki keputusan terstruktur.</p>
            )}
            <label>
              Cari target
              <input
                aria-label="Cari target"
                value={targetSearch}
                onChange={(event) => {
                  setTargetSearch(event.currentTarget.value);
                  setTargetValue('');
                }}
                minLength={2}
                maxLength={100}
              />
            </label>
            {targetSearch.trim().length < 2 && (
              <p className="dashboard-empty">
                Masukkan minimal dua karakter untuk mencari pengguna, unit, atau role.
              </p>
            )}
            {targetSearchLoading && (
              <p className="dashboard-state" role="status">
                Mencari target...
              </p>
            )}
            {targetSearchError && (
              <p className="meeting-error" role="alert">
                {targetSearchError}
              </p>
            )}
            {displayedDirectory &&
              !targetSearchLoading &&
              (targetType === 'USER'
                ? displayedDirectory.users.length === 0
                : targetType === 'UNIT'
                  ? displayedDirectory.units.length === 0
                  : displayedDirectory.roles.length === 0) && (
                <p className="dashboard-empty">Tidak ada target yang cocok dengan pencarian.</p>
              )}
            {displayedDirectory &&
              !targetSearchLoading &&
              ((targetType === 'USER' && displayedDirectory.more_users) ||
                (targetType === 'UNIT' && displayedDirectory.more_units) ||
                (targetType === 'ROLE' && displayedDirectory.more_roles)) && (
                <p className="dashboard-empty">
                  Ada lebih dari 100 hasil. Perjelas kata kunci pencarian.
                </p>
              )}
            <label>
              Jenis target
              <select
                aria-label="Jenis target"
                value={targetType}
                onChange={(event) => {
                  const value = event.currentTarget.value;
                  if (value === 'USER' || value === 'UNIT' || value === 'ROLE') {
                    setTargetType(value);
                  }
                  setTargetValue('');
                }}
              >
                <option value="USER">Pengguna</option>
                <option value="UNIT">Unit organisasi</option>
                <option value="ROLE">Role</option>
              </select>
            </label>
            <label>
              Target
              <select
                aria-label="Target"
                value={targetValue}
                onChange={(event) => setTargetValue(event.currentTarget.value)}
                disabled={!displayedDirectory || targetSearchLoading}
              >
                <option value="">Pilih target</option>
                {targetOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="secondary-button" onClick={addTarget}>
              Tambahkan target
            </button>
            {targets.length > 0 && (
              <ul aria-label="Target disposisi terpilih">
                {targets.map((target) => {
                  const key = `${target.value.target_type}:${targetId(target.value)}`;
                  return (
                    <li key={key}>
                      {target.label}
                      <button
                        type="button"
                        className="text-button"
                        aria-label={`Hapus target ${target.label}`}
                        onClick={() =>
                          setTargets((current) =>
                            current.filter(
                              (entry) =>
                                !(
                                  entry.value.target_type === target.value.target_type &&
                                  targetId(entry.value) === targetId(target.value)
                                ),
                            ),
                          )
                        }
                      >
                        Hapus
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
            <label>
              Instruksi disposisi
              <textarea
                value={instruction}
                onChange={(event) => setInstruction(event.currentTarget.value)}
                maxLength={20_000}
                required
              />
            </label>
            <button
              type="submit"
              className="primary-button"
              disabled={saving || !activeRevision || activeDecisions.length === 0}
            >
              {saving ? 'Menyimpan...' : 'Simpan disposisi'}
            </button>
          </form>
        </>
      )}
    </section>
  );
}

export default DispositionManagement;
