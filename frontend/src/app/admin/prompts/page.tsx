'use client';

import { useState, useEffect, useCallback } from 'react';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';
import {
  Plus, Search, Edit2, Trash2, X, Upload, Loader2, BookOpen,
} from 'lucide-react';

/* ============================================================
   Types
   ============================================================ */

interface Category {
  id: number;
  name: string;
  start_intro: string | null;
  sort_order: number;
  example_count: number;
  created_at: string;
}

interface Example {
  id: number;
  category_id: number;
  category_name: string;
  param_type: string;
  image_num: number;
  image_url: string | null;
  name: string | null;
  chinese_example: string;
  english_example: string;
  ul_list: string[];
  sort_order: number;
  is_public: boolean;
  created_by: number | null;
  created_by_name: string | null;
  created_at: string;
}

interface ReportItem {
  id: number;
  prompt_id: number;
  prompt_name: string;
  prompt_text: string;
  reason: string;
  details: string | null;
  status: string;
  reporter_id: number;
  reporter_name: string;
  created_at: string;
  resolved_at: string | null;
  resolution_note: string | null;
}

interface AuditItem {
  id: number;
  prompt_id: number;
  prompt_name: string;
  action: string;
  operator_id: number | null;
  operator_name: string | null;
  details: string | null;
  created_at: string;
}

interface PromptOverview {
  total_categories: number;
  total_examples: number;
  public_examples: number;
  private_examples: number;
  with_image_examples: number;
  pending_reports: number;
}

/* ============================================================
   MAIN PAGE
   ============================================================ */

export default function AdminPromptsPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [examples, setExamples] = useState<Example[]>([]);
  const [totalExamples, setTotalExamples] = useState(0);
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [reportTotal, setReportTotal] = useState(0);
  const [overview, setOverview] = useState<PromptOverview | null>(null);
  const [reportPage, setReportPage] = useState(1);
  const [reportStatus, setReportStatus] = useState<string>('');
  const [processingReportId, setProcessingReportId] = useState<number | null>(null);
  const [selectedReportIds, setSelectedReportIds] = useState<Set<number>>(new Set());
  const [reportStats, setReportStats] = useState<{ total: number; pending: number; resolved: number; rejected: number; by_reason: Array<{ reason: string; count: number }> } | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditItem[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditAction, setAuditAction] = useState('');
  const [auditOperator, setAuditOperator] = useState('');
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'categories' | 'examples' | 'reports' | 'audit'>('examples');
  const [catSearch, setCatSearch] = useState('');
  const [exSearch, setExSearch] = useState('');
  const [exPage, setExPage] = useState(1);
  const [catFilter, setCatFilter] = useState<number | undefined>(undefined);

  // Modals
  const [showCatModal, setShowCatModal] = useState(false);
  const [editingCat, setEditingCat] = useState<Category | null>(null);
  const [showExModal, setShowExModal] = useState(false);
  const [editingEx, setEditingEx] = useState<Example | null>(null);


  const fetchCategories = useCallback(async () => {
    try {
      const res = await adminApi.getPromptCategories(1, 200, catSearch || undefined);
      setCategories(res.data.items);
    } catch (e: unknown) {
      console.error(e);
    }
  }, [catSearch]);

  const fetchOverview = useCallback(async () => {
    try {
      const res = await adminApi.getPromptOverview();
      setOverview(res.data);
    } catch (e: unknown) {
      console.error(e);
    }
  }, []);

  const fetchExamples = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminApi.getPromptExamples(exPage, 50, catFilter, undefined, exSearch || undefined);
      setExamples(res.data.items);
      setTotalExamples(res.data.total);
    } catch (e: unknown) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [exPage, catFilter, exSearch]);

  const fetchReports = useCallback(async () => {
    setLoading(true);
    try {
      const [res, statsRes] = await Promise.all([
        adminApi.getPromptReports(reportPage, 20, reportStatus || undefined),
        adminApi.getPromptReportStats(),
      ]);
      setReports(res.data.items);
      setReportTotal(res.data.total);
      setReportStats(statsRes.data);
    } catch (e: unknown) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [reportPage, reportStatus]);

  const fetchAuditLogs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminApi.getPromptAuditLogs(auditPage, 20, auditAction || undefined, auditOperator || undefined);
      setAuditLogs(res.data.items);
      setAuditTotal(res.data.total);
    } catch (e: unknown) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [auditPage, auditAction, auditOperator]);

  useEffect(() => { fetchCategories(); fetchOverview(); }, [fetchCategories, fetchOverview]);
  useEffect(() => { if (activeTab === 'examples' || activeTab === 'categories') fetchExamples(); }, [fetchExamples, activeTab]);
  useEffect(() => { if (activeTab === 'reports') fetchReports(); }, [fetchReports, activeTab]);
  useEffect(() => { if (activeTab === 'audit') fetchAuditLogs(); }, [fetchAuditLogs, activeTab]);

  const handleDeleteCategory = async (id: number, name: string) => {
    if (!confirm(`确定删除分类「${name}」？该分类下的所有示例也会被删除。`)) return;
    try {
      await adminApi.deletePromptCategory(id);
      toast.success('已删除');
      fetchCategories();
      fetchExamples();
      fetchOverview();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    }
  };

  const handleDeleteExample = async (id: number) => {
    if (!confirm('确定删除此提示词示例吗？')) return;
    try {
      await adminApi.deletePromptExample(id);
      toast.success('已删除');
      fetchExamples();
      fetchCategories();
      fetchOverview();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    }
  };

  const handleResolveReport = async (report: ReportItem, action: 'hide' | 'reject') => {
    const note = window.prompt(action === 'hide' ? '处理备注（可选）：' : '驳回备注（可选）：') || '';
    setProcessingReportId(report.id);
    try {
      await adminApi.resolvePromptReport(report.id, { action, note: note || undefined });
      toast.success('处理成功');
      fetchReports();
      fetchExamples();
      fetchOverview();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '处理失败');
    } finally {
      setProcessingReportId(null);
    }
  };

  const toggleReportSelect = (id: number) => {
    setSelectedReportIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleBatchResolve = async (action: 'hide' | 'reject') => {
    if (selectedReportIds.size === 0) {
      toast.error('请先选择待处理举报');
      return;
    }
    const ok = window.confirm(action === 'hide'
      ? `确认下架所选 ${selectedReportIds.size} 条举报对应的提示词？`
      : `确认驳回所选 ${selectedReportIds.size} 条举报？`);
    if (!ok) return;
    const note = window.prompt('批量处理备注（可选）：') || '';
    try {
      await adminApi.batchResolvePromptReports({
        report_ids: Array.from(selectedReportIds),
        action,
        note: note || undefined,
      });
      toast.success('批量处理成功');
      setSelectedReportIds(new Set());
      fetchReports();
      fetchExamples();
      fetchOverview();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '批量处理失败');
    }
  };

  /* ============================================================
   Render
   ============================================================ */

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BookOpen className="h-5 w-5 text-indigo-600" />
          <h2 className="text-lg font-semibold">提示词管理</h2>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => { setEditingCat(null); setShowCatModal(true); }}
            className="flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors">
            <Plus className="h-4 w-4" /> 新建分类
          </button>
          <button onClick={() => { setEditingEx(null); setShowExModal(true); }}
            className="flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border hover:bg-gray-50 transition-colors">
            <Plus className="h-4 w-4" /> 新建示例
          </button>
        </div>
      </div>

      <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
        <StatCard label="分类数" value={overview?.total_categories ?? categories.length} />
        <StatCard label="示例总数" value={overview?.total_examples ?? totalExamples} />
        <StatCard label="公开示例" value={overview?.public_examples ?? 0} />
        <StatCard label="私有示例" value={overview?.private_examples ?? 0} />
        <StatCard label="带图示例" value={overview?.with_image_examples ?? 0} />
        <StatCard label="待处理举报" value={overview?.pending_reports ?? 0} highlight />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5 w-fit">
        <button onClick={() => setActiveTab('categories')}
          className={cn('px-4 py-1.5 text-sm font-medium rounded-md transition-colors',
            activeTab === 'categories' ? 'bg-white shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground')}>
          分类管理
        </button>
        <button onClick={() => setActiveTab('examples')}
          className={cn('px-4 py-1.5 text-sm font-medium rounded-md transition-colors',
            activeTab === 'examples' ? 'bg-white shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground')}>
          示例管理
          <span className="ml-1 text-xs text-muted-foreground">({totalExamples})</span>
        </button>
        <button onClick={() => setActiveTab('reports')}
          className={cn('px-4 py-1.5 text-sm font-medium rounded-md transition-colors',
            activeTab === 'reports' ? 'bg-white shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground')}>
          举报审核
          <span className="ml-1 text-xs text-muted-foreground">({reportTotal})</span>
        </button>
        <button onClick={() => setActiveTab('audit')}
          className={cn('px-4 py-1.5 text-sm font-medium rounded-md transition-colors',
            activeTab === 'audit' ? 'bg-white shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground')}>
          审核日志
          <span className="ml-1 text-xs text-muted-foreground">({auditTotal})</span>
        </button>
      </div>

      {/* Categories tab */}
      {activeTab === 'categories' && (
        <div>
          <div className="flex gap-3 mb-3">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input className="w-full pl-9 pr-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="搜索分类..." value={catSearch} onChange={e => setCatSearch(e.target.value)} />
            </div>
          </div>

          {categories.length === 0 ? (
            <div className="text-center py-20 text-gray-400">暂无分类，点击「新建分类」创建</div>
          ) : (
            <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">ID</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">分类名称</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">简介</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">示例数</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">排序</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">创建时间</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {categories.map(c => (
                    <tr key={c.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-500">{c.id}</td>
                      <td className="px-4 py-3 font-medium">{c.name}</td>
                      <td className="px-4 py-3 text-gray-500 max-w-[200px] truncate">{c.start_intro || '-'}</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded text-xs bg-indigo-50 text-indigo-600">{c.example_count}</span>
                      </td>
                      <td className="px-4 py-3">{c.sort_order}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{c.created_at?.slice(0, 19)}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button onClick={() => { setEditingCat(c); setShowCatModal(true); }}
                            className="text-xs text-blue-600 hover:underline flex items-center gap-1">
                            <Edit2 className="h-3 w-3" /> 编辑
                          </button>
                          <button onClick={() => handleDeleteCategory(c.id, c.name)}
                            className="text-xs text-red-600 hover:underline flex items-center gap-1">
                            <Trash2 className="h-3 w-3" /> 删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Examples tab */}
      {activeTab === 'examples' && (
        <div>
          <div className="flex gap-3 mb-3 flex-wrap">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input className="w-full pl-9 pr-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="搜索提示词..." value={exSearch} onChange={e => setExSearch(e.target.value)} />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-500">分类:</label>
              <select className="w-40 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                value={catFilter ?? ''} onChange={e => setCatFilter(e.target.value ? Number(e.target.value) : undefined)}>
                <option value="">全部分类</option>
                {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              {catFilter && (
                <button className="text-sm text-indigo-600 hover:underline" onClick={() => setCatFilter(undefined)}>清除</button>
              )}
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground mr-2" />
              <span className="text-sm text-muted-foreground">加载中...</span>
            </div>
          ) : examples.length === 0 ? (
            <div className="text-center py-20 text-gray-400">暂无示例，点击「新建示例」创建</div>
          ) : (
            <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">ID</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">分类</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">类型</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">中文提示词</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">图片</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">状态</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {examples.map(ex => (
                    <tr key={ex.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-500">{ex.id}</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded text-xs bg-indigo-50 text-indigo-600">{ex.category_name}</span>
                      </td>
                      <td className="px-4 py-3 text-gray-600">{ex.param_type}</td>
                      <td className="px-4 py-3 text-gray-500 max-w-[300px] truncate">{ex.chinese_example}</td>
                      <td className="px-4 py-3">
                        {ex.image_url ? (
                          <div className="h-16 w-12 rounded-lg overflow-hidden border bg-slate-50 bg-[radial-gradient(circle_at_1px_1px,rgba(100,116,139,0.16)_1px,transparent_0)] [background-size:10px_10px]">
                            <img src={ex.image_url} alt="" className="w-full h-full object-cover object-[center_68%] rounded"
                              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />
                          </div>
                        ) : (
                          <span className="text-gray-400 text-xs">无</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn('px-2 py-0.5 rounded text-xs', ex.is_public ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-600')}>
                          {ex.is_public ? '公开' : '隐藏'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button onClick={() => { setEditingEx(ex); setShowExModal(true); }}
                            className="text-xs text-blue-600 hover:underline flex items-center gap-1">
                            <Edit2 className="h-3 w-3" />
                          </button>
                          <button onClick={() => handleDeleteExample(ex.id)}
                            className="text-xs text-red-600 hover:underline flex items-center gap-1">
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Pagination */}
              {totalExamples > 50 && (
                <div className="flex items-center justify-between border-t px-4 py-3">
                  <span className="text-xs text-gray-500">第 {exPage} 页 / 共 {Math.ceil(totalExamples / 50)} 页</span>
                  <div className="flex gap-2">
                    <button disabled={exPage <= 1} onClick={() => setExPage(p => p - 1)}
                      className="px-3 py-1 text-xs rounded-md border disabled:opacity-40 hover:bg-gray-50">上一页</button>
                    <button disabled={exPage * 50 >= totalExamples} onClick={() => setExPage(p => p + 1)}
                      className="px-3 py-1 text-xs rounded-md border disabled:opacity-40 hover:bg-gray-50">下一页</button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {activeTab === 'reports' && (
        <div>
          {reportStats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
              <div className="rounded-lg border bg-white p-3"><div className="text-xs text-gray-500">总举报</div><div className="text-lg font-semibold">{reportStats.total}</div></div>
              <div className="rounded-lg border bg-white p-3"><div className="text-xs text-gray-500">待处理</div><div className="text-lg font-semibold text-amber-700">{reportStats.pending}</div></div>
              <div className="rounded-lg border bg-white p-3"><div className="text-xs text-gray-500">已下架</div><div className="text-lg font-semibold text-green-700">{reportStats.resolved}</div></div>
              <div className="rounded-lg border bg-white p-3"><div className="text-xs text-gray-500">已驳回</div><div className="text-lg font-semibold text-gray-700">{reportStats.rejected}</div></div>
            </div>
          )}
          <div className="flex items-center gap-2 mb-3">
            <label className="text-sm text-gray-500">状态:</label>
            <select
              className="w-40 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              value={reportStatus}
              onChange={e => { setReportStatus(e.target.value); setReportPage(1); }}
            >
              <option value="">全部</option>
              <option value="pending">待处理</option>
              <option value="resolved">已下架</option>
              <option value="rejected">已驳回</option>
            </select>
            <button onClick={() => handleBatchResolve('hide')} className="px-3 py-2 text-xs rounded-lg border hover:bg-red-50 text-red-600">批量下架</button>
            <button onClick={() => handleBatchResolve('reject')} className="px-3 py-2 text-xs rounded-lg border hover:bg-gray-50">批量驳回</button>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground mr-2" />
              <span className="text-sm text-muted-foreground">加载中...</span>
            </div>
          ) : reports.length === 0 ? (
            <div className="text-center py-20 text-gray-400">暂无举报记录</div>
          ) : (
            <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">选择</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">ID</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">提示词</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">举报原因</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">举报人</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">状态</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">时间</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {reports.map(r => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3">
                        {r.status === 'pending' ? (
                          <input type="checkbox" checked={selectedReportIds.has(r.id)} onChange={() => toggleReportSelect(r.id)} className="rounded" />
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-gray-500">{r.id}</td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-gray-800">{r.prompt_name}</div>
                        <div className="text-xs text-gray-500 max-w-[240px] truncate">{r.prompt_text}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-gray-700">{r.reason}</div>
                        {r.details && <div className="text-xs text-gray-500 max-w-[220px] truncate">{r.details}</div>}
                      </td>
                      <td className="px-4 py-3 text-gray-600">{r.reporter_name}</td>
                      <td className="px-4 py-3">
                        <span className={cn('px-2 py-0.5 rounded text-xs', r.status === 'pending' ? 'bg-amber-50 text-amber-700' : r.status === 'resolved' ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-600')}>
                          {r.status === 'pending' ? '待处理' : r.status === 'resolved' ? '已下架' : '已驳回'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500">{r.created_at?.slice(0, 19)}</td>
                      <td className="px-4 py-3 text-right">
                        {r.status === 'pending' ? (
                          <div className="flex items-center justify-end gap-2">
                            <button
                              disabled={processingReportId === r.id}
                              onClick={() => handleResolveReport(r, 'hide')}
                              className="text-xs text-red-600 hover:underline disabled:opacity-50"
                            >
                              下架提示词
                            </button>
                            <button
                              disabled={processingReportId === r.id}
                              onClick={() => handleResolveReport(r, 'reject')}
                              className="text-xs text-gray-600 hover:underline disabled:opacity-50"
                            >
                              驳回举报
                            </button>
                          </div>
                        ) : (
                          <span className="text-xs text-gray-400">已处理</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'audit' && (
        <div>
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <label className="text-sm text-gray-500">动作:</label>
            <select
              className="w-40 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              value={auditAction}
              onChange={e => { setAuditAction(e.target.value); setAuditPage(1); }}
            >
              <option value="">全部</option>
              <option value="report">举报</option>
              <option value="hide">下架</option>
              <option value="show">公开</option>
              <option value="reject_report">驳回举报</option>
              <option value="delete">删除</option>
            </select>
            <input
              value={auditOperator}
              onChange={e => { setAuditOperator(e.target.value); setAuditPage(1); }}
              placeholder="按操作人筛选"
              className="w-48 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground mr-2" />
              <span className="text-sm text-muted-foreground">加载中...</span>
            </div>
          ) : auditLogs.length === 0 ? (
            <div className="text-center py-20 text-gray-400">暂无审核日志</div>
          ) : (
            <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">ID</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">提示词</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">动作</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">操作人</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">详情</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">时间</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {auditLogs.map(log => (
                    <tr key={log.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-500">{log.id}</td>
                      <td className="px-4 py-3 text-gray-700">{log.prompt_name}</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700">{log.action}</span>
                      </td>
                      <td className="px-4 py-3 text-gray-600">{log.operator_name || '-'}</td>
                      <td className="px-4 py-3 text-xs text-gray-500 max-w-[280px] truncate">{log.details || '-'}</td>
                      <td className="px-4 py-3 text-xs text-gray-500">{log.created_at?.slice(0, 19)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Modals */}
      {showCatModal && (
        <CatModal category={editingCat}
          onClose={() => { setShowCatModal(false); setEditingCat(null); }}
          onSaved={() => { setShowCatModal(false); setEditingCat(null); fetchCategories(); fetchExamples(); fetchOverview(); }} />
      )}
      {showExModal && (
        <ExModal example={editingEx} categories={categories}
          onClose={() => { setShowExModal(false); setEditingEx(null); }}
          onSaved={() => { setShowExModal(false); setEditingEx(null); fetchExamples(); fetchCategories(); fetchOverview(); }} />
      )}
    </div>
  );
}

function StatCard({ label, value, highlight = false }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className={cn(
      'rounded-xl border bg-white p-3 shadow-sm',
      highlight && 'border-amber-300 bg-amber-50/50',
    )}>
      <div className="text-xs text-gray-500">{label}</div>
      <div className={cn('mt-1 text-xl font-semibold text-gray-900', highlight && 'text-amber-700')}>{value}</div>
    </div>
  );
}

/* ============================================================
   Category Modal
   ============================================================ */

function CatModal({ category, onClose, onSaved }: {
  category: Category | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(category?.name || '');
  const [intro, setIntro] = useState(category?.start_intro || '');
  const [sortOrder, setSortOrder] = useState(category?.sort_order || 0);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!name.trim()) { toast.error('名称不能为空'); return; }
    setSaving(true);
    try {
      if (category) {
        await adminApi.updatePromptCategory(category.id, { name, start_intro: intro, sort_order: sortOrder });
        toast.success('更新成功');
      } else {
        await adminApi.createPromptCategory({ name, start_intro: intro, sort_order: sortOrder });
        toast.success('创建成功');
      }
      onSaved();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '保存失败');
    } finally { setSaving(false); };
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl border w-[460px] overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h3 className="text-sm font-semibold">{category ? '编辑分类' : '新建分类'}</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">分类名称 <span className="text-red-500">*</span></label>
            <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="如：游戏行业提示词"
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">简介（可选）</label>
            <textarea value={intro} onChange={e => setIntro(e.target.value)} rows={3}
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">排序（数字越小越靠前）</label>
            <input type="number" value={sortOrder} onChange={e => setSortOrder(Number(e.target.value))}
              className="w-24 rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          </div>
        </div>
        <div className="flex gap-2 p-5 border-t">
          <button onClick={onClose} disabled={saving} className="flex-1 rounded-lg border py-2 text-sm hover:bg-neutral-50 transition-colors disabled:opacity-50">取消</button>
          <button onClick={handleSave} disabled={saving || !name.trim()}
            className="flex-1 rounded-lg bg-indigo-600 text-white py-2 text-sm hover:bg-indigo-700 transition-colors disabled:opacity-50">
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   Example Modal
   ============================================================ */

function ExModal({ example, categories, onClose, onSaved }: {
  example: Example | null;
  categories: Category[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [categoryId, setCategoryId] = useState(example?.category_id || categories[0]?.id || 0);
  const [paramType, setParamType] = useState(example?.param_type || '');
  const [chinese, setChinese] = useState(example?.chinese_example || '');
  const [english, setEnglish] = useState(example?.english_example || '');
  const [imageUrl, setImageUrl] = useState(example?.image_url || '');
  const [name, setName] = useState(example?.name || '');
  const [sortOrder, setSortOrder] = useState(example?.sort_order || 0);
  const [isPublic, setIsPublic] = useState(example?.is_public ?? true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);

  const handleSave = async () => {
    if (!categoryId || !paramType.trim() || !chinese.trim()) { toast.error('分类、类型和中文提示词不能为空'); return; }
    setSaving(true);
    try {
      const data = {
        category_id: categoryId,
        param_type: paramType,
        chinese_example: chinese,
        english_example: english,
        image_url: imageUrl || undefined,
        name: name || undefined,
        sort_order: sortOrder,
        is_public: isPublic,
      };
      if (example) {
        await adminApi.updatePromptExample(example.id, data);
        toast.success('更新成功');
      } else {
        await adminApi.createPromptExample(data);
        toast.success('创建成功');
      }
      onSaved();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '保存失败');
    } finally { setSaving(false); }
  };

  const handleUploadImage = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await adminApi.uploadPromptImage(file);
      setImageUrl(res.data.url);
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
      <div className="bg-white rounded-2xl shadow-2xl border w-[540px] overflow-hidden flex flex-col max-h-[85vh]" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h3 className="text-sm font-semibold">{example ? '编辑示例' : '新建示例'}</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4 overflow-auto flex-1">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">分类 <span className="text-red-500">*</span></label>
              <select value={categoryId} onChange={e => setCategoryId(Number(e.target.value))}
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
                {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">参数类型 <span className="text-red-500">*</span></label>
              <input type="text" value={paramType} onChange={e => setParamType(e.target.value)} placeholder="如：角色设计"
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">示例名称（可选）</label>
            <input type="text" value={name} onChange={e => setName(e.target.value)}
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">中文提示词 <span className="text-red-500">*</span></label>
            <textarea value={chinese} onChange={e => setChinese(e.target.value)} rows={3}
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">英文提示词</label>
            <textarea value={english} onChange={e => setEnglish(e.target.value)} rows={3}
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">图片URL</label>
            <div className="flex gap-2">
              <input type="text" value={imageUrl} onChange={e => setImageUrl(e.target.value)} placeholder="/uploads/prompts/xxx.png"
                className="flex-1 rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
              <label className="px-3 py-2 border rounded-lg text-sm text-muted-foreground hover:bg-gray-50 flex items-center gap-1 cursor-pointer">
                <Upload className="h-3.5 w-3.5" /> {uploading ? '上传中...' : '上传'}
                <input type="file" accept="image/*" className="hidden" onChange={handleUploadImage} />
              </label>
            </div>
            {imageUrl && (
              <div className="mt-2 aspect-[3/4] max-h-80 rounded-xl overflow-hidden border bg-slate-50 bg-[radial-gradient(circle_at_1px_1px,rgba(100,116,139,0.16)_1px,transparent_0)] [background-size:14px_14px] p-2 flex items-center justify-center">
                <img src={imageUrl} alt="" className="w-full h-full object-cover object-[center_68%] rounded-lg"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />
              </div>
            )}
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">排序</label>
            <input type="number" value={sortOrder} onChange={e => setSortOrder(Number(e.target.value))}
              className="w-24 rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          </div>
          <div className="flex items-center gap-2">
            <input id="is_public" type="checkbox" checked={isPublic} onChange={e => setIsPublic(e.target.checked)} className="rounded" />
            <label htmlFor="is_public" className="text-sm text-muted-foreground">公开到社区（关闭后前台用户不可见）</label>
          </div>
        </div>
        <div className="flex gap-2 p-5 border-t shrink-0">
          <button onClick={onClose} disabled={saving} className="flex-1 rounded-lg border py-2 text-sm hover:bg-neutral-50 transition-colors disabled:opacity-50">取消</button>
          <button onClick={handleSave} disabled={saving}
            className="flex-1 rounded-lg bg-indigo-600 text-white py-2 text-sm hover:bg-indigo-700 transition-colors disabled:opacity-50">
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}
