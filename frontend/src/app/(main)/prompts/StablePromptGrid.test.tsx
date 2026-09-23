import { describe, expect, it } from 'vitest';
import { arrangePromptColumns, coverRatio } from './StablePromptGrid';
import type { PromptItem } from '@/services/promptsApi';

const items: PromptItem[] = Array.from({ length: 90 }, (_, id) => ({
  id, title: String(id), chinese: '', english: '', image_url: `/uploads/${id}.png`,
  category: '', param_type: '', image_width: 600, image_height: [400, 600, 800, 1000][id % 4],
}));

describe('stable prompt masonry', () => {
  it('appends three pages without changing any existing column or position', () => {
    let columns = arrangePromptColumns(items.slice(0, 30), 5, 300);
    for (const size of [60, 90]) {
      const next = arrangePromptColumns(items.slice(0, size), 5, 300, columns);
      columns.forEach((column, index) => expect(next[index].slice(0, column.length)).toEqual(column));
      expect(new Set(next.flat()).size).toBe(size);
      columns = next;
    }
  });

  it('deletes exactly one card and does not redistribute cards in other columns', () => {
    const before = arrangePromptColumns(items, 5, 300);
    const deleted = before[2][1];
    const after = arrangePromptColumns(items.filter(item => item.id !== deleted), 5, 300, before);
    expect(after).toEqual(before.map(column => column.filter(id => id !== deleted)));
    expect(after.flat()).toHaveLength(89);
  });

  it('does not move old cards when a response returns existing IDs in another order', () => {
    const before = arrangePromptColumns(items.slice(0, 30), 4, 300);
    expect(arrangePromptColumns(items.slice(0, 30).reverse(), 4, 300, before)).toEqual(before);
  });

  it('reflows on a real responsive column-count change without losing cards', () => {
    const desktop = arrangePromptColumns(items, 5, 300);
    const mobile = arrangePromptColumns(items, 2, 145, desktop);
    expect(mobile).toHaveLength(2);
    expect(mobile.flat().sort((a, b) => a - b)).toEqual(items.map(item => item.id));
  });

  it('uses real dimensions and a fixed fallback for missing metadata', () => {
    expect(coverRatio(items[0])).toBe(1.5);
    expect(coverRatio({ ...items[0], image_width: undefined })).toBe(0.75);
    expect(coverRatio({ ...items[0], image_width: Infinity })).toBe(0.75);
  });
});
