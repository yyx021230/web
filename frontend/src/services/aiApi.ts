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
  generation_mode?: 'fast' | 'precision'; // GPT Image 2.5：快速出图 / 精细创作
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
    const body = data as { message?: unknown; detail?: unknown; data?: unknown };
    const errors = Array.isArray(body.data) ? body.data : Array.isArray(body.detail) ? body.detail : [];
    const fields: Record<string, string> = {
      image_url: '参考图地址', image_data: '参考图', images_data: '参考图',
      prompt: '提示词', width: '图片宽度', height: '图片高度', count: '生成数量',
      generation_mode: '生成模式', model: '模型', client_request_id: '请求编号',
    };
    const details = errors.flatMap((error: unknown) => {
      if (!error || typeof error !== 'object') return [];
      const item = error as { field?: string; loc?: unknown[]; message?: string; msg?: string };
      const message = item.message || item.msg;
      if (typeof message !== 'string') return [];
      const field = (item.field || item.loc?.join('.') || '').replace(/^body\./, '');
      const label = fields[field.split('.')[0]] || field;
      return [`${label ? `${label}：` : ''}${message.replace(/^Value error, /, '')}`];
    });
    if (details.length) return details.join('；');
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

async function prepareReferenceSource(source: string): Promise<string> {
  if (typeof window === 'undefined' || source.startsWith('data:')) return source;
  const url = new URL(source, window.location.origin);
  if (url.origin !== window.location.origin) return source;
  if (url.pathname.startsWith('/uploads/')) return `${url.pathname}${url.search}`;
  if (!url.pathname.startsWith('/car-models/')) return source;

  // Legacy car images live in Next public, not in the backend storage volume.
  try {
    const response = await fetch(url.href, { signal: AbortSignal.timeout(30000) });
    if (!response.ok) throw new Error(`图片读取失败（${response.status}）`);
    const blob = await response.blob();
    if (!/^image\/(png|jpeg|webp|gif)$/.test(blob.type)) throw new Error('地址返回的不是可用图片');
    if (blob.size > 10 * 1024 * 1024) throw new Error('图片不能超过 10MB');
    return await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(new Error('图片读取失败'));
      reader.readAsDataURL(blob);
    });
  } catch (error) {
    throw createApiError(`车型参考图读取失败：${error instanceof Error ? error.message : '请重新选择图片'}`, 400);
  }
}

async function prepareGenerationParams(params: GenerateImageParams): Promise<GenerateImageParams> {
  const prepared = { ...params };
  if (params.image_url) {
    const source = await prepareReferenceSource(params.image_url);
    if (source.startsWith('data:image/')) {
      prepared.image_data = source;
      delete prepared.image_url;
    } else {
      prepared.image_url = source;
    }
  }
  if (params.images_data) prepared.images_data = await Promise.all(params.images_data.map(prepareReferenceSource));
  return prepared;
}

export const aiApi = {
  generateImage: async (params: GenerateImageParams) => {
    const prepared = await prepareGenerationParams(params);
    // Use direct API route for generate (avoids Next.js rewrite 1MB body limit)
    // Other calls go through the proxy which is fine (they don't have large bodies)
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch('/api/ai-image/generate', {
      method: 'POST',
      headers,
      body: JSON.stringify(prepared),
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
