import { NextRequest } from 'next/server';

const actions = new Set(['policy', 'login', 'refresh', 'activity', 'logout', 'logout-all']);

async function proxy(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  const { action } = await context.params;
  if (!actions.has(action) || (request.method === 'GET') !== (action === 'policy')) {
    return Response.json({ detail: 'Not found' }, { status: 404 });
  }
  const origin = request.headers.get('origin') || request.nextUrl.origin;
  let matchesHost = false;
  try {
    const parsed = new URL(origin);
    matchesHost = parsed.origin === origin && parsed.host === (request.headers.get('host') || request.nextUrl.host);
  } catch { /* Reject invalid and opaque origins. */ }
  if (request.method !== 'GET' && (!matchesHost
    || request.headers.get('x-session-request') !== '1')) {
    return Response.json({ detail: 'session_origin_rejected' }, { status: 403 });
  }
  const base = process.env.BACKEND_ORIGIN || 'http://localhost:8000';
  try {
    const body = request.method === 'GET' ? undefined : await request.text();
    if (body && body.length > 16384) return Response.json({ detail: 'Request too large' }, { status: 413 });
    const upstream = await fetch(`${base}/api/v1/auth/session/${action}`, {
      method: request.method,
      headers: {
        'Content-Type': 'application/json', Origin: origin, 'X-Session-Request': '1',
        Cookie: request.cookies.get('creative_refresh')?.value
          ? `creative_refresh=${encodeURIComponent(request.cookies.get('creative_refresh')!.value)}` : '',
        Authorization: request.headers.get('authorization') || '',
      },
      body,
      cache: 'no-store', signal: AbortSignal.timeout(15000),
    });
    const headers = new Headers({ 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    for (const cookie of upstream.headers.getSetCookie()) headers.append('Set-Cookie', cookie);
    return new Response(await upstream.text(), { status: upstream.status, headers });
  } catch {
    return Response.json({ detail: '登录服务暂时不可用，请稍后重试' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
}

export const GET = proxy;
export const POST = proxy;
