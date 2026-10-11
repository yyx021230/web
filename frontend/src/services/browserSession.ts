import { notifyAuthStateChanged, requestAuthentication } from '@/lib/auth-events';

const MODE = 'creative_auth_mode';
const ATTEMPT = 'creative_refresh_attempt';
let accessToken: string | null = null;
let expiresAt = 0;
let epoch = 0;
let renewal: Promise<string> | null = null;
let loginInProgress: Promise<Token> | null = null;

type Token = { access_token: string; expires_in: number };
export type SessionError = Error & { status?: number };

function failure(message: string, status?: number): SessionError {
  return Object.assign(new Error(message), { status });
}

export function isBrowserSession() {
  return typeof window !== 'undefined' && localStorage.getItem(MODE) === 'session';
}

async function call<T>(action: string, data?: unknown, token?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/auth-session/${action}`, {
      method: action === 'policy' ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Session-Request': '1',
        ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: action === 'policy' ? undefined : JSON.stringify(data || {}),
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    throw failure('登录服务连接中断，请稍后重试', 503);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw failure(typeof body?.detail === 'string' ? body.detail
    : body?.message || '登录服务暂时不可用', response.status);
  return body?.code === 0 ? body.data : body;
}

function install(token: Token) {
  accessToken = token.access_token;
  expiresAt = Date.now() + token.expires_in * 1000;
}

async function withSessionLock<T>(action: () => Promise<T>): Promise<T> {
  return navigator.locks
    ? await navigator.locks.request('creative-studio-session', async () => await action())
    : await action();
}

export function forgetLocalAuthentication(mode = 'logged-out') {
  epoch += 1;
  accessToken = null;
  expiresAt = 0;
  localStorage.setItem(MODE, mode);
  localStorage.removeItem('token');
  localStorage.removeItem('app_current_user');
  localStorage.removeItem(ATTEMPT);
}

export function authenticationRequired() {
  if (localStorage.getItem(MODE)?.endsWith('expired')) return;
  const browser = isBrowserSession() || localStorage.getItem(MODE) === 'expired';
  forgetLocalAuthentication(browser ? 'expired' : 'legacy-expired');
  requestAuthentication({ next: `${window.location.pathname}${window.location.search}`,
    reason: '登录状态已失效，请重新登录后继续，已提交任务不会重新执行' });
}

function refreshNonce() {
  try {
    const saved = JSON.parse(localStorage.getItem(ATTEMPT) || 'null');
    if (saved && saved.until > Date.now() && /^[a-f0-9]{32}$/.test(saved.id)) return saved.id as string;
  } catch { /* Ignore an interrupted or old browser record. */ }
  const id = crypto.randomUUID().replaceAll('-', '');
  localStorage.setItem(ATTEMPT, JSON.stringify({ id, until: Date.now() + 25000 }));
  return id;
}

export async function getAccessToken(force = false): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  if (localStorage.getItem(MODE)?.endsWith('expired')) {
    throw failure('登录已失效，请重新登录后继续', 401);
  }
  if (!isBrowserSession()) return localStorage.getItem('token');
  if (!force && accessToken && expiresAt > Date.now() + 60000) return accessToken;
  if (renewal) return renewal;
  const started = epoch;
  const refresh = async () => {
    // Web Locks serializes rotations across tabs. The backend also uses CAS and
    // bounded idempotency for browsers without locks and lost HTTP responses.
    if (started !== epoch || !isBrowserSession()) throw failure('登录状态已变化', 409);
    let token: Token;
    try {
      token = await call<Token>('refresh', { request_id: refreshNonce() });
    } catch (error) {
      if ((error as SessionError).status === 401) authenticationRequired();
      throw error;
    }
    if (started !== epoch || !isBrowserSession()) throw failure('登录状态已变化', 409);
    install(token);
    return token.access_token;
  };
  renewal = withSessionLock(refresh);
  try { return await renewal; } finally { renewal = null; }
}

export async function loginBrowserSession(data: { username: string; password: string }): Promise<Token | null> {
  epoch += 1;
  const started = epoch;
  const policy = await call<{ enabled: boolean }>('policy');
  if (started !== epoch) throw failure('登录已取消，请重试', 409);
  if (!policy.enabled) return null;
  loginInProgress = withSessionLock(() => {
    if (started !== epoch) throw failure('登录已取消，请重试', 409);
    return call<Token>('login', data);
  });
  let token: Token;
  try { token = await loginInProgress; } finally { loginInProgress = null; }
  if (started !== epoch) throw failure('登录已取消，请重试', 409);
  localStorage.setItem(MODE, 'session');
  localStorage.removeItem('token');
  localStorage.removeItem(ATTEMPT);
  install(token);
  return token;
}

export function authenticationEpoch() { return epoch; }

export function setLegacyAuthentication(token: string, expectedEpoch = epoch) {
  if (expectedEpoch !== epoch) throw failure('登录已取消，请重试', 409);
  forgetLocalAuthentication('legacy');
  localStorage.setItem('token', token);
}

export async function logoutBrowserSession() {
  const login = loginInProgress;
  const session = isBrowserSession() || ['logout-pending', 'expired'].includes(localStorage.getItem(MODE) || '') || !!login;
  forgetLocalAuthentication(session ? 'logout-pending' : 'logged-out');
  notifyAuthStateChanged();
  if (session) {
    // A cancelled login response may still set a cookie. Wait for it before
    // revoking so an overlapping logout cannot leave that new session alive.
    if (login) await login.catch(() => undefined);
    await withSessionLock(() => call('logout'));
    localStorage.setItem(MODE, 'logged-out');
  }
}

export async function reportUserActivity() {
  if (!isBrowserSession()) return;
  const token = await getAccessToken();
  if (token) await call('activity', {}, token);
}

export function observeSessionChanges() {
  const changed = (event: StorageEvent) => {
    if (event.key !== MODE && event.key !== 'app_current_user') return;
    epoch += 1;
    accessToken = null;
    expiresAt = 0;
    notifyAuthStateChanged();
  };
  window.addEventListener('storage', changed);
  return () => window.removeEventListener('storage', changed);
}
