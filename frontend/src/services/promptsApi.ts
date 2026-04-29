import api from './api';

export interface PromptItem {
  id: number;
  title: string;
  name?: string;
  chinese: string;
  english: string;
  image_url: string;
  category: string;
  param_type: string;
  created_by?: number | null;
  created_by_name?: string | null;
  is_public?: boolean;
  can_edit?: boolean;
  can_delete?: boolean;
  is_mine?: boolean;
  created_at?: string;
}

export interface PromptImportResult {
  total_rows: number;
  imported_count: number;
  failed_count: number;
  failed_rows: Array<{ row: number; title?: string; reason: string }>;
  created_categories: string[];
}

export const promptsApi = {
  getPrompts: (keyword?: string, category?: string, page = 1, limit = 100, owner = false) =>
    api.get<{ items: PromptItem[]; total: number; page: number; limit: number }>('/prompts', {
      params: { keyword, category, page, limit, owner },
    }),

  getCategories: () =>
    api.get<{ categories: { name: string; count: number }[] }>('/prompts/categories'),

  createPrompt: (data: { title?: string; name?: string; chinese: string; english?: string; category?: string; image_url?: string; param_type?: string }) =>
    api.post('/prompts', data),

  updatePrompt: (id: number, data: { title?: string; name?: string; chinese?: string; english?: string; category?: string; image_url?: string; param_type?: string }) =>
    api.put(`/prompts/${id}`, data),

  deletePrompt: (id: number) =>
    api.delete(`/prompts/${id}`),

  importPrompts: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<PromptImportResult>('/prompts/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  uploadImage: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<{ url: string }>('/prompts/upload-image', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  reportPrompt: (id: number, data: { reason: string; details?: string }) =>
    api.post(`/prompts/${id}/report`, data),

  getMyReports: (page = 1, limit = 20, status?: string) =>
    api.get<{ items: Array<{ id: number; prompt_id: number; prompt_name: string; prompt_text: string; reason: string; details: string | null; status: string; created_at: string; resolved_at: string | null; resolution_note: string | null }>; total: number; page: number; limit: number }>('/prompts/my-reports', { params: { page, limit, status } }),

  getReportReasons: () =>
    api.get<{ reasons: string[] }>('/prompts/report-reasons'),
};
