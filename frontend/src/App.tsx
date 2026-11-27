import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { canAccessMinutes, type AuthenticatedUser } from './api';
import Dashboard from './Dashboard';
import SearchPage from './SearchPage';
import DecisionBriefEditor from './DecisionBriefEditor';
import ActionItemManagement from './ActionItemManagement';
import LoginPage from './LoginPage';
import MeetingManagement from './MeetingManagement';
import MinutesEditor, { UNSAVED_MINUTES_NAVIGATION_WARNING } from './MinutesEditor';
import NotificationCenter from './NotificationCenter';
import { useAuth } from './useAuth';
import PasswordChangePage from './PasswordChangePage';
import AdminUserManagement from './AdminUserManagement';

type IconName =
  | 'grid'
  | 'calendar'
  | 'checklist'
  | 'chart'
  | 'chevron'
  | 'document'
  | 'users'
  | 'search'
  | 'menu'
  | 'close';

const iconPaths: Record<IconName, string> = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M14 14h7v7h-7z M3 14h7v7H3z',
  calendar: 'M7 2v4 M17 2v4 M3 9h18 M5 4h14a2 2 0 0 1 2 2v13H3V6a2 2 0 0 1 2-2z',
  checklist: 'M9 6h11 M9 12h11 M9 18h11 M4 6l1 1 2-2 M4 12l1 1 2-2 M4 18l1 1 2-2',
  chart: 'M4 19V5 M4 19h17 M8 15l4-4 3 2 5-6',
  chevron: 'm9 18 6-6-6-6',
  document: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h8',
  users:
    'M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M20 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75',
  search: 'm20 20-4.5-4.5 M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0z',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  close: 'm6 6 12 12 M18 6 6 18',
};

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={iconPaths[name]} />
    </svg>
  );
}

const roleLabels: Record<string, string> = {
  REKTOR: 'Rektor',
  WAREK: 'Wakil Rektor',
  SEKRETARIAT: 'Sekretariat',
  MANAGER_LEGAL: 'Manager Legal',
  PIC: 'PIC',
  SUPER_ADMIN: 'Super Admin',
};

function displayRoles(user: AuthenticatedUser): string {
  return user.roles.map((role) => roleLabels[role] ?? role).join(', ') || 'Pengguna';
}

function viewFromHash(
  hash: string,
):
  | 'dashboard'
  | 'meetings'
  | 'minutes'
  | 'decision-briefs'
  | 'action-items'
  | 'search'
  | 'admin-users' {
  if (hash === '#admin/users' || hash.startsWith('#admin/users/')) return 'admin-users';
  if (hash === '#search' || hash.startsWith('#search/')) return 'search';
  if (hash === '#action-items' || hash.startsWith('#action-items/')) return 'action-items';
  if (hash === '#notulensi' || hash.startsWith('#notulensi/')) return 'minutes';
  if (hash === '#decision-briefs' || hash.startsWith('#decision-briefs/')) {
    return 'decision-briefs';
  }
  if (hash.startsWith('#meetings')) return 'meetings';
  return 'dashboard';
}

function meetingIdFromHash(
  hash: string,
  view: 'notulensi' | 'decision-briefs',
): string | undefined {
  const prefix = `#${view}/`;
  if (!hash.startsWith(prefix)) return undefined;
  return hash.slice(prefix.length) || undefined;
}

function actionItemIdFromHash(hash: string): string | undefined {
  const prefix = '#action-items/';
  if (!hash.startsWith(prefix)) return undefined;
  const encodedId = hash.slice(prefix.length);
  try {
    return encodedId ? decodeURIComponent(encodedId) : undefined;
  } catch {
    return undefined;
  }
}

function initials(fullName: string): string {
  return fullName
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toLocaleUpperCase('id') ?? '')
    .join('');
}

function App() {
  const auth = useAuth();

  if (auth.status === 'checking') {
    return (
      <main className="auth-loading" role="status">
        Memeriksa sesi SITARA...
      </main>
    );
  }

  if (auth.status === 'authenticated' && auth.user) {
    if (auth.user.must_change_password === true) {
      return (
        <PasswordChangePage
          fullName={auth.user.full_name}
          onChangePassword={auth.changeTemporaryPassword}
          onLogout={auth.signOut}
        />
      );
    }
    return <AuthenticatedApp authenticatedUser={auth.user} onLogout={auth.signOut} />;
  }

  return (
    <LoginPage
      notice={auth.message}
      onLogin={auth.signIn}
      onRetry={() => void auth.checkSession()}
      retryable={auth.status === 'unavailable'}
    />
  );
}

function AuthenticatedApp({
  authenticatedUser,
  onLogout,
}: {
  authenticatedUser: AuthenticatedUser;
  onLogout: () => Promise<void>;
}) {
  const [activeView, setActiveView] = useState<
    | 'dashboard'
    | 'meetings'
    | 'minutes'
    | 'decision-briefs'
    | 'action-items'
    | 'search'
    | 'admin-users'
  >(() => viewFromHash(window.location.hash));
  const [routeHash, setRouteHash] = useState(() => window.location.hash || '#dashboard');
  const [minutesHasPendingDraft, setMinutesHasPendingDraft] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const previousHashRef = useRef(window.location.hash || '#dashboard');
  const approvedHashRef = useRef<string | null>(null);
  const canOpenMinutes = canAccessMinutes(authenticatedUser);
  const targetMinutesMeetingId = meetingIdFromHash(routeHash, 'notulensi');
  const targetBriefMeetingId = meetingIdFromHash(routeHash, 'decision-briefs');
  const targetActionItemId = actionItemIdFromHash(routeHash);
  const hasPicRole = authenticatedUser.roles.includes('PIC');
  const hasSuperAdminRole = authenticatedUser.roles.includes('SUPER_ADMIN');
  const isStandaloneSuperAdmin =
    authenticatedUser.roles.length === 1 && hasSuperAdminRole;
  const canReadMeetings =
    !hasPicRole &&
    !hasSuperAdminRole &&
    authenticatedUser.roles.some((role) =>
      ['SEKRETARIAT', 'MANAGER_LEGAL', 'REKTOR', 'WAREK'].includes(role),
    );
  const userInitials = initials(authenticatedUser.full_name);

  useEffect(() => {
    const syncViewFromHash = () => {
      const nextHash = window.location.hash || '#dashboard';
      if (approvedHashRef.current === nextHash) {
        approvedHashRef.current = null;
      } else if (
        minutesHasPendingDraft &&
        nextHash !== previousHashRef.current &&
        !window.confirm(UNSAVED_MINUTES_NAVIGATION_WARNING)
      ) {
        window.history.replaceState(null, '', previousHashRef.current);
        return;
      }
      previousHashRef.current = nextHash;
      setRouteHash(nextHash);
      setActiveView(viewFromHash(nextHash));
      setMobileNavOpen(false);
    };
    window.addEventListener('hashchange', syncViewFromHash);
    return () => window.removeEventListener('hashchange', syncViewFromHash);
  }, [minutesHasPendingDraft]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileNavOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [mobileNavOpen]);

  useEffect(() => {
    if (!minutesHasPendingDraft) return;
    const preventUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', preventUnload);
    return () => window.removeEventListener('beforeunload', preventUnload);
  }, [minutesHasPendingDraft]);

  function guardUnsavedMinutesNavigation(event: ReactMouseEvent<HTMLDivElement>): void {
    if (!minutesHasPendingDraft || !(event.target instanceof Element)) return;
    const link = event.target.closest<HTMLAnchorElement>('a[href^="#"]');
    const targetHash = link?.hash;
    if (!targetHash || targetHash === (window.location.hash || '#dashboard')) return;
    if (!window.confirm(UNSAVED_MINUTES_NAVIGATION_WARNING)) {
      event.preventDefault();
      return;
    }
    approvedHashRef.current = targetHash;
  }

  async function handleLogout() {
    setLogoutError(null);
    try {
      await onLogout();
    } catch (error) {
      setLogoutError(
        error instanceof Error ? error.message : 'Logout gagal. Silakan coba kembali.',
      );
    }
  }

  return (
    <div className="app-shell" onClickCapture={guardUnsavedMinutesNavigation}>
      <a className="skip-link" href="#dashboard">
        Lewati ke konten
      </a>
      <aside className={`sidebar${mobileNavOpen ? ' is-open' : ''}`} aria-label="Menu ruang kerja">
        <a className="brand" href="#dashboard" aria-label="SITARA, ke dashboard">
          <span className="brand-mark">S</span>
          <span className="brand-copy">
            <strong>SITARA</strong>
            <small>Sistem Informasi Tindak Lanjut dan Arsip Rapat</small>
          </span>
        </a>
        <div className="workspace-label">RUANG KERJA</div>
        <nav
          className="primary-nav"
          id="primary-navigation"
          aria-label="Navigasi utama"
          onClick={() => setMobileNavOpen(false)}
        >
          <a
            className={`nav-link${activeView === 'dashboard' ? ' is-active' : ''}`}
            href="#dashboard"
            aria-current={activeView === 'dashboard' ? 'page' : undefined}
          >
            <Icon name="grid" />
            <span>Dashboard</span>
          </a>
          {canReadMeetings && (
            <a
              className={`nav-link${activeView === 'meetings' ? ' is-active' : ''}`}
              href="#meetings"
              aria-current={activeView === 'meetings' ? 'page' : undefined}
            >
              <Icon name="calendar" />
              <span>Rapat</span>
            </a>
          )}
          {isStandaloneSuperAdmin && (
            <a
              className={`nav-link${activeView === 'admin-users' ? ' is-active' : ''}`}
              href="#admin/users"
              aria-current={activeView === 'admin-users' ? 'page' : undefined}
            >
              <Icon name="users" />
              <span>Pengguna</span>
            </a>
          )}
          {canOpenMinutes && (
            <a
              className={`nav-link${activeView === 'minutes' ? ' is-active' : ''}`}
              href="#notulensi"
              aria-current={activeView === 'minutes' ? 'page' : undefined}
            >
              <Icon name="document" />
              <span>Notulensi</span>
            </a>
          )}
          {canOpenMinutes && (
            <a
              className={`nav-link${activeView === 'decision-briefs' ? ' is-active' : ''}`}
              href="#decision-briefs"
              aria-current={activeView === 'decision-briefs' ? 'page' : undefined}
            >
              <Icon name="chart" />
              <span>Decision Brief</span>
            </a>
          )}
          {!hasSuperAdminRole && (
            <a
              className={`nav-link${activeView === 'action-items' ? ' is-active' : ''}`}
              href="#action-items"
              aria-current={activeView === 'action-items' ? 'page' : undefined}
            >
              <Icon name={hasPicRole ? 'checklist' : 'users'} />
              <span>{hasPicRole ? 'Tugas saya' : 'Tindak lanjut'}</span>
            </a>
          )}
          {canReadMeetings && (
            <a
              className={`nav-link${activeView === 'search' ? ' is-active' : ''}`}
              href="#search"
              aria-current={activeView === 'search' ? 'page' : undefined}
            >
              <Icon name="search" />
              <span>Repository</span>
            </a>
          )}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-divider" />
        <div className="profile-summary">
          <div className="avatar" aria-hidden="true">
            {userInitials}
          </div>
          <div className="profile-copy">
            <strong>{authenticatedUser.full_name}</strong>
            <span>{displayRoles(authenticatedUser)}</span>
          </div>
        </div>
      </aside>
      {mobileNavOpen && (
        <button
          className="sidebar-backdrop"
          type="button"
          aria-label="Tutup menu"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <main
        className={`main-content${activeView === 'dashboard' ? '' : ' main-content--workspace'}`}
        id="dashboard"
      >
        <header className="topbar">
          <div className="topbar-leading">
            <button
              className="mobile-nav-toggle"
              type="button"
              aria-label={mobileNavOpen ? 'Tutup menu navigasi' : 'Buka menu navigasi'}
              aria-expanded={mobileNavOpen}
              aria-controls="primary-navigation"
              onClick={() => setMobileNavOpen((open) => !open)}
            >
              <Icon name={mobileNavOpen ? 'close' : 'menu'} />
            </button>
            <div className="breadcrumbs">
              <span>Ruang kerja</span>
              <Icon name="chevron" size={14} />
              <strong>
                {activeView === 'minutes'
                  ? 'Notulensi'
                  : activeView === 'decision-briefs'
                    ? 'Decision Brief'
                    : activeView === 'action-items'
                      ? 'Action Item'
                      : activeView === 'meetings'
                        ? 'Rapat'
                        : activeView === 'search'
                          ? 'Repository & Pencarian'
                          : activeView === 'admin-users'
                            ? 'Pengguna'
                          : 'Dashboard'}
              </strong>
            </div>
          </div>
          <div className="topbar-actions">
            <NotificationCenter />
            <div className="topbar-profile" aria-label={`Profil ${authenticatedUser.full_name}`}>
              <div className="avatar avatar--small" aria-hidden="true">
                {userInitials}
              </div>
              <span>{authenticatedUser.full_name}</span>
              <span className="topbar-role">{displayRoles(authenticatedUser)}</span>
              <button className="logout-button" type="button" onClick={() => void handleLogout()}>
                Keluar
              </button>
            </div>
          </div>
        </header>
        {logoutError && (
          <div className="logout-error" role="alert">
            {logoutError}
          </div>
        )}

        {activeView === 'dashboard' && <Dashboard authenticatedUser={authenticatedUser} />}
        {activeView === 'admin-users' && (
          <AdminUserManagement authenticatedUser={authenticatedUser} />
        )}
        {activeView === 'search' && <SearchPage authenticatedUser={authenticatedUser} />}
        {activeView === 'meetings' && <MeetingManagement authenticatedUser={authenticatedUser} />}
        {activeView === 'action-items' && (
          <ActionItemManagement
            authenticatedUser={authenticatedUser}
            targetActionItemId={targetActionItemId}
          />
        )}
        {activeView === 'minutes' && (
          <div className="dashboard-content">
            {canOpenMinutes ? (
              <MinutesEditor
                key={targetMinutesMeetingId ?? 'all-meetings'}
                authenticatedUser={authenticatedUser}
                onPendingDraftChange={setMinutesHasPendingDraft}
                targetMeetingId={targetMinutesMeetingId}
              />
            ) : (
              <p className="minutes-alert" role="alert">
                Anda tidak memiliki akses ke Notulensi.
              </p>
            )}
          </div>
        )}
        {activeView === 'decision-briefs' && (
          <div className="dashboard-content">
            {canOpenMinutes ? (
              <DecisionBriefEditor
                key={targetBriefMeetingId ?? 'all-meetings'}
                authenticatedUser={authenticatedUser}
                targetMeetingId={targetBriefMeetingId}
              />
            ) : (
              <p className="minutes-alert" role="alert">
                Anda tidak memiliki akses ke Decision Brief.
              </p>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
