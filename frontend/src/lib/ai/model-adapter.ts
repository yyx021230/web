export interface GenerateImageParams {
  prompt: string;
  negative_prompt?: string;
  width?: number;
  height?: number;
  style?: string;
  num_images?: number;
}

export interface GenerateImageResult {
  taskId: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  imageUrls?: string[];
  error?: string;
}

export interface AIModelAdapter {
  readonly name: string;
  readonly description: string;

  generateImage(params: GenerateImageParams): Promise<GenerateImageResult>;
  cancelTask(taskId: string): Promise<void>;
  getTaskStatus(taskId: string): Promise<GenerateImageResult>;
}
