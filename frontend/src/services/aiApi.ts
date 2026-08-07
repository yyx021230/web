import api from './api';

export interface GenerateImageParams {
  prompt: string;
  client_request_id?: string;
  negative_prompt?: string;
  model: string;
  count?: number;
  width?: number;
  height?: number;
  style?: string;
  quality?: string;  // low / medium / high
  image_data?: string; // 单张参考图片 base64（图生图模式）
  images_data?: string[]; // 多张参考图片 base64/URL（Seedream 支持最多 10 张）
  image_url?: string; // 单张参考图片 URL（图库模式）
  image_urls?: string[]; // 多张参考图片 URL（图库多图模式）
}

export interface ImageTaskResponse {
  task_id: string;
  status: string;
  image_urls: string[];
  error?: string;
  client_request_id?: string;
  created_at?: string | null;
  finished_at?: string | null;
  elapsed_seconds?: number | null;
}

export interface QueueStatus {
  pending: number;
  processing: boolean;
  processing_count?: number;
  tracked?: number;
  redis_available?: boolean;
  error?: string;
  local_fallback?: {
    pending: number;
    processing: boolean;
    total_processed: number;
    total_failed: number;
    last_request_time?: number | null;
  };
  total_processed?: number;
  total_failed?: number;
}

export interface ActiveImageTask {
  id: number;
  task_id: string;
  model_name: string;
  status: string;
  prompt: string;
  created_at: string;
  finished_at?: string | null;
}

export interface ActiveImageTasksResponse {
  active_count: number;
  max_active: number;
  can_submit: boolean;
  items: ActiveImageTask[];
}

export interface AIImageRuntimeConfig {
  task_timeout_seconds: number;
  poll_interval_seconds: number;
}

function resolveErrorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === 'object') {
    const body = data as { message?: unknown; detail?: unknown };
    if (typeof body.message === 'string' && body.message.trim()) {
      return body.message;
    }
    if (typeof body.detail === 'string' && body.detail.trim()) {
      return body.detail;
    }
  }
  return fallback;
}

function createApiError(message: string, status?: number): Error & { status?: number; response?: { status?: number; data?: unknown } } {
  const err = new Error(message) as Error & { status?: number; response?: { status?: number; data?: unknown } };
  err.status = status;
  err.response = { status };
  return err;
}

export const aiApi = {
  generateImage: async (params: GenerateImageParams) => {
    // Use direct API route for generate (avoids Next.js rewrite 1MB body limit)
    // Other calls go through the proxy which is fine (they don't have large bodies)
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch('/api/ai-image/generate', {
      method: 'POST',
      headers,
      body: JSON.stringify(params),
    });
    const data = await res.json();
    // Unwrap the { code, message, data } envelope to match axios api behavior
    if (data?.code === 0) {
      return { data: data.data } as { data: ImageTaskResponse };
    }
    if (res.status === 401) {
      throw createApiError(resolveErrorMessage(data, '请先登录后再生成图片'), res.status);
    }
    throw createApiError(resolveErrorMessage(data, '请求失败'), res.status);
  },

  getTaskStatus: (taskId: string, model?: string) => {
    const qs = model ? `?model=${model}` : '';
    return api.get<ImageTaskResponse>(`/ai-image/tasks/${taskId}${qs}`);
  },

  getTaskByClientRequestId: (clientRequestId: string) =>
    api.get<ImageTaskResponse>(`/ai-image/requests/${encodeURIComponent(clientRequestId)}`),

  cancelTask: (taskId: string, model?: string) => {
    const qs = model ? `?model=${model}` : '';
    return api.post(`/ai-image/tasks/${taskId}/cancel${qs}`);
  },

  getHistory: (page = 1, limit = 60) =>
    api.get<{ items: Record<string, unknown>[]; total: number }>('/ai-image/history', {
      params: { page, limit },
    }),

  getActiveTasks: () =>
    api.get<ActiveImageTasksResponse>('/ai-image/active'),

  listModels: () =>
    api.get<{ id: string; name: string; description: string }[]>('/ai-image/models'),

  getQueueStatus: () =>
    api.get<QueueStatus>('/ai-image/queue/status'),

  getRuntimeConfig: () =>
    api.get<AIImageRuntimeConfig>('/ai-image/runtime-config'),
};
