import api from './api';

export interface User {
  id: number;
  username: string;
  email: string;
  avatar: string | null;
  is_active: boolean;
  created_at: string | null;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface RegisterPayload {
  username: string;
  email: string;
  password: string;
}

export const authApi = {
  login: (data: LoginPayload) =>
    api.post<{ access_token: string; token_type: string }>('/auth/login', data),

  register: (data: RegisterPayload) =>
    api.post<{ access_token: string; token_type: string }>('/auth/register', data),

  getMe: () =>
    api.get<User>('/auth/me'),

  logout: () => {
    localStorage.removeItem('token');
    localStorage.removeItem('app_current_user');
  },
};
