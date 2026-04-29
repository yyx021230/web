'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { cn } from '@/lib/utils';
import {
  Play, Search, Loader2, X, Trash2,
  PanelRightClose, CheckCircle2, XCircle,
  Zap, FileText, ListTodo, Copy, Download, History,
} from 'lucide-react';
import { difyApi, type DifyWorkflowLog } from '@/services/difyApi';
import { toast } from '@/lib/toast';

interface Workflow {
  id: number;
  name: string;
  description: string | null;
  appType: string;
  enabled: boolean;
  inputsSchema: Record<string, unknown> | null;
}

interface Task {
  id: number;
  workflow_id: number;
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'queued' | 'cancelled';
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  error?: string;
  progress: string;
  elapsed_ms?: number;
  viewed?: number;
  queue_position?: number;
  created_at: string;
  finished_at?: string;
  workflow_name?: string;
}

type WorkflowLog = DifyWorkflowLog;

const typeIcons: Record<string, typeof Zap> = {
  workflow: Zap,
  chat: FileText,
  completion: Zap,
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
  queued: { label: '排队中', icon: Loader2, dot: 'bg-amber-500', text: 'text-amber-600' },
  pending: { label: '排队中', icon: Loader2, dot: 'bg-amber-500', text: 'text-amber-600' },
  cancelled: { label: '已取消', icon: XCircle, dot: 'bg-neutral-400', text: 'text-neutral-500' },
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

/* ============================================================
   MAIN PAGE
   ============================================================ */

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [logs, setLogs] = useState<WorkflowLog[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningWorkflow, setRunningWorkflow] = useState<Workflow | null>(null);
  const [logSearch, setLogSearch] = useState('');
  const [showTaskPanel, setShowTaskPanel] = useState(false);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [activeTab, setActiveTab] = useState<'workflows' | 'logs'>('workflows');
  const pollRef = useRef<number>();

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

  const runningCount = tasks.filter(t => t.status === 'running' || t.status === 'pending' || t.status === 'queued').length;

  const handleDeleteTask = async (taskId: number, status: string) => {
    if (status === 'running') return;
    if (!confirm(status === 'queued' ? '确定要取消此排队中的任务吗？' : '确定要删除此任务记录吗？')) return;
    try {
      await difyApi.deleteTask(String(taskId));
      setTasks(prev => prev.filter(t => t.id !== taskId));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '操作失败');
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
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '提交失败');
    }
  };

  const filteredLogs = logs.filter(log => {
    if (!logSearch) return true;
    const wfName = workflows.find(w => w.id === Number(log.workflow_id))?.name || '';
    return wfName.toLowerCase().includes(logSearch.toLowerCase());
  });

  return (
    <div className="flex h-full bg-[#fafafa]">
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
              const unviewedCount = tasks.filter(t => !t.viewed && t.status !== 'running' && t.status !== 'pending' && t.status !== 'queued').length;
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
                  <p className="text-sm text-muted-foreground">请联系管理员添加工作流</p>
                </div>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
                  {workflows.map(wf => {
                    const Icon = typeIcons[wf.appType] || Zap;
                    const gradient = 'from-violet-500 to-purple-600';
                    const wfTasks = tasks.filter(t => t.workflow_id === wf.id);
                    const hasRunning = wfTasks.some(t => t.status === 'running' || t.status === 'pending' || t.status === 'queued');
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
                        <div className={cn(
                          "inset-x-3 bottom-2.5 transition-opacity duration-200",
                          hasRunning ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                        )}>
                          <button onClick={() => setRunningWorkflow(wf)}
                            className="w-full flex items-center justify-center gap-1 rounded-md bg-green-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-green-700 transition-colors">
                            <Play className="h-3 w-3" /> {hasRunning ? '继续运行' : '运行'}
                          </button>
                        </div>
                      </div>
                    );
                  })}
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
                const o: Record<string, number> = { running: 0, queued: 1, pending: 2, succeeded: 3, failed: 4, cancelled: 5 };
                return (o[a.status] ?? 6) - (o[b.status] ?? 6);
              }).map(task => {
                const s = statusConfig[task.status] || statusConfig.failed;
                const canDelete = task.status !== 'running';
                return (
                  <div key={task.id}
                    className={cn(
                      'rounded-xl border transition-all overflow-hidden',
                      task.status === 'running' ? 'border-blue-200 bg-blue-50/40' :
                      task.status === 'queued' || task.status === 'pending' ? 'border-amber-200 bg-amber-50/40' :
                      task.status === 'succeeded' ? 'border-emerald-100 bg-emerald-50/30' :
                      task.status === 'failed' ? 'border-red-100 bg-red-50/30' :
                      task.status === 'cancelled' ? 'border-neutral-200 bg-neutral-50/30' :
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
                          {!task.viewed && task.status !== 'running' && task.status !== 'pending' && task.status !== 'queued' && (
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
                      {(task.status === 'queued' || task.status === 'pending') && task.queue_position && (
                        <div className="flex items-center gap-2 text-[11px] text-amber-600 mb-1.5">
                          <Loader2 className="h-3 w-3" />
                          排队中，第 {task.queue_position} 位
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

                    {/* Action button */}
                    {canDelete && (
                      <div className="px-3.5 pb-3 pt-0">
                        <button onClick={() => handleDeleteTask(task.id, task.status)}
                          className="w-full flex items-center justify-center gap-1.5 rounded-md bg-white/60 border border-neutral-100 py-1.5 text-[11px] text-muted-foreground hover:text-red-500 hover:border-red-200 hover:bg-red-50 transition-colors">
                          <Trash2 className="h-3 w-3" /> {task.status === 'queued' ? '取消排队' : '删除记录'}
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
      {runningWorkflow && (
        <RunWorkflowModal workflow={runningWorkflow}
          lastTask={tasks.find(t => t.workflow_id === runningWorkflow.id && t.status === 'succeeded')}
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
   RUN WORKFLOW MODAL
   ============================================================ */

function RunWorkflowModal({ workflow, lastTask, onClose, onRun }: { workflow: Workflow; lastTask?: Task; onClose: () => void; onRun: (inputs: Record<string, string>) => Promise<void> }) {
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

  const handleUseLast = () => {
    if (!lastTask?.inputs) return;
    const newFormData = { ...formData };
    for (const [key, val] of Object.entries(lastTask.inputs)) {
      if (key in schema) {
        newFormData[key] = String(val);
      }
    }
    setFormData(newFormData);
    toast.success('已加载上次成功运行的参数');
  };

  const handleRun = async () => {
    for (const [key, val] of Object.entries(schema)) {
      const v = val as any;
      if (v.required && !formData[key]?.trim()) { toast.error('请填写必填项: ' + (v.label || key)); return; }
    }
    setRunning(true);
    try { await onRun(formData); } catch (e: unknown) { toast.error(e instanceof Error ? e.message : '运行失败'); }
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
          <div className="flex items-center gap-2">
            {lastTask && (
              <button
                onClick={handleUseLast}
                title="加载上次成功的参数"
                className="p-1.5 rounded-lg hover:bg-blue-50 text-blue-600 transition-colors border border-blue-100 flex items-center gap-1 text-[10px] font-medium"
              >
                <History className="h-3.5 w-3.5" />
                使用上次参数
              </button>
            )}
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors"><X className="h-4 w-4" /></button>
          </div>
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

  const handleCopy = () => {
    const outputText = extractOutput(task.outputs);
    navigator.clipboard.writeText(outputText).then(() => {
      toast.success('已复制到剪贴板');
    }).catch(() => {
      toast.error('复制失败');
    });
  };

  const handleExport = () => {
    const outputText = extractOutput(task.outputs);
    const blob = new Blob([outputText], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `workflow-result-${task.id}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success('正在下载...');
  };

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
          <div className="rounded-lg bg-neutral-50 p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">工作流</div>
            <div className="text-sm font-semibold">{wfName}</div>
          </div>

          <div className="rounded-lg bg-neutral-50 p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">状态</div>
            <span className={cn('flex items-center gap-1.5 text-xs font-medium', s.text)}>
              <span className={cn('h-2 w-2 rounded-full', s.dot)} />
              {s.label}
            </span>
          </div>

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

          {task.outputs && Object.keys(task.outputs).length > 0 && (
            <div className="rounded-lg bg-neutral-50 p-3 relative group/output">
              <div className="flex items-center justify-between mb-2">
                <div className="text-[10px] font-medium text-muted-foreground">输出结果</div>
                <div className="flex items-center gap-2 opacity-0 group-hover/output:opacity-100 transition-opacity">
                  <button onClick={handleCopy} className="p-1 rounded bg-white border shadow-sm hover:bg-neutral-50 text-neutral-600 transition-colors" title="复制结果">
                    <Copy className="h-3 w-3" />
                  </button>
                  <button onClick={handleExport} className="p-1 rounded bg-white border shadow-sm hover:bg-neutral-50 text-neutral-600 transition-colors" title="导出为 Markdown">
                    <Download className="h-3 w-3" />
                  </button>
                </div>
              </div>
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

          {task.error && (
            <div className="rounded-lg bg-red-50 p-3 border border-red-100">
              <div className="text-[10px] font-medium text-red-500 mb-1">错误信息</div>
              <div className="text-xs text-red-600 break-all whitespace-pre-wrap">{task.error}</div>
            </div>
          )}

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
