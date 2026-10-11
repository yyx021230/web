import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  forgetLocalAuthentication, getAccessToken, isBrowserSession, loginBrowserSession,
  logoutBrowserSession, observeSessionChanges, reportUserActivity, setLegacyAuthentication,
} from './browserSession';

function response(data: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => data };
}

async function login(expires = 1800) {
  const fetcher = vi.fn().mockResolvedValueOnce(response({ enabled: true }))
    .mockResolvedValueOnce(response({ access_token: 'browser-token', expires_in: expires }));
  vi.stubGlobal('fetch', fetcher);
  await loginBrowserSession({ username: 'user', password: 'password123' });
  return fetcher;
}

describe('browser session lifecycle', () => {
  beforeEach(() => {
    forgetLocalAuthentication();
    vi.useRealTimers();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('stores no browser bearer or refresh token in localStorage', async () => {
    await login();
    expect(isBrowserSession()).toBe(true);
    expect(localStorage.getItem('token')).toBeNull();
    expect(await getAccessToken()).toBe('browser-token');
    expect(JSON.stringify(localStorage)).not.toContain('browser-token');
  });

  it('only falls back to legacy when the server explicitly disables sessions', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ enabled: false })));
    expect(await loginBrowserSession({ username: 'user', password: 'password123' })).toBeNull();
    setLegacyAuthentication('legacy-token');
    expect(await getAccessToken()).toBe('legacy-token');
  });

  it.each([403, 500, 503])('does not fall back on policy/login error %s', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ detail: 'unavailable' }, status)));
    await expect(loginBrowserSession({ username: 'user', password: 'password123' })).rejects.toMatchObject({ status });
    expect(localStorage.getItem('token')).toBeNull();
  });

  it('coalesces 10 simultaneous renewals into one request', async () => {
    const fetcher = await login(1);
    fetcher.mockResolvedValue(response({ access_token: 'new-token', expires_in: 1800 }));
    const result = await Promise.all(Array.from({ length: 10 }, () => getAccessToken()));
    expect(result).toEqual(Array(10).fill('new-token'));
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls[2][0]).toBe('/api/auth-session/refresh');
  });

  it('retains identity and the same nonce after a lost refresh response', async () => {
    const fetcher = await login(1);
    localStorage.setItem('app_current_user', '{"id":1}');
    fetcher.mockRejectedValueOnce(new Error('offline'));
    await expect(getAccessToken()).rejects.toMatchObject({ status: 503 });
    const nonce = JSON.parse(fetcher.mock.calls[2][1].body).request_id;
    expect(isBrowserSession()).toBe(true);
    expect(localStorage.getItem('app_current_user')).toBe('{"id":1}');
    fetcher.mockResolvedValueOnce(response({ access_token: 'restored', expires_in: 1800 }));
    expect(await getAccessToken()).toBe('restored');
    expect(JSON.parse(fetcher.mock.calls[3][1].body).request_id).toBe(nonce);
  });

  it('does not count a silent renewal as foreground activity', async () => {
    const fetcher = await login(1);
    fetcher.mockResolvedValue(response({ access_token: 'new-token', expires_in: 1800 }));
    await getAccessToken();
    expect(fetcher.mock.calls.some(call => call[0].includes('activity'))).toBe(false);
    await reportUserActivity();
    expect(fetcher.mock.calls[3][0]).toBe('/api/auth-session/activity');
  });

  it('cannot resurrect credentials when logout races a refresh', async () => {
    const fetcher = await login(1);
    let finish!: (value: unknown) => void;
    fetcher.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const pending = getAccessToken();
    fetcher.mockResolvedValueOnce(response({ ok: true }));
    await logoutBrowserSession();
    finish(response({ access_token: 'late-token', expires_in: 1800 }));
    await expect(pending).rejects.toMatchObject({ status: 409 });
    expect(await getAccessToken()).toBeNull();
    expect(isBrowserSession()).toBe(false);
  });

  it('serializes logout behind an in-flight refresh when Web Locks is available', async () => {
    let queue = Promise.resolve<unknown>(undefined);
    const request = vi.fn((_name: string, action: () => Promise<unknown>) => {
      const next = queue.then(action);
      queue = next.catch(() => undefined);
      return next;
    });
    vi.stubGlobal('navigator', { locks: { request } });
    const fetcher = await login(1);
    let finish!: (value: unknown) => void;
    fetcher.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const pending = getAccessToken();
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
    const rejection = expect(pending).rejects.toMatchObject({ status: 409 });
    fetcher.mockResolvedValueOnce(response({ ok: true }));
    const logout = logoutBrowserSession();
    expect(fetcher).toHaveBeenCalledTimes(3);
    finish(response({ access_token: 'late-token', expires_in: 1800 }));
    await rejection;
    await logout;
    expect(fetcher.mock.calls[3][0]).toBe('/api/auth-session/logout');
    expect(request.mock.calls.every(call => call[0] === 'creative-studio-session')).toBe(true);
    expect(await getAccessToken()).toBeNull();
  });

  it('keeps an offline logout pending and retries server revocation', async () => {
    const fetcher = await login();
    fetcher.mockRejectedValueOnce(new Error('offline'));
    await expect(logoutBrowserSession()).rejects.toMatchObject({ status: 503 });
    expect(localStorage.getItem('creative_auth_mode')).toBe('logout-pending');
    expect(await getAccessToken()).toBeNull();
    fetcher.mockResolvedValueOnce(response({ ok: true }));
    await logoutBrowserSession();
    expect(localStorage.getItem('creative_auth_mode')).toBe('logged-out');
    expect(fetcher.mock.calls.filter(call => call[0].endsWith('/logout'))).toHaveLength(2);
  });

  it('applies logout from another tab without restoring cached access', async () => {
    await login();
    const stop = observeSessionChanges();
    localStorage.setItem('creative_auth_mode', 'logged-out');
    window.dispatchEvent(new StorageEvent('storage', { key: 'creative_auth_mode' }));
    expect(await getAccessToken()).toBeNull();
    stop();
  });

  it('waits for an in-flight login response before revoking its cookie', async () => {
    let finish!: (value: unknown) => void;
    const fetcher = vi.fn().mockResolvedValueOnce(response({ enabled: true }))
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(response({ ok: true }));
    vi.stubGlobal('fetch', fetcher);
    const pending = loginBrowserSession({ username: 'user', password: 'password123' });
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
    const rejection = expect(pending).rejects.toMatchObject({ status: 409 });
    const logout = logoutBrowserSession();
    expect(fetcher).toHaveBeenCalledTimes(2);
    finish(response({ access_token: 'late', expires_in: 1800 }));
    await rejection;
    await logout;
    expect(fetcher.mock.calls[2][0]).toBe('/api/auth-session/logout');
    expect(await getAccessToken()).toBeNull();
  });
});
