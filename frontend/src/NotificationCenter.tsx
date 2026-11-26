import { useCallback, useEffect, useState } from 'react';
import {
  getNotifications,
  markNotificationRead,
  type NotificationPage,
  type NotificationRecord,
} from './api';

function notificationTarget(notification: NotificationRecord): string {
  const section = notification.target_type === 'ACTION_ITEM' ? 'action-items' : 'decision-briefs';
  return `#${section}/${encodeURIComponent(notification.target_id)}`;
}

function notificationDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function NotificationCenter() {
  const [page, setPage] = useState<NotificationPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [pendingReadIds, setPendingReadIds] = useState<Set<string>>(() => new Set());

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPage(await getNotifications());
    } catch {
      setError('Notifikasi tidak dapat dimuat. Coba lagi.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const refreshOnFocus = () => void refresh();
    window.addEventListener('focus', refreshOnFocus);
    return () => window.removeEventListener('focus', refreshOnFocus);
  }, [refresh]);

  async function markRead(notification: NotificationRecord) {
    if (notification.read_at !== null || pendingReadIds.has(notification.id)) return;
    setPendingReadIds((current) => new Set(current).add(notification.id));
    setError(null);
    try {
      const updated = await markNotificationRead(notification.id);
      setPage((current) =>
        current
          ? {
              items: current.items.map((item) => (item.id === updated.id ? updated : item)),
              unread_count: Math.max(0, current.unread_count - 1),
            }
          : current,
      );
    } catch {
      setError('Notifikasi gagal ditandai dibaca. Coba lagi.');
    } finally {
      setPendingReadIds((current) => {
        const next = new Set(current);
        next.delete(notification.id);
        return next;
      });
    }
  }

  const unreadCount = page?.unread_count ?? 0;
  const label = unreadCount > 0 ? `Notifikasi (${unreadCount} belum dibaca)` : 'Notifikasi';

  return (
    <div className="notification-center">
      <button
        className="notification-toggle"
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls="notification-panel"
        onClick={() => setOpen((current) => !current)}
      >
        Notifikasi
        {unreadCount > 0 && <span className="notification-count">{unreadCount}</span>}
      </button>
      {open && (
        <section
          className="notification-panel"
          id="notification-panel"
          aria-label="Pusat notifikasi"
        >
          <div className="notification-panel-heading">
            <h2>Notifikasi</h2>
            <button
              type="button"
              className="text-button"
              onClick={() => void refresh()}
              disabled={loading}
            >
              Muat ulang
            </button>
          </div>
          {loading ? (
            <p className="dashboard-state" role="status">
              Memuat notifikasi...
            </p>
          ) : error ? (
            <p className="notification-error" role="alert">
              {error}
            </p>
          ) : page && page.items.length > 0 ? (
            <ol className="notification-list">
              {page.items.map((notification) => (
                <li
                  className={
                    notification.read_at === null
                      ? 'notification-item notification-item--unread'
                      : 'notification-item'
                  }
                  key={notification.id}
                >
                  <a href={notificationTarget(notification)}>{notification.message}</a>
                  <time dateTime={notification.created_at}>
                    {notificationDate(notification.created_at)}
                  </time>
                  {notification.read_at === null && (
                    <button
                      className="text-button"
                      type="button"
                      disabled={pendingReadIds.has(notification.id)}
                      onClick={() => void markRead(notification)}
                    >
                      Tandai dibaca
                    </button>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p className="dashboard-empty">Belum ada notifikasi.</p>
          )}
        </section>
      )}
    </div>
  );
}

export default NotificationCenter;
