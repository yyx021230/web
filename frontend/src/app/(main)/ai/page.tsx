'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  Sparkles, Download, Share2, Maximize2, Loader2, X, ChevronDown, CheckCircle2, AlertCircle,
  ImagePlus, Trash2, Image as ImageIcon, FolderOpen, Save, BookOpen,
} from 'lucide-react';
import { aiApi, type ActiveImageTasksResponse, type AIImageRuntimeConfig, type ImageTaskResponse, type QueueStatus } from '@/services/aiApi';
import { editorApi } from '@/services/editorApi';
import { promptsApi } from '@/services/promptsApi';
import { toast } from '@/lib/toast';
import GalleryPicker, { type GalleryPickerImage } from '@/components/ai/GalleryPicker';

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
  params?: { model: string; size: string; style: string; count: number; quality?: string };
  refImages?: RefImageItem[]; // 参考图片列表（用于图生图）
  taskId?: string; // 异步任务的 task_id（用于轮询）
  clientRequestId?: string; // 前端提交请求幂等 ID（用于找回任务）
}

interface AIImageResult {
  id: string;
  url: string;
  width: number;
  height: number;
  liked: boolean;
}

const models = [
  { id: 'seedream', name: 'Seedream', desc: '字节跳动' },
  { id: 'gptimage2', name: 'GPT Image 2', desc: 'OpenAI' },
];

const qualities = [
  { id: 'low', label: '低', desc: '快速/便宜' },
  { id: 'medium', label: '中', desc: '均衡' },
  { id: 'high', label: '高', desc: '精细/最贵' },
];

type AspectRatioId = '1:1' | '4:5' | '3:4' | '2:3' | '9:16' | '4:3' | '3:2' | '16:9';
type ResolutionTierId = '1K' | '2K' | '3K' | '4K';

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
const getAspectRatiosForModel = (model: string) => {
  const ids = model === 'gptimage2' ? gptimage2RatioIds : seedreamRatioIds;
  return ids.map(id => aspectRatios.find(ratio => ratio.id === id)).filter(Boolean) as typeof aspectRatios;
};
const getResolutionOptions = (model: string, ratio: AspectRatioId) => {
  const map = model === 'gptimage2' ? gptimage2ResolutionMap : seedreamResolutionMap;
  return resolutionTiers.map(tier => map[ratio][tier.id]);
};
const getDefaultPreset = (model: string): { ratio: AspectRatioId; tier: ResolutionTierId; size: string } => {
  const ratio: AspectRatioId = '1:1';
  const tier: ResolutionTierId = model === 'gptimage2' ? '1K' : '2K';
  const option = getResolutionOptions(model, ratio).find(item => item.id === tier) || getResolutionOptions(model, ratio)[0];
  return { ratio, tier: option.id, size: formatSize(option.w, option.h) };
};

const styles = ['写实', '插画', '3D', '动漫', '水彩', '像素', '油画', '极简', '赛博朋克', '扁平化'];

/** 轮询间隔(ms)：运行时会优先使用后端配置 */
const POLL_INTERVAL = 2000;
const MAX_PARALLEL_TASKS = 6;
const STORAGE_KEY_BASE = 'ai_image_messages';
const PENDING_KEY_BASE = 'ai_pending_generation';
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
  const router = useRouter();
  const initialPreset = getDefaultPreset('seedream');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [reconcilingPending, setReconcilingPending] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);
  const [activeTasks, setActiveTasks] = useState<ActiveImageTasksResponse | null>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<AIImageRuntimeConfig | null>(null);
  const [selectedModel, setSelectedModel] = useState('seedream');
  const [selectedRatio, setSelectedRatio] = useState<AspectRatioId>(initialPreset.ratio);
  const [selectedResolutionTier, setSelectedResolutionTier] = useState<ResolutionTierId>(initialPreset.tier);
  const [selectedSize, setSelectedSize] = useState(initialPreset.size);
  const [selectedStyle, setSelectedStyle] = useState('写实');
  const [selectedQuality, setSelectedQuality] = useState('low');
  const [imageCount, setImageCount] = useState(1);
  const [previewImage, setPreviewImage] = useState<AIImageResult | null>(null);
  const [refImages, setRefImages] = useState<RefImageItem[]>([]); // 参考图片列表
  const [galleryPickerOpen, setGalleryPickerOpen] = useState(false);
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [scopedKeys, setScopedKeys] = useState<{ storageKey: string; pendingKey: string } | null>(null);
  const pollTimersRef = useRef<Record<string, number>>({});
  const runtimeConfigRef = useRef<AIImageRuntimeConfig | null>(null);
  const deletedPendingRef = useRef<{ promptMsgId?: string; resultMsgId?: string } | null>(null);
  const pendingCancelRef = useRef<PendingGenerationState | null>(null);
  const debugStorageRef = useRef(false);
  const availableAspectRatios = getAspectRatiosForModel(selectedModel);
  const showResolutionTiers = selectedModel === 'gptimage2';
  const selectedResolutionOptions = getResolutionOptions(selectedModel, selectedRatio);
  const activeResolutionOption = selectedResolutionOptions.find(item => item.id === selectedResolutionTier && !item.disabled)
    || selectedResolutionOptions.find(item => !item.disabled)
    || selectedResolutionOptions[0];
  const selectedModelInfo = models.find(item => item.id === selectedModel) || models[0];

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
    shouldStickToBottomRef.current = distanceToBottom < 120;
  }, []);

  const getActiveKeys = useCallback(() => {
    if (scopedKeys) return scopedKeys;
    return {
      storageKey: getUserScopedKey(STORAGE_KEY_BASE),
      pendingKey: getUserScopedKey(PENDING_KEY_BASE),
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
          params: { model: pending.model || 'seedream', size: pending.size || '2048×2048', style: pending.style || '写实', count: 1 },
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
    const preferredTier: ResolutionTierId = selectedModel === 'gptimage2' ? selectedResolutionTier : '2K';
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
      const { storageKey, pendingKey } = scopedKeys;
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

  // 持久化到 localStorage（包含进行中的任务）
  useEffect(() => {
    if (!loaded || !scopedKeys) return;
    persistMessages(messages);
  }, [messages, loaded, persistMessages, scopedKeys]);

  // 轮询队列和当前用户 active 状态（每 2 秒）
  useEffect(() => {
    const fetchRuntimeConfig = async () => {
      try {
        const res = await aiApi.getRuntimeConfig();
        setRuntimeConfig(res.data as AIImageRuntimeConfig);
      } catch { /* ignore */ }
    };
    const fetchQueue = async () => {
      try {
        const res = await aiApi.getQueueStatus();
        setQueueStatus(res.data as QueueStatus);
      } catch { /* ignore */ }
      void refreshActiveTasks();
    };
    void fetchRuntimeConfig();
    fetchQueue();
    const timer = setInterval(fetchQueue, 2000);
    return () => clearInterval(timer);
  }, [refreshActiveTasks]);

  /** 轮询任务状态直到完成（向后兼容） */
  const pollTask = useCallback(async (taskId: string, model: string, resultMsgId: string, width: number, height: number, clientRequestId?: string) => {
    startPoll(taskId, model, resultMsgId, width, height, clientRequestId);
  }, [startPoll]);

  const handleGenerate = async () => {
    if (!prompt.trim() || submitting || !loaded || prompt.length > PROMPT_MAX_LEN) return;
    setSubmitting(true);
    const active = await refreshActiveTasks();
    const activeCount = active?.active_count ?? effectiveActiveTaskCount;
    const maxActive = active?.max_active ?? maxActiveTasks;
    if (activeCount >= maxActive) {
      toast.error(`最多同时提交 ${maxActive} 个生图任务，请等待当前任务完成后再试`);
      setSubmitting(false);
      return;
    }
    forceScrollToBottomRef.current = true;
    shouldStickToBottomRef.current = true;

    const sizeParts = selectedSize.split('×');
    const width = parseInt(sizeParts[0]) || 1024;
    const height = parseInt(sizeParts[1]) || 1024;

    const currentRefImages = refImages;
    const promptMessage: ChatMessage = {
      id: Date.now().toString(), type: 'prompt', content: prompt, images: [],
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      params: {
        model: models.find(m => m.id === selectedModel)?.name || selectedModel,
        size: selectedSize,
        style: selectedStyle,
        count: imageCount,
        quality: selectedModel === 'gptimage2' ? selectedQuality : undefined,
      },
      refImages: currentRefImages.length > 0 ? [...currentRefImages] : undefined,
    };
    setMessages(prev => [...prev, promptMessage]);
    const currentPrompt = prompt;
    setPrompt('');
    setRefImages([]);

    const resultMsgId = (Date.now() + 1).toString();
    const clientRequestId = createClientRequestId();
    // 先显示一个加载中的结果占位
    setMessages(prev => [...prev, {
      id: resultMsgId, type: 'result', content: getWaitingContent('queued'), images: [],
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      clientRequestId,
    }]);

    upsertPendingState({
      promptMsgId: promptMessage.id,
      resultMsgId,
      prompt: currentPrompt,
      model: selectedModel,
      size: selectedSize,
      style: selectedStyle,
      timestamp: Date.now(),
      clientRequestId,
      status: 'pending',
    } as PendingGenerationState);

    try {
      // 构建参考图片参数
      const refParams: Record<string, unknown> = {};
      if (currentRefImages.length > 0) {
        const allImages = currentRefImages.map(img => img.data);
        if (allImages.length === 1) {
          // 单图：用兼容字段保持向后兼容
          const img = currentRefImages[0];
          refParams[img.source === 'gallery' ? 'image_url' : 'image_data'] = img.data;
        } else {
          // 多图：发 images_data 数组（后端 images_data 支持 base64 和 URL 混合）
          refParams.images_data = allImages;
        }
      }

      const res = await aiApi.generateImage({
        prompt: currentPrompt,
        client_request_id: clientRequestId,
        model: selectedModel,
        count: imageCount,
        width,
        height,
        style: selectedStyle,
        ...(selectedModel === 'gptimage2' ? { quality: selectedQuality } : {}),
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
          promptMsgId: promptMessage.id,
          resultMsgId,
          prompt: currentPrompt,
          model: selectedModel,
          size: selectedSize,
          style: selectedStyle,
          timestamp: Date.now(),
          taskId: data.task_id,
          clientRequestId,
          status: 'pending',
        });
        await pollTask(data.task_id, selectedModel, resultMsgId, width, height, clientRequestId);
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
        promptMsgId: promptMessage.id,
        resultMsgId,
        prompt: currentPrompt,
        model: selectedModel,
        size: selectedSize,
        style: selectedStyle,
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
      };

      if (saveTarget === 'drafts') {
        // 保存到草稿箱（保留 AI 元数据）
        await editorApi.saveAIDraft({
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
        await editorApi.saveAITemplate({
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
    <div className="relative h-full overflow-hidden bg-[#f5f8ff]">
      <div className="pointer-events-none absolute -left-24 bottom-0 h-72 w-72 rounded-full bg-white blur-2xl" />
      <div className="pointer-events-none absolute -right-24 -top-28 h-96 w-96 rounded-full bg-blue-200/40 blur-3xl" />
      <div className="pointer-events-none absolute left-1/3 top-8 h-80 w-80 rounded-full bg-indigo-100/60 blur-3xl" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(120deg,rgba(255,255,255,0.72),rgba(237,244,255,0.45)_48%,rgba(255,255,255,0.86))]" />

      <input ref={fileInputRef} type="file" accept="image/*" multiple className="hidden" onChange={handleFileSelect} />

      <div className="relative z-10 flex h-full w-full flex-col gap-4 overflow-auto p-3 md:p-5 xl:flex-row xl:overflow-hidden">
        {/* ===== 左侧：Cloud Studio 控制台 ===== */}
        <section className="flex min-h-[760px] w-full shrink-0 flex-col overflow-hidden rounded-[28px] border border-white/80 bg-white/80 shadow-[0_24px_70px_rgba(81,112,160,0.18)] backdrop-blur-xl xl:min-h-0 xl:w-[500px]">
          <div className="flex items-center justify-between border-b border-slate-200/70 px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-300/40">
                <Sparkles className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-600">Cloud Studio</span>
                  {queueStatus && (queueStatus.processing || queueStatus.pending > 0) && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-600">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      {queueStatus.pending > 0 ? `排队中 ${queueStatus.pending}` : '生成中'}
                    </span>
                  )}
                </div>
                <h2 className="mt-1 text-base font-semibold tracking-tight text-slate-950">AI 智能创作</h2>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => router.push('/prompts')}
                className="flex items-center gap-1.5 rounded-full border border-slate-200/80 bg-white/70 px-3 py-2 text-xs font-medium text-slate-500 shadow-sm transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600"
                title="提示词宝库">
                <BookOpen className="h-3.5 w-3.5" /> 提示词宝库
              </button>
              {messages.length > 0 && (
                <button onClick={handleClearHistory} className="rounded-full px-2.5 py-2 text-xs font-medium text-slate-400 transition-colors hover:bg-red-50 hover:text-red-500" title="清空对话">
                  清空
                </button>
              )}
            </div>
          </div>

          <div className="flex-1 space-y-3 overflow-auto px-5 py-4 scrollbar-thin">
            <div className="rounded-2xl border border-slate-200/80 bg-white/85 p-3 shadow-[0_12px_36px_rgba(79,103,146,0.08)]">
              <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">AI 模型</label>
              <div className="relative rounded-2xl border border-slate-200 bg-white shadow-sm transition-all focus-within:border-indigo-300 focus-within:ring-4 focus-within:ring-indigo-100">
                <div className="pointer-events-none absolute left-2.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-xl bg-slate-950 text-white shadow-sm">
                  <Sparkles className="h-4 w-4" />
                </div>
                <select value={selectedModel} onChange={(e) => {
                  const next = e.target.value;
                  const preset = getDefaultPreset(next);
                  setSelectedModel(next);
                  setSelectedRatio(preset.ratio);
                  setSelectedResolutionTier(preset.tier);
                  setSelectedSize(preset.size);
                }}
                  aria-label="选择 AI 模型"
                  className="absolute inset-0 z-10 h-full w-full cursor-pointer appearance-none rounded-2xl opacity-0 outline-none">
                  {models.map(m => (
                    <option key={m.id} value={m.id}>
                      {m.name} — {m.desc}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none flex h-11 items-center pl-12 pr-10">
                  <div className="truncate text-sm font-bold text-slate-950">
                    {selectedModelInfo.name} — {selectedModelInfo.desc}
                  </div>
                </div>
                <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200/80 bg-white/70 p-3 shadow-[0_12px_36px_rgba(79,103,146,0.07)]">
              <div className="mb-2 flex items-center justify-between gap-3">
                <label className="block text-xs font-semibold text-slate-500">图片尺寸</label>
                <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-500">
                  {showResolutionTiers ? formatSize(activeResolutionOption.w, activeResolutionOption.h) : `固定 2K · ${formatSize(activeResolutionOption.w, activeResolutionOption.h)}`}
                </span>
              </div>
              <div className="grid grid-cols-[repeat(auto-fit,minmax(54px,1fr))] gap-1.5">
                {availableAspectRatios.map(ratio => (
                  <button key={ratio.id} onClick={() => setSelectedRatio(ratio.id)}
                    className={cn('rounded-xl border px-1.5 py-1.5 text-center shadow-sm transition-all',
                      selectedRatio === ratio.id
                        ? 'border-indigo-400 bg-indigo-50 text-indigo-600 shadow-indigo-100'
                        : 'border-slate-200 bg-white/80 text-slate-700 hover:border-indigo-200 hover:bg-indigo-50/70 hover:text-indigo-600')}>
                    <div className="text-xs font-bold">{ratio.label}</div>
                    <div className="mt-0.5 text-[9px] font-medium leading-none text-slate-400">{ratio.desc}</div>
                  </button>
                ))}
              </div>
              {showResolutionTiers && (
                <div className="mt-2 grid grid-cols-[repeat(auto-fit,minmax(62px,1fr))] gap-1.5">
                  {selectedResolutionOptions.map(option => {
                    const selected = selectedResolutionTier === option.id && !option.disabled;
                    return (
                      <button key={option.id} disabled={option.disabled}
                        onClick={() => {
                          setSelectedResolutionTier(option.id);
                          setSelectedSize(formatSize(option.w, option.h));
                        }}
                        className={cn('min-h-[50px] rounded-xl border px-1.5 py-1.5 text-center shadow-sm transition-all',
                          selected
                            ? 'border-indigo-400 bg-indigo-50 text-indigo-600 shadow-indigo-100'
                            : 'border-slate-200 bg-white/80 text-slate-700 hover:border-indigo-200 hover:bg-indigo-50/70 hover:text-indigo-600',
                          option.disabled && 'cursor-not-allowed border-slate-100 bg-slate-50/80 text-slate-300 shadow-none hover:border-slate-100 hover:bg-slate-50/80 hover:text-slate-300')}>
                        <div className="text-xs font-bold">{option.label}</div>
                        <div className={cn('mt-0.5 text-[9px] font-medium leading-tight', option.disabled ? 'text-slate-300' : 'text-slate-400')}>
                          {option.disabled ? option.note : formatSize(option.w, option.h)}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-slate-200/80 bg-white/70 p-3 shadow-[0_12px_36px_rgba(79,103,146,0.07)]">
              <label className="mb-2 block text-xs font-semibold text-slate-500">风格</label>
              <div className="flex flex-wrap gap-2">
                {styles.map(s => (
                  <button key={s} onClick={() => setSelectedStyle(s)}
                    className={cn('rounded-xl border px-3.5 py-2 text-xs font-semibold shadow-sm transition-all',
                      selectedStyle === s
                        ? 'border-indigo-400 bg-indigo-50 text-indigo-600 shadow-indigo-100'
                        : 'border-slate-200 bg-white/80 text-slate-700 hover:border-indigo-200 hover:bg-indigo-50/70 hover:text-indigo-600')}>{s}</button>
                ))}
              </div>
            </div>

            {selectedModel === 'gptimage2' && (
              <div className="rounded-2xl border border-slate-200/80 bg-white/70 p-3 shadow-[0_12px_36px_rgba(79,103,146,0.07)]">
                <label className="mb-2 block text-xs font-semibold text-slate-500">
                  图像质量
                  <span className="ml-1 text-[10px] font-normal text-slate-400">(质量越高价格越贵)</span>
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {qualities.map(q => (
                    <button key={q.id} onClick={() => setSelectedQuality(q.id)}
                      className={cn('rounded-2xl border px-3 py-2.5 text-center shadow-sm transition-all',
                        selectedQuality === q.id
                          ? 'border-indigo-400 bg-indigo-50 text-indigo-600 shadow-indigo-100'
                          : 'border-slate-200 bg-white/80 hover:border-indigo-200 hover:bg-indigo-50/70')}>
                      <div className={cn('text-sm font-bold', selectedQuality === q.id ? 'text-indigo-600' : 'text-slate-900')}>{q.label}</div>
                      <div className="mt-0.5 text-[10px] text-slate-400">{q.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="border-t border-slate-200/70 bg-white/72 p-4">
            <div className="rounded-3xl border border-slate-200 bg-white shadow-[0_14px_36px_rgba(79,103,146,0.1)]">
              {refImages.length > 0 && (
                <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
                  <span className="shrink-0 rounded-full bg-indigo-50 px-2 py-1 text-[10px] font-medium text-indigo-600">参考图 · {refImages.length}</span>
                  <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto scrollbar-thin">
                    {refImages.map((img, idx) => (
                      <div key={`${img.data}-${idx}`} className="group relative h-9 w-9 shrink-0 overflow-hidden rounded-xl border border-white bg-slate-100 shadow-sm">
                        <img src={img.data} alt={img.name} className="h-full w-full object-cover" />
                        <button onClick={() => removeRefImage(idx)}
                          className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full border border-white bg-white/95 text-slate-400 opacity-0 shadow-sm transition-all hover:bg-red-50 hover:text-red-500 group-hover:opacity-100">
                          <X className="h-2.5 w-2.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleGenerate(); } }}
                placeholder={refImages.length > 0 ? '描述你想要的修改...' : '描述你想要的图片...'}
                className="h-36 w-full resize-none rounded-t-3xl border-0 bg-transparent p-4 text-sm leading-relaxed text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-0" />
              <div className="relative flex items-center border-t border-slate-100 px-3 py-2.5">
                <span className={cn('absolute left-3 text-xs', prompt.length > PROMPT_MAX_LEN ? 'text-red-600' : 'text-slate-400')}>{prompt.length}/{PROMPT_MAX_LEN}</span>
                <div className="ml-auto flex items-center gap-1.5">
                  <div className="relative">
                    <select
                      value={imageCount}
                      onChange={(e) => setImageCount(Number(e.target.value))}
                      className="h-9 w-[70px] appearance-none rounded-xl border border-slate-200 bg-slate-50 pl-3 pr-7 text-xs font-semibold text-slate-700 transition-all hover:border-indigo-200 focus:border-indigo-300 focus:outline-none focus:ring-4 focus:ring-indigo-100"
                      title="生成数量"
                    >
                      {[1, 2, 4].map(n => (
                        <option key={n} value={n}>{n} 张</option>
                      ))}
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                  </div>
                  <button onClick={() => fileInputRef.current?.click()}
                    className={cn('flex h-9 items-center justify-center gap-1 rounded-xl border px-2 text-xs font-semibold transition-all',
                      refImages.length > 0 ? 'border-indigo-200 bg-indigo-50 text-indigo-600' : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600')}
                    title="上传参考图">
                    <ImagePlus className="h-3.5 w-3.5" />
                    上传
                  </button>
                  <button onClick={() => setGalleryPickerOpen(true)} disabled={refImages.length >= 10}
                    className={cn('flex h-9 items-center justify-center gap-1 rounded-xl border px-2 text-xs font-semibold transition-all',
                      refImages.length > 0 ? 'border-indigo-200 bg-indigo-50 text-indigo-600' : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600',
                      refImages.length >= 10 && 'cursor-not-allowed opacity-50')}
                    title="从图库选择">
                  <FolderOpen className="h-3.5 w-3.5" />
                  图库
                </button>
                <button onClick={handleGenerate} disabled={!prompt.trim() || !canStartMoreTasks || !loaded || prompt.length > PROMPT_MAX_LEN}
                  className={cn('flex h-9 min-w-[108px] items-center justify-center gap-1.5 rounded-xl px-3 text-sm font-semibold text-white shadow-lg transition-all',
                    prompt.trim() && canStartMoreTasks && loaded && prompt.length <= PROMPT_MAX_LEN
                      ? 'bg-gradient-to-r from-indigo-500 to-violet-500 shadow-indigo-300/40 hover:-translate-y-0.5 hover:shadow-indigo-300/60'
                      : 'cursor-not-allowed bg-slate-200 text-slate-400 shadow-none')}>
                  {!canStartMoreTasks ? (
                    submitting ? (
                      <><Loader2 className="h-4 w-4 animate-spin" />提交中</>
                    ) : (
                      <><Loader2 className="h-4 w-4 animate-spin" />任务已满 {effectiveActiveTaskCount}/{maxActiveTasks}</>
                    )
                  ) : (
                    <><Sparkles className="h-4 w-4" />{refImages.length > 0 ? `图生图 (${refImages.length}张)` : effectiveActiveTaskCount > 0 ? `继续生成 ${effectiveActiveTaskCount}/${maxActiveTasks}` : '生成图片'}</>
                  )}
                </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ===== 右侧：云画布结果区 ===== */}
        <section className="relative flex min-h-[620px] flex-1 flex-col overflow-hidden rounded-[32px] border border-white/80 bg-white/72 shadow-[0_24px_80px_rgba(81,112,160,0.18)] backdrop-blur-xl xl:min-h-0">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_80%_5%,rgba(129,161,255,0.22),transparent_30%),radial-gradient(circle_at_10%_100%,rgba(255,255,255,0.95),transparent_34%)]" />
          <div ref={scrollRef} onScroll={handleResultScroll} className="relative z-10 flex-1 overflow-auto p-4 md:p-6 scrollbar-thin">
            {reconcilingPending && (
              <div className="mb-3 inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-600">
                <Loader2 className="h-3 w-3 animate-spin" /> 正在同步任务状态
              </div>
            )}
            <div className="min-h-full rounded-[28px] border border-dashed border-slate-300/80 bg-white/55 p-4 shadow-inner md:p-6">
              {messages.length === 0 && !isGenerating && loaded && (
                <div className="flex min-h-[520px] flex-col items-center justify-center text-center text-slate-500">
                  <div className="relative mb-6 h-32 w-44">
                    <div className="absolute bottom-2 left-5 h-20 w-32 rounded-[50px] bg-gradient-to-br from-indigo-100 via-blue-100 to-white shadow-[0_20px_60px_rgba(99,102,241,0.22)]" />
                    <div className="absolute bottom-8 left-14 h-24 w-24 rounded-full bg-gradient-to-br from-white to-indigo-100 shadow-inner" />
                    <div className="absolute bottom-8 right-2 h-20 w-20 rounded-full bg-gradient-to-br from-blue-100 to-white" />
                    <div className="absolute bottom-11 left-16 flex h-14 w-20 items-center justify-center rounded-2xl bg-indigo-400/20 text-indigo-500 backdrop-blur-sm">
                      <ImageIcon className="h-8 w-8" />
                    </div>
                    <Sparkles className="absolute left-2 top-12 h-5 w-5 text-indigo-400" />
                    <Sparkles className="absolute right-0 top-24 h-4 w-4 text-blue-300" />
                  </div>
                  <p className="text-base font-semibold text-slate-800">输入描述开始 AI 创作</p>
                  <p className="mt-2 max-w-sm text-sm leading-6 text-slate-400">在左侧设置参数并描述你的创意，生成专属的精美图像。</p>
                </div>
              )}

              {messages.length > 0 && (
                <div className="space-y-6">
                  {messages.map((msg) => (
                    <div key={msg.id} className="group/msg relative">
                      {msg.type === 'prompt' && (
                        <div className="flex gap-3 items-start">
                          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-white text-xs font-bold text-indigo-600 shadow-sm ring-1 ring-indigo-100">我</div>
                          <div className="flex-1">
                            <div className="relative rounded-[24px] border border-white bg-white/88 px-5 py-4 shadow-[0_16px_42px_rgba(79,103,146,0.12)] group/bubble">
                              {msg.refImages && msg.refImages.length > 0 && (
                                <div className="mb-3 flex items-start gap-2 rounded-2xl bg-slate-50/80 p-2">
                                  {msg.refImages.slice(0, 4).map((img, idx) => (
                                    <div key={`${img.data}-${idx}`} className="relative h-12 w-12 shrink-0 overflow-hidden rounded-xl border border-white shadow-sm">
                                      <img src={img.data} alt="" className="h-full w-full object-cover" />
                                    </div>
                                  ))}
                                  {msg.refImages.length > 4 && (
                                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-white bg-white text-xs text-slate-400 shadow-sm">+{msg.refImages.length - 4}</div>
                                  )}
                                  <div className="flex items-center gap-1 self-center text-[10px] font-medium text-indigo-600">
                                    <ImageIcon className="h-3 w-3" />
                                    <span>{msg.refImages.length} 张参考图</span>
                                  </div>
                                </div>
                              )}
                              <p className="text-sm leading-relaxed text-slate-800">{msg.content}</p>
                              <button onClick={() => deleteMessage(msg.id)}
                                className="absolute -bottom-2.5 -right-2.5 flex h-7 w-7 items-center justify-center rounded-full border border-white bg-white text-slate-300 opacity-0 shadow-md transition-all hover:bg-red-50 hover:text-red-500 group-hover/bubble:opacity-100"
                                title="删除">
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                            {msg.params && (
                              <div className="mt-2 flex flex-wrap gap-2 pl-1">
                                <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-[10px] font-semibold text-indigo-600">{msg.params.model}</span>
                                <span className="rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-semibold text-blue-600">{msg.params.size}</span>
                                <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-semibold text-amber-600">{msg.params.style}</span>
                                {msg.params.quality && (
                                  <span className={cn('rounded-full px-2.5 py-1 text-[10px] font-semibold',
                                    msg.params.quality === 'high' ? 'bg-red-50 text-red-600' :
                                    msg.params.quality === 'medium' ? 'bg-orange-50 text-orange-600' :
                                    'bg-emerald-50 text-emerald-600'
                                  )}>{msg.params.quality === 'high' ? '高质量' : msg.params.quality === 'medium' ? '中质量' : '低质量'}</span>
                                )}
                                <span className="rounded-full bg-white px-2.5 py-1 text-[10px] font-medium text-slate-400 shadow-sm">{msg.params.count} 张</span>
                                <span className="ml-auto text-[10px] text-slate-400">{msg.timestamp}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {msg.type === 'result' && (
                        <div className="flex gap-3 items-start">
                          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-300/40">
                            {msg.taskId || msg.clientRequestId ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : msg.images.length > 0 ? (
                              <CheckCircle2 className="h-4 w-4" />
                            ) : msg.content.startsWith('生成失败') || msg.content.startsWith('已取消') ? (
                              <AlertCircle className="h-4 w-4" />
                            ) : (
                              <CheckCircle2 className="h-4 w-4" />
                            )}
                          </div>
                          <div className="flex-1">
                            <div className="relative group/bubble">
                              {msg.content && (
                                <div className={cn(
                                  'relative mb-3 rounded-[24px] border px-5 py-4 text-sm shadow-[0_16px_42px_rgba(79,103,146,0.1)]',
                                  msg.content.startsWith('生成失败') || msg.content.startsWith('已取消')
                                    ? 'border-red-100 bg-red-50 text-red-600'
                                    : (msg.taskId || msg.clientRequestId) ? 'border-blue-100 bg-blue-50 text-blue-700' : 'border-white bg-white/88 text-slate-700'
                                )}>
                                  {msg.content}
                                  <button onClick={() => deleteMessage(msg.id)}
                                    className="absolute -bottom-2.5 -right-2.5 flex h-7 w-7 items-center justify-center rounded-full border border-white bg-white text-slate-300 opacity-0 shadow-md transition-all hover:bg-red-50 hover:text-red-500 group-hover/bubble:opacity-100"
                                    title="删除">
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              )}
                              {msg.images.length > 0 && (
                                <div className="relative">
                                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3">
                                    {msg.images.map((img) => (
                                      <div key={img.id} className="group relative cursor-zoom-in overflow-hidden rounded-[26px] border border-white bg-white shadow-[0_18px_48px_rgba(79,103,146,0.16)]" style={{ aspectRatio: `${img.width} / ${img.height}` }} onClick={() => setPreviewImage(img)}>
                                        <img src={img.url} alt="" className="h-full w-full object-contain bg-white" />
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
                                      className="absolute -bottom-2.5 -right-2.5 flex h-7 w-7 items-center justify-center rounded-full border border-white bg-white text-slate-300 opacity-0 shadow-md transition-all hover:bg-red-50 hover:text-red-500 group-hover/bubble:opacity-100"
                                      title="删除">
                                      <Trash2 className="h-3.5 w-3.5" />
                                    </button>
                                  )}
                                </div>
                              )}
                              <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
                                <span>{msg.images.length} 张图片</span><span className="text-slate-300">•</span><span>{msg.timestamp}</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
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
