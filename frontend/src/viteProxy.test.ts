import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('Vite API proxy', () => {
  it('uses an explicit target for an isolated local demo', async () => {
    vi.stubEnv('VITE_API_PROXY_TARGET', 'http://127.0.0.1:8100');
    vi.resetModules();

    const { default: config } = await import('../vite.config');
    const resolvedConfig = await (typeof config === 'function'
      ? config({
          command: 'serve',
          mode: 'development',
          isSsrBuild: false,
          isPreview: false,
        })
      : config);

    expect(resolvedConfig.server?.proxy).toMatchObject({
      '/api/v1': 'http://127.0.0.1:8100',
    });
  });

  it('uses the standard local API target when no override is provided', async () => {
    vi.stubEnv('VITE_API_PROXY_TARGET', '');
    vi.resetModules();

    const { default: config } = await import('../vite.config');
    const resolvedConfig = await (typeof config === 'function'
      ? config({
          command: 'serve',
          mode: 'development',
          isSsrBuild: false,
          isPreview: false,
        })
      : config);

    expect(resolvedConfig.server?.proxy).toMatchObject({
      '/api/v1': 'http://127.0.0.1:8000',
    });
  });
});
