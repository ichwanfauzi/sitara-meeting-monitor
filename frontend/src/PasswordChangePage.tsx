import { useState, type FormEvent } from 'react';

type PasswordChangePageProps = {
  fullName: string;
  onChangePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  onLogout: () => Promise<void>;
};

export default function PasswordChangePage({
  fullName,
  onChangePassword,
  onLogout,
}: PasswordChangePageProps) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (newPassword !== confirmPassword) {
      setError('Konfirmasi kata sandi baru tidak sama.');
      return;
    }
    if (newPassword.length < 16) {
      setError('Kata sandi baru minimal 16 karakter.');
      return;
    }
    setSubmitting(true);
    try {
      await onChangePassword(currentPassword, newPassword);
    } catch (changeError) {
      setError(
        changeError instanceof Error
          ? changeError.message
          : 'Ganti kata sandi gagal. Silakan coba kembali.',
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="password-change-title">
        <div className="login-heading">
          <p className="eyebrow">KEAMANAN AKUN</p>
          <h1 id="password-change-title">Ganti kata sandi sementara</h1>
          <p>
            {fullName}, ganti kata sandi sebelum dapat menggunakan aplikasi SITARA.
          </p>
        </div>
        {error && (
          <div className="login-error" role="alert">
            {error}
          </div>
        )}
        <form className="login-form" onSubmit={(event) => void handleSubmit(event)}>
          <label htmlFor="current-password">Kata sandi sementara</label>
          <input
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            required
            disabled={submitting}
          />
          <label htmlFor="new-password">Kata sandi baru</label>
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            minLength={16}
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            required
            disabled={submitting}
          />
          <label htmlFor="confirm-password">Konfirmasi kata sandi baru</label>
          <input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            minLength={16}
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            required
            disabled={submitting}
          />
          <button className="login-submit" type="submit" disabled={submitting}>
            {submitting ? 'Menyimpan...' : 'Ganti kata sandi'}
          </button>
          <button
            className="text-button"
            type="button"
            onClick={() => void onLogout()}
            disabled={submitting}
          >
            Keluar
          </button>
        </form>
      </section>
    </main>
  );
}
