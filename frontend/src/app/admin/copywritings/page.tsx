'use client';

import { useCallback, useEffect, useState } from 'react';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';
import { BookOpen, Play, Search, Trash2, Users } from 'lucide-react';

interface Copywriting {
  id: number;
  title: string;
  content: string;
  tags: string[];
  category: string;
  created_by: number | null;
  created_at: string;
}

interface ReviewTask {
  id: number;
  name: string;
  source: string;
  status: string;
  max_items: number;
  candidate_count: number;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  needs_second_review_count: number;
  saved_path: string | null;
  last_error: string | null;
  source_config: Record<string, unknown>;
  run_meta: Record<string, unknown>;
  run_summary: RunSummary;
  reviewers: Array<{ id: number; username: string }>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

interface RunSummary {
  requested_max_items: number;
  actual_count: number;
  saved_count: number;
  keyword_mode: string;
  configured_keywords: string[];
  configured_keyword_count: number;
  history_dedupe_days: number;
  search_returned_count: number;
  considered_count: number;
  duplicate_filtered_count: number;
  history_filtered_count: number;
  shortfall_count: number;
  search_shortage_count: number;
}

interface ReviewTaskDetail extends ReviewTask {
  source_config: Record<string, unknown>;
  run_meta: Record<string, unknown>;
  run_summary: RunSummary;
}

interface ReviewCandidate {
  id: number;
  title: string;
  content: string;
  author: string | null;
  source_keyword: string | null;
  post_url: string | null;
  publish_date: string | null;
  copy_type: string | null;
  brand: string | null;
  likes: number;
  comments: number;
  collects: number;
  shares: number;
  views: number;
  review_status: string;
  reviewer_name: string | null;
  review_note: string | null;
  copywriting_id: number | null;
}

interface UserItem {
  id: number;
  username: string;
}

type TabKey = 'library' | 'tasks';

export default function CopywritingsPage() {
  const [tab, setTab] = useState<TabKey>('tasks');

  const [items, setItems] = useState<Copywriting[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loadingLibrary, setLoadingLibrary] = useState(true);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [usernameFilter, setUsernameFilter] = useState<string | undefined>(undefined);
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>(undefined);

  const [tasks, setTasks] = useState<ReviewTask[]>([]);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loadingTasks, setLoadingTasks] = useState(true);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [selectedTaskDetail, setSelectedTaskDetail] = useState<ReviewTaskDetail | null>(null);
  const [loadingTaskDetail, setLoadingTaskDetail] = useState(false);
  const [candidateFilter, setCandidateFilter] = useState<string>('');
  const [candidates, setCandidates] = useState<ReviewCandidate[]>([]);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [creatingTask, setCreatingTask] = useState(false);
  const [runningTaskId, setRunningTaskId] = useState<number | null>(null);

  const [taskName, setTaskName] = useState('');
  const [rawKeywords, setRawKeywords] = useState('');
  const [maxItems, setMaxItems] = useState(50);
  const [selectedTaskIds, setSelectedTaskIds] = useState<number[]>([]);
  const [reviewerIds, setReviewerIds] = useState<number[]>([]);
  const [assigningTasks, setAssigningTasks] = useState(false);

  const fetchLibrary = useCallback(() => {
    setLoadingLibrary(true);
    adminApi.getAdminCopywritings(page, 20, usernameFilter, categoryFilter, search || undefined)
      .then(res => {
        setItems(res.data.items);
        setTotal(res.data.total);
      })
      .catch((err: unknown) => {
        toast.error(err instanceof Error ? err.message : '加载文案库失败');
      })
      .finally(() => setLoadingLibrary(false));
  }, [page, usernameFilter, categoryFilter, search]);

  const fetchTasks = useCallback(async () => {
    setLoadingTasks(true);
    try {
      const [taskRes, userRes] = await Promise.all([
        adminApi.getScrapeReviewTasks(1, 100),
        adminApi.getUsers(1, 100),
      ]);
      setTasks(taskRes.data.items);
      setUsers(userRes.data.items.map(item => ({ id: item.id, username: item.username })));
      if (!selectedTaskId && taskRes.data.items.length > 0) {
        setSelectedTaskId(taskRes.data.items[0].id);
      }
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : '加载抓取任务失败');
    } finally {
      setLoadingTasks(false);
    }
  }, [selectedTaskId]);

  const fetchCandidates = useCallback(async () => {
    if (!selectedTaskId) {
      setCandidates([]);
      return;
    }
    setLoadingCandidates(true);
    try {
      const res = await adminApi.getScrapeReviewCandidates(selectedTaskId, candidateFilter || undefined);
      setCandidates(res.data.items);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : '加载候选内容失败');
    } finally {
      setLoadingCandidates(false);
    }
  }, [selectedTaskId, candidateFilter]);

  const fetchTaskDetail = useCallback(async () => {
    if (!selectedTaskId) {
      setSelectedTaskDetail(null);
      return;
    }
    setLoadingTaskDetail(true);
    try {
      const res = await adminApi.getScrapeReviewTaskDetail(selectedTaskId);
      setSelectedTaskDetail(res.data as ReviewTaskDetail);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : '加载任务详情失败');
    } finally {
      setLoadingTaskDetail(false);
    }
  }, [selectedTaskId]);

  useEffect(() => {
    fetchLibrary();
  }, [fetchLibrary]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  useEffect(() => {
    fetchCandidates();
  }, [fetchCandidates]);

  useEffect(() => {
    fetchTaskDetail();
  }, [fetchTaskDetail]);

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这篇文案吗？')) return;
    setDeletingId(id);
    try {
      await adminApi.deleteAdminCopywriting(id);
      toast.success('已删除');
      fetchLibrary();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  const toggleReviewer = (userId: number) => {
    setReviewerIds(prev => prev.includes(userId) ? prev.filter(id => id !== userId) : [...prev, userId]);
  };

  const toggleTaskSelection = (taskId: number) => {
    setSelectedTaskIds(prev => prev.includes(taskId) ? prev.filter(id => id !== taskId) : [...prev, taskId]);
  };

  const handleCreateTask = async () => {
    if (!taskName.trim()) {
      toast.error('任务名称不能为空');
      return;
    }
    if (!rawKeywords.trim()) {
      toast.error('关键词不能为空');
      return;
    }
    const normalizedKeywords = rawKeywords.trim();
    const keywordMode = /[,，\r\n]+/.test(normalizedKeywords) ? 'multi' : 'phrase';
    setCreatingTask(true);
    try {
      const res = await adminApi.createScrapeReviewTask({
        name: taskName.trim(),
        source: 'keyword',
        max_items: maxItems,
        source_config: {
          keywordMode,
          rawKeywords: normalizedKeywords,
          sortBy: '综合',
          noteType: '不限',
          searchScope: '不限',
          historyDedupeDays: 30,
        },
      });
      toast.success('任务已创建');
      setTaskName('');
      setRawKeywords('');
      await fetchTasks();
      setSelectedTaskId(res.data.id);
    } catch (err: any) {
      toast.error(err?.message || '创建任务失败');
    } finally {
      setCreatingTask(false);
    }
  };

  const handleRunTask = async (taskId: number) => {
    setRunningTaskId(taskId);
    try {
      const res = await adminApi.runScrapeReviewTask(taskId);
      toast.success(`抓取完成：新增 ${res.data.created} 条候选`);
      await fetchTasks();
      if (selectedTaskId === taskId) {
        await fetchTaskDetail();
        await fetchCandidates();
      }
    } catch (err: any) {
      toast.error(err?.message || '启动任务失败');
    } finally {
      setRunningTaskId(null);
    }
  };

  const handleAssignTasks = async () => {
    if (selectedTaskIds.length === 0) {
      toast.error('请先选择要分配的任务');
      return;
    }
    if (reviewerIds.length === 0) {
      toast.error('请至少指定一个审核人');
      return;
    }
    setAssigningTasks(true);
    try {
      const res = await adminApi.assignScrapeReviewTasks({
        task_ids: selectedTaskIds,
        reviewer_ids: reviewerIds,
      });
      toast.success(`已分配 ${res.data.assigned_task_count} 个任务`);
      setSelectedTaskIds([]);
      await fetchTasks();
      await fetchTaskDetail();
    } catch (err: any) {
      toast.error(err?.message || '批量分配失败');
    } finally {
      setAssigningTasks(false);
    }
  };

  const selectedTask = tasks.find(task => task.id === selectedTaskId) || null;
  const taskDetail = selectedTaskDetail && selectedTaskDetail.id === selectedTaskId ? selectedTaskDetail : null;
  const runSummary = taskDetail?.run_summary || selectedTask?.run_summary || null;
  const configuredKeywords = runSummary?.configured_keywords || [];
  const completedTaskIds = tasks.filter(task => task.status === 'completed').map(task => task.id);
  const selectedCompletedCount = selectedTaskIds.filter(taskId => completedTaskIds.includes(taskId)).length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">文案与抓取审核</h2>
          <p className="text-sm text-gray-500">先创建并运行抓取任务，确认结果后再批量分配给审核人。</p>
        </div>
        <div className="flex rounded-lg border bg-white p-1 text-sm">
          <button
            onClick={() => setTab('tasks')}
            className={`rounded-md px-3 py-1.5 ${tab === 'tasks' ? 'bg-indigo-50 text-indigo-700' : 'text-gray-500'}`}
          >
            抓取任务
          </button>
          <button
            onClick={() => setTab('library')}
            className={`rounded-md px-3 py-1.5 ${tab === 'library' ? 'bg-indigo-50 text-indigo-700' : 'text-gray-500'}`}
          >
            已入库文案
          </button>
        </div>
      </div>

      {tab === 'library' ? (
        <div className="space-y-4">
          <div className="flex gap-3 flex-wrap">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                className="w-full pl-9 pr-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="搜索标题..."
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
            <input
              className="w-28 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="分类"
              value={categoryFilter ?? ''}
              onChange={e => setCategoryFilter(e.target.value || undefined)}
            />
            <input
              className="w-28 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="用户"
              value={usernameFilter ?? ''}
              onChange={e => setUsernameFilter(e.target.value || undefined)}
            />
          </div>

          {loadingLibrary ? (
            <div className="text-sm text-gray-400 py-10">加载中...</div>
          ) : items.length === 0 ? (
            <div className="text-center py-12 text-gray-400">暂无入库文案</div>
          ) : (
            <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">标题</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">摘要</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">分类</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-600">创建时间</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {items.map(c => (
                    <tr key={c.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium">{c.title}</td>
                      <td className="px-4 py-3 text-gray-500 max-w-[320px] truncate">{c.content}</td>
                      <td className="px-4 py-3">{c.category || '-'}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{c.created_at?.slice(0, 19)}</td>
                      <td className="px-4 py-3 text-right">
                        <button
                          disabled={deletingId === c.id}
                          onClick={() => handleDelete(c.id)}
                          className="text-xs text-red-600 hover:underline disabled:opacity-50 inline-flex items-center gap-1"
                        >
                          <Trash2 className="h-3 w-3" />
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {total > 20 && (
                <div className="flex items-center justify-between border-t px-4 py-3">
                  <span className="text-xs text-gray-500">第 {page} 页</span>
                  <div className="flex gap-2">
                    <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-3 py-1 text-xs rounded-md border disabled:opacity-40 hover:bg-gray-50">上一页</button>
                    <button disabled={page * 20 >= total} onClick={() => setPage(p => p + 1)} className="px-3 py-1 text-xs rounded-md border disabled:opacity-40 hover:bg-gray-50">下一页</button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
          <div className="space-y-4">
            <div className="rounded-xl border bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2 mb-3">
                <Users className="h-4 w-4 text-indigo-600" />
                <h3 className="font-medium">新建抓取任务</h3>
              </div>
              <div className="space-y-3">
                <input
                  className="w-full rounded-lg border px-3 py-2 text-sm"
                  placeholder="任务名称，例如：5月购车补贴热门池"
                  value={taskName}
                  onChange={e => setTaskName(e.target.value)}
                />
                <textarea
                  className="w-full rounded-lg border px-3 py-2 text-sm min-h-[120px]"
                  placeholder="每行一个关键词，或逗号分隔"
                  value={rawKeywords}
                  onChange={e => setRawKeywords(e.target.value)}
                />
                <div className="flex items-center gap-3">
                  <label className="text-sm text-gray-500">单次上限</label>
                  <input
                    type="number"
                    min={1}
                    max={300}
                    className="w-24 rounded-lg border px-3 py-2 text-sm"
                    value={maxItems}
                    onChange={e => setMaxItems(Number(e.target.value) || 50)}
                  />
                </div>
                <div className="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  `单次上限` 是最多抓取条数，不保证一定拿满。跨关键词重复、历史去重、搜索结果不足都会让最终候选少于设置值。
                </div>
                <button
                  onClick={handleCreateTask}
                  disabled={creatingTask}
                  className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {creatingTask ? '创建中...' : '保存任务'}
                </button>
              </div>
            </div>

            <div className="rounded-xl border bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2 mb-3">
                <Users className="h-4 w-4 text-indigo-600" />
                <h3 className="font-medium">批量分配审核</h3>
              </div>
              <div className="space-y-3">
                <div className="text-xs text-gray-500">
                  先在下方任务列表勾选已完成任务，再把它们一次性分配给审核人。
                </div>
                <div className="rounded-lg border bg-gray-50 px-3 py-2 text-xs text-gray-600">
                  已选任务 {selectedCompletedCount} 个
                </div>
                <div>
                  <div className="mb-2 text-sm text-gray-500">审核人</div>
                  <div className="flex flex-wrap gap-2">
                    {users.map(user => (
                      <button
                        key={user.id}
                        onClick={() => toggleReviewer(user.id)}
                        className={`rounded-full border px-3 py-1 text-xs ${
                          reviewerIds.includes(user.id)
                            ? 'border-indigo-200 bg-indigo-50 text-indigo-700'
                            : 'border-gray-200 bg-white text-gray-600'
                        }`}
                      >
                        {user.username}
                      </button>
                    ))}
                  </div>
                </div>
                <button
                  onClick={handleAssignTasks}
                  disabled={assigningTasks || selectedTaskIds.length === 0}
                  className="w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  {assigningTasks ? '分配中...' : '分配选中任务'}
                </button>
              </div>
            </div>

            <div className="rounded-xl border bg-white shadow-sm">
              <div className="border-b px-4 py-3 font-medium">任务列表</div>
              {loadingTasks ? (
                <div className="px-4 py-8 text-sm text-gray-400">加载中...</div>
              ) : tasks.length === 0 ? (
                <div className="px-4 py-8 text-sm text-gray-400">暂无抓取任务</div>
              ) : (
                <div className="divide-y">
                  {tasks.map(task => (
                    <div
                      key={task.id}
                      onClick={() => setSelectedTaskId(task.id)}
                      className={`w-full cursor-pointer px-4 py-3 text-left hover:bg-gray-50 ${selectedTaskId === task.id ? 'bg-indigo-50' : ''}`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-3 min-w-0">
                          <input
                            type="checkbox"
                            checked={selectedTaskIds.includes(task.id)}
                            disabled={task.status !== 'completed'}
                            onChange={(event) => {
                              event.stopPropagation();
                              toggleTaskSelection(task.id);
                            }}
                            onClick={(event) => event.stopPropagation()}
                            className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 disabled:opacity-40"
                          />
                          <div className="min-w-0">
                          <div className="font-medium truncate">{task.name}</div>
                          <div className="mt-1 text-xs text-gray-500">
                            上限 {task.max_items} / 实际 {task.candidate_count} / 待审 {task.pending_count}
                          </div>
                          <div className="mt-1 text-[11px] text-gray-400">
                            通过 {task.approved_count} / 淘汰 {task.rejected_count} / 复核 {task.needs_second_review_count}
                          </div>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {task.reviewers.length > 0 ? task.reviewers.map(reviewer => (
                              <span key={reviewer.id} className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">
                                {reviewer.username}
                              </span>
                            )) : (
                              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                                未分配审核人
                              </span>
                            )}
                          </div>
                        </div>
                        </div>
                        <button
                          onClick={(event) => {
                            event.stopPropagation();
                            handleRunTask(task.id);
                          }}
                          disabled={runningTaskId === task.id || task.status === 'running'}
                          className="rounded-md border px-2 py-1 text-xs text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
                        >
                          <span className="inline-flex items-center gap-1">
                            <Play className="h-3 w-3" />
                            {runningTaskId === task.id ? '抓取中...' : '启动'}
                          </span>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="rounded-xl border bg-white shadow-sm overflow-hidden">
            {!selectedTask ? (
              <div className="p-10 text-center text-gray-400">选择左侧任务查看候选内容</div>
            ) : (
              <>
                <div className="border-b px-4 py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <BookOpen className="h-4 w-4 text-indigo-600" />
                        <h3 className="font-semibold">{selectedTask.name}</h3>
                      </div>
                      <div className="mt-1 text-sm text-gray-500">
                        状态 {selectedTask.status}，候选 {selectedTask.candidate_count}，待审 {selectedTask.pending_count}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {selectedTask.reviewers.length > 0 ? selectedTask.reviewers.map(reviewer => (
                          <span key={reviewer.id} className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">
                            {reviewer.username}
                          </span>
                        )) : (
                          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                            这次任务还没分配审核人
                          </span>
                        )}
                      </div>
                      {runSummary && (
                        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                          <div className="rounded-lg border bg-gray-50 px-3 py-2">
                            <div className="text-[11px] text-gray-500">抓取结果</div>
                            <div className="mt-1 text-sm font-medium">上限 {runSummary.requested_max_items} / 实际 {runSummary.actual_count}</div>
                          </div>
                          <div className="rounded-lg border bg-gray-50 px-3 py-2">
                            <div className="text-[11px] text-gray-500">关键词</div>
                            <div className="mt-1 text-sm font-medium">{runSummary.configured_keyword_count} 个 · {runSummary.keyword_mode === 'multi' ? '多关键词' : '单关键词'}</div>
                          </div>
                          <div className="rounded-lg border bg-gray-50 px-3 py-2">
                            <div className="text-[11px] text-gray-500">重复过滤</div>
                            <div className="mt-1 text-sm font-medium">{runSummary.duplicate_filtered_count} 条</div>
                          </div>
                          <div className="rounded-lg border bg-gray-50 px-3 py-2">
                            <div className="text-[11px] text-gray-500">历史去重</div>
                            <div className="mt-1 text-sm font-medium">{runSummary.history_filtered_count} 条</div>
                          </div>
                        </div>
                      )}
                      {runSummary && (
                        <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-3 text-xs text-gray-600">
                          <div>搜索返回 {runSummary.search_returned_count} 条，实际纳入候选 {runSummary.actual_count} 条。</div>
                          <div className="mt-1">
                            少于上限 {runSummary.shortfall_count} 条；
                            其中重复过滤 {runSummary.duplicate_filtered_count} 条，历史去重 {runSummary.history_filtered_count} 条，
                            其余 {runSummary.search_shortage_count} 条通常是搜索结果不足或有效详情不足。
                          </div>
                          {runSummary.history_dedupe_days > 0 && (
                            <div className="mt-1">当前启用了近 {runSummary.history_dedupe_days} 天历史去重。</div>
                          )}
                          {configuredKeywords.length > 0 && (
                            <div className="mt-2 flex flex-wrap gap-1">
                              {configuredKeywords.map(keyword => (
                                <span key={keyword} className="rounded-full bg-white px-2 py-0.5 text-[11px] text-gray-700 border">
                                  {keyword}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                      {selectedTask.last_error && (
                        <div className="mt-2 text-xs text-red-600">{selectedTask.last_error}</div>
                      )}
                      {loadingTaskDetail && (
                        <div className="mt-2 text-xs text-gray-400">任务详情刷新中...</div>
                      )}
                    </div>
                    <select
                      value={candidateFilter}
                      onChange={e => setCandidateFilter(e.target.value)}
                      className="rounded-lg border px-3 py-2 text-sm"
                    >
                      <option value="">待审 + 复核</option>
                      <option value="pending">待审</option>
                      <option value="approved">已通过</option>
                      <option value="rejected">已淘汰</option>
                      <option value="needs_second_review">待复核</option>
                    </select>
                  </div>
                </div>
                {loadingCandidates ? (
                  <div className="p-8 text-sm text-gray-400">加载候选内容中...</div>
                ) : candidates.length === 0 ? (
                  <div className="p-8 text-sm text-gray-400">该任务下暂无候选内容</div>
                ) : (
                  <div className="divide-y">
                    {candidates.map(item => (
                      <div key={item.id} className="px-4 py-4">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <h4 className="font-medium">{item.title}</h4>
                              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">{item.review_status}</span>
                              {item.brand && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">{item.brand}</span>}
                              {item.copy_type && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">{item.copy_type}</span>}
                            </div>
                            <div className="mt-2 line-clamp-4 text-sm text-gray-600 whitespace-pre-wrap">{item.content}</div>
                            <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-500">
                              <span>作者 {item.author || '-'}</span>
                              <span>发布日期 {item.publish_date || '-'}</span>
                              <span>点赞 {item.likes}</span>
                              <span>评论 {item.comments}</span>
                              <span>收藏 {item.collects}</span>
                              <span>分享 {item.shares}</span>
                              {item.source_keyword && <span>关键词 {item.source_keyword}</span>}
                              {item.reviewer_name && <span>审核人 {item.reviewer_name}</span>}
                            </div>
                            {item.post_url && (
                              <a href={item.post_url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs text-indigo-600 hover:underline">
                                查看原帖
                              </a>
                            )}
                            {item.review_note && (
                              <div className="mt-2 text-xs text-gray-500">备注：{item.review_note}</div>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
