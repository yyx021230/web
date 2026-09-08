'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { ArrowLeft, X } from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
import s from './hermes.module.css';

export function HermesFrame({ title, active, children }: { title: string; active: string; children: ReactNode }) {
  return <div className={s.shell} data-module={active}><main className={s.scroll}><div className={s.container}>
    <header className={s.header}><div className={s.heading}><Link href="/workflows" className={s.back} aria-label="返回工作流广场"><ArrowLeft size={16} /></Link><h1>{title}</h1></div>
      <nav className={s.nav} aria-label="创作模块">{[['batch', '/workflows/hermes', '批量创作'], ['single', '/workflows/hermes/single', '精准单篇'], ['publish', '/workflows/hermes/publish', '发布计划']].map(([key, href, label]) => <Link key={key} href={href} aria-current={active === key ? 'page' : undefined}>{label}</Link>)}</nav>
    </header>{children}</div></main></div>;
}

export function HermesModal({ title, description, children, footer, onClose, bodyClassName = '' }: { title: string; description?: string; children: ReactNode; footer?: ReactNode; onClose: () => void; bodyClassName?: string }) {
  return <Dialog.Root open onOpenChange={open => !open && onClose()}><Dialog.Portal><Dialog.Overlay className={s.overlay} /><Dialog.Content className={s.dialog}>
    <header className={s.dialogHead}><div><Dialog.Title>{title}</Dialog.Title><Dialog.Description className={s.muted}>{description || '查看内容与创作依据'}</Dialog.Description></div><Dialog.Close className={s.button} aria-label="关闭面板"><X size={17} /></Dialog.Close></header>
    <div className={`${s.dialogBody} ${bodyClassName}`}>{children}</div>{footer && <footer className={s.dialogFoot}>{footer}</footer>}
  </Dialog.Content></Dialog.Portal></Dialog.Root>;
}

export function hermesDate(value?: string | null) {
  if (!value) return '—';
  // Backend dates without offsets are explicitly Beijing wall time.
  const date = new Date(/[Zz]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}+08:00`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
}
