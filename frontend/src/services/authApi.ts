import api from './api';
import { authenticationEpoch, loginBrowserSession, logoutBrowserSession, setLegacyAuthentication } from './browserSession';

export interface User {
  id: number;
  username: string;
  display_name?: string | null;
  email: string;
  avatar: string | null;
  is_active: boolean;
  role: string;
  roles?: string[];
  created_at: string | null;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface RegisterPayload {
  username: string;
  display_name?: string;
  email: string;
  password: string;
}

export const authApi = {
  login: async (data: LoginPayload) => {
    const session = await loginBrowserSession(data);
    if (session) return { data: session };
    const started = authenticationEpoch();
    const result = await api.post<{ access_token: string; token_type: string }>('/auth/login', data);
    setLegacyAuthentication(result.data.access_token, started);
    return result;
  },

  register: (data: RegisterPayload) =>
    api.post<{ access_token: string; token_type: string }>('/auth/register', data),

  getMe: () =>
    api.get<User>('/auth/me'),

  logout: logoutBrowserSession,
};
