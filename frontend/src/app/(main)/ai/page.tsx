'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  Sparkles, Download, Share2, Maximize2, Loader2, X, ChevronDown, CheckCircle2, AlertCircle,
  ImagePlus, Trash2, Image as ImageIcon, FolderOpen, Save, BookOpen,
} from 'lucide-react';
import { aiApi, type ImageTaskResponse, type QueueStatus } from '@/services/aiApi';
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
  { id: 'midjourney', name: 'Midjourney', desc: '预留' },
  { id: 'dall-e', name: 'DALL·E 3', desc: '预留' },
];

const qualities = [
  { id: 'low', label: '低', desc: '快速/便宜' },
  { id: 'medium', label: '中', desc: '均衡' },
  { id: 'high', label: '高', desc: '精细/最贵' },
];

const seedreamSizes = [
  { label: '1:1',    w: 2048, h: 2048 },
  { label: '16:9',   w: 2560, h: 1440 },
  { label: '9:16',   w: 1440, h: 2560 },
  { label: '4:3',    w: 2240, h: 1680 },
  { label: '3:4',    w: 1680, h: 2240 },
  { label: '3:2',    w: 2400, h: 1600 },
  { label: '2:3',    w: 1600, h: 2400 },
];

const gptimage2Sizes = [
  { label: '1:1',    w: 1024, h: 1024 },
  { label: '2:3',    w: 1024, h: 1536 },
  { label: '3:2',    w: 1536, h: 1024 },
  { label: '3:4',    w: 1536, h: 2048 },
  { label: '2K 1:1', w: 2048, h: 2048 },
  { label: '4K 16:9',w: 3840, h: 2160 },
  { label: '4K 9:16',w: 2160, h: 3840 },
];

const getSizesForModel = (model: string) => model === 'gptimage2' ? gptimage2Sizes : seedreamSizes;
const getDefaultSize = (model: string) => model === 'gptimage2' ? '1024×1024' : '2048×2048';

const styles = ['写实', '插画', '3D', '动漫', '水彩', '像素', '油画', '极简', '赛博朋克', '扁平化'];

/** 轮询间隔(ms)和最大次数 */
const POLL_INTERVAL = 2000;
const MAX_POLLS = 60; // 最多轮询 2 分钟
const STORAGE_KEY_BASE = 'ai_image_messages';
const PENDING_KEY_BASE = 'ai_pending_generation';
const PROMPT_MAX_LEN = 8000;

/** 持久化相关常量 */
const MAX_HISTORY = 50; // 最多保留 50 条消息（含 prompt + result）

interface PendingGenerationState {
  promptMsgId: string;
  resultMsgId: string;
  prompt: string;
  model: string;
  size: string;
  style: string;
  timestamp: number;
  taskId?: string;
  status?: 'reconciling' | 'pending';
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

function getFallbackKeys(base: string, primary: string): string[] {
  const keys = [primary, base, `${base}:guest`];
  const uniq: string[] = [];
  for (const k of keys) {
    if (!uniq.includes(k)) uniq.push(k);
  }
  return uniq;
}

export default function AIPage() {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [reconcilingPending, setReconcilingPending] = useState(false);
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);
  const [selectedModel, setSelectedModel] = useState('seedream');
  const [selectedSize, setSelectedSize] = useState('2048×2048');
  const [selectedStyle, setSelectedStyle] = useState('写实');
  const [selectedQuality, setSelectedQuality] = useState('low');
  const [imageCount, setImageCount] = useState(1);
  const [previewImage, setPreviewImage] = useState<AIImageResult | null>(null);
  const [refImages, setRefImages] = useState<RefImageItem[]>([]); // 参考图片列表
  const [galleryPickerOpen, setGalleryPickerOpen] = useState(false);
  const hasPendingTasks = messages.some(m => m.type === 'result' && Boolean(m.taskId));
  /** 保存模版状态 */
  const [savingTemplate, setSavingTemplate] = useState(false);
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [scopedKeys, setScopedKeys] = useState<{ storageKey: string; pendingKey: string } | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  const activePollTaskIdRef = useRef<string | null>(null);
  const deletedPendingRef = useRef<{ promptMsgId?: string; resultMsgId?: string } | null>(null);
  const pendingCancelRef = useRef<PendingGenerationState | null>(null);
  const debugStorageRef = useRef(false);

  const logDebug = useCallback((msg: string, extra?: Record<string, unknown>) => {
    if (!debugStorageRef.current) return;
    // eslint-disable-next-line no-console
    console.log(`[AIStorage] ${msg}`, extra || {});
  }, []);

  const getActiveKeys = useCallback(() => {
    if (scopedKeys) return scopedKeys;
    return {
      storageKey: getUserScopedKey(STORAGE_KEY_BASE),
      pendingKey: getUserScopedKey(PENDING_KEY_BASE),
    };
  }, [scopedKeys]);

  const clearPendingState = useCallback(() => {
    const { pendingKey } = getActiveKeys();
    try {
      const pendingCandidates = getFallbackKeys(PENDING_KEY_BASE, pendingKey);
      pendingCandidates.forEach(k => localStorage.removeItem(k));
    } catch {
      // ignore
    }
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    activePollTaskIdRef.current = null;
    logDebug('clearPendingState', { pendingKey });
  }, [getActiveKeys, logDebug]);

  const persistMessages = useCallback((source: ChatMessage[]) => {
    const { storageKey } = getActiveKeys();
    try {
      const toSave = source.filter(
        m => m.type === 'prompt' || (m.type === 'result' && (m.images.length > 0 || m.content.startsWith('生成失败') || m.content.startsWith('生成超时')))
      ).slice(-MAX_HISTORY);
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
          content: '正在生成图片，请稍候...',
          images: [],
          timestamp: ts,
          taskId,
        });
      } else {
        for (let i = 0; i < next.length; i += 1) {
          if (next[i].id === pending.resultMsgId) {
            next[i] = { ...next[i], taskId, content: next[i].images.length > 0 ? '' : '正在生成图片，请稍候...' };
            break;
          }
        }
      }
      return next;
    });
  }, []);

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

  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [messages]);

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

  /** 启动轮询任务状态直到完成 */
  const startPoll = useCallback((taskId: string, model: string, resultMsgId: string, width: number, height: number) => {
    if (activePollTaskIdRef.current === taskId && pollTimerRef.current !== null) return;
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    activePollTaskIdRef.current = taskId;
    let polls = 0;
    pollTimerRef.current = window.setInterval(async () => {
      polls += 1;
      if (polls > MAX_POLLS) {
        if (pollTimerRef.current !== null) {
          window.clearInterval(pollTimerRef.current);
          pollTimerRef.current = null;
        }
        setMessages(prev => {
          const updated = prev.map(msg =>
            msg.id === resultMsgId
              ? { ...msg, content: '生成超时，请稍后重试', taskId: undefined }
              : msg
          );
          return updated;
        });
        clearPendingState();
        return;
      }

      try {
        const res = await aiApi.getTaskStatus(taskId, model);
        const data = res.data as ImageTaskResponse;

        if (data.status === 'completed' && data.image_urls && data.image_urls.length > 0) {
          if (pollTimerRef.current !== null) {
            window.clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
          const images: AIImageResult[] = data.image_urls.map((url, i) => ({
            id: `${taskId}-${i}`, url, width, height, liked: false,
          }));
          setMessages(prev => {
            const updated = prev.map(msg =>
              msg.id === resultMsgId ? { ...msg, images, taskId: undefined, content: '' } : msg
            );
            return updated;
          });
          clearPendingState();
        } else if (data.status === 'failed') {
          if (pollTimerRef.current !== null) {
            window.clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
          setMessages(prev => {
            const updated = prev.map(msg =>
              msg.id === resultMsgId
                ? { ...msg, content: `生成失败: ${data.error || '未知错误'}`, taskId: undefined }
                : msg
            );
            return updated;
          });
          clearPendingState();
        }
      } catch {
        // 轮询请求失败，继续重试
      }
    }, POLL_INTERVAL);
  }, [clearPendingState]);

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
        const parsed = JSON.parse(saved) as ChatMessage[];
        setMessages(parsed);
        if (savedFrom !== storageKey) {
          localStorage.setItem(storageKey, saved);
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
      if (pendingRaw) {
        if (pendingFrom !== pendingKey) {
          localStorage.setItem(pendingKey, pendingRaw);
          localStorage.removeItem(pendingFrom);
        }
        const pending = JSON.parse(pendingRaw) as PendingGenerationState;
        if (
          deletedPendingRef.current &&
          (deletedPendingRef.current.promptMsgId === pending.promptMsgId ||
            deletedPendingRef.current.resultMsgId === pending.resultMsgId)
        ) {
          clearPendingState();
          return;
        }
        setReconcilingPending(true);
        (async () => {
          try {
            const sizeParts = (pending.size || '2048×2048').split('×');
            const width = parseInt(sizeParts[0]) || 2048;
            const height = parseInt(sizeParts[1]) || 2048;
            if (pending.taskId) {
              const statusRes = await aiApi.getTaskStatus(pending.taskId, (pending.model || 'seedream').toLowerCase());
              const statusData = statusRes.data as ImageTaskResponse;
              if (statusData.status === 'completed' && statusData.image_urls && statusData.image_urls.length > 0) {
                if (
                  deletedPendingRef.current &&
                  (deletedPendingRef.current.promptMsgId === pending.promptMsgId ||
                    deletedPendingRef.current.resultMsgId === pending.resultMsgId)
                ) {
                  clearPendingState();
                  return;
                }
                const images: AIImageResult[] = statusData.image_urls.map((url, i) => ({
                  id: `${pending.taskId}-${i}`, url, width, height, liked: false,
                }));
                setMessages(prev => prev.map(msg =>
                  msg.id === pending.resultMsgId ? { ...msg, images, content: '', taskId: undefined } : msg
                ));
                clearPendingState();
                return;
              }
              if (statusData.status === 'failed') {
                setMessages(prev => prev.map(msg =>
                  msg.id === pending.resultMsgId ? { ...msg, content: `生成失败: ${statusData.error || '未知错误'}`, taskId: undefined } : msg
                ));
                clearPendingState();
                return;
              }
              upsertPendingMessages(pending, pending.taskId);
              localStorage.setItem(pendingKey, JSON.stringify({ ...pending, status: 'pending' }));
              startPoll(pending.taskId, (pending.model || 'seedream').toLowerCase(), pending.resultMsgId, width, height);
              return;
            }

            const res = await aiApi.getHistory(1, 20);
            const items = (res.data?.items || []) as Array<Record<string, unknown>>;
            const matched = items.find((it) => {
              const modelName = String(it.model_name || '');
              const promptText = String(it.prompt || '');
              return modelName === pending.model && (
                promptText.includes(pending.prompt || '') || (pending.prompt || '').includes(promptText)
              );
            });

            if (!matched) {
              setMessages(prev => prev.map(msg =>
                msg.id === pending.resultMsgId
                  ? { ...msg, content: '生成状态丢失，请重新发起', taskId: undefined }
                  : msg
              ));
              clearPendingState();
              return;
            }

            const matchedId = String(matched.id || '');
            const status = String(matched.status || '');
            const urls = (matched.result_urls as string[] | undefined) || [];
            const error = String(matched.error || '');
            if (!matchedId) return;

            if (status === 'completed' && urls.length > 0) {
              if (
                deletedPendingRef.current &&
                (deletedPendingRef.current.promptMsgId === pending.promptMsgId ||
                  deletedPendingRef.current.resultMsgId === pending.resultMsgId)
              ) {
                clearPendingState();
                return;
              }
              const images: AIImageResult[] = urls.map((url, i) => ({
                id: `${matchedId}-${i}`, url, width, height, liked: false,
              }));
              setMessages(prev => prev.map(msg =>
                msg.id === pending.resultMsgId ? { ...msg, images, content: '', taskId: undefined } : msg
              ));
              clearPendingState();
              return;
            }
            if (status === 'failed') {
              setMessages(prev => prev.map(msg =>
                msg.id === pending.resultMsgId ? { ...msg, content: `生成失败: ${error || '未知错误'}`, taskId: undefined } : msg
              ));
              clearPendingState();
              return;
            }

            upsertPendingMessages(pending, matchedId);
            localStorage.setItem(pendingKey, JSON.stringify({ ...pending, taskId: matchedId, status: 'pending' }));
            startPoll(matchedId, (pending.model || 'seedream').toLowerCase(), pending.resultMsgId, width, height);
          } catch {
            // ignore
          } finally {
            setReconcilingPending(false);
          }
        })();
      }
    } catch { /* ignore */ }
    setLoaded(true);
  }, [clearPendingState, logDebug, scopedKeys, startPoll, upsertPendingMessages]);

  const isGenerating = hasPendingTasks || reconcilingPending;

  // 持久化到 localStorage（包含进行中的任务）
  useEffect(() => {
    if (!loaded || !scopedKeys) return;
    persistMessages(messages);
  }, [messages, loaded, persistMessages, scopedKeys]);

  // 轮询队列状态（每 2 秒）
  useEffect(() => {
    const fetchQueue = async () => {
      try {
        const res = await aiApi.getQueueStatus();
        setQueueStatus(res.data as QueueStatus);
      } catch { /* ignore */ }
    };
    fetchQueue();
    const timer = setInterval(fetchQueue, 2000);
    return () => clearInterval(timer);
  }, []);

  /** 轮询任务状态直到完成（向后兼容） */
  const pollTask = useCallback(async (taskId: string, model: string, resultMsgId: string, width: number, height: number) => {
    startPoll(taskId, model, resultMsgId, width, height);
  }, [startPoll]);

  const handleGenerate = async () => {
    if (!prompt.trim() || hasPendingTasks || !loaded || prompt.length > PROMPT_MAX_LEN) return;
    const sizeParts = selectedSize.split('×');
    const width = parseInt(sizeParts[0]) || 1024;
    const height = parseInt(sizeParts[1]) || 1024;

    const currentRefImages = refImages;
    const promptMessage: ChatMessage = {
      id: Date.now().toString(), type: 'prompt', content: prompt, images: [],
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      params: { model: models.find(m => m.id === selectedModel)?.name || selectedModel, size: selectedSize, style: selectedStyle, count: imageCount, quality: selectedModel === 'gptimage2' ? selectedQuality : undefined },
      refImages: currentRefImages.length > 0 ? [...currentRefImages] : undefined,
    };
    setMessages(prev => [...prev, promptMessage]);
    const currentPrompt = prompt;
    setPrompt('');
    setRefImages([]);

    const resultMsgId = (Date.now() + 1).toString();
    // 先显示一个加载中的结果占位
    setMessages(prev => [...prev, {
      id: resultMsgId, type: 'result', content: '正在生成图片，请稍候...', images: [],
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    }]);

    const { pendingKey } = getActiveKeys();
    localStorage.setItem(pendingKey, JSON.stringify({
      promptMsgId: promptMessage.id,
      resultMsgId,
      prompt: currentPrompt,
      model: selectedModel,
      size: selectedSize,
      style: selectedStyle,
      timestamp: Date.now(),
      status: 'pending',
    } as PendingGenerationState));

    try {
      const fullPrompt = selectedStyle ? `${currentPrompt}, ${selectedStyle}风格` : currentPrompt;

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
        prompt: fullPrompt,
        model: selectedModel,
        width,
        height,
        ...(selectedModel === 'gptimage2' ? { quality: selectedQuality } : {}),
        ...refParams,
      });

      const data = res.data as ImageTaskResponse;

      // 同步模型（如 Seedream）直接返回 image_urls
      if (data.status === 'completed' && data.image_urls && data.image_urls.length > 0) {
        const images: AIImageResult[] = data.image_urls.map((url, i) => ({
          id: `${data.task_id}-${i}`, url, width, height, liked: false,
        }));
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId ? { ...msg, images } : msg
        ));
        clearPendingState();
      } else if (data.status === 'failed') {
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId
            ? { ...msg, content: `生成失败: ${data.error || '未知错误'}`, images: [] }
            : msg
        ));
        clearPendingState();
      } else {
        // 异步模型，更新 taskId 并开始轮询
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId ? { ...msg, taskId: data.task_id } : msg
        ));
        try {
          const raw = localStorage.getItem(pendingKey);
          if (raw) {
            const pending = JSON.parse(raw) as PendingGenerationState;
            localStorage.setItem(pendingKey, JSON.stringify({ ...pending, taskId: data.task_id, status: 'pending' }));
          }
        } catch {}
        await pollTask(data.task_id, selectedModel, resultMsgId, width, height);
      }
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : '生成失败';
      setMessages(prev => prev.map(msg =>
        msg.id === resultMsgId
          ? { ...msg, content: `生成失败: ${errorMsg}`, images: [] }
          : msg
      ));
      clearPendingState();
    }
  };

  const shareToPromptLibrary = async (img: AIImageResult, resultMsgId: string) => {
    if (sharingImageId) return;
    setSharingImageId(img.id);
    try {
      const promptMsg = getPromptMessageByResultId(resultMsgId);
      const rawPrompt = promptMsg?.content?.replace(/,\s*\S+风格$/, '')?.trim() || 'AI 生图分享';
      await promptsApi.createPrompt({
        title: rawPrompt.slice(0, 60),
        chinese: rawPrompt,
        english: '',
        category: 'AI生图分享',
        image_url: img.url,
        param_type: promptMsg?.params?.style || '通用',
      });
      toast.success('已分享到提示词宝库');
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '分享失败');
    } finally {
      setSharingImageId(null);
    }
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

  const getPromptMessageByResultId = useCallback((resultMsgId: string): ChatMessage | null => {
    const msgs = messagesRef.current;
    const resultIdx = msgs.findIndex(m => m.id === resultMsgId);
    if (resultIdx > 0 && msgs[resultIdx]?.type === 'result') {
      const prev = msgs[resultIdx - 1];
      if (prev?.type === 'prompt') return prev;
    }
    return null;
  }, []);

  /** 打开保存对话框 */
  const openSaveDialog = (img: AIImageResult, resultMsgId: string) => {
    setSaveModal({ img, resultMsgId });
    setSaveTarget('templates');
    setSaveTag('');
    // 从 localStorage 读取用户创建的文件夹
    try {
      const stored = localStorage.getItem('user_created_folders');
      setSaveFolders(stored ? JSON.parse(stored) : []);
    } catch {
      setSaveFolders([]);
    }
  };

  /** 确认保存 */
  const confirmSave = async () => {
    if (!saveModal) return;
    const { img, resultMsgId } = saveModal;
    setSavingTemplate(true);
    try {
      const promptMsg = getPromptMessageByResultId(resultMsgId);
      const rawPrompt = promptMsg?.content?.replace(/,\s*\S+风格$/, '')?.trim() ?? '';

      if (saveTarget === 'drafts') {
        // 保存到草稿箱（设计稿格式）
        await editorApi.saveDesign({
          name: rawPrompt.slice(0, 50) || 'AI 设计稿',
          design_json: null,
          thumbnail: img.url,
          width: img.width,
          height: img.height,
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
          ai_meta: rawPrompt ? {
            prompt: rawPrompt,
            ref_images: promptMsg?.refImages?.map(r => r.data) ?? [],
            model: promptMsg?.params?.model ?? '',
            size: promptMsg?.params?.size ?? '',
            style: promptMsg?.params?.style ?? '',
            count: promptMsg?.params?.count,
            quality: promptMsg?.params?.quality,
          } : undefined,
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
        const { pendingKey } = getActiveKeys();
        const raw = localStorage.getItem(pendingKey);
        if (raw) {
          const pending = JSON.parse(raw) as PendingGenerationState;
          if (toDelete.has(pending.promptMsgId) || toDelete.has(pending.resultMsgId)) {
            pendingCancelRef.current = pending;
            deletedPendingRef.current = { promptMsgId: pending.promptMsgId, resultMsgId: pending.resultMsgId };
            clearPendingState();
          }
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
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, []);

  return (
    <div className="flex h-full">
      {/* ===== 左侧：提示词 + 参数 ===== */}
      <div className="flex w-96 shrink-0 flex-col border-r bg-card">
        <div className="border-b px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold">AI 智能创作</h2>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => router.push('/prompts')}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-primary hover:bg-primary/5 transition-colors"
              title="提示词宝库">
              <BookOpen className="h-3.5 w-3.5" /> 提示词宝库
            </button>
            {queueStatus && (queueStatus.processing || queueStatus.pending > 0) && (
              <div className="flex items-center gap-1.5 text-xs text-amber-600">
                <Loader2 className="h-3 w-3 animate-spin" />
                <span>{queueStatus.pending > 0 ? `排队中 ${queueStatus.pending}` : '生成中'}</span>
              </div>
            )}
            {messages.length > 0 && (
              <button onClick={handleClearHistory} className="text-xs text-muted-foreground hover:text-red-500 transition-colors" title="清空对话">
                清空
              </button>
            )}
          </div>
        </div>
        <div className="flex-1 overflow-auto px-4 py-4 space-y-5">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-2 block">AI 模型</label>
            <div className="relative">
              <select value={selectedModel} onChange={(e) => {
                const next = e.target.value;
                setSelectedModel(next);
                setSelectedSize(getDefaultSize(next));
              }}
                className="w-full appearance-none rounded-lg border bg-background px-3 py-2.5 pr-8 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-primary/30">
                {models.map(m => (
                  <option key={m.id} value={m.id} disabled={m.id === 'midjourney' || m.id === 'dall-e'}>
                    {m.name} — {m.desc}{(m.id === 'midjourney' || m.id === 'dall-e') ? ' (即将上线)' : ''}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-2 block">图片尺寸</label>
            <div className="flex flex-wrap gap-2">
              {getSizesForModel(selectedModel).map(s => (
                <button key={s.label} onClick={() => setSelectedSize(`${s.w}×${s.h}`)}
                  className={cn('rounded-lg border px-3 py-1.5 text-xs font-medium transition-all',
                    selectedSize === `${s.w}×${s.h}` ? 'border-primary bg-primary/5 text-primary' : 'hover:bg-accent')}>
                  {s.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-2 block">风格</label>
            <div className="flex flex-wrap gap-2">
              {styles.map(s => (
                <button key={s} onClick={() => setSelectedStyle(s)}
                  className={cn('rounded-lg border px-3 py-1.5 text-xs transition-all',
                    selectedStyle === s ? 'border-primary bg-primary/5 text-primary' : 'hover:bg-accent')}>{s}</button>
              ))}
            </div>
          </div>
          {selectedModel === 'gptimage2' && (
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-2 block">
                图像质量
                <span className="ml-1 text-[10px] text-muted-foreground/60">(质量越高价格越贵)</span>
              </label>
              <div className="flex gap-2">
                {qualities.map(q => (
                  <button key={q.id} onClick={() => setSelectedQuality(q.id)}
                    className={cn('flex-1 rounded-lg border py-2 text-center transition-all',
                      selectedQuality === q.id ? 'border-primary bg-primary/5' : 'hover:bg-accent')}>
                    <div className={cn('text-xs font-medium',
                      selectedQuality === q.id ? 'text-primary' : 'text-foreground')}>{q.label}</div>
                    <div className="text-[10px] text-muted-foreground">{q.desc}</div>
                  </button>
                ))}
              </div>
            </div>
          )}
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-2 block">生成数量</label>
            <div className="flex gap-2">
              {[1, 2, 4].map(n => (
                <button key={n} onClick={() => setImageCount(n)}
                  className={cn('flex-1 rounded-lg border py-2 text-sm font-medium transition-all',
                    imageCount === n ? 'border-primary bg-primary/5 text-primary' : 'hover:bg-accent')}>{n} 张</button>
              ))}
            </div>
          </div>
        </div>
        <div className="border-t p-4">
          {/* 参考图片预览 */}
          {refImages.length > 0 && (
            <div className="mb-3">
              <div className="flex flex-wrap gap-2">
                {refImages.map((img, idx) => (
                  <div key={`${img.data}-${idx}`} className="group relative w-16 h-16 rounded-lg overflow-hidden border bg-muted/50">
                    <img src={img.data} alt={img.name} className="w-full h-full object-cover" />
                    <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent p-0.5">
                      <span className="text-[9px] text-white truncate">{img.name || '参考图'}</span>
                    </div>
                    <button onClick={() => removeRefImage(idx)}
                      className="absolute -top-1.5 -right-1.5 flex h-4.5 w-4.5 items-center justify-center rounded-full bg-background/90 border shadow-sm text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity hover:text-red-500 hover:bg-red-50">
                      <X className="h-2.5 w-2.5" />
                    </button>
                    {img.source === 'gallery' && (
                      <span className="absolute top-0.5 left-0.5 text-[8px] text-primary bg-primary/20 px-1 rounded">图库</span>
                    )}
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-1.5 mt-1.5">
                <span className="text-[10px] text-muted-foreground">图生图模式 · {refImages.length} 张参考图</span>
              </div>
            </div>
          )}
          <input ref={fileInputRef} type="file" accept="image/*" multiple className="hidden" onChange={handleFileSelect} />
          <div className="flex gap-2">
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleGenerate(); } }}
              placeholder={refImages.length > 0 ? "描述你想要的修改..." : "描述你想要的图片..."}
              className="flex-1 resize-none rounded-xl border bg-background p-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 h-28" />
          </div>
          <div className={cn('mt-1 text-right text-xs', prompt.length > PROMPT_MAX_LEN ? 'text-red-600' : 'text-muted-foreground')}>
            {prompt.length}/{PROMPT_MAX_LEN}
          </div>
          <div className="flex gap-2 mt-2">
            <button onClick={() => fileInputRef.current?.click()}
              className={cn('flex items-center gap-1.5 rounded-xl px-3 py-2.5 text-xs font-medium transition-all',
                refImages.length > 0 ? 'bg-primary/10 text-primary' : 'bg-accent text-muted-foreground hover:bg-accent/80')}>
              <ImagePlus className="h-3.5 w-3.5" />
              {refImages.length > 0 ? `已选 ${refImages.length} 张` : '上传参考图'}
            </button>
            <button onClick={() => setGalleryPickerOpen(true)} disabled={refImages.length >= 10}
              className={cn('flex items-center gap-1.5 rounded-xl px-3 py-2.5 text-xs font-medium transition-all',
                refImages.length > 0 ? 'bg-primary/10 text-primary' : 'bg-accent text-muted-foreground hover:bg-accent/80',
                refImages.length >= 10 && 'opacity-50 cursor-not-allowed')}>
              <FolderOpen className="h-3.5 w-3.5" />
              {refImages.length > 0 ? '从图库追加' : '从图库选择'}
            </button>
            <button onClick={handleGenerate} disabled={!prompt.trim() || hasPendingTasks || isGenerating || prompt.length > PROMPT_MAX_LEN}
              className={cn('flex-1 flex items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-medium transition-all',
                prompt.trim() && !hasPendingTasks && !isGenerating && prompt.length <= PROMPT_MAX_LEN ? 'bg-primary text-white hover:bg-primary-hover shadow-sm' : 'bg-muted text-muted-foreground cursor-not-allowed')}>
              {hasPendingTasks || isGenerating ? (<><Loader2 className="h-4 w-4 animate-spin" />生成中...</>) : (<><Sparkles className="h-4 w-4" />{refImages.length > 0 ? `图生图 (${refImages.length}张)` : '生成图片'}</>)}
            </button>
          </div>
        </div>
      </div>

      {/* ===== 右侧：对话式结果 ===== */}
      <div className="flex flex-1 flex-col bg-background">
        {reconcilingPending && (
          <div className="border-b bg-amber-50/60 px-6 py-2 text-xs text-amber-700">
            正在同步任务状态...
          </div>
        )}
        <div ref={scrollRef} className="flex-1 overflow-auto p-6 space-y-6">
          {messages.length === 0 && !isGenerating && loaded && (
            <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground">
              <Sparkles className="h-12 w-12 mb-4 opacity-30" />
              <p className="text-sm">输入描述开始 AI 创作</p>
            </div>
          )}
          {messages.map((msg) => (
            <div key={msg.id} className="group/msg relative">
              {msg.type === 'prompt' && (
                <div className="flex gap-3 items-start">
                  <div className="h-7 w-7 shrink-0 rounded-full bg-primary/10 flex items-center justify-center mt-0.5">
                    <span className="text-xs text-primary font-medium">我</span>
                  </div>
                  <div className="flex-1">
                    <div className="rounded-xl bg-card border px-4 py-3 group/bubble relative">
                      {msg.refImages && msg.refImages.length > 0 && (
                        <div className="mb-2 flex items-start gap-2 p-2 rounded-lg bg-muted/50">
                          {msg.refImages.slice(0, 4).map((img, idx) => (
                            <div key={`${img.data}-${idx}`} className="relative w-12 h-12 shrink-0 rounded-md overflow-hidden border">
                              <img src={img.data} alt="" className="w-full h-full object-cover" />
                            </div>
                          ))}
                          {msg.refImages.length > 4 && (
                            <div className="w-12 h-12 shrink-0 rounded-md overflow-hidden border bg-muted flex items-center justify-center">
                              <span className="text-xs text-muted-foreground">+{msg.refImages.length - 4}</span>
                            </div>
                          )}
                          <div className="flex items-center gap-1 text-[10px] text-primary">
                            <ImageIcon className="h-3 w-3" />
                            <span>{msg.refImages.length} 张参考图</span>
                          </div>
                        </div>
                      )}
                      <p className="text-sm leading-relaxed">{msg.content}</p>
                      {/* 删除按钮 - 右下角 */}
                      <button onClick={() => deleteMessage(msg.id)}
                        className="absolute -bottom-2.5 -right-2.5 flex h-6 w-6 items-center justify-center rounded-full bg-background border shadow-sm text-muted-foreground/40 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover/bubble:opacity-100"
                        title="删除">
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                    {msg.params && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-[10px] font-medium text-primary">{msg.params.model}</span>
                        <span className="rounded-full bg-purple-50 px-2.5 py-0.5 text-[10px] font-medium text-purple-600">{msg.params.size}</span>
                        <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-[10px] font-medium text-amber-600">{msg.params.style}</span>
                        {msg.params.quality && (
                          <span className={cn('rounded-full px-2.5 py-0.5 text-[10px] font-medium',
                            msg.params.quality === 'high' ? 'bg-red-50 text-red-600' :
                            msg.params.quality === 'medium' ? 'bg-orange-50 text-orange-600' :
                            'bg-green-50 text-green-600'
                          )}>{msg.params.quality === 'high' ? '高质量' : msg.params.quality === 'medium' ? '中质量' : '低质量'}</span>
                        )}
                        <span className="rounded-full bg-muted px-2.5 py-0.5 text-[10px] text-muted-foreground">{msg.params.count} 张</span>
                        <span className="text-[10px] text-muted-foreground ml-auto">{msg.timestamp}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
              {msg.type === 'result' && (
                <div className="flex gap-3 items-start">
                  <div className="h-7 w-7 shrink-0 rounded-full bg-gradient-to-br from-primary to-purple-500 flex items-center justify-center mt-0.5">
                    {msg.taskId ? (
                      <Loader2 className="h-3.5 w-3.5 text-white animate-spin" />
                    ) : msg.images.length > 0 ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-white" />
                    ) : msg.content.startsWith('生成失败') || msg.content.startsWith('生成超时') ? (
                      <AlertCircle className="h-3.5 w-3.5 text-white" />
                    ) : (
                      <CheckCircle2 className="h-3.5 w-3.5 text-white" />
                    )}
                  </div>
                  <div className="flex-1">
                    <div className="relative group/bubble">
                      {msg.content && (
                        <div className={cn(
                          'rounded-xl border px-4 py-3 text-sm mb-3',
                          msg.content.startsWith('生成失败') || msg.content.startsWith('生成超时')
                            ? 'bg-red-50 border-red-200 text-red-600'
                            : msg.taskId ? 'bg-blue-50 border-blue-200 text-blue-700' : 'bg-card border'
                        )}>
                          {msg.content}
                          {/* 删除按钮 - 右下角 */}
                          <button onClick={() => deleteMessage(msg.id)}
                            className="absolute -bottom-2.5 -right-2.5 flex h-6 w-6 items-center justify-center rounded-full bg-background border shadow-sm text-muted-foreground/40 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover/bubble:opacity-100"
                            title="删除">
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                      )}
                      {msg.images.length > 0 && (
                        <div className="relative">
                          <div className="grid grid-cols-2 gap-3">
                            {msg.images.map((img) => (
                              <div key={img.id} className="group relative rounded-xl overflow-hidden border bg-muted cursor-zoom-in" style={{ aspectRatio: `${img.width} / ${img.height}` }} onClick={() => setPreviewImage(img)}>
                                <img src={img.url} alt="" className="w-full h-full object-cover" />
                                <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
                                  <div className="absolute bottom-0 left-0 right-0 flex items-center justify-center gap-2 p-3">
                                    <button onClick={(e) => { e.stopPropagation(); shareToPromptLibrary(img, msg.id); }}
                                      disabled={sharingImageId === img.id}
                                      className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20 text-white hover:bg-white/30 transition-colors disabled:opacity-50"
                                      title="分享到提示词宝库">
                                      {sharingImageId === img.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Share2 className="h-4 w-4" />}
                                    </button>
                                    <button onClick={(e) => { e.stopPropagation(); handleDownload(img); }}
                                      className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20 text-white hover:bg-white/30 transition-colors"
                                      title="下载">
                                      <Download className="h-4 w-4" />
                                    </button>
                                    <button onClick={(e) => { e.stopPropagation(); openSaveDialog(img, msg.id); }}
                                      disabled={savingTemplate}
                                      className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20 text-white hover:bg-white/30 transition-colors disabled:opacity-50"
                                      title="保存">
                                      {savingTemplate ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                                    </button>
                                    <button onClick={(e) => { e.stopPropagation(); setPreviewImage(img); }}
                                      className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20 text-white hover:bg-white/30 transition-colors"
                                      title="预览">
                                      <Maximize2 className="h-4 w-4" />
                                    </button>
                                  </div>
                                </div>
                                <div className="absolute top-2 right-2 rounded bg-black/50 px-1.5 py-0.5 text-[10px] text-white opacity-0 group-hover:opacity-100 transition-opacity">
                                  {img.width}×{img.height}
                                </div>
                              </div>
                            ))}
                          </div>
                          {/* 删除按钮 - 右下角 */}
                          {!msg.content && (
                            <button onClick={() => deleteMessage(msg.id)}
                              className="absolute -bottom-2.5 -right-2.5 flex h-6 w-6 items-center justify-center rounded-full bg-background border shadow-sm text-muted-foreground/40 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover/bubble:opacity-100"
                              title="删除">
                              <Trash2 className="h-3 w-3" />
                            </button>
                          )}
                        </div>
                      )}
                    <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                      <span>{msg.images.length} 张图片</span><span className="text-muted-foreground/50">•</span><span>{msg.timestamp}</span>
                    </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}

        </div>
      </div>

      {/* ===== 图片预览弹窗 ===== */}
      {previewImage && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm" onClick={() => setPreviewImage(null)}>
          <button onClick={() => setPreviewImage(null)} className="absolute top-4 right-4 z-10 flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors">
            <X className="h-5 w-5" />
          </button>
          <div onClick={(e) => e.stopPropagation()} className="flex flex-col items-center max-w-xl w-full mx-4">
            <div className="w-full rounded-2xl overflow-hidden bg-muted border">
              <img src={previewImage.url} alt="" className="w-full h-auto" />
            </div>
            <div className="flex items-center gap-3 mt-4">
              <button
                onClick={() => shareToPromptLibrary(
                  previewImage,
                  messages.find(m => m.images?.some(i => i.id === previewImage.id))?.id || ''
                )}
                disabled={sharingImageId === previewImage.id}
                className="flex items-center gap-1.5 rounded-lg py-2 px-4 text-sm font-medium bg-white/10 text-white hover:bg-white/20 transition-colors disabled:opacity-50">
                {sharingImageId === previewImage.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Share2 className="h-4 w-4" />}
                分享到提示词宝库
              </button>
              <button onClick={() => openSaveDialog(previewImage, messages.find(m => m.images?.some(i => i.id === previewImage.id))?.id || '')}
                disabled={savingTemplate}
                className="flex items-center gap-1.5 rounded-lg bg-white/10 text-white py-2 px-4 text-sm font-medium hover:bg-white/20 transition-colors disabled:opacity-50">
                {savingTemplate ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}保存
              </button>
              <button onClick={() => handleDownload(previewImage)}
                className="flex items-center gap-1.5 rounded-lg bg-white/10 text-white py-2 px-4 text-sm font-medium hover:bg-white/20 transition-colors">
                <Download className="h-4 w-4" />下载
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== 保存选择弹窗 ===== */}
      {saveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setSaveModal(null)}>
          <div onClick={(e) => e.stopPropagation()} className="w-80 rounded-xl border bg-card shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b">
              <h3 className="text-sm font-semibold">保存到</h3>
              <button onClick={() => setSaveModal(null)} className="p-1 rounded hover:bg-accent transition-colors">
                <X className="h-4 w-4 text-muted-foreground" />
              </button>
            </div>

            {/* 预览图 */}
            <div className="px-4 pt-3">
              <div className="w-full aspect-square rounded-lg overflow-hidden bg-muted border">
                <img src={saveModal.img.url} alt="" className="w-full h-full object-cover" />
              </div>
            </div>

            {/* 草稿箱 / 模版库 选择 */}
            <div className="px-4 pt-3 pb-2 flex gap-2">
              <button
                onClick={() => setSaveTarget('drafts')}
                className={cn(
                  'flex-1 flex items-center justify-center gap-2 rounded-lg border py-2.5 text-xs font-medium transition-colors',
                  saveTarget === 'drafts'
                    ? 'border-primary bg-primary/5 text-primary'
                    : 'hover:bg-accent'
                )}
              >
                <ImagePlus className="h-3.5 w-3.5" />草稿箱
              </button>
              <button
                onClick={() => setSaveTarget('templates')}
                className={cn(
                  'flex-1 flex items-center justify-center gap-2 rounded-lg border py-2.5 text-xs font-medium transition-colors',
                  saveTarget === 'templates'
                    ? 'border-primary bg-primary/5 text-primary'
                    : 'hover:bg-accent'
                )}
              >
                <Save className="h-3.5 w-3.5" />模版库
              </button>
            </div>

            {/* 模版库：选择文件夹标签 */}
            {saveTarget === 'templates' && (
              <div className="px-4 pb-3">
                <label className="text-xs text-muted-foreground mb-1.5 block">选择文件夹标签</label>
                <div className="flex flex-wrap gap-1.5">
                  {/* 无标签选项 */}
                  <button
                    onClick={() => setSaveTag('')}
                    className={cn(
                      'rounded-lg border px-2.5 py-1.5 text-xs transition-colors',
                      !saveTag
                        ? 'border-primary bg-primary/5 text-primary font-medium'
                        : 'hover:bg-accent'
                    )}
                  >
                    未分类
                  </button>
                  {saveFolders.map(tag => (
                    <button key={tag}
                      onClick={() => setSaveTag(tag)}
                      className={cn(
                        'rounded-lg border px-2.5 py-1.5 text-xs transition-colors',
                        saveTag === tag
                          ? 'border-primary bg-primary/5 text-primary font-medium'
                          : 'hover:bg-accent'
                      )}
                    >
                      {tag}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 底部按钮 */}
            <div className="flex gap-2 px-4 py-3 border-t">
              <button onClick={() => setSaveModal(null)}
                className="flex-1 rounded-lg border px-4 py-2 text-xs font-medium text-muted-foreground hover:bg-accent transition-colors">
                取消
              </button>
              <button onClick={confirmSave} disabled={savingTemplate}
                className="flex-1 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-white hover:bg-primary/90 transition-colors disabled:opacity-50">
                {savingTemplate ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : '确认保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== 图库选择器弹窗 ===== */}
      <GalleryPicker
        open={galleryPickerOpen}
        onClose={() => setGalleryPickerOpen(false)}
        onSelect={handleGallerySelect}
        multiSelect
        onMultiSelect={handleGalleryMultiSelect}
      />
    </div>
  );
}
