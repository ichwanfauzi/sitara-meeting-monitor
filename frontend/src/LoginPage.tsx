import { useState, type FormEvent } from 'react';

type LoginPageProps = {
  notice: string | null;
  onLogin: (email: string, password: string) => Promise<void>;
  onRetry: () => void;
  retryable: boolean;
};

function LoginPage({ notice, onLogin, onRetry, retryable }: LoginPageProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginError(null);
    setSubmitting(true);
    try {
      await onLogin(email.trim(), password);
    } catch (error) {
      setLoginError(
        error instanceof Error ? error.message : 'Login gagal. Periksa kembali data Anda.',
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <div className="login-layout">
        <aside className="login-story" aria-label="Tentang SITARA">
          <a className="login-brand" href="#dashboard" aria-label="SITARA">
            <span className="brand-mark">S</span>
            <span>
              <strong>SITARA</strong>
              <small>Sistem Informasi Tindak Lanjut dan Arsip Rapat</small>
            </span>
          </a>
          <div className="login-story-copy">
            <p className="login-story-kicker">SATU ALUR KERJA RAPIM</p>
            <h2>
              Rapat tertata.
              <br />
              Tindak lanjut terarah.
            </h2>
            <p>
              Catat keputusan, pantau progres, dan temukan kembali hasil rapat dalam satu ruang
              kerja.
            </p>
          </div>
          <ol className="login-workflow" aria-label="Alur kerja SITARA">
            <li>
              <span>01</span>
              <div>
                <strong>Rapat</strong>
                <small>Agenda dan notulensi</small>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>Keputusan</strong>
                <small>Ringkasan yang terhubung</small>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>Tindak lanjut</strong>
                <small>PIC, status, dan tenggat</small>
              </div>
            </li>
          </ol>
          <p className="login-story-footer">Akses dan informasi mengikuti peran pengguna.</p>
        </aside>

        <section className="login-card" aria-labelledby="login-title">
          <div className="login-heading">
            <p className="eyebrow">RUANG KERJA DIGITAL</p>
            <h1 id="login-title">Masuk ke SITARA</h1>
            <p>Gunakan akun yang diberikan oleh administrator aplikasi.</p>
          </div>

          {notice && (
            <div className="login-notice" role="alert">
              <span>{notice}</span>
              {retryable && (
                <button className="text-button" type="button" onClick={onRetry}>
                  Coba lagi
                </button>
              )}
            </div>
          )}
          {loginError && (
            <div className="login-error" role="alert">
              {loginError}
            </div>
          )}

          <form className="login-form" onSubmit={(event) => void handleSubmit(event)}>
            <label htmlFor="login-email">Email</label>
            <input
              id="login-email"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              disabled={submitting}
            />

            <label htmlFor="login-password">Kata sandi</label>
            <div className="password-field">
              <input
                id="login-password"
                name="password"
                autoComplete="current-password"
                type={passwordVisible ? 'text' : 'password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                disabled={submitting}
              />
              <button
                className="password-toggle"
                type="button"
                aria-label={passwordVisible ? 'Sembunyikan kata sandi' : 'Tampilkan kata sandi'}
                aria-pressed={passwordVisible}
                onClick={() => setPasswordVisible((visible) => !visible)}
                disabled={submitting}
              >
                {passwordVisible ? 'Sembunyikan' : 'Tampilkan'}
              </button>
            </div>

            <button className="login-submit" type="submit" disabled={submitting}>
              {submitting ? 'Memverifikasi...' : 'Masuk'}
            </button>
          </form>
          <p className="login-security-note">
            Sesi Anda dilindungi dan dikelola oleh server SITARA.
          </p>
        </section>
      </div>
    </main>
  );
}

export default LoginPage;
