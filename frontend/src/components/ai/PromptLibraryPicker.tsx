'use client';

import { useEffect, useRef, useState } from 'react';
import { BookOpen, Image as ImageIcon, Loader2, Search, X } from 'lucide-react';
import { promptsApi, type PromptItem } from '@/services/promptsApi';
import { cn } from '@/lib/utils';
import styles from './PromptLibraryPicker.module.css';

type SourceKind = 'internal' | 'external' | 'performance';

const SOURCES: { key: SourceKind; label: string; description: string }[] = [
  { key: 'internal', label: '内部素材', description: '团队沉淀的创作提示词' },
  { key: 'external', label: '外部素材', description: '外部精选的视觉灵感' },
  { key: 'performance', label: '优质帖子', description: '账户里表现较好的帖子' },
];
const PAGE_SIZE = 24;

interface PromptLibraryPickerProps {
  open: boolean;
  onClose: () => void;
  onSelect: (item: PromptItem, includeImage: boolean) => void;
  referenceCount: number;
}

export default function PromptLibraryPicker({ open, onClose, onSelect, referenceCount }: PromptLibraryPickerProps) {
  const [source, setSource] = useState<SourceKind>('internal');
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<PromptItem[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const requestIdRef = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = query.trim();
      if (next !== search) {
        setItems([]);
        setSelectedId(null);
        setPage(1);
        setSearch(next);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query, search]);

  useEffect(() => {
    if (!open) return;
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');
    promptsApi.getPrompts(search || undefined, undefined, page, PAGE_SIZE, false, undefined, source)
      .then(response => {
        if (requestId !== requestIdRef.current) return;
        const next = response.data.items || [];
        setItems(current => page === 1 ? next : [
          ...current,
          ...next.filter(item => !current.some(existing => existing.id === item.id)),
        ]);
        setTotal(response.data.total || 0);
        setHasMore(next.length > 0 && (response.data.has_more ?? page * PAGE_SIZE < response.data.total));
        if (page === 1) setSelectedId(next[0]?.id ?? null);
      })
      .catch(() => {
        if (requestId !== requestIdRef.current) return;
        setError(source === 'performance' ? '优质帖子加载失败，请检查登录状态后重试' : '素材加载失败，请重试');
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false);
      });
    return () => { requestIdRef.current += 1; };
  }, [open, source, search, page, retry]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const selected = items.find(item => item.id === selectedId) || null;
  const selectedText = (selected?.chinese || selected?.english || '').trim();
  const changeSource = (next: SourceKind) => {
    if (next === source) return;
    setSource(next);
    setItems([]);
    setSelectedId(null);
    setPage(1);
  };
  const changeQuery = (value: string) => {
    setQuery(value);
  };

  return (
    <div className={styles.backdrop} onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label="从提示词库选择素材" className={styles.dialog}>
        <header className={styles.header}>
          <div className={styles.heading}>
            <span className={styles.headingIcon}><BookOpen aria-hidden="true" /></span>
            <div><h2>提示词库</h2><p>挑选灵感，带入当前创作</p></div>
          </div>
          <button type="button" className={styles.close} aria-label="关闭提示词库" onClick={onClose}><X /></button>
        </header>

        <div className={styles.filterBar}>
          <div role="tablist" aria-label="素材来源" className={styles.tabs}>
            {SOURCES.map(tab => (
              <button key={tab.key} type="button" role="tab" aria-selected={source === tab.key}
                className={cn(styles.tab, source === tab.key && styles.activeTab)} onClick={() => changeSource(tab.key)}>
                {tab.label}
              </button>
            ))}
          </div>
          <label className={styles.search}>
            <Search aria-hidden="true" />
            <input aria-label="搜索提示词素材" value={query} onChange={event => changeQuery(event.target.value)} placeholder="搜索标题或内容" />
          </label>
        </div>

        <div className={styles.content}>
          <div className={styles.browser}>
            <div className={styles.listHeading}><span>{SOURCES.find(tab => tab.key === source)?.description}</span><span>{total} 条</span></div>
            {error && <div className={styles.message} role="alert">{error}<button type="button" onClick={() => setRetry(current => current + 1)}>重试</button></div>}
            {!error && loading && items.length === 0 && <div className={styles.message}><Loader2 className={styles.spinner} />正在加载素材…</div>}
            {!error && !loading && items.length === 0 && <div className={styles.message}>没有找到符合条件的素材</div>}
            {items.length > 0 && <div className={styles.grid}>
              {items.map(item => (
                <button key={item.id} type="button" aria-label={`查看素材 ${item.title || item.name || item.id}`}
                  aria-pressed={selectedId === item.id} className={cn(styles.card, selectedId === item.id && styles.selectedCard)}
                  onClick={() => setSelectedId(item.id)}>
                  <span className={styles.cover}>
                    {item.image_url ? <img src={item.image_url} alt="" loading="lazy" /> : <ImageIcon aria-hidden="true" />}
                  </span>
                  <span className={styles.cardText}><strong>{item.title || item.name || '未命名素材'}</strong><small>{item.category || item.source_name || '创作素材'}</small></span>
                </button>
              ))}
            </div>}
            {hasMore && <button type="button" className={styles.more} disabled={loading} onClick={() => setPage(current => current + 1)}>
              {loading ? <Loader2 className={styles.spinner} /> : null}加载更多
            </button>}
          </div>

          <aside className={styles.preview} aria-label="素材预览">
            {selected ? <>
              <div className={styles.previewImage}>{selected.image_url ? <img src={selected.image_url} alt={selected.title || '素材预览'} /> : <ImageIcon aria-hidden="true" />}</div>
              <div className={styles.previewDetails}>
                <span className={styles.sourceLabel}>{SOURCES.find(tab => tab.key === source)?.label} · {selected.category || '未分类'}</span>
                <h3>{selected.title || selected.name || '未命名素材'}</h3>
                <p>{selectedText || '这条素材暂无文字描述，可只添加图片作为参考。'}</p>
              </div>
              <div className={styles.actions}>
                <span>将替换输入框中的文字，生成前仍可编辑</span>
                <div>
                  <button type="button" className={styles.textOnly} disabled={!selectedText} onClick={() => onSelect(selected, false)}>只用文字</button>
                  <button type="button" className={styles.withImage} disabled={!selected.image_url || referenceCount >= 10}
                    title={referenceCount >= 10 ? '参考图已满 10 张' : undefined} onClick={() => onSelect(selected, true)}>
                    文字 + 参考图
                  </button>
                </div>
              </div>
            </> : <div className={styles.emptyPreview}>选择一张素材，查看完整内容</div>}
          </aside>
        </div>
      </div>
    </div>
  );
}
