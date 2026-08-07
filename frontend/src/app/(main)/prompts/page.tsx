'use client';

import { useState, useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';
import {
  Search, Copy, Check, Sparkles, Loader2, Upload,
  FileText, X, Plus, ImageIcon, Trash2, Pencil, Flag,
} from 'lucide-react';
import { promptsApi, type PromptItem, type PromptImportResult } from '@/services/promptsApi';
import { toast } from '@/lib/toast';

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

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [categories, setCategories] = useState<{ name: string; count: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('');
  const [onlyMine, setOnlyMine] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [showAllCategories, setShowAllCategories] = useState(false);
  const [previewPrompt, setPreviewPrompt] = useState<PromptItem | null>(null);
  const PAGE_SIZE = 24;

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
  const hasLoadedListRef = useRef(false);

  const [addForm, setAddForm] = useState<PromptForm>(emptyForm);
  const [editForm, setEditForm] = useState<PromptForm>(emptyForm);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(false);

  const fetchData = async (kw?: string, cat?: string, p = 1, mine = onlyMine) => {
    setLoading(true);
    try {
      const res = await promptsApi.getPrompts(kw, cat, p, PAGE_SIZE, mine);
      setPrompts(res.data.items);
      setTotal(res.data.total);
      setPage(res.data.page);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const fetchCategories = async () => {
    try {
      const res = await promptsApi.getCategories();
      setCategories(res.data.categories);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchCategories();
  }, []);

  useEffect(() => {
    if (!hasLoadedListRef.current) {
      hasLoadedListRef.current = true;
      fetchData(searchQuery, activeCategory, 1, onlyMine);
      return;
    }
    const timer = setTimeout(() => {
      fetchData(searchQuery, activeCategory, 1, onlyMine);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, activeCategory, onlyMine]);

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
      fetchData(searchQuery, activeCategory, 1);
      fetchCategories();
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
      fetchData(searchQuery, activeCategory, 1);
      fetchCategories();
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
      fetchData(searchQuery, activeCategory, page);
      fetchCategories();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '更新失败');
    } finally {
      setEditing(false);
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const visibleCategories = showAllCategories ? categories : categories.slice(0, 12);

  return (
    <div className="cloud-page flex h-full flex-col">
      <div className="cloud-toolbar flex items-center justify-between px-5 py-3 shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-300/40">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <div className="text-[11px] font-semibold text-indigo-600">Cloud Studio</div>
            <h1 className="text-sm font-semibold text-slate-950">提示词库</h1>
          </div>
          <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-600">{total} 条</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => { setShowMyReports(true); fetchMyReports(); }} className="cloud-pill flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-indigo-50 transition-colors">
            我的举报
          </button>
          <button onClick={() => setShowAdd(true)} className="cloud-pill flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-indigo-50 transition-colors">
            <Plus className="h-3.5 w-3.5" /> 添加
          </button>
          <button onClick={() => setShowImport(true)} className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-3 py-1.5 text-xs font-medium text-white shadow-lg shadow-indigo-200 transition-colors">
            <Upload className="h-3.5 w-3.5" /> 批量导入
          </button>
        </div>
      </div>

      <div className="cloud-toolbar px-5 py-3 shrink-0 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[220px] max-w-md">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="搜索提示词..." className="cloud-pill w-full rounded-2xl py-2 pl-8 pr-3 text-xs focus:outline-none focus:ring-4 focus:ring-indigo-100" />
          </div>
          <label className="inline-flex items-center gap-2 text-xs text-muted-foreground whitespace-nowrap">
            <input type="checkbox" checked={onlyMine} onChange={e => setOnlyMine(e.target.checked)} className="rounded" />
            只看我上传的提示词
          </label>
        </div>
        <div className="flex items-center justify-between gap-3">
          <div className="text-[11px] text-muted-foreground">
            分类 {categories.length} 个
          </div>
          {categories.length > 12 && (
            <button
              onClick={() => setShowAllCategories(v => !v)}
              className="text-[11px] text-primary hover:underline"
            >
              {showAllCategories ? '收起分类' : '展开全部'}
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button onClick={() => setActiveCategory('')} className={cn('cloud-pill rounded-full px-3 py-1 text-[11px] font-medium transition-colors', !activeCategory ? 'border-indigo-400 bg-indigo-50 text-indigo-600' : 'text-slate-500 hover:border-indigo-200 hover:text-slate-900')}>全部</button>
          {visibleCategories.map(cat => (
            <button key={cat.name} onClick={() => setActiveCategory(cat.name)} className={cn('cloud-pill rounded-full px-3 py-1 text-[11px] font-medium transition-colors', activeCategory === cat.name ? 'border-indigo-400 bg-indigo-50 text-indigo-600' : 'text-slate-500 hover:border-indigo-200 hover:text-slate-900')}>
              {cat.name} <span className="opacity-50 ml-0.5">({cat.count})</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-auto p-5">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin mb-2" />
            <span className="text-sm">加载中...</span>
          </div>
        ) : prompts.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <FileText className="h-8 w-8 mb-3 opacity-30" />
            <p className="text-sm">暂无提示词</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
            {prompts.map(prompt => {
              const copyIdCn = `cn-${prompt.id}`;
              const copyIdEn = `en-${prompt.id}`;
              return (
                <div key={prompt.id} className="cloud-card cloud-card-hover group overflow-hidden rounded-3xl">
                  {prompt.image_url ? (
                    <div
                      className="aspect-[3/4] overflow-hidden bg-slate-50 bg-[radial-gradient(circle_at_1px_1px,rgba(100,116,139,0.18)_1px,transparent_0)] [background-size:14px_14px] cursor-zoom-in flex items-center justify-center"
                      onClick={() => setPreviewPrompt(prompt)}
                      title="点击查看图片和提示词详情"
                    >
                      <img
                        src={prompt.image_url}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        className="h-full w-full object-cover object-[center_68%] rounded-2xl shadow-sm transition-transform duration-300 group-hover:scale-[1.04]"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                      />
                    </div>
                  ) : (
                    <div className="aspect-[3/4] bg-gradient-to-br from-primary/5 via-purple-50/50 to-primary/5 flex items-center justify-center">
                      <ImageIcon className="h-5 w-5 text-muted-foreground/20" />
                    </div>
                  )}

                  <div className="p-3 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-xs font-semibold text-foreground line-clamp-1 flex-1">{prompt.title}</h3>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all">
                        {prompt.can_edit && (
                          <button onClick={() => openEdit(prompt)} className="p-1 rounded hover:bg-blue-50 text-muted-foreground hover:text-blue-500">
                            <Pencil className="h-3 w-3" />
                          </button>
                        )}
                        {prompt.can_delete && (
                          <button onClick={() => handleDelete(prompt.id)} className="p-1 rounded hover:bg-red-50 text-muted-foreground hover:text-red-500">
                            <Trash2 className="h-3 w-3" />
                          </button>
                        )}
                        {!prompt.can_delete && (
                          <button onClick={() => handleReport(prompt)} className="p-1 rounded hover:bg-amber-50 text-muted-foreground hover:text-amber-600" title="举报">
                            <Flag className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {prompt.category && <span className="inline-block rounded-md bg-primary/5 px-1.5 py-0.5 text-[10px] text-primary font-medium">{prompt.category}</span>}
                      {prompt.created_by_name && <span className="inline-block rounded-md bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">By {prompt.created_by_name}</span>}
                    </div>

                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] font-medium text-muted-foreground">中文</span>
                        <button onClick={() => handleCopy(prompt.chinese, copyIdCn)} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-primary transition-colors">
                          {copiedId === copyIdCn ? <><Check className="h-3 w-3 text-green-500" /> 已复制</> : <><Copy className="h-3 w-3" /> 复制</>}
                        </button>
                      </div>
                      <div className="line-clamp-3 rounded-lg bg-muted/50 px-2.5 py-2 text-xs leading-relaxed text-foreground">{prompt.chinese}</div>
                    </div>

                    {prompt.english && (
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] font-medium text-muted-foreground">English</span>
                          <button onClick={() => handleCopy(prompt.english, copyIdEn)} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-primary transition-colors">
                            {copiedId === copyIdEn ? <><Check className="h-3 w-3 text-green-500" /> 已复制</> : <><Copy className="h-3 w-3" /> 复制</>}
                          </button>
                        </div>
                        <div className="line-clamp-2 rounded-lg bg-muted/30 px-2.5 py-2 text-xs leading-relaxed text-muted-foreground">{prompt.english}</div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-6 pb-4">
            <button disabled={page <= 1} onClick={() => fetchData(searchQuery, activeCategory, page - 1)} className="rounded-lg border bg-card px-3 py-1.5 text-xs font-medium disabled:opacity-40 hover:bg-accent transition-colors">上一页</button>
            <span className="text-xs text-muted-foreground">{page} / {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => fetchData(searchQuery, activeCategory, page + 1)} className="rounded-lg border bg-card px-3 py-1.5 text-xs font-medium disabled:opacity-40 hover:bg-accent transition-colors">下一页</button>
          </div>
        )}
      </div>

      {showImport && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setShowImport(false)}>
          <div className="bg-white rounded-2xl shadow-2xl border w-[480px] overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h3 className="text-sm font-semibold">批量导入提示词</h3>
              <button onClick={() => setShowImport(false)} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-5 space-y-4">
              <div className="rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground space-y-1.5">
                <p className="font-medium text-foreground">导入说明</p>
                <p>支持格式：`.xlsx` / `.xls` / `.csv`</p>
                <p>必填字段：`中文提示词`、`图片URL`（无图行会被拦截）</p>
                <p>推荐字段：`标题`、`分类`、`参数类型`、`英文提示词`</p>
                <p>示例表头：`标题,中文提示词,英文提示词,分类,参数类型,图片URL`</p>
                <a href="/prompt-import-template.csv" download className="inline-flex items-center gap-1 text-primary hover:underline">
                  <FileText className="h-3 w-3" />
                  下载导入模板
                </a>
              </div>
              <input ref={importInputRef} type="file" accept=".xlsx,.xls,.csv" onChange={handleImportFile} className="w-full text-sm" />
              {importing && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> 导入中...</div>}
              {importResult && (
                <div className="rounded-lg border p-3 text-xs space-y-2">
                  <p className="text-foreground font-medium">
                    导入结果：成功 {importResult.imported_count} 条，失败 {importResult.failed_count} 条（总计 {importResult.total_rows} 条）
                  </p>
                  {importResult.created_categories.length > 0 && (
                    <p className="text-muted-foreground">新建分类：{importResult.created_categories.join('、')}</p>
                  )}
                  {importResult.failed_rows.length > 0 && (
                    <details>
                      <summary className="cursor-pointer text-red-600">查看失败明细（最多展示 10 条）</summary>
                      <ul className="mt-2 list-disc pl-5 space-y-1 text-red-600">
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
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setShowMyReports(false)}>
          <div className="bg-white rounded-2xl shadow-2xl border w-[680px] max-h-[80vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h3 className="text-sm font-semibold">我的举报记录</h3>
              <button onClick={() => setShowMyReports(false)} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-5 overflow-auto">
              {reportsLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> 加载中...</div>
              ) : myReports.length === 0 ? (
                <div className="text-sm text-muted-foreground">暂无举报记录</div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-left text-gray-600 border-b">
                    <tr>
                      <th className="py-2">提示词</th>
                      <th className="py-2">原因</th>
                      <th className="py-2">状态</th>
                      <th className="py-2">时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {myReports.map(r => (
                      <tr key={r.id} className="border-b last:border-0">
                        <td className="py-2 pr-2 text-gray-700">{r.prompt_name}</td>
                        <td className="py-2 pr-2 text-gray-600">{r.reason}</td>
                        <td className="py-2 pr-2">
                          <span className={cn('px-2 py-0.5 rounded text-xs', r.status === 'pending' ? 'bg-amber-50 text-amber-700' : r.status === 'resolved' ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-600')}>
                            {r.status === 'pending' ? '待处理' : r.status === 'resolved' ? '已处理' : '已驳回'}
                          </span>
                          {r.resolution_note && <div className="text-xs text-gray-500 mt-1">备注：{r.resolution_note}</div>}
                        </td>
                        <td className="py-2 text-xs text-gray-500">{r.created_at.slice(0, 19)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {previewPrompt && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setPreviewPrompt(null)}>
          <button
            onClick={() => setPreviewPrompt(null)}
            className="absolute top-4 right-4 z-10 p-2 rounded-full bg-white/10 text-white hover:bg-white/20"
          >
            <X className="h-5 w-5" />
          </button>

          <div
            className="grid max-h-[92vh] w-full max-w-6xl grid-cols-1 gap-4 overflow-auto lg:h-[92vh] lg:grid-cols-[minmax(0,1fr)_420px] lg:overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex h-[58vh] min-h-0 items-center justify-center overflow-hidden rounded-[28px] bg-black shadow-2xl lg:h-full">
              {previewPrompt.image_url ? (
                <img
                  src={previewPrompt.image_url}
                  alt={previewPrompt.title || '提示词图片'}
                  className="h-full w-full object-contain"
                />
              ) : (
                <div className="flex aspect-[3/4] w-full max-w-md items-center justify-center bg-slate-900 text-slate-500">
                  <ImageIcon className="h-10 w-10" />
                </div>
              )}
            </div>

            <aside className="min-h-0 overflow-hidden rounded-[28px] bg-white shadow-2xl">
              <div className="flex h-full flex-col">
                <div className="border-b border-slate-100 px-6 py-5">
                  <div className="mb-4 flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-slate-400">#{previewPrompt.id}</span>
                    {previewPrompt.category && (
                      <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-600">
                        {previewPrompt.category}
                      </span>
                    )}
                  </div>
                  <h2 className="text-xl font-bold leading-snug text-slate-950">{previewPrompt.title || previewPrompt.name || '未命名提示词'}</h2>
                  <p className="mt-3 line-clamp-3 text-sm leading-6 text-slate-500">{previewPrompt.chinese}</p>
                </div>

                <div className="flex-1 overflow-auto px-6 py-5">
                  <div className="mb-3 flex items-center justify-between">
                    <div className="text-xs font-bold uppercase tracking-[0.22em] text-indigo-500">Prompt</div>
                    <button
                      onClick={() => handleCopy(previewPrompt.chinese, `preview-cn-${previewPrompt.id}`)}
                      className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-600 hover:bg-indigo-100"
                    >
                      {copiedId === `preview-cn-${previewPrompt.id}` ? <><Check className="h-3.5 w-3.5" /> 已复制</> : <><Copy className="h-3.5 w-3.5" /> 复制中文</>}
                    </button>
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm leading-7 text-slate-700 whitespace-pre-wrap">
                    {previewPrompt.chinese}
                  </div>

                  {previewPrompt.english && (
                    <div className="mt-5">
                      <div className="mb-3 flex items-center justify-between">
                        <div className="text-xs font-bold uppercase tracking-[0.22em] text-slate-400">English</div>
                        <button
                          onClick={() => handleCopy(previewPrompt.english, `preview-en-${previewPrompt.id}`)}
                          className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-200"
                        >
                          {copiedId === `preview-en-${previewPrompt.id}` ? <><Check className="h-3.5 w-3.5 text-green-500" /> 已复制</> : <><Copy className="h-3.5 w-3.5" /> 复制英文</>}
                        </button>
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4 text-sm leading-7 text-slate-600 whitespace-pre-wrap">
                        {previewPrompt.english}
                      </div>
                    </div>
                  )}
                </div>

                <div className="border-t border-slate-100 px-6 py-4">
                  <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                    <span>作者：<b className="text-slate-800">{previewPrompt.created_by_name || '未知'}</b></span>
                    {previewPrompt.param_type && <span className="rounded-full bg-slate-100 px-2.5 py-1">{previewPrompt.param_type}</span>}
                  </div>
                </div>
              </div>
            </aside>
          </div>
        </div>
      )}
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
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl border w-[520px] max-h-[90vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h3 className="text-sm font-semibold">{title}</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4 overflow-y-auto">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">标题 <span className="text-red-500">*</span></label>
            <input value={form.title} onChange={e => patch('title', e.target.value)} className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">中文提示词 <span className="text-red-500">*</span></label>
            <textarea value={form.chinese} onChange={e => patch('chinese', e.target.value)} rows={3} className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">英文提示词</label>
            <textarea value={form.english} onChange={e => patch('english', e.target.value)} rows={3} className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">分类</label>
              <input value={form.category} onChange={e => patch('category', e.target.value)} className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">参数类型</label>
              <input value={form.param_type} onChange={e => patch('param_type', e.target.value)} className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">图片 URL</label>
            <div className="flex gap-2">
              <input value={form.image_url} onChange={e => patch('image_url', e.target.value)} placeholder="/uploads/prompts/xxx.png" className="flex-1 rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
              <label className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-xs cursor-pointer hover:bg-accent">
                <Upload className="h-3.5 w-3.5" />
                {uploading ? '上传中...' : '上传'}
                <input type="file" accept="image/*" className="hidden" onChange={handleUpload} />
              </label>
            </div>
            {form.image_url && (
              <div className="mt-2 aspect-[3/4] max-h-80 overflow-hidden rounded-xl border bg-slate-50 bg-[radial-gradient(circle_at_1px_1px,rgba(100,116,139,0.16)_1px,transparent_0)] [background-size:14px_14px] p-2 flex items-center justify-center">
                <img
                  src={form.image_url}
                  alt="提示词图片预览"
                  className="h-full w-full object-cover object-[center_68%] rounded-lg"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
              </div>
            )}
          </div>
        </div>
        <div className="flex gap-2 p-5 border-t">
          <button onClick={onClose} className="flex-1 rounded-lg border py-2 text-sm hover:bg-neutral-50 transition-colors">取消</button>
          <button onClick={onSubmit} disabled={loading} className="flex-1 rounded-lg bg-primary text-white py-2 text-sm hover:bg-primary/90 transition-colors disabled:opacity-50">
            {loading ? '处理中...' : submitText}
          </button>
        </div>
      </div>
    </div>
  );
}
