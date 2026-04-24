import axios, { type AxiosInstance } from 'axios';

const api: AxiosInstance = axios.create({
  baseURL: '/api/backend',
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
        throw err;
      }
    }
    return response;
  },
  (error) => {
    const isAuthEndpoint = error.config?.url?.includes('/auth/');
    if (error.response?.status === 401 && !isAuthEndpoint) {
      localStorage.removeItem('token');
      localStorage.removeItem('app_current_user');
      window.location.href = '/';
    }
    // Prefer detail from FastAPI HTTPException, or message from envelope
    const message = error.response?.data?.detail || error.response?.data?.message || error.message || '请求失败';
    console.error('[API Error]', message);
    return Promise.reject(new Error(message));
  }
);

export default api;
