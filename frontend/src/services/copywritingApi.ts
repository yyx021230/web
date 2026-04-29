import api from './api';

export interface Copywriting {
  id: number;
  title: string;
  content: string;
  tags: string[];
  category: string | null;
  created_at: string;
}

export interface CopywritingListResponse {
  items: Copywriting[];
  total: number;
  page: number;
  limit: number;
}

export const copywritingApi = {
  getList: (params: { page?: number; limit?: number; category?: string; keyword?: string; owner?: boolean } = {}) => {
    const p: Record<string, unknown> = { page: 1, limit: 50, ...(params as Record<string, unknown>) };
    return api.get<CopywritingListResponse>('/copywritings', { params: p });
  },

  getById: (id: number) =>
    api.get<Copywriting>(`/copywritings/${id}`),

  create: (data: { title: string; content: string }) =>
    api.post('/copywritings', data),

  update: (id: number, data: { title?: string; content?: string }) =>
    api.put(`/copywritings/${id}`, data),

  delete: (id: number) =>
    api.delete(`/copywritings/${id}`),

  importExcel: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/copywritings/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  getCategories: () =>
    api.get<{ categories: Array<{ name: string; count: number }> }>('/copywritings/categories'),
};
