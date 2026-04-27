'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { cn } from '@/lib/utils';
import {
  Sparkles, Download, Heart, Maximize2, Loader2, X, ChevronDown, CheckCircle2, AlertCircle,
  ImagePlus, Trash2, Image as ImageIcon, FolderOpen,
} from 'lucide-react';
import { aiApi, type ImageTaskResponse, type QueueStatus } from '@/services/aiApi';
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
  taskId?: string; // 异步任务的 task_id（用于恢复轮询）
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

const sizes = [
  { label: '1:1',    w: 2048, h: 2048 },   // 4.2MP
  { label: '16:9',   w: 2560, h: 1440 },   // 3.7MP
  { label: '9:16',   w: 1440, h: 2560 },   // 3.7MP
  { label: '4:3',    w: 2240, h: 1680 },   // 3.8MP
  { label: '3:4',    w: 1680, h: 2240 },   // 3.8MP
  { label: '3:2',    w: 2400, h: 1600 },   // 3.8MP
  { label: '2:3',    w: 1600, h: 2400 },   // 3.8MP
];

const styles = ['写实', '插画', '3D', '动漫', '水彩', '像素', '油画', '极简', '赛博朋克', '扁平化'];

/** 轮询间隔(ms)和最大次数 */
const POLL_INTERVAL = 2000;
const MAX_POLLS = 60; // 最多轮询 2 分钟
const STORAGE_KEY = 'ai_image_messages';
const GENERATION_KEY = 'ai_generation_active';

/** 持久化相关常量 */
const MAX_HISTORY = 50; // 最多保留 50 条消息（含 prompt + result）

interface ActiveGeneration {
  prompt: string;
  model: string;
  size: string;
  style: string;
  promptMsgId: string;
  resultMsgId: string;
  timestamp: number;
}

export default function AIPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);
  const [selectedModel, setSelectedModel] = useState('seedream');
  const [selectedSize, setSelectedSize] = useState('2048×2048');
  const [selectedStyle, setSelectedStyle] = useState('写实');
  const [selectedQuality, setSelectedQuality] = useState('low');
  const [imageCount, setImageCount] = useState(1);
  const [previewImage, setPreviewImage] = useState<AIImageResult | null>(null);
  const [refImages, setRefImages] = useState<RefImageItem[]>([]); // 参考图片列表
  const [galleryPickerOpen, setGalleryPickerOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  /** 启动轮询任务状态直到完成 */
  const startPoll = useCallback((taskId: string, model: string, resultMsgId: string, width: number, height: number) => {
    let polls = 0;
    const timer = setInterval(async () => {
      polls += 1;
      if (polls > MAX_POLLS) {
        clearInterval(timer);
        setMessages(prev => {
          const updated = prev.map(msg =>
            msg.id === resultMsgId
              ? { ...msg, content: '生成超时，请稍后重试', taskId: undefined }
              : msg
          );
          const hasPending = updated.some(m => m.type === 'result' && m.taskId);
          if (!hasPending) setIsGenerating(false);
          return updated;
        });
        localStorage.removeItem(GENERATION_KEY);
        return;
      }

      try {
        const res = await aiApi.getTaskStatus(taskId, model);
        const data = res.data as ImageTaskResponse;

        if (data.status === 'completed' && data.image_urls && data.image_urls.length > 0) {
          clearInterval(timer);
          const images: AIImageResult[] = data.image_urls.map((url, i) => ({
            id: `${taskId}-${i}`, url, width, height, liked: false,
          }));
          setMessages(prev => {
            const updated = prev.map(msg =>
              msg.id === resultMsgId ? { ...msg, images, taskId: undefined } : msg
            );
            const hasPending = updated.some(m => m.type === 'result' && m.taskId);
            if (!hasPending) setIsGenerating(false);
            return updated;
          });
          localStorage.removeItem(GENERATION_KEY);
        } else if (data.status === 'failed') {
          clearInterval(timer);
          setMessages(prev => {
            const updated = prev.map(msg =>
              msg.id === resultMsgId
                ? { ...msg, content: `生成失败: ${data.error || '未知错误'}`, taskId: undefined }
                : msg
            );
            const hasPending = updated.some(m => m.type === 'result' && m.taskId);
            if (!hasPending) setIsGenerating(false);
            return updated;
          });
          localStorage.removeItem(GENERATION_KEY);
        }
      } catch {
        // 轮询请求失败，继续重试
      }
    }, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, []);

  // 客户端首次加载时从 localStorage 恢复历史记录 + 进行中的任务
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved) as ChatMessage[];
        setMessages(parsed);

        // 查找进行中的任务并恢复轮询
        const pendingTasks = parsed.filter(
          m => m.type === 'result' && (!m.content || m.content === '') && (!m.images || m.images.length === 0) && m.taskId
        );
        if (pendingTasks.length > 0) {
          setIsGenerating(true);
          for (const pendingMsg of pendingTasks) {
            const taskModel = pendingMsg.params?.model?.toLowerCase() || 'seedream';
            const sizeParts = pendingMsg.params?.size?.split('×') ?? ['2048', '2048'];
            const width = parseInt(sizeParts[0]) || 2048;
            const height = parseInt(sizeParts[1]) || 2048;
            startPoll(pendingMsg.taskId!, taskModel, pendingMsg.id, width, height);
          }
        }
      }

      // 也检查独立的 generation state（处理切页面丢失状态的情况）
      const genState = localStorage.getItem(GENERATION_KEY);
      if (genState) {
        const gen = JSON.parse(genState) as ActiveGeneration;

        // 异步恢复：查询后端历史并兜底清理
        (async () => {
          try {
            const res = await aiApi.getHistory(1, 1);
            const items = res.data?.items ?? [];
            if (items.length > 0) {
              const latest = items[0];
              if (latest.result_urls && Array.isArray(latest.result_urls) && latest.result_urls.length > 0) {
                // 任务已完成，恢复图片
                const images: AIImageResult[] = latest.result_urls.map((url: string, i: number) => ({
                  id: `${latest.id}-${i}`, url, width: 2048, height: 2048, liked: false,
                }));
                setMessages(prev => prev.map(msg =>
                  msg.id === gen.resultMsgId ? { ...msg, images } : msg
                ));
              } else if (latest.error || latest.status === 'failed') {
                // 任务失败，恢复错误信息
                setMessages(prev => prev.map(msg =>
                  msg.id === gen.resultMsgId
                    ? { ...msg, content: `生成失败: ${latest.error || '未知错误'}` }
                    : msg
                ));
              }
              // 有其他状态（queued/processing）则保留等待状态
            }
          } catch {
            // 查询失败，不清理（保留等待状态）
          } finally {
            // 无论成功/失败/无结果，都结束生成状态
            setIsGenerating(false);
            localStorage.removeItem(GENERATION_KEY);
          }
        })();
      }
    } catch { /* ignore */ }
    setLoaded(true);
  }, [startPoll]);

  // 持久化到 localStorage（包含进行中的任务）
  useEffect(() => {
    if (!loaded) return;
    try {
      const allMessages = messages.filter(
        m => m.type === 'prompt' || (m.type === 'result' && (m.images.length > 0 || m.content.startsWith('生成失败') || m.content.startsWith('生成超时')))
      ).slice(-MAX_HISTORY);
      // 追加进行中的任务
      const inProgress = messages.filter(
        m => m.type === 'result' && (!m.content || m.content === '') && (!m.images || m.images.length === 0) && m.taskId
      );
      const toSave = [...allMessages, ...inProgress];
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
    } catch { /* ignore storage errors */ }
  }, [messages, loaded]);

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
    if (!prompt.trim() || isGenerating || !loaded) return;
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
    setIsGenerating(true);
    const currentPrompt = prompt;
    setPrompt('');
    setRefImages([]);

    const resultMsgId = (Date.now() + 1).toString();
    // 先显示一个加载中的结果占位
    setMessages(prev => [...prev, {
      id: resultMsgId, type: 'result', content: '', images: [],
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    }]);

    // 保存生成状态到 localStorage，防止切页面丢失
    const modelName = models.find(m => m.id === selectedModel)?.name || selectedModel;
    const activeGen: ActiveGeneration = {
      prompt: currentPrompt,
      model: modelName,
      size: selectedSize,
      style: selectedStyle,
      promptMsgId: Date.now().toString(),
      resultMsgId,
      timestamp: Date.now(),
    };
    localStorage.setItem(GENERATION_KEY, JSON.stringify(activeGen));

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
        localStorage.removeItem(GENERATION_KEY);
      } else if (data.status === 'failed') {
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId
            ? { ...msg, content: `生成失败: ${data.error || '未知错误'}`, images: [] }
            : msg
        ));
        localStorage.removeItem(GENERATION_KEY);
      } else {
        // 异步模型，先更新 taskId 以便恢复轮询
        setMessages(prev => prev.map(msg =>
          msg.id === resultMsgId ? { ...msg, taskId: data.task_id } : msg
        ));
        await pollTask(data.task_id, selectedModel, resultMsgId, width, height);
      }
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : '生成失败';
      setMessages(prev => prev.map(msg =>
        msg.id === resultMsgId
          ? { ...msg, content: `生成失败: ${errorMsg}`, images: [] }
          : msg
      ));
      localStorage.removeItem(GENERATION_KEY);
    } finally {
      setIsGenerating(false);
    }
  };

  const toggleLike = (imageId: string) => {
    setMessages(prev => prev.map(msg => ({
      ...msg, images: msg.images.map(img => img.id === imageId ? { ...img, liked: !img.liked } : img),
    })));
    if (previewImage && previewImage.id === imageId) {
      setPreviewImage(prev => prev ? { ...prev, liked: !prev.liked } : null);
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
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(GENERATION_KEY);
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

  const deleteMessage = (msgId: string) => {
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
      const filtered = prev.filter(m => !toDelete.has(m.id));
      // 同步 localStorage
      try {
        const completed = filtered.filter(
          m => m.type === 'prompt' || (m.type === 'result' && m.images?.length > 0) || (m.type === 'result' && m.content?.startsWith('生成失败'))
        ).slice(-MAX_HISTORY);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(completed));
      } catch { /* ignore */ }
      return filtered;
    });
  };

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
              <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}
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
              {sizes.map(s => (
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
              className="flex-1 resize-none rounded-xl border bg-background p-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 h-20" />
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
            <button onClick={handleGenerate} disabled={!prompt.trim() || isGenerating}
              className={cn('flex-1 flex items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-medium transition-all',
                prompt.trim() && !isGenerating ? 'bg-primary text-white hover:bg-primary-hover shadow-sm' : 'bg-muted text-muted-foreground cursor-not-allowed')}>
              {isGenerating ? (<><Loader2 className="h-4 w-4 animate-spin" />生成中...</>) : (<><Sparkles className="h-4 w-4" />{refImages.length > 0 ? `图生图 (${refImages.length}张)` : '生成图片'}</>)}
            </button>
          </div>
        </div>
      </div>

      {/* ===== 右侧：对话式结果 ===== */}
      <div className="flex flex-1 flex-col bg-background">
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
                    {msg.images.length > 0 ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-white" />
                    ) : msg.content ? (
                      <AlertCircle className="h-3.5 w-3.5 text-white" />
                    ) : (
                      <Loader2 className="h-3.5 w-3.5 text-white animate-spin" />
                    )}
                  </div>
                  <div className="flex-1">
                    <div className="relative group/bubble">
                      {msg.content && (
                        <div className={cn(
                          'rounded-xl border px-4 py-3 text-sm mb-3',
                          msg.content.startsWith('生成失败') || msg.content.startsWith('生成超时')
                            ? 'bg-red-50 border-red-200 text-red-600'
                            : 'bg-card border'
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
                              <div key={img.id} className="group relative aspect-square rounded-xl overflow-hidden border bg-muted cursor-zoom-in" onClick={() => setPreviewImage(img)}>
                                <img src={img.url} alt="" className="w-full h-full object-cover" />
                                <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
                                  <div className="absolute bottom-0 left-0 right-0 flex items-center justify-center gap-2 p-3">
                                    <button onClick={(e) => { e.stopPropagation(); toggleLike(img.id); }}
                                      className={cn('flex h-8 w-8 items-center justify-center rounded-full transition-colors',
                                        img.liked ? 'bg-red-500 text-white' : 'bg-white/20 text-white hover:bg-white/30')}>
                                      <Heart className={cn('h-4 w-4', img.liked && 'fill-current')} />
                                    </button>
                                    <button onClick={(e) => { e.stopPropagation(); handleDownload(img); }}
                                      className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20 text-white hover:bg-white/30 transition-colors"
                                      title="下载">
                                      <Download className="h-4 w-4" />
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
          {isGenerating && (
            <div className="flex gap-3 items-start">
              <div className="h-7 w-7 shrink-0 rounded-full bg-gradient-to-br from-primary to-purple-500 flex items-center justify-center mt-0.5">
                <Loader2 className="h-3.5 w-3.5 text-white animate-spin" />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /><span>正在生成图片，请稍候...</span>
                </div>
                <div className="mt-2 w-48 h-1.5 bg-muted rounded-full overflow-hidden">
                  <div className="h-full bg-primary rounded-full animate-pulse" style={{ width: '60%' }} />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ===== 图片预览弹窗 ===== */}
      {previewImage && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm" onClick={() => setPreviewImage(null)}>
          <button onClick={() => setPreviewImage(null)} className="absolute top-4 right-4 z-10 flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors">
            <X className="h-5 w-5" />
          </button>
          <div onClick={(e) => e.stopPropagation()} className="flex flex-col items-center max-w-lg w-full mx-4">
            <div className="w-full aspect-square rounded-2xl overflow-hidden bg-muted">
              <img src={previewImage.url} alt="" className="w-full h-full object-cover" />
            </div>
            <div className="flex items-center gap-3 mt-4">
              <button onClick={() => toggleLike(previewImage.id)}
                className={cn('flex items-center gap-1.5 rounded-lg py-2 px-4 text-sm font-medium transition-colors',
                  previewImage.liked ? 'bg-red-500 text-white' : 'bg-white/10 text-white hover:bg-white/20')}>
                <Heart className={cn('h-4 w-4', previewImage.liked && 'fill-current')} />
                {previewImage.liked ? '已收藏' : '收藏'}
              </button>
              <button onClick={() => handleDownload(previewImage)}
                className="flex items-center gap-1.5 rounded-lg bg-white/10 text-white py-2 px-4 text-sm font-medium hover:bg-white/20 transition-colors">
                <Download className="h-4 w-4" />下载
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
