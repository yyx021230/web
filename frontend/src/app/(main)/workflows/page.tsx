'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  ArrowRight, ArrowUpRight, CarFront, CircleCheck, Loader2, Workflow,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { hermesWorkflowApi, type HermesRun } from '@/services/hermesWorkflowApi';
import WorkflowGalleryCards from '@/components/workflow/WorkflowGalleryCards';
import styles from '@/components/workflow/workflow-workspace.module.css';

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
  return <span className={cn(styles.statusBadge, current.className)}>{current.label}</span>;
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

  const recentRuns = runs.slice(0, 3);

  return (
    <div className={styles.page}>
      <main className={styles.scrollArea}>
        <section id="gallery" className={styles.workspaceHero}>
          <h1>选择工作流，快速开始</h1>
          <p>批量生产、单篇创作或安排发布</p>
        </section>

        <WorkflowGalleryCards />

        <section id="recent" className={styles.recentSection}>
          <div className={styles.sectionHeading}>
            <h2>最近项目</h2>
            <Link href="/workflows/hermes#history">查看全部 <ArrowUpRight /></Link>
          </div>
          <div className={styles.runList}>
            {loadError && <div role="alert" className={styles.errorState}>{loadError}，请刷新页面重试。</div>}
            {loading && <div className={styles.emptyState}><Loader2 className="animate-spin" />加载最近项目</div>}
            {!loading && recentRuns.length === 0 && <div className={styles.emptyState}><Workflow />还没有项目，进入批量或单篇模块创建第一批内容</div>}
            {recentRuns.map((run, index) => {
              const accountNames = run.accounts || [];
              const name = accountNames.length > 1 ? `${accountNames.length}个账号` : accountNames[0] || `Hermes 任务 #${run.id}`;
              const status = run.assigned_status || run.status;
              const generated = run.assigned_generated ?? run.generated_posts;
              const total = run.assigned_posts || run.total_posts;
              return (
                <Link key={run.id} href={`/workflows/hermes${run.source === 'manual' ? '/single' : ''}?run=${run.id}`} className={styles.runItem} data-index={index}>
                  <span className={styles.runIcon}>{status === 'published' || status === 'approved' ? <CircleCheck /> : <CarFront />}</span>
                  <div className={styles.runCopy}>
                    <h3>{name}</h3>
                    <p>{formatDate(run.created_at)} · {(run.vehicles || []).join('、') || '汽车图文运营'}</p>
                  </div>
                  <span className={styles.progress}>{generated}/{total}<small>已生成</small></span>
                  <StatusBadge status={status} />
                  <ArrowRight className={styles.runArrow} />
                </Link>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
}
