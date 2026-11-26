import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  getCurrentUser,
  login,
  logout,
  SESSION_EXPIRED_EVENT,
  type AuthenticatedUser,
} from './api';

type AuthStatus = 'checking' | 'authenticated' | 'anonymous' | 'unavailable';

const SESSION_EXPIRED_MESSAGE = 'Sesi Anda telah berakhir. Silakan masuk kembali.';
const SESSION_CHECK_MESSAGE =
  'Sesi tidak dapat diverifikasi. Periksa koneksi server lalu coba lagi.';

export function useAuth() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>('checking');
  const [message, setMessage] = useState<string | null>(null);

  const checkSession = useCallback(async () => {
    setStatus('checking');
    setMessage(null);
    try {
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      setStatus('authenticated');
    } catch (error) {
      setUser(null);
      if (error instanceof ApiError && error.status === 401) {
        setStatus('anonymous');
      } else {
        setStatus('unavailable');
        setMessage(SESSION_CHECK_MESSAGE);
      }
    }
  }, []);

  useEffect(() => {
    const handleSessionExpired = () => {
      setUser(null);
      setStatus('anonymous');
      setMessage(SESSION_EXPIRED_MESSAGE);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    void checkSession();
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
  }, [checkSession]);

  const signIn = useCallback(async (email: string, password: string) => {
    const loginUser = await login(email, password);
    try {
      const currentUser = await getCurrentUser();
      if (currentUser.id !== loginUser.id) {
        throw new ApiError('Identitas sesi tidak sesuai dengan hasil login.', 401);
      }
      setUser(currentUser);
      setStatus('authenticated');
      setMessage(null);
    } catch (error) {
      setUser(null);
      setStatus('anonymous');
      try {
        await logout();
      } catch {
        setMessage(
          'Login tidak dapat diverifikasi dan sesi server belum dapat dipastikan tertutup.',
        );
      }
      throw error;
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await logout();
      setUser(null);
      setStatus('anonymous');
      setMessage(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setUser(null);
        setStatus('anonymous');
        setMessage(SESSION_EXPIRED_MESSAGE);
        return;
      }
      throw error;
    }
  }, []);

  return {
    user,
    status,
    message,
    checkSession,
    signIn,
    signOut,
  };
}
