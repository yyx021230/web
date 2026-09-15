'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import * as Dialog from '@radix-ui/react-dialog';
import styles from './prompts.module.css';
import { cn } from '@/lib/utils';
import {
  Copy, Check, Loader2, Upload,
  FileText, X, Plus, ImageIcon, Trash2, Pencil, Flag, MoreHorizontal, SlidersHorizontal,
  Heart, Shuffle, Download,
} from 'lucide-react';
import { promptsApi, type PromptItem, type PromptImportResult } from '@/services/promptsApi';
import { toast } from '@/lib/toast';
import { useOptionalAuthSession } from '@/components/auth/AuthSession';

type PromptForm = {
  title: string;
  chinese: string;
  english: string;
  category: string;
  image_url: string;
  param_type: string;
};

const emptyForm: PromptForm = {
  title: '',
  chinese: '',
  english: '',
  category: '',
  image_url: '',
  param_type: '通用',
};

type SourceFilter = 'all' | 'external' | 'internal';

const sourceTabs: Array<{ value: SourceFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'external', label: '外部' },
  { value: 'internal', label: '内部' },
];

const promptImageSizeCache = new Map<string, { width: number; height: number }>();

const RELATED_POOL_SIZE = 600;
const RELATED_RESULT_SIZE = 6;
const RELATED_STOP_WORDS = new Set([
  'about', 'above', 'against', 'along', 'also', 'and', 'are', 'around', 'background', 'based',
  'cinematic', 'close', 'create', 'detailed', 'details', 'dramatic', 'each', 'featuring', 'from',
  'generate', 'high', 'image', 'lighting', 'photo', 'photograph', 'photography', 'prompt', 'realistic',
  'render', 'scene', 'shot', 'style', 'the', 'this', 'through', 'ultra', 'using', 'very', 'visual',
  'with', 'without', 'quality', 'resolution', 'composition', 'perspective', 'aspect', 'ratio',
  '画面', '图片', '图像', '照片', '摄影', '风格', '高清', '超清', '细节', '构图', '背景', '光影',
  '生成', '设计', '展示', '呈现', '整体', '质感', '效果', '一个', '一种', '使用', '具有', '非常',
]);
const RELATED_CJK_STOP_FRAGMENTS = Array.from(RELATED_STOP_WORDS).filter(word => /[\u3400-\u9fff]/.test(word));

function normalizeRelatedTerm(value: string) {
  const normalized = value.toLocaleLowerCase().replace(/[^a-z0-9\u3400-\u9fff]+/g, '');
  if (normalized.length > 4 && normalized.endsWith('s') && !normalized.endsWith('ss')) {
    return normalized.slice(0, -1);
  }
  return normalized;
}

function isUsefulRelatedTerm(value: string) {
  if (!value || RELATED_STOP_WORDS.has(value)) return false;
  if (/^\d+$/.test(value) || /^(?:[248]k|hd|hdr|rgb)$/.test(value)) return false;
  if (!/^[\u3400-\u9fff]+$/.test(value) || value.length > 4) return true;
  return !RELATED_CJK_STOP_FRAGMENTS.some(word => word.includes(value));
}

function collectRelatedTerms(prompt: PromptItem) {
  const terms = new Map<string, number>();
  const add = (value: string, weight: number) => {
    const term = normalizeRelatedTerm(value);
    if (!isUsefulRelatedTerm(term)) return;
    terms.set(term, Math.max(terms.get(term) || 0, weight));
  };
  const collect = (value: string, weight: number) => {
    const normalized = value.toLocaleLowerCase().slice(0, 3000);
    const latinWords = (normalized.match(/[a-z0-9][a-z0-9.+-]{1,}/g) || [])
      .map(normalizeRelatedTerm)
      .filter(isUsefulRelatedTerm);
    latinWords.forEach(word => add(word, weight));
    for (let index = 0; index < latinWords.length - 1; index += 1) {
      add(`${latinWords[index]}:${latinWords[index + 1]}`, weight * 1.7);
    }

    for (const run of normalized.match(/[\u3400-\u9fff]{2,}/g) || []) {
      const boundedRun = run.slice(0, 120);
      for (const size of [2, 3, 4]) {
        for (let index = 0; index <= boundedRun.length - size; index += 1) {
          add(boundedRun.slice(index, index + size), weight * (size === 2 ? 1 : 1.35));
        }
      }
    }
  };

  collect(`${prompt.title || ''} ${prompt.name || ''}`, 2.4);
  collect(`${prompt.chinese || ''} ${prompt.english || ''}`, 1);
  return terms;
}

function promptCopyIdentity(prompt: PromptItem) {
  return (prompt.chinese || prompt.english || '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLocaleLowerCase();
}

function rankRelatedPrompts(selected: PromptItem, candidates: PromptItem[], limit = RELATED_RESULT_SIZE) {
  const seenIds = new Set<number>([selected.id]);
  const seenVisuals = new Set<string>([promptIdentity(selected)]);
  const selectedCopy = promptCopyIdentity(selected);
  const seenCopies = new Set<string>(selectedCopy ? [selectedCopy] : []);
  const uniqueCandidates = candidates.filter(candidate => {
    const visual = promptIdentity(candidate);
    const copy = promptCopyIdentity(candidate);
    if (seenIds.has(candidate.id) || seenVisuals.has(visual) || (copy && seenCopies.has(copy))) return false;
    seenIds.add(candidate.id);
    seenVisuals.add(visual);
    if (copy) seenCopies.add(copy);
    return true;
  });
  if (uniqueCandidates.length === 0) return [];

  const selectedTerms = collectRelatedTerms(selected);
  const candidateTerms = uniqueCandidates.map(collectRelatedTerms);
  const documentFrequency = new Map<string, number>();
  for (const terms of candidateTerms) {
    for (const term of terms.keys()) {
      documentFrequency.set(term, (documentFrequency.get(term) || 0) + 1);
    }
  }

  const candidateCount = candidateTerms.length;
  const weightedSelectedTerms = Array.from(selectedTerms.entries()).map(([term, weight]) => {
    const idf = Math.log((candidateCount + 1) / ((documentFrequency.get(term) || 0) + 1)) + 1;
    return { term, weight: weight * idf };
  });
  const selectedWeight = weightedSelectedTerms.reduce((sum, item) => sum + item.weight, 0) || 1;

  return uniqueCandidates
    .map((candidate, index) => {
      const terms = candidateTerms[index];
      const sharedWeight = weightedSelectedTerms.reduce((sum, item) => {
        const candidateWeight = terms.get(item.term);
        return candidateWeight ? sum + item.weight * Math.min(candidateWeight, 1.7) : sum;
      }, 0);
      const categoryBoost = selected.category && candidate.category === selected.category ? 0.08 : 0;
      const modelBoost = selected.param_type && candidate.param_type === selected.param_type ? 0.01 : 0;
      return { candidate, score: sharedWeight / selectedWeight + categoryBoost + modelBoost, index };
    })
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .slice(0, limit)
    .map(item => item.candidate);
}

function normalizePromptImageUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return '';

  try {
    const url = new URL(trimmed, 'https://creative-studio.local');
    const path = url.pathname.replace(/\/{2,}/g, '/').replace(/\/$/, '') || '/';
    return url.origin === 'https://creative-studio.local'
      ? path
      : `${url.protocol}//${url.host.toLowerCase()}${path}`;
  } catch {
    return trimmed.split(/[?#]/, 1)[0].replace(/\/$/, '');
  }
}

function promptIdentity(prompt: PromptItem) {
  const imageUrl = normalizePromptImageUrl(prompt.image_url || '');
  if (imageUrl) return `image:${imageUrl}`;

  const externalId = prompt.external_id?.trim();
  if (externalId) return `external:${prompt.source_name || ''}:${externalId}`;

  const copy = (prompt.chinese || prompt.english || prompt.title || prompt.name || '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLocaleLowerCase();
  return copy ? `copy:${copy}` : `id:${prompt.id}`;
}

function mergeUniquePrompts(current: PromptItem[], incoming: PromptItem[]) {
  const seenIds = new Set(current.map(item => item.id));
  const seenContent = new Set(current.map(promptIdentity));
  const merged = [...current];

  for (const item of incoming) {
    const identity = promptIdentity(item);
    if (seenIds.has(item.id) || seenContent.has(identity)) continue;
    seenIds.add(item.id);
    seenContent.add(identity);
    merged.push(item);
  }

  return merged;
}

function fallbackImageSize(id: number) {
  const ratios = [
    { width: 3, height: 4 },
    { width: 1, height: 1 },
    { width: 4, height: 5 },
    { width: 3, height: 2 },
  ];
  return ratios[Math.abs(id) % ratios.length];
}

async function preparePromptImages(items: PromptItem[]): Promise<PromptItem[]> {
  return Promise.all(items.map(item => new Promise<PromptItem>(resolve => {
    if (!item.image_url || typeof window === 'undefined') {
      const size = fallbackImageSize(item.id);
      resolve({ ...item, image_width: size.width, image_height: size.height });
      return;
    }
    const cached = promptImageSizeCache.get(item.image_url);
    if (cached) {
      resolve({ ...item, image_width: cached.width, image_height: cached.height });
      return;
    }
    const image = new window.Image();
    let settled = false;
    const finish = (size: { width: number; height: number }) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      promptImageSizeCache.set(item.image_url, size);
      resolve({ ...item, image_width: size.width, image_height: size.height });
    };
    const timeout = window.setTimeout(() => finish(fallbackImageSize(item.id)), 5000);
    image.onload = () => finish({
      width: Math.max(1, image.naturalWidth),
      height: Math.max(1, image.naturalHeight),
    });
    image.onerror = () => finish(fallbackImageSize(item.id));
    image.src = item.image_url;
  })));
}

export default function PromptsPage() {
  const authSession = useOptionalAuthSession();
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [activeSource, setActiveSource] = useState<SourceFilter>('all');
  const [loading, setLoading] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const requestIdRef = useRef(0);
  const loadingMoreRef = useRef(false);
  const discoverySeedRef = useRef(0);
  const galleryRef = useRef<HTMLDivElement>(null);
  const loadMoreSentinelRef = useRef<HTMLDivElement>(null);
  const promptsRef = useRef<PromptItem[]>([]);
  const [previewPrompt, setPreviewPrompt] = useState<PromptItem | null>(null);
  const [relatedPrompts, setRelatedPrompts] = useState<PromptItem[]>([]);
  const relatedCacheRef = useRef<Map<string, PromptItem[]>>(new Map());
  const relatedRequestRef = useRef(0);
  const [favoriteIds, setFavoriteIds] = useState<Set<number>>(new Set());
  const [promptExpanded, setPromptExpanded] = useState(false);
  const PAGE_SIZE = 30;

  const [showImport, setShowImport] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showMyReports, setShowMyReports] = useState(false);
  const [editingPrompt, setEditingPrompt] = useState<PromptItem | null>(null);
  const [myReports, setMyReports] = useState<Array<{ id: number; prompt_name: string; reason: string; status: string; created_at: string; resolution_note: string | null }>>([]);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [reportReasons, setReportReasons] = useState<string[]>(['其他']);

  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<PromptImportResult | null>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  const [addForm, setAddForm] = useState<PromptForm>(emptyForm);
  const [editForm, setEditForm] = useState<PromptForm>(emptyForm);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(false);

  const requireLogin = (next = '/prompts', reason = '登录后继续使用这项功能') => {
    // Tests and isolated embeds may render the gallery without the app provider.
    if (!authSession || authSession.user) return true;
    authSession.requestLogin({ next, reason });
    return false;
  };

  const protectLink = (event: React.MouseEvent<HTMLAnchorElement>, next: string, reason: string) => {
    if (requireLogin(next, reason)) return;
    event.preventDefault();
  };

  const fetchData = useCallback(async (p = 1, append = false) => {
    if (append && loadingMoreRef.current) return;
    const requestId = append ? requestIdRef.current : ++requestIdRef.current;
    if (append) {
      loadingMoreRef.current = true;
      setLoadingMore(true);
      setLoadMoreError(null);
    } else {
      setLoading(true);
      setLoadError(null);
      setLoadMoreError(null);
    }
    try {
      if (!discoverySeedRef.current) {
        discoverySeedRef.current = Math.floor(Math.random() * 2_147_483_646) + 1;
      }
      const sourceKind = activeSource === 'all' ? undefined : activeSource;
      const res = await promptsApi.getPrompts('', undefined, p, PAGE_SIZE, false, discoverySeedRef.current, sourceKind);
      if (requestId !== requestIdRef.current) return;
      const preparedItems = await preparePromptImages(res.data.items);
      if (requestId !== requestIdRef.current) return;
      setPrompts(current => mergeUniquePrompts(append ? current : [], preparedItems));
      setTotal(res.data.total);
      setPage(res.data.page);
      if (!append) galleryRef.current?.scrollTo?.({ top: 0 });
    } catch (e) {
      if (requestId !== requestIdRef.current) return;
      const message = e instanceof Error ? e.message : '提示词加载失败，请重试';
      if (append) setLoadMoreError(message);
      else setLoadError(message);
    } finally {
      if (append) {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      } else if (requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [activeSource]);

  useEffect(() => {
    fetchData(1);
    return () => { requestIdRef.current += 1; };
  }, [fetchData]);

  useEffect(() => {
    promptsRef.current = prompts;
  }, [prompts]);

  useEffect(() => {
    const requestId = ++relatedRequestRef.current;
    if (!previewPrompt) {
      setRelatedPrompts([]);
      return;
    }

    const visiblePrompts = promptsRef.current;
    const visibleCandidates = previewPrompt.category
      ? visiblePrompts.filter(item => item.category === previewPrompt.category)
      : visiblePrompts;
    setRelatedPrompts(rankRelatedPrompts(previewPrompt, visibleCandidates));
    if (!previewPrompt.category) return;

    const sourceKind = activeSource === 'all' ? undefined : activeSource;
    const cacheKey = `${previewPrompt.category}:${sourceKind || 'all'}`;
    const cached = relatedCacheRef.current.get(cacheKey);
    if (cached) {
      setRelatedPrompts(rankRelatedPrompts(previewPrompt, cached));
      return;
    }

    promptsApi.getPrompts('', previewPrompt.category, 1, RELATED_POOL_SIZE, false, undefined, sourceKind)
      .then(res => {
        if (requestId !== relatedRequestRef.current) return;
        relatedCacheRef.current.set(cacheKey, res.data.items);
        setRelatedPrompts(rankRelatedPrompts(previewPrompt, res.data.items));
      })
      .catch(() => {
        // Keep the locally ranked fallback when the wider candidate pool is unavailable.
      });
  }, [activeSource, previewPrompt]);

  const hasMore = page * PAGE_SIZE < total;

  useEffect(() => {
    const root = galleryRef.current;
    const sentinel = loadMoreSentinelRef.current;
    if (!root || !sentinel || !hasMore || loading || loadingMore || loadMoreError || typeof IntersectionObserver === 'undefined') return;

    const observer = new IntersectionObserver(entries => {
      if (entries[0]?.isIntersecting) fetchData(page + 1, true);
    }, { root, rootMargin: '600px 0px' });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [fetchData, hasMore, loadMoreError, loading, loadingMore, page]);

  const handleCopy = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const getCreativeHref = (item: PromptItem, includeReference = false) => {
    const text = (item.chinese || item.english || '').trim();
    const params = new URLSearchParams({ prompt: text, from: 'prompt-library' });
    if (includeReference && item.image_url) params.set('reference', item.image_url);
    return `/ai?${params.toString()}`;
  };

  const toggleFavorite = (id: number) => {
    if (!requireLogin('/prompts', '登录后收藏喜欢的创意')) return;
    setFavoriteIds(current => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除此提示词吗？')) return;
    try {
      await promptsApi.deletePrompt(id);
      setPrompts(prev => prev.filter(p => p.id !== id));
      setTotal(t => t - 1);
      toast.success('已删除');
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    }
  };

  const handleReport = async (prompt: PromptItem) => {
    if (!requireLogin('/prompts', '登录后提交内容举报')) return;
    let reasons = reportReasons;
    if (reasons.length === 1 && reasons[0] === '其他') {
      try {
        const res = await promptsApi.getReportReasons();
        reasons = res.data.reasons;
        setReportReasons(reasons);
      } catch {
        // keep fallback reason list
      }
    }
    const reason = window.prompt(`举报原因（可选：${reasons.join(' / ')}）`, reasons[0] || '其他');
    if (!reason) return;
    const details = window.prompt('补充说明（可选）') || '';
    try {
      await promptsApi.reportPrompt(prompt.id, { reason, details: details || undefined });
      toast.success('举报已提交');
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : '举报失败');
    }
  };

  const fetchMyReports = async () => {
    setReportsLoading(true);
    try {
      const res = await promptsApi.getMyReports(1, 50);
      setMyReports(
        res.data.items.map(i => ({
          id: i.id,
          prompt_name: i.prompt_name,
          reason: i.reason,
          status: i.status,
          created_at: i.created_at,
          resolution_note: i.resolution_note,
        }))
      );
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '加载我的举报失败');
    } finally {
      setReportsLoading(false);
    }
  };

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    try {
      const res = await promptsApi.importPrompts(file);
      const result = res.data;
      setImportResult(result);
      if (result.failed_count > 0) {
        toast.success(`导入完成：成功 ${result.imported_count} 条，失败 ${result.failed_count} 条`);
      } else {
        toast.success(`导入成功：${result.imported_count} 条`);
        setShowImport(false);
      }
      fetchData(1);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : '导入失败');
    } finally {
      setImporting(false);
      if (importInputRef.current) importInputRef.current.value = '';
    }
  };

  const handleAdd = async () => {
    if (!addForm.title.trim() || !addForm.chinese.trim()) {
      toast.error('标题和中文提示词不能为空');
      return;
    }
    setAdding(true);
    try {
      if (!addForm.image_url.trim()) {
        toast.success('提示：建议上传图片，便于宝库展示效果');
      }
      await promptsApi.createPrompt(addForm);
      toast.success('添加成功');
      setShowAdd(false);
      setAddForm(emptyForm);
      fetchData(1);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '添加失败');
    } finally {
      setAdding(false);
    }
  };

  const openEdit = (prompt: PromptItem) => {
    setEditingPrompt(prompt);
    setEditForm({
      title: prompt.title || prompt.name || '',
      chinese: prompt.chinese || '',
      english: prompt.english || '',
      category: prompt.category || '',
      image_url: prompt.image_url || '',
      param_type: prompt.param_type || '通用',
    });
    setShowEdit(true);
  };

  const handleEdit = async () => {
    if (!editingPrompt) return;
    if (!editForm.title.trim() || !editForm.chinese.trim()) {
      toast.error('标题和中文提示词不能为空');
      return;
    }
    setEditing(true);
    try {
      if (!editForm.image_url.trim()) {
        toast.success('提示：建议上传图片，便于宝库展示效果');
      }
      await promptsApi.updatePrompt(editingPrompt.id, editForm);
      toast.success('更新成功');
      setShowEdit(false);
      setEditingPrompt(null);
      fetchData(1);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '更新失败');
    } finally {
      setEditing(false);
    }
  };

  return (
    <div className={styles.page}>
      <h1 className="sr-only">提示词宝库</h1>
      <header className={styles.toolbar}>
        <div className={styles.categoryRail}>
          <nav className={styles.categories} aria-label="提示词来源">
            {sourceTabs.map(tab => (
              <button
                key={tab.value}
                className={styles.category}
                aria-pressed={tab.value === activeSource}
                onClick={() => {
                  if (tab.value === activeSource) return;
                  discoverySeedRef.current = Math.floor(Math.random() * 2_147_483_646) + 1;
                  setActiveSource(tab.value);
                }}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
        <div className={styles.tools}>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger className={styles.manageButton} aria-label="管理提示词宝库" title="管理提示词宝库">
              <SlidersHorizontal size={17} />
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content className={styles.menu} align="end" sideOffset={8}>
                <DropdownMenu.Label className={styles.menuLabel}>提示词宝库</DropdownMenu.Label>
                <DropdownMenu.Item className={styles.menuItem} onSelect={() => { if (requireLogin('/prompts', '登录后添加你的提示词')) setShowAdd(true); }}><Plus size={15} />添加提示词</DropdownMenu.Item>
                <DropdownMenu.Item className={styles.menuItem} onSelect={() => { if (requireLogin('/prompts', '登录后批量导入提示词')) setShowImport(true); }}><Upload size={15} />批量导入</DropdownMenu.Item>
                <DropdownMenu.Separator className={styles.menuDivider} />
                <DropdownMenu.Item className={styles.menuItem} onSelect={() => { if (requireLogin('/prompts', '登录后查看你的举报记录')) { setShowMyReports(true); fetchMyReports(); } }}><Flag size={15} />我的举报记录</DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>
      </header>

      <div ref={galleryRef} className={styles.scrollArea}>
        {loading ? (
          <div aria-busy="true" aria-label="正在加载提示词">
            <span role="status" className="sr-only">正在加载提示词</span>
            <div className={styles.gallery} aria-hidden="true">
              {Array.from({ length: 15 }, (_, i) => <div key={i} className={styles.skeleton} />)}
            </div>
          </div>
        ) : loadError ? (
          <div className={styles.empty} role="alert">
            <ImageIcon size={30} /><h2>灵感暂时没有加载出来</h2><p>{loadError}</p>
            <button onClick={() => fetchData(1)}>重新加载</button>
          </div>
        ) : prompts.length === 0 ? (
          <div className={styles.empty}>
            <ImageIcon size={30} /><h2>灵感，即将入场</h2>
            <p>添加图片和提示词，让好想法可以再次被使用。</p>
            <button onClick={() => { if (requireLogin('/prompts', '登录后添加你的提示词')) setShowAdd(true); }}>添加提示词</button>
          </div>
        ) : (
          <div className={styles.gallery}>
            {prompts.map(prompt => (
              <article key={prompt.id} className={styles.card}>
                <button className={styles.coverButton} onClick={() => { setPreviewPrompt(prompt); setPromptExpanded(false); }}
                  aria-label={`查看提示词：${prompt.title || prompt.name || '未命名提示词'}`}>
                  <PromptCover prompt={prompt} />
                </button>
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger className={styles.cardMenu} aria-label={`更多操作：${prompt.title || prompt.name || '未命名提示词'}`}>
                    <MoreHorizontal size={18} />
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Portal>
                    <DropdownMenu.Content className={styles.menu} align="end" sideOffset={6}>
                      <DropdownMenu.Item className={styles.menuItem} onSelect={() => handleCopy(prompt.chinese, `cn-${prompt.id}`)}><Copy size={15} />复制提示词</DropdownMenu.Item>
                      {prompt.english && <DropdownMenu.Item className={styles.menuItem} onSelect={() => handleCopy(prompt.english, `en-${prompt.id}`)}><Copy size={15} />复制英文提示词</DropdownMenu.Item>}
                      {prompt.can_edit && <DropdownMenu.Item className={styles.menuItem} onSelect={() => openEdit(prompt)}><Pencil size={15} />编辑</DropdownMenu.Item>}
                      {prompt.can_delete ? <DropdownMenu.Item className={cn(styles.menuItem, styles.danger)} onSelect={() => handleDelete(prompt.id)}><Trash2 size={15} />删除</DropdownMenu.Item>
                        : <DropdownMenu.Item className={styles.menuItem} onSelect={() => handleReport(prompt)}><Flag size={15} />举报</DropdownMenu.Item>}
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
                <div className={styles.cardDetails}>
                  <button className={styles.author} onClick={() => { setPreviewPrompt(prompt); setPromptExpanded(false); }}>
                    <span aria-hidden="true">{(prompt.source_author || prompt.source_name || prompt.created_by_name || '灵感')[0]}</span>
                    <b>{prompt.source_author || prompt.source_name || prompt.created_by_name || '灵感收录'}</b>
                  </button>
                  <div className={styles.cardActions}>
                    <Link className={styles.useCreative} href={getCreativeHref(prompt)}
                      onClick={event => protectLink(event, getCreativeHref(prompt), '登录后将这个提示词带入 AI 生图')}>
                      <Shuffle size={14} />使用创意
                    </Link>
                    <button
                      className={styles.favoriteButton}
                      aria-label={favoriteIds.has(prompt.id) ? '取消收藏' : '收藏'}
                      aria-pressed={favoriteIds.has(prompt.id)}
                      onClick={() => toggleFavorite(prompt.id)}
                    >
                      <Heart size={17} />
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
        {!loading && !loadError && prompts.length > 0 && <footer className={styles.feedStatus}>
          <span>已展示 {prompts.length.toLocaleString()} 个不重复灵感</span>
          {loadingMore && <span role="status"><Loader2 className="animate-spin" />正在加载更多灵感</span>}
          {loadMoreError && <button onClick={() => fetchData(page + 1, true)}>继续加载</button>}
          {!hasMore && <span>已经浏览完当前标签的全部内容</span>}
          <div ref={loadMoreSentinelRef} className={styles.loadMoreSentinel} aria-hidden="true" />
        </footer>}
      </div>

      {showImport && (
        <div className={styles.modalOverlay} onClick={() => setShowImport(false)}>
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div><span className={styles.modalEyebrow}>Import collection</span><h3>批量导入提示词</h3></div>
              <button aria-label="关闭导入弹窗" onClick={() => setShowImport(false)} className={styles.modalClose}><X /></button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.importGuide}>
                <p className={styles.guideTitle}>准备你的文件</p>
                <p>支持格式：`.xlsx` / `.xls` / `.csv`</p>
                <p>必填字段：`中文提示词`、`图片URL`（无图行会被拦截）</p>
                <p>推荐字段：`标题`、`分类`、`参数类型`、`英文提示词`</p>
                <p>示例表头：`标题,中文提示词,英文提示词,分类,参数类型,图片URL`</p>
                <a href="/prompt-import-template.csv" download className={styles.templateLink}>
                  <FileText />
                  下载导入模板
                </a>
              </div>
              <label className={styles.filePicker}>
                <span className={styles.filePickerIcon}><Upload /></span>
                <span><b>选择要导入的文件</b><small>单次导入后会自动刷新提示词宝库</small></span>
                <input ref={importInputRef} type="file" accept=".xlsx,.xls,.csv" onChange={handleImportFile} />
              </label>
              {importing && <div className={styles.processing}><Loader2 className="animate-spin" /> 正在整理提示词...</div>}
              {importResult && (
                <div className={styles.importResult}>
                  <p>
                    导入结果：成功 {importResult.imported_count} 条，失败 {importResult.failed_count} 条（总计 {importResult.total_rows} 条）
                  </p>
                  {importResult.created_categories.length > 0 && (
                    <p>新建分类：{importResult.created_categories.join('、')}</p>
                  )}
                  {importResult.failed_rows.length > 0 && (
                    <details>
                      <summary>查看失败明细（最多展示 10 条）</summary>
                      <ul>
                        {importResult.failed_rows.slice(0, 10).map((row, idx) => (
                          <li key={`${row.row}-${idx}`}>第 {row.row} 行{row.title ? `（${row.title}）` : ''}：{row.reason}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {showAdd && (
        <PromptModal
          title="添加提示词"
          form={addForm}
          onChange={setAddForm}
          onClose={() => setShowAdd(false)}
          onSubmit={handleAdd}
          loading={adding}
          submitText="添加"
        />
      )}

      {showEdit && (
        <PromptModal
          title="编辑提示词"
          form={editForm}
          onChange={setEditForm}
          onClose={() => { setShowEdit(false); setEditingPrompt(null); }}
          onSubmit={handleEdit}
          loading={editing}
          submitText="保存"
        />
      )}

      {showMyReports && (
        <div className={styles.modalOverlay} onClick={() => setShowMyReports(false)}>
          <div className={cn(styles.modal, styles.reportModal)} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div><span className={styles.modalEyebrow}>My reports</span><h3>我的举报记录</h3></div>
              <button aria-label="关闭举报记录" onClick={() => setShowMyReports(false)} className={styles.modalClose}><X /></button>
            </div>
            <div className={cn(styles.modalBody, styles.reportBody)}>
              {reportsLoading ? (
                <div className={styles.processing}><Loader2 className="animate-spin" /> 正在加载记录...</div>
              ) : myReports.length === 0 ? (
                <div className={styles.reportEmpty}><Flag />暂无举报记录</div>
              ) : (
                <table className={styles.reportTable}>
                  <thead>
                    <tr>
                      <th>提示词</th>
                      <th>原因</th>
                      <th>状态</th>
                      <th>时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {myReports.map(r => (
                      <tr key={r.id}>
                        <td>{r.prompt_name}</td>
                        <td>{r.reason}</td>
                        <td>
                          <span className={cn(styles.status, r.status === 'pending' ? styles.statusPending : r.status === 'resolved' ? styles.statusResolved : styles.statusRejected)}>
                            {r.status === 'pending' ? '待处理' : r.status === 'resolved' ? '已处理' : '已驳回'}
                          </span>
                          {r.resolution_note && <div className={styles.reportNote}>备注：{r.resolution_note}</div>}
                        </td>
                        <td>{r.created_at.slice(0, 19)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      <Dialog.Root open={Boolean(previewPrompt)} onOpenChange={open => { if (!open) setPreviewPrompt(null); }}>
      {previewPrompt && (
        <Dialog.Portal>
        <Dialog.Overlay className={styles.detailOverlay} />
        <Dialog.Content aria-describedby={undefined} className={styles.detailDialog}
          onClick={e => { if (e.target === e.currentTarget) setPreviewPrompt(null); }}>
          <Dialog.Title className="sr-only">{previewPrompt.title || previewPrompt.name || '提示词详情'}</Dialog.Title>
          <div
            className={styles.detailLayout}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.detailImagePanel}>
              <div className={styles.detailCover}><PromptDetailCover prompt={previewPrompt} /></div>
              <div className={styles.detailFloatingActions}>
                {previewPrompt.image_url && (
                  <a href={previewPrompt.image_url} target="_blank" rel="noreferrer" aria-label="下载图片" title="下载图片">
                    <Download />
                  </a>
                )}
                <button aria-label="关闭提示词详情" onClick={() => setPreviewPrompt(null)} className={styles.detailClose}>
                  <span>ESC</span><X />
                </button>
              </div>
            </div>

            <aside className={styles.detailAside}>
              <div className={styles.detailAsideInner}>
                <div className={styles.detailHeader}>
                  <div className={styles.detailMeta}>
                    <span className={styles.detailAuthorAvatar}>{(previewPrompt.source_author || previewPrompt.source_name || previewPrompt.created_by_name || '灵感')[0]}</span>
                    <b>{previewPrompt.source_author || previewPrompt.source_name || previewPrompt.created_by_name || '灵感收录'}</b>
                    <span className={styles.detailParam}>{previewPrompt.param_type || previewPrompt.category || 'AI 图像'}</span>
                  </div>
                  <div className={styles.detailQuickActions}>
                    <button aria-pressed={favoriteIds.has(previewPrompt.id)} onClick={() => toggleFavorite(previewPrompt.id)}>
                      <Heart />{favoriteIds.has(previewPrompt.id) ? '已收藏' : '收藏'}
                    </button>
                    <button onClick={() => handleCopy(previewPrompt.chinese, `preview-cn-${previewPrompt.id}`)}>
                      {copiedId === `preview-cn-${previewPrompt.id}` ? <><Check />已复制</> : <><Copy />复制提示词</>}
                    </button>
                  </div>
                </div>

                <div className={styles.detailBody}>
                  <div className={styles.detailSectionLabel}>提示词</div>
                  <div className={cn(styles.promptText, promptExpanded && styles.promptTextExpanded)}>
                    {previewPrompt.chinese}
                  </div>
                  {previewPrompt.chinese.length > 150 && (
                    <button className={styles.promptExpand} onClick={() => setPromptExpanded(value => !value)}>
                      {promptExpanded ? '收起' : '展开'}
                    </button>
                  )}

                  {previewPrompt.english && (
                    <div className={styles.englishBlock}>
                      <div className={styles.detailSectionHead}>
                        <div className={cn(styles.detailSectionLabel, styles.mutedLabel)}>English Prompt</div>
                        <button
                          onClick={() => handleCopy(previewPrompt.english, `preview-en-${previewPrompt.id}`)}
                          className={cn(styles.detailCopy, styles.detailCopyMuted)}
                        >
                          {copiedId === `preview-en-${previewPrompt.id}` ? <><Check /> 已复制</> : <><Copy /> 复制英文</>}
                        </button>
                      </div>
                      <div className={cn(styles.promptText, styles.promptTextEnglish)}>
                        {previewPrompt.english}
                      </div>
                    </div>
                  )}

                  {previewPrompt.source_kind === 'external' && (
                    <div className={styles.sourceAttribution}>
                      <div>
                        <span>外部灵感</span>
                        <b>{previewPrompt.source_name || '开放素材库'}</b>
                        {previewPrompt.source_license && <small>{previewPrompt.source_license}</small>}
                      </div>
                      {previewPrompt.source_url && (
                        <a href={previewPrompt.source_url} target="_blank" rel="noreferrer">查看原始内容</a>
                      )}
                    </div>
                  )}

                  {relatedPrompts.length > 0 && (
                    <section className={styles.relatedSection}>
                      <h3>更多相关内容</h3>
                      <div className={styles.relatedGrid}>
                        {relatedPrompts.map(item => (
                          <button key={item.id} onClick={() => { setPreviewPrompt(item); setPromptExpanded(false); }} aria-label={`查看相关提示词：${item.title || item.name || '未命名提示词'}`}>
                            <PromptCover prompt={item} />
                          </button>
                        ))}
                      </div>
                    </section>
                  )}
                </div>

                <div className={styles.detailFooter}>
                  <Link className={styles.detailUseCreative} href={getCreativeHref(previewPrompt)}
                    onClick={event => protectLink(event, getCreativeHref(previewPrompt), '登录后将这个提示词带入 AI 生图')}>
                    <Shuffle />使用创意
                  </Link>
                  <Link className={styles.detailReference} href={getCreativeHref(previewPrompt, true)}
                    onClick={event => protectLink(event, getCreativeHref(previewPrompt, true), '登录后用这张图片继续创作')}>
                    <ImageIcon />用作参考图
                  </Link>
                </div>
              </div>
            </aside>
          </div>
        </Dialog.Content>
        </Dialog.Portal>
      )}
      </Dialog.Root>
    </div>
  );
}

function PromptCover({ prompt }: { prompt: PromptItem }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [prompt.image_url]);
  if (!prompt.image_url || failed) return (
    <div className={styles.missingCover}>
      <ImageIcon size={28} /><strong>{prompt.title || prompt.name || '未命名提示词'}</strong>
      <span>{failed ? '图片暂不可用 · 查看提示词' : '文字也能开启灵感 · 查看提示词'}</span>
    </div>
  );
  const width = prompt.image_width || fallbackImageSize(prompt.id).width;
  const height = prompt.image_height || fallbackImageSize(prompt.id).height;
  return <span className={styles.coverFrame} style={{ aspectRatio: `${width} / ${height}` }}>
    <img src={prompt.image_url} alt={prompt.title || prompt.name || '提示词效果图'} loading="lazy" decoding="async" onError={() => setFailed(true)} />
  </span>;
}

function PromptDetailCover({ prompt }: { prompt: PromptItem }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [prompt.image_url]);

  if (!prompt.image_url || failed) return (
    <div className={styles.detailMissingCover}>
      <ImageIcon size={30} />
      <strong>{prompt.title || prompt.name || '未命名提示词'}</strong>
      <span>{failed ? '图片暂不可用' : '当前灵感暂无配图'}</span>
    </div>
  );

  return (
    <div className={styles.detailImageStage}>
      <img
        className={styles.detailImage}
        src={prompt.image_url}
        alt={prompt.title || prompt.name || '提示词效果图'}
        loading="eager"
        decoding="async"
        onError={() => setFailed(true)}
      />
    </div>
  );
}

function PromptModal({
  title,
  form,
  onChange,
  onClose,
  onSubmit,
  loading,
  submitText,
}: {
  title: string;
  form: PromptForm;
  onChange: (v: PromptForm) => void;
  onClose: () => void;
  onSubmit: () => void;
  loading: boolean;
  submitText: string;
}) {
  const [uploading, setUploading] = useState(false);
  const patch = (key: keyof PromptForm, value: string) => onChange({ ...form, [key]: value });

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await promptsApi.uploadImage(file);
      patch('image_url', res.data.url);
      toast.success('图片上传成功');
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : '图片上传失败');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={cn(styles.modal, styles.formModal)} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <div><span className={styles.modalEyebrow}>Prompt details</span><h3>{title}</h3></div>
          <button aria-label={`关闭${title}`} onClick={onClose} className={styles.modalClose}><X /></button>
        </div>
        <div className={cn(styles.modalBody, styles.formBody)}>
          <div className={styles.field}>
            <label>标题 <span>*</span></label>
            <input value={form.title} onChange={e => patch('title', e.target.value)} />
          </div>
          <div className={styles.field}>
            <label>中文提示词 <span>*</span></label>
            <textarea value={form.chinese} onChange={e => patch('chinese', e.target.value)} rows={4} />
          </div>
          <div className={styles.field}>
            <label>英文提示词</label>
            <textarea value={form.english} onChange={e => patch('english', e.target.value)} rows={3} />
          </div>
          <div className={styles.fieldRow}>
            <div className={styles.field}>
              <label>分类</label>
              <input value={form.category} onChange={e => patch('category', e.target.value)} />
            </div>
            <div className={styles.field}>
              <label>参数类型</label>
              <input value={form.param_type} onChange={e => patch('param_type', e.target.value)} />
            </div>
          </div>
          <div className={styles.field}>
            <label>图片 URL</label>
            <div className={styles.imageFieldRow}>
              <input value={form.image_url} onChange={e => patch('image_url', e.target.value)} placeholder="/uploads/prompts/xxx.png" />
              <label className={styles.uploadButton}>
                <Upload />
                {uploading ? '上传中...' : '上传'}
                <input type="file" accept="image/*" onChange={handleUpload} />
              </label>
            </div>
            {form.image_url && (
              <div className={styles.formPreview}>
                <img
                  src={form.image_url}
                  alt="提示词图片预览"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
              </div>
            )}
          </div>
        </div>
        <div className={styles.modalActions}>
          <button onClick={onClose} className={styles.secondaryAction}>取消</button>
          <button onClick={onSubmit} disabled={loading} className={styles.primaryAction}>
            {loading ? <><Loader2 className="animate-spin" />处理中...</> : submitText}
          </button>
        </div>
      </div>
    </div>
  );
}
