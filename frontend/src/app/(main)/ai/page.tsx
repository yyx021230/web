'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { cn } from '@/lib/utils';
import {
  Download, Share2, Maximize2, Loader2, X, ChevronDown, CheckCircle2, AlertCircle,
  ImagePlus, Images, Upload, Trash2, Image as ImageIcon, Save, Zap, ScanLine, RotateCcw, SlidersHorizontal, ArrowUp,
} from 'lucide-react';
import { aiApi, type ActiveImageTasksResponse, type AIImageRuntimeConfig, type ImageTaskResponse, type QueueStatus } from '@/services/aiApi';
import { materialApi } from '@/services/materialApi';
import { promptsApi } from '@/services/promptsApi';
import { toast } from '@/lib/toast';
import GalleryPicker, { type GalleryPickerImage } from '@/components/ai/GalleryPicker';
import studio from './studio.module.css';

interface RefImageItem {
  data: string; // base64 or URL
  name: string;
  source: 'local' | 'gallery';
}

interface ChatMessage {
  id: string;
  type: 'prompt' | 'result';
  content: string;
  images: AIImageResult[];
  timestamp: string;
  params?: { model: string; modelId?: string; size: string; style: string; count: number; quality?: string; generationMode?: 'fast' | 'precision' };
  refImages?: RefImageItem[]; // 参考图片列表（用于图生图）
  taskId?: string; // 异步任务的 task_id（用于轮询）
  clientRequestId?: string; // 前端提交请求幂等 ID（用于找回任务）
}

interface GenerationRequestSnapshot {
  prompt: string;
  model: string;
  size: string;
  style: string;
  count: number;
  quality?: string;
  generationMode?: 'fast' | 'precision';
  refImages: RefImageItem[];
}

interface AIImageResult {
  id: string;
  url: string;
  width: number;
  height: number;
  liked: boolean;
}

function ByteDanceLogo({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
      <path d="M19.8772 1.4685 24 2.5326v18.9426l-4.1228 1.0563V1.4685Zm-13.3481 9.428 4.115 1.0641v8.9786l-4.115 1.0642V10.8965ZM0 2.572l4.115 1.0642v16.7354L0 21.428V2.572Zm17.4553 5.6205v11.107l-4.1228-1.0642V9.2568l4.1228-1.0642Z" />
    </svg>
  );
}

function OpenAILogo({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
      <path d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729Zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944Zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464ZM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865a4.504 4.504 0 0 1-1.6464-6.1408Zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667Zm2.0107-3.0231-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66ZM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813Zm1.0976-2.3654 2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z" />
    </svg>
  );
}

const models = [
  { id: 'seedream', name: 'Seedream', desc: '字节跳动', note: '中文海报与批量创作', icon: ByteDanceLogo, brand: 'bytedance' },
  { id: 'gptimage2', name: 'GPT Image 2', desc: 'OpenAI', note: '稳定通用的图像生成', icon: OpenAILogo, brand: 'openai' },
  { id: 'gptimage25', name: 'GPT Image 2.5', desc: 'OpenAI 新一代', note: '快速与精细双模式', icon: OpenAILogo, brand: 'openai', badge: 'NEW' },
];

const generationModes = [
  {
    id: 'fast' as const,
    label: '快速出图',
    desc: '日常批量创作，响应更快',
    icon: Zap,
  },
  {
    id: 'precision' as const,
    label: '精细创作',
    desc: '复杂版式与精准改图更稳',
    icon: ScanLine,
  },
];
const getGenerationModeLabel = (mode: 'fast' | 'precision') => mode === 'precision' ? '精细创作' : '快速出图';

const qualities = [
  { id: 'low', label: '低', desc: '快速/便宜' },
  { id: 'medium', label: '中', desc: '均衡' },
  { id: 'high', label: '高', desc: '精细/最贵' },
];

type AspectRatioId = '1:1' | '4:5' | '3:4' | '2:3' | '9:16' | '4:3' | '3:2' | '16:9';
type ResolutionTierId = '1K' | '2K' | '3K' | '4K';

interface GenerationPreferences {
  version: 1;
  prompt: string;
  model: string;
  ratio: AspectRatioId;
  resolutionTier: ResolutionTierId;
  style: string;
  quality: string;
  generationMode: 'fast' | 'precision';
  count: number;
}

interface ResolutionOption {
  id: ResolutionTierId;
  label: string;
  w: number;
  h: number;
  disabled?: boolean;
  note?: string;
}

const aspectRatios: Array<{ id: AspectRatioId; label: string; desc: string }> = [
  { id: '1:1', label: '1:1', desc: '方图' },
  { id: '4:5', label: '4:5', desc: '信息流' },
  { id: '3:4', label: '3:4', desc: '小红书' },
  { id: '2:3', label: '2:3', desc: '海报' },
  { id: '9:16', label: '9:16', desc: '竖屏' },
  { id: '4:3', label: '4:3', desc: '横版' },
  { id: '3:2', label: '3:2', desc: '封面' },
  { id: '16:9', label: '16:9', desc: '横屏' },
];

const seedreamRatioIds: AspectRatioId[] = ['1:1', '3:4', '2:3', '9:16', '4:3', '3:2', '16:9'];
const gptimage2RatioIds: AspectRatioId[] = ['1:1', '4:5', '3:4', '2:3', '9:16', '4:3', '3:2', '16:9'];

const resolutionTiers: Array<{ id: ResolutionTierId; label: string }> = [
  { id: '1K', label: '1K' },
  { id: '2K', label: '2K' },
  { id: '3K', label: '3K' },
  { id: '4K', label: '4K' },
];

const gptimage2ResolutionMap: Record<AspectRatioId, Record<ResolutionTierId, ResolutionOption>> = {
  '1:1': {
    '1K': { id: '1K', label: '1K', w: 1024, h: 1024 },
    '2K': { id: '2K', label: '2K', w: 2048, h: 2048 },
    '3K': { id: '3K', label: '3K', w: 2880, h: 2880, note: '最大方图' },
    '4K': { id: '4K', label: '4K', w: 2880, h: 2880, note: '最大方图' },
  },
  '4:5': {
    '1K': { id: '1K', label: '1K', w: 1024, h: 1280 },
    '2K': { id: '2K', label: '2K', w: 1536, h: 1920 },
    '3K': { id: '3K', label: '3K', w: 2304, h: 2880 },
    '4K': { id: '4K', label: '4K', w: 2560, h: 3200, note: '最大4:5' },
  },
  '3:4': {
    '1K': { id: '1K', label: '1K', w: 768, h: 1024 },
    '2K': { id: '2K', label: '2K', w: 1536, h: 2048 },
    '3K': { id: '3K', label: '3K', w: 2304, h: 3072 },
    '4K': { id: '4K', label: '4K', w: 2448, h: 3264, note: '最大3:4' },
  },
  '2:3': {
    '1K': { id: '1K', label: '1K', w: 1024, h: 1536 },
    '2K': { id: '2K', label: '2K', w: 1344, h: 2016 },
    '3K': { id: '3K', label: '3K', w: 2048, h: 3072 },
    '4K': { id: '4K', label: '4K', w: 2336, h: 3504, note: '最大2:3' },
  },
  '9:16': {
    '1K': { id: '1K', label: '1K', w: 720, h: 1280, note: '最低可用' },
    '2K': { id: '2K', label: '2K', w: 1152, h: 2048 },
    '3K': { id: '3K', label: '3K', w: 1728, h: 3072 },
    '4K': { id: '4K', label: '4K', w: 2160, h: 3840 },
  },
  '4:3': {
    '1K': { id: '1K', label: '1K', w: 1024, h: 768 },
    '2K': { id: '2K', label: '2K', w: 2048, h: 1536 },
    '3K': { id: '3K', label: '3K', w: 3072, h: 2304 },
    '4K': { id: '4K', label: '4K', w: 3264, h: 2448, note: '最大4:3' },
  },
  '3:2': {
    '1K': { id: '1K', label: '1K', w: 1536, h: 1024 },
    '2K': { id: '2K', label: '2K', w: 2016, h: 1344 },
    '3K': { id: '3K', label: '3K', w: 3072, h: 2048 },
    '4K': { id: '4K', label: '4K', w: 3504, h: 2336, note: '最大3:2' },
  },
  '16:9': {
    '1K': { id: '1K', label: '1K', w: 1280, h: 720, note: '最低可用' },
    '2K': { id: '2K', label: '2K', w: 2048, h: 1152 },
    '3K': { id: '3K', label: '3K', w: 3072, h: 1728 },
    '4K': { id: '4K', label: '4K', w: 3840, h: 2160 },
  },
};

const seedreamResolutionMap: Record<AspectRatioId, Record<ResolutionTierId, ResolutionOption>> = {
  '1:1': {
    '1K': { id: '1K', label: '1K', w: 1024, h: 1024, disabled: true, note: 'Seedream 固定档' },
    '2K': { id: '2K', label: '2K', w: 2048, h: 2048 },
    '3K': { id: '3K', label: '3K', w: 3072, h: 3072, disabled: true, note: 'Seedream 固定档' },
    '4K': { id: '4K', label: '4K', w: 4096, h: 4096, disabled: true, note: 'Seedream 固定档' },
  },
  '4:5': {
    '1K': { id: '1K', label: '1K', w: 1024, h: 1280, disabled: true, note: 'Seedream 未支持' },
    '2K': { id: '2K', label: '2K', w: 1680, h: 2240, disabled: true, note: 'Seedream 未支持' },
    '3K': { id: '3K', label: '3K', w: 2304, h: 2880, disabled: true, note: 'Seedream 未支持' },
    '4K': { id: '4K', label: '4K', w: 2560, h: 3200, disabled: true, note: 'Seedream 未支持' },
  },
  '3:4': {
    '1K': { id: '1K', label: '1K', w: 768, h: 1024, disabled: true, note: 'Seedream 固定档' },
    '2K': { id: '2K', label: '2K', w: 1680, h: 2240 },
    '3K': { id: '3K', label: '3K', w: 2304, h: 3072, disabled: true, note: 'Seedream 固定档' },
    '4K': { id: '4K', label: '4K', w: 3072, h: 4096, disabled: true, note: 'Seedream 固定档' },
  },
  '2:3': {
    '1K': { id: '1K', label: '1K', w: 1024, h: 1536, disabled: true, note: 'Seedream 固定档' },
    '2K': { id: '2K', label: '2K', w: 1600, h: 2400 },
    '3K': { id: '3K', label: '3K', w: 2048, h: 3072, disabled: true, note: 'Seedream 固定档' },
    '4K': { id: '4K', label: '4K', w: 2336, h: 3504, disabled: true, note: 'Seedream 固定档' },
  },
  '9:16': {
    '1K': { id: '1K', label: '1K', w: 720, h: 1280, disabled: true, note: 'Seedream 固定档' },
    '2K': { id: '2K', label: '2K', w: 1440, h: 2560 },
    '3K': { id: '3K', label: '3K', w: 1728, h: 3072, disabled: true, note: 'Seedream 固定档' },
    '4K': { id: '4K', label: '4K', w: 2304, h: 4096, disabled: true, note: 'Seedream 固定档' },
  },
  '4:3': {
    '1K': { id: '1K', label: '1K', w: 1024, h: 768, disabled: true, note: 'Seedream 固定档' },
    '2K': { id: '2K', label: '2K', w: 2240, h: 1680 },
    '3K': { id: '3K', label: '3K', w: 3072, h: 2304, disabled: true, note: 'Seedream 固定档' },
    '4K': { id: '4K', label: '4K', w: 3264, h: 2448, disabled: true, note: 'Seedream 固定档' },
  },
  '3:2': {
    '1K': { id: '1K', label: '1K', w: 1536, h: 1024, disabled: true, note: 'Seedream 固定档' },
    '2K': { id: '2K', label: '2K', w: 2400, h: 1600 },
    '3K': { id: '3K', label: '3K', w: 3072, h: 2048, disabled: true, note: 'Seedream 固定档' },
    '4K': { id: '4K', label: '4K', w: 3504, h: 2336, disabled: true, note: 'Seedream 固定档' },
  },
  '16:9': {
    '1K': { id: '1K', label: '1K', w: 1280, h: 720, disabled: true, note: 'Seedream 固定档' },
    '2K': { id: '2K', label: '2K', w: 2560, h: 1440 },
    '3K': { id: '3K', label: '3K', w: 3072, h: 1728, disabled: true, note: 'Seedream 固定档' },
    '4K': { id: '4K', label: '4K', w: 4096, h: 2304, disabled: true, note: 'Seedream 固定档' },
  },
};

const formatSize = (w: number, h: number) => `${w}×${h}`;
const isGptImageModel = (model: string) => model === 'gptimage2' || model === 'gptimage25';
const getAspectRatiosForModel = (model: string) => {
  const ids = isGptImageModel(model) ? gptimage2RatioIds : seedreamRatioIds;
  return ids.map(id => aspectRatios.find(ratio => ratio.id === id)).filter(Boolean) as typeof aspectRatios;
};
const getResolutionOptions = (model: string, ratio: AspectRatioId) => {
  const map = isGptImageModel(model) ? gptimage2ResolutionMap : seedreamResolutionMap;
  return resolutionTiers.map(tier => map[ratio][tier.id]);
};
const getDefaultPreset = (model: string): { ratio: AspectRatioId; tier: ResolutionTierId; size: string } => {
  const ratio: AspectRatioId = '1:1';
  const tier: ResolutionTierId = isGptImageModel(model) ? '1K' : '2K';
  const option = getResolutionOptions(model, ratio).find(item => item.id === tier) || getResolutionOptions(model, ratio)[0];
  return { ratio, tier: option.id, size: formatSize(option.w, option.h) };
};

const styles = ['写实', '插画', '3D', '动漫', '水彩', '像素', '油画', '极简', '赛博朋克', '扁平化'];

/** 轮询间隔(ms)：运行时会优先使用后端配置 */
const POLL_INTERVAL = 2000;
const MAX_PARALLEL_TASKS = 6;
const STORAGE_KEY_BASE = 'ai_image_messages';
const PENDING_KEY_BASE = 'ai_pending_generation';
const PREFERENCES_SCOPE_BASE = 'ai_image_preferences';
const PROMPT_MAX_LEN = 8000;

/** 持久化相关常量 */
const MAX_HISTORY = 50; // 最多保留 50 条消息（含 prompt + result）
const MAX_HISTORY_PAIRS = Math.floor(MAX_HISTORY / 2); // 按 prompt+result 成对保留
const DEFAULT_PROMPT_SHARE_CATEGORY = 'AI生图分享';

interface PendingGenerationState {
  promptMsgId: string;
  resultMsgId: string;
  prompt: string;
  model: string;
  size: string;
  style: string;
  generationMode?: 'fast' | 'precision';
  timestamp: number;
  taskId?: string;
  clientRequestId?: string;
  status?: 'reconciling' | 'pending';
}

function parsePendingStates(raw: string | null): PendingGenerationState[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as PendingGenerationState | PendingGenerationState[];
    if (Array.isArray(parsed)) return parsed.filter(Boolean);
    return parsed ? [parsed] : [];
  } catch {
    return [];
  }
}

function parseGenerationPreferences(raw: string | null): GenerationPreferences | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<GenerationPreferences>;
    const model = models.some(item => item.id === parsed.model) ? parsed.model! : 'seedream';
    const preset = getDefaultPreset(model);
    const ratio = getAspectRatiosForModel(model).some(item => item.id === parsed.ratio)
      ? parsed.ratio!
      : preset.ratio;
    const resolutionTier = getResolutionOptions(model, ratio).some(item => item.id === parsed.resolutionTier && !item.disabled)
      ? parsed.resolutionTier!
      : preset.tier;
    return {
      version: 1,
      prompt: typeof parsed.prompt === 'string' ? parsed.prompt.slice(0, PROMPT_MAX_LEN) : '',
      model,
      ratio,
      resolutionTier,
      style: typeof parsed.style === 'string' && styles.includes(parsed.style) ? parsed.style : '写实',
      quality: qualities.some(item => item.id === parsed.quality) ? parsed.quality! : 'low',
      generationMode: parsed.generationMode === 'precision' ? 'precision' : 'fast',
      count: [1, 2, 4].includes(Number(parsed.count)) ? Number(parsed.count) : 1,
    };
  } catch {
    return null;
  }
}

// 只跨客户端路由切换保留；浏览器刷新后模块重载，草稿随即清空。
const generationPreferencesMemory = new Map<string, GenerationPreferences>();

function normalizeMessagePairs(source: ChatMessage[]): ChatMessage[] {
  const normalized: ChatMessage[] = [];
  for (let i = 0; i < source.length; i += 1) {
    const promptMsg = source[i];
    const resultMsg = source[i + 1];
    if (promptMsg?.type === 'prompt' && resultMsg?.type === 'result') {
      normalized.push(promptMsg, resultMsg);
      i += 1;
    }
  }
  return normalized;
}

function clampHistoryByPairs(source: ChatMessage[]): ChatMessage[] {
  const normalized = normalizeMessagePairs(source);
  if (normalized.length <= MAX_HISTORY_PAIRS * 2) return normalized;
  return normalized.slice(-(MAX_HISTORY_PAIRS * 2));
}

function getUserScopedKey(base: string): string {
  try {
    const raw = localStorage.getItem('app_current_user');
    if (raw) {
      const u = JSON.parse(raw) as { id?: number; username?: string };
      if (u?.id != null) return `${base}:uid:${u.id}`;
      if (u?.username) return `${base}:user:${u.username}`;
    }
  } catch {
    // ignore
  }
  return `${base}:guest`;
}

function currentUserCanViewGlobalQueue(): boolean {
  try {
    const raw = localStorage.getItem('app_current_user');
    if (!raw) return false;
    const user = JSON.parse(raw) as { role?: string; roles?: string[] };
    return user.role === 'admin' || Boolean(user.roles?.includes('admin'));
  } catch {
    return false;
  }
}

function createClientRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID().slice(0, 64);
  }
  return `ai-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`.slice(0, 64);
}

function getWaitingContent(status?: string, recovering = false): string {
  if (recovering) return '任务仍在后台处理，正在重新确认状态...';
  if (status === 'queued') return '任务已提交，正在排队...';
  if (status === 'processing') return '正在生成图片，请稍候...';
  return '正在生成图片，请稍候...';
}

function getHttpErrorStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined;
  const candidate = error as { status?: unknown; response?: { status?: unknown } };
  if (typeof candidate.status === 'number') return candidate.status;
  if (typeof candidate.response?.status === 'number') return candidate.response.status;
  return undefined;
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function getUserScopedFolders(): string[] {
  const scopedKey = getUserScopedKey('user_created_folders');
  try {
    const scoped = localStorage.getItem(scopedKey);
    if (scoped) return JSON.parse(scoped) as string[];

    // 兼容早期未做按用户隔离的本地数据
    const legacy = localStorage.getItem('user_created_folders');
    return legacy ? JSON.parse(legacy) as string[] : [];
  } catch {
    return [];
  }
}

function getFallbackKeys(base: string, primary: string): string[] {
  const keys = [primary, base, `${base}:guest`];
  const uniq: string[] = [];
  for (const k of keys) {
    if (!uniq.includes(k)) uniq.push(k);
  }
  return uniq;
}

function readImageNaturalSize(url: string): Promise<{ width: number; height: number } | null> {
  return new Promise(resolve => {
    const img = document.createElement('img');
    img.onload = () => {
      const width = img.naturalWidth || img.width;
      const height = img.naturalHeight || img.height;
      resolve(width > 0 && height > 0 ? { width, height } : null);
    };
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

async function buildImageResults(
  urls: string[],
  idPrefix: string,
  fallbackWidth: number,
  fallbackHeight: number,
): Promise<AIImageResult[]> {
  return Promise.all(urls.map(async (url, i) => {
    const naturalSize = await readImageNaturalSize(url);
    return {
      id: `${idPrefix}-${i}`,
      url,
      width: naturalSize?.width || fallbackWidth,
      height: naturalSize?.height || fallbackHeight,
      liked: false,
    };
  }));
}

export default function AIPage() {
  const initialPreset = getDefaultPreset('seedream');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [reconcilingPending, setReconcilingPending] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);
  const [activeTasks, setActiveTasks] = useState<ActiveImageTasksResponse | null>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<AIImageRuntimeConfig | null>(null);
  const [canViewGlobalQueue, setCanViewGlobalQueue] = useState(false);
  const [selectedModel, setSelectedModel] = useState('seedream');
  const [selectedRatio, setSelectedRatio] = useState<AspectRatioId>(initialPreset.ratio);
  const [selectedResolutionTier, setSelectedResolutionTier] = useState<ResolutionTierId>(initialPreset.tier);
  const [selectedSize, setSelectedSize] = useState(initialPreset.size);
  const [selectedStyle, setSelectedStyle] = useState('写实');
  const [selectedQuality, setSelectedQuality] = useState('low');
  const [selectedGenerationMode, setSelectedGenerationMode] = useState<'fast' | 'precision'>('fast');
  const [imageCount, setImageCount] = useState(1);
  const [previewImage, setPreviewImage] = useState<AIImageResult | null>(null);
  const [refImages, setRefImages] = useState<RefImageItem[]>([]); // 参考图片列表
  const [galleryPickerOpen, setGalleryPickerOpen] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false);
  const [restoredParameters, setRestoredParameters] = useState(false);
  const [composerCompact, setComposerCompact] = useState(false);
  const pendingTaskCount = messages.filter(m =>
    m.type === 'result' && (Boolean(m.taskId) || Boolean(m.clientRequestId) || m.content === '正在生成图片，请稍候...')
  ).length;
  const maxActiveTasks = activeTasks?.max_active ?? MAX_PARALLEL_TASKS;
  const effectiveActiveTaskCount = Math.max(pendingTaskCount, activeTasks?.active_count ?? 0);
  const canStartMoreTasks = !submitting && effectiveActiveTaskCount < maxActiveTasks;
  /** 保存模版状态 */
  const [savingTemplate, setSavingTemplate] = useState(false);
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;
  const scrollRef = useRef<HTMLDivElement>(null);
  const shouldStickToBottomRef = useRef(true);
  const forceScrollToBottomRef = useRef(false);
  const composerExpandedByUserRef = useRef(false);
  const lastScrollTopRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const promptInputRef = useRef<HTMLTextAreaElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const settingsMenuRef = useRef<HTMLDivElement>(null);
  const [scopedKeys, setScopedKeys] = useState<{ storageKey: string; pendingKey: string; preferencesScope: string } | null>(null);
  const pollTimersRef = useRef<Record<string, number>>({});
  const runtimeConfigRef = useRef<AIImageRuntimeConfig | null>(null);
  const deletedPendingRef = useRef<{ promptMsgId?: string; resultMsgId?: string } | null>(null);
  const pendingCancelRef = useRef<PendingGenerationState | null>(null);
  const debugStorageRef = useRef(false);
  const importedCreativeRef = useRef(false);
  const availableAspectRatios = getAspectRatiosForModel(selectedModel);
  const selectedResolutionOptions = getResolutionOptions(selectedModel, selectedRatio);
  const activeResolutionOption = selectedResolutionOptions.find(item => item.id === selectedResolutionTier && !item.disabled)
    || selectedResolutionOptions.find(item => !item.disabled)
    || selectedResolutionOptions[0];
  const selectedModelInfo = models.find(item => item.id === selectedModel) || models[0];
  const SelectedModelIcon = selectedModelInfo.icon;
  const generateLabel = submitting
    ? '正在提交任务'
    : !canStartMoreTasks
      ? '任务已满 ' + effectiveActiveTaskCount + '/' + maxActiveTasks
      : '开始生成';

  const selectModel = (nextModel: string) => {
    const preset = getDefaultPreset(nextModel);
    setSelectedModel(nextModel);
    setSelectedRatio(preset.ratio);
    setSelectedResolutionTier(preset.tier);
    setSelectedSize(preset.size);
    setModelMenuOpen(false);
    setSettingsMenuOpen(false);
  };

  useEffect(() => {
    if (!modelMenuOpen && !settingsMenuOpen) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!modelMenuRef.current?.contains(event.target as Node)) setModelMenuOpen(false);
      if (!settingsMenuRef.current?.contains(event.target as Node)) setSettingsMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setModelMenuOpen(false);
        setSettingsMenuOpen(false);
      }
    };
    document.addEventListener('pointerdown', closeOnOutsideClick);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [modelMenuOpen, settingsMenuOpen]);

  useEffect(() => {
    if (importedCreativeRef.current) return;
    importedCreativeRef.current = true;
    const params = new URLSearchParams(window.location.search);
    if (params.get('from') !== 'prompt-library') return;

    const importedPrompt = (params.get('prompt') || '').trim().slice(0, PROMPT_MAX_LEN);
    const reference = (params.get('reference') || '').trim();
    if (importedPrompt) setPrompt(importedPrompt);
    if (reference) {
      setRefImages(current => current.some(item => item.data === reference)
        ? current
        : [{ data: reference, name: '提示词宝库参考图', source: 'gallery' as const }, ...current].slice(0, 10));
    }
  }, []);

  useEffect(() => {
    runtimeConfigRef.current = runtimeConfig;
  }, [runtimeConfig]);

  const logDebug = useCallback((msg: string, extra?: Record<string, unknown>) => {
    if (!debugStorageRef.current) return;
    // eslint-disable-next-line no-console
    console.log(`[AIStorage] ${msg}`, extra || {});
  }, []);

  const refreshActiveTasks = useCallback(async () => {
    try {
      const res = await aiApi.getActiveTasks();
      const data = res.data as ActiveImageTasksResponse;
      setActiveTasks(data);
      return data;
    } catch {
      return null;
    }
  }, []);

  const scrollToBottom = useCallback(() => {
    composerExpandedByUserRef.current = false;
    setComposerCompact(false);
    requestAnimationFrame(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    });
  }, []);

  const handleResultScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const movedUp = el.scrollTop < lastScrollTopRef.current - 2;
    lastScrollTopRef.current = el.scrollTop;
    shouldStickToBottomRef.current = distanceToBottom < 120;
    if (distanceToBottom < 120) {
      composerExpandedByUserRef.current = false;
      setComposerCompact(false);
      return;
    }
    if (movedUp || !composerExpandedByUserRef.current) {
      composerExpandedByUserRef.current = false;
      setComposerCompact(true);
      setModelMenuOpen(false);
      setSettingsMenuOpen(false);
    }
  }, []);

  const expandComposer = useCallback(() => {
    composerExpandedByUserRef.current = true;
    setComposerCompact(false);
    requestAnimationFrame(() => promptInputRef.current?.focus({ preventScroll: true }));
  }, []);

  const returnToBottom = useCallback(() => {
    composerExpandedByUserRef.current = false;
    setComposerCompact(false);
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (!el) return;
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    });
  }, []);

  const getActiveKeys = useCallback(() => {
    if (scopedKeys) return scopedKeys;
    return {
      storageKey: getUserScopedKey(STORAGE_KEY_BASE),
      pendingKey: getUserScopedKey(PENDING_KEY_BASE),
      preferencesScope: getUserScopedKey(PREFERENCES_SCOPE_BASE),
    };
  }, [scopedKeys]);

  const readPendingStates = useCallback((): PendingGenerationState[] => {
    const { pendingKey } = getActiveKeys();
    try {
      const pendingCandidates = getFallbackKeys(PENDING_KEY_BASE, pendingKey);
      for (const key of pendingCandidates) {
        const parsed = parsePendingStates(localStorage.getItem(key));
        if (parsed.length > 0) return parsed;
      }
    } catch {
      // ignore
    }
    return [];
  }, [getActiveKeys]);

  const writePendingStates = useCallback((items: PendingGenerationState[]) => {
    const { pendingKey } = getActiveKeys();
    try {
      const pendingCandidates = getFallbackKeys(PENDING_KEY_BASE, pendingKey);
      pendingCandidates.forEach(k => {
        if (k !== pendingKey) localStorage.removeItem(k);
      });
      if (items.length > 0) {
        localStorage.setItem(pendingKey, JSON.stringify(items));
      } else {
        localStorage.removeItem(pendingKey);
      }
    } catch {
      // ignore
    }
  }, [getActiveKeys]);

  const upsertPendingState = useCallback((pending: PendingGenerationState) => {
    const items = readPendingStates();
    const idx = items.findIndex(item =>
      item.resultMsgId === pending.resultMsgId ||
      item.promptMsgId === pending.promptMsgId ||
      (pending.taskId && item.taskId === pending.taskId)
    );
    if (idx >= 0) {
      items[idx] = { ...items[idx], ...pending };
    } else {
      items.push(pending);
    }
    writePendingStates(items.slice(-MAX_PARALLEL_TASKS));
  }, [readPendingStates, writePendingStates]);

  const removePendingState = useCallback((match: { promptMsgId?: string; resultMsgId?: string; taskId?: string; clientRequestId?: string }) => {
    const items = readPendingStates().filter(item =>
      !(match.promptMsgId && item.promptMsgId === match.promptMsgId) &&
      !(match.resultMsgId && item.resultMsgId === match.resultMsgId) &&
      !(match.taskId && item.taskId === match.taskId) &&
      !(match.clientRequestId && item.clientRequestId === match.clientRequestId)
    );
    writePendingStates(items);
  }, [readPendingStates, writePendingStates]);

  const clearPollTimer = useCallback((taskId: string) => {
    const timer = pollTimersRef.current[taskId];
    if (timer !== undefined) {
      window.clearInterval(timer);
      delete pollTimersRef.current[taskId];
    }
  }, []);

  const clearAllPollTimers = useCallback(() => {
    Object.values(pollTimersRef.current).forEach(timer => window.clearInterval(timer));
    pollTimersRef.current = {};
  }, []);

  const clearPendingState = useCallback(() => {
    writePendingStates([]);
    clearAllPollTimers();
    logDebug('clearPendingState');
  }, [clearAllPollTimers, logDebug, writePendingStates]);

  const persistMessages = useCallback((source: ChatMessage[]) => {
    const { storageKey } = getActiveKeys();
    try {
      const filtered = source.filter(
        m => m.type === 'prompt' || (m.type === 'result' && (m.images.length > 0 || Boolean(m.taskId) || Boolean(m.clientRequestId) || m.content.startsWith('生成失败') || m.content.startsWith('已取消')))
      );
      const toSave = clampHistoryByPairs(filtered);
      localStorage.setItem(storageKey, JSON.stringify(toSave));
      const candidates = getFallbackKeys(STORAGE_KEY_BASE, storageKey);
      candidates.forEach(k => {
        if (k !== storageKey) localStorage.removeItem(k);
      });
      logDebug('persistMessages', { storageKey, count: toSave.length });
    } catch {
      // ignore storage errors
    }
  }, [getActiveKeys, logDebug]);

  const upsertPendingMessages = useCallback((pending: PendingGenerationState, taskId?: string) => {
    const ts = new Date(pending.timestamp || Date.now()).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    setMessages(prev => {
      const hasPrompt = prev.some(m => m.id === pending.promptMsgId);
      const hasResult = prev.some(m => m.id === pending.resultMsgId);
      const next = [...prev];
      if (!hasPrompt) {
        next.push({
          id: pending.promptMsgId,
          type: 'prompt',
          content: pending.prompt || '恢复中的任务',
          images: [],
          timestamp: ts,
          params: {
            model: pending.model || 'seedream',
            size: pending.size || '2048×2048',
            style: pending.style || '写实',
            count: 1,
            generationMode: pending.model === 'gptimage25' ? (pending.generationMode || 'fast') : undefined,
          },
        });
      }
      if (!hasResult) {
        next.push({
          id: pending.resultMsgId,
          type: 'result',
          content: getWaitingContent(undefined, pending.status === 'reconciling'),
          images: [],
          timestamp: ts,
          taskId,
          clientRequestId: pending.clientRequestId,
        });
      } else {
        for (let i = 0; i < next.length; i += 1) {
          if (next[i].id === pending.resultMsgId) {
            next[i] = {
              ...next[i],
              taskId,
              clientRequestId: pending.clientRequestId,
              content: next[i].images.length > 0 ? '' : getWaitingContent(undefined, pending.status === 'reconciling'),
            };
            break;
          }
        }
      }
      return next;
    });
  }, []);

  useEffect(() => {
    const availableRatios = getAspectRatiosForModel(selectedModel);
    const nextRatio = availableRatios.some(item => item.id === selectedRatio)
      ? selectedRatio
      : availableRatios[0]?.id || '1:1';
    const preferredTier: ResolutionTierId = isGptImageModel(selectedModel) ? selectedResolutionTier : '2K';
    const options = getResolutionOptions(selectedModel, nextRatio);
    const next = options.find(item => item.id === preferredTier && !item.disabled)
      || options.find(item => !item.disabled)
      || options[0];
    if (!next) return;
    const nextSize = formatSize(next.w, next.h);
    if (nextRatio !== selectedRatio) setSelectedRatio(nextRatio);
    if (next.id !== selectedResolutionTier) setSelectedResolutionTier(next.id);
    if (nextSize !== selectedSize) setSelectedSize(nextSize);
  }, [selectedModel, selectedRatio, selectedResolutionTier, selectedSize]);

  /** 处理图片文件上传为 base64（支持多选） */
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    const remainingSlots = 10 - refImages.length;
    const toProcess = files.slice(0, remainingSlots);

    const promises = toProcess.map(file => {
      if (file.size > 10 * 1024 * 1024) {
        alert(`图片 "${file.name}" 大小不能超过 10MB`);
        return Promise.resolve(null);
      }
      return new Promise<RefImageItem | null>(resolve => {
        const reader = new FileReader();
        reader.onload = () => resolve({ data: reader.result as string, name: file.name, source: 'local' as const });
        reader.readAsDataURL(file);
      });
    });

    Promise.all(promises).then(results => {
      const newImages = results.filter(Boolean) as RefImageItem[];
      if (newImages.length > 0) setRefImages(prev => [...prev, ...newImages]);
    });
    // 重置 input 以便重新选择同一文件
    e.target.value = '';
  };

  useEffect(() => {
    if (!forceScrollToBottomRef.current && !shouldStickToBottomRef.current) return;
    forceScrollToBottomRef.current = false;
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    try {
      debugStorageRef.current = Boolean((window as Window & { __AI_DEBUG_STORAGE__?: boolean }).__AI_DEBUG_STORAGE__);
    } catch {
      debugStorageRef.current = false;
    }
    const next = {
      storageKey: getUserScopedKey(STORAGE_KEY_BASE),
      pendingKey: getUserScopedKey(PENDING_KEY_BASE),
      preferencesScope: getUserScopedKey(PREFERENCES_SCOPE_BASE),
    };
    setScopedKeys(next);
    logDebug('scopedKeysReady', next as unknown as Record<string, unknown>);
  }, [logDebug]);

  const getPollIntervalMs = useCallback(() => {
    const seconds = runtimeConfigRef.current?.poll_interval_seconds ?? 2;
    return Math.max(1000, seconds * 1000) || POLL_INTERVAL;
  }, []);

  const applyTaskStatus = useCallback(async (
    data: ImageTaskResponse,
    resultMsgId: string,
    width: number,
    height: number,
    clientRequestId?: string,
  ): Promise<boolean> => {
    const taskId = data.task_id;
    if (data.status === 'completed' && data.image_urls && data.image_urls.length > 0) {
      clearPollTimer(taskId);
      if (clientRequestId) clearPollTimer(`request:${clientRequestId}`);
      void refreshActiveTasks();
      const images = await buildImageResults(data.image_urls, taskId, width, height);
      setMessages(prev => prev.map(msg =>
        msg.id === resultMsgId ? { ...msg, images, taskId: undefined, clientRequestId: undefined, content: '' } : msg
      ));
      removePendingState({ taskId, resultMsgId, clientRequestId });
      return true;
    }

    if (data.status === 'failed' || data.status === 'cancelled') {
      clearPollTimer(taskId);
      if (clientRequestId) clearPollTimer(`request:${clientRequestId}`);
      void refreshActiveTasks();
      setMessages(prev => prev.map(msg =>
        msg.id === resultMsgId
          ? {
              ...msg,
              content: data.status === 'cancelled' ? '已取消' : `生成失败: ${data.error || '未知错误'}`,
              taskId: undefined,
              clientRequestId: undefined,
            }
          : msg
      ));
      removePendingState({ taskId, resultMsgId, clientRequestId });
      return true;
    }

    setMessages(prev => prev.map(msg =>
      msg.id === resultMsgId
        ? { ...msg, taskId, clientRequestId, content: getWaitingContent(data.status) }
        : msg
    ));
    return false;
  }, [clearPollTimer, refreshActiveTasks, removePendingState]);

  // A missing task is not recoverable by polling. It can happen after an old
  // deployment or an interrupted browser request, and must release the local
  // pending slot instead of leaving the user in an endless "reconfirming" state.
  const finishTerminalTaskLookupError = useCallback((
    error: unknown,
    resultMsgId: string,
    taskId?: string,
    clientRequestId?: string,
  ): boolean => {
    const status = getHttpErrorStatus(error);
    if (status !== 401 && status !== 403 && status !== 404) return false;

    if (taskId) clearPollTimer(taskId);
    if (clientRequestId) clearPollTimer(`request:${clientRequestId}`);
    void refreshActiveTasks();

    const content = status === 404
      ? '生成失败: 后台未找到该任务，请重新提交'
      : status === 401
        ? '生成失败: 登录已失效，请重新登录后再提交'
        : '生成失败: 无权读取该任务，请重新提交';
    setMessages(prev => prev.map(msg =>
      msg.id === resultMsgId
        ? { ...msg, content, images: [], taskId: undefined, clientRequestId: undefined }
        : msg
    ));
    removePendingState({ taskId, resultMsgId, clientRequestId });
    return true;
  }, [clearPollTimer, refreshActiveTasks, removePendingState]);

  /** 启动轮询任务状态直到后端给出最终状态 */
  const startPoll = useCallback((taskId: string, model: string, resultMsgId: string, width: number, height: number, clientRequestId?: string) => {
    if (pollTimersRef.current[taskId] !== undefined) return;
    const pollOnce = async () => {
      try {
        const res = await aiApi.getTaskStatus(taskId, model);
        await applyTaskStatus(res.data as ImageTaskResponse, resultMsgId, width, height, clientRequestId);
      } catch (error) {
        if (finishTerminalTaskLookupError(error, resultMsgId, taskId, clientRequestId)) return;
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId
            ? { ...msg, taskId, clientRequestId, content: getWaitingContent(undefined, true) }
            : msg
        ));
      }
    };
    void pollOnce();
    pollTimersRef.current[taskId] = window.setInterval(pollOnce, getPollIntervalMs());
  }, [applyTaskStatus, finishTerminalTaskLookupError, getPollIntervalMs]);

  const startRequestRecovery = useCallback((pending: PendingGenerationState, width: number, height: number) => {
    if (!pending.clientRequestId) return;
    const timerKey = `request:${pending.clientRequestId}`;
    if (pollTimersRef.current[timerKey] !== undefined) return;
    const recoverOnce = async () => {
      try {
        const res = await aiApi.getTaskByClientRequestId(pending.clientRequestId as string);
        const data = res.data as ImageTaskResponse;
        if (data.task_id) {
          clearPollTimer(timerKey);
          const nextPending = { ...pending, taskId: data.task_id, status: 'pending' as const };
          upsertPendingMessages(nextPending, data.task_id);
          upsertPendingState(nextPending);
          const finished = await applyTaskStatus(data, pending.resultMsgId, width, height, pending.clientRequestId);
          if (!finished) {
            startPoll(data.task_id, (pending.model || 'seedream').toLowerCase(), pending.resultMsgId, width, height, pending.clientRequestId);
          }
        }
      } catch (error) {
        if (finishTerminalTaskLookupError(error, pending.resultMsgId, pending.taskId, pending.clientRequestId)) return;
        upsertPendingMessages({ ...pending, status: 'reconciling' }, pending.taskId);
        setMessages(prev => prev.map(msg =>
          msg.id === pending.resultMsgId
            ? { ...msg, clientRequestId: pending.clientRequestId, content: getWaitingContent(undefined, true) }
            : msg
        ));
      }
    };
    void recoverOnce();
    pollTimersRef.current[timerKey] = window.setInterval(recoverOnce, getPollIntervalMs());
  }, [applyTaskStatus, clearPollTimer, finishTerminalTaskLookupError, getPollIntervalMs, startPoll, upsertPendingMessages, upsertPendingState]);

  // 客户端首次加载时从 localStorage 恢复历史记录
  useEffect(() => {
    try {
      if (!scopedKeys) return;
      const { storageKey, pendingKey, preferencesScope } = scopedKeys;
      const preferences = parseGenerationPreferences(
        generationPreferencesMemory.has(preferencesScope)
          ? JSON.stringify(generationPreferencesMemory.get(preferencesScope))
          : null
      );
      if (preferences) {
        const params = new URLSearchParams(window.location.search);
        const hasImportedPrompt = params.get('from') === 'prompt-library' && Boolean(params.get('prompt')?.trim());
        const option = getResolutionOptions(preferences.model, preferences.ratio)
          .find(item => item.id === preferences.resolutionTier && !item.disabled);
        if (!hasImportedPrompt) setPrompt(preferences.prompt);
        setSelectedModel(preferences.model);
        setSelectedRatio(preferences.ratio);
        setSelectedResolutionTier(preferences.resolutionTier);
        if (option) setSelectedSize(formatSize(option.w, option.h));
        setSelectedStyle(preferences.style);
        setSelectedQuality(preferences.quality);
        setSelectedGenerationMode(preferences.generationMode);
        setImageCount(preferences.count);
      }
      const storageCandidates = getFallbackKeys(STORAGE_KEY_BASE, storageKey);
      let saved: string | null = null;
      let savedFrom = storageKey;
      for (const k of storageCandidates) {
        const val = localStorage.getItem(k);
        if (val) {
          saved = val;
          savedFrom = k;
          break;
        }
      }
      if (saved) {
        const parsed = clampHistoryByPairs(JSON.parse(saved) as ChatMessage[]);
        setMessages(parsed);
        if (savedFrom !== storageKey) {
          localStorage.setItem(storageKey, JSON.stringify(parsed));
          localStorage.removeItem(savedFrom);
        }
        logDebug('loadMessages', { savedFrom, storageKey, count: parsed.length });
      }

      const pendingCandidates = getFallbackKeys(PENDING_KEY_BASE, pendingKey);
      let pendingRaw: string | null = null;
      let pendingFrom = pendingKey;
      for (const k of pendingCandidates) {
        const val = localStorage.getItem(k);
        if (val) {
          pendingRaw = val;
          pendingFrom = k;
          break;
        }
      }
      const pendingList = parsePendingStates(pendingRaw).slice(-MAX_PARALLEL_TASKS);
      if (pendingList.length > 0) {
        if (pendingFrom !== pendingKey) {
          writePendingStates(pendingList);
          localStorage.removeItem(pendingFrom);
        }
        setReconcilingPending(true);
        (async () => {
          try {
            await Promise.all(pendingList.map(async (pending) => {
              if (
                deletedPendingRef.current &&
                (deletedPendingRef.current.promptMsgId === pending.promptMsgId ||
                  deletedPendingRef.current.resultMsgId === pending.resultMsgId)
              ) {
                removePendingState({ promptMsgId: pending.promptMsgId, resultMsgId: pending.resultMsgId });
                return;
              }

              const sizeParts = (pending.size || '2048×2048').split('×');
              const width = parseInt(sizeParts[0]) || 2048;
              const height = parseInt(sizeParts[1]) || 2048;

              const ensureResultMsg = () => {
                setMessages(prev => {
                  if (prev.some(m => m.id === pending.resultMsgId)) return prev;
                  const ts = new Date(pending.timestamp || Date.now()).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
                  return [...prev, {
                    id: pending.resultMsgId,
                    type: 'result',
                    content: getWaitingContent(undefined, pending.status === 'reconciling'),
                    images: [],
                    timestamp: ts,
                    taskId: pending.taskId,
                    clientRequestId: pending.clientRequestId,
                  }];
                });
              };

              if (pending.taskId) {
                ensureResultMsg();
                upsertPendingMessages(pending, pending.taskId);
                upsertPendingState({ ...pending, status: 'pending' });
                startPoll(pending.taskId, (pending.model || 'seedream').toLowerCase(), pending.resultMsgId, width, height, pending.clientRequestId);
                return;
              }

              if (pending.clientRequestId) {
                ensureResultMsg();
                const nextPending = { ...pending, status: 'reconciling' as const };
                upsertPendingMessages(nextPending);
                upsertPendingState(nextPending);
                startRequestRecovery(nextPending, width, height);
                return;
              }

              ensureResultMsg();
              upsertPendingState({ ...pending, status: 'reconciling' });
            }));
          } catch {
            // ignore
          } finally {
            setReconcilingPending(false);
          }
        })();
      }
    } catch { /* ignore */ }
    setLoaded(true);
  }, [logDebug, removePendingState, scopedKeys, startPoll, startRequestRecovery, upsertPendingMessages, upsertPendingState, writePendingStates]);

  const isGenerating = pendingTaskCount > 0 || reconcilingPending;
  const generationGroups = messages.reduce<ChatMessage[][]>((groups, message) => {
    if (message.type === 'prompt' || groups.length === 0) groups.push([message]);
    else groups[groups.length - 1].push(message);
    return groups;
  }, []);

  // 持久化到 localStorage（包含进行中的任务）
  useEffect(() => {
    if (!loaded || !scopedKeys) return;
    persistMessages(messages);
  }, [messages, loaded, persistMessages, scopedKeys]);

  // 保留当前用户尚未提交的创作草稿，页面切换后可继续编辑。
  useEffect(() => {
    if (!loaded || !scopedKeys) return;
    const preferences: GenerationPreferences = {
      version: 1,
      prompt,
      model: selectedModel,
      ratio: selectedRatio,
      resolutionTier: selectedResolutionTier,
      style: selectedStyle,
      quality: selectedQuality,
      generationMode: selectedGenerationMode,
      count: imageCount,
    };
    generationPreferencesMemory.set(scopedKeys.preferencesScope, preferences);
  }, [imageCount, loaded, prompt, scopedKeys, selectedGenerationMode, selectedModel, selectedQuality, selectedRatio, selectedResolutionTier, selectedStyle]);

  useEffect(() => {
    setCanViewGlobalQueue(currentUserCanViewGlobalQueue());
  }, []);

  // 管理员轮询全局队列；所有用户只轮询自己的 active 状态。
  useEffect(() => {
    const fetchRuntimeConfig = async () => {
      try {
        const res = await aiApi.getRuntimeConfig();
        setRuntimeConfig(res.data as AIImageRuntimeConfig);
      } catch { /* ignore */ }
    };
    const fetchQueue = async () => {
      if (canViewGlobalQueue) {
        try {
          const res = await aiApi.getQueueStatus();
          setQueueStatus(res.data as QueueStatus);
        } catch { /* ignore */ }
      } else {
        setQueueStatus(null);
      }
      void refreshActiveTasks();
    };
    void fetchRuntimeConfig();
    fetchQueue();
    const timer = setInterval(fetchQueue, 2000);
    return () => clearInterval(timer);
  }, [canViewGlobalQueue, refreshActiveTasks]);

  /** 轮询任务状态直到完成（向后兼容） */
  const pollTask = useCallback(async (taskId: string, model: string, resultMsgId: string, width: number, height: number, clientRequestId?: string) => {
    startPoll(taskId, model, resultMsgId, width, height, clientRequestId);
  }, [startPoll]);

  const submitGenerationAttempt = async (
    request: GenerationRequestSnapshot,
    promptMsgId: string,
    resultMsgId: string,
  ) => {
    const sizeParts = request.size.split('×');
    const width = parseInt(sizeParts[0]) || 1024;
    const height = parseInt(sizeParts[1]) || 1024;
    const clientRequestId = createClientRequestId();
    setMessages(prev => prev.map(msg =>
      msg.id === resultMsgId
        ? { ...msg, content: getWaitingContent('queued'), images: [], taskId: undefined, clientRequestId }
        : msg
    ));

    upsertPendingState({
      promptMsgId,
      resultMsgId,
      prompt: request.prompt,
      model: request.model,
      size: request.size,
      style: request.style,
      generationMode: request.model === 'gptimage25' ? request.generationMode : undefined,
      timestamp: Date.now(),
      clientRequestId,
      status: 'pending',
    });

    try {
      // 构建参考图片参数
      const refParams: Record<string, unknown> = {};
      if (request.refImages.length > 0) {
        const allImages = request.refImages.map(img => img.data);
        if (allImages.length === 1) {
          // 单图：用兼容字段保持向后兼容
          const img = request.refImages[0];
          refParams[img.source === 'gallery' ? 'image_url' : 'image_data'] = img.data;
        } else {
          // 多图：发 images_data 数组（后端 images_data 支持 base64 和 URL 混合）
          refParams.images_data = allImages;
        }
      }

      const res = await aiApi.generateImage({
        prompt: request.prompt,
        client_request_id: clientRequestId,
        model: request.model,
        count: request.count,
        width,
        height,
        style: request.style,
        ...(isGptImageModel(request.model) && request.quality ? { quality: request.quality } : {}),
        ...(request.model === 'gptimage25' && request.generationMode ? { generation_mode: request.generationMode } : {}),
        ...refParams,
      });

      const data = res.data as ImageTaskResponse;

      // 同步模型（如 Seedream）直接返回 image_urls
      if (data.status === 'completed' && data.image_urls && data.image_urls.length > 0) {
        const images = await buildImageResults(data.image_urls, data.task_id, width, height);
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId ? { ...msg, images, taskId: undefined, clientRequestId: undefined, content: '' } : msg
        ));
        removePendingState({ resultMsgId, clientRequestId });
      } else if (data.status === 'failed') {
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId
            ? { ...msg, content: `生成失败: ${data.error || '未知错误'}`, images: [], taskId: undefined, clientRequestId: undefined }
            : msg
        ));
        removePendingState({ resultMsgId, clientRequestId });
      } else if (data.status === 'cancelled') {
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId
            ? { ...msg, content: '已取消', images: [], taskId: undefined, clientRequestId: undefined }
            : msg
        ));
        removePendingState({ resultMsgId, clientRequestId });
      } else {
        // 异步模型，更新 taskId 并开始轮询
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId ? { ...msg, taskId: data.task_id, clientRequestId, content: getWaitingContent(data.status) } : msg
        ));
        upsertPendingState({
          promptMsgId,
          resultMsgId,
          prompt: request.prompt,
          model: request.model,
          size: request.size,
          style: request.style,
          generationMode: request.model === 'gptimage25' ? request.generationMode : undefined,
          timestamp: Date.now(),
          taskId: data.task_id,
          clientRequestId,
          status: 'pending',
        });
        await pollTask(data.task_id, request.model, resultMsgId, width, height, clientRequestId);
      }
    } catch (e) {
      const status = getHttpErrorStatus(e);
      if (status && status >= 400 && status < 500 && status !== 408 && status !== 429) {
        const message = getErrorMessage(e, '请求参数不正确，请检查参考图后重试');
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId
            ? { ...msg, content: `生成失败: ${message}`, images: [], taskId: undefined, clientRequestId: undefined }
            : msg
        ));
        removePendingState({ resultMsgId, clientRequestId });
        toast.error(message);
        return;
      }
      const pendingForRecovery: PendingGenerationState = {
        promptMsgId,
        resultMsgId,
        prompt: request.prompt,
        model: request.model,
        size: request.size,
        style: request.style,
        generationMode: request.model === 'gptimage25' ? request.generationMode : undefined,
        timestamp: Date.now(),
        clientRequestId,
        status: 'reconciling',
      };
      setMessages(prev => prev.map(msg =>
        msg.id === resultMsgId
          ? { ...msg, content: getWaitingContent(undefined, true), images: [], clientRequestId }
          : msg
      ));
      upsertPendingState(pendingForRecovery);
      startRequestRecovery(pendingForRecovery, width, height);
    } finally {
      setSubmitting(false);
      void refreshActiveTasks();
    }
  };

  const ensureGenerationSlot = async () => {
    const active = await refreshActiveTasks();
    const activeCount = active?.active_count ?? effectiveActiveTaskCount;
    const maxActive = active?.max_active ?? maxActiveTasks;
    if (activeCount < maxActive) return true;
    toast.error(`最多同时提交 ${maxActive} 个生图任务，请等待当前任务完成后再试`);
    return false;
  };

  const handleGenerate = async () => {
    if (!prompt.trim() || submitting || !loaded || prompt.length > PROMPT_MAX_LEN) return;
    setSubmitting(true);
    if (!await ensureGenerationSlot()) {
      setSubmitting(false);
      return;
    }
    forceScrollToBottomRef.current = true;
    shouldStickToBottomRef.current = true;

    const timestamp = Date.now();
    const promptMsgId = timestamp.toString();
    const resultMsgId = (timestamp + 1).toString();
    const request: GenerationRequestSnapshot = {
      prompt: prompt.trim(),
      model: selectedModel,
      size: selectedSize,
      style: selectedStyle,
      count: imageCount,
      quality: isGptImageModel(selectedModel) ? selectedQuality : undefined,
      generationMode: selectedModel === 'gptimage25' ? selectedGenerationMode : undefined,
      refImages: refImages.map(image => ({ ...image })),
    };
    const displayTimestamp = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    setMessages(prev => [...prev,
      {
        id: promptMsgId,
        type: 'prompt',
        content: request.prompt,
        images: [],
        timestamp: displayTimestamp,
        params: {
          model: models.find(m => m.id === request.model)?.name || request.model,
          modelId: request.model,
          size: request.size,
          style: request.style,
          count: request.count,
          quality: request.quality,
          generationMode: request.generationMode,
        },
        refImages: request.refImages.length > 0 ? request.refImages : undefined,
      },
      {
        id: resultMsgId,
        type: 'result',
        content: getWaitingContent('queued'),
        images: [],
        timestamp: displayTimestamp,
      },
    ]);
    setRestoredParameters(false);
    setPrompt('');
    setRefImages([]);
    await submitGenerationAttempt(request, promptMsgId, resultMsgId);
  };

  const handleRestoreParameters = (resultMessage: ChatMessage) => {
    if (submitting || !loaded) return;
    const currentMessages = messagesRef.current;
    const resultIndex = currentMessages.findIndex(message => message.id === resultMessage.id);
    const promptMessage = resultIndex > 0
      ? [...currentMessages.slice(0, resultIndex)].reverse().find(message => message.type === 'prompt')
      : undefined;
    if (!promptMessage?.params || !promptMessage.content.trim()) {
      toast.error('未找到这次任务的原始参数，无法载入');
      return;
    }

    const modelId = promptMessage.params.modelId
      || models.find(model => model.name === promptMessage.params?.model)?.id
      || promptMessage.params.model;
    if (!models.some(model => model.id === modelId)) {
      toast.error('原任务使用的模型已不可用，请重新选择模型');
      return;
    }

    const preset = getAspectRatiosForModel(modelId).flatMap(ratio =>
      getResolutionOptions(modelId, ratio.id).filter(option => !option.disabled)
        .map(option => ({ ratio: ratio.id, tier: option.id, size: formatSize(option.w, option.h) }))
    ).find(option => option.size === promptMessage.params?.size);
    if (!preset) {
      toast.error('原任务尺寸已不在当前支持的档位中，请重新选择尺寸');
      return;
    }
    if ((prompt.trim() || refImages.length) && !window.confirm('载入后将替换输入区当前的提示词、参考图和生成设置，是否继续？')) return;
    setPrompt(promptMessage.content);
    setSelectedModel(modelId);
    setSelectedRatio(preset.ratio);
    setSelectedResolutionTier(preset.tier);
    setSelectedSize(preset.size);
    setSelectedStyle(promptMessage.params.style);
    setImageCount(promptMessage.params.count);
    setSelectedQuality(promptMessage.params.quality || 'low');
    setSelectedGenerationMode(promptMessage.params.generationMode || 'fast');
    setRefImages(promptMessage.refImages?.map(image => ({ ...image })) || []);
    setRestoredParameters(true);
    setModelMenuOpen(false);
    expandComposer();
    toast.success('原参数已载入，可修改后再生成');
  };

  const openShareDialog = async (img: AIImageResult, resultMsgId: string) => {
    setShareModal({ img, resultMsgId });
    setShareCategory(DEFAULT_PROMPT_SHARE_CATEGORY);
    setShareCustomCategory('');

    if (shareCategories.length > 1 || loadingShareCategories) return;

    setLoadingShareCategories(true);
    try {
      const res = await promptsApi.getCategories();
      const categoryNames = res.data.categories.map(item => item.name).filter(Boolean);
      setShareCategories(Array.from(new Set([DEFAULT_PROMPT_SHARE_CATEGORY, ...categoryNames])));
    } catch {
      setShareCategories([DEFAULT_PROMPT_SHARE_CATEGORY]);
    } finally {
      setLoadingShareCategories(false);
    }
  };

  const shareToPromptLibrary = async (img: AIImageResult, resultMsgId: string, category: string) => {
    if (sharingImageId) return;
    const finalCategory = category.trim();
    if (!finalCategory) {
      toast.error('请先选择或输入分享标签');
      return;
    }
    setSharingImageId(img.id);
    try {
      const promptMsg = getPromptMessageByResultId(resultMsgId);
      const rawPrompt = promptMsg?.content?.replace(/,\s*\S+风格$/, '')?.trim() || 'AI 生图分享';
      await promptsApi.createPrompt({
        title: rawPrompt.slice(0, 60),
        chinese: rawPrompt,
        english: '',
        category: finalCategory,
        image_url: img.url,
        param_type: promptMsg?.params?.style || '通用',
      });
      toast.success('已分享到提示词宝库');
      setShareModal(null);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '分享失败');
    } finally {
      setSharingImageId(null);
    }
  };

  const confirmShareToPromptLibrary = async () => {
    if (!shareModal) return;
    const finalCategory = shareCustomCategory.trim() || shareCategory;
    await shareToPromptLibrary(shareModal.img, shareModal.resultMsgId, finalCategory);
  };

  const handleDownload = (img: AIImageResult) => {
    if (img.url) {
      const a = document.createElement('a');
      a.href = img.url;
      a.download = 'ai-image.png';
      a.click();
    } else {
      alert('图片生成中，请稍后再试');
    }
  };

  const handleClearHistory = () => {
    if (!confirm('确定要清空所有对话记录吗？')) return;
    setMessages([]);
    const { storageKey } = getActiveKeys();
    const storageCandidates = getFallbackKeys(STORAGE_KEY_BASE, storageKey);
    storageCandidates.forEach(k => localStorage.removeItem(k));
    clearPendingState();
  };

  /** 从图库选择参考图（单选） */
  const handleGallerySelect = (image: GalleryPickerImage) => {
    setRefImages(prev => [...prev, { data: image.url, name: image.name, source: 'gallery' }]);
    setGalleryPickerOpen(false);
  };

  /** 从图库多选参考图 */
  const handleGalleryMultiSelect = (images: GalleryPickerImage[]) => {
    setRefImages(prev => [
      ...prev,
      ...images.map(img => ({ data: img.url, name: img.name, source: 'gallery' as const })),
    ]);
    setGalleryPickerOpen(false);
  };

  /** 清除参考图 */
//  const _clearRefImage = () => {
//    setRefImages([]);
//  };

  /** 移除单张参考图 */
  const removeRefImage = (index: number) => {
    setRefImages(prev => prev.filter((_, i) => i !== index));
  };

  /** 保存 AI 生图结果：弹出选择草稿箱/模版库 */
  const [saveModal, setSaveModal] = useState<{
    img: AIImageResult;
    resultMsgId: string;
  } | null>(null);
  const [saveTarget, setSaveTarget] = useState<'drafts' | 'templates'>('templates');
  const [saveTag, setSaveTag] = useState('');
  const [saveFolders, setSaveFolders] = useState<string[]>([]);
  const [sharingImageId, setSharingImageId] = useState<string | null>(null);
  const [shareModal, setShareModal] = useState<{
    img: AIImageResult;
    resultMsgId: string;
  } | null>(null);
  const [shareCategory, setShareCategory] = useState(DEFAULT_PROMPT_SHARE_CATEGORY);
  const [shareCustomCategory, setShareCustomCategory] = useState('');
  const [shareCategories, setShareCategories] = useState<string[]>([DEFAULT_PROMPT_SHARE_CATEGORY]);
  const [loadingShareCategories, setLoadingShareCategories] = useState(false);

  const getPromptMessageByResultId = useCallback((resultMsgId: string): ChatMessage | null => {
    const msgs = messagesRef.current;
    if (!resultMsgId) {
      for (let i = msgs.length - 1; i >= 0; i -= 1) {
        if (msgs[i]?.type === 'prompt') return msgs[i];
      }
      return null;
    }
    const resultIdx = msgs.findIndex(m => m.id === resultMsgId);
    if (resultIdx >= 0) {
      if (msgs[resultIdx]?.type === 'prompt') return msgs[resultIdx];
      for (let i = resultIdx - 1; i >= 0; i -= 1) {
        if (msgs[i]?.type === 'prompt') return msgs[i];
      }
    }
    return null;
  }, []);

  /** 打开保存对话框 */
  const openSaveDialog = (img: AIImageResult, resultMsgId: string) => {
    setSaveModal({ img, resultMsgId });
    setSaveTarget('templates');
    setSaveTag('');
    setSaveFolders(getUserScopedFolders());
  };

  /** 确认保存 */
  const confirmSave = async () => {
    if (!saveModal) return;
    const { img, resultMsgId } = saveModal;
    setSavingTemplate(true);
    try {
      const promptMsg = getPromptMessageByResultId(resultMsgId);
      const rawPrompt = (promptMsg?.content || '').replace(/,\s*\S+风格$/, '').trim();
      const aiMeta = {
        prompt: rawPrompt || 'AI 生图',
        ref_images: promptMsg?.refImages?.map(r => r.data) ?? [],
        model: promptMsg?.params?.model ?? '',
        size: promptMsg?.params?.size ?? '',
        style: promptMsg?.params?.style ?? '',
        count: promptMsg?.params?.count,
        quality: promptMsg?.params?.quality,
        generation_mode: promptMsg?.params?.generationMode,
      };

      if (saveTarget === 'drafts') {
        // 保存到草稿箱（保留 AI 元数据）
        await materialApi.saveAIDraft({
          name: rawPrompt.slice(0, 50) || 'AI 草稿',
          url: img.url,
          width: img.width,
          height: img.height,
          ai_meta: aiMeta,
        });
        alert('✅ 已保存到草稿箱');
      } else {
        // 保存到模版库，带标签
        const tags = saveTag ? [saveTag] : [];
        await materialApi.saveAITemplate({
          name: rawPrompt.slice(0, 50) || 'AI 模版',
          url: img.url,
          width: img.width,
          height: img.height,
          tags,
          ai_meta: aiMeta,
        });
        alert('✅ 已保存到模版库');
      }
      setSaveModal(null);
    } catch (e) {
      const errorMsg = (e as Error)?.message || '保存失败';
      alert('❌ 保存失败: ' + errorMsg);
    } finally {
      setSavingTemplate(false);
    }
  };

  const deleteMessage = async (msgId: string) => {
    pendingCancelRef.current = null;
    setMessages(prev => {
      const idx = prev.findIndex(m => m.id === msgId);
      if (idx === -1) return prev;
      const msg = prev[idx];
      // 如果删除 prompt，同时删除后面紧跟的 result；反之亦然
      const toDelete = new Set<string>();
      toDelete.add(msgId);
      // 找配对的消息
      if (msg.type === 'prompt' && idx + 1 < prev.length) {
        toDelete.add(prev[idx + 1].id);
      } else if (msg.type === 'result' && idx > 0) {
        toDelete.add(prev[idx - 1].id);
      }
      try {
        const pending = readPendingStates().find(item => toDelete.has(item.promptMsgId) || toDelete.has(item.resultMsgId));
        if (pending) {
          pendingCancelRef.current = pending;
          deletedPendingRef.current = { promptMsgId: pending.promptMsgId, resultMsgId: pending.resultMsgId };
          if (pending.taskId) clearPollTimer(pending.taskId);
          if (pending.clientRequestId) clearPollTimer(`request:${pending.clientRequestId}`);
          removePendingState({
            promptMsgId: pending.promptMsgId,
            resultMsgId: pending.resultMsgId,
            taskId: pending.taskId,
            clientRequestId: pending.clientRequestId,
          });
        }
      } catch {
        // ignore
      }
      const filtered = prev.filter(m => !toDelete.has(m.id));
      persistMessages(filtered);
      return filtered;
    });
    const pendingToCancel = pendingCancelRef.current as PendingGenerationState | null;
    pendingCancelRef.current = null;
    if (pendingToCancel && pendingToCancel.taskId) {
      try {
        await aiApi.cancelTask(pendingToCancel.taskId, (pendingToCancel.model || 'seedream').toLowerCase());
        logDebug('cancelTaskOnDelete', { taskId: pendingToCancel.taskId });
      } catch (e) {
        logDebug('cancelTaskOnDeleteFailed', { error: e instanceof Error ? e.message : String(e) });
      }
    }
  };

  useEffect(() => {
    return () => {
      clearAllPollTimers();
    };
  }, [clearAllPollTimers]);

  return (
    <div className={cn(studio.studio, 'relative h-full overflow-hidden')}>
      <div aria-hidden="true" className={studio.atmosphere} />

      <input ref={fileInputRef} type="file" accept="image/*" multiple className="hidden" onChange={handleFileSelect} />

      <div className="relative z-10 flex h-full w-full flex-col overflow-hidden">
        <section aria-label="创作结果" className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
          <div
            ref={scrollRef}
            data-testid="creation-results-scroller"
            onScroll={handleResultScroll}
            className={cn(studio.resultsScroller, 'relative z-10 flex-1 overflow-auto scrollbar-thin')}
          >
            {reconcilingPending && (
              <div className="mb-3 inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-600">
                <Loader2 className="h-3 w-3 animate-spin" /> 正在同步任务状态
              </div>
            )}
            <div className={cn(studio.resultsInner, 'relative')}>
              {messages.length === 0 && !isGenerating && loaded && (
                <div className={cn(studio.empty, 'absolute inset-0 flex flex-col items-center justify-center text-center')}>
                  <p className={studio.headline}>今天想创作什么？</p>
                  <p className="mt-3 px-4 text-sm leading-6 text-muted-foreground">描述画面，或添加参考图</p>
                </div>
              )}

              {messages.length > 0 && (
                <div className={studio.history}>
                  <div className={studio.historyActions}>
                    <button onClick={handleClearHistory}>
                      <Trash2 />
                      清空记录
                    </button>
                  </div>
                  {generationGroups.map((group, index) => (
                    <article key={group[0].id} aria-label={`创作记录 ${index + 1}`} className={studio.generationCard}>
                    {group.map((msg) => (
                    <div key={msg.id} className={cn('group/msg relative', msg.type === 'prompt' ? studio.promptColumn : studio.resultColumn)}>
                      {msg.type === 'prompt' && (
                        <div className={cn(studio.promptRecord, msg.refImages?.length === 1 && studio.singleReference, 'relative')}>
                          <div className="min-w-0 flex-1">
                            <div className={cn(studio.promptBody, 'relative group/bubble')}>
                              {msg.refImages && msg.refImages.length > 0 && (
                                <div className={studio.referenceStrip}>
                                  {msg.refImages.map((img, idx) => (
                                    <div key={`${img.data}-${idx}`} className={studio.referenceThumbnail}>
                                      <img src={img.data} alt={img.name || `参考图 ${idx + 1}`} className="h-full w-full object-contain" />
                                    </div>
                                  ))}
                                  {msg.refImages.length > 1 && <div className="flex items-center gap-1 self-center text-[10px] text-slate-400">
                                    <ImageIcon className="h-3 w-3" />
                                    <span>{msg.refImages.length} 张参考图</span>
                                  </div>}
                                </div>
                              )}
                              <p className={cn(studio.promptText, 'whitespace-pre-wrap break-words')}>{msg.content}</p>
                            </div>
                            {msg.params && (
                              <div className={studio.recordParameters}>
                                <span>{msg.params.model}</span>
                                <span>{msg.params.size}</span>
                                <span>{msg.params.style}</span>
                                {msg.params.generationMode && (
                                  <span>{getGenerationModeLabel(msg.params.generationMode)}</span>
                                )}
                                {msg.params.quality && (
                                  <span>{msg.params.quality === 'high' ? '高质量' : msg.params.quality === 'medium' ? '中质量' : '低质量'}</span>
                                )}
                                <span>{msg.params.count} 张</span>
                                <time className="ml-auto">{msg.timestamp}</time>
                              </div>
                            )}
                            <button onClick={() => deleteMessage(msg.id)} className={studio.deleteRecord} title="删除"><Trash2 className="h-3.5 w-3.5" /></button>
                          </div>
                        </div>
                      )}

                      {msg.type === 'result' && (
                        <div className={studio.resultRecord}>
                          <div className={studio.resultHeading}>
                            {msg.taskId || msg.clientRequestId ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : msg.images.length > 0 ? (
                              <CheckCircle2 className="h-4 w-4" />
                            ) : msg.content.startsWith('生成失败') || msg.content.startsWith('已取消') ? (
                              <AlertCircle className="h-4 w-4" />
                            ) : (
                              <CheckCircle2 className="h-4 w-4" />
                            )}
                            <span>{msg.taskId || msg.clientRequestId ? '正在生成' : msg.images.length ? '已完成' : '未完成'}</span>
                            <span className={studio.resultType}>{group[0].params?.model || 'AI IMAGE'}</span>
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="relative group/bubble">
                              {msg.content && (
                                <div className={cn(
                                  studio.taskState,
                                  msg.content.startsWith('生成失败') || msg.content.startsWith('已取消')
                                    ? studio.taskFailed : studio.taskWaiting
                                )}>
                                  <p className="max-w-full break-words text-[13px] leading-6">{msg.content}</p>
                                  {msg.content.startsWith('生成失败') && (
                                    <div className="mt-3 flex flex-wrap items-center gap-2.5">
                                      <button
                                        type="button"
                                        onClick={() => handleRestoreParameters(msg)}
                                        disabled={submitting || !loaded}
                                        className={studio.restoreButton}
                                      >
                                        <RotateCcw className="h-3.5 w-3.5" />
                                        载入参数并修改
                                      </button>
                                      <span className="text-[11px] text-slate-400">恢复到输入区，不会直接生成</span>
                                    </div>
                                  )}
                                  <button onClick={() => deleteMessage(msg.id)}
                                    className={studio.deleteRecord}
                                    title="删除">
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              )}
                              {msg.images.length > 0 && (
                                <div className="relative">
                                  <div className={cn(studio.outputGrid, msg.images.length === 1 && studio.singleOutput)}>
                                    {msg.images.map((img) => (
                                      <div key={img.id} className={cn(studio.outputImage, 'group relative cursor-zoom-in')} style={{ aspectRatio: `${img.width} / ${img.height}` }} onClick={() => setPreviewImage(img)}>
                                        <img src={img.url} alt="生成图片" className="h-full w-full object-contain" />
                                        <div className="absolute inset-0 bg-gradient-to-t from-slate-950/70 via-transparent to-transparent opacity-0 transition-opacity group-hover:opacity-100">
                                          <div className="absolute bottom-0 left-0 right-0 flex items-center justify-center gap-2 p-4">
                                            <button onClick={(e) => { e.stopPropagation(); openShareDialog(img, msg.id); }}
                                              disabled={sharingImageId === img.id}
                                              className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20 text-white backdrop-blur-md transition-colors hover:bg-white/30 disabled:opacity-50"
                                              title="分享到提示词宝库">
                                              {sharingImageId === img.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Share2 className="h-4 w-4" />}
                                            </button>
                                            <button onClick={(e) => { e.stopPropagation(); handleDownload(img); }}
                                              className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20 text-white backdrop-blur-md transition-colors hover:bg-white/30"
                                              title="下载">
                                              <Download className="h-4 w-4" />
                                            </button>
                                            <button onClick={(e) => { e.stopPropagation(); openSaveDialog(img, msg.id); }}
                                              disabled={savingTemplate}
                                              className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20 text-white backdrop-blur-md transition-colors hover:bg-white/30 disabled:opacity-50"
                                              title="保存">
                                              {savingTemplate ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                                            </button>
                                            <button onClick={(e) => { e.stopPropagation(); setPreviewImage(img); }}
                                              className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20 text-white backdrop-blur-md transition-colors hover:bg-white/30"
                                              title="预览">
                                              <Maximize2 className="h-4 w-4" />
                                            </button>
                                          </div>
                                        </div>
                                        <div className="absolute right-3 top-3 rounded-full bg-slate-950/55 px-2 py-1 text-[10px] font-medium text-white opacity-0 backdrop-blur-sm transition-opacity group-hover:opacity-100">
                                          {img.width}×{img.height}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                  {!msg.content && (
                                    <button onClick={() => deleteMessage(msg.id)}
                                      className={studio.deleteRecord}
                                      title="删除">
                                      <Trash2 className="h-3.5 w-3.5" />
                                    </button>
                                  )}
                                </div>
                              )}
                              {msg.images.length > 0 && <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-slate-400"><span>{msg.images.length} 张图片</span><button type="button" className={studio.restoreButton} disabled={submitting || !loaded} onClick={() => handleRestoreParameters(msg)}><RotateCcw className="h-3 w-3" />载入参数并修改</button></div>}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                    ))}
                    </article>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>
        <section
          aria-label="创作控制台"
          data-mode={composerCompact ? 'compact' : 'expanded'}
          className={cn(studio.composerFrame, composerCompact && studio.composerFrameCompact)}
        >
          {composerCompact && messages.length > 0 && (
            <button type="button" className={studio.returnToBottom} onClick={returnToBottom}>
              回到底部
              <ChevronDown />
            </button>
          )}
          {restoredParameters && <div role="status" className={studio.restoredNotice}><RotateCcw className="h-3 w-3" /><span>已载入原任务参数，可修改后再生成</span><button type="button" aria-label="关闭参数载入提示" onClick={() => setRestoredParameters(false)}><X className="h-3 w-3" /></button></div>}
          <div
            className={studio.composer}
            onClick={() => { if (composerCompact) expandComposer(); }}
          >
          <div className={studio.composerSurface}>
            <div className={studio.composerTop} aria-hidden={composerCompact}>
              <div ref={modelMenuRef} className="relative z-30 shrink-0">
                <button
                  type="button"
                  aria-haspopup="listbox"
                  aria-expanded={modelMenuOpen}
                  onClick={() => {
                    setModelMenuOpen(open => !open);
                    setSettingsMenuOpen(false);
                  }}
                  className={studio.modelTrigger}
                >
                  <span className={studio.modelIcon} data-brand={selectedModelInfo.brand}>
                    <SelectedModelIcon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-[13px] font-semibold text-slate-950">{selectedModelInfo.name}</span>
                      {selectedModelInfo.badge && (
                        <span className="rounded-md border border-indigo-100 bg-indigo-50 px-1.5 py-0.5 text-[9px] font-medium text-primary">新一代</span>
                      )}
                    </span>
                  </span>
                  <ChevronDown className={cn('h-3 w-3 shrink-0 text-slate-400 transition-transform', modelMenuOpen && 'rotate-180')} />
                </button>

                {modelMenuOpen && (
                  <div
                    role="listbox"
                    aria-label="选择 AI 模型"
                    className={cn(studio.modelMenu, 'rounded-[22px] border border-slate-200 bg-white p-2 shadow-[0_12px_36px_rgba(15,23,42,0.14)]')}
                  >
                    <div className="px-2 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">生成引擎</div>
                    <div className="space-y-1">
                      {models.map(model => {
                        const Icon = model.icon;
                        const selected = model.id === selectedModel;
                        return (
                          <button
                            key={model.id}
                            type="button"
                            role="option"
                            aria-selected={selected}
                            onClick={() => selectModel(model.id)}
                            className={cn(
                              'group/model flex w-full items-center gap-3 rounded-2xl border px-2.5 py-2.5 text-left transition-all',
                              selected
                                ? 'border-indigo-100 bg-indigo-50'
                                : 'border-transparent hover:border-slate-200 hover:bg-slate-50',
                            )}
                          >
                            <span className={studio.modelOptionIcon} data-brand={model.brand}>
                              <Icon className="h-4 w-4" />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="flex items-center gap-2">
                                <span className="text-sm font-semibold text-slate-800">{model.name}</span>
                                {model.badge && <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[9px] font-medium tracking-wide text-primary">{model.badge}</span>}
                              </span>
                              <span className="mt-0.5 block text-xs leading-4 text-slate-400">{model.note} · {model.desc}</span>
                            </span>
                            <span className={cn(
                              'flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-all',
                              selected ? 'border-primary bg-primary text-white' : 'border-slate-200 bg-white text-transparent',
                            )}>
                              <CheckCircle2 className="h-3 w-3" />
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              {selectedModel === 'gptimage25' && (
                <div className={studio.modeSwitch}>
                  {generationModes.map(mode => {
                    const Icon = mode.icon;
                    const selected = selectedGenerationMode === mode.id;
                    return (
                      <button
                        key={mode.id}
                        type="button"
                        aria-pressed={selected}
                        title={mode.desc}
                        onClick={() => setSelectedGenerationMode(mode.id)}
                        className={cn(studio.modeOption, selected && studio.modeOptionSelected)}
                      >
                        <Icon />
                        <span>{mode.label}</span>
                      </button>
                    );
                  })}
                </div>
              )}

              <div ref={settingsMenuRef} className={studio.settingsControl}>
                <button
                  type="button"
                  aria-label="生成参数"
                  aria-haspopup="dialog"
                  aria-expanded={settingsMenuOpen}
                  onClick={() => {
                    setSettingsMenuOpen(open => !open);
                    setModelMenuOpen(false);
                  }}
                  className={studio.settingsTrigger}
                >
                  <SlidersHorizontal />
                  <span>{selectedRatio}</span>
                  <span className={studio.settingsTriggerMeta}>· {activeResolutionOption.label} · {imageCount}张</span>
                  <ChevronDown className={cn(settingsMenuOpen && studio.chevronOpen)} />
                </button>

                {settingsMenuOpen && (
                  <div
                    role="dialog"
                    aria-label="生成参数设置"
                    className={studio.settingsMenu}
                    onClick={event => event.stopPropagation()}
                  >
                    <div className={studio.settingsMenuHeader}>
                      <div>
                        <p>生成参数</p>
                        <span>统一设置画幅与输出规格</span>
                      </div>
                      <button type="button" aria-label="关闭生成参数" onClick={() => setSettingsMenuOpen(false)}><X /></button>
                    </div>

                    <section className={studio.settingsSection}>
                      <p className={studio.settingsLabel}>画面比例</p>
                      <div role="group" aria-label="画面比例" className={studio.ratioOptions}>
                        {availableAspectRatios.map(item => (
                          <button
                            key={item.id}
                            type="button"
                            aria-pressed={selectedRatio === item.id}
                            className={studio.ratioOption}
                            onClick={() => setSelectedRatio(item.id)}
                          >
                            <span className={studio.ratioGlyph}>
                              <i style={{ aspectRatio: item.id.replace(':', ' / ') }} />
                            </span>
                            <span>{item.label}</span>
                          </button>
                        ))}
                      </div>
                    </section>

                    <section className={studio.settingsSection}>
                      <p className={studio.settingsLabel}>分辨率</p>
                      <div role="group" aria-label="分辨率" className={studio.segmentedOptions}>
                        {selectedResolutionOptions.map(option => (
                          <button
                            key={option.id}
                            type="button"
                            disabled={option.disabled}
                            aria-pressed={selectedResolutionTier === option.id}
                            title={option.disabled ? option.note : formatSize(option.w, option.h)}
                            onClick={() => setSelectedResolutionTier(option.id)}
                          >
                            <span>{option.label}</span>
                            {!option.disabled && <small>{formatSize(option.w, option.h)}</small>}
                          </button>
                        ))}
                      </div>
                    </section>

                    <section className={studio.settingsSection}>
                      <p className={studio.settingsLabel}>生成数量</p>
                      <div role="group" aria-label="生成数量" className={studio.countOptions}>
                        {[1, 2, 4].map(count => (
                          <button key={count} type="button" aria-pressed={imageCount === count} onClick={() => setImageCount(count)}>{count}</button>
                        ))}
                      </div>
                    </section>

                    {isGptImageModel(selectedModel) && (
                      <section className={studio.settingsSection}>
                        <p className={studio.settingsLabel}>图像质量</p>
                        <div role="group" aria-label="图像质量" className={studio.qualityOptions}>
                          {qualities.map(option => (
                            <button key={option.id} type="button" aria-pressed={selectedQuality === option.id} onClick={() => setSelectedQuality(option.id)}>
                              <span>{option.label}质量</span>
                              <small>{option.desc}</small>
                            </button>
                          ))}
                        </div>
                      </section>
                    )}

                    <section className={studio.settingsSection}>
                      <p className={studio.settingsLabel}>画面风格</p>
                      <div role="group" aria-label="画面风格" className={studio.styleOptions}>
                        {styles.map(style => (
                          <button key={style} type="button" aria-pressed={selectedStyle === style} onClick={() => setSelectedStyle(style)}>{style}</button>
                        ))}
                      </div>
                    </section>
                  </div>
                )}
              </div>

              <div className={studio.referenceActions} role="group" aria-label="添加参考图">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={refImages.length >= 10}
                  className={cn(studio.sourceAction, studio.localSourceAction)}
                  title="从电脑选择图片"
                >
                  <Upload className="h-3.5 w-3.5" />
                  <span>本地导入</span>
                </button>
                <button
                  type="button"
                  onClick={() => setGalleryPickerOpen(true)}
                  disabled={refImages.length >= 10}
                  className={cn(studio.sourceAction, studio.gallerySourceAction)}
                  title="从我的图库选择图片"
                >
                  <Images className="h-3.5 w-3.5" />
                  <span>我的图库</span>
                </button>
              </div>

              <button
                type="button"
                aria-label={generateLabel}
                title={generateLabel}
                onClick={handleGenerate}
                disabled={!prompt.trim() || !canStartMoreTasks || !loaded || prompt.length > PROMPT_MAX_LEN}
                className={studio.generate}
              >
                {submitting ? <Loader2 className="animate-spin" /> : <ArrowUp />}
              </button>
            </div>
            <div className={studio.composerBody}>
              <button
                type="button"
                aria-label="展开并添加参考图"
                className={studio.compactReferenceAction}
                onClick={(event) => {
                  event.stopPropagation();
                  expandComposer();
                  requestAnimationFrame(() => fileInputRef.current?.click());
                }}
              >
                <ImagePlus />
              </button>
              <div className={studio.composerDraft}>
                {refImages.length > 0 && <div className={cn(studio.composerReferences, 'scrollbar-thin')}>
                  {refImages.map((img, idx) => <div
                    key={idx}
                    className={studio.composerReferenceThumbnail}
                    title={`${img.source === 'local' ? '本地导入' : '我的图库'} · ${img.name}`}
                  >
                    <img src={img.data} alt={img.name} className="h-full w-full object-cover" />
                    <span className={cn(
                      studio.referenceSourceBadge,
                      img.source === 'local' ? studio.localSourceBadge : studio.gallerySourceBadge,
                    )}>
                      {img.source === 'local' ? '本地' : '图库'}
                    </span>
                    <button onClick={() => removeRefImage(idx)} aria-label={'移除参考图 ' + (idx + 1)} className="absolute right-0 top-0 rounded-full bg-slate-900/70 p-0.5 text-white hover:bg-red-500"><X className="h-3 w-3" /></button>
                  </div>)}
                </div>}
                <textarea ref={promptInputRef} id="ai-creation-prompt" aria-label="画面描述" value={prompt} onChange={e => setPrompt(e.target.value)}
                  onFocus={() => {
                    composerExpandedByUserRef.current = true;
                    setComposerCompact(false);
                  }}
                  onKeyDown={e => {
                    // Enter also confirms Chinese IME candidates; only submit committed input.
                    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                      e.preventDefault();
                      handleGenerate();
                    }
                  }}
                  placeholder={refImages.length ? '描述你希望如何修改参考图…' : '描述你想创造的画面，或者添加一张参考图…'}
                  className={cn(studio.promptInput, 'border-0 bg-transparent pt-0.5 text-[13px] leading-[1.75] tracking-[0.01em] text-slate-700 placeholder:text-slate-400 focus:outline-none focus:ring-0')}
                />
              </div>
              <button
                type="button"
                aria-label={generateLabel}
                title={generateLabel}
                onClick={(event) => {
                  event.stopPropagation();
                  handleGenerate();
                }}
                disabled={!prompt.trim() || !canStartMoreTasks || !loaded || prompt.length > PROMPT_MAX_LEN}
                className={studio.compactGenerate}
              >
                {submitting ? <Loader2 className="animate-spin" /> : <ArrowUp />}
              </button>
            </div>
          </div>
          </div>
          <div className={studio.composerMeta}>
            <span>{formatSize(activeResolutionOption.w, activeResolutionOption.h)} px</span>
            <span className={cn('tabular-nums', prompt.length > PROMPT_MAX_LEN && 'text-red-600')}>{prompt.length} / {PROMPT_MAX_LEN}</span>
            <span>Shift + Enter 换行</span>
            {effectiveActiveTaskCount > 0 && <span>正在处理 {effectiveActiveTaskCount} 个任务</span>}
            {canViewGlobalQueue && !!queueStatus?.pending && <span>队列中 {queueStatus.pending} 个任务</span>}
          </div>
        </section>
      </div>

      {/* ===== 图片预览弹窗 ===== */}
      {previewImage && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm" onClick={() => setPreviewImage(null)}>
          <button onClick={() => setPreviewImage(null)} className="absolute right-4 top-4 z-10 flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20">
            <X className="h-5 w-5" />
          </button>
          <div onClick={(e) => e.stopPropagation()} className="mx-4 flex max-h-[88vh] max-w-[92vw] flex-col items-center">
            <div className="overflow-hidden rounded-[28px] border border-white/20 bg-slate-950/30 shadow-2xl">
              <img
                src={previewImage.url}
                alt=""
                className="block max-h-[80vh] max-w-[92vw] object-contain"
              />
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
              <button
                onClick={() => openShareDialog(
                  previewImage,
                  messages.find(m => m.images?.some(i => i.id === previewImage.id))?.id || ''
                )}
                disabled={sharingImageId === previewImage.id}
                className="flex items-center gap-1.5 rounded-2xl bg-white/10 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/20 disabled:opacity-50">
                {sharingImageId === previewImage.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Share2 className="h-4 w-4" />}
                分享到提示词宝库
              </button>
              <button onClick={() => openSaveDialog(previewImage, messages.find(m => m.images?.some(i => i.id === previewImage.id))?.id || '')}
                disabled={savingTemplate}
                className="flex items-center gap-1.5 rounded-2xl bg-white/10 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/20 disabled:opacity-50">
                {savingTemplate ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}保存
              </button>
              <button onClick={() => handleDownload(previewImage)}
                className="flex items-center gap-1.5 rounded-2xl bg-white/10 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/20">
                <Download className="h-4 w-4" />下载
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== 分享到提示词库弹窗 ===== */}
      {shareModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 backdrop-blur-sm" onClick={() => setShareModal(null)}>
          <div onClick={(e) => e.stopPropagation()} className="w-[380px] max-w-[calc(100vw-32px)] overflow-hidden rounded-[28px] border border-white/70 bg-white/95 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">分享到提示词库</h3>
                <p className="mt-0.5 text-xs text-slate-400">先选择这张图归属的标签</p>
              </div>
              <button onClick={() => setShareModal(null)} className="rounded-full p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="px-4 pt-3">
              <div className="mx-auto aspect-[3/4] max-h-64 overflow-hidden rounded-2xl border border-slate-100 bg-slate-100">
                <img src={shareModal.img.url} alt="" className="h-full w-full object-cover" />
              </div>
            </div>

            <div className="px-4 pb-3 pt-4">
              <label className="mb-2 block text-xs font-medium text-slate-500">选择标签</label>
              <div className="flex max-h-28 flex-wrap gap-1.5 overflow-auto rounded-2xl border border-slate-100 bg-slate-50/70 p-2">
                {loadingShareCategories && (
                  <span className="inline-flex items-center gap-1 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-400">
                    <Loader2 className="h-3 w-3 animate-spin" />加载标签
                  </span>
                )}
                {shareCategories.map(tag => (
                  <button
                    key={tag}
                    onClick={() => {
                      setShareCategory(tag);
                      setShareCustomCategory('');
                    }}
                    className={cn(
                      'rounded-xl border px-2.5 py-1.5 text-xs transition-colors',
                      !shareCustomCategory.trim() && shareCategory === tag
                        ? 'border-indigo-300 bg-indigo-50 font-medium text-indigo-600'
                        : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                    )}
                  >
                    {tag}
                  </button>
                ))}
              </div>

              <label className="mb-1.5 mt-3 block text-xs font-medium text-slate-500">或者输入新标签</label>
              <input
                value={shareCustomCategory}
                onChange={(e) => setShareCustomCategory(e.target.value)}
                placeholder="例如：汽车海报 / 产品场景 / 人像写真"
                className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
              />
            </div>

            <div className="flex gap-2 border-t border-slate-100 px-4 py-3">
              <button onClick={() => setShareModal(null)}
                className="flex-1 rounded-2xl border border-slate-200 px-4 py-2 text-xs font-semibold text-slate-500 transition-colors hover:bg-slate-50">
                取消
              </button>
              <button onClick={confirmShareToPromptLibrary} disabled={sharingImageId === shareModal.img.id}
                className="flex-1 rounded-2xl bg-gradient-to-r from-indigo-500 to-violet-500 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-indigo-200 transition-colors disabled:opacity-50">
                {sharingImageId === shareModal.img.id ? <Loader2 className="mx-auto h-3.5 w-3.5 animate-spin" /> : '确认分享'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== 保存选择弹窗 ===== */}
      {saveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 backdrop-blur-sm" onClick={() => setSaveModal(null)}>
          <div onClick={(e) => e.stopPropagation()} className="w-80 overflow-hidden rounded-[28px] border border-white/70 bg-white/95 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
              <h3 className="text-sm font-semibold text-slate-900">保存到</h3>
              <button onClick={() => setSaveModal(null)} className="rounded-full p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="px-4 pt-3">
              <div className="aspect-square w-full overflow-hidden rounded-2xl border border-slate-100 bg-slate-100">
                <img src={saveModal.img.url} alt="" className="h-full w-full object-cover" />
              </div>
            </div>

            <div className="flex gap-2 px-4 pb-2 pt-3">
              <button
                onClick={() => setSaveTarget('drafts')}
                className={cn(
                  'flex flex-1 items-center justify-center gap-2 rounded-2xl border py-2.5 text-xs font-semibold transition-colors',
                  saveTarget === 'drafts'
                    ? 'border-indigo-300 bg-indigo-50 text-indigo-600'
                    : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                )}
              >
                <ImagePlus className="h-3.5 w-3.5" />草稿箱
              </button>
              <button
                onClick={() => setSaveTarget('templates')}
                className={cn(
                  'flex flex-1 items-center justify-center gap-2 rounded-2xl border py-2.5 text-xs font-semibold transition-colors',
                  saveTarget === 'templates'
                    ? 'border-indigo-300 bg-indigo-50 text-indigo-600'
                    : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                )}
              >
                <Save className="h-3.5 w-3.5" />模版库
              </button>
            </div>

            {saveTarget === 'templates' && (
              <div className="px-4 pb-3">
                <label className="mb-1.5 block text-xs text-slate-400">选择文件夹标签</label>
                <div className="flex flex-wrap gap-1.5">
                  <button
                    onClick={() => setSaveTag('')}
                    className={cn(
                      'rounded-xl border px-2.5 py-1.5 text-xs transition-colors',
                      !saveTag
                        ? 'border-indigo-300 bg-indigo-50 font-medium text-indigo-600'
                        : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                    )}
                  >
                    未分类
                  </button>
                  {saveFolders.map(tag => (
                    <button key={tag}
                      onClick={() => setSaveTag(tag)}
                      className={cn(
                        'rounded-xl border px-2.5 py-1.5 text-xs transition-colors',
                        saveTag === tag
                          ? 'border-indigo-300 bg-indigo-50 font-medium text-indigo-600'
                          : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                      )}
                    >
                      {tag}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="flex gap-2 border-t border-slate-100 px-4 py-3">
              <button onClick={() => setSaveModal(null)}
                className="flex-1 rounded-2xl border border-slate-200 px-4 py-2 text-xs font-semibold text-slate-500 transition-colors hover:bg-slate-50">
                取消
              </button>
              <button onClick={confirmSave} disabled={savingTemplate}
                className="flex-1 rounded-2xl bg-gradient-to-r from-indigo-500 to-violet-500 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-indigo-200 transition-colors disabled:opacity-50">
                {savingTemplate ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : '确认保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      <GalleryPicker
        open={galleryPickerOpen}
        onClose={() => setGalleryPickerOpen(false)}
        onSelect={handleGallerySelect}
        multiSelect
        onMultiSelect={handleGalleryMultiSelect}
        existingIds={refImages.map((img) => img.data)}
      />
    </div>
  );
}
