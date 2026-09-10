'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { CalendarClock, Check, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { toast } from '@/lib/toast';
import { hermesWorkflowApi, type HermesAccount, type HermesPost, type HermesPublishQuery } from '@/services/hermesWorkflowApi';
import HermesPostInspector from './HermesPostInspector';
import { hermesDate } from './HermesFrame';
import s from './hermes.module.css';

function nextHour() { const now = new Date(Date.now() + 3600000); const bj = new Date(now.getTime() + 8 * 3600000); return `${bj.toISOString().slice(0, 13)}:00`; }

export default function HermesPublishPlanner({ admin = false }: { admin?: boolean }) {
  const [posts, setPosts] = useState<HermesPost[]>([]);
  const [accounts, setAccounts] = useState<HermesAccount[]>([]);
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
  const requestSeq = useRef(0);
  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      const [b, r] = await Promise.all([admin ? hermesWorkflowApi.adminBootstrap() : hermesWorkflowApi.bootstrap(), admin ? hermesWorkflowApi.adminPublishCandidates(query) : hermesWorkflowApi.listPublishCandidates(query)]);
      if (seq !== requestSeq.current) return;
      setAccounts(b.data.accounts); setPosts(r.data.items); setTotal(r.data.total); setError('');
      setTargets(old => Object.fromEntries(r.data.items.map(p => [p.id, old[p.id] || p.publish_target_environment_id || p.environment_id])));
      setTimes(old => Object.fromEntries(r.data.items.map(p => [p.id, old[p.id] || p.scheduled_publish_at?.slice(0, 16) || ''])));
      setSelected(old => old.filter(id => r.data.items.some(p => p.id === id)));
    } catch (e) { if (seq === requestSeq.current) setError(e instanceof Error ? e.message : '加载发布内容失败'); }
    finally { if (seq === requestSeq.current) setLoading(false); }
  }, [admin, query]);
  useEffect(() => { setLoading(true); setPosts([]); setSelected([]); setTargets({}); setTimes({}); void load(); return () => { requestSeq.current += 1; }; }, [load]);
  useEffect(() => { const timer = window.setTimeout(() => setQuery(q => ({ ...q, search: search.trim() || undefined, page: 1 })), 350); return () => clearTimeout(timer); }, [search]);
  const visible = posts;
  const pages = Math.max(1, Math.ceil(total / 40));
  const selectedPosts = posts.filter(p => selected.includes(p.id));
  const inspectPost = posts.find(p => p.id === inspecting);
  function toggle(id: number) { setSelected(old => old.includes(id) ? old.filter(v => v !== id) : old.length < 40 ? [...old, id] : (toast.error('一次最多排期40篇'), old)); }
  function distribute() {
    if (!start || !selectedPosts.length) return;
    const seen: Record<number, number> = {};
    const next = { ...times };
    selectedPosts.forEach(p => { const target = targets[p.id] || p.environment_id; const offset = seen[target] || 0; seen[target] = offset + 1; next[p.id] = new Date(new Date(`${start}+08:00`).getTime() + offset * gap * 60000 + 8 * 3600000).toISOString().slice(0, 16); });
    setTimes(next); toast.success('已填入预览时间，仅本页有效，尚未保存');
  }
  function save() {
    toast.info('发布计划功能开发中，敬请期待。当前设置暂未保存，也不会执行发布。');
  }
  return <>
    <div className={s.toolbar}><div className={s.row}><h2>{admin ? '全账户已审核内容' : '已审核内容'}</h2><span className={s.small}>共 {total} 篇 · 本页 {posts.length} 篇</span></div><button className={s.button} onClick={load}><RefreshCw size={14} />刷新</button></div>
    <div className={s.notice}><CalendarClock size={17} style={{ flexShrink: 0, marginTop: 2 }} /><span>发布计划功能开发中。可预览账号与时间设置，<strong>暂不保存，也不会自动发布</strong>。所有时间均为北京时间。</span></div>
    <div className={s.filters}><input className={s.input} maxLength={100} placeholder="搜索标题、账号或车型" aria-label="搜索待发布内容" value={search} onChange={e => setSearch(e.target.value)} /><select className={s.input} aria-label="待发布账号" value={query.environment_id || ''} onChange={e => setQuery(q => ({ ...q, environment_id: Number(e.target.value) || undefined, page: 1 }))}><option value="">全部账号</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select><select className={s.input} aria-label="排期状态" value={query.planned === undefined ? '' : query.planned ? 'planned' : 'unplanned'} onChange={e => setQuery(q => ({ ...q, planned: e.target.value ? e.target.value === 'planned' : undefined, page: 1 }))}><option value="">全部排期状态</option><option value="unplanned">尚未排期</option><option value="planned">已有排期</option></select><button className={s.button} onClick={() => setSelected(visible.slice(0, 40).map(p => p.id))}>选择本页（最多40篇）</button>{selected.length > 0 && <button className={s.textButton} onClick={() => setSelected([])}>清空选择</button>}</div>
    {error && <div role="alert" className={`${s.notice} ${s.error}`}>{error}</div>}
    <div className={s.publishLayout}><section>
      {loading && <div className={s.empty}>读取审核通过内容…</div>}
      {!loading && !visible.length && !error && <div className={s.empty}>没有符合条件的已通过内容。请先完成图文审核。</div>}
      {visible.map(p => <article className={s.publishRow} key={p.id} style={selected.includes(p.id) ? { borderColor: '#82a1cf', background: '#fafcff' } : undefined}>
        <button onClick={() => setInspecting(p.id)} aria-label={`查看${p.title}`}><img src={p.image_url || ''} alt={p.title || '待发布配图'} loading="lazy" /></button><div style={{ minWidth: 0 }}><div className={s.between}><label className={s.row}><input type="checkbox" checked={selected.includes(p.id)} onChange={() => toggle(p.id)} style={{ accentColor: '#46679f' }} /><span className={s.small}>{p.account_name} · {p.vehicle_model} · V{p.revision || 1}</span></label><span className={s.badge} data-tone={p.publish_status === 'scheduled' ? 'blue' : 'green'}>{p.publish_status === 'scheduled' ? '已排期 · 未发布' : '已通过'}</span></div><button className={s.cardTitle} style={{ textAlign: 'left' }} onClick={() => setInspecting(p.id)}>{p.title}</button><p className={s.excerpt} style={{ maxHeight: 46 }}>{p.content}</p>
        {p.scheduled_publish_at && <p className={s.small} style={{ marginTop: 8 }}>当前计划：{hermesDate(p.scheduled_publish_at)}</p>}
        {selected.includes(p.id) && <div className={s.advanced} style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))' }}><label className={s.label}>发布账号<select className={s.input} value={targets[p.id] || p.environment_id} onChange={e => setTargets(old => ({ ...old, [p.id]: Number(e.target.value) }))}>{accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label><label className={s.label}>发布时间 · 北京时间<input className={s.input} type="datetime-local" value={times[p.id] || ''} onChange={e => setTimes(old => ({ ...old, [p.id]: e.target.value }))} /></label></div>}</div>
      </article>)}
      {total > 40 && <nav className={s.pager} aria-label="待发布内容分页"><button className={s.button} disabled={loading || query.page === 1} onClick={() => setQuery(q => ({ ...q, page: (q.page || 1) - 1 }))}><ChevronLeft size={14} />上一页</button><span>{query.page} / {pages}</span><button className={s.button} disabled={loading || (query.page || 1) >= pages} onClick={() => setQuery(q => ({ ...q, page: (q.page || 1) + 1 }))}>下一页<ChevronRight size={14} /></button></nav>}
    </section><aside className={s.sticky}><div className={s.paper}><h3>本次安排 <span className={s.small}>{selected.length} / 40 篇</span></h3><p className={s.muted}>同一账号按间隔顺延，不同账号可以同时开始。填入时间后可逐篇调整。</p><label className={s.label} style={{ marginTop: 18 }}>起始时间 · 北京时间<input className={s.input} type="datetime-local" value={start} onChange={e => setStart(e.target.value)} /></label><label className={s.label} style={{ marginTop: 12 }}>每个账号的发帖间隔<select className={s.input} value={gap} onChange={e => setGap(Number(e.target.value))}>{[30, 60, 120, 180, 240].map(n => <option key={n} value={n}>{n} 分钟</option>)}</select></label><button className={s.button} style={{ marginTop: 15, width: '100%' }} onClick={distribute} disabled={!selected.length}>按账号填入时间</button><button className={s.primary} style={{ marginTop: 10, width: '100%' }} onClick={save}><Check size={14} />保存发布计划</button><p className={s.small} style={{ marginTop: 14 }}>当前设置仅用于本页预览，不会创建发布计划。</p></div></aside></div>
    {inspectPost && <HermesPostInspector key={`${inspectPost.id}-${inspectPost.version}`} post={inspectPost} admin={admin} onClose={() => setInspecting(null)} onSaved={load} />}
  </>;
}
