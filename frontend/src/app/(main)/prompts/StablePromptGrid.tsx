'use client';

import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import type { PromptItem } from '@/services/promptsApi';
import styles from './prompts.module.css';

export function coverRatio(item: PromptItem): number {
  const width = item.image_width || 0;
  const height = item.image_height || 0;
  return width > 0 && height > 0 && Number.isFinite(width / height) ? width / height : 3 / 4;
}

export function arrangePromptColumns(
  items: PromptItem[],
  count: number,
  width: number,
  previous: number[][] = [],
): number[][] {
  const byId = new Map(items.map(item => [item.id, item]));
  const columns = Array.from({ length: count }, (_, index) =>
    previous.length === count ? previous[index].filter(id => byId.has(id)) : [],
  );
  const placed = new Set(columns.flat());
  const heights = columns.map(column => column.reduce((sum, id) => sum + width / coverRatio(byId.get(id)!) + 12, 0));
  for (const item of items) {
    if (placed.has(item.id)) continue;
    const index = heights.indexOf(Math.min(...heights));
    columns[index].push(item.id);
    heights[index] += width / coverRatio(item) + 12;
    placed.add(item.id);
  }
  return columns;
}

export function StablePromptGrid({ items, children }: {
  items: PromptItem[];
  children: (item: PromptItem) => ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [columns, setColumns] = useState<number[][]>([]);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    const minWidth = parseFloat(getComputedStyle(ref.current!).getPropertyValue('--cover-min-width')) || 300;
    const count = Math.max(1, Math.floor((width + 12) / (minWidth + 12)));
    const columnWidth = Math.max(1, (width - (count - 1) * 12) / count);
    // Existing IDs never change columns when appending or deleting. Only resize
    // across a column-count breakpoint rebuilds the layout.
    setColumns(previous => arrangePromptColumns(items, count, columnWidth, previous));
  }, [items, width]);

  const byId = new Map(items.map(item => [item.id, item]));
  return <div ref={ref} className={styles.gallery} data-testid="prompt-grid"
    style={{ gridTemplateColumns: `repeat(${columns.length || 1}, minmax(0, 1fr))` }}>
    {columns.map((column, index) => <div key={index} className={styles.galleryColumn} data-prompt-column={index}>
      {column.map(id => { const item = byId.get(id); return item ? children(item) : null; })}
    </div>)}
  </div>;
}
