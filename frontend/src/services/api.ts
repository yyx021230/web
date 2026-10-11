import axios, { type AxiosInstance } from 'axios';
import { toast } from '@/lib/toast';
import { requestAuthentication } from '@/lib/auth-events';
import { authenticationRequired, getAccessToken, isBrowserSession } from './browserSession';

let lastAuthNoticeAt = 0;

function resolveApiBaseURL(): string {
  if (process.env.NEXT_PUBLIC_API_BASE) {
    return process.env.NEXT_PUBLIC_API_BASE;
  }

  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    const isLocalDevHost = host === 'localhost' || host === '127.0.0.1';
    if (isLocalDevHost) {
      // Local XHS publish requests can run for 50s+.
      // In `next dev`, the `/api/backend` rewrite/proxy may terminate the upstream
      // connection around 30s and surface a generic 500, even though FastAPI keeps
      // running and the publish eventually succeeds. For local development we
      // therefore bypass the Next proxy and call FastAPI directly.
      // Do not change this back to `/api/backend` unless the local long-request
      // proxy behavior has been re-verified end-to-end.
      return 'http://127.0.0.1:8000/api/v1';
    }
  }

  return '/api/backend';
}

export function resolveDirectApiBaseURL(): string {
  if (process.env.NEXT_PUBLIC_API_BASE) {
    return process.env.NEXT_PUBLIC_API_BASE;
  }

  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol;
    const host = window.location.hostname;
    return `${protocol}//${host}:8000/api/v1`;
  }

  return '/api/backend';
}

const api: AxiosInstance = axios.create({
  baseURL: resolveApiBaseURL(),
  timeout: 900000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
api.interceptors.request.use(
  async (config) => {
    const token = config.url === '/auth/login'
      ? null : await getAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor: unwrap { code, message, data } envelope
api.interceptors.response.use(
  (response) => {
    const body = response.data;
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) {
        response.data = body.data;
      } else {
        const msg = body.message || '请求失败';
        const err = new Error(msg) as Error & { status?: number; response?: { data?: unknown } };
        err.status = body.code;
        err.response = { data: body };
        toast.error(msg);
        throw err;
      }
    }
    return response;
  },
  async (error) => {
    if (axios.isCancel(error) || error?.code === 'ERR_CANCELED') {
      return Promise.reject(error);
    }
    const isAuthEndpoint = error.config?.url === '/auth/login';
    if (error.response?.status === 401 && isBrowserSession() && !isAuthEndpoint) {
      const config = error.config as typeof error.config & { sessionRetried?: boolean };
      if (!config?.sessionRetried) {
        try {
          await getAccessToken(true);
          // A rejected read is safe to repeat. Never replay a write implicitly.
          if (config && ['get', 'head'].includes((config.method || 'get').toLowerCase())) {
            config.sessionRetried = true;
            return api.request(config);
          }
        } catch (refreshError) {
          return Promise.reject(refreshError);
        }
      } else authenticationRequired();
    }
    if (error.response?.status === 401 && !isAuthEndpoint) {
      if (isBrowserSession()) {
        return Promise.reject(Object.assign(new Error('本次操作未提交，请确认后重新操作'), { status: 401 }));
      }
      localStorage.removeItem('token');
      localStorage.removeItem('app_current_user');
      const now = Date.now();
      if (now - lastAuthNoticeAt > 2000) {
        lastAuthNoticeAt = now;
        toast.error('登录已过期，请重新登录');
        requestAuthentication({
          next: `${window.location.pathname}${window.location.search}`,
          reason: '登录状态已过期，请重新登录后继续',
        });
      }
    }
    // Prefer detail from FastAPI HTTPException, or message from envelope
    const message = error.response?.data?.detail || error.response?.data?.message || error.message || '请求失败';
    console.error('[API Error]', message);
    // Keep the HTTP status when normalizing Axios errors. Callers such as the
    // AI task recovery flow need to distinguish a missing task (404) from a
    // temporary network failure and must not retry the former forever.
    const normalized = new Error(message) as Error & {
      status?: number;
      response?: { status?: number; data?: unknown };
    };
    normalized.status = error.response?.status ?? error.status;
    normalized.response = {
      status: error.response?.status,
      data: error.response?.data,
    };
    return Promise.reject(normalized);
  }
);

export default api;
