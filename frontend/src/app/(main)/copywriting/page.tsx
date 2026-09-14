'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import {
  Search, Upload, Copy, Trash2, Eye, X, Loader2, FileText, Tag,
  Plus, Edit3, Check, ChevronLeft, ChevronRight, Shield, RotateCcw, BellRing,
} from 'lucide-react';
import { copywritingApi, type ReviewCandidate, type ReviewTask } from '@/services/copywritingApi';
import { toast } from '@/lib/toast';
import styles from '@/components/library/library-workspace.module.css';

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
    <div className={styles.page} data-library="copywriting">
      <input ref={fileInputRef} type="file" accept=".xlsx,.xls" className="hidden" onChange={handleImport} />
      <header className={styles.header}>
        <nav className={styles.tabs} aria-label="文案库视图">
          <button className={styles.tab} aria-pressed={mode === 'library'} onClick={() => setMode('library')}>
            <FileText />文案
            {mode === 'library' && <span className={styles.count}>{filteredCount.toLocaleString()}</span>}
          </button>
          <button className={styles.tab} aria-pressed={mode === 'review'} onClick={() => setMode('review')}>
            <Shield />审核
            {pendingReviewCount > 0 && <span className={styles.count}>{pendingReviewCount}</span>}
          </button>
        </nav>
        <div className={styles.actions}>
          {mode === 'library' && (
            <label className={styles.search}>
              <Search />
              <input aria-label="搜索文案" placeholder="搜索标题、正文…" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
              {searchQuery && <button aria-label="清除搜索" onClick={() => setSearchQuery('')}><X /></button>}
            </label>
          )}
          <button className={styles.button} onClick={() => fileInputRef.current?.click()} disabled={importing}>
            {importing ? <Loader2 className="animate-spin" /> : <Upload />}
            {importing ? '导入中…' : '导入'}
          </button>
          <button className={styles.primaryButton} onClick={() => setShowCreate(true)}>
            <Plus />新建
          </button>
        </div>
      </header>

      {mode === 'library' ? (
        <div className={styles.filters}>
          <span className={styles.filterLabel}><Tag />分类</span>
          <nav className={styles.chips} aria-label="文案分类">
            <button className={styles.chip} aria-pressed={!activeCategory} onClick={() => setActiveCategory('')}>全部</button>
            {categories.map(cat => (
              <button key={cat.name} className={styles.chip} aria-pressed={activeCategory === cat.name} onClick={() => setActiveCategory(cat.name)} title={cat.name}>
                <span>{cat.name}</span><small>{cat.count}</small>
              </button>
            ))}
          </nav>
        </div>
      ) : (
        <div className={styles.filters}>
          <span className={styles.filterLabel}><BellRing />审核任务</span>
          <select className={styles.select} aria-label="选择审核任务" value={selectedTaskId ?? ''} onChange={e => setSelectedTaskId(Number(e.target.value) || null)} disabled={loadingReviewTasks || !reviewTasks.length}>
            {!reviewTasks.length && <option value="">{loadingReviewTasks ? '加载审核任务…' : '暂无审核任务'}</option>}
            {reviewTasks.map(task => <option key={task.id} value={task.id}>{task.name} · 待审 {task.pending_count} / 复核 {task.needs_second_review_count}</option>)}
          </select>
          <select aria-label="审核状态" value={reviewStatusFilter} onChange={e => setReviewStatusFilter(e.target.value)} className={styles.select}>
            <option value="">待审 + 复核</option>
            <option value="pending">仅待审</option>
            <option value="needs_second_review">仅待复核</option>
            <option value="approved">已通过</option>
            <option value="rejected">已淘汰</option>
          </select>
          {selectedReviewTask && <span className={styles.filterLabel}>已通过 {selectedReviewTask.approved_count} · 已淘汰 {selectedReviewTask.rejected_count}</span>}
        </div>
      )}

      <div className={styles.content}>
        {mode === 'library' && pendingReviewCount > 0 && (
          <div className={styles.notice}>
            <span>有 {pendingReviewCount} 条文案等待审核，通过后会收入文案库。</span>
            <button onClick={() => setMode('review')}>去审核 →</button>
          </div>
        )}
        <div className={styles.scrollArea}>
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
                <div className={styles.copyGrid}>
                  {filteredItems.map(item => (
                    <article key={item.id} className={styles.copyCard}>
                      <div className={styles.copyCardHeader}>
                        <span className={styles.copyCategory}><Tag /><span>{item.category || '文案灵感'}</span></span>
                        <div className={styles.cardActions}>
                          <button
                            onClick={() => { setEditingId(item.id); setEditTitle(item.title); setEditContent(item.content); }}
                            title="编辑文案" aria-label={`编辑 ${item.title}`}
                          ><Edit3 /></button>
                          <button onClick={() => handleDelete(item.id)} title="删除文案" aria-label={`删除 ${item.title}`}><Trash2 /></button>
                        </div>
                      </div>
                      <button className={styles.copyBody} onClick={() => setPreviewItem(item)} aria-label={`预览 ${item.title}`}>
                        <h3>{item.title}</h3>
                        <p>{item.content}</p>
                        {item.tags.length > 0 && (
                          <div className={styles.copyTags}>
                            {item.tags.slice(0, 3).map(tag => <span key={tag}>#{tag}</span>)}
                            {item.tags.length > 3 && <span>+{item.tags.length - 3}</span>}
                          </div>
                        )}
                      </button>
                      <div className={styles.copyFooter}>
                        <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleDateString('zh-CN')}</time>
                        <div>
                          <button onClick={() => copyToClipboard(item)}>
                            {copiedId === item.id ? <Check className="text-green-600" /> : <Copy />}
                            {copiedId === item.id ? '已复制' : '复制'}
                          </button>
                          <button onClick={() => setPreviewItem(item)}><Eye />全文</button>
                        </div>
                      </div>
                    </article>
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
            <div className={styles.reviewGrid}>
              {reviewCandidates.map(item => (
                <div key={item.id} className={styles.reviewCard}>
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

      {previewItem && createPortal(
        <div className={styles.modalBackdrop} onClick={() => setPreviewItem(null)}>
          <div className={styles.copyModal} onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => setPreviewItem(null)}
              aria-label="关闭文案预览"
              className={styles.modalClose}
            >
              <X className="h-4 w-4" />
            </button>
            <div className={styles.modalText}>
              <span className={styles.sectionKicker}>Copy preview</span>
              <h3>{previewItem.title}</h3>
              {previewItem.category && (
                <div className={styles.modalCategory}>
                  <Tag className="h-3 w-3" />
                  {previewItem.category}
                </div>
              )}
              <div className={styles.modalBody}>
                {previewItem.content}
              </div>
            </div>
          </div>
        </div>, document.body
      )}

      {(showCreate || editingId !== null) && createPortal(
        <div className={styles.modalBackdrop} onClick={() => { setShowCreate(false); setEditingId(null); }}>
          <div className={styles.editorModal} onClick={(e) => e.stopPropagation()}>
            <span className={styles.sectionKicker}>Writing editor</span>
            <h3>{editingId ? '编辑文案' : '新建文案'}</h3>
            <div className={styles.editorFields}>
              <input
                value={editingId ? editTitle : newTitle}
                onChange={(e) => editingId ? setEditTitle(e.target.value) : setNewTitle(e.target.value)}
                placeholder="标题"
                className={styles.editorInput}
              />
              <textarea
                value={editingId ? editContent : newContent}
                onChange={(e) => editingId ? setEditContent(e.target.value) : setNewContent(e.target.value)}
                placeholder="正文"
                rows={10}
                className={styles.editorTextarea}
              />
            </div>
            <div className={styles.modalActions}>
              <button
                onClick={() => { setShowCreate(false); setEditingId(null); }}
                className={styles.button}
              >
                取消
              </button>
              <button
                onClick={() => editingId ? handleUpdate(editingId) : handleCreate()}
                disabled={creating}
                className={styles.primaryButton}
              >
                {creating ? '处理中...' : editingId ? '保存修改' : '创建文案'}
              </button>
            </div>
          </div>
        </div>, document.body
      )}
    </div>
  );
}
