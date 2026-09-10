'use client';
import { useRef, useState } from 'react';
import { Check, Copy, FilePenLine, History, Loader2, RefreshCw, X } from 'lucide-react';
import { toast } from '@/lib/toast';
import { hermesWorkflowApi, type HermesPost } from '@/services/hermesWorkflowApi';
import { HermesModal, hermesDate } from './HermesFrame';
import s from './hermes.module.css';

function text(value: unknown): string { return typeof value === 'string' || typeof value === 'number' ? String(value) : ''; }
function records(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.filter(v => v && typeof v === 'object') : []; }
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }

export type HermesInspectorTab = 'post' | 'copy' | 'image' | 'history' | 'edit' | 'review';

export default function HermesPostInspector({ post, admin = false, initialTab = 'post', runError, onClose, onSaved }: { post: HermesPost; admin?: boolean; initialTab?: HermesInspectorTab; runError?: string | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const [tab, setTab] = useState<HermesInspectorTab>(initialTab);
  const [title, setTitle] = useState(post.title || '');
  const [content, setContent] = useState(post.content || '');
  const [note, setNote] = useState('');
  const [reviewNote, setReviewNote] = useState(post.status === 'rejected' ? post.review_comment || '' : '');
  const [regenerate, setRegenerate] = useState(false);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const source = post.source_detail || {};
  const accountHistory = record(source.account_history);
  const repetition = record(source.account_repetition);
  const dirty = title !== (post.title || '') || content !== (post.content || '');
  const editable = ['review_pending', 'approved', 'rejected', 'publish_ready'].includes(post.status);
  const events = records(source.events);
  function close() { if (!busy && (!dirty || window.confirm('有尚未保存的文案修改，确定离开吗？'))) onClose(); }
  function changeTab(next: HermesInspectorTab) {
    if (busy) return;
    if (tab === 'edit' && next !== 'edit' && dirty) {
      if (!window.confirm('文案修改尚未保存，放弃这些修改并切换吗？')) return;
      setTitle(post.title || ''); setContent(post.content || ''); setNote('');
    }
    setTab(next);
  }
  async function review(action: 'approve' | 'reject') {
    if (lock.current || dirty) return;
    if (action === 'reject' && !reviewNote.trim()) return toast.error('请填写不通过的具体原因');
    if (!post.version) return toast.error('未取得版本信息，请刷新后重试');
    lock.current = true; setBusy(true);
    try {
      const result = await (admin ? hermesWorkflowApi.adminReviewPost : hermesWorkflowApi.reviewPost)(post.id, action, action === 'reject' ? reviewNote.trim() : undefined, post.version, action === 'reject' && regenerate);
      toast.success(action === 'approve' ? '审核通过，可进入发布计划' : regenerate ? `已标为不通过，重生任务 #${result.data.regenerated_run_id} 已入队` : '已标为不通过，保留原稿，未触发重新生成');
      await onSaved(); onClose();
    } catch (e) { toast.error(e instanceof Error ? e.message : '保存失败'); }
    finally { lock.current = false; setBusy(false); }
  }
  async function save() {
    if (lock.current || !dirty) return;
    if (!note.trim()) return toast.error('请简要说明改了什么');
    if (!post.version) return toast.error('未取得版本信息，请刷新后重试');
    lock.current = true; setBusy(true);
    try {
      await hermesWorkflowApi.editPost(post.id, { title, content, comment: note, expected_version: post.version });
      toast.success('修改前后内容和具体差异已记录，新版本待审核'); await onSaved(); onClose();
    } catch (e) { toast.error(e instanceof Error ? e.message : '保存失败'); }
    finally { lock.current = false; setBusy(false); }
  }
  async function copy() { try { await navigator.clipboard.writeText(`${post.title || ''}\n\n${post.content || ''}`); toast.success('标题与完整正文已复制'); } catch { toast.error('无法复制，请手动选中文字'); } }
  return <HermesModal title={post.title || `第 ${post.slot} 篇`} description={`${post.account_name} · ${post.vehicle_model} · V${post.revision || 1} · 任务 #${post.run_id}`} onClose={close}
    footer={<><span className={s.muted}>{tab === 'review' ? '原稿保留；不通过或编辑后，已有发布排期将撤销。' : tab === 'edit' ? '自动记录修改人、时间与逐字段差异；图片保持不变。' : source.manual_edit_requires_review ? '人工编辑版本，请核对文案与图片是否一致。' : '保留标题、正文、emoji 与末尾话题标签。'}</span><div className={s.row}>
      {busy && <Loader2 size={15} className="animate-spin" />}
      {tab === 'edit' ? <button className={s.primary} disabled={busy || !dirty || !note.trim() || !title.trim() || !content.trim()} onClick={save}>保存新版本 · 重新待审</button> : tab === 'review' ? <><button className={s.button} disabled={busy} onClick={close}>取消</button><button className={s.rejectPrimary} disabled={busy || !reviewNote.trim() || !editable} onClick={() => review('reject')}>{regenerate ? <RefreshCw size={14} /> : <X size={14} />}{regenerate ? '不通过并重新生成' : '确认不通过'}</button></> : <>
        {editable && <button className={s.button} disabled={busy} onClick={() => changeTab('edit')}><FilePenLine size={14} />编辑文案</button>}
        {editable && <button className={s.rejectButton} disabled={busy} onClick={() => changeTab('review')}>不通过</button>}
        {['review_pending', 'rejected'].includes(post.status) && <button className={s.primary} disabled={busy || dirty} onClick={() => review('approve')}><Check size={14} />审核通过</button>}
      </>}
    </div></>}>
    <div className={s.toolbar}><div className={s.nav} role="tablist" aria-label="帖子详情">{[['post', '完整图文'], ['copy', '文案对照'], ['image', '生图依据'], ['history', `修改记录${events.length ? ` · ${events.length}` : ''}`], ...(tab === 'edit' ? [['edit', '编辑文案']] : tab === 'review' ? [['review', '不通过处理']] : [])].map(([key, label]) => <button key={key} className={s.tab} role="tab" aria-selected={tab === key} disabled={busy} onClick={() => changeTab(key as HermesInspectorTab)}>{label}</button>)}</div><button className={s.button} onClick={copy}><Copy size={13} />复制图文文案</button></div>
    {(text(source.error) || runError) && <p className={`${s.notice} ${s.error}`}>{text(source.error) || runError}</p>}
    {post.review_comment && tab === 'post' && <p className={s.notice}>{post.status === 'rejected' ? '不通过原因：' : '修改说明：'}{post.review_comment}</p>}
    {tab === 'review' && <div className={s.reviewPanel}><div className={s.reviewIntro}><span className={s.reviewIcon}><X size={20} /></span><div><h3>这篇内容哪里需要调整？</h3><p>不通过原因会保留在审核记录里；是否重新生成，由你决定。</p></div></div><label className={s.label}>不通过原因 <textarea aria-label="不通过原因" className={s.input} disabled={busy} rows={3} maxLength={1000} value={reviewNote} onChange={e => setReviewNote(e.target.value)} placeholder="例如：第二段配置与车型不符；图片上的价格条件需要补全……" /></label><fieldset className={s.reviewOptions}><legend>接下来怎么处理</legend><label data-selected={!regenerate}><input type="radio" disabled={busy} name={`post-${post.id}-regenerate`} checked={!regenerate} onChange={() => setRegenerate(false)} /><span><strong>仅标记不通过</strong><small>保留原稿和原因，可稍后人工编辑，不调用生成接口。</small></span></label><label data-selected={regenerate}><input type="radio" disabled={busy} name={`post-${post.id}-regenerate`} checked={regenerate} onChange={() => setRegenerate(true)} /><span><strong>重新生成这一篇图文</strong><small>沿用账号、车型和图文类型，按下发时最新政策生成；将原因交给 AI，原稿保留，新稿重新待审。</small></span></label></fieldset>{regenerate && <p className={s.notice}>将创建 1 篇关联新任务，进入 Hermes 队列，并产生模型与生图调用；不会重跑同批其他帖子。生成结果仍需审核。</p>}</div>}
    {tab === 'post' && <div className={s.inspector}><div>{post.image_url ? <a href={post.image_url} target="_blank" rel="noreferrer" title="打开原尺寸图片"><img className={s.largeImage} src={post.image_url} alt={post.title || '生成配图'} /></a> : <div className={s.empty}>暂无可展示配图</div>}<p className={s.small} style={{ marginTop: 9 }}>按原图比例完整展示 · 点击打开原尺寸</p></div><article className={s.paper}><h3>{post.title || '暂无标题'}</h3><div className={s.copy}>{post.content || '正文尚未完成'}</div></article></div>}
    {tab === 'copy' && <>
      <div className={s.historyEvidence}><History size={16} /><div><strong>账号避重参考 · {post.account_name}</strong><p>{typeof accountHistory.history_posts === 'number' ? <>本次参考 {accountHistory.history_posts} 条已同步帖子（最多 15 条）{typeof accountHistory.history_missing_body === 'number' && accountHistory.history_missing_body > 0 ? `，其中 ${accountHistory.history_missing_body} 条缺正文，只参考标题。` : '。'}{text(accountHistory.latest_published_at) && ` 最新一条发布于 ${hermesDate(text(accountHistory.latest_published_at))}。`}</> : '该历史任务未保存账号参考快照，不能据此认定已检查最近15条。'}</p>{repetition.status === 'high_similarity' && <p className={s.danger}>高度相似提醒：建议对照「{text(repetition.closest_title) || '账号近期帖子'}」人工确认；未自动拦截。</p>}<small>普通相似可以接受；同车型、同政策、相同话题不单独判为重复。</small></div></div>
      {typeof repetition.compared_bodies === 'number' && <p className={s.historyCheck}>生成后实际比对 {repetition.compared_bodies} 篇有效正文{repetition.status === 'insufficient_history' ? ' · 历史正文不足，无法判断全文重复' : repetition.status === 'high_similarity' ? ' · 检出高度相似，仅提醒' : ' · 未检出高度重复'}。缺失或过短正文不参与全文比较，不代表已核对小红书实时最新内容。{source.manual_edit_requires_review ? ' 此记录针对生成稿，人工修改后未重新计算。' : ''}</p>}
      <div className={s.compare}><article className={s.paper}><div className={s.small}>参考文案 · #{text(source.mother_copy_id) || '未记录'}</div><h3 style={{ marginTop: 12 }}>{text(source.mother_title) || '历史记录未保存原文标题'}</h3><div className={s.copy}>{text(source.mother_content) || '历史记录未保存参考正文，不能据此判断复刻差异。'}</div></article><article className={s.paper}><div className={s.small}>当前文案 · V{post.revision || 1}</div><h3 style={{ marginTop: 12 }}>{post.title}</h3><div className={s.copy}>{post.content || '尚未完成'}</div></article></div>
    </>}
    {tab === 'image' && <>
      <div className={s.compare}><article className={s.paper}><h3>原始母图 · #{text(source.selected_prompt_id) || '未记录'}</h3>{text(source.selected_prompt_image) && <a href={text(source.selected_prompt_image)} target="_blank" rel="noreferrer"><img src={text(source.selected_prompt_image)} alt="提示词库原始示例图" /></a>}<div className={s.copy}>{text(source.selected_prompt_original) || '原始提示词未记录'}</div></article><article className={s.paper}><h3>改造后提示词</h3>{post.image_url && <img src={post.image_url} alt="本次生成结果" />}<div className={s.copy}>{text(source.adapted_prompt) || '改造后提示词未记录'}</div></article></div>
      <div className={s.notice}>场景变化：{text(source.scene_change) || '历史记录未单独说明'}{text(source.vehicle_image) && <a className={s.textButton} href={text(source.vehicle_image)} target="_blank" rel="noreferrer">查看对应车型辅助图 ↗</a>}</div>
      <div className={s.tableWrap}><table className={s.table}><thead><tr><th>原图文字</th><th>处理方式</th><th>新图文字</th></tr></thead><tbody>{records(source.slot_mappings).map((m, i) => <tr key={i}><td>{text(m.source)}</td><td>{text(m.action)}</td><td>{text(m.output)}</td></tr>)}{!records(source.slot_mappings).length && <tr><td colSpan={3}>该历史记录没有逐项文字映射。</td></tr>}</tbody></table></div>
      <details className={s.paper} style={{ marginTop: 16 }}><summary>查看 OCR 识别文字</summary><div className={s.copy} style={{ marginTop: 14 }}>{Array.isArray(source.ocr_lines) ? source.ocr_lines.map(v => text(v) || text(v?.text)).filter(Boolean).join('\n') : '未记录 OCR 明细'}</div></details>
    </>}
    {tab === 'history' && <div className={s.timeline}><div className={s.event}><strong>当前版本 V{post.revision || 1}</strong><p className={s.muted}>保留修改人、时间、原因与修改前后内容，原始母文和生图依据不变。</p></div>{[...events].reverse().map((event, i) => <div className={s.event} key={i}><strong>{({ edit: '编辑文案', approve: '审核通过', reject: '审核不通过', regenerate: '发起单篇重生', schedule: '保存发布排期' } as Record<string, string>)[text(event.action)] || text(event.action)}</strong><p className={s.small}>{hermesDate(text(event.at))} · {text(event.user_name) || `操作人 #${text(event.user_id)}`} · V{text(event.revision)}{event.result_revision ? ` → V${text(event.result_revision)}` : ''}</p><p className={s.copy}>{text(event.comment)}</p>{event.regenerated_run_id ? <a className={s.regenerationLink} href={`${admin ? '/admin/workflows' : '/workflows/hermes'}?run=${text(event.regenerated_run_id)}`}>查看关联任务 #{text(event.regenerated_run_id)} ↗</a> : null}{event.action === 'edit' && <EditChanges event={event} />}</div>)}{!events.length && <p className={s.muted}>该历史帖子尚无审改记录。旧系统未记录的操作不会补写成虚构历史。</p>}</div>}
    {tab === 'edit' && <div className={s.inspector}><div>{post.image_url && <img className={s.largeImage} src={post.image_url} alt="配图保持不变，编辑时对照" />}<p className={s.notice}>可修改标题与完整正文，图片不变。系统自动记录具体改动；保存后需要重新核对图文并审核，已有排期会撤销。</p></div><div className={s.paper}><label className={s.label}>标题 · {title.length}/80<input aria-label="编辑标题" className={s.input} disabled={busy} value={title} maxLength={80} onChange={e => setTitle(e.target.value)} /></label><label className={s.label} style={{ marginTop: 14 }}>完整正文 · {content.length}/1000<textarea aria-label="编辑正文" className={s.input} disabled={busy} rows={15} maxLength={1000} value={content} onChange={e => setContent(e.target.value)} /></label><label className={s.label} style={{ marginTop: 14 }}>修改说明<textarea aria-label="修改说明" className={s.input} disabled={busy} rows={2} value={note} maxLength={1000} onChange={e => setNote(e.target.value)} placeholder="简述为什么修改；具体文字差异由系统自动记录" /></label></div></div>}
  </HermesModal>;
}

function EditChanges({ event }: { event: Record<string, unknown> }) {
  const changes = record(event.changes);
  const fields = Object.keys(changes).filter(field => ['title', 'content'].includes(field));
  if (!fields.length) return <details className={s.paper} style={{ marginTop: 10 }}><summary>查看修改前完整版本</summary><p className={s.small}>此旧记录未保存逐字段差异，仅展示已保存的修改前内容。</p><h3 style={{ marginTop: 15 }}>{text(event.title)}</h3><div className={s.copy}>{text(event.content)}</div></details>;
  return <details className={s.editDiff} open><summary>修改了{fields.map(field => field === 'title' ? '标题' : '正文').join('、')} <span>红色为删除 · 绿色为新增</span></summary>{fields.map(field => {
    const change = record(changes[field]);
    const segments = records(change.segments);
    return <section key={field}><h4>{field === 'title' ? '标题变化' : '正文变化'}</h4><div className={s.compare}>{(['before', 'after'] as const).map(side => <article key={side}><small>{side === 'before' ? '修改前' : '修改后'}</small><div className={s.diffText}>{segments.length ? segments.filter(segment => segment.kind !== (side === 'before' ? 'added' : 'removed')).map((segment, index) => <span key={index} data-kind={text(segment.kind)}>{text(segment.text)}</span>) : text(change[side])}</div></article>)}</div></section>;
  })}</details>;
}
