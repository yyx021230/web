'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { cn } from '@/lib/utils';
import {
  Search, Upload, Copy, Trash2, Eye, X, Loader2, FileText, Tag,
  Plus, Edit3, Check, ChevronLeft, ChevronRight, Shield, RotateCcw, BellRing,
} from 'lucide-react';
import { copywritingApi, type ReviewCandidate, type ReviewTask } from '@/services/copywritingApi';
import { toast } from '@/lib/toast';

interface CopyItem {
  id: number;
  title: string;
  content: string;
  tags: string[];
  category: string | null;
  created_at: string;
}

const PAGE_SIZE = 20;

export default function CopywritingPage() {
  const [mode, setMode] = useState<'library' | 'review'>('library');

  const [items, setItems] = useState<CopyItem[]>([]);
  const [categories, setCategories] = useState<Array<{ name: string; count: number }>>([]);
  const [activeCategory, setActiveCategory] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [previewItem, setPreviewItem] = useState<CopyItem | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [importing, setImporting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newContent, setNewContent] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [debouncedQuery, setDebouncedQuery] = useState('');

  const [reviewTasks, setReviewTasks] = useState<ReviewTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [reviewStatusFilter, setReviewStatusFilter] = useState('');
  const [reviewCandidates, setReviewCandidates] = useState<ReviewCandidate[]>([]);
  const [loadingReviewTasks, setLoadingReviewTasks] = useState(true);
  const [loadingReviewCandidates, setLoadingReviewCandidates] = useState(false);
  const [actingId, setActingId] = useState<number | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchLibrary = useCallback(async () => {
    setLoading(true);
    try {
      const [itemsRes, catsRes] = await Promise.all([
        copywritingApi.getList({
          page,
          limit: PAGE_SIZE,
          owner: false,
          category: activeCategory || undefined,
          keyword: debouncedQuery || undefined,
        }),
        copywritingApi.getCategories(),
      ]);
      setItems(itemsRes.data.items);
      setTotal(itemsRes.data.total);
      setCategories(catsRes.data.categories);
    } catch (e) {
      console.error('Failed to fetch copywriting data:', e);
      toast.error(e instanceof Error ? e.message : '加载文案失败');
    } finally {
      setLoading(false);
    }
  }, [page, activeCategory, debouncedQuery]);

  const fetchReviewTasks = useCallback(async () => {
    setLoadingReviewTasks(true);
    try {
      const res = await copywritingApi.getReviewTasks();
      setReviewTasks(res.data.items);
      if (!selectedTaskId && res.data.items.length > 0) {
        setSelectedTaskId(res.data.items[0].id);
      }
      if (selectedTaskId && !res.data.items.some(task => task.id === selectedTaskId)) {
        setSelectedTaskId(res.data.items[0]?.id ?? null);
      }
    } catch (e) {
      console.error('Failed to fetch review tasks:', e);
    } finally {
      setLoadingReviewTasks(false);
    }
  }, [selectedTaskId]);

  const fetchReviewCandidates = useCallback(async () => {
    if (!selectedTaskId) {
      setReviewCandidates([]);
      return;
    }
    setLoadingReviewCandidates(true);
    try {
      const res = await copywritingApi.getReviewCandidates({
        task_id: selectedTaskId,
        status: reviewStatusFilter || undefined,
      });
      setReviewCandidates(res.data.items);
    } catch (e) {
      console.error('Failed to fetch review candidates:', e);
      toast.error(e instanceof Error ? e.message : '加载审核内容失败');
    } finally {
      setLoadingReviewCandidates(false);
    }
  }, [selectedTaskId, reviewStatusFilter]);

  useEffect(() => { fetchLibrary(); }, [fetchLibrary]);
  useEffect(() => { fetchReviewTasks(); }, [fetchReviewTasks]);
  useEffect(() => { fetchReviewCandidates(); }, [fetchReviewCandidates]);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(searchQuery), 400);
    return () => clearTimeout(t);
  }, [searchQuery]);

  useEffect(() => { setPage(1); }, [activeCategory, debouncedQuery]);

  const copyToClipboard = async (item: CopyItem) => {
    const text = `${item.title}\n${item.content}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(item.id);
      setTimeout(() => setCopiedId(null), 1500);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopiedId(item.id);
      setTimeout(() => setCopiedId(null), 1500);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这条文案吗？')) return;
    try {
      await copywritingApi.delete(id);
      toast.success('已删除');
      fetchLibrary();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const res = await copywritingApi.importExcel(file);
      toast.success(`${(res.data as any)?.count || '成功'} 条文案已导入`);
      fetchLibrary();
    } catch (err) {
      toast.error('导入失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setImporting(false);
    }
    e.target.value = '';
  };

  const handleCreate = async () => {
    if (!newTitle.trim() || !newContent.trim()) return;
    setCreating(true);
    try {
      await copywritingApi.create({ title: newTitle, content: newContent });
      toast.success('创建成功');
      setNewTitle('');
      setNewContent('');
      setShowCreate(false);
      fetchLibrary();
    } catch (err) {
      toast.error('创建失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setCreating(false);
    }
  };

  const handleUpdate = async (id: number) => {
    if (!editTitle.trim() || !editContent.trim()) return;
    try {
      await copywritingApi.update(id, { title: editTitle, content: editContent });
      toast.success('更新成功');
      setEditingId(null);
      fetchLibrary();
    } catch (err) {
      toast.error('更新失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
  };

  const handleReviewAction = async (candidateId: number, action: 'approved' | 'rejected' | 'needs_second_review') => {
    setActingId(candidateId);
    try {
      await copywritingApi.reviewCandidate(candidateId, action);
      toast.success(action === 'approved' ? '已通过入库' : action === 'rejected' ? '已淘汰' : '已标记待复核');
      await fetchReviewTasks();
      await fetchReviewCandidates();
      if (action === 'approved') {
        fetchLibrary();
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '审核失败');
    } finally {
      setActingId(null);
    }
  };

  const pendingReviewCount = reviewTasks.reduce((sum, task) => sum + task.pending_count + task.needs_second_review_count, 0);
  const selectedReviewTask = reviewTasks.find(task => task.id === selectedTaskId) || null;
  const filteredItems = items;
  const filteredCount = total;

  return (
    <div className="cloud-page flex h-full gap-4 p-4">
      <input ref={fileInputRef} type="file" accept=".xlsx,.xls" className="hidden" onChange={handleImport} />

      <div className="cloud-panel flex w-60 shrink-0 flex-col overflow-hidden rounded-[28px]">
        <div className="border-b border-slate-200/70 px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[11px] font-semibold text-indigo-600">Cloud Studio</div>
              <h2 className="text-sm font-semibold text-slate-950">文案库</h2>
            </div>
            <button
              onClick={() => setShowCreate(true)}
              className="flex h-8 w-8 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600 hover:bg-indigo-100 transition-colors"
              title="新建文案"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
          <p className="mt-1 text-xs text-slate-500">管理文案素材和审核任务</p>
        </div>

        <div className="border-b border-slate-200/70 px-4 py-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder={mode === 'library' ? '搜索文案...' : '审核内容筛选在右侧'}
              value={mode === 'library' ? searchQuery : ''}
              onChange={(e) => mode === 'library' && setSearchQuery(e.target.value)}
              disabled={mode !== 'library'}
              className="cloud-pill w-full rounded-2xl py-2 pl-8 pr-2.5 text-xs focus:outline-none focus:ring-4 focus:ring-indigo-100 disabled:opacity-50"
            />
          </div>
        </div>

        <div className="border-b border-slate-200/70 px-3 py-3 space-y-2">
          <button
            onClick={() => setMode('library')}
            className={cn(
              'flex w-full items-center justify-between rounded-2xl px-3 py-2 text-sm transition-colors',
              mode === 'library' ? 'bg-indigo-50 text-indigo-600 font-medium' : 'text-slate-700 hover:bg-white/60'
            )}
          >
            <span className="inline-flex items-center gap-2">
              <FileText className="h-4 w-4" />
              正式文案库
            </span>
            <span className="text-xs text-muted-foreground">{total}</span>
          </button>
          <button
            onClick={() => setMode('review')}
            className={cn(
              'flex w-full items-center justify-between rounded-2xl px-3 py-2 text-sm transition-colors',
              mode === 'review' ? 'bg-amber-50 text-amber-700 font-medium' : 'text-slate-700 hover:bg-white/60'
            )}
          >
            <span className="inline-flex items-center gap-2">
              <Shield className="h-4 w-4" />
              待我审核
            </span>
            <span className="text-xs text-amber-700">{pendingReviewCount}</span>
          </button>
        </div>

        {mode === 'library' ? (
          <>
            <nav className="flex-1 overflow-auto py-2">
              <button
                onClick={() => setActiveCategory('')}
                className={cn(
                  'flex w-full items-center justify-between px-4 py-2.5 text-sm transition-colors',
                  !activeCategory ? 'bg-indigo-50 text-indigo-600 font-medium' : 'text-slate-700 hover:bg-white/60'
                )}
              >
                <div className="flex items-center gap-2.5">
                  <FileText className="h-4 w-4" />
                  <span>全部</span>
                </div>
                <span className="text-xs text-muted-foreground">共 {total}</span>
              </button>
              {categories.map(cat => (
                <button
                  key={cat.name}
                  onClick={() => setActiveCategory(cat.name)}
                  className={cn(
                    'flex w-full items-center justify-between px-4 py-2.5 text-sm transition-colors',
                    activeCategory === cat.name ? 'bg-indigo-50 text-indigo-600 font-medium' : 'text-slate-700 hover:bg-white/60'
                  )}
                >
                  <div className="flex items-center gap-2.5">
                    <Tag className="h-4 w-4" />
                    <span className="truncate">{cat.name}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">{cat.count}</span>
                </button>
              ))}
            </nav>
            <div className="border-t border-slate-200/70 p-3 space-y-2">
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={importing}
                className="cloud-pill flex w-full items-center justify-center gap-1.5 rounded-2xl py-2 text-xs font-medium text-slate-600 transition-colors hover:bg-indigo-50 disabled:opacity-50"
              >
                {importing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                {importing ? '导入中...' : '导入 Excel'}
              </button>
            </div>
          </>
        ) : (
          <div className="flex-1 overflow-auto py-2">
            {loadingReviewTasks ? (
              <div className="px-4 py-8 text-sm text-slate-400">加载审核任务...</div>
            ) : reviewTasks.length === 0 ? (
              <div className="px-4 py-8 text-sm text-slate-400">暂无待处理任务</div>
            ) : (
              reviewTasks.map(task => (
                <button
                  key={task.id}
                  onClick={() => setSelectedTaskId(task.id)}
                  className={cn(
                    'flex w-full items-center justify-between px-4 py-3 text-left transition-colors',
                    selectedTaskId === task.id ? 'bg-amber-50 text-amber-700 font-medium' : 'text-slate-700 hover:bg-white/60'
                  )}
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm">{task.name}</div>
                    <div className="mt-1 text-[11px] text-slate-500">
                      待审 {task.pending_count} / 复核 {task.needs_second_review_count}
                    </div>
                  </div>
                  <span className="text-xs text-amber-700">{task.pending_count + task.needs_second_review_count}</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>

      <div className="cloud-panel flex flex-1 flex-col overflow-hidden rounded-[28px]">
        <div className="cloud-toolbar flex items-center justify-between px-4 py-3 shrink-0">
          {mode === 'library' ? (
            <div className="flex items-center gap-2">
              {activeCategory && (
                <span className="flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs text-primary">
                  <Tag className="h-3 w-3" />{activeCategory}
                  <button onClick={() => setActiveCategory('')} className="ml-1 hover:text-primary-hover">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              )}
              {debouncedQuery && (
                <span className="text-xs text-muted-foreground">
                  搜索 "{debouncedQuery}" · {filteredCount} 条
                </span>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <span className="inline-flex items-center gap-2 text-sm font-medium text-slate-900">
                <BellRing className="h-4 w-4 text-amber-600" />
                {selectedReviewTask ? selectedReviewTask.name : '待我审核'}
              </span>
              {selectedReviewTask && (
                <span className="text-xs text-slate-500">
                  待审 {selectedReviewTask.pending_count} / 已通过 {selectedReviewTask.approved_count} / 已淘汰 {selectedReviewTask.rejected_count}
                </span>
              )}
            </div>
          )}

          {mode === 'review' && (
            <select
              value={reviewStatusFilter}
              onChange={(e) => setReviewStatusFilter(e.target.value)}
              className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700"
            >
              <option value="">待审 + 复核</option>
              <option value="pending">仅待审</option>
              <option value="needs_second_review">仅待复核</option>
              <option value="approved">已通过</option>
              <option value="rejected">已淘汰</option>
            </select>
          )}
        </div>

        {mode === 'library' && pendingReviewCount > 0 && (
          <div className="mx-4 mt-4 rounded-3xl border border-amber-200 bg-amber-50 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-amber-900">你有新的审核任务</div>
                <div className="mt-1 text-xs text-amber-800">
                  当前共有 {pendingReviewCount} 条待处理内容，审核通过后才会进入正式文案库。
                </div>
              </div>
              <button
                onClick={() => setMode('review')}
                className="rounded-2xl bg-amber-600 px-3 py-2 text-xs font-medium text-white hover:bg-amber-700"
              >
                去处理
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-auto p-4">
          {mode === 'library' ? (
            loading ? (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <Loader2 className="mb-3 h-10 w-10 animate-spin text-primary" />
                <p className="text-sm text-muted-foreground">加载文案中...</p>
              </div>
            ) : filteredItems.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <FileText className="mb-4 h-12 w-12 text-muted-foreground/30" />
                <h3 className="mb-1 text-sm font-medium">暂无文案</h3>
                <p className="mb-4 text-xs text-muted-foreground">导入 Excel 或手动新建文案</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="flex items-center gap-1.5 rounded-lg border bg-background px-3 py-2 text-xs font-medium transition-colors hover:bg-accent"
                  >
                    <Upload className="h-3.5 w-3.5" />导入 Excel
                  </button>
                  <button
                    onClick={() => setShowCreate(true)}
                    className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-primary/90"
                  >
                    <Plus className="h-3.5 w-3.5" />新建
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {filteredItems.map(item => (
                    <div
                      key={item.id}
                      className="cloud-card cloud-card-hover group relative flex cursor-pointer flex-col rounded-3xl"
                      onClick={() => setPreviewItem(item)}
                    >
                      {item.category && (
                        <div className="absolute top-2 right-2 flex items-center gap-1 rounded bg-blue-600/90 px-1.5 py-0.5 text-[9px] font-medium text-white">
                          <Tag className="h-2.5 w-2.5" />
                          <span>{item.category}</span>
                        </div>
                      )}
                      <div className="absolute top-2 left-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingId(item.id);
                            setEditTitle(item.title);
                            setEditContent(item.content);
                          }}
                          className="flex h-5 w-5 items-center justify-center rounded border bg-background/90 text-muted-foreground shadow-sm hover:text-blue-500"
                          title="编辑"
                        >
                          <Edit3 className="h-2.5 w-2.5" />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(item.id);
                          }}
                          className="flex h-5 w-5 items-center justify-center rounded border bg-background/90 text-muted-foreground shadow-sm hover:text-red-500"
                          title="删除"
                        >
                          <Trash2 className="h-2.5 w-2.5" />
                        </button>
                      </div>
                      <div className="flex-1 p-3 pt-8">
                        <h3 className="truncate text-sm font-semibold">{item.title}</h3>
                        <p className="mt-1.5 line-clamp-4 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
                          {item.content.replace(/^.*?\n/, '').slice(0, 200)}
                        </p>
                        {item.tags.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {item.tags.slice(0, 3).map(tag => (
                              <span key={tag} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                                #{tag}
                              </span>
                            ))}
                            {item.tags.length > 3 && (
                              <span className="text-[10px] text-muted-foreground">+{item.tags.length - 3}</span>
                            )}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center justify-between border-t px-3 py-2">
                        <span className="text-[10px] text-muted-foreground">
                          {new Date(item.created_at).toLocaleDateString('zh-CN')}
                        </span>
                        <div className="flex gap-1">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              copyToClipboard(item);
                            }}
                            className={cn(
                              'flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition-colors',
                              copiedId === item.id ? 'text-green-600' : 'text-muted-foreground hover:text-primary'
                            )}
                          >
                            {copiedId === item.id ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                            {copiedId === item.id ? '已复制' : '复制'}
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setPreviewItem(item);
                            }}
                            className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:text-primary"
                          >
                            <Eye className="h-3 w-3" />预览
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                {total > PAGE_SIZE && (
                  <div className="flex items-center justify-between border-t pt-4">
                    <span className="text-xs text-muted-foreground">
                      第 {page} 页 / 共 {Math.ceil(total / PAGE_SIZE)} 页 · 共 {total} 条
                    </span>
                    <div className="flex gap-2">
                      <button
                        disabled={page <= 1}
                        onClick={() => setPage(p => p - 1)}
                        className="flex items-center gap-1 rounded-lg border bg-background px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent disabled:opacity-40"
                      >
                        <ChevronLeft className="h-3.5 w-3.5" />上一页
                      </button>
                      <button
                        disabled={page * PAGE_SIZE >= total}
                        onClick={() => setPage(p => p + 1)}
                        className="flex items-center gap-1 rounded-lg border bg-background px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent disabled:opacity-40"
                      >
                        下一页<ChevronRight className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          ) : loadingReviewCandidates ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <Loader2 className="mb-3 h-10 w-10 animate-spin text-amber-600" />
              <p className="text-sm text-muted-foreground">加载审核内容中...</p>
            </div>
          ) : !selectedReviewTask ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <Shield className="mb-4 h-12 w-12 text-muted-foreground/30" />
              <h3 className="mb-1 text-sm font-medium">暂无审核任务</h3>
              <p className="text-xs text-muted-foreground">管理员分配任务后，会在这里提醒你处理。</p>
            </div>
          ) : reviewCandidates.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <Shield className="mb-4 h-12 w-12 text-muted-foreground/30" />
              <h3 className="mb-1 text-sm font-medium">当前筛选下没有内容</h3>
              <p className="text-xs text-muted-foreground">换个任务或筛选状态看看。</p>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {reviewCandidates.map(item => (
                <div key={item.id} className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold text-slate-950">{item.title}</h3>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{item.review_status}</span>
                    {item.brand && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">{item.brand}</span>}
                    {item.copy_type && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">{item.copy_type}</span>}
                  </div>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-600">{item.content}</p>
                  <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                    <span>作者 {item.author || '-'}</span>
                    <span>日期 {item.publish_date || '-'}</span>
                    <span>点赞 {item.likes}</span>
                    <span>评论 {item.comments}</span>
                    <span>收藏 {item.collects}</span>
                    <span>分享 {item.shares}</span>
                    {item.source_keyword && <span>关键词 {item.source_keyword}</span>}
                  </div>
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    {item.post_url && (
                      <a href={item.post_url} target="_blank" rel="noreferrer" className="text-xs text-indigo-600 hover:underline">
                        查看原帖
                      </a>
                    )}
                    <button
                      disabled={actingId === item.id}
                      onClick={() => handleReviewAction(item.id, 'approved')}
                      className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      <Check className="h-3.5 w-3.5" />
                      通过入库
                    </button>
                    <button
                      disabled={actingId === item.id}
                      onClick={() => handleReviewAction(item.id, 'rejected')}
                      className="inline-flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700 disabled:opacity-50"
                    >
                      <X className="h-3.5 w-3.5" />
                      淘汰
                    </button>
                    <button
                      disabled={actingId === item.id}
                      onClick={() => handleReviewAction(item.id, 'needs_second_review')}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      标记复核
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {previewItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setPreviewItem(null)}>
          <div className="cloud-panel relative max-h-[85vh] w-full max-w-2xl overflow-auto rounded-[32px] p-6" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => setPreviewItem(null)}
              className="absolute right-4 top-4 flex h-8 w-8 items-center justify-center rounded-full bg-accent text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
            <div className="pr-10">
              <h3 className="text-lg font-semibold">{previewItem.title}</h3>
              {previewItem.category && (
                <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-1 text-xs text-blue-700">
                  <Tag className="h-3 w-3" />
                  {previewItem.category}
                </div>
              )}
              <div className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                {previewItem.content}
              </div>
            </div>
          </div>
        </div>
      )}

      {(showCreate || editingId !== null) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => { setShowCreate(false); setEditingId(null); }}>
          <div className="cloud-panel w-full max-w-2xl rounded-[32px] p-6" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold">{editingId ? '编辑文案' : '新建文案'}</h3>
            <div className="mt-4 space-y-3">
              <input
                value={editingId ? editTitle : newTitle}
                onChange={(e) => editingId ? setEditTitle(e.target.value) : setNewTitle(e.target.value)}
                placeholder="标题"
                className="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm focus:outline-none focus:ring-4 focus:ring-indigo-100"
              />
              <textarea
                value={editingId ? editContent : newContent}
                onChange={(e) => editingId ? setEditContent(e.target.value) : setNewContent(e.target.value)}
                placeholder="正文"
                rows={10}
                className="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm focus:outline-none focus:ring-4 focus:ring-indigo-100"
              />
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => { setShowCreate(false); setEditingId(null); }}
                className="rounded-2xl border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
              >
                取消
              </button>
              <button
                onClick={() => editingId ? handleUpdate(editingId) : handleCreate()}
                disabled={creating}
                className="rounded-2xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {creating ? '处理中...' : editingId ? '保存修改' : '创建文案'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
