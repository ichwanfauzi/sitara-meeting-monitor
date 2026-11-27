import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  ApiError,
  createAdminUser,
  getAdminUsers,
  resetAdminUserPassword,
  updateAdminUserStatus,
  type AdminManagedUser,
  type AdminOperationalRole,
  type AuthenticatedUser,
} from './api';

const operationalRoles: { value: AdminOperationalRole; label: string }[] = [
  { value: 'REKTOR', label: 'Rektor' },
  { value: 'WAREK', label: 'Wakil Rektor' },
  { value: 'SEKRETARIAT', label: 'Sekretariat' },
  { value: 'MANAGER_LEGAL', label: 'Manager Legal' },
];

const warekPositions = [
  'Wakil Rektor I Bidang Akademik',
  'Wakil Rektor II Bidang Sumber Daya',
  'Wakil Rektor III Bidang Kemahasiswaan',
  'Wakil Rektor IV Bidang Kerjasama',
];

function roleLabel(roleCode: string): string {
  return operationalRoles.find((role) => role.value === roleCode)?.label ?? roleCode;
}

type AdminUserManagementProps = {
  authenticatedUser: AuthenticatedUser;
};

function isStandaloneSuperAdmin(user: AuthenticatedUser): boolean {
  return user.roles.length === 1 && user.roles[0] === 'SUPER_ADMIN';
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : 'Terjadi kesalahan saat mengelola akun. Coba lagi.';
}

export default function AdminUserManagement({
  authenticatedUser,
}: AdminUserManagementProps) {
  const authorized = isStandaloneSuperAdmin(authenticatedUser);
  const [accounts, setAccounts] = useState<AdminManagedUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [roleCode, setRoleCode] = useState<AdminOperationalRole | ''>('');
  const [jobTitle, setJobTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [busyAccountId, setBusyAccountId] = useState<string | null>(null);
  const [temporaryPassword, setTemporaryPassword] = useState<{
    email: string;
    value: string;
  } | null>(null);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await getAdminUsers();
      setAccounts(
        result.items.filter((account) => !account.roles.includes('SUPER_ADMIN')),
      );
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authorized) void loadAccounts();
  }, [authorized, loadAccounts]);

  if (!authorized) {
    return (
      <div className="dashboard-content">
        <p className="minutes-alert" role="alert">
          Halaman ini hanya tersedia untuk Super Admin.
        </p>
      </div>
    );
  }

  async function handleCreateAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!roleCode) return;
    if (!window.confirm(`Buat akun ${fullName.trim()} dengan peran ${roleLabel(roleCode)}?`)) {
      return;
    }

    setSaving(true);
    setActionError(null);
    setTemporaryPassword(null);
    try {
      const result = await createAdminUser({
        email: email.trim(),
        full_name: fullName.trim(),
        job_title: jobTitle.trim() || null,
        role_code: roleCode,
      });
      setTemporaryPassword({
        email: result.user.email,
        value: result.temporary_password,
      });
      setEmail('');
      setFullName('');
      setRoleCode('');
      setJobTitle('');
      setShowCreateForm(false);
      await loadAccounts();
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  async function handleActivationChange(account: AdminManagedUser) {
    const nextActive = !account.is_active;
    const action = nextActive ? 'aktifkan kembali' : 'nonaktifkan';
    if (!window.confirm(`${action[0].toLocaleUpperCase('id-ID')}${action.slice(1)} akun ${account.full_name}?`)) {
      return;
    }

    setBusyAccountId(account.id);
    setActionError(null);
    setTemporaryPassword(null);
    try {
      const updated = await updateAdminUserStatus(account.id, nextActive);
      setAccounts((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusyAccountId(null);
    }
  }

  async function handlePasswordReset(account: AdminManagedUser) {
    if (
      !window.confirm(
        `Reset kata sandi ${account.full_name}? Sesi akun akan dicabut dan kata sandi sementara hanya ditampilkan sekali.`,
      )
    ) {
      return;
    }

    setBusyAccountId(account.id);
    setActionError(null);
    setTemporaryPassword(null);
    try {
      const result = await resetAdminUserPassword(account.id);
      setTemporaryPassword({
        email: account.email,
        value: result.temporary_password,
      });
      await loadAccounts();
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusyAccountId(null);
    }
  }

  return (
    <div className="dashboard-content admin-users-page">
      <section className="surface-panel admin-users-heading">
        <div>
          <p className="section-kicker">ADMINISTRASI SISTEM</p>
          <h1>Manajemen akun</h1>
          <p>Kelola akun operasional SITARA. Perubahan akses dicatat dalam audit.</p>
        </div>
        <button
          className="primary-button"
          type="button"
          onClick={() => {
            setActionError(null);
            setTemporaryPassword(null);
            setShowCreateForm((current) => !current);
          }}
        >
          {showCreateForm ? 'Tutup form' : 'Tambah akun'}
        </button>
      </section>

      {temporaryPassword && (
        <section className="admin-temporary-password" aria-label="Kata sandi sementara">
          <div>
            <strong>Kata sandi sementara untuk {temporaryPassword.email}</strong>
            <p>Simpan sekarang. Kata sandi ini tidak akan ditampilkan kembali.</p>
            <code>{temporaryPassword.value}</code>
          </div>
          <button
            className="secondary-button"
            type="button"
            onClick={() => setTemporaryPassword(null)}
          >
            Sembunyikan kata sandi sementara
          </button>
        </section>
      )}

      {actionError && !showCreateForm && (
        <div className="meeting-error" role="alert">
          {actionError}
        </div>
      )}

      {showCreateForm && (
        <form className="surface-panel admin-account-form" onSubmit={handleCreateAccount}>
          <div className="admin-account-form-heading">
            <h2>Buat akun operasional</h2>
            <p>Kata sandi sementara dibuat otomatis dan wajib diganti saat masuk pertama kali.</p>
          </div>
          <label>
            Nama lengkap
            <input
              autoComplete="name"
              maxLength={200}
              required
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
            />
          </label>
          <label>
            Email
            <input
              autoComplete="email"
              maxLength={320}
              required
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            Peran
            <select
              required
              value={roleCode}
              onChange={(event) => {
                const selectedRole = operationalRoles.find(
                  (role) => role.value === event.target.value,
                );
                setRoleCode(selectedRole?.value ?? '');
                setJobTitle('');
              }}
            >
              <option value="">Pilih peran</option>
              {operationalRoles.map((role) => (
                <option key={role.value} value={role.value}>
                  {role.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Jabatan
            {roleCode === 'WAREK' ? (
              <select
                required
                value={jobTitle}
                onChange={(event) => setJobTitle(event.target.value)}
              >
                <option value="">Pilih jabatan Warek</option>
                {warekPositions.map((position) => (
                  <option key={position} value={position}>
                    {position}
                  </option>
                ))}
              </select>
            ) : (
              <input
                maxLength={200}
                value={jobTitle}
                onChange={(event) => setJobTitle(event.target.value)}
              />
            )}
          </label>
          {actionError && (
            <div className="meeting-error admin-account-form-error" role="alert">
              {actionError}
            </div>
          )}
          <div className="meeting-form-actions">
            <button
              className="secondary-button"
              type="button"
              onClick={() => setShowCreateForm(false)}
              disabled={saving}
            >
              Batal
            </button>
            <button className="primary-button" type="submit" disabled={saving}>
              {saving ? 'Membuat akun...' : 'Buat akun'}
            </button>
          </div>
        </form>
      )}

      <section className="surface-panel admin-account-list" aria-labelledby="admin-accounts-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">PENGGUNA</p>
            <h2 id="admin-accounts-title">Daftar akun operasional</h2>
          </div>
          <span className="meeting-page-count">{accounts.length} akun</span>
        </div>

        {loading ? (
          <p className="dashboard-state" role="status">
            Memuat daftar akun...
          </p>
        ) : loadError ? (
          <div className="meeting-error" role="alert">
            <span>{loadError}</span>
            <button className="secondary-button" type="button" onClick={() => void loadAccounts()}>
              Coba lagi
            </button>
          </div>
        ) : accounts.length === 0 ? (
          <p className="dashboard-empty" role="status">
            Belum ada akun operasional.
          </p>
        ) : (
          <div className="admin-account-table-wrap">
            <table className="admin-account-table" aria-label="Daftar akun SITARA">
              <thead>
                <tr>
                  <th scope="col">Nama</th>
                  <th scope="col">Username / email</th>
                  <th scope="col">Peran dan jabatan</th>
                  <th scope="col">Status akun</th>
                  <th scope="col">Status kata sandi</th>
                  <th scope="col">Tindakan</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => (
                  <tr key={account.id}>
                    <td>{account.full_name}</td>
                    <td>{account.email}</td>
                    <td>
                      <strong>{account.roles.map(roleLabel).join(', ')}</strong>
                      <span>{account.job_title || 'Jabatan belum dicatat'}</span>
                    </td>
                    <td>
                      <span
                        className={`admin-account-status${account.is_active ? ' is-active' : ' is-inactive'}`}
                      >
                        {account.is_active ? 'Aktif' : 'Nonaktif'}
                      </span>
                    </td>
                    <td>
                      {account.must_change_password
                        ? 'Perlu ganti kata sandi'
                        : 'Kata sandi sudah diperbarui'}
                    </td>
                    <td>
                      <div className="admin-account-actions">
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() => void handleActivationChange(account)}
                          disabled={busyAccountId === account.id || saving}
                        >
                          {account.is_active ? 'Nonaktifkan' : 'Aktifkan kembali'}
                        </button>
                        <button
                          className="text-button"
                          type="button"
                          onClick={() => void handlePasswordReset(account)}
                          disabled={busyAccountId === account.id || saving}
                        >
                          Reset kata sandi
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
