'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, Copy, FilePenLine, ImageIcon, Loader2, RefreshCw, Search, SlidersHorizontal, X } from 'lucide-react';
import { toast } from '@/lib/toast';
import { hermesWorkflowApi, type HermesAccount, type HermesPost, type HermesRun, type HermesRunQuery } from '@/services/hermesWorkflowApi';
import HermesPostInspector, { type HermesInspectorTab } from './HermesPostInspector';
import { hermesDate } from './HermesFrame';
import s from './hermes.module.css';

const STATUS: Record<string, [string, string]> = {
  queued: ['排队中', 'amber'], running: ['生产中', 'blue'], generating: ['生产中', 'blue'],
  review_pending: ['待审核', 'amber'], approved: ['已通过', 'green'], changes_requested: ['待修改', 'red'],
  rejected: ['未通过', 'red'], partial_failed: ['部分失败', 'red'], failed: ['任务失败', 'red'],
  generation_failed: ['生成失败', 'red'], cancelled: ['已取消', 'gray'],
  publish_ready: ['已通过', 'green'], ready_to_publish: ['发布待接入', 'blue'], published: ['已发布', 'green'],
};
const SOURCE: Record<string, string> = { manual: '单篇创作', manual_batch: '批量创作', schedule: '定时任务', admin_manual: '管理员任务', regeneration: '不通过重生' };
export function historyMode(run: HermesRun) { return run.workflow_mode || (run.source === 'manual' ? 'single' : 'batch'); }
function runLink(id: number, mode: 'batch' | 'single', admin: boolean) { return `${admin ? '/admin/workflows' : mode === 'single' ? '/workflows/hermes/single' : '/workflows/hermes'}?run=${id}`; }
export function HermesStatusBadge({ status }: { status: string }) { const [label, tone] = STATUS[status] || [status, 'gray']; return <span className={s.badge} data-tone={tone}>{label}</span>; }

function PostCard({ post, onInspect, onReload, admin, mode }: { post: HermesPost; onInspect: (tab?: HermesInspectorTab) => void; onReload: () => Promise<void>; admin: boolean; mode: 'batch' | 'single' }) {
  const [busy, setBusy] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const failed = ['failed', 'generation_failed'].includes(post.status);
  const emptyTitle = failed ? '本篇生成失败' : post.status === 'cancelled' ? '本篇已取消' : '等待创作完成';
  const editable = ['review_pending', 'approved', 'rejected', 'publish_ready'].includes(post.status);
  const regenerated = post.source_detail?.latest_regeneration as { run_id?: number } | undefined;
  useEffect(() => setImageFailed(false), [post.image_url]);
  async function copy() {
    try { await navigator.clipboard.writeText(`${post.title || ''}\n\n${post.content || ''}`); toast.success('已复制标题、完整正文与话题'); }
    catch { toast.error('复制失败，请打开完整图文后手动复制'); }
  }
  async function approve() {
    setBusy(true);
    try { await (admin ? hermesWorkflowApi.adminReviewPost : hermesWorkflowApi.reviewPost)(post.id, 'approve', undefined, post.version); toast.success('已通过'); await onReload(); }
    catch (e) { toast.error(e instanceof Error ? e.message : '审核失败'); }
    finally { setBusy(false); }
  }
  const note = post.review_comment ? `${post.status === 'rejected' ? '不通过原因' : '修改说明'}：${post.review_comment}` : post.source_detail?.error ? String(post.source_detail.error) : post.publish_status === 'scheduled' ? `已排期 ${hermesDate(post.scheduled_publish_at)} · 尚未发布` : '';
  return <article className={s.card} data-post-id={post.id} aria-label={`第${post.slot}篇：${post.title || emptyTitle}`}>
    <button type="button" className={s.cardOpen} onClick={() => onInspect('post')} aria-label={`查看第${post.slot}篇完整图文`} />
    <div className={s.media}>
      {post.image_url && !imageFailed ? <img src={post.image_url} alt={post.title || '生成配图'} loading="lazy" onError={() => setImageFailed(true)} /> : <span className={s.mediaPlaceholder}>{['queued', 'generating'].includes(post.status) ? <Loader2 size={24} className="animate-spin" /> : <ImageIcon size={27} />}{imageFailed ? '图片暂时无法加载' : ['queued', 'generating'].includes(post.status) ? '正在创作' : '暂无配图'}</span>}
      <span className={s.mediaLabel}>{String(post.slot).padStart(2, '0')}</span><span className={s.mediaOpen}>查看完整图文 ↗</span>
    </div>
    <div className={s.cardBody}><div className={s.between}><span className={s.small}>{post.vehicle_model} · V{post.revision || 1}</span><HermesStatusBadge status={post.status} /></div>
      <h4 className={s.cardTitle}>{post.title || emptyTitle}</h4><div id={`post-copy-${post.id}`} className={s.excerpt}>{post.content || (failed ? '查看详情了解原因' : post.status === 'cancelled' ? '任务已取消' : '完成后自动显示')}</div>
      <div className={s.cardNote} data-error={failed || post.status === 'rejected'} title={note}>{regenerated?.run_id ? <a href={runLink(regenerated.run_id, mode, admin)}><RefreshCw size={11} />重生任务 #{regenerated.run_id} ↗</a> : note}</div>
      <div className={s.cardSources}><span>母文 #{String(post.source_detail?.mother_copy_id || '—')} · 母图 #{String(post.source_detail?.selected_prompt_id || '—')}</span><button className={s.textButton} onClick={() => onInspect('copy')}>对照</button>{post.content && <button className={s.textButton} onClick={copy} aria-label={`复制第${post.slot}篇完整文案`}><Copy size={12} />复制</button>}</div>
      <div className={s.cardFooter}>{editable ? <><button className={s.button} onClick={() => onInspect('edit')}><FilePenLine size={13} />编辑</button><div className={s.reviewActions}><button className={s.rejectButton} disabled={busy} onClick={() => onInspect('review')}>{post.status === 'rejected' ? '处理未通过' : '不通过'}</button>{['review_pending', 'rejected'].includes(post.status) && <button className={s.primary} disabled={busy} onClick={approve}>{busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}通过</button>}</div></> : <button className={s.button} onClick={() => onInspect('post')}>查看详情</button>}</div>
    </div>
  </article>;
}

export function HermesRunGroup({ run, admin = false, onRefresh, compact = false }: { run: HermesRun; admin?: boolean; onRefresh: () => void; compact?: boolean }) {
  const root = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  const [detail, setDetail] = useState<HermesRun | null>(null);
  const [error, setError] = useState('');
  const [collapsed, setCollapsed] = useState(false);
  const [selected, setSelected] = useState<{ post: HermesPost; tab: HermesInspectorTab } | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const load = useCallback(async () => {
    const id = ++seq.current;
    try { const res = await (admin ? hermesWorkflowApi.adminGetRun : hermesWorkflowApi.getRun)(run.id); if (seq.current === id) { setDetail(res.data); setError(''); } }
    catch (e) { if (seq.current === id) setError(e instanceof Error ? e.message : '加载失败'); }
  }, [run.id, admin]);
  useEffect(() => {
    const observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) { setVisible(true); observer.disconnect(); } }, { rootMargin: '300px' });
    if (root.current) observer.observe(root.current); return () => observer.disconnect();
  }, []);
  useEffect(() => { if (visible && !collapsed) void load(); return () => { seq.current += 1; }; }, [visible, collapsed, load, run.updated_at, run.status, run.generated_posts, run.approved_posts, run.rejected_posts]);
  const current = detail || run;
  const total = current.assigned_posts ?? current.total_posts;
  const generated = current.assigned_generated ?? current.generated_posts;
  const failed = current.assigned_failed ?? current.failed_posts ?? 0;
  const producing = ['queued', 'running'].includes(current.assigned_status || current.status);
  useEffect(() => {
    if (!visible || collapsed || !producing) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!document.hidden) await load();
      if (!stopped) timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 3000);
    return () => { stopped = true; clearTimeout(timer); };
  }, [visible, collapsed, producing, load]);
  const accounts = Array.from(new Set((detail?.posts || []).map(p => p.environment_id)));
  const reload = async () => { await load(); onRefresh(); };
  async function cancel() {
    if (!window.confirm('取消这个尚未执行的任务？不会删除历史记录。')) return;
    setBusy(true); try { await hermesWorkflowApi.cancelRun(run.id); await reload(); toast.success('已取消排队任务'); } catch (e) { toast.error(e instanceof Error ? e.message : '取消失败'); } finally { setBusy(false); }
  }
  return <section ref={root} id={`run-${run.id}`} className={s.task} data-compact={compact}>
    <header className={s.taskHead}><div className={s.taskHeadMain}><span className={s.taskNumber}>#{run.id}</span><div><h3>{run.name || run.parameters?.name || '图文创作任务'}</h3><div className={s.small}><span>{SOURCE[run.source] || run.source}</span><span>{hermesDate(run.created_at)}</span><span>{total} 篇 · {(run.accounts || []).length || accounts.length} 个账号</span></div></div></div>
      <div className={s.row}><HermesStatusBadge status={current.assigned_status || current.status} /><span className={s.small} aria-live="polite" title="已完成的帖子可先编辑、审核">已生成 {generated}/{total}{failed > 0 && <span className={s.danger}> · 失败 {failed}</span>}{producing && generated > 0 && <span> · 剩余 {Math.max(0, total - generated - failed)} 篇</span>}</span>
        {run.status === 'queued' && <button className={s.textButton} disabled={busy} onClick={cancel}>取消排队</button>}
        <button className={s.iconButton} onClick={() => setCollapsed(!collapsed)} aria-expanded={!collapsed} aria-label={collapsed ? '展开任务' : '收起任务'}><ChevronDown size={14} style={{ transform: collapsed ? 'rotate(-90deg)' : undefined }} /></button>
      </div>
    </header>
    {(compact || run.parameters?.selection_contract?.mode === 'typed') && <div className={s.runSelection}>{compact && current.error ? <span className={s.danger} title={current.error}>任务异常 · 点击卡片查看原因</span> : <><span>文案 · {run.parameters?.selection_contract?.copy_label || '自动选材'}</span><span>图片 · {run.parameters?.selection_contract?.image_label || '自动选材'}</span></>}</div>}
    {run.parameters?.regeneration && <a className={s.regenerationLink} href={runLink(run.parameters.regeneration.run_id, historyMode(run), admin)}>来自任务 #{run.parameters.regeneration.run_id} · 原稿 #{run.parameters.regeneration.post_id} ↗</a>}
    {!collapsed && <>
      {error && <div role="alert" className={`${s.notice} ${s.error}`}>{error}<button className={s.textButton} onClick={load}>重试加载</button></div>}
      {current.error && !compact && <div className={`${s.notice} ${s.error}`}>任务异常：{current.error}。成功内容仍可逐篇审核。</div>}
      {!detail && !error && <div className={s.empty}><Loader2 className="mx-auto mb-3 animate-spin" size={18} />正在读取此任务的图文记录…</div>}
      {accounts.map(id => { const posts = (detail?.posts || []).filter(p => p.environment_id === id); return <div key={id}><div className={s.accountHead}><span className={s.avatar}>{posts[0]?.account_name.slice(0, 1)}</span><strong>{posts[0]?.account_name}</strong>{posts.length > 1 && <span>{posts.length} 篇</span>}</div><div className={s.grid} data-single={posts.length === 1}>{posts.map(post => <PostCard key={post.id} post={post} admin={admin} mode={historyMode(run)} onInspect={tab => setSelected({ post, tab: tab || 'post' })} onReload={reload} />)}</div></div>; })}
    </>}
    {selected && <HermesPostInspector key={selected.post.id} post={selected.post} initialTab={selected.tab} runError={current.error} admin={admin} onClose={() => setSelected(null)} onSaved={reload} />}
  </section>;
}

export default function HermesCreationHistory({ admin = false, refreshKey = 0, accounts = [], mode }: { admin?: boolean; refreshKey?: number; accounts?: HermesAccount[]; mode?: 'batch' | 'single' }) {
  const [runs, setRuns] = useState<HermesRun[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState<HermesRunQuery>({ page: 1, limit: 8 });
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  const [moreFilters, setMoreFilters] = useState(false);
  const [focusedRun, setFocusedRun] = useState<HermesRun | null>(null);
  const [otherRun, setOtherRun] = useState<HermesRun | null>(null);
  const historyTitle = mode === 'batch' ? '批量创作记录' : mode === 'single' ? '单篇创作记录' : '全部创作记录';
  const firstLoad = useRef(true);
  const refresh = useCallback(() => setTick(v => v + 1), []);
  useEffect(() => { const timer = window.setTimeout(() => setQuery(q => ({ ...q, search: keyword || undefined, page: 1 })), 350); return () => clearTimeout(timer); }, [keyword]);
  useEffect(() => {
    let active = true;
    if (firstLoad.current) setLoading(true);
    (admin ? hermesWorkflowApi.adminListRuns : hermesWorkflowApi.listRuns)({ ...query, workflow_mode: mode }).then(res => {
      if (active) { setRuns(res.data.items || []); setTotal(res.data.total || 0); setError(''); }
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : '历史记录加载失败'); }).finally(() => { if (active) { setLoading(false); firstLoad.current = false; } });
    return () => { active = false; };
  }, [admin, query, refreshKey, tick, mode]);
  const hasActiveRuns = runs.some(run => ['queued', 'running'].includes(run.assigned_status || run.status));
  useEffect(() => { const timer = window.setInterval(() => { if (!document.hidden) refresh(); }, hasActiveRuns ? 3000 : 15000); return () => clearInterval(timer); }, [refresh, hasActiveRuns]);
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get('run'));
    let active = true;
    if (id > 0) (admin ? hermesWorkflowApi.adminGetRun : hermesWorkflowApi.getRun)(id).then(res => { if (!active) return; if (mode && historyMode(res.data) !== mode) { setOtherRun(res.data); return; } setFocusedRun(res.data); setTimeout(() => document.getElementById(`run-${id}`)?.scrollIntoView({ block: 'start' }), 100); }).catch(e => { if (active) setError(e instanceof Error ? e.message : '任务不存在'); });
    return () => { active = false; };
  }, [admin, mode]);
  function filter(values: Partial<HermesRunQuery>) { setLoading(true); setRuns([]); setFocusedRun(null); setOtherRun(null); firstLoad.current = true; setQuery(q => ({ ...q, ...values, page: 1 })); }
  function page(delta: number) { setLoading(true); setRuns([]); setFocusedRun(null); firstLoad.current = true; setQuery(q => ({ ...q, page: (q.page || 1) + delta })); document.getElementById('history')?.scrollIntoView(); }
  const pages = Math.max(1, Math.ceil(total / 8));
  const extraFilterCount = [query.source, query.date_from || query.date_to].filter(Boolean).length;
  const filtered = !!(keyword || query.status || query.source || query.environment_id || query.date_from || query.date_to);
  return <section id="history" className={s.history} aria-label={historyTitle} aria-busy={loading}>
    <div className={s.toolbar}><div className={s.row}><h2>{historyTitle}</h2><span className={s.historyCount}>{total}</span></div><button className={s.iconButton} onClick={refresh} aria-label="刷新创作记录" title="刷新创作记录"><RefreshCw size={15} /></button></div>
    <div className={s.filters}><div className={s.searchField}><Search size={15} /><input aria-label="搜索任务、账号、车型或标题" placeholder="搜索任务、账号、车型或标题" value={keyword} onChange={e => setKeyword(e.target.value)} />{keyword && <button aria-label="清除搜索" onClick={() => setKeyword('')}><X size={13} /></button>}</div>
      <select className={s.input} aria-label="审核状态筛选" value={query.status || ''} onChange={e => filter({ status: e.target.value || undefined })}>{[['', '全部状态'], ['running', '含排队 / 生产中'], ['review_pending', '含待审核'], ['approved', '含已通过'], ['changes_requested', '含未通过'], ['failed', '含失败帖子'], ['cancelled', '已取消']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      {accounts.length > 1 && <select className={s.input} aria-label="账号筛选" value={query.environment_id || ''} onChange={e => filter({ environment_id: Number(e.target.value) || undefined })}><option value="">全部账号</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select>}
      <button className={s.button} aria-expanded={moreFilters} onClick={() => setMoreFilters(v => !v)}><SlidersHorizontal size={14} />筛选{extraFilterCount > 0 && <span className={s.filterCount}>{extraFilterCount}</span>}</button>
      {filtered && <button className={s.textButton} onClick={() => { setKeyword(''); filter({ status: undefined, source: undefined, environment_id: undefined, date_from: undefined, date_to: undefined, search: undefined }); }}>清除筛选</button>}
    </div>
    {moreFilters && <div className={s.extraFilters}><select className={s.input} aria-label="任务来源筛选" value={query.source || ''} onChange={e => filter({ source: e.target.value || undefined })}><option value="">全部任务来源</option>{Object.entries(SOURCE).filter(([v]) => !mode || v === 'regeneration' || (mode === 'single' ? v === 'manual' : v !== 'manual')).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      <details className={`${s.dropdown} ${s.dateFilter}`}><summary className={s.button}><CalendarDays size={14} />{query.date_from || query.date_to ? '已筛选日期' : '日期范围'}<ChevronDown size={12} /></summary><div className={s.menu}><label className={s.label}>开始日期<input className={s.input} type="date" aria-label="开始日期" value={query.date_from || ''} max={query.date_to} onChange={e => filter({ date_from: e.target.value || undefined })} /></label><label className={s.label}>结束日期<input className={s.input} type="date" aria-label="结束日期" value={query.date_to || ''} min={query.date_from} onChange={e => filter({ date_to: e.target.value || undefined })} /></label><button className={s.textButton} onClick={() => filter({ date_from: undefined, date_to: undefined })}>清除日期筛选</button></div></details>
    </div>}
    {error && <div className={`${s.notice} ${s.error}`} role="alert">{error}。已有内容保留，可点击刷新重试。</div>}
    {loading && <div className={s.empty}><Loader2 size={18} className="mx-auto mb-2 animate-spin" />加载创作记录</div>}
    {otherRun && <div className={s.notice}>任务 #{otherRun.id} 属于{historyMode(otherRun) === 'single' ? '单篇' : '批量'}创作。<a className={s.textButton} href={runLink(otherRun.id, historyMode(otherRun), admin)}>前往查看 ↗</a></div>}
    <div className={s.historyList} data-mode={mode}>
      {focusedRun && !runs.some(r => r.id === focusedRun.id) && <HermesRunGroup run={focusedRun} admin={admin} compact={mode === 'single'} onRefresh={refresh} />}
      {runs.map(run => <HermesRunGroup key={run.id} run={run} admin={admin} compact={mode === 'single'} onRefresh={refresh} />)}
    </div>
    {!loading && !runs.length && !error && !focusedRun && <div className={s.empty}>{filtered ? '没有匹配的记录' : `暂无${mode === 'single' ? '单篇' : mode === 'batch' ? '批量' : ''}创作记录`}</div>}
    {total > 8 && <nav className={s.pager} aria-label="历史任务分页"><button className={s.button} disabled={query.page === 1} onClick={() => page(-1)}><ChevronLeft size={14} />上一页</button><span>{query.page} / {pages}</span><button className={s.button} disabled={(query.page || 1) >= pages} onClick={() => page(1)}>下一页<ChevronRight size={14} /></button></nav>}
  </section>;
}
