'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, ImagePlus, X } from 'lucide-react';
import { hermesWorkflowApi, type HermesAccount, type HermesPost } from '@/services/hermesWorkflowApi';
import { HermesModal } from './HermesFrame';
import s from './hermes.module.css';
import u from './hermes-upload.module.css';

function uploadRequestId() {
  // The current HTTP ingress is not a secure context, so randomUUID may be absent.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export default function HermesUploadComposer({ accounts, maxImages = 5, onClose, onSaved }: {
  accounts: HermesAccount[]; maxImages?: number; onClose: () => void; onSaved: (post: HermesPost) => Promise<void>;
}) {
  const [account, setAccount] = useState('');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const lock = useRef(false);
  const requestId = useRef('');
  const dirty = Boolean(title || content || files.length);
  useEffect(() => {
    const urls = files.map(file => URL.createObjectURL(file));
    setPreviews(urls);
    return () => urls.forEach(url => URL.revokeObjectURL(url));
  }, [files]);
  function close() {
    if (!busy && (!dirty || window.confirm(uncertain ? '上传结果未确认，请先到列表核查。确定关闭？' : '图文尚未保存，确定关闭？'))) onClose();
  }
  function addFiles(incoming: File[]) {
    if (incoming.some(file => !['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || !file.size || file.size > 3_000_000)) {
      setError('仅支持PNG、JPEG、WebP，每张不超过3MB'); return;
    }
    if (files.length + incoming.length > maxImages) { setError(`一篇最多上传${maxImages}张图片`); return; }
    setFiles(old => [...old, ...incoming]); setError('');
  }
  function move(index: number, offset: number) {
    setFiles(old => { const next = [...old]; [next[index], next[index + offset]] = [next[index + offset], next[index]]; return next; });
  }
  async function save() {
    if (lock.current) return;
    if (!account || !title.trim() || !content.trim() || !files.length) { setError('请选择发布账号，填写标题、正文并上传图片'); return; }
    if (title.trim().length > 100 || content.trim().length > 2000) { setError('标题或正文超过云手机接口限制，请缩短后保存'); return; }
    lock.current = true; setBusy(true); setError('');
    requestId.current ||= uploadRequestId();
    try {
      const result = await hermesWorkflowApi.uploadPost({ request_id: requestId.current, environment_id: Number(account), title: title.trim(), content: content.trim() }, files);
      await onSaved(result.data);
    } catch (e) {
      const status = (e as Error & { status?: number }).status;
      const unknown = !status || status >= 500;
      setUncertain(unknown);
      setError(unknown ? '保存结果未确认。请先关闭并刷新列表核查，或以相同内容重试；不会创建第二份草稿。' : e instanceof Error ? e.message : '保存失败');
    } finally { lock.current = false; setBusy(false); }
  }
  const disabled = busy || uncertain;
  return <HermesModal title="上传图文" description="自己准备内容，复用同一套审核、排期与云手机发布流程" onClose={close}
    footer={<><span className={s.muted}>这里只保存草稿，不调用AI、不立即发布；确认图文后再安排时间。</span><button className={s.primary} disabled={busy} onClick={save}>{busy ? '正在保存…' : uncertain ? '核查并重试保存' : '保存草稿并确认图文'}</button></>}>
    {error && <p className={`${s.notice} ${s.error}`} role="alert">{error}</p>}
    <div className={u.layout}><section className={u.images} aria-label="上传图片">
      <div className={s.between}><h3>图片 <span className={s.small}>{files.length} / {maxImages}</span></h3><span className={s.small}>第1张为封面 · 按序发布</span></div>
      <label className={u.dropzone} onPaste={e => { if (!disabled) { const pasted = Array.from(e.clipboardData.files); if (pasted.length) { e.preventDefault(); addFiles(pasted); } } }}
        onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!disabled) addFiles(Array.from(e.dataTransfer.files)); }}>
        <ImagePlus size={25} /><strong>选择图片或拖到这里</strong><small>PNG / JPEG / WebP，每张最多3MB</small>
        <input aria-label="选择图文图片" type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={disabled} onChange={e => { addFiles(Array.from(e.target.files || [])); e.target.value = ''; }} />
      </label>
      <div className={u.thumbnails}>{files.map((file, index) => <article key={`${file.name}-${index}`}>
        <img src={previews[index]} alt={`第${index + 1}张：${file.name}`} /><span>{index === 0 ? '封面' : index + 1}</span>
        <div><button className={s.iconButton} disabled={disabled || index === 0} aria-label={`前移第${index + 1}张`} onClick={() => move(index, -1)}><ArrowLeft size={14} /></button><button className={s.iconButton} disabled={disabled || index === files.length - 1} aria-label={`后移第${index + 1}张`} onClick={() => move(index, 1)}><ArrowRight size={14} /></button><button className={s.iconButton} disabled={disabled} aria-label={`移除第${index + 1}张`} onClick={() => setFiles(old => old.filter((_, i) => i !== index))}><X size={14} /></button></div>
      </article>)}</div>
    </section><section className={u.fields}>
      <label className={s.label}>发布账号<select className={s.input} aria-label="上传图文发布账号" disabled={disabled} value={account} onChange={e => setAccount(e.target.value)}><option value="">请选择账号</option>{accounts.map(item => <option key={item.id} value={item.id}>{item.name}{item.owner_name ? ` · ${item.owner_name}` : ''}</option>)}</select></label>
      <label className={s.label}>标题 · {title.length}/80<input className={s.input} aria-label="上传图文标题" disabled={disabled} maxLength={80} value={title} onChange={e => setTitle(e.target.value)} /></label>
      <label className={s.label}>正文 · {content.length}/1000<textarea className={s.input} aria-label="上传图文正文" disabled={disabled} rows={13} maxLength={1000} value={content} onChange={e => setContent(e.target.value)} placeholder="填写完整正文，可保留emoji和话题标签" /></label>
      <p className={s.notice}>保存后需人工确认全部图片及文案。发布账号在审核时固定，不能排期时临时换号。</p>
    </section></div>
  </HermesModal>;
}
