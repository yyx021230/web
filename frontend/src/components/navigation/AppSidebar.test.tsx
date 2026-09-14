import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AppSidebar from './AppSidebar';
import { AUTH_REQUIRED_EVENT, type AuthRequiredDetail } from '@/lib/auth-events';

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

describe('workspace sidebar', () => {
  it('preserves every destination and groups navigation without a global header', async () => {
    await act(async () => root.render(<AppSidebar pathname="/ai" />));
    expect(host.querySelectorAll('nav a')).toHaveLength(8);
    expect(host.querySelector('nav a')?.getAttribute('href')).toBe('/prompts');
    expect(host.querySelector('a[href="/editor"], a[href="/library"], a[href="/templates"]')).toBeNull();
    expect(Array.from(host.querySelectorAll('nav [role="group"]')).map(el => el.getAttribute('aria-label'))).toEqual(['创作', '资源', '运营']);
    expect(host.querySelector('[aria-current="page"]')?.getAttribute('href')).toBe('/ai');
    expect(host.querySelector('header')).toBeNull();
    expect(host.querySelector('a[aria-label="AI Creative Studio"]')?.getAttribute('href')).toBe('/prompts');
    expect(host.querySelector('img[alt="Creative Studio"]')?.getAttribute('src')).toBe('/brand/creative-studio-integrated-v2.png');
    expect(host.querySelector('img[src="/brand/creative-studio-glass-mark.png"]')).not.toBeNull();
    expect(host.querySelector('a[aria-label="AI Creative Studio"] span')).toBeNull();
    expect(host.querySelector('button[aria-label="登录"]')?.textContent).toContain('登录');
  });

  it('keeps public discovery open and requests login for protected destinations', async () => {
    let requested: AuthRequiredDetail | undefined;
    window.addEventListener(AUTH_REQUIRED_EVENT, event => {
      requested = (event as CustomEvent<AuthRequiredDetail>).detail;
    }, { once: true });
    await act(async () => root.render(<AppSidebar pathname="/prompts" />));
    await act(async () => (host.querySelector('a[href="/gallery"]') as HTMLAnchorElement).click());
    expect(requested).toEqual({ next: '/gallery', reason: '登录后进入图库' });
    expect(host.querySelector('a[href="/prompts"]')).not.toBeNull();
  });

  it.each([['/posts/123', '/publish'], ['/workflows/hermes', '/workflows'], ['/ad-insights', '/ad-insights']])('selects the correct navigation for %s', async (pathname, href) => {
    await act(async () => root.render(<AppSidebar pathname={pathname} />));
    expect(host.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    expect(host.querySelector('[aria-current="page"]')?.getAttribute('href')).toBe(href);
  });

  it('preserves the collapsed preference', async () => {
    await act(async () => root.render(<AppSidebar pathname="/ai" />));
    await act(async () => (host.querySelector('button[aria-label="收起侧边栏"]') as HTMLButtonElement).click());
    expect(localStorage.getItem('app_sidebar_collapsed')).toBe('true');
    expect(host.querySelector('button[aria-label="展开侧边栏"]')?.getAttribute('aria-expanded')).toBe('false');
    await act(async () => root.render(<AppSidebar pathname="/gallery" />));
    expect(host.querySelector('button[aria-label="展开侧边栏"]')).not.toBeNull();
  });

  it.each([['admin', true], ['viewer', false]])('shows account actions with correct %s access', async (role, admin) => {
    localStorage.setItem('app_current_user', JSON.stringify({ username: 'test_login', display_name: '测试用户', roles: [role] }));
    await act(async () => root.render(<AppSidebar pathname="/ai" />));
    const trigger = host.querySelector('button[aria-label="账户菜单：测试用户"]')!;
    expect(trigger).not.toBeNull();
    await act(async () => { trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });
    expect(Boolean(document.querySelector('[role="menu"] a[href="/admin"]'))).toBe(admin);
    expect(document.querySelector('[role="menu"]')?.textContent).toContain('退出登录');
  });
});
