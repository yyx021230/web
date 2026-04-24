export interface AIModel {
  id: string;
  name: string;
  description: string;
  maxResolution: { width: number; height: number };
  styles?: string[];
  supportedRatios?: string[];
}

export interface AIGenerationTask {
  id: string;
  modelId: string;
  prompt: string;
  negativePrompt?: string;
  width: number;
  height: number;
  style?: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  resultUrls?: string[];
  error?: string;
  createdAt: string;
  finishedAt?: string;
}
