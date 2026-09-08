'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  CalendarDays, Check, CheckCircle2, ChevronDown, CircleAlert,
  ExternalLink, FileSearch, ImageIcon, Loader2, Maximize2,
  MessageSquareText, X, XCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from '@/lib/toast';
import { hermesWorkflowApi, type HermesPost, type HermesRun } from '@/services/hermesWorkflowApi';
import { HermesStatusBadge } from '@/components/workflow/HermesCreationHistory';

interface HermesReviewWorkspaceProps {
  run: HermesRun | null;
  loading: boolean;
  onClose: () => void;
  onReload: (runId: number) => Promise<void>;
}

function formatDate(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}

function postLabel(post: HermesPost) {
  return `${post.account_name} · 第 ${post.slot} 篇`;
}

export default function HermesReviewWorkspace({ run, loading, onClose, onReload }: HermesReviewWorkspaceProps) {
  const [reviewingId, setReviewingId] = useState<number | null>(null);
  const [reviewNotes, setReviewNotes] = useState<Record<number, string>>({});
  const [expandedPosts, setExpandedPosts] = useState<Record<number, boolean>>({});
  const [notePosts, setNotePosts] = useState<Record<number, boolean>>({});
  const [lightboxPost, setLightboxPost] = useState<HermesPost | null>(null);

  useEffect(() => {
    setExpandedPosts({});
    setNotePosts({});
    setLightboxPost(null);
  }, [run?.id]);

  const task = useMemo(() => {
    if (!run) return null;
    const accounts = (run.accounts || []).join('、') || run.posts?.[0]?.account_name || '内容账号';
    const vehicles = (run.vehicles || []).join('、') || run.posts?.[0]?.vehicle_model || '新能源车型';
    const total = run.assigned_posts || run.total_posts || run.posts?.length || 0;
    const generated = run.assigned_generated ?? run.generated_posts;
    return {
      accounts,
      vehicles,
      total,
      generated,
      percent: total ? Math.round((generated / total) * 100) : 0,
      title: `${vehicles}｜${total}篇小红书图文任务`,
    };
  }, [run]);

  if (!run && !loading) return null;

  async function review(post: HermesPost, action: 'approve' | 'reject') {
    const note = reviewNotes[post.id] || '';
    if (action === 'reject' && !note.trim()) {
      setNotePosts(current => ({ ...current, [post.id]: true }));
      toast.error('退回内容时请先填写修改意见');
      return;
    }
    setReviewingId(post.id);
    try {
      await hermesWorkflowApi.reviewPost(post.id, action, note);
      toast.success(action === 'approve' ? '已通过这篇内容' : '已退回并记录修改意见');
      await onReload(post.run_id);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '审核失败');
    } finally {
      setReviewingId(null);
    }
  }

  return (
    <div className="fixed inset-0 z-[90] bg-slate-950/45 p-2 backdrop-blur-sm sm:p-4" onMouseDown={event => event.target === event.currentTarget && onClose()}>
      <section className="cloud-page mx-auto flex h-full w-full max-w-[1660px] flex-col overflow-hidden rounded-[26px] border border-white/85 shadow-[0_36px_110px_rgba(15,23,42,.28)]">
        {loading && !run ? (
          <div className="flex h-full items-center justify-center gap-3 text-sm text-slate-500"><Loader2 className="h-5 w-5 animate-spin text-indigo-500" />加载任务里的全部帖子</div>
        ) : run && task && (
          <>
            <header className="relative z-20 shrink-0 border-b border-slate-200/80 bg-white/91 px-4 py-4 backdrop-blur-xl sm:px-6">
              <div className="absolute inset-y-0 left-0 w-1.5 bg-gradient-to-b from-sky-500 via-indigo-500 to-violet-500" />
              <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-center">
                <div className="min-w-0 pl-2">
                  <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[.16em] text-indigo-500">
                    <span>任务名称</span><span className="h-1 w-1 rounded-full bg-slate-300" /><span>Hermes Run #{run.id}</span>
                  </div>
                  <h2 className="mt-1.5 truncate text-xl font-semibold tracking-[-.03em] text-slate-950 sm:text-2xl">{task.title}</h2>
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
                    <span className="font-semibold text-slate-700">{task.accounts}</span>
                    <span className="inline-flex items-center gap-1.5"><CalendarDays className="h-3.5 w-3.5" />{formatDate(run.created_at)}</span>
                    <span>每篇内容独立审核，完整图片不裁切</span>
                  </div>
                </div>
                <div className="flex items-center gap-3 pl-2 xl:pl-0">
                  <HermesStatusBadge status={run.assigned_status || run.status} />
                  <div className="hidden min-w-[210px] sm:block">
                    <div className="mb-1.5 flex items-center justify-between text-[10px] font-medium text-slate-500"><span>{task.generated}/{task.total} 已生成</span><span>{task.percent}%</span></div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-gradient-to-r from-sky-500 to-indigo-500" style={{ width: `${task.percent}%` }} /></div>
                  </div>
                  <button type="button" onClick={onClose} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600" aria-label="关闭任务详情"><X className="h-4 w-4" /></button>
                </div>
              </div>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto bg-[radial-gradient(circle_at_top_left,rgba(224,231,255,.5),transparent_34%),linear-gradient(180deg,rgba(248,250,252,.9),rgba(241,245,249,.82))] p-3 sm:p-5">
              {run.error && <div className="mb-4 flex gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />{run.error}</div>}

              <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {(run.posts || []).map(post => {
                  const expanded = Boolean(expandedPosts[post.id]);
                  const noteOpen = Boolean(notePosts[post.id]);
                  return (
                    <article key={post.id} className="group overflow-hidden rounded-[22px] border border-white bg-white shadow-[0_12px_35px_rgba(71,85,105,.10)] transition duration-300 hover:-translate-y-0.5 hover:shadow-[0_20px_50px_rgba(71,85,105,.16)]">
                      <button type="button" onClick={() => post.image_url && setLightboxPost(post)} className="relative block aspect-[4/3] w-full overflow-hidden border-b border-slate-100 bg-[linear-gradient(135deg,#eef2ff,#f8fafc_48%,#e0f2fe)] text-left">
                        {post.image_url ? <img src={post.image_url} alt={post.title || postLabel(post)} className="h-full w-full object-contain transition duration-500 group-hover:scale-[1.015]" /> : <span className="flex h-full flex-col items-center justify-center text-slate-400"><ImageIcon className="mb-2 h-8 w-8" /><span className="text-xs">图片生成中</span></span>}
                        <span className="absolute left-3 top-3 rounded-full border border-white/80 bg-white/90 px-2.5 py-1 text-[9px] font-semibold text-slate-700 shadow-sm backdrop-blur">POST {String(post.slot).padStart(2, '0')}</span>
                        {post.image_url && <span className="absolute bottom-3 right-3 flex h-8 w-8 items-center justify-center rounded-xl border border-white/80 bg-white/90 text-slate-600 opacity-0 shadow-sm backdrop-blur transition group-hover:opacity-100"><Maximize2 className="h-3.5 w-3.5" /></span>}
                      </button>

                      <div className="p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0"><div className="truncate text-[9px] font-semibold uppercase tracking-[.14em] text-indigo-500">{postLabel(post)}</div><h3 className="mt-1.5 min-h-[48px] text-base font-semibold leading-6 text-slate-950">{post.title || '等待 Hermes 生成'}</h3></div>
                          <HermesStatusBadge status={post.status} />
                        </div>

                        <div className="relative mt-3 rounded-2xl border border-slate-100 bg-slate-50/80">
                          <div className={cn('whitespace-pre-wrap px-3.5 py-3 text-[12px] leading-[1.75] text-slate-600 transition-all', expanded ? 'max-h-none' : 'max-h-[178px] overflow-hidden')}>
                            {post.content || '内容尚未生成完成。'}
                          </div>
                          {!expanded && post.content && post.content.length > 180 && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-slate-50 via-slate-50/95 to-transparent" />}
                          {post.content && post.content.length > 180 && <button type="button" onClick={() => setExpandedPosts(current => ({ ...current, [post.id]: !expanded }))} className="relative z-10 flex w-full items-center justify-center gap-1 border-t border-slate-100 py-2 text-[10px] font-semibold text-indigo-600 hover:bg-indigo-50/60">{expanded ? '收起正文' : '展开完整正文'}<ChevronDown className={cn('h-3 w-3 transition', expanded && 'rotate-180')} /></button>}
                        </div>

                        {post.review_comment && <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-[11px] leading-5 text-rose-800">上次意见：{post.review_comment}</div>}

                        {post.status === 'review_pending' && (
                          <div className="mt-3">
                            {noteOpen && <textarea autoFocus value={reviewNotes[post.id] || ''} onChange={event => setReviewNotes(current => ({ ...current, [post.id]: event.target.value }))} placeholder="填写要修改的问题，再点击退回" className="mb-2 min-h-20 w-full resize-none rounded-2xl border border-rose-200 bg-rose-50/60 p-3 text-xs leading-5 text-slate-700 outline-none focus:border-rose-300 focus:ring-4 focus:ring-rose-100" />}
                            <div className="grid grid-cols-2 gap-2">
                              <button type="button" disabled={reviewingId === post.id} onClick={() => review(post, 'approve')} className="flex h-10 items-center justify-center gap-2 rounded-2xl bg-slate-950 text-xs font-semibold text-white transition hover:bg-indigo-600 disabled:opacity-50">{reviewingId === post.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}审核通过</button>
                              <button type="button" disabled={reviewingId === post.id} onClick={() => noteOpen && (reviewNotes[post.id] || '').trim() ? review(post, 'reject') : setNotePosts(current => ({ ...current, [post.id]: true }))} className="flex h-10 items-center justify-center gap-2 rounded-2xl border border-rose-200 bg-white text-xs font-semibold text-rose-600 transition hover:bg-rose-50 disabled:opacity-50"><MessageSquareText className="h-4 w-4" />{noteOpen ? '确认退回' : '退回修改'}</button>
                            </div>
                          </div>
                        )}

                        {post.status === 'approved' && <div className="mt-3 flex items-center gap-2 rounded-2xl bg-emerald-50 p-3 text-[11px] font-semibold text-emerald-800"><CheckCircle2 className="h-4 w-4" />已通过，等待统一发布</div>}
                        {post.status === 'rejected' && <div className="mt-3 flex items-center gap-2 rounded-2xl bg-rose-50 p-3 text-[11px] font-semibold text-rose-700"><XCircle className="h-4 w-4" />已退回，等待重新生成</div>}
                      </div>

                      {post.source_detail && Object.keys(post.source_detail).length > 0 && (
                        <details className="border-t border-slate-100 bg-white px-4 py-3">
                          <summary className="flex cursor-pointer list-none items-center justify-between text-[10px] font-semibold text-slate-600 [&::-webkit-details-marker]:hidden"><span className="inline-flex items-center gap-2"><FileSearch className="h-3.5 w-3.5 text-indigo-500" />母文、母图与改造依据</span><ChevronDown className="h-3 w-3" /></summary>
                          <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-2xl bg-slate-950 p-3 text-[10px] leading-5 text-slate-200">{JSON.stringify(post.source_detail, null, 2)}</pre>
                        </details>
                      )}
                    </article>
                  );
                })}
              </div>

              {!loading && !(run.posts || []).length && <div className="flex min-h-[360px] flex-col items-center justify-center rounded-[24px] border border-dashed border-slate-300 bg-white/60 text-slate-400"><ImageIcon className="mb-3 h-9 w-9" /><p className="text-sm">这个任务暂时还没有可展示的帖子</p></div>}
            </div>
          </>
        )}
      </section>

      {lightboxPost?.image_url && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-950/88 p-4 backdrop-blur-md" onMouseDown={event => event.target === event.currentTarget && setLightboxPost(null)}>
          <div className="relative flex h-full w-full max-w-[1120px] items-center justify-center">
            <img src={lightboxPost.image_url} alt={lightboxPost.title || postLabel(lightboxPost)} className="max-h-full max-w-full rounded-[20px] object-contain shadow-2xl" />
            <button type="button" onClick={() => setLightboxPost(null)} className="absolute right-2 top-2 flex h-11 w-11 items-center justify-center rounded-2xl border border-white/20 bg-slate-950/60 text-white backdrop-blur hover:bg-slate-950"><X className="h-5 w-5" /></button>
            <a href={lightboxPost.image_url} target="_blank" rel="noreferrer" className="absolute bottom-2 right-2 inline-flex h-10 items-center gap-2 rounded-2xl border border-white/20 bg-slate-950/60 px-4 text-xs font-semibold text-white backdrop-blur hover:bg-slate-950">打开原图 <ExternalLink className="h-3.5 w-3.5" /></a>
          </div>
        </div>
      )}
    </div>
  );
}
