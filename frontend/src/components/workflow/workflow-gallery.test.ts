import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WorkflowGalleryCards from './WorkflowGalleryCards';

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

describe('workflow gallery entrances', () => {
  it('keeps three whole-card links with distinct destinations and accessible titles', async () => {
    await act(async () => root.render(React.createElement(WorkflowGalleryCards)));
    const cards = Array.from(host.querySelectorAll('a[data-workflow]'));
    expect(cards.map(card => card.getAttribute('href'))).toEqual(['/workflows/hermes', '/workflows/hermes/single', '/workflows/hermes/publish']);
    for (const card of cards) {
      expect(document.getElementById(card.getAttribute('aria-labelledby')!)?.textContent).toBeTruthy();
      expect(document.getElementById(card.getAttribute('aria-describedby')!)?.textContent).toBeTruthy();
      expect(card.querySelector('button, a')).toBeNull();
    }
  });

  it('reuses original cover artwork and removes the two decorative type labels', async () => {
    await act(async () => root.render(React.createElement(WorkflowGalleryCards)));
    expect(host.querySelector('[data-visual="batch"] img')?.getAttribute('src')).toBe('/workflows/hermes-cover-stack.png');
    expect(host.querySelector('[data-visual="single"] img')?.getAttribute('src')).toBe('/workflows/single-post-cover.png');
    const single = host.querySelector('[data-workflow="single"]')!;
    expect(single.textContent).not.toContain('文案类型');
    expect(single.textContent).not.toContain('图片类型');
    expect(host.querySelectorAll('[data-visual][aria-hidden="true"]')).toHaveLength(3);
    expect(host.querySelector('[data-visual="publish"]')?.textContent).toContain('排期示意');
  });
});
