'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { CalendarClock, Check, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { toast } from '@/lib/toast';
import { hermesWorkflowApi, type HermesAccount, type HermesPost, type HermesPublishQuery, type HermesPublishJob } from '@/services/hermesWorkflowApi';
import HermesPostInspector from './HermesPostInspector';
import HermesUploadComposer from './HermesUploadComposer';
import { hermesDate } from './HermesFrame';
import s from './hermes.module.css';

function nextHour() { const now = new Date(Date.now() + 3600000); const bj = new Date(now.getTime() + 8 * 3600000); return `${bj.toISOString().slice(0, 13)}:00`; }
const publishLabels: Record<string, string> = { scheduled: '已排期', waiting_device: '等待设备', preparing: '准备配图', submitting: '下发中', queued: '手机排队中', running: '手机执行中', stalled: '等待恢复', cancel_requested: '取消请求中', cancelled: '已取消', submitted: '云手机发布成功', unknown: '结果未知 · 需核查', failed: '发布失败' };
const editable = new Set(['not_requested', 'not_ready', 'scheduled', 'waiting_device', 'cancelled', 'failed']);
const ready = (post: HermesPost) => ['approved', 'publish_ready'].includes(post.status);

export default function HermesPublishPlanner({ admin = false }: { admin?: boolean }) {
  const [posts, setPosts] = useState<HermesPost[]>([]);
  const [accounts, setAccounts] = useState<HermesAccount[]>([]);
  const [maxImages, setMaxImages] = useState(5);
  const [selected, setSelected] = useState<number[]>([]);
  const [targets, setTargets] = useState<Record<number, number>>({});
  const [times, setTimes] = useState<Record<number, string>>({});
  const [start, setStart] = useState(nextHour);
  const [gap, setGap] = useState(120);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState<HermesPublishQuery>({ page: 1, limit: 40 });
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [inspecting, setInspecting] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadedPost, setUploadedPost] = useState<HermesPost | null>(null);
  const [saving, setSaving] = useState(false);
  const saveLock = useRef(false);
  const [jobs, setJobs] = useState<HermesPublishJob[]>([]);
  const [jobsPage, setJobsPage] = useState(1);
  const [jobsTotal, setJobsTotal] = useState(0);
  const [jobsError, setJobsError] = useState('');
  const [dispatchEnabled, setDispatchEnabled] = useState(false);
  const [cancelling, setCancelling] = useState<number | null>(null);
  const jobSeq = useRef(0);
  const loadJobs = useCallback(async () => {
    const seq = ++jobSeq.current;
    try {
      const r = await (admin ? hermesWorkflowApi.adminPublishJobs(jobsPage) : hermesWorkflowApi.listPublishJobs(jobsPage));
      if (seq !== jobSeq.current) return;
      setJobs(r.data.items); setJobsTotal(r.data.total); setDispatchEnabled(r.data.dispatch_enabled); setJobsError('');
    } catch (e) { if (seq === jobSeq.current) setJobsError(e instanceof Error ? e.message : '读取发布记录失败'); }
  }, [admin, jobsPage]);
  useEffect(() => {
    void loadJobs();
    const timer = window.setInterval(() => { if (!document.hidden) void loadJobs(); }, 5000);
    return () => { window.clearInterval(timer); jobSeq.current += 1; };
  }, [loadJobs]);
  const requestSeq = useRef(0);
  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      const [b, r] = await Promise.all([admin ? hermesWorkflowApi.adminBootstrap() : hermesWorkflowApi.bootstrap(), admin ? hermesWorkflowApi.adminPublishCandidates(query) : hermesWorkflowApi.listPublishCandidates(query)]);
      if (seq !== requestSeq.current) return;
      setAccounts(b.data.accounts); setPosts(r.data.items); setTotal(r.data.total); setError('');
      setMaxImages(b.data.limits?.max_publish_images || 5);
      setTargets(Object.fromEntries(r.data.items.map(p => [p.id, p.environment_id])));
      setTimes(old => Object.fromEntries(r.data.items.map(p => [p.id, old[p.id] || p.scheduled_publish_at?.slice(0, 16) || ''])));
      setSelected(old => old.filter(id => r.data.items.some(p => p.id === id)));
    } catch (e) { if (seq === requestSeq.current) setError(e instanceof Error ? e.message : '加载发布内容失败'); }
    finally { if (seq === requestSeq.current) setLoading(false); }
  }, [admin, query]);
  useEffect(() => { setLoading(true); setPosts([]); setSelected([]); setTargets({}); setTimes({}); void load(); return () => { requestSeq.current += 1; }; }, [load]);
  useEffect(() => { const timer = window.setTimeout(() => setQuery(q => ({ ...q, search: search.trim() || undefined, page: 1 })), 350); return () => clearTimeout(timer); }, [search]);
  const visible = posts;
  const pages = Math.max(1, Math.ceil(total / 40));
  function currentStatus(post: HermesPost) { return jobs.find(job => job.post_id === post.id)?.status || post.publish_status; }
  const selectedPosts = posts.filter(p => selected.includes(p.id) && ready(p) && editable.has(currentStatus(p)));
  useEffect(() => {
    setSelected(old => old.filter(id => posts.some(post => post.id === id && ready(post) && editable.has(jobs.find(job => job.post_id === id)?.status || post.publish_status))));
  }, [posts, jobs]);
  const inspectPost = posts.find(p => p.id === inspecting);
  function toggle(id: number) { setSelected(old => old.includes(id) ? old.filter(v => v !== id) : old.length < 40 ? [...old, id] : (toast.error('一次最多排期40篇'), old)); }
  function distribute() {
    if (!start || !selectedPosts.length) return;
    const seen: Record<number, number> = {};
    const next = { ...times };
    selectedPosts.forEach(p => { const target = targets[p.id] || p.environment_id; const offset = seen[target] || 0; seen[target] = offset + 1; next[p.id] = new Date(new Date(`${start}+08:00`).getTime() + offset * gap * 60000 + 8 * 3600000).toISOString().slice(0, 16); });
    setTimes(next); toast.success('已填入预览时间，仅本页有效，尚未保存');
  }
  async function save() {
    if (saveLock.current) return;
    if (!selectedPosts.length) { toast.error('请先选择需要排期的内容'); return; }
    if (selectedPosts.some(p => !times[p.id] || !p.version)) { toast.error('请填写每篇发布时间，并确认审核版本已加载'); return; }
    if (!window.confirm(`保存 ${selectedPosts.length} 篇发布排期？后台开启后会按时在对应账号真实发布。`)) return;
    saveLock.current = true; setSaving(true);
    try {
      const items = selectedPosts.map(p => ({ post_id: p.id, environment_id: targets[p.id] || p.environment_id, scheduled_at: `${times[p.id]}+08:00`, expected_version: p.version }));
      await (admin ? hermesWorkflowApi.adminSavePublishPlan(items) : hermesWorkflowApi.savePublishPlan(items));
      toast.success('发布排期已保存'); setSelected([]); setTimes({}); setTargets({});
      await Promise.all([load(), loadJobs()]);
    } catch (e) { toast.error(e instanceof Error ? e.message : '保存结果未确认，请刷新发布记录核查，不要反复提交'); }
    finally { saveLock.current = false; setSaving(false); }
  }
  async function cancel(job: HermesPublishJob) {
    if (cancelling !== null || !window.confirm('取消这条发布任务？若手机已经提交，取消不能撤回帖子。')) return;
    setCancelling(job.id);
    try {
      await (admin ? hermesWorkflowApi.adminCancelPublishJob(job.id) : hermesWorkflowApi.cancelPublishJob(job.id));
      toast.success('取消请求已保存'); await Promise.all([loadJobs(), load()]);
    } catch (e) { toast.error(e instanceof Error ? e.message : '取消结果未确认，请刷新核查'); }
    finally { setCancelling(null); }
  }
  return <>
    <div className={s.toolbar}><div className={s.row}><h2>{admin ? '全账户发布内容' : '发布内容'}</h2><span className={s.small}>AI生成 / 自主上传 · 共 {total} 篇</span></div><div className={s.row}><button className={s.primary} disabled={loading} onClick={() => setUploading(true)}>上传图文</button><button className={s.button} onClick={load}><RefreshCw size={14} />刷新</button></div></div>
    <div className={s.notice}><CalendarClock size={17} style={{ flexShrink: 0, marginTop: 2 }} /><span>{dispatchEnabled ? '云手机发布已开启，到点后由后台执行。' : '云手机实际发布暂未开启，排期可保存，但不会下发手机。'}所有时间均为北京时间；已提交不等于帖子公开可见。</span></div>
    <div className={s.filters}><input disabled={saving} className={s.input} maxLength={100} placeholder="搜索标题、账号或车型" aria-label="搜索待发布内容" value={search} onChange={e => setSearch(e.target.value)} /><select disabled={saving} className={s.input} aria-label="待发布账号" value={query.environment_id || ''} onChange={e => setQuery(q => ({ ...q, environment_id: Number(e.target.value) || undefined, page: 1 }))}><option value="">全部账号</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select><select disabled={saving} className={s.input} aria-label="排期状态" value={query.planned === undefined ? '' : query.planned ? 'planned' : 'unplanned'} onChange={e => setQuery(q => ({ ...q, planned: e.target.value ? e.target.value === 'planned' : undefined, page: 1 }))}><option value="">全部排期状态</option><option value="unplanned">尚未排期</option><option value="planned">已有排期</option></select><button disabled={saving} className={s.button} onClick={() => setSelected(visible.filter(p => ready(p) && editable.has(currentStatus(p))).slice(0, 40).map(p => p.id))}>选择本页（最多40篇）</button>{selected.length > 0 && <button disabled={saving} className={s.textButton} onClick={() => setSelected([])}>清空选择</button>}</div>
    {error && <div role="alert" className={`${s.notice} ${s.error}`}>{error}</div>}
    <div className={s.publishLayout}><section>
      {loading && <div className={s.empty}>读取审核通过内容…</div>}
      {!loading && !visible.length && !error && <div className={s.empty}>暂无发布内容。可上传自己的图文，或先完成AI图文审核。</div>}
      {visible.map(p => <article className={s.publishRow} key={p.id} style={selected.includes(p.id) ? { borderColor: '#82a1cf', background: '#fafcff' } : undefined}>
        <button onClick={() => setInspecting(p.id)} aria-label={`查看${p.title}`}><img src={p.image_url || ''} alt={p.title || '待发布配图'} loading="lazy" /></button><div style={{ minWidth: 0 }}><div className={s.between}><label className={s.row}><input type="checkbox" disabled={saving || !ready(p) || !editable.has(currentStatus(p))} checked={selected.includes(p.id)} onChange={() => toggle(p.id)} style={{ accentColor: '#46679f' }} /><span className={s.small}>{p.account_name} · {p.source_kind === 'user_upload' ? `自主上传 · ${p.image_urls?.length || 1}张图片` : p.vehicle_model} · V{p.revision || 1}</span></label><span className={s.badge} data-tone={ready(p) ? 'green' : 'amber'}>{!ready(p) ? p.status === 'rejected' ? '待修改' : '待确认图文' : publishLabels[currentStatus(p)] || '已通过'}</span></div><button className={s.cardTitle} style={{ textAlign: 'left' }} onClick={() => setInspecting(p.id)}>{p.title}</button><p className={s.excerpt} style={{ maxHeight: 46 }}>{p.content}</p>
        {!ready(p) && <button className={s.button} onClick={() => setInspecting(p.id)}>查看并确认图文</button>}
        {p.scheduled_publish_at && <p className={s.small} style={{ marginTop: 8 }}>当前计划：{hermesDate(p.scheduled_publish_at)}</p>}
        {selected.includes(p.id) && <div className={s.advanced} style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))' }}><label className={s.label}>发布账号 · 与审核一致<input className={s.input} readOnly value={accounts.find(a => a.id === p.environment_id)?.name || p.account_name} /></label><label className={s.label}>发布时间 · 北京时间<input disabled={saving} className={s.input} type="datetime-local" value={times[p.id] || ''} onChange={e => setTimes(old => ({ ...old, [p.id]: e.target.value }))} /></label></div>}</div>
      </article>)}
      {total > 40 && <nav className={s.pager} aria-label="待发布内容分页"><button className={s.button} disabled={loading || query.page === 1} onClick={() => setQuery(q => ({ ...q, page: (q.page || 1) - 1 }))}><ChevronLeft size={14} />上一页</button><span>{query.page} / {pages}</span><button className={s.button} disabled={loading || (query.page || 1) >= pages} onClick={() => setQuery(q => ({ ...q, page: (q.page || 1) + 1 }))}>下一页<ChevronRight size={14} /></button></nav>}
    </section><aside className={s.sticky}><div className={s.paper}><h3>本次安排 <span className={s.small}>{selected.length} / 40 篇</span></h3><p className={s.muted}>同一账号按间隔顺延；同一手机串行执行，空闲的不同手机可并发。</p><label className={s.label} style={{ marginTop: 18 }}>起始时间 · 北京时间<input className={s.input} type="datetime-local" value={start} onChange={e => setStart(e.target.value)} /></label><label className={s.label} style={{ marginTop: 12 }}>每个账号的发帖间隔<select className={s.input} value={gap} onChange={e => setGap(Number(e.target.value))}>{[30, 60, 120, 180, 240].map(n => <option key={n} value={n}>{n} 分钟</option>)}</select></label><button className={s.button} style={{ marginTop: 15, width: '100%' }} onClick={distribute} disabled={!selected.length || saving}>按账号填入时间</button><button className={s.primary} disabled={saving} style={{ marginTop: 10, width: '100%' }} onClick={save}><Check size={14} />{saving ? '正在保存…' : '保存发布计划'}</button><p className={s.small} style={{ marginTop: 14 }}>保存后可离开页面；内容修改会取消未执行排期，提交后不可直接重发。</p></div></aside></div>
    <section className={s.paper} style={{ marginTop: 20 }} aria-label="发布记录">
      <div className={s.between}><h3>发布记录 <span className={s.small}>{jobsTotal} 条</span></h3><button className={s.button} onClick={loadJobs}>刷新发布记录</button></div>
      {jobsError && <p role="alert" className={s.error}>{jobsError}，保留上次有效记录。</p>}
      {!jobs.length && !jobsError && <p className={s.muted}>暂无发布记录，保存排期后会显示在这里。</p>}
      {jobs.map(job => <article key={job.id} style={{ padding: '16px 0', borderBottom: '1px solid hsl(var(--border))' }}>
        <div className={s.between}><strong>{job.title || `内容 #${job.post_id}`}</strong><span className={s.badge}>{publishLabels[job.status] || job.status}</span></div>
        <p className={s.small}>{accounts.find(a => a.id === job.environment_id)?.name || '审核目标账号'} · V{job.revision} · {hermesDate(job.scheduled_at)}</p>
        {job.message && <p className={s.muted}>{job.message}</p>}
        <details><summary className={s.small}>状态记录{job.remote_job_id ? ` · 手机任务 ${job.remote_job_id}` : ''}</summary>{job.events.map((event, index) => <p className={s.small} key={index}>{hermesDate(event.at)} · {publishLabels[event.status] || event.status}{event.code ? ` · ${event.code}` : ''}</p>)}</details>
        {job.can_cancel && <button className={s.textButton} disabled={cancelling !== null} onClick={() => cancel(job)}>{cancelling === job.id ? '处理中…' : '取消发布'}</button>}
      </article>)}
      {jobsTotal > 40 && <nav className={s.pager} aria-label="发布记录分页"><button className={s.button} disabled={jobsPage === 1} onClick={() => setJobsPage(p => p - 1)}>上一页</button><span>{jobsPage} / {Math.ceil(jobsTotal / 40)}</span><button className={s.button} disabled={jobsPage >= Math.ceil(jobsTotal / 40)} onClick={() => setJobsPage(p => p + 1)}>下一页</button></nav>}
    </section>
    {inspectPost && <HermesPostInspector key={`${inspectPost.id}-${inspectPost.version}`} post={inspectPost} admin={admin} onClose={() => setInspecting(null)} onSaved={load} />}
    {uploading && <HermesUploadComposer accounts={accounts} maxImages={maxImages} onClose={() => setUploading(false)} onSaved={async post => { setUploading(false); setUploadedPost(post); await load(); }} />}
    {uploadedPost && <HermesPostInspector key={`upload-${uploadedPost.id}-${uploadedPost.version}`} post={uploadedPost} admin={admin} onClose={() => setUploadedPost(null)} onSaved={load} />}
  </>;
}
