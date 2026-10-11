import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';
import api from './api';
import { forgetLocalAuthentication, getAccessToken, loginBrowserSession } from './browserSession';
import { authApi } from './authApi';

const originalAdapter = api.defaults.adapter;

describe('business request session integration', () => {
  beforeEach(async () => {
    forgetLocalAuthentication();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ enabled: true }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ access_token: 'old', expires_in: 1800 }) }));
    await loginBrowserSession({ username: 'user', password: 'password123' });
  });
  afterEach(() => {
    api.defaults.adapter = originalAdapter;
    vi.unstubAllGlobals();
  });

  function unauthorized(config: InternalAxiosRequestConfig) {
    return new AxiosError('unauthorized', 'ERR_BAD_REQUEST', config, {},
      { status: 401, statusText: 'Unauthorized', data: { detail: 'Invalid token' }, headers: {}, config });
  }

  it('renews and repeats a rejected GET once', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ access_token: 'new', expires_in: 1800 }) }));
    const adapter = vi.fn().mockImplementationOnce(config => Promise.reject(unauthorized(config)))
      .mockImplementationOnce(config => Promise.resolve({ status: 200, data: { code: 0, data: { value: 1 } }, headers: {}, config }));
    api.defaults.adapter = adapter;
    expect((await api.get('/some-read')).data).toEqual({ value: 1 });
    expect(adapter).toHaveBeenCalledTimes(2);
    expect(adapter.mock.calls[1][0].headers.Authorization).toBe('Bearer new');
  });

  it.each(['post', 'put', 'patch', 'delete'])('never replays %s after rejection', async method => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ access_token: 'new', expires_in: 1800 }) }));
    const adapter = vi.fn().mockImplementation(config => Promise.reject(unauthorized(config)));
    api.defaults.adapter = adapter;
    await expect(api.request({ method, url: '/mutation', data: { request_id: 'original' } })).rejects.toMatchObject({ status: 401 });
    expect(adapter).toHaveBeenCalledTimes(1);
  });

  it('keeps administrator authentication when creating a user, without impersonating the created user', async () => {
    const adapter = vi.fn().mockImplementation(config => Promise.resolve({ status: 200,
      data: { access_token: 'new-user-token', token_type: 'bearer' }, headers: {}, config }));
    api.defaults.adapter = adapter;
    await authApi.register({ username: 'new-user', email: 'new@example.com', password: 'password123' });
    expect(adapter.mock.calls[0][0].headers.Authorization).toBe('Bearer old');
    expect(await getAccessToken()).toBe('old');
  });

  it('does not turn a renewal network failure into logout', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    api.defaults.adapter = config => Promise.reject(unauthorized(config));
    await expect(api.get('/read')).rejects.toMatchObject({ status: 503 });
    expect(localStorage.getItem('creative_auth_mode')).toBe('session');
  });

  it.each([403, 503])('does not refresh or log out on HTTP %s', async status => {
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    api.defaults.adapter = config => Promise.reject(new AxiosError('down', 'ERR_BAD_RESPONSE', config, {},
      { status, statusText: 'down', data: {}, headers: new AxiosHeaders(), config }));
    await expect(api.get('/read')).rejects.toMatchObject({ status });
    expect(fetcher).not.toHaveBeenCalled();
    expect(localStorage.getItem('creative_auth_mode')).toBe('session');
  });
});
