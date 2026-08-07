import axios, { type AxiosInstance } from 'axios';
import { toast } from '@/lib/toast';

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
  (config) => {
    const token = localStorage.getItem('token');
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
  (error) => {
    if (axios.isCancel(error) || error?.code === 'ERR_CANCELED') {
      return Promise.reject(error);
    }
    const isAuthEndpoint = error.config?.url?.includes('/auth/');
    if (error.response?.status === 401 && !isAuthEndpoint) {
      localStorage.removeItem('token');
      localStorage.removeItem('app_current_user');
      toast.error('登录已过期，请重新登录');
      window.location.href = '/';
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
    normalized.status = error.response?.status;
    normalized.response = {
      status: error.response?.status,
      data: error.response?.data,
    };
    return Promise.reject(normalized);
  }
);

export default api;
