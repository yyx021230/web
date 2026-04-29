'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { cn } from '@/lib/utils';
import {
  Search, Upload, Copy, Trash2, Eye, X, Loader2, FileText, Tag,
  Plus, Edit3, Check, ChevronLeft, ChevronRight,
} from 'lucide-react';
import { copywritingApi } from '@/services/copywritingApi';
import { toast } from '@/lib/toast';

/* ---- Types ---- */
interface CopyItem {
  id: number;
  title: string;
  content: string;
  tags: string[];
  category: string | null;
  created_at: string;
}

const PAGE_SIZE = 20;

/* ---- Main Component ---- */
export default function CopywritingPage() {
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
  /* Pagination */
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  /* Debounced search */
  const [debouncedQuery, setDebouncedQuery] = useState('');

  const fileInputRef = useRef<HTMLInputElement>(null);

  /* ---- Fetch ---- */
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [itemsRes, catsRes] = await Promise.all([
        copywritingApi.getList({
          page, limit: PAGE_SIZE, owner: false,
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
    } finally {
      setLoading(false);
    }
  }, [page, activeCategory, debouncedQuery]);

  useEffect(() => { fetchData(); }, [fetchData]);

  /* ---- Actions ---- */
  const copyToClipboard = async (item: CopyItem) => {
    const text = `${item.title}\n${item.content}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(item.id);
      setTimeout(() => setCopiedId(null), 1500);
    } catch {
      // Fallback
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
      fetchData();
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
      fetchData();
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
      fetchData();
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
      fetchData();
    } catch (err) {
      toast.error('更新失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
  };

  /* Debounce effect */
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(searchQuery), 400);
    return () => clearTimeout(t);
  }, [searchQuery]);
  /* Reset page on filter change */
  useEffect(() => { setPage(1); }, [activeCategory, debouncedQuery]);

  const filteredItems = items;
  const filteredCount = total;

  return (
    <div className="flex h-full">
      <input ref={fileInputRef} type="file" accept=".xlsx,.xls" className="hidden" onChange={handleImport} />

      {/* ===== 左侧分类栏 ===== */}
      <div className="flex w-52 shrink-0 flex-col border-r bg-card">
        <div className="border-b px-4 py-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">文案库</h2>
            <button onClick={() => setShowCreate(true)}
              className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
              title="新建文案">
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">管理文案素材</p>
        </div>

        <div className="border-b px-4 py-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text" placeholder="搜索文案..." value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-md border bg-background py-1.5 pl-8 pr-2.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary/30"
            />
          </div>
        </div>

        <nav className="flex-1 overflow-auto py-2">
          <button
            onClick={() => setActiveCategory('')}
            className={cn(
              'flex w-full items-center justify-between px-4 py-2.5 text-sm transition-colors',
              !activeCategory ? 'bg-primary/10 text-primary font-medium' : 'text-foreground hover:bg-accent'
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
                activeCategory === cat.name ? 'bg-primary/10 text-primary font-medium' : 'text-foreground hover:bg-accent'
              )}
            >
              <div className="flex items-center gap-2.5">
                <Tag className="h-4 w-4" />
                <span className="truncate">{cat.name}</span>
              </div>
              <span className="text-xs text-muted-foreground">
                {cat.count}
              </span>
            </button>
          ))}
        </nav>

        {/* 导入按钮 */}
        <div className="border-t p-3 space-y-2">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={importing}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg border bg-background py-2 text-xs font-medium transition-colors hover:bg-accent disabled:opacity-50"
          >
            {importing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
            {importing ? '导入中...' : '导入 Excel'}
          </button>
        </div>
      </div>

      {/* ===== 主内容 ===== */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* 顶部工具栏 */}
        <div className="flex items-center justify-between border-b bg-card px-4 py-2.5 shrink-0">
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
        </div>

        {/* 文案卡片列表 */}
        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <Loader2 className="h-10 w-10 animate-spin text-primary mb-3" />
              <p className="text-sm text-muted-foreground">加载文案中...</p>
            </div>
          ) : filteredItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <FileText className="h-12 w-12 text-muted-foreground/30 mb-4" />
              <h3 className="text-sm font-medium mb-1">暂无文案</h3>
              <p className="text-xs text-muted-foreground mb-4">导入 Excel 或手动新建文案</p>
              <div className="flex gap-2">
                <button onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-1.5 rounded-lg border bg-background px-3 py-2 text-xs font-medium transition-colors hover:bg-accent">
                  <Upload className="h-3.5 w-3.5" />导入 Excel
                </button>
                <button onClick={() => setShowCreate(true)}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-primary/90">
                  <Plus className="h-3.5 w-3.5" />新建
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {filteredItems.map(item => (
                <div key={item.id}
                  className="group relative flex flex-col rounded-xl border bg-card hover:shadow-md transition-all cursor-pointer"
                  onClick={() => setPreviewItem(item)}>
                  {/* 分类标签 */}
                  {item.category && (
                    <div className="absolute top-2 right-2 flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-600/90 text-white text-[9px] font-medium">
                      <Tag className="h-2.5 w-2.5" />
                      <span>{item.category}</span>
                    </div>
                  )}
                  {/* 编辑/删除/复制按钮 */}
                  <div className="absolute top-2 left-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={(e) => { e.stopPropagation(); setEditingId(item.id); setEditTitle(item.title); setEditContent(item.content); }}
                      className="flex h-5 w-5 items-center justify-center rounded bg-background/90 border shadow-sm text-muted-foreground hover:text-blue-500"
                      title="编辑">
                      <Edit3 className="h-2.5 w-2.5" />
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); handleDelete(item.id); }}
                      className="flex h-5 w-5 items-center justify-center rounded bg-background/90 border shadow-sm text-muted-foreground hover:text-red-500"
                      title="删除">
                      <Trash2 className="h-2.5 w-2.5" />
                    </button>
                  </div>
                  {/* 卡片内容 */}
                  <div className="flex-1 p-3 pt-8">
                    <h3 className="text-sm font-semibold truncate">{item.title}</h3>
                    <p className="text-xs text-muted-foreground mt-1.5 line-clamp-4 leading-relaxed whitespace-pre-wrap">
                      {item.content.replace(/^.*?\n/, '').slice(0, 200)}
                    </p>
                    {/* 标签 */}
                    {item.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
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
                  {/* 底部操作 */}
                  <div className="flex items-center justify-between border-t px-3 py-2">
                    <span className="text-[10px] text-muted-foreground">
                      {new Date(item.created_at).toLocaleDateString('zh-CN')}
                    </span>
                    <div className="flex gap-1">
                      <button onClick={(e) => { e.stopPropagation(); copyToClipboard(item); }}
                        className={cn(
                          'flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition-colors',
                          copiedId === item.id ? 'text-green-600' : 'text-muted-foreground hover:text-primary'
                        )}>
                        {copiedId === item.id ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                        {copiedId === item.id ? '已复制' : '复制'}
                      </button>
                      <button onClick={(e) => { e.stopPropagation(); setPreviewItem(item); }}
                        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-primary transition-colors">
                        <Eye className="h-3 w-3" />预览
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            {/* Pagination */}
            {total > PAGE_SIZE && (
              <div className="flex items-center justify-between border-t pt-4">
                <span className="text-xs text-muted-foreground">
                  第 {page} 页 / 共 {Math.ceil(total / PAGE_SIZE)} 页 · 共 {total} 条
                </span>
                <div className="flex gap-2">
                  <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
                    className="px-3 py-1.5 text-xs rounded-md border disabled:opacity-40 hover:bg-accent flex items-center gap-1">
                    <ChevronLeft className="h-3.5 w-3.5" />上一页
                  </button>
                  {Array.from({ length: Math.min(5, Math.ceil(total / PAGE_SIZE)) }, (_, i) => {
                    let p: number;
                    const maxPage = Math.ceil(total / PAGE_SIZE);
                    if (maxPage <= 5) p = i + 1;
                    else if (page <= 3) p = i + 1;
                    else if (page >= maxPage - 2) p = maxPage - 4 + i;
                    else p = page - 2 + i;
                    return (
                      <button key={p} onClick={() => setPage(p)}
                        className={cn(
                          'h-7 w-7 text-xs rounded-md transition-colors',
                          p === page ? 'bg-primary text-white font-bold' : 'hover:bg-accent'
                        )}>{p}</button>
                    );
                  })}
                  <button disabled={page * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}
                    className="px-3 py-1.5 text-xs rounded-md border disabled:opacity-40 hover:bg-accent flex items-center gap-1">
                    下一页<ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            )}
            </div>
          )}
        </div>
      </div>

      {/* ===== 预览弹窗 ===== */}
      {previewItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm" onClick={() => setPreviewItem(null)}>
          <button onClick={() => setPreviewItem(null)} className="absolute top-4 right-4 z-10 flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors">
            <X className="h-5 w-5" />
          </button>
          <div onClick={(e) => e.stopPropagation()} className="flex flex-col max-w-2xl w-full mx-4 max-h-[85vh]">
            <div className="bg-card rounded-2xl border p-6 overflow-auto">
              {/* 标题 */}
              <div className="flex items-start justify-between mb-3">
                <h3 className="text-base font-semibold">{previewItem.title}</h3>
                {previewItem.category && (
                  <span className="flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-[10px] text-blue-600 shrink-0 ml-2">
                    <Tag className="h-3 w-3" />{previewItem.category}
                  </span>
                )}
              </div>
              {/* 正文 */}
              <div className="text-sm leading-relaxed whitespace-pre-wrap bg-muted/50 rounded-lg p-4 mb-4 max-h-[50vh] overflow-auto">
                {previewItem.content}
              </div>
              {/* 标签 */}
              {previewItem.tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-4">
                  {previewItem.tags.map(tag => (
                    <span key={tag} className="rounded-full bg-muted px-2.5 py-0.5 text-[10px] text-muted-foreground">
                      #{tag}
                    </span>
                  ))}
                </div>
              )}
              {/* 操作 */}
              <div className="flex items-center gap-2">
                <button onClick={() => copyToClipboard(previewItem)}
                  className={cn(
                    'flex-1 flex items-center justify-center gap-1.5 rounded-lg py-2 text-xs font-medium transition-colors',
                    copiedId === previewItem.id
                      ? 'bg-green-50 text-green-600'
                      : 'bg-primary text-white hover:bg-primary/90'
                  )}>
                  {copiedId === previewItem.id ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                  {copiedId === previewItem.id ? '已复制到剪贴板' : '复制全文'}
                </button>
                <button onClick={() => { setEditingId(previewItem.id); setEditTitle(previewItem.title); setEditContent(previewItem.content); }}
                  className="flex items-center justify-center gap-1.5 rounded-lg border py-2 px-3 text-xs font-medium text-muted-foreground hover:bg-accent transition-colors">
                  <Edit3 className="h-3.5 w-3.5" />编辑
                </button>
                <button onClick={() => { handleDelete(previewItem.id); }}
                  className="flex items-center justify-center gap-1.5 rounded-lg border py-2 px-3 text-xs font-medium text-red-600 hover:bg-red-50 transition-colors">
                  <Trash2 className="h-3.5 w-3.5" />删除
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ===== 编辑弹窗 ===== */}
      {editingId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm" onClick={() => setEditingId(null)}>
          <div onClick={(e) => e.stopPropagation()} className="flex flex-col max-w-2xl w-full mx-4 max-h-[85vh]">
            <div className="bg-card rounded-2xl border p-6">
              <h3 className="text-sm font-semibold mb-4">编辑文案</h3>
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">标题</label>
                  <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">内容</label>
                  <textarea value={editContent} onChange={(e) => setEditContent(e.target.value)} rows={12}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none whitespace-pre-wrap" />
                </div>
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setEditingId(null)}
                    className="rounded-lg border px-4 py-2 text-xs font-medium text-muted-foreground hover:bg-accent transition-colors">
                    取消
                  </button>
                  <button onClick={() => handleUpdate(editingId)}
                    className="rounded-lg bg-primary px-4 py-2 text-xs font-medium text-white hover:bg-primary/90 transition-colors">
                    保存
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ===== 新建弹窗 ===== */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm" onClick={() => setShowCreate(false)}>
          <div onClick={(e) => e.stopPropagation()} className="flex flex-col max-w-2xl w-full mx-4 max-h-[85vh]">
            <div className="bg-card rounded-2xl border p-6">
              <h3 className="text-sm font-semibold mb-4">新建文案</h3>
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">标题</label>
                  <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                    placeholder="输入文案标题" />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">内容</label>
                  <textarea value={newContent} onChange={(e) => setNewContent(e.target.value)} rows={12}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none whitespace-pre-wrap"
                    placeholder="输入文案正文，支持 #标签 自动提取" />
                </div>
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setShowCreate(false)}
                    className="rounded-lg border px-4 py-2 text-xs font-medium text-muted-foreground hover:bg-accent transition-colors">
                    取消
                  </button>
                  <button onClick={handleCreate} disabled={creating || !newTitle.trim() || !newContent.trim()}
                    className="rounded-lg bg-primary px-4 py-2 text-xs font-medium text-white hover:bg-primary/90 transition-colors disabled:opacity-50">
                    {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : '创建'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
