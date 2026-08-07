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

export interface ReviewTask {
  id: number;
  name: string;
  source: string;
  status: string;
  candidate_count: number;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  needs_second_review_count: number;
  created_at: string;
  finished_at: string | null;
}

export interface ReviewCandidate {
  id: number;
  task_id: number;
  title: string;
  content: string;
  author: string | null;
  source: string;
  source_keyword: string | null;
  post_url: string | null;
  publish_date: string | null;
  copy_type: string | null;
  brand: string | null;
  likes: number;
  comments: number;
  collects: number;
  shares: number;
  views: number;
  review_status: string;
  review_note: string | null;
  reviewed_at: string | null;
  copywriting_id: number | null;
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

  getReviewTasks: () =>
    api.get<{ items: ReviewTask[] }>('/copywritings/review/tasks'),

  getReviewCandidates: (params: { task_id?: number; status?: string } = {}) =>
    api.get<{ items: ReviewCandidate[] }>('/copywritings/review/candidates', { params }),

  reviewCandidate: (candidateId: number, action: 'approved' | 'rejected' | 'needs_second_review', note?: string) =>
    api.post(`/copywritings/review/candidates/${candidateId}/action`, { action, note }),
};
