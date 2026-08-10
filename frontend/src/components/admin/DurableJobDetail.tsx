'use client';

import type { ReactNode } from 'react';
import {
  AlertTriangle,
  Boxes,
  Clock3,
  Cpu,
  GitBranch,
  History,
  KeyRound,
  Layers3,
  ShieldCheck,
  X,
} from 'lucide-react';
import type { DurableJobDetail as DurableJobDetailData } from '@/services/adminApi';
import { formatLocalDateTime } from '@/lib/dateTime';
import { cn } from '@/lib/utils';

const STATUS_LABELS: Record<string, string> = {
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

const STATUS_STYLES: Record<string, string> = {
  queued: 'bg-slate-100 text-slate-700 border-slate-200',
  leased: 'bg-cyan-50 text-cyan-700 border-cyan-200',
  running: 'bg-blue-50 text-blue-700 border-blue-200',
  retry_wait: 'bg-amber-50 text-amber-700 border-amber-200',
  waiting_review: 'bg-orange-50 text-orange-700 border-orange-200',
  succeeded: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  failed: 'bg-rose-50 text-rose-700 border-rose-200',
  cancelled: 'bg-zinc-100 text-zinc-600 border-zinc-200',
  dead_letter: 'bg-red-950 text-red-50 border-red-900',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold',
        STATUS_STYLES[status] || STATUS_STYLES.queued,
      )}
    >
      {STATUS_LABELS[status] || status}
    </span>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-xl border border-slate-200 bg-slate-950 p-4 font-mono text-[11px] leading-5 text-slate-200 whitespace-pre-wrap break-all">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">{label}</div>
      <div className="mt-1.5 break-all text-sm font-semibold text-slate-800">{value || '-'}</div>
    </div>
  );
}

export function DurableJobDetail({
  task,
  loading,
  onClose,
}: {
  task: DurableJobDetailData | null;
  loading: boolean;
  onClose: () => void;
}) {
  const progress = task?.progress_total
    ? Math.min(100, Math.round((task.progress_current / task.progress_total) * 100))
    : 0;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/25 backdrop-blur-[2px]">
      <button type="button" aria-label="关闭任务详情" className="absolute inset-0 cursor-default" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-[760px] flex-col border-l border-slate-200 bg-[#f8fafc] shadow-2xl">
        <header className="shrink-0 border-b border-slate-200 bg-white px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                <ShieldCheck className="h-4 w-4 text-emerald-600" />
                Durable Job Evidence
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <h2 className="text-xl font-bold tracking-tight text-slate-950">
                  {task ? `任务 #${task.id}` : '任务详情'}
                </h2>
                {task && <StatusBadge status={task.status} />}
              </div>
              <p className="mt-1.5 text-xs text-slate-500">
                状态、分片、执行尝试和审计事件均来自统一任务内核，只读展示。
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-slate-200 bg-white p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          {loading || !task ? (
            <div className="space-y-4 animate-pulse">
              <div className="grid grid-cols-2 gap-3">
                {Array.from({ length: 4 }).map((_, index) => (
                  <div key={index} className="h-20 rounded-xl bg-slate-200/70" />
                ))}
              </div>
              <div className="h-48 rounded-2xl bg-slate-200/70" />
              <div className="h-64 rounded-2xl bg-slate-200/70" />
            </div>
          ) : (
            <div className="space-y-6">
              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <Metric label="任务类型" value={task.job_type} />
                  <Metric label="执行器" value={task.worker_type} />
                  <Metric label="负责人" value={task.display_name || task.username || '系统'} />
                  <Metric label="重试" value={`${task.retry_count} / ${task.max_retries}`} />
                </div>
                <div className="mt-5">
                  <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
                    <span>{task.current_step || '尚未报告当前步骤'}</span>
                    <span>{task.progress_total ? `${task.progress_current}/${task.progress_total}` : '未设置总进度'}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-slate-900 transition-all" style={{ width: `${progress}%` }} />
                  </div>
                </div>
              </section>

              {(task.error_code || task.user_message || task.cancel_requested) && (
                <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
                  <div className="flex gap-3">
                    <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
                    <div>
                      <div className="text-sm font-semibold text-amber-950">任务需要关注</div>
                      <div className="mt-1 text-sm leading-6 text-amber-800">
                        {task.user_message || (task.cancel_requested ? '已收到取消请求，等待执行器确认。' : task.error_code)}
                      </div>
                      {task.error_code && <div className="mt-2 font-mono text-xs text-amber-700">{task.error_code}</div>}
                    </div>
                  </div>
                </section>
              )}

              <section className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <Metric label="公开任务 ID" value={task.public_id} />
                <Metric label="幂等键" value={task.idempotency_key || '-'} />
                <Metric label="业务来源" value={[task.source_type, task.source_id].filter(Boolean).join(' / ') || '-'} />
                <Metric label="作用域" value={task.scope_key} />
                <Metric label="创建时间" value={formatLocalDateTime(task.created_at)} />
                <Metric label="完成时间" value={formatLocalDateTime(task.finished_at)} />
              </section>

              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-4 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
                    <Boxes className="h-4 w-4 text-slate-500" />
                    分片结果
                  </div>
                  <span className="text-xs text-slate-400">{task.diagnostics.item_count} 项</span>
                </div>
                {task.items.length ? (
                  <div className="space-y-2">
                    {task.items.map((item) => (
                      <div key={item.id} className="rounded-xl border border-slate-200 px-4 py-3">
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold text-slate-800">{item.display_name || item.item_key}</div>
                            <div className="mt-1 font-mono text-[11px] text-slate-400">{item.item_type || 'item'} · {item.item_key}</div>
                          </div>
                          <StatusBadge status={item.status} />
                        </div>
                        {(item.user_message || item.error_code) && (
                          <div className="mt-2 text-xs text-rose-600">{item.user_message || item.error_code}</div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-slate-200 py-8 text-center text-sm text-slate-400">该任务没有分片记录</div>
                )}
              </section>

              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-4 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
                    <Cpu className="h-4 w-4 text-slate-500" />
                    执行尝试
                  </div>
                  <span className="text-xs text-slate-400">{task.diagnostics.attempt_count} 次</span>
                </div>
                {task.attempts.length ? (
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    {task.attempts.map((attempt) => (
                      <div key={attempt.id} className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-sm font-semibold text-slate-800">第 {attempt.attempt_number} 次</div>
                          <StatusBadge status={attempt.status} />
                        </div>
                        <div className="mt-3 space-y-1.5 text-xs text-slate-500">
                          <div>Worker：{attempt.worker_id || '-'}</div>
                          <div>开始：{formatLocalDateTime(attempt.started_at)}</div>
                          <div>结束：{formatLocalDateTime(attempt.finished_at)}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-slate-200 py-8 text-center text-sm text-slate-400">影子任务不会创建真实执行尝试</div>
                )}
              </section>

              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-5 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
                    <History className="h-4 w-4 text-slate-500" />
                    事件时间线
                  </div>
                  <span className="text-xs text-slate-400">{task.diagnostics.event_count} 条</span>
                </div>
                <div className="space-y-0">
                  {task.events.map((event, index) => (
                    <div key={event.id} className="relative flex gap-4 pb-5 last:pb-0">
                      {index < task.events.length - 1 && <div className="absolute left-[7px] top-5 h-full w-px bg-slate-200" />}
                      <div className={cn('relative mt-1.5 h-[15px] w-[15px] shrink-0 rounded-full border-[3px] border-white ring-1 ring-slate-200', event.level === 'error' ? 'bg-rose-500' : event.level === 'warning' ? 'bg-amber-500' : 'bg-slate-700')} />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="text-sm font-semibold text-slate-800">{event.message || event.event_type}</div>
                          <div className="text-[11px] text-slate-400">{formatLocalDateTime(event.created_at)}</div>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                          <span>{event.event_type}</span>
                          {(event.from_status || event.to_status) && <span>{event.from_status || '-'} → {event.to_status || '-'}</span>}
                          <span>{event.actor_type}{event.actor_id ? `:${event.actor_id}` : ''}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800"><Layers3 className="h-4 w-4" />输入快照</div>
                  <JsonBlock value={task.payload} />
                </div>
                <div>
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800"><GitBranch className="h-4 w-4" />结果摘要</div>
                  <JsonBlock value={task.result_summary} />
                </div>
              </section>

              <footer className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-2xl border border-slate-200 bg-white px-5 py-4 text-xs text-slate-500">
                <span className="flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5" />最近更新 {formatLocalDateTime(task.updated_at)}</span>
                <span className="flex items-center gap-1.5"><KeyRound className="h-3.5 w-3.5" />敏感字段已脱敏</span>
              </footer>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
