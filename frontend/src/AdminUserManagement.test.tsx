import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AuthenticatedUser } from './api';
import AdminUserManagement from './AdminUserManagement';

const superAdmin: AuthenticatedUser = {
  id: '10000000-0000-4000-8000-000000000001',
  email: 'admin@example.test',
  full_name: 'Admin SITARA',
  roles: ['SUPER_ADMIN'],
};

const warekAccount = {
  id: '20000000-0000-4000-8000-000000000001',
  email: 'warek@example.test',
  full_name: 'Nama Warek Sintetis',
  job_title: 'Wakil Rektor I Bidang Akademik',
  roles: ['WAREK'],
  is_active: true,
  must_change_password: false,
  created_at: '2026-11-20T08:00:00Z',
};

const inactiveAccount = {
  id: '20000000-0000-4000-8000-000000000002',
  email: 'sekretariat@example.test',
  full_name: 'Nama Sekretariat Sintetis',
  job_title: 'Direktur Sekretariat',
  roles: ['SEKRETARIAT'],
  is_active: false,
  must_change_password: true,
  created_at: '2026-11-20T08:00:00Z',
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.cookie = 'sitara_csrf=; Max-Age=0; Path=/';
});

describe('Super Admin account management', () => {
  it('does not request or show managed accounts to non-Super Admin users', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render(
      <AdminUserManagement
        authenticatedUser={{ ...superAdmin, roles: ['SEKRETARIAT'] }}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Halaman ini hanya tersedia untuk Super Admin.',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('lists account identity, role, activation, and forced-password state from the API', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ items: [warekAccount, inactiveAccount], total: 2 }),
      ),
    );
    render(<AdminUserManagement authenticatedUser={superAdmin} />);

    const table = await screen.findByRole('table', { name: 'Daftar akun SITARA' });
    const warekRow = within(table).getByRole('row', { name: /warek@example\.test/ });
    const inactiveRow = within(table).getByRole('row', {
      name: /sekretariat@example\.test/,
    });

    expect(warekRow).toHaveTextContent('Nama Warek Sintetis');
    expect(warekRow).toHaveTextContent('warek@example.test');
    expect(warekRow).toHaveTextContent('Wakil Rektor I Bidang Akademik');
    expect(warekRow).toHaveTextContent('Aktif');
    expect(warekRow).toHaveTextContent('Kata sandi sudah diperbarui');
    expect(inactiveRow).toHaveTextContent('Nonaktif');
    expect(inactiveRow).toHaveTextContent('Perlu ganti kata sandi');
  });

  it('creates an account and reveals its temporary password only until dismissed', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=synthetic-csrf; Path=/';
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/v1/admin/users' && !init?.method) {
        return jsonResponse({ items: [], total: 0 });
      }
      if (path === '/api/v1/admin/users' && init?.method === 'POST') {
        return jsonResponse(
          {
            user: {
              ...warekAccount,
              email: 'warek-baru@example.test',
              full_name: 'Warek Baru Sintetis',
            },
            temporary_password: 'synthetic-temporary-password',
          },
          201,
        );
      }
      throw new Error(`Unexpected admin request: ${path}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<AdminUserManagement authenticatedUser={superAdmin} />);

    await user.click(await screen.findByRole('button', { name: 'Tambah akun' }));
    await user.type(screen.getByLabelText('Nama lengkap'), 'Warek Baru Sintetis');
    await user.type(screen.getByLabelText('Email'), 'warek-baru@example.test');
    await user.selectOptions(screen.getByLabelText('Peran'), 'WAREK');
    await user.selectOptions(
      screen.getByLabelText('Jabatan'),
      'Wakil Rektor I Bidang Akademik',
    );
    await user.click(screen.getByRole('button', { name: 'Buat akun' }));

    expect(window.confirm).toHaveBeenCalled();
    expect(await screen.findByText('synthetic-temporary-password')).toBeInTheDocument();
    const createRequest = fetchMock.mock.calls.find(
      ([path, init]) => String(path) === '/api/v1/admin/users' && init?.method === 'POST',
    );
    expect(createRequest?.[1]?.body).toBe(
      JSON.stringify({
        email: 'warek-baru@example.test',
        full_name: 'Warek Baru Sintetis',
        job_title: 'Wakil Rektor I Bidang Akademik',
        role_code: 'WAREK',
      }),
    );
    expect(new Headers(createRequest?.[1]?.headers).get('X-CSRF-Token')).toBe(
      'synthetic-csrf',
    );

    await user.click(screen.getByRole('button', { name: 'Sembunyikan kata sandi sementara' }));
    expect(screen.queryByText('synthetic-temporary-password')).not.toBeInTheDocument();
  });

  it('confirms activation, deactivation, and password reset before calling their endpoints', async () => {
    const user = userEvent.setup();
    document.cookie = 'sitara_csrf=synthetic-csrf; Path=/';
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/v1/admin/users' && !init?.method) {
        return jsonResponse({ items: [warekAccount, inactiveAccount], total: 2 });
      }
      if (
        path === `/api/v1/admin/users/${inactiveAccount.id}` &&
        init?.method === 'PATCH'
      ) {
        return jsonResponse({ ...inactiveAccount, is_active: true });
      }
      if (
        path === `/api/v1/admin/users/${warekAccount.id}` &&
        init?.method === 'PATCH'
      ) {
        return jsonResponse({ ...warekAccount, is_active: false });
      }
      if (
        path === `/api/v1/admin/users/${warekAccount.id}/reset-password` &&
        init?.method === 'POST'
      ) {
        return jsonResponse({ temporary_password: 'synthetic-reset-password' });
      }
      throw new Error(`Unexpected admin request: ${path}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<AdminUserManagement authenticatedUser={superAdmin} />);

    const inactiveRow = await screen.findByRole('row', {
      name: /sekretariat@example\.test/,
    });
    await user.click(within(inactiveRow).getByRole('button', { name: 'Aktifkan kembali' }));
    expect(within(inactiveRow).getByText('Aktif')).toBeInTheDocument();

    const warekRow = screen.getByRole('row', { name: /warek@example\.test/ });
    await user.click(within(warekRow).getByRole('button', { name: 'Nonaktifkan' }));
    expect(within(warekRow).getByText('Nonaktif')).toBeInTheDocument();
    await user.click(within(warekRow).getByRole('button', { name: 'Reset kata sandi' }));

    expect(window.confirm).toHaveBeenCalledTimes(3);
    expect(await screen.findByText('synthetic-reset-password')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/admin/users/${inactiveAccount.id}`,
      expect.objectContaining({ method: 'PATCH' }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/admin/users/${warekAccount.id}`,
      expect.objectContaining({ method: 'PATCH' }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/admin/users/${warekAccount.id}/reset-password`,
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
