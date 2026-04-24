import type { AIModelAdapter, GenerateImageParams, GenerateImageResult } from './model-adapter';
import { aiApi } from '@/services/aiApi';

export class SeedreamAdapter implements AIModelAdapter {
  readonly name = 'seedream';
  readonly description = '字节跳动 Seedream 图像生成模型';

  async generateImage(params: GenerateImageParams): Promise<GenerateImageResult> {
    const response = await aiApi.generateImage({
      prompt: params.prompt,
      negative_prompt: params.negative_prompt,
      model: this.name,
      width: params.width || 1024,
      height: params.height || 1024,
      style: params.style,
    });

    return {
      taskId: response.data.task_id,
      status: 'pending',
    };
  }

  async cancelTask(taskId: string): Promise<void> {
    await aiApi.cancelTask(taskId);
  }

  async getTaskStatus(taskId: string): Promise<GenerateImageResult> {
    const response = await aiApi.getTaskStatus(taskId);
    const data = response.data as { task_id?: string; status: string; image_urls?: string[]; error?: string };
    return {
      taskId,
      status: data.status as GenerateImageResult['status'],
      imageUrls: data.image_urls,
      error: data.error,
    };
  }
}
