'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import yaml from 'js-yaml';
import { cn } from '@/lib/utils';
import {
  Plus, Play, Trash2, Edit2, X, Search,
  Clock, ArrowRight, Loader2,
  PanelRightClose, CheckCircle2, XCircle,
  Zap, FileText, ListTodo, MoreVertical,
} from 'lucide-react';
import { difyApi, type DifyWorkflowLog } from '@/services/difyApi';

interface Workflow {
  id: number;
  name: string;
  description: string | null;
  appType: string;
  enabled: boolean;
  inputsSchema: Record<string, unknown> | null;
  apiKey?: string;
}

interface Task {
  id: number;
  workflow_id: number;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  error?: string;
  progress: string;
  elapsed_ms?: number;
  viewed?: number;
  created_at: string;
  finished_at?: string;
  workflow_name?: string;
}

type WorkflowLog = DifyWorkflowLog;

const typeIcons: Record<string, typeof Zap> = {
  workflow: Zap,
  chat: FileText,
  completion: ArrowRight,
};

const typeColors: Record<string, string> = {
  workflow: 'from-violet-500 to-purple-600',
  chat: 'from-sky-500 to-blue-600',
  completion: 'from-emerald-500 to-green-600',
};

const statusConfig: Record<string, {
  label: string;
  icon: typeof CheckCircle2;
  dot: string;
  text: string;
}> = {
  succeeded: { label: '成功', icon: CheckCircle2, dot: 'bg-emerald-500', text: 'text-emerald-600' },
  failed: { label: '失败', icon: XCircle, dot: 'bg-red-500', text: 'text-red-600' },
  running: { label: '运行中', icon: Loader2, dot: 'bg-blue-500', text: 'text-blue-600' },
  pending: { label: '排队中', icon: Clock, dot: 'bg-amber-500', text: 'text-amber-600' },
};

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '-';
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0') + ' ' +
      String(d.getHours()).padStart(2, '0') + ':' +
      String(d.getMinutes()).padStart(2, '0') + ':' +
      String(d.getSeconds()).padStart(2, '0');
  } catch {
    return '-';
  }
}

function extractOutput(outputs: Record<string, unknown>): string {
  if (!outputs) return '-';
  const text = outputs.text || outputs.answer || outputs.result || outputs.output || outputs.content;
  if (typeof text === 'string') return text;
  const vals = Object.values(outputs);
  if (vals.length === 1 && typeof vals[0] === 'string') return vals[0];
  return JSON.stringify(outputs);
}

function formatTaskTime(dateStr: string): string {
  if (!dateStr) return '-';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0') + ' ' +
      String(d.getHours()).padStart(2, '0') + ':' +
      String(d.getMinutes()).padStart(2, '0') + ':' +
      String(d.getSeconds()).padStart(2, '0');
  } catch {
    return dateStr;
  }
}

interface WorkflowField {
  variable: string;
  label: string;
  type: 'text-input' | 'paragraph' | 'number' | 'select';
  required: boolean;
  placeholder: string;
  hint: string;
  options: string;
}

/* ============================================================
   MAIN PAGE
   ============================================================ */

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [logs, setLogs] = useState<WorkflowLog[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null);
  const [runningWorkflow, setRunningWorkflow] = useState<Workflow | null>(null);
  const [logSearch, setLogSearch] = useState('');
  const [showTaskPanel, setShowTaskPanel] = useState(false);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [activeTab, setActiveTab] = useState<'workflows' | 'logs'>('workflows');
  const [openDropdown, setOpenDropdown] = useState<number | null>(null);
  const pollRef = useRef<number>();
  const pageRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (openDropdown === null) return;
      if (pageRef.current && !pageRef.current.contains(e.target as Node)) {
        setOpenDropdown(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [openDropdown]);

  const fetchWorkflows = async () => {
    try {
      const res = await difyApi.listWorkflows();
      setWorkflows(res.data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const fetchTasks = useCallback(async () => {
    try {
      const res = await difyApi.getTasks();
      const items = (res.data.items as Task[]) || [];
      setTasks(items.map(t => ({
        ...t,
        workflow_name: workflows.find(w => w.id === t.workflow_id)?.name || '#' + t.workflow_id,
      })));
    } catch (e) { console.error(e); }
  }, [workflows]);

  const fetchLogs = async () => {
    try {
      const res = await difyApi.getAllLogs(1, 50);
      setLogs(res.data.items);
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    fetchWorkflows();
    fetchLogs();
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  // Poll running tasks
  useEffect(() => {
    const hasRunning = tasks.some(t => t.status === 'running' || t.status === 'pending');
    if (hasRunning) {
      pollRef.current = window.setInterval(fetchTasks, 3000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [tasks, fetchTasks]);

  const runningCount = tasks.filter(t => t.status === 'running' || t.status === 'pending').length;

  const handleDeleteTask = async (taskId: number, status: string) => {
    if (status === 'running' || status === 'pending') return;
    if (!confirm('确定要删除此任务记录吗？')) return;
    try {
      await difyApi.deleteTask(String(taskId));
      setTasks(prev => prev.filter(t => t.id !== taskId));
    } catch (e: any) {
      alert('删除失败: ' + (e?.message || '未知错误'));
    }
  };

  const handleTaskClick = async (task: Task) => {
    if (!task.viewed) {
      try {
        await difyApi.markTaskViewed(String(task.id));
        setTasks(prev => prev.map(t => t.id === task.id ? { ...t, viewed: 1 } : t));
      } catch { /* ignore */ }
    }
    setSelectedTask(task);
  };

  const handleRun = async (wf: Workflow, inputs: Record<string, string>) => {
    try {
      await difyApi.runTask(String(wf.id), { inputs });
      await fetchTasks();
      setShowTaskPanel(true);
    } catch (e: any) {
      alert('提交失败: ' + (e?.response?.data?.detail || e?.message || '未知错误'));
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除此工作流吗？')) return;
    try {
      await difyApi.deleteWorkflow(String(id));
      setWorkflows(prev => prev.filter(w => w.id !== id));
    } catch (e: any) {
      alert('删除失败: ' + (e?.message || '未知错误'));
    }
  };

  const filteredLogs = logs.filter(log => {
    if (!logSearch) return true;
    const wfName = workflows.find(w => w.id === Number(log.workflow_id))?.name || '';
    return wfName.toLowerCase().includes(logSearch.toLowerCase());
  });

  return (
    <div ref={pageRef} className="flex h-full bg-[#fafafa]">
      {/* ---- Main Area ---- */}
      <div className={cn('flex-1 flex flex-col min-w-0 transition-all', showTaskPanel && 'mr-96')}>
        {/* Header */}
        <div className="flex items-center justify-between px-8 py-5 border-b bg-white shrink-0">
          <div className="flex items-center gap-6">
            <button onClick={() => setActiveTab('workflows')}
              className={cn('text-sm font-medium transition-colors relative pb-1',
                activeTab === 'workflows'
                  ? 'text-foreground after:absolute after:bottom-0 after:left-0 after:right-0 after:h-[2px] after:bg-foreground'
                  : 'text-muted-foreground hover:text-foreground')}>
              工作流
            </button>
            <button onClick={() => setActiveTab('logs')}
              className={cn('text-sm font-medium transition-colors relative pb-1',
                activeTab === 'logs'
                  ? 'text-foreground after:absolute after:bottom-0 after:left-0 after:right-0 after:h-[2px] after:bg-foreground'
                  : 'text-muted-foreground hover:text-foreground')}>
              运行日志
            </button>
          </div>
          <div className="flex items-center gap-3">
            {runningCount > 0 && (
              <div className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full bg-blue-50 text-blue-600">
                <span className="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
                {runningCount} 个执行中
              </div>
            )}
            {(() => {
              const unviewedCount = tasks.filter(t => !t.viewed && t.status !== 'running' && t.status !== 'pending').length;
              return (
                <button onClick={() => setShowTaskPanel(!showTaskPanel)}
                  className={cn(
                    'relative flex items-center gap-2 text-xs px-3 py-1.5 rounded-full transition-colors',
                    showTaskPanel
                      ? 'bg-neutral-100 text-foreground hover:bg-neutral-200'
                      : 'bg-white border text-muted-foreground hover:text-foreground hover:border-neutral-300',
                  )}>
                  <ListTodo className="h-3.5 w-3.5" />
                  任务历史
                  {unviewedCount > 0 && (
                    <span className="absolute top-[1px] right-[1px] h-2 w-2 rounded-full bg-blue-500" />
                  )}
                  {runningCount > 0 && (
                    <span className="h-4 min-w-[1rem] flex items-center justify-center rounded-full bg-blue-500 text-white text-[10px] font-bold px-1">
                      {runningCount}
                    </span>
                  )}
                </button>
              );
            })()}
            {activeTab === 'workflows' && (
              <button onClick={() => setShowAddModal(true)}
                className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-lg bg-foreground text-white hover:bg-foreground/90 transition-colors">
                <Plus className="h-4 w-4" /> 新建工作流
              </button>
            )}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto">
          {activeTab === 'workflows' ? (
            <div className="p-8">
              {loading ? (
                <div className="flex items-center justify-center py-32">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : workflows.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-32">
                  <div className="h-20 w-20 rounded-3xl bg-gradient-to-br from-violet-50 to-purple-100 flex items-center justify-center mb-6">
                    <Zap className="h-10 w-10 text-violet-500" />
                  </div>
                  <h3 className="text-lg font-semibold mb-2">暂无工作流</h3>
                  <p className="text-sm text-muted-foreground mb-6">创建第一个 Dify 工作流，开启 AI 能力</p>
                  <button onClick={() => setShowAddModal(true)}
                    className="flex items-center gap-2 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-white hover:bg-foreground/90 transition-colors">
                    <Plus className="h-4 w-4" /> 新建工作流
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
                  {workflows.map(wf => {
                    const Icon = typeIcons[wf.appType] || Zap;
                    const gradient = typeColors[wf.appType] || typeColors.workflow;
                    const wfTasks = tasks.filter(t => t.workflow_id === wf.id);
                    const hasRunning = wfTasks.some(t => t.status === 'running' || t.status === 'pending');
                    const lastTask = wfTasks.length > 0 ? wfTasks[0] : null;
                    return (
                      <div key={wf.id}
                        className={cn(
                          'group relative rounded-2xl bg-white border border-neutral-200/60 p-4',
                          'flex flex-col items-center text-center',
                          'hover:border-neutral-300 hover:shadow-lg hover:shadow-neutral-200/50',
                          'transition-all duration-200 cursor-default',
                          hasRunning && 'border-blue-300 shadow-md shadow-blue-100/50',
                        )}>
                        {/* Three dots menu (top-right) */}
                        <div className="absolute top-2 right-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setOpenDropdown(openDropdown === wf.id ? null : wf.id);
                            }}
                            className="rounded-md p-1 hover:bg-neutral-100 transition-colors"
                          >
                            <MoreVertical className="h-3.5 w-3.5 text-neutral-500" />
                          </button>
                          {openDropdown === wf.id && (
                            <div className="absolute right-0 top-full mt-1 w-28 rounded-lg border bg-white shadow-lg py-1 z-20">
                              <button
                                onClick={() => { setEditingWorkflow(wf); setOpenDropdown(null); }}
                                className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left hover:bg-neutral-50 transition-colors"
                              >
                                <Edit2 className="h-3 w-3" /> 编辑
                              </button>
                              <button
                                onClick={() => { handleDelete(wf.id); setOpenDropdown(null); }}
                                className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left text-red-500 hover:bg-red-50 transition-colors"
                              >
                                <Trash2 className="h-3 w-3" /> 删除
                              </button>
                            </div>
                          )}
                        </div>

                        {/* Gradient Icon */}
                        <div className={cn(
                          'h-14 w-14 rounded-2xl bg-gradient-to-br flex items-center justify-center mb-3',
                          'transition-transform duration-200 group-hover:scale-105',
                          gradient,
                        )}>
                          <Icon className="h-7 w-7 text-white" />
                        </div>

                        {/* Name */}
                        <h3 className="text-sm font-semibold mb-1 line-clamp-2 w-full">{wf.name}</h3>
                        {wf.description && (
                          <p className="text-[11px] text-muted-foreground mb-2 line-clamp-2 w-full">{wf.description}</p>
                        )}

                        {/* Status indicator */}
                        <div className="mt-auto w-full pt-2 border-t border-neutral-100 flex items-center justify-center gap-1.5">
                          {hasRunning ? (
                            <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
                          ) : lastTask ? (
                            <span className={cn('h-2 w-2 rounded-full',
                              lastTask.status === 'succeeded' ? 'bg-emerald-500' : 'bg-red-400')} />
                          ) : (
                            <span className="h-2 w-2 rounded-full bg-neutral-200" />
                          )}
                        </div>

                        {/* Run button */}
                        {!hasRunning && (
                          <div className="absolute inset-x-3 bottom-2.5 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                            <button onClick={() => setRunningWorkflow(wf)}
                              className="w-full flex items-center justify-center gap-1 rounded-md bg-green-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-green-700 transition-colors">
                              <Play className="h-3 w-3" /> 运行
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}

                  {/* Add Card */}
                  <button onClick={() => setShowAddModal(true)}
                    className="rounded-2xl border-2 border-dashed border-neutral-200 p-4 flex flex-col items-center justify-center gap-3 text-muted-foreground hover:border-neutral-300 hover:text-foreground hover:bg-white/50 transition-all min-h-[200px]">
                    <Plus className="h-8 w-8" />
                    <span className="text-sm font-medium">新建工作流</span>
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="p-8">
              <div className="mb-6">
                <div className="relative max-w-sm">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <input type="text" value={logSearch} onChange={(e) => setLogSearch(e.target.value)}
                    placeholder="搜索工作流名称..."
                    className="w-full rounded-lg border bg-white py-2 pl-9 pr-3 text-sm placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
                </div>
              </div>
              <div className="bg-white rounded-xl border border-neutral-200/60 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="border-b border-neutral-100">
                    <tr>
                      {['工作流', '状态', '输入参数', '输出结果', '运行时间', '耗时'].map(h => (
                        <th key={h} className="text-left px-5 py-3 font-medium text-xs text-muted-foreground">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-50">
                    {filteredLogs.map(log => {
                      const wfName = workflows.find(w => w.id === Number(log.workflow_id))?.name || '#' + log.workflow_id;
                      const s = statusConfig[log.status] || statusConfig.failed;
                      const outputText = log.outputs ? extractOutput(log.outputs) : '-';
                      return (
                        <tr key={log.id} className="hover:bg-neutral-50/50 transition-colors">
                          <td className="px-5 py-3.5 font-medium text-sm">{wfName}</td>
                          <td className="px-5 py-3.5">
                            <span className={cn('flex items-center gap-1.5 text-xs font-medium', s.text)}>
                              <span className={cn('h-1.5 w-1.5 rounded-full', s.dot)} />
                              {s.label}
                            </span>
                          </td>
                          <td className="px-5 py-3.5 text-xs text-muted-foreground max-w-[180px] truncate">
                            {Object.entries(log.inputs || {}).map(([, v]) => String(v)).join(', ') || '-'}
                          </td>
                          <td className="px-5 py-3.5 text-xs max-w-[280px]">
                            {outputText.startsWith('http') ? (
                              <a href={outputText} target="_blank" rel="noopener noreferrer"
                                className="text-blue-600 hover:underline break-all">{outputText}</a>
                            ) : (
                              <span className="text-muted-foreground break-all">{outputText}</span>
                            )}
                          </td>
                          <td className="px-5 py-3.5 text-xs tabular-nums whitespace-nowrap text-muted-foreground">
                            {log.started_at ? formatDateTime(log.started_at) : '-'}
                          </td>
                          <td className="px-5 py-3.5 text-xs tabular-nums text-muted-foreground">
                            {log.elapsed_ms ? (log.elapsed_ms / 1000).toFixed(1) + 's' : '-'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {filteredLogs.length === 0 && (
                  <div className="text-center py-16 text-sm text-muted-foreground">暂无运行记录</div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ---- Task Drawer ---- */}
      {showTaskPanel && (
        <div className="fixed right-0 top-0 bottom-0 w-96 bg-white border-l border-neutral-200/60 shadow-xl z-40 flex flex-col">
          <div className="flex items-center justify-between px-5 py-4 border-b border-neutral-100">
            <h3 className="text-sm font-semibold">任务历史</h3>
            <button onClick={() => setShowTaskPanel(false)}
              className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors">
              <PanelRightClose className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 overflow-auto p-4 space-y-3">
            {tasks.length === 0 ? (
              <div className="text-center py-16 text-sm text-muted-foreground">暂无任务</div>
            ) : (
              [...tasks].sort((a, b) => {
                const o: Record<string, number> = { running: 0, pending: 1, succeeded: 2, failed: 3 };
                return (o[a.status] ?? 4) - (o[b.status] ?? 4);
              }).map(task => {
                const s = statusConfig[task.status] || statusConfig.failed;
                const canDelete = task.status !== 'running' && task.status !== 'pending';
                return (
                  <div key={task.id}
                    className={cn(
                      'rounded-xl border transition-all overflow-hidden',
                      task.status === 'running' ? 'border-blue-200 bg-blue-50/40' :
                      task.status === 'succeeded' ? 'border-emerald-100 bg-emerald-50/30' :
                      task.status === 'failed' ? 'border-red-100 bg-red-50/30' :
                      'border-neutral-100',
                    )}>
                    {/* Clickable header */}
                    <button onClick={() => handleTaskClick(task)}
                      className="w-full p-3.5 text-left">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-semibold truncate flex-1 mr-2">{task.workflow_name}</span>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className={cn('flex items-center gap-1 text-xs font-medium', s.text)}>
                            <span className={cn('h-1.5 w-1.5 rounded-full', s.dot)} />
                            {s.label}
                          </span>
                          {!task.viewed && task.status !== 'running' && task.status !== 'pending' && (
                            <span className="relative flex h-3 w-3">
                              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                              <span className="relative inline-flex rounded-full h-3 w-3 bg-blue-500 ring-2 ring-blue-100"></span>
                            </span>
                          )}
                        </div>
                      </div>

                      {task.status === 'running' && (
                        <div className="flex items-center gap-2 text-[11px] text-blue-600 mb-1.5">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          {task.progress || '正在执行...'}
                        </div>
                      )}
                      {task.status === 'succeeded' && task.outputs && (
                        <div className="text-[11px] text-emerald-700 mb-1.5 truncate">
                          输出: {extractOutput(task.outputs)}
                        </div>
                      )}
                      {task.status === 'failed' && task.error && (
                        <div className="text-[11px] text-red-600 mb-1.5 truncate">
                          {task.error.length > 80 ? task.error.substring(0, 80) + '...' : task.error}
                        </div>
                      )}

                      <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
                        <span>{formatTaskTime(task.created_at)}</span>
                        {task.elapsed_ms && <span>{(task.elapsed_ms / 1000).toFixed(1)}s</span>}
                      </div>
                    </button>

                    {/* Delete button */}
                    {canDelete && (
                      <div className="px-3.5 pb-3 pt-0">
                        <button onClick={() => handleDeleteTask(task.id, task.status)}
                          className="w-full flex items-center justify-center gap-1.5 rounded-md bg-white/60 border border-neutral-100 py-1.5 text-[11px] text-muted-foreground hover:text-red-500 hover:border-red-200 hover:bg-red-50 transition-colors">
                          <Trash2 className="h-3 w-3" /> 删除记录
                        </button>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* ---- Modals ---- */}
      {showAddModal && (
        <AddWorkflowModal onClose={() => setShowAddModal(false)}
          onSaved={() => { setShowAddModal(false); fetchWorkflows(); }} />
      )}
      {editingWorkflow && (
        <EditWorkflowModal workflow={editingWorkflow}
          onClose={() => setEditingWorkflow(null)}
          onSaved={() => { setEditingWorkflow(null); fetchWorkflows(); }} />
      )}
      {runningWorkflow && (
        <RunWorkflowModal workflow={runningWorkflow}
          onClose={() => setRunningWorkflow(null)}
          onRun={async (inputs) => {
            await handleRun(runningWorkflow, inputs);
            setRunningWorkflow(null);
          }} />
      )}
      {selectedTask && (
        <TaskDetailModal task={selectedTask} workflows={workflows}
          onClose={() => setSelectedTask(null)} />
      )}
    </div>
  );
}

/* ============================================================
   ADD WORKFLOW MODAL
   ============================================================ */

function AddWorkflowModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [appType, setAppType] = useState('workflow');
  const [description, setDescription] = useState('');
  const [fields, setFields] = useState<WorkflowField[]>([]);
  const dslInputRef = useRef<HTMLInputElement>(null);

  const handleImportDSL = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const content = event.target?.result as string;
        const dsl = file.name.endsWith('.json') ? JSON.parse(content) : yaml.load(content);
        const nodes = dsl?.app?.workflow?.graph?.nodes || dsl?.workflow?.graph?.nodes || dsl?.workflow?.nodes || dsl?.graph?.nodes;
        if (!nodes) throw new Error('无法解析 DSL');
        const startNode = nodes.find((n: any) => n.data?.type === 'start');
        if (!startNode) throw new Error('未找到 Start 节点');
        const variables = startNode.data?.variables || [];
        if (!variables.length) { alert('Start 节点没有定义变量'); return; }
        setFields(variables.map((v: any) => ({
          variable: v.variable || v.name || '', label: v.label || v.variable || v.name || '',
          type: ['text-input', 'paragraph', 'number', 'select'].includes(v.type) ? v.type : 'text-input',
          required: v.required || false, placeholder: v.placeholder || '',
          hint: v.hint || '', options: Array.isArray(v.options) ? v.options.join(', ') : '',
        })));
        if (!name.trim()) setName(dsl.app?.name || dsl.workflow?.name || file.name.replace(/\.(yml|yaml|json)$/, ''));
      } catch (err: any) { alert('DSL 解析失败: ' + err.message); }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const addField = () => setFields(p => [...p, { variable: '', label: '', type: 'text-input', required: false, placeholder: '', hint: '', options: '' }]);
  const removeField = (i: number) => setFields(p => p.filter((_, idx) => idx !== i));
  const updateField = (i: number, key: keyof WorkflowField, val: string | boolean) => setFields(p => p.map((f, idx) => idx === i ? { ...f, [key]: val } : f));

  const handleAdd = async () => {
    if (!name.trim() || !apiKey.trim()) return;
    const vars = fields.map(f => f.variable.trim()).filter(Boolean);
    if (new Set(vars).size !== vars.length) { alert('变量名不能重复'); return; }
    const inputsSchema: Record<string, any> = {};
    for (const f of fields) {
      if (!f.variable.trim()) continue;
      inputsSchema[f.variable.trim()] = {
        label: f.label.trim() || f.variable.trim(), type: f.type, required: f.required,
        placeholder: f.placeholder.trim(), hint: f.hint.trim(), max_length: null,
        options: f.options.split(',').map(s => s.trim()).filter(Boolean), default: '',
      };
    }
    try {
      await difyApi.createWorkflow({
        api_key: apiKey.trim(), app_name: name, app_type: appType,
        description: description || undefined,
        inputs_schema: Object.keys(inputsSchema).length > 0 ? inputsSchema : undefined,
      });
      onSaved();
    } catch (e: any) { alert('添加失败: ' + (e?.response?.data?.detail || e?.message || '未知错误')); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl border w-[580px] overflow-hidden flex flex-col max-h-[85vh]" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h3 className="text-sm font-semibold">新建工作流</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4 overflow-auto flex-1">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">API Key</label>
              <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="app-xxx-xxx"
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">名称</label>
              <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="小红书文案生成"
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">类型</label>
              <select value={appType} onChange={e => setAppType(e.target.value)}
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all">
                <option value="workflow">Workflow</option><option value="chat">Chat</option><option value="completion">Completion</option>
              </select>
            </div>
            <div className="col-span-2">
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">描述（可选）</label>
              <input type="text" value={description} onChange={e => setDescription(e.target.value)}
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium">输入字段</label>
              <div className="flex items-center gap-3">
                <button onClick={() => dslInputRef.current?.click()} className="text-xs text-muted-foreground hover:text-foreground transition-colors">导入 DSL</button>
                <button onClick={addField} className="text-xs text-blue-600 hover:text-blue-700 transition-colors">+ 添加字段</button>
              </div>
            </div>
            <input ref={dslInputRef} type="file" accept=".yml,.yaml,.json" className="hidden" onChange={handleImportDSL} />
            {fields.length === 0 && (
              <div className="rounded-lg border border-dashed p-6 text-center text-xs text-muted-foreground">暂无字段，可手动添加或导入 DSL 文件</div>
            )}
            <div className="space-y-2 mt-2">
              {fields.map((f, idx) => (
                <div key={idx} className="rounded-lg border bg-neutral-50 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-medium text-muted-foreground">字段 {idx + 1}</span>
                    <button onClick={() => removeField(idx)} className="text-[10px] text-red-500 hover:underline">删除</button>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <input type="text" value={f.variable} onChange={e => updateField(idx, 'variable', e.target.value)} placeholder="变量名"
                      className="rounded-lg border bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-foreground/10" />
                    <input type="text" value={f.label} onChange={e => updateField(idx, 'label', e.target.value)} placeholder="显示名称"
                      className="rounded-lg border bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-foreground/10" />
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <select value={f.type} onChange={e => updateField(idx, 'type', e.target.value)}
                      className="rounded-lg border bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-foreground/10">
                      <option value="text-input">文本</option><option value="paragraph">多行</option><option value="number">数字</option><option value="select">选择</option>
                    </select>
                    <input type="text" value={f.placeholder} onChange={e => updateField(idx, 'placeholder', e.target.value)} placeholder="占位提示"
                      className="rounded-lg border bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-foreground/10" />
                    <label className="flex items-center gap-1.5 text-xs pt-1.5 cursor-pointer">
                      <input type="checkbox" checked={f.required} onChange={e => updateField(idx, 'required', e.target.checked)} className="rounded" /> 必填
                    </label>
                  </div>
                  {f.type === 'select' && (
                    <input type="text" value={f.options} onChange={e => updateField(idx, 'options', e.target.value)} placeholder="选项（逗号分隔）"
                      className="w-full rounded-lg border bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-foreground/10" />
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="flex gap-2 p-5 border-t">
          <button onClick={onClose} className="flex-1 rounded-lg border py-2 text-sm hover:bg-neutral-50 transition-colors">取消</button>
          <button onClick={handleAdd} disabled={!name.trim() || !apiKey.trim()}
            className="flex-1 rounded-lg bg-foreground text-white py-2 text-sm hover:bg-foreground/90 transition-colors disabled:opacity-50">创建</button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   EDIT WORKFLOW MODAL
   ============================================================ */

function EditWorkflowModal({ workflow, onClose, onSaved }: { workflow: Workflow; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(workflow.name);
  const [apiKey, setApiKey] = useState(workflow.apiKey || '');
  const [appType, setAppType] = useState(workflow.appType);
  const [description, setDescription] = useState(workflow.description || '');

  const handleSave = async () => {
    if (!name.trim() || !apiKey.trim()) return;
    try {
      await difyApi.updateWorkflow(String(workflow.id), { api_key: apiKey, app_name: name, app_type: appType, description: description || undefined });
      onSaved();
    } catch (e: any) { alert('保存失败: ' + (e?.response?.data?.detail || e?.message || '未知错误')); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl border w-[460px] overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h3 className="text-sm font-semibold">编辑工作流</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">API Key</label>
            <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="app-xxx-xxx"
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">名称</label>
              <input type="text" value={name} onChange={e => setName(e.target.value)}
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">类型</label>
              <select value={appType} onChange={e => setAppType(e.target.value)}
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all">
                <option value="workflow">Workflow</option><option value="chat">Chat</option><option value="completion">Completion</option>
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">描述</label>
            <input type="text" value={description} onChange={e => setDescription(e.target.value)}
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
          </div>
          <div className="flex gap-2 pt-2">
            <button onClick={onClose} className="flex-1 rounded-lg border py-2 text-sm hover:bg-neutral-50 transition-colors">取消</button>
            <button onClick={handleSave} disabled={!name.trim() || !apiKey.trim()}
              className="flex-1 rounded-lg bg-foreground text-white py-2 text-sm hover:bg-foreground/90 transition-colors disabled:opacity-50">保存</button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   RUN WORKFLOW MODAL
   ============================================================ */

function RunWorkflowModal({ workflow, onClose, onRun }: { workflow: Workflow; onClose: () => void; onRun: (inputs: Record<string, string>) => Promise<void> }) {
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const schema = workflow.inputsSchema || {};

  useEffect(() => {
    const defaults: Record<string, string> = {};
    for (const [key, val] of Object.entries(schema)) {
      const v = val as any;
      defaults[key] = v.default || '';
    }
    setFormData(defaults);
  }, [schema]);

  const handleRun = async () => {
    for (const [key, val] of Object.entries(schema)) {
      const v = val as any;
      if (v.required && !formData[key]?.trim()) { alert('请填写必填项: ' + (v.label || key)); return; }
    }
    setRunning(true);
    try { await onRun(formData); } catch (e: any) { alert('运行失败: ' + (e.message || '未知错误')); }
    finally { setRunning(false); }
  };

  const renderField = (key: string, val: any) => {
    const value = formData[key] || '';
    const onChange = (v: string) => setFormData(p => ({ ...p, [key]: v }));
    switch (val.type) {
      case 'paragraph':
        return <textarea value={value} onChange={e => onChange(e.target.value)} placeholder={val.placeholder} rows={4} className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all resize-none" />;
      case 'number':
        return <input type="number" value={value} onChange={e => onChange(e.target.value)} placeholder={val.placeholder} className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />;
      case 'select':
        return (
          <select value={value} onChange={e => onChange(e.target.value)} className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all">
            <option value="">请选择...</option>
            {(val.options || []).map((opt: any) => <option key={typeof opt === 'string' ? opt : opt.value} value={typeof opt === 'string' ? opt : opt.value}>{typeof opt === 'string' ? opt : opt.label}</option>)}
          </select>
        );
      default:
        return <input type="text" value={value} onChange={e => onChange(e.target.value)} placeholder={val.placeholder} maxLength={val.max_length || undefined} className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />;
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl border w-[460px] overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div>
            <h3 className="text-sm font-semibold">{workflow.name}</h3>
            <p className="text-[10px] text-muted-foreground">{workflow.appType}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4 max-h-[60vh] overflow-auto">
          {Object.keys(schema).length === 0 ? (
            <div className="text-center py-8 text-sm text-muted-foreground">该工作流无需输入参数</div>
          ) : (
            Object.keys(schema).map(key => {
              const val = schema[key] as any;
              return (
                <div key={key}>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    {val.label || key}{val.required && <span className="text-red-500 ml-0.5">*</span>}
                  </label>
                  {renderField(key, val)}
                  {val.hint && (
                    <p className="text-[10px] text-muted-foreground mt-1" dangerouslySetInnerHTML={{ __html: val.hint.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') }} />
                  )}
                </div>
              );
            })
          )}
        </div>
        <div className="flex gap-2 p-5 border-t">
          <button onClick={onClose} disabled={running} className="flex-1 rounded-lg border py-2 text-sm hover:bg-neutral-50 transition-colors disabled:opacity-50">取消</button>
          <button onClick={handleRun} disabled={running}
            className="flex-1 rounded-lg bg-green-600 text-white py-2 text-sm hover:bg-green-700 transition-colors disabled:opacity-50">
            {running ? '提交中...' : '提交运行'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   TASK DETAIL MODAL
   ============================================================ */

function TaskDetailModal({ task, workflows, onClose }: { task: Task; workflows: Workflow[]; onClose: () => void }) {
  const s = statusConfig[task.status] || statusConfig.failed;
  const wfName = workflows.find(w => w.id === task.workflow_id)?.name || '#' + task.workflow_id;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl border w-[520px] overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div>
            <h3 className="text-sm font-semibold">任务详情</h3>
            <p className="text-[10px] text-muted-foreground">ID: {task.id}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4 max-h-[60vh] overflow-auto">
          {/* Workflow name */}
          <div className="rounded-lg bg-neutral-50 p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">工作流</div>
            <div className="text-sm font-semibold">{wfName}</div>
          </div>

          {/* Status */}
          <div className="rounded-lg bg-neutral-50 p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">状态</div>
            <span className={cn('flex items-center gap-1.5 text-xs font-medium', s.text)}>
              <span className={cn('h-2 w-2 rounded-full', s.dot)} />
              {s.label}
            </span>
          </div>

          {/* Time info */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-neutral-50 p-3">
              <div className="text-[10px] font-medium text-muted-foreground mb-1">创建时间</div>
              <div className="text-xs tabular-nums">{formatTaskTime(task.created_at)}</div>
            </div>
            <div className="rounded-lg bg-neutral-50 p-3">
              <div className="text-[10px] font-medium text-muted-foreground mb-1">完成时间</div>
              <div className="text-xs tabular-nums">{task.finished_at ? formatTaskTime(task.finished_at) : '-'}</div>
            </div>
          </div>
          {task.elapsed_ms && (
            <div className="rounded-lg bg-neutral-50 p-3">
              <div className="text-[10px] font-medium text-muted-foreground mb-1">耗时</div>
              <div className="text-xs tabular-nums font-medium">{(task.elapsed_ms / 1000).toFixed(1)}s</div>
            </div>
          )}

          {/* Inputs */}
          {task.inputs && Object.keys(task.inputs).length > 0 && (
            <div className="rounded-lg bg-neutral-50 p-3">
              <div className="text-[10px] font-medium text-muted-foreground mb-2">输入参数</div>
              <div className="space-y-1.5">
                {Object.entries(task.inputs).map(([key, val]) => (
                  <div key={key} className="flex gap-2 text-xs">
                    <span className="text-muted-foreground shrink-0 w-24 truncate">{key}:</span>
                    <span className="break-all">{String(val)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Outputs */}
          {task.outputs && Object.keys(task.outputs).length > 0 && (
            <div className="rounded-lg bg-neutral-50 p-3">
              <div className="text-[10px] font-medium text-muted-foreground mb-2">输出结果</div>
              {Object.entries(task.outputs).map(([key, val]) => {
                const text = typeof val === 'string' ? val : JSON.stringify(val, null, 2);
                const isUrl = text.startsWith('http');
                return (
                  <div key={key} className="flex gap-2 text-xs mb-1.5 last:mb-0">
                    <span className="text-muted-foreground shrink-0 w-24 truncate">{key}:</span>
                    {isUrl ? (
                      <a href={text} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline break-all">{text}</a>
                    ) : (
                      <span className="break-all">{text}</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Error */}
          {task.error && (
            <div className="rounded-lg bg-red-50 p-3 border border-red-100">
              <div className="text-[10px] font-medium text-red-500 mb-1">错误信息</div>
              <div className="text-xs text-red-600 break-all whitespace-pre-wrap">{task.error}</div>
            </div>
          )}

          {/* Progress */}
          {task.progress && task.status === 'running' && (
            <div className="rounded-lg bg-blue-50 p-3 border border-blue-100">
              <div className="flex items-center gap-1.5 text-[10px] font-medium text-blue-600 mb-1">
                <Loader2 className="h-3 w-3 animate-spin" /> 进度
              </div>
              <div className="text-xs text-blue-700">{task.progress}</div>
            </div>
          )}
        </div>
        <div className="px-5 py-4 border-t">
          <button onClick={onClose} className="w-full rounded-lg border py-2 text-sm hover:bg-neutral-50 transition-colors">关闭</button>
        </div>
      </div>
    </div>
  );
}
