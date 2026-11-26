import { useMemo, useState } from 'react';
import type { MeetingSummary } from './api';

interface MeetingPickerProps {
  id: string;
  label: string;
  meetings: MeetingSummary[];
  selectedMeetingId: string;
  onSelect: (meetingId: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

function formatMeetingDate(value: string): string {
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(date);
}

function MeetingPicker({
  id,
  label,
  meetings,
  selectedMeetingId,
  onSelect,
  disabled = false,
  placeholder = 'Ketik nomor atau judul rapat',
}: MeetingPickerProps) {
  const [query, setQuery] = useState('');
  const selectedMeeting = meetings.find((meeting) => meeting.id === selectedMeetingId) ?? null;
  const results = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase('id-ID');
    if (!normalized) return [];
    return meetings
      .filter((meeting) =>
        `${meeting.meeting_number} ${meeting.title}`
          .toLocaleLowerCase('id-ID')
          .includes(normalized),
      )
      .slice(0, 8);
  }, [meetings, query]);

  return (
    <div className="meeting-picker">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className="minutes-input meeting-picker-input"
        type="search"
        autoComplete="off"
        aria-autocomplete="list"
        aria-controls={`${id}-results`}
        aria-expanded={query.trim().length > 0}
        disabled={disabled}
        value={query}
        onChange={(event) => setQuery(event.currentTarget.value)}
        placeholder={placeholder}
      />
      {query.trim() && (
        <div className="meeting-picker-results" id={`${id}-results`} role="listbox">
          {results.length ? (
            results.map((meeting) => (
              <button
                className="meeting-picker-option"
                key={meeting.id}
                type="button"
                role="option"
                aria-selected={meeting.id === selectedMeetingId}
                onClick={() => {
                  onSelect(meeting.id);
                  setQuery('');
                }}
              >
                <strong>
                  {meeting.meeting_number} · {meeting.title}
                </strong>
                <span>{formatMeetingDate(meeting.meeting_date)}</span>
              </button>
            ))
          ) : (
            <p className="meeting-picker-empty">Tidak ada rapat yang cocok.</p>
          )}
        </div>
      )}
      {!query.trim() && selectedMeeting && (
        <div className="meeting-picker-selected" aria-live="polite">
          <span>Rapat dipilih</span>
          <strong>
            {selectedMeeting.meeting_number} · {selectedMeeting.title}
          </strong>
          <small>
            {formatMeetingDate(selectedMeeting.meeting_date)} · {selectedMeeting.status}
          </small>
        </div>
      )}
    </div>
  );
}

export default MeetingPicker;
