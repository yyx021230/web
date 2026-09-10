'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight, ArrowUpRight, CarFront, Loader2, Workflow,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { hermesWorkflowApi, type HermesRun } from '@/services/hermesWorkflowApi';
import WorkflowGalleryCards from '@/components/workflow/WorkflowGalleryCards';

const STATUS: Record<string, { label: string; className: string }> = {
  queued: { label: '等待生产', className: 'border-amber-200 bg-amber-50 text-amber-700' },
  running: { label: '生成中', className: 'border-blue-200 bg-blue-50 text-blue-700' },
  review_pending: { label: '待审核', className: 'border-orange-200 bg-orange-50 text-orange-700' },
  approved: { label: '已通过', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
  changes_requested: { label: '待调整', className: 'border-rose-200 bg-rose-50 text-rose-700' },
  ready_to_publish: { label: '待发布', className: 'border-cyan-200 bg-cyan-50 text-cyan-700' },
  published: { label: '已完成', className: 'border-slate-200 bg-slate-50 text-slate-600' },
  failed: { label: '执行失败', className: 'border-red-200 bg-red-50 text-red-700' },
  partial_failed: { label: '部分失败', className: 'border-red-200 bg-red-50 text-red-700' },
  cancelled: { label: '已取消', className: 'border-slate-200 bg-slate-50 text-slate-500' },
};

function formatDate(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}

function StatusBadge({ status }: { status: string }) {
  const current = STATUS[status] || { label: status, className: 'border-slate-200 bg-slate-50 text-slate-600' };
  return <span className={cn('inline-flex rounded-full border px-2.5 py-1 text-[10px] font-semibold', current.className)}>{current.label}</span>;
}

export default function WorkflowGalleryPage() {
  const [runs, setRuns] = useState<HermesRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    hermesWorkflowApi.listRuns({ limit: 3 })
      .then(response => setRuns(response.data.items || []))
      .catch(error => setLoadError(error instanceof Error ? error.message : '最近项目加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const recentRuns = useMemo(() => runs.slice(0, 3), [runs]);

  return (
    <div className="cloud-page flex h-full min-h-0 flex-col text-slate-950">
      <main className="relative mx-auto w-full min-h-0 flex-1 overflow-y-auto max-w-[1540px] p-4 lg:p-5">
        <section className="cloud-panel relative min-h-[calc(100vh-82px)] overflow-hidden rounded-[30px] px-5 py-4 sm:px-7 lg:px-9">
          <div className="pointer-events-none absolute -right-28 top-8 h-72 w-72 rounded-full bg-indigo-200/25 blur-3xl" />
          <div className="pointer-events-none absolute -left-24 bottom-12 h-64 w-64 rounded-full bg-sky-200/20 blur-3xl" />
          <nav className="relative z-10 flex items-center gap-8 border-b border-slate-200/70 text-sm font-semibold">
            <a href="#gallery" className="relative py-3 text-indigo-600 after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:rounded-full after:bg-indigo-600">工作流广场</a>
            <a href="#recent" className="py-3 text-slate-500 transition hover:text-slate-900">我的项目</a>
          </nav>
          <header id="gallery" className="relative z-10 mx-auto max-w-3xl py-6 text-center">
            <h1 className="text-xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-[25px]">让每一次创作，顺手一点</h1>
            <p className="mt-2 text-xs text-slate-500">批量创作 · 精准单篇 · 发布排期</p>
          </header>

          <WorkflowGalleryCards />

          <section id="recent" className="relative z-10 mt-5 scroll-mt-5">
            <div className="mb-3 flex items-end justify-between px-1"><h2 className="text-sm font-semibold text-slate-950">最近项目</h2><Link href="/workflows/hermes#history" className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-slate-500 transition hover:text-indigo-600">查看全部 <ArrowUpRight className="h-3.5 w-3.5" /></Link></div>
            <div className="overflow-hidden rounded-[22px] border border-white/80 bg-white/58 shadow-[0_14px_38px_rgba(77,91,138,.07)] backdrop-blur-xl">
              {loadError && <div role="alert" className="p-5 text-xs text-rose-600">{loadError}，请刷新页面重试。</div>}
              {loading && <div className="flex items-center justify-center gap-2 py-8 text-xs text-slate-400"><Loader2 className="h-4 w-4 animate-spin" />加载最近项目</div>}
              {!loading && recentRuns.length === 0 && <div className="flex items-center justify-center gap-2 py-8 text-xs text-slate-400"><Workflow className="h-5 w-5 opacity-40" />还没有项目，进入批量或单篇模块创建第一批内容</div>}
              {recentRuns.map((run, index) => {
                const accountNames = run.accounts || [];
                const name = accountNames.length > 1 ? `${accountNames.length}个账号` : accountNames[0] || `Hermes 任务 #${run.id}`;
                const status = run.assigned_status || run.status;
                return <Link key={run.id} href={`/workflows/hermes${run.source === 'manual' ? '/single' : '' }?run=${run.id}`} className={cn('group grid items-center gap-3 px-4 py-2.5 transition hover:bg-indigo-50/45 sm:grid-cols-[48px_1fr_auto_auto]', index > 0 && 'border-t border-slate-100/90')}><div className="flex h-10 w-12 items-center justify-center overflow-hidden rounded-xl bg-gradient-to-br from-sky-100 to-indigo-100"><CarFront className="h-5 w-5 text-indigo-500" /></div><div className="min-w-0"><h3 className="truncate text-xs font-semibold text-slate-900">{formatDate(run.created_at).split(' ')[0]} · {name} · {run.assigned_posts || run.total_posts}篇</h3><p className="mt-0.5 truncate text-[10px] text-slate-500">{(run.vehicles || []).join('、') || '汽车图文运营'} · 已生成 {run.assigned_generated ?? run.generated_posts}/{run.assigned_posts || run.total_posts}</p></div><StatusBadge status={status} /><ArrowRight className="h-3.5 w-3.5 text-slate-400 transition group-hover:translate-x-1 group-hover:text-indigo-600" /></Link>;
              })}
            </div>
          </section>
        </section>
      </main>
    </div>
  );
}
