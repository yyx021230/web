import React, { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { authApi, type User } from '@/services/authApi';
import { notifyAuthStateChanged, requestAuthentication } from '@/lib/auth-events';
import { forgetLocalAuthentication, reportUserActivity } from '@/services/browserSession';
import { AuthRouteGate, AuthSessionProvider, useAuthSession } from './AuthSession';

const { push, replace } = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({ usePathname: () => '/ai', useRouter: () => ({ push, replace }) }));
vi.mock('@/services/authApi', () => ({ authApi: { getMe: vi.fn(), login: vi.fn(), logout: vi.fn() } }));
vi.mock('@/services/browserSession', () => ({ forgetLocalAuthentication: vi.fn(),
  isBrowserSession: () => localStorage.getItem('creative_auth_mode') === 'session',
  observeSessionChanges: () => () => {}, reportUserActivity: vi.fn().mockResolvedValue(undefined) }));

const user = { id: 1, username: 'user', role: 'viewer', roles: ['viewer'] } as User;
let host: HTMLDivElement, root: Root;
function Draft() {
  const [text, setText] = useState('尚未提交的创作内容');
  return <textarea aria-label="创作草稿" value={text} onChange={event => setText(event.target.value)} />;
}
function Identity() {
  const { user, checking, logout, verificationError } = useAuthSession();
  return <><output aria-label="当前身份">{checking ? 'checking' : user?.username || 'anonymous'}</output>
    <button onClick={logout}>退出验证</button><span>{verificationError}</span></>;
}

async function fillLogin() {
  const inputs = document.querySelectorAll<HTMLInputElement>('[role="dialog"] input');
  await act(async () => {
    for (const [index, value] of ['user', 'password123'].entries()) {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(inputs[index], value);
      inputs[index].dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
}
async function render() {
  await act(async () => root.render(<AuthSessionProvider><AuthRouteGate><Draft /></AuthRouteGate></AuthSessionProvider>));
}
beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.mocked(reportUserActivity).mockResolvedValue(undefined);
  localStorage.setItem('token', 'legacy');
  vi.mocked(authApi.getMe).mockResolvedValue({ data: user } as never);
  vi.mocked(authApi.login).mockResolvedValue({ data: { access_token: 'new' } } as never);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals();
});

describe('authentication state and mounted drafts', () => {
  it('ignores a late initial identity response after another tab logs out', async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(authApi.getMe).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }) as never);
    await act(async () => root.render(<AuthSessionProvider><Identity /></AuthSessionProvider>));
    await act(async () => {
      localStorage.removeItem('token');
      localStorage.removeItem('app_current_user');
      localStorage.setItem('creative_auth_mode', 'logged-out');
      notifyAuthStateChanged();
    });
    await act(async () => finish({ data: user }));
    expect(localStorage.getItem('app_current_user')).toBeNull();
    expect(host.querySelector('output')?.textContent).toBe('anonymous');
  });

  it('does not restore identity when another tab logs out during login verification', async () => {
    await act(async () => root.render(<AuthSessionProvider><Identity /></AuthSessionProvider>));
    await act(async () => requestAuthentication({ next: '/ai' }));
    await fillLogin();
    let finish!: (value: unknown) => void;
    vi.mocked(authApi.getMe).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }) as never);
    await act(async () => document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    await act(async () => {
      localStorage.removeItem('token');
      localStorage.removeItem('app_current_user');
      localStorage.setItem('creative_auth_mode', 'logged-out');
      notifyAuthStateChanged();
    });
    await act(async () => finish({ data: user }));
    expect(localStorage.getItem('app_current_user')).toBeNull();
    expect(host.querySelector('output')?.textContent).toBe('anonymous');
  });

  it('keeps a rejected legacy credential separate from browser-session expiry', async () => {
    vi.mocked(authApi.getMe).mockRejectedValueOnce(Object.assign(new Error('invalid'), { status: 401 }));
    await act(async () => root.render(<AuthSessionProvider><Identity /></AuthSessionProvider>));
    expect(forgetLocalAuthentication).toHaveBeenCalledWith('legacy-expired');
  });

  it('marks a rejected browser session as expired instead of legacy', async () => {
    localStorage.setItem('creative_auth_mode', 'session');
    vi.mocked(authApi.getMe).mockRejectedValueOnce(Object.assign(new Error('invalid'), { status: 401 }));
    await act(async () => root.render(<AuthSessionProvider><Identity /></AuthSessionProvider>));
    expect(forgetLocalAuthentication).toHaveBeenCalledWith('expired');
  });

  it('does not count mounting a hidden page as foreground activity', async () => {
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    await render();
    expect(reportUserActivity).not.toHaveBeenCalled();
  });

  it('ignores synthetic input events when recording foreground activity', async () => {
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    await render();
    expect(reportUserActivity).toHaveBeenCalledTimes(1);
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 70000);
    await act(async () => window.dispatchEvent(new Event('keydown')));
    expect(reportUserActivity).toHaveBeenCalledTimes(1);
  });

  it('waits for explicit logout confirmation and preserves the offline retry feedback', async () => {
    let fail!: (error: Error) => void;
    vi.mocked(authApi.logout).mockImplementationOnce(() => {
      localStorage.removeItem('token');
      localStorage.removeItem('app_current_user');
      localStorage.setItem('creative_auth_mode', 'logout-pending');
      notifyAuthStateChanged();
      return new Promise((_resolve, reject) => { fail = reject; });
    });
    await act(async () => root.render(<AuthSessionProvider><Identity /></AuthSessionProvider>));
    await act(async () => host.querySelector('button')!.click());
    expect(host.querySelector('output')?.textContent).toBe('checking');
    await act(async () => fail(new Error('offline')));
    expect(host.querySelector('output')?.textContent).toBe('anonymous');
    expect(host.textContent).toContain('服务器会话撤销未确认');
  });

  it('retains cached identity on a temporary /me failure', async () => {
    localStorage.setItem('app_current_user', JSON.stringify(user));
    vi.mocked(authApi.getMe).mockRejectedValueOnce(Object.assign(new Error('offline'), { status: 503 }));
    await render();
    expect(localStorage.getItem('token')).toBe('legacy');
    expect(host.querySelector('textarea')?.value).toBe('尚未提交的创作内容');
    expect(authApi.logout).not.toHaveBeenCalled();
  });

  it('shows retry rather than login when identity cannot be verified due to a network fault', async () => {
    vi.mocked(authApi.getMe).mockRejectedValueOnce(Object.assign(new Error('offline'), { status: 503 }));
    await render();
    expect(host.textContent).toContain('登录信息未清除');
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await act(async () => host.querySelector('button')!.click());
    expect(host.querySelector('textarea')).not.toBeNull();
  });

  it('keeps the same draft mounted through reauthentication without a full reload', async () => {
    await render();
    const draft = host.querySelector('textarea');
    await act(async () => requestAuthentication({ next: '/ai' }));
    expect(host.querySelector('textarea')).toBe(draft);
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    const inputs = document.querySelectorAll<HTMLInputElement>('[role="dialog"] input');
    await act(async () => {
      for (const [index, value] of ['user', 'password123'].entries()) {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(inputs[index], value);
        inputs[index].dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await act(async () => document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    expect(authApi.login).toHaveBeenCalledWith({ username: 'user', password: 'password123' });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(host.querySelector('textarea')).toBe(draft);
    expect(draft?.value).toBe('尚未提交的创作内容');
    expect(push).not.toHaveBeenCalled();
  });
});
