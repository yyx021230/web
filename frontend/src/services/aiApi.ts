import api from './api';

export interface GenerateImageParams {
  prompt: string;
  negative_prompt?: string;
  model: string;
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
}

export interface QueueStatus {
  pending: number;
  processing: boolean;
  total_processed: number;
  total_failed: number;
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
    throw new Error(data?.message || '请求失败');
  },

  getTaskStatus: (taskId: string, model?: string) => {
    const qs = model ? `?model=${model}` : '';
    return api.get<ImageTaskResponse>(`/ai-image/tasks/${taskId}${qs}`);
  },

  cancelTask: (taskId: string, model?: string) => {
    const qs = model ? `?model=${model}` : '';
    return api.post(`/ai-image/tasks/${taskId}/cancel${qs}`);
  },

  getHistory: (page = 1, limit = 20) =>
    api.get<{ items: Record<string, unknown>[]; total: number }>('/ai-image/history', {
      params: { page, limit },
    }),

  listModels: () =>
    api.get<{ id: string; name: string; description: string }[]>('/ai-image/models'),

  getQueueStatus: () =>
    api.get<QueueStatus>('/ai-image/queue/status'),
};
