'use client';
import { useCallback, useEffect, useState } from 'react';
import { Activity, CalendarClock, FileCheck2, Loader2, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { hermesWorkflowApi } from '@/services/hermesWorkflowApi';
import HermesCreationHistory from '@/components/workflow/HermesCreationHistory';
import HermesPublishPlanner from '@/components/workflow/HermesPublishPlanner';
import HermesPolicyViewer from '@/components/workflow/HermesPolicyViewer';
import { hermesDate } from '@/components/workflow/HermesFrame';
import s from '@/components/workflow/hermes.module.css';

type Bootstrap = Awaited<ReturnType<typeof hermesWorkflowApi.adminBootstrap>>['data'];
type AccountDraft = { environment_id: number; vehicle_model: string; case_id?: string | null };
export default function Page() {
  const [tab, setTab] = useState('content');
  const [data, setData] = useState<Bootstrap | null>(null);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState<AccountDraft[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [time, setTime] = useState('09:00');
  const [instruction, setInstruction] = useState('');
  const [saving, setSaving] = useState(false);
  const [policyOpen, setPolicyOpen] = useState(false);
  const load = useCallback(async (initial = false) => {
    try { const r = await hermesWorkflowApi.adminBootstrap(); setData(r.data); setError(''); if (initial) { setDraft(r.data.schedule.accounts); setEnabled(r.data.schedule.enabled); setTime(r.data.schedule.run_time); setInstruction(r.data.schedule.instruction || ''); } }
    catch (e) { setError(e instanceof Error ? e.message : '管理数据加载失败'); }
  }, []);
  useEffect(() => { void load(true); const timer = setInterval(() => { if (!document.hidden) void load(); }, 20000); return () => clearInterval(timer); }, [load]);
  async function save() {
    if (enabled && draft.length !== 8) return toast.error('开启正式定时任务需要8个账号，每个账号5篇');
    if (draft.some(a => !a.environment_id || !a.vehicle_model)) return toast.error('请补齐账号与车型，或删除空行');
    if (enabled && !window.confirm(`确认开启每天 ${time}（北京时间）的8账号×5篇生产？此操作会启动定时生成，但不会自动发布。`)) return;
    setSaving(true);
    try { await hermesWorkflowApi.updateSchedule({ enabled, run_time: time, posts_per_account: 5, accounts: draft, instruction }); await load(true); toast.success('定时配置已保存'); }
    catch (e) { toast.error(e instanceof Error ? e.message : '保存失败'); }
    finally { setSaving(false); }
  }
  const accounts = data?.accounts || [];
  const models = [...new Set([...(data?.policies || []).map(p => p.vehicle_model), ...draft.map(a => a.vehicle_model)])].filter(Boolean);
  return <div className={s.shell}><main className={s.scroll}><div className={s.container}>
    <header className={s.header}><div className={s.heading}><h1>内容运营管理</h1><span className={s.badge} data-tone={data?.schedule.enabled ? 'green' : 'gray'}>{data?.schedule.enabled ? '定时生产已开启' : '定时生产未开启'}</span></div><button className={s.button} onClick={() => load()}><RefreshCw size={14} />刷新状态</button></header>
    <div className={s.toolbar}><div className={s.nav} role="tablist" aria-label="运营管理模块">{[['content', '全账户内容'], ['publish', '发布排期'], ['schedule', '定时生产'], ['health', '运行状态']].map(([v, l]) => <button className={s.tab} role="tab" aria-selected={tab === v} key={v} onClick={() => setTab(v)}>{l}</button>)}</div><button className={s.textButton} onClick={() => setPolicyOpen(true)}>查看全部最新政策 ↗</button></div>
    {error && <div role="alert" className={`${s.notice} ${s.error}`}>{error}</div>}
    {tab === 'content' && <HermesCreationHistory admin accounts={accounts} />}
    {tab === 'publish' && <HermesPublishPlanner admin />}
    {tab === 'schedule' && <div className={s.scheduleGrid}><section className={s.paper}><div className={s.row}><CalendarClock size={18} /><h3 style={{ margin: 0 }}>每日 8 个账号 × 5 篇</h3></div><p className={s.muted} style={{ marginTop: 12 }}>每天创建一批40篇内容，按账号负责人分发到用户创作记录，审核后再进入发布排期。</p>
      <div className={s.advanced}><label className={s.option}><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /><span>启用定时生产</span></label><label className={s.label}>每日开始时间 · 北京时间<input type="time" className={s.input} value={time} onChange={e => setTime(e.target.value)} /></label></div>
      <label className={s.label} style={{ marginTop: 18 }}>默认补充要求<textarea className={s.input} rows={5} value={instruction} maxLength={1000} onChange={e => setInstruction(e.target.value)} placeholder="可选，所有定时任务默认携带这些要求" /></label>
      <div className={s.notice}>当前保存状态：{data?.schedule.enabled ? `每天 ${data.schedule.run_time}` : '已暂停'}<br />上次下发：{data?.schedule.last_enqueued_for || '暂无'}{data?.schedule.last_run_id ? ` · 任务 #${data.schedule.last_run_id}` : ''}</div>
      <button className={s.primary} onClick={save} disabled={saving || !data}>{saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}保存定时配置</button>
    </section><section className={s.paper}><div className={s.between}><h3 style={{ margin: 0 }}>账号与负责关系</h3><span className={s.small}>{draft.length} / 8 个账号 · 每个5篇</span></div><div style={{ margin: '16px 0' }}>{draft.map((a, index) => <div key={index} style={{ borderBottom: '1px solid #e6ebf3', padding: '12px 0' }}><div className={s.row}><select aria-label={`定时账号${index + 1}`} className={s.input} style={{ flex: 1 }} value={a.environment_id || ''} onChange={e => setDraft(old => old.map((v, i) => i === index ? { ...v, environment_id: Number(e.target.value) } : v))}><option value="">选择账号</option>{accounts.map(row => <option key={row.id} value={row.id} disabled={draft.some((d, i) => d.environment_id === row.id && i !== index)}>{row.name}</option>)}</select><select aria-label={`定时车型${index + 1}`} className={s.input} value={a.vehicle_model} onChange={e => setDraft(old => old.map((v, i) => i === index ? { ...v, vehicle_model: e.target.value, case_id: null } : v))}><option value="">车型</option>{models.map(m => <option key={m}>{m}</option>)}</select><button className={s.button} aria-label={`移除账号${index + 1}`} onClick={() => setDraft(old => old.filter((_, i) => i !== index))}><Trash2 size={14} /></button></div><p className={s.small} style={{ marginTop: 8 }}>负责人：{accounts.find(row => row.id === a.environment_id)?.owner_name || '尚未分配，开启前必须分配负责人'}</p></div>)}</div><button className={s.button} disabled={draft.length >= 8} onClick={() => setDraft(old => [...old, { environment_id: 0, vehicle_model: '' }])}><Plus size={14} />添加账号</button></section></div>}
    {tab === 'health' && <><div className={s.statline}><span><b>{data?.workers.filter(w => w.online).length || 0}</b>在线 Worker</span><span><b>{data?.status_counts.queued || 0}</b>排队任务</span><span><b>{data?.status_counts.running || 0}</b>运行任务</span></div>
      <div className={s.notice}><Activity size={17} style={{ flexShrink: 0 }} />这里显示真实心跳，不代表生成接口一定可用。整批回传前不会把“已领取任务”当作“图文已完成”。</div>
      <div className={s.policyList}>{data?.workers.map(w => <article className={s.paper} key={w.worker_id}><div className={s.between}><div className={s.row}><Activity size={18} /><strong>{w.worker_id}</strong></div><span className={s.badge} data-tone={w.online ? 'green' : 'red'}>{w.online ? (w.current_run_id ? '在线 · 执行中' : '在线 · 空闲') : '离线'}</span></div><p className={s.muted} style={{ marginTop: 12 }}>最后心跳：{hermesDate(w.last_seen_at)} · 当前任务：{w.current_run_id ? `#${w.current_run_id}` : '无'}<br />支持车型：{w.capabilities?.models?.join('、') || '未上报'}<br />OCR：{w.capabilities?.image_ocr || '未上报'}</p></article>)}{data && !data.workers.length && <div className={s.empty}>还没有 Worker 心跳记录，请先确认本地 Hermes Worker 已启动。</div>}</div>
      <div className={s.paper} style={{ marginTop: 18 }}><h3 className={s.row}><FileCheck2 size={17} />上线边界</h3><p className={s.copy}>生产、人工审核、发布排期分别记录。修改文案会使原审核与排期失效。<br />审核不通过可选择保留原稿，或单独重新生成这一篇；重生原因交给 Hermes，新稿仍需审核。<br />发布接口未接入，不会执行外部发布。</p></div>
    </>}
    {policyOpen && <HermesPolicyViewer policies={data?.policies || []} onClose={() => setPolicyOpen(false)} />}
  </div></main></div>;
}
