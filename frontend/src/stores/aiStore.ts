import { create } from 'zustand';
import { aiApi, type GenerateImageParams as ApiParams } from '@/services/aiApi';

export interface AIGeneration {
  id: string;
  prompt: string;
  negativePrompt?: string;
  model: string;
  status: 'pending' | 'generating' | 'completed' | 'failed';
  imageUrl?: string;
  error?: string;
  createdAt: Date;
}

interface AIState {
  generations: AIGeneration[];
  currentModel: string;
  isGenerating: boolean;
  availableModels: { id: string; name: string; description: string }[];

  // Actions
  setCurrentModel: (model: string) => void;
  generateImage: (prompt: string, params?: Record<string, unknown>) => Promise<string | void>;
  cancelGeneration: (id: string) => void;
  addToCanvas: (generationId: string) => void;
  fetchHistory: (page?: number, limit?: number) => Promise<void>;
}

export const useAIStore = create<AIState>((set, get) => ({
  generations: [],
  currentModel: 'seedream',
  isGenerating: false,
  availableModels: [
    { id: 'seedream', name: 'Seedream', description: '字节跳动生图模型' },
    { id: 'gptimage2', name: 'GPT Image 2', description: 'OpenAI GPT Image 2 图像生成' },
    { id: 'midjourney', name: 'Midjourney', description: '预留 - Midjourney' },
    { id: 'stable-diffusion', name: 'Stable Diffusion', description: '预留 - SD' },
  ],

  setCurrentModel: (model: string) => set({ currentModel: model }),

  generateImage: async (prompt: string, params: Record<string, unknown> = {}) => {
    set({ isGenerating: true });
    try {
      const apiParams: ApiParams = {
        prompt,
        model: get().currentModel,
        width: (params.width as number) || 1024,
        height: (params.height as number) || 1024,
        style: params.style as string | undefined,
        quality: params.quality as string | undefined,
        negative_prompt: params.negative_prompt as string | undefined,
      };

      const res = await aiApi.generateImage(apiParams);
      const taskId = res.data.task_id;

      // 同步模型直接返回 image_urls
      if (res.data.status === 'completed' && res.data.image_urls?.length) {
        const newGen: AIGeneration = {
          id: taskId,
          prompt,
          model: apiParams.model,
          status: 'completed',
          imageUrl: res.data.image_urls[0],
          createdAt: new Date(),
        };
        set(state => ({ generations: [newGen, ...state.generations], isGenerating: false }));
        return taskId;
      }

      // 异步模型 - 简单轮询
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await aiApi.getTaskStatus(taskId, get().currentModel);
          const data = statusRes.data;

          if (data.status === 'completed' && data.image_urls?.length) {
            clearInterval(pollInterval);
            set(state => ({
              generations: state.generations.map(g =>
                g.id === taskId ? { ...g, status: 'completed' as const, imageUrl: data.image_urls![0] } : g
              ),
              isGenerating: false,
            }));
          } else if (data.status === 'failed') {
            clearInterval(pollInterval);
            set(state => ({
              generations: state.generations.map(g =>
                g.id === taskId ? { ...g, status: 'failed' as const, error: data.error || '生成失败' } : g
              ),
              isGenerating: false,
            }));
          }
        } catch {
          // 继续轮询
        }
      }, 2000);

      // 先创建一个 pending 记录
      const newGen: AIGeneration = {
        id: taskId,
        prompt,
        model: get().currentModel,
        status: 'generating',
        createdAt: new Date(),
      };
      set(state => ({ generations: [newGen, ...state.generations] }));
      return taskId;
    } catch (e) {
      const error = e instanceof Error ? e.message : '生成失败';
      set({ isGenerating: false });
      console.error('[AI Store] Generate failed:', error);
    }
  },

  cancelGeneration: (id: string) => {
    const generation = get().generations.find(g => g.id === id);
    void aiApi.cancelTask(id, generation?.model || get().currentModel).catch((error) => {
      console.error('[AI Store] Cancel failed:', error);
    });
    set((state) => ({
      generations: state.generations.map((g) =>
        g.id === id ? { ...g, status: 'failed' as const, error: '已取消' } : g
      ),
      isGenerating: false,
    }));
  },

  addToCanvas: (_generationId: string) => {
    // Add generated image to canvas
  },

  fetchHistory: async (page = 1, limit = 60) => {
    try {
      const res = await aiApi.getHistory(page, limit);
      const items = res.data.items ?? [];
      const generations: AIGeneration[] = items.map((item) => ({
        id: String(item.id ?? ''),
        prompt: String(item.prompt ?? ''),
        model: String(item.model_name ?? ''),
        status: (item.status as AIGeneration['status']) || 'completed',
        imageUrl: Array.isArray(item.result_urls) ? (item.result_urls[0] as string) : undefined,
        error: item.error as string | undefined,
        createdAt: new Date(String(item.created_at ?? '')),
      }));
      set({ generations });
    } catch (e) {
      console.error('[AI Store] Fetch history failed:', e);
    }
  },
}));
