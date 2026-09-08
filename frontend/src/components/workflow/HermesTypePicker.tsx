'use client';

import { useState } from 'react';
import { ArrowRight, Check, FileText, ImageIcon, Layers3 } from 'lucide-react';
import type { HermesReferenceCatalog, HermesReferenceExample, HermesReferenceType } from '@/services/hermesWorkflowApi';
import { HermesModal, hermesDate } from './HermesFrame';
import HermesTypePreview from './HermesTypePreview';
import s from './hermes.module.css';

export function HermesTypeChoice({ kind, type, onClick }: { kind: 'copy' | 'image'; type?: HermesReferenceType; onClick: () => void }) {
  const Icon = kind === 'copy' ? FileText : ImageIcon;
  return <button type="button" className={s.typeChoice} onClick={onClick} data-selected={!!type} data-tone={type?.accent || (kind === 'copy' ? 'sage' : 'blue')} aria-label={`选择${kind === 'copy' ? '文案' : '图片'}类型与实例`}>
    <span className={s.typeChoiceArt}>{type ? <HermesTypePreview id={type.id} small /> : <Icon size={25} strokeWidth={1.4} />}</span>
    <span className={s.typeChoiceText}><small>{kind === 'copy' ? '文案方向' : '图片版式'}</small><strong>{type?.name || (kind === 'copy' ? '选择文案类型' : '选择图片类型')}</strong></span><span className={s.typeChoiceAction}>{type ? '更换' : '看案例'}<ArrowRight size={14} /></span>
  </button>;
}

export default function HermesTypePicker({ kind, catalog, value, quoteAllowed, onSelect, onClose }: {
  kind: 'copy' | 'image'; catalog: HermesReferenceCatalog; value: string; quoteAllowed: boolean;
  onSelect: (type: HermesReferenceType) => void; onClose: () => void;
}) {
  const types = kind === 'copy' ? catalog.copy_types : catalog.image_types;
  const [active, setActive] = useState(value || types.find(t => t.reference_count > 0)?.id || types[0]?.id);
  const [expanded, setExpanded] = useState<number | null>(null);
  const selected = types.find(t => t.id === active);
  const blocked = kind === 'image' && active === 'quote_table' && !quoteAllowed;
  return <HermesModal title={kind === 'copy' ? '选择文案方向' : '选择图片版式'} description="文案与图片独立选择，自由组合。" onClose={onClose} bodyClassName={s.typeDialogBody}
    footer={<><span className={s.muted}>{blocked ? '报价单需先选择有完整配置价格的车型。' : '按所选类型随机匹配母版，不固定使用展示案例。'}</span><button className={s.primary} disabled={!selected || blocked} onClick={() => selected && onSelect(selected)}><Check size={15} />使用{selected?.name || '此类型'}</button></>}>
    <div className={s.typeBrowser}>
      <aside className={s.typeRail}><div className={s.typeRailTitle}><Layers3 size={15} />{types.length} 种{kind === 'copy' ? '文案方向' : '图片版式'}</div>
        {types.map(t => <button key={t.id} className={s.typeTab} data-active={active === t.id} data-tone={t.accent} aria-label={t.name} aria-pressed={active === t.id} onClick={() => { setActive(t.id); setExpanded(null); }}><HermesTypePreview id={t.id} small /><span className={s.typeTabText}><strong>{t.name}</strong><small>{t.description}</small></span><span className={s.typeCount}>{active === t.id ? <Check size={13} /> : t.reference_count || '0'}</span></button>)}
      </aside>
      <section className={s.typeResults}>{selected && <>
        <header className={s.typeDetailHead} data-tone={selected.accent}><div className={s.typeDetailIntro}><span className={s.eyebrow}>{kind === 'copy' ? '文案方向' : '图片版式'}</span><h3>{selected.name}</h3><p>{selected.description}</p><div className={s.structureNote}>{selected.structure}</div></div><figure className={s.typeSketch}><HermesTypePreview id={selected.id} /><figcaption>结构示意 · 非母版</figcaption></figure></header>
        {blocked && <p className={s.typeWarning}>该版式包含多个配置的报价，需所选车型有完整配置价格后才能使用。</p>}
        <div className={s.typeExamplesHeading}><strong>{catalog.source === 'synced_online_library' ? '线上库真实案例' : '库内真实案例'}</strong><span>{selected.reference_count} 条 · 展示 {selected.examples.length} 条</span></div>
        {!selected.examples.length && <div className={s.typeEmpty}><ImageIcon size={22} strokeWidth={1.4} /><strong>{selected.reference_count ? '本地原图暂不可用' : '本地暂无此类型案例'}</strong><p>上方示意只说明结构。生产时从线上库匹配这一类型，候选不足会明确提示，不换成其他类型。</p></div>}
        <div className={kind === 'image' ? s.imageExamples : s.copyExamples}>{selected.examples.map(example => <ExampleCard key={`${selected.id}-${example.id}`} example={example} expanded={expanded === example.id} onExpand={() => setExpanded(expanded === example.id ? null : example.id)} />)}</div>
        <details className={s.sourceNote}><summary>{catalog.synced_at ? `案例同步于 ${hermesDate(catalog.synced_at)} · 使用说明` : '案例来源与使用说明'}</summary><p>{catalog.source_note} 旧车型、旧政策不直接沿用；结构示意不用于生产，也不是固定模板。</p></details>
      </>}</section>
    </div>
  </HermesModal>;
}

function ExampleCard({ example, expanded, onExpand }: { example: HermesReferenceExample; expanded: boolean; onExpand: () => void }) {
  const [imageFailed, setImageFailed] = useState(false);
  return <article className={s.exampleCard}>
    {example.preview_note && <p className={s.typeWarning}>{example.preview_note}</p>}
    {example.image_url && (imageFailed ? <div className={s.empty}>原图暂不可用，仍可查看下方原始提示词。</div> : <a className={s.exampleImage} href={example.image_url} target="_blank" rel="noreferrer"><img src={example.image_url} alt={`提示词库原始示例 #${example.id}`} loading="lazy" onError={() => setImageFailed(true)} /><span>打开原图 ↗</span></a>)}
    <div className={s.exampleBody}><div className={s.between}><span className={s.eyebrow}>{example.kind === 'copy' ? '文案库' : '提示词库'} #{example.id}</span><span className={s.small}>原始参考</span></div><h4>{example.title}</h4><div className={s.exampleCopy} data-expanded={expanded}>{example.content}</div><button className={s.textButton} onClick={onExpand}>{expanded ? '收起' : example.kind === 'copy' ? '读完整原文与话题' : '查看完整原始提示词'}<ArrowRight size={12} /></button></div>
  </article>;
}
