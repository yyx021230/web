import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { GET, POST } from './[action]/route';

const context = (action: string) => ({ params: Promise.resolve({ action }) });
function request(action: string, origin = 'http://localhost:3000', host?: string) {
  return new NextRequest(`http://localhost:3000/api/auth-session/${action}`, {
    method: 'POST', body: '{}', headers: { Origin: origin, 'X-Session-Request': '1',
      ...(host ? { Host: host } : {}), Cookie: 'creative_refresh=fake-test-cookie', Authorization: 'Bearer fake-test-access' },
  });
}
afterEach(() => vi.unstubAllGlobals());

describe('same-origin session gateway', () => {
  it('forwards only session endpoints and preserves cookie attributes', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200,
      headers: { 'Set-Cookie': 'creative_refresh=fake; HttpOnly; Secure; SameSite=Strict; Path=/api/auth-session' } }));
    vi.stubGlobal('fetch', fetcher);
    const result = await POST(request('refresh'), context('refresh'));
    expect(result.status).toBe(200);
    expect(result.headers.get('cache-control')).toBe('no-store');
    expect(result.headers.get('set-cookie')).toContain('HttpOnly; Secure; SameSite=Strict; Path=/api/auth-session');
    expect(fetcher.mock.calls[0][0]).toMatch(/\/api\/v1\/auth\/session\/refresh$/);
    expect(fetcher.mock.calls[0][1].headers.Cookie).toBe('creative_refresh=fake-test-cookie');
  });

  it.each(['https://evil.example', 'null', 'http://localhost:3000/path'])('rejects a cross-site origin %s', async origin => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    expect((await POST(request('login', origin), context('login'))).status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('accepts an HTTPS public host behind a local reverse proxy', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', fetcher);
    expect((await POST(request('login', 'https://app.example.com', 'app.example.com'), context('login'))).status).toBe(200);
    expect(fetcher.mock.calls[0][1].headers.Origin).toBe('https://app.example.com');
  });

  it('never forwards an arbitrary action or GET refresh', async () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    expect((await POST(request('anything'), context('anything'))).status).toBe(404);
    expect((await GET(new NextRequest('http://localhost:3000/api/auth-session/refresh'), context('refresh'))).status).toBe(404);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('returns a non-authentication failure when upstream is offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('private connection detail')));
    const result = await POST(request('refresh'), context('refresh'));
    expect(result.status).toBe(503);
    expect(await result.text()).not.toContain('private connection detail');
  });
});
