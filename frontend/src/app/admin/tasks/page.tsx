'use client';

import { useState, useEffect, useRef } from 'react';
import {
  adminApi,
  type DurableJobDetail as DurableJobDetailData,
  type DurableJobListResponse,
} from '@/services/adminApi';
import { formatLocalDateTime } from '@/lib/dateTime';
import { toast } from '@/lib/toast';
import { 
  Activity, Bot, Workflow, Search, Trash2, ShieldCheck,
  ChevronLeft, ChevronRight, AlertCircle, Eye, X
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { DurableJobDetail } from '@/components/admin/DurableJobDetail';

const DURABLE_STATUS_LABELS: Record<string, string> = {
  queued: '等待领取',
  leased: '已领取',
  running: '执行中',
  retry_wait: '等待重试',
  waiting_review: '待人工核验',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  dead_letter: '死信',
};

const DURABLE_JOB_LABELS: Record<string, string> = {
  ai_image_generation: 'AI 生图',
  xhs_homepage_sync: '主页帖子同步',
  xhs_engagement_sync: '创作中心主同步',
  xhs_note_detail_sync: '帖子详情同步',
  xhs_report_refresh: '投流报表刷新',
  dify_workflow: '工作流执行',
  report_refresh: '报表刷新',
};

function getAiProviderLabel(item: {
  provider_name?: string | null;
  provider_kind?: string | null;
  model_name?: string;
}) {
  if (item.provider_name) {
    return item.provider_name;
  }
  if (item.model_name === 'gptimage2') {
    return 'GPT Image 2 直连适配器';
  }
  return '-';
}

export default function GlobalTasksPage() {
  const [activeTab, setActiveTab] = useState<'durable' | 'workflow' | 'ai'>('durable');
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [username, setUsername] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [jobType, setJobType] = useState('');
  const [workerType, setWorkerType] = useState('');
  const [durableSummary, setDurableSummary] = useState<DurableJobListResponse['summary'] | null>(null);
  const [durableFilters, setDurableFilters] = useState<DurableJobListResponse['filters']>({ job_types: [], worker_types: [] });
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedTask, setSelectedTask] = useState<any | null>(null);
  const listRequestSequence = useRef(0);
  const detailRequestSequence = useRef(0);

  const openDetail = async (id: number) => {
    const requestId = ++detailRequestSequence.current;
    setDetailLoading(true);
    setDetailOpen(true);
    try {
      const res = activeTab === 'durable'
        ? await adminApi.getDurableJobDetail(id)
        : activeTab === 'workflow'
          ? await adminApi.getWorkflowTaskDetail(id)
          : await adminApi.getAiTaskDetail(id);
      if (requestId !== detailRequestSequence.current) return;
      setSelectedTask(res.data);
    } catch (e: any) {
      if (requestId !== detailRequestSequence.current) return;
      toast.error(e.message || '获取详情失败');
      setDetailOpen(false);
      setSelectedTask(null);
    } finally {
      if (requestId === detailRequestSequence.current) setDetailLoading(false);
    }
  };

  const fetchData = async () => {
    const requestId = ++listRequestSequence.current;
    setLoading(true);
    try {
      if (activeTab === 'durable') {
        const res = await adminApi.getDurableJobs({
          page,
          limit: 15,
          username: username || undefined,
          search: search || undefined,
          status: status || undefined,
          job_type: jobType || undefined,
          worker_type: workerType || undefined,
        });
        if (requestId !== listRequestSequence.current) return;
        const items = (res.data.items || []).map((item) => ({
          ...item,
          username: item.display_name || item.username || '系统任务',
          user_id: item.requested_by_user_id,
        }));
        setData(items);
        setTotal(res.data.total);
        setDurableSummary(res.data.summary);
        setDurableFilters(res.data.filters);
      } else if (activeTab === 'workflow') {
        const res = await adminApi.getAdminDifyTasks(
          page,
          15,
          username || undefined,
          undefined,
          status || undefined,
        );
        if (requestId !== listRequestSequence.current) return;
        const items = (res.data.items || []).map((item) => ({
          ...item,
          username: item.user_name || '-',
          workflow_name: item.workflow_name || `#${item.workflow_id}`,
        }));
        setData(items);
        setTotal(res.data.total);
      } else {
        const res = await adminApi.getAiTasks({ page, limit: 15, username, status });
        if (requestId !== listRequestSequence.current) return;
        const items = (res.data.items || []).map((item) => ({
          ...item,
          username: item.username || '-',
        }));
        setData(items);
        setTotal(res.data.total);
      }
    } catch (e: any) {
      if (requestId !== listRequestSequence.current) return;
      toast.error(e.message || '获取数据失败');
    } finally {
      if (requestId === listRequestSequence.current) setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [activeTab, page, status, jobType, workerType]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (page === 1) {
      fetchData();
    } else {
      setPage(1);
    }
  };

  const switchTab = (tab: 'durable' | 'workflow' | 'ai') => {
    listRequestSequence.current += 1;
    detailRequestSequence.current += 1;
    setActiveTab(tab);
    setPage(1);
    setStatus('');
    setJobType('');
    setWorkerType('');
    setSelectedTask(null);
    setDetailOpen(false);
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除此任务记录吗？')) return;
    try {
      if (activeTab === 'workflow') {
        const target = data.find((item) => item.id === id);
        if (target && ['running', 'pending', 'queued'].includes(target.status)) {
          toast.error('执行中的任务不允许删除');
          return;
        }
        await adminApi.deleteAdminDifyTask(id);
      } else {
        // AI task deletion endpoint might need to be added or used from common resources
        // For now just alert or implementation if exists
        toast.error('AI 任务暂不支持从此处直接删除');
        return;
      }
      toast.success('已删除');
      fetchData();
    } catch (e: any) {
      toast.error(e.message || '删除失败');
    }
  };

  const handleFail = async (id: number) => {
    if (!confirm('确定要手动终止这个任务，并将状态标记为失败吗？')) return;
    try {
      if (activeTab === 'workflow') {
        await adminApi.failAdminDifyTask(id, '管理员手动终止任务');
      } else {
        await adminApi.failAiTask(id, '管理员手动终止任务');
      }
      toast.success('任务已终止并标记失败');
      if (detailOpen && selectedTask?.id === id) {
        await openDetail(id);
      }
      fetchData();
    } catch (e: any) {
      toast.error(e.message || '终止任务失败');
    }
  };

  return (
    <div className="p-8 max-w-[1500px] mx-auto space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Activity className="h-6 w-6 text-indigo-500" />
            任务中心
          </h1>
          <p className="text-sm text-gray-500 mt-1">统一查看可靠任务、AI 生图和工作流执行记录；可靠任务页签提供状态、分片、执行尝试与事件证据。</p>
        </div>

        <div className="flex bg-gray-100 p-1 rounded-xl">
          <button
            onClick={() => switchTab('durable')}
            className={cn(
              "px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2",
              activeTab === 'durable' ? "bg-white text-emerald-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
            )}
          >
            <ShieldCheck className="h-4 w-4" />
            可靠任务
          </button>
          <button
            onClick={() => switchTab('workflow')}
            className={cn(
              "px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2",
              activeTab === 'workflow' ? "bg-white text-indigo-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
            )}
          >
            <Workflow className="h-4 w-4" />
            工作流任务
          </button>
          <button
            onClick={() => switchTab('ai')}
            className={cn(
              "px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2",
              activeTab === 'ai' ? "bg-white text-indigo-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
            )}
          >
            <Bot className="h-4 w-4" />
            AI 生图任务
          </button>
        </div>
      </div>

      {activeTab === 'durable' && durableSummary && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[
            { label: '统一任务总数', value: durableSummary.total, tone: 'text-slate-950', note: '当前类型与用户筛选范围' },
            { label: '正在流转', value: durableSummary.active, tone: 'text-blue-700', note: '等待 / 领取 / 执行 / 重试' },
            { label: '需要关注', value: durableSummary.attention, tone: 'text-orange-700', note: '待核验与死信' },
            { label: '已完成', value: durableSummary.status_counts.succeeded, tone: 'text-emerald-700', note: '终态成功任务' },
          ].map((item) => (
            <div key={item.label} className="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
              <div className="text-xs font-medium text-slate-500">{item.label}</div>
              <div className={cn('mt-2 text-2xl font-bold tracking-tight', item.tone)}>{item.value.toLocaleString()}</div>
              <div className="mt-1 text-[11px] text-slate-400">{item.note}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="bg-white p-4 rounded-xl border shadow-sm flex flex-wrap items-center gap-4">
        <form onSubmit={handleSearch} className="flex flex-1 flex-wrap gap-3 min-w-[280px]">
          {activeTab === 'durable' && (
            <div className="relative min-w-[260px] flex-[1.4]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                type="text"
                placeholder="任务 ID / 来源 ID / 错误码"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-600 outline-none transition-all"
              />
            </div>
          )}
          <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="按用户名或显示名搜索"
            value={username}
            onChange={e => setUsername(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none transition-all"
          />
          </div>
          <button type="submit" className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-700">查询</button>
        </form>

        <select
          value={status}
          onChange={e => { setStatus(e.target.value); setPage(1); }}
          className="px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all"
        >
          <option value="">所有状态</option>
          {activeTab === 'durable' ? (
            <>
              <option value="queued">等待领取</option>
              <option value="leased">已领取</option>
              <option value="running">执行中</option>
              <option value="retry_wait">等待重试</option>
              <option value="waiting_review">待人工核验</option>
              <option value="succeeded">已完成</option>
              <option value="failed">失败</option>
              <option value="cancelled">已取消</option>
              <option value="dead_letter">死信</option>
            </>
          ) : activeTab === 'workflow' ? (
            <>
              <option value="queued">排队中</option>
              <option value="pending">排队中</option>
              <option value="running">运行中</option>
              <option value="succeeded">成功</option>
              <option value="failed">失败</option>
            </>
          ) : (
            <>
              <option value="pending">排队中</option>
              <option value="processing">处理中</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
            </>
          )}
        </select>

        {activeTab === 'durable' && (
          <>
            <select
              value={jobType}
              onChange={e => { setJobType(e.target.value); setPage(1); }}
              className="px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500/20 outline-none transition-all"
            >
              <option value="">所有任务类型</option>
              {durableFilters.job_types.map(value => <option key={value} value={value}>{DURABLE_JOB_LABELS[value] || value}</option>)}
            </select>
            <select
              value={workerType}
              onChange={e => { setWorkerType(e.target.value); setPage(1); }}
              className="px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-emerald-500/20 outline-none transition-all"
            >
              <option value="">所有执行器</option>
              {durableFilters.worker_types.map(value => <option key={value} value={value}>{value}</option>)}
            </select>
          </>
        )}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-6 py-4 font-semibold text-gray-700">任务 ID</th>
                <th className="px-6 py-4 font-semibold text-gray-700">用户</th>
                <th className="px-6 py-4 font-semibold text-gray-700">
                  {activeTab === 'durable' ? '任务类型 / 执行器' : activeTab === 'workflow' ? '工作流名称' : '模型'}
                </th>
                {activeTab === 'ai' && (
                  <th className="px-6 py-4 font-semibold text-gray-700">生图入口</th>
                )}
                <th className="px-6 py-4 font-semibold text-gray-700">状态</th>
                <th className="px-6 py-4 font-semibold text-gray-700">创建时间</th>
                <th className="px-6 py-4 font-semibold text-gray-700 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    <td colSpan={activeTab === 'ai' ? 7 : 6} className="px-6 py-4"><div className="h-4 bg-gray-100 rounded w-full"></div></td>
                  </tr>
                ))
              ) : data.length > 0 ? (
                data.map((item) => (
                  <tr key={item.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4 font-mono text-xs text-gray-500">
                      <div>#{item.id}</div>
                      {activeTab === 'durable' && <div className="mt-1 max-w-[140px] truncate text-[10px] text-gray-300" title={item.public_id}>{item.public_id}</div>}
                    </td>
                    <td className="px-6 py-4">
                      <div className="font-medium text-gray-900">{item.username}</div>
                      <div className="text-[10px] text-gray-400">UID: {item.user_id ?? '-'}</div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-gray-700 font-medium">
                        {activeTab === 'durable' ? (DURABLE_JOB_LABELS[item.job_type] || item.job_type) : activeTab === 'workflow' ? item.workflow_name : item.model_name}
                      </div>
                      {activeTab === 'durable' && (
                        <div className="mt-1 text-[10px] text-gray-400">{item.worker_type} · {item.current_step || '尚未开始'}</div>
                      )}
                    </td>
                    {activeTab === 'ai' && (
                      <td className="px-6 py-4">
                        <div className="text-gray-700 font-medium">
                          {getAiProviderLabel(item)}
                        </div>
                        <div className="text-[10px] text-gray-400">
                          {item.provider_kind || (item.model_name === 'gptimage2' ? 'adapter_direct' : '-')}
                        </div>
                      </td>
                    )}
                    <td className="px-6 py-4">
                      <span className={cn(
                        "px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider",
                        item.status === 'succeeded' || item.status === 'completed' ? "bg-green-50 text-green-600" :
                        ['failed', 'dead_letter'].includes(item.status) ? "bg-red-50 text-red-600" :
                        item.status === 'waiting_review' ? "bg-orange-50 text-orange-700" :
                        "bg-blue-50 text-blue-600"
                      )}>
                        {activeTab === 'durable' ? (DURABLE_STATUS_LABELS[item.status] || item.status) : item.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-gray-500 text-xs">
                      {formatLocalDateTime(item.created_at)}
                    </td>
                    <td className="px-6 py-4 text-right space-x-2">
                      <button
                        onClick={() => openDetail(item.id)}
                        className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all"
                      >
                        <Eye className="h-4 w-4" />
                      </button>
                      {((activeTab === 'workflow' && ['queued', 'pending', 'running'].includes(item.status)) ||
                        (activeTab === 'ai' && ['pending', 'processing'].includes(item.status))) && (
                        <button
                          onClick={() => handleFail(item.id)}
                          className="p-1.5 text-gray-400 hover:text-amber-600 hover:bg-amber-50 rounded-lg transition-all"
                          title="手动终止并标记失败"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      )}
                      {activeTab !== 'durable' && (
                        <button
                          onClick={() => handleDelete(item.id)}
                          className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={activeTab === 'ai' ? 7 : 6} className="px-6 py-20 text-center text-gray-500">
                    <div className="flex flex-col items-center gap-2">
                      <AlertCircle className="h-8 w-8 text-gray-200" />
                      <p>暂无符合条件的任务记录</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {total > 15 && (
          <div className="px-6 py-4 border-t flex items-center justify-between bg-gray-50/50">
            <div className="text-xs text-gray-500">
              共 {total} 条记录，第 {page} / {Math.ceil(total / 15)} 页
            </div>
            <div className="flex items-center gap-2">
              <button
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
                className="p-1.5 rounded-lg border bg-white hover:bg-gray-50 disabled:opacity-50 transition-all"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                disabled={page >= Math.ceil(total / 15)}
                onClick={() => setPage(p => p + 1)}
                className="p-1.5 rounded-lg border bg-white hover:bg-gray-50 disabled:opacity-50 transition-all"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {detailOpen && activeTab === 'durable' && (
        <DurableJobDetail
          task={selectedTask as DurableJobDetailData | null}
          loading={detailLoading}
          onClose={() => { setDetailOpen(false); setSelectedTask(null); }}
        />
      )}

      {detailOpen && activeTab !== 'durable' && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/20">
          <div className="h-full w-full max-w-2xl bg-white shadow-2xl border-l flex flex-col">
            <div className="px-6 py-4 border-b flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">任务详情</h2>
                <p className="text-xs text-gray-500 mt-1">
                  {activeTab === 'workflow' ? '工作流任务执行详情与运行日志' : 'AI 生图任务详情与事件日志'}
                </p>
              </div>
              <button
                onClick={() => { setDetailOpen(false); setSelectedTask(null); }}
                className="p-2 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {detailLoading || !selectedTask ? (
                <div className="space-y-3 animate-pulse">
                  <div className="h-5 bg-gray-100 rounded w-40" />
                  <div className="h-24 bg-gray-100 rounded-xl" />
                  <div className="h-40 bg-gray-100 rounded-xl" />
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="rounded-xl border bg-gray-50 p-4">
                      <div className="text-xs text-gray-500">任务 ID</div>
                      <div className="mt-1 font-mono text-sm text-gray-900">#{selectedTask.id}</div>
                    </div>
                    <div className="rounded-xl border bg-gray-50 p-4">
                      <div className="text-xs text-gray-500">状态</div>
                      <div className="mt-1 font-medium text-gray-900">{selectedTask.status}</div>
                    </div>
                    <div className="rounded-xl border bg-gray-50 p-4">
                      <div className="text-xs text-gray-500">用户</div>
                      <div className="mt-1 font-medium text-gray-900">{selectedTask.username || '-'}</div>
                    </div>
                    <div className="rounded-xl border bg-gray-50 p-4">
                      <div className="text-xs text-gray-500">{activeTab === 'workflow' ? '工作流' : '模型'}</div>
                      <div className="mt-1 font-medium text-gray-900">
                        {activeTab === 'workflow' ? selectedTask.workflow_name : selectedTask.model_name}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <div className="text-sm font-semibold text-gray-900 mb-2">核心信息</div>
                      <div className="rounded-xl border bg-white overflow-hidden">
                        <div className="px-4 py-3 border-b text-xs text-gray-500">创建时间</div>
                        <div className="px-4 py-3 text-sm text-gray-900">{selectedTask.created_at ? formatLocalDateTime(selectedTask.created_at) : '-'}</div>
                        <div className="px-4 py-3 border-y text-xs text-gray-500">完成时间</div>
                        <div className="px-4 py-3 text-sm text-gray-900">{selectedTask.finished_at ? formatLocalDateTime(selectedTask.finished_at) : '-'}</div>
                        {activeTab === 'workflow' ? (
                          <>
                            <div className="px-4 py-3 border-y text-xs text-gray-500">进度 / 外部任务 ID</div>
                            <div className="px-4 py-3 text-sm text-gray-900 break-all">{selectedTask.progress || selectedTask.task_id || '-'}</div>
                          </>
                        ) : (
                          <>
                            <div className="px-4 py-3 border-y text-xs text-gray-500">生图入口</div>
                            <div className="px-4 py-3 text-sm text-gray-900">{selectedTask.provider_name || selectedTask.provider_kind || '-'}</div>
                          </>
                        )}
                      </div>
                    </div>

                    <div>
                      <div className="text-sm font-semibold text-gray-900 mb-2">任务日志</div>
                      <div className="rounded-xl border divide-y bg-white">
                        {(selectedTask.logs || []).length > 0 ? (
                          selectedTask.logs.map((log: any, idx: number) => (
                            <div key={log.id || idx} className="p-4 space-y-2">
                              <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                  <span className={cn(
                                    'inline-block h-2.5 w-2.5 rounded-full',
                                    log.level === 'error' ? 'bg-red-500' :
                                    log.level === 'success' ? 'bg-green-500' : 'bg-blue-500'
                                  )} />
                                  <div className="text-sm font-medium text-gray-900">{log.title}</div>
                                </div>
                                <div className="text-[11px] text-gray-400">{log.timestamp ? formatLocalDateTime(log.timestamp) : '-'}</div>
                              </div>
                              <div className="text-sm text-gray-600 whitespace-pre-wrap break-all">{log.message || '-'}</div>
                              {log.payload && (
                                <pre className="overflow-x-auto rounded-lg bg-gray-50 p-3 text-xs text-gray-700 whitespace-pre-wrap break-all">
{JSON.stringify(log.payload, null, 2)}
                                </pre>
                              )}
                            </div>
                          ))
                        ) : (
                          <div className="p-6 text-sm text-gray-500">暂无日志</div>
                        )}
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-4">
                      {activeTab === 'workflow' ? (
                        <>
                          <div className="rounded-xl border bg-white">
                            <div className="px-4 py-3 border-b text-sm font-semibold text-gray-900">输入</div>
                            <pre className="p-4 text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap break-all">{JSON.stringify(selectedTask.inputs || {}, null, 2)}</pre>
                          </div>
                          <div className="rounded-xl border bg-white">
                            <div className="px-4 py-3 border-b text-sm font-semibold text-gray-900">输出</div>
                            <pre className="p-4 text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap break-all">{JSON.stringify(selectedTask.outputs || {}, null, 2)}</pre>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="rounded-xl border bg-white">
                            <div className="px-4 py-3 border-b text-sm font-semibold text-gray-900">提示词</div>
                            <div className="p-4 text-sm text-gray-700 whitespace-pre-wrap break-all">{selectedTask.prompt || '-'}</div>
                          </div>
                          <div className="rounded-xl border bg-white">
                            <div className="px-4 py-3 border-b text-sm font-semibold text-gray-900">任务参数</div>
                            <pre className="p-4 text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap break-all">{JSON.stringify(selectedTask.params || {}, null, 2)}</pre>
                          </div>
                          <div className="rounded-xl border bg-white">
                            <div className="px-4 py-3 border-b text-sm font-semibold text-gray-900">结果图片</div>
                            <div className="p-4 space-y-2">
                              {(selectedTask.result_urls || []).length > 0 ? (
                                selectedTask.result_urls.map((url: string) => (
                                  <a key={url} href={url} target="_blank" rel="noreferrer" className="block text-sm text-indigo-600 break-all hover:underline">
                                    {url}
                                  </a>
                                ))
                              ) : (
                                <div className="text-sm text-gray-500">暂无结果图片</div>
                              )}
                            </div>
                          </div>
                        </>
                      )}
                      {selectedTask.error && (
                        <div className="rounded-xl border border-red-200 bg-red-50">
                          <div className="px-4 py-3 border-b border-red-200 text-sm font-semibold text-red-700">错误信息</div>
                          <div className="p-4 text-sm text-red-700 whitespace-pre-wrap break-all">{selectedTask.error}</div>
                        </div>
                      )}
                      {activeTab === 'ai' && selectedTask.upstream_debug && (
                        <div className="rounded-xl border border-amber-200 bg-amber-50">
                          <div className="flex items-center justify-between gap-3 border-b border-amber-200 px-4 py-3">
                            <div>
                              <div className="text-sm font-semibold text-amber-800">上游完整响应日志</div>
                              <div className="mt-1 text-xs text-amber-700">已脱敏 Authorization / Cookie 等敏感头；正文过大时会标记 body_truncated。</div>
                            </div>
                            <button
                              type="button"
                              onClick={() => navigator.clipboard?.writeText(JSON.stringify(selectedTask.upstream_debug, null, 2)).then(() => toast.success('已复制上游日志')).catch(() => toast.error('复制失败'))}
                              className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100"
                            >
                              复制日志
                            </button>
                          </div>
                          <pre className="max-h-[520px] overflow-auto p-4 text-xs leading-5 text-amber-950 whitespace-pre-wrap break-all">
                            {JSON.stringify(selectedTask.upstream_debug, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
