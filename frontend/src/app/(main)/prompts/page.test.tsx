import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AxiosHeaders, type AxiosResponse } from 'axios';
import PromptsPage from './page';
import { promptsApi, type PromptItem } from '@/services/promptsApi';
import { useOptionalAuthSession } from '@/components/auth/AuthSession';

vi.mock('@/services/promptsApi', () => ({
  promptsApi: {
    getPrompts: vi.fn(), getCategories: vi.fn(), getMyReports: vi.fn(),
    getReportReasons: vi.fn(), deletePrompt: vi.fn(), reportPrompt: vi.fn(),
  },
}));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/components/auth/AuthSession', () => ({ useOptionalAuthSession: vi.fn(() => null) }));

const entry = {
  id: 7, title: '汽车光影', chinese: '完整的中文提示词', english: 'Full English prompt',
  image_url: '/cover.png', category: '摄影', param_type: '通用',
  created_by_name: '创作者', can_edit: true, can_delete: true,
};
function response<T>(data: T): AxiosResponse<T> {
  return { data, status: 200, statusText: 'OK', headers: {}, config: { headers: new AxiosHeaders() } };
}
const result = (items: PromptItem[] = [entry], total = items.length, page = 1) => response({ items, total, page, limit: 30 });
let host: HTMLDivElement;
let root: Root;
let intersectionCallback: IntersectionObserverCallback | undefined;
async function mount() { await act(async () => root.render(<PromptsPage />)); }
function button(text: string) {
  return Array.from(document.querySelectorAll('button')).find(el => el.textContent?.trim() === text)!;
}

beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.mocked(promptsApi.getPrompts).mockReset().mockResolvedValue(result());
  vi.mocked(promptsApi.getCategories).mockResolvedValue(response({ categories: [{ name: '摄影', count: 24 }] }));
  vi.mocked(useOptionalAuthSession).mockReturnValue(null);
  vi.mocked(promptsApi.deletePrompt).mockReset().mockResolvedValue(response({}));
  vi.stubGlobal('confirm', vi.fn(() => true));
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: IntersectionObserverCallback) { intersectionCallback = callback; }
    observe() { /* test controls intersection explicitly */ }
    disconnect() { /* no-op */ }
    unobserve() { /* no-op */ }
  });
  vi.stubGlobal('Image', class {
    naturalWidth = 960;
    naturalHeight = 640;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    set src(_value: string) { queueMicrotask(() => this.onload?.()); }
  });
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('image-first prompt gallery', () => {
  it('opens full bilingual details and copies text without modifying the prompt', async () => {
    await mount();
    await act(async () => (host.querySelector('[aria-label="查看提示词：汽车光影"]') as HTMLButtonElement).click());
    const dialog = document.querySelector('[role="dialog"]')!;
    expect(dialog.textContent).toContain(entry.chinese);
    expect(dialog.textContent).toContain(entry.english);
    const detailImage = dialog.querySelector('img[alt="汽车光影"]');
    expect(detailImage?.getAttribute('loading')).toBe('eager');
    expect(detailImage?.className).toContain('detailImage');
    await act(async () => button('复制英文').click());
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(entry.english);
    await act(async () => (document.querySelector('[aria-label="关闭提示词详情"]') as HTMLButtonElement).click());
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it('opens AI creation with the selected prompt already imported', async () => {
    await mount();
    const useLink = Array.from(host.querySelectorAll('a')).find(link => link.textContent?.trim() === '使用创意');
    expect(useLink?.getAttribute('href')).toBe(`/ai?prompt=${encodeURIComponent(entry.chinese)}&from=prompt-library&reference=${encodeURIComponent(entry.image_url)}`);
  });

  it('lets guests browse but requests login before personal actions', async () => {
    const requestLogin = vi.fn();
    vi.mocked(useOptionalAuthSession).mockReturnValue({
      user: null,
      checking: false,
      loginOpen: false,
      requestLogin,
      logout: vi.fn(),
    });
    await mount();
    const useLink = Array.from(host.querySelectorAll('a')).find(link => link.textContent?.trim() === '使用创意')!;
    await act(async () => useLink.click());
    expect(requestLogin).toHaveBeenCalledWith({
      next: `/ai?prompt=${encodeURIComponent(entry.chinese)}&from=prompt-library&reference=${encodeURIComponent(entry.image_url)}`,
      reason: '登录后将这个提示词和参考图带入 AI 生图',
    });
    expect(promptsApi.getPrompts).toHaveBeenLastCalledWith('', undefined, 1, 30, false, expect.any(Number), undefined);
  });

  it('uses product-facing names and loads each inspiration source', async () => {
    await mount();
    expect(button('全部').getAttribute('aria-pressed')).toBe('true');
    expect(button('外部素材').disabled).toBe(false);
    expect(button('内部素材').disabled).toBe(false);
    expect(button('优质帖子').disabled).toBe(false);
    await act(async () => button('外部素材').click());
    expect(button('外部素材').getAttribute('aria-pressed')).toBe('true');
    expect(promptsApi.getPrompts).toHaveBeenLastCalledWith('', undefined, 1, 30, false, expect.any(Number), 'external');
    await act(async () => button('优质帖子').click());
    expect(button('优质帖子').getAttribute('aria-pressed')).toBe('true');
    expect(promptsApi.getPrompts).toHaveBeenLastCalledWith('', undefined, 1, 30, false, expect.any(Number), 'performance');
  });

  it('presents performance covers as account data instead of editable prompts', async () => {
    const performanceEntry: PromptItem = {
      ...entry,
      id: -18,
      title: '真实高表现帖子',
      chinese: '真实帖子文案',
      source_kind: 'performance',
      source_name: '云凌胜',
      source_license: '阅读 12,000 · 互动 1,230',
      source_url: 'https://www.xiaohongshu.com/explore/note-18',
      can_edit: false,
      can_delete: false,
    };
    vi.mocked(promptsApi.getPrompts).mockResolvedValue(result([performanceEntry]));
    await mount();
    await act(async () => button('优质帖子').click());
    await act(async () => (host.querySelector('[aria-label="查看提示词：真实高表现帖子"]') as HTMLButtonElement).click());

    const dialog = document.querySelector('[role="dialog"]')!;
    expect(dialog.textContent).toContain('帖子文案');
    expect(dialog.textContent).toContain('优质帖子');
    expect(dialog.textContent).toContain('阅读 12,000 · 互动 1,230');
    expect(dialog.textContent).toContain('复制文案');
    expect(dialog.textContent).toContain('用作参考图');
  });

  it('has an explicit retry state and preserves access when a cover fails', async () => {
    vi.mocked(promptsApi.getPrompts).mockRejectedValueOnce(new Error('暂时离线'));
    await mount();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('暂时离线');
    await act(async () => button('重新加载').click());
    await act(async () => host.querySelector('img')!.dispatchEvent(new Event('error')));
    expect(host.textContent).toContain('图片暂不可用');
    await act(async () => (host.querySelector('[aria-label="查看提示词：汽车光影"]') as HTMLButtonElement).click());
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain(entry.chinese);
  });

  it('keeps appending unique items as the user scrolls', async () => {
    const nextEntry = { ...entry, id: 8, title: '第二批灵感', image_url: '/second-cover.png' };
    vi.mocked(promptsApi.getPrompts)
      .mockResolvedValueOnce(result([entry], 60, 1))
      .mockResolvedValueOnce(result([entry, nextEntry], 60, 2));
    await mount();
    const observer = {} as IntersectionObserver;
    await act(async () => intersectionCallback?.([{ isIntersecting: true } as IntersectionObserverEntry], observer));
    const firstSeed = vi.mocked(promptsApi.getPrompts).mock.calls[0][5];
    expect(promptsApi.getPrompts).toHaveBeenLastCalledWith('', undefined, 2, 30, false, firstSeed, undefined);
    expect(host.querySelector('[aria-label="查看提示词：汽车光影"]')).not.toBeNull();
    expect(host.querySelector('[aria-label="查看提示词：第二批灵感"]')).not.toBeNull();
    expect(host.querySelectorAll('article')).toHaveLength(2);
  });

  it('falls back from a failed thumbnail to the original without changing card dimensions', async () => {
    const cover = { ...entry, image_url: '/uploads/test.png', image_width: 1200, image_height: 800 };
    vi.mocked(promptsApi.getPrompts).mockResolvedValue(result([cover]));
    await mount();
    const image = host.querySelector('article img')!;
    const frame = image.closest('button')!;
    const reservedRatio = frame.style.aspectRatio;
    expect(reservedRatio).toBe('1.5');
    expect(image.getAttribute('src')).toContain('/_next/image?');
    await act(async () => image.dispatchEvent(new Event('error')));
    expect(image.getAttribute('src')).toBe(cover.image_url);
    expect(frame.style.aspectRatio).toBe(reservedRatio);
    expect(host.textContent).not.toContain('图片暂不可用');
    await act(async () => image.dispatchEvent(new Event('load')));
    expect(frame.style.aspectRatio).toBe(reservedRatio);
    await act(async () => image.dispatchEvent(new Event('error')));
    expect(host.textContent).toContain('图片暂不可用');
    expect(frame.style.aspectRatio).toBe(reservedRatio);
  });

  it('removes only the chosen card and continues from the server cursor after deletion', async () => {
    const other = { ...entry, id: 8, title: '不要删除', image_url: '/other.png' };
    const next = { ...entry, id: 9, title: '下一张', image_url: '/next.png' };
    vi.mocked(promptsApi.getPrompts)
      .mockResolvedValueOnce(response({ ...result([entry, other], 3).data, has_more: true, next_cursor: 8 }))
      .mockResolvedValueOnce(response({ ...result([next], 2, 2).data, has_more: false, next_cursor: null }));
    await mount();
    const otherCard = host.querySelector('[data-prompt-id="8"]');
    const trigger = host.querySelector('[aria-label="更多操作：汽车光影"]')!;
    await act(async () => trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    const remove = Array.from(document.querySelectorAll('[role="menuitem"]')).find(item => item.textContent === '删除') as HTMLElement;
    expect(remove).toBeTruthy();
    await act(async () => remove.click());
    expect(promptsApi.deletePrompt).toHaveBeenCalledTimes(1);
    expect(promptsApi.deletePrompt).toHaveBeenCalledWith(7);
    expect(host.querySelector('[data-prompt-id="7"]')).toBeNull();
    expect(host.querySelector('[data-prompt-id="8"]')).toBe(otherCard);
    expect(host.querySelectorAll('article')).toHaveLength(1);
    await act(async () => intersectionCallback?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
    expect(promptsApi.getPrompts).toHaveBeenLastCalledWith('', undefined, 2, 30, false, expect.any(Number), undefined, 8);
    expect(host.querySelectorAll('article')).toHaveLength(2);
    expect(host.querySelector('[data-prompt-id="8"]')).toBe(otherCard);
  });

  it('ignores a slow previous-source response after switching tabs', async () => {
    let finishOldPage!: (value: ReturnType<typeof result>) => void;
    const external = { ...entry, id: 20, title: '外部新列表', image_url: '/external.png' };
    vi.mocked(promptsApi.getPrompts)
      .mockResolvedValueOnce(result([entry], 90))
      .mockImplementationOnce(() => new Promise(resolve => { finishOldPage = resolve; }))
      .mockResolvedValueOnce(result([external], 1));
    await mount();
    await act(async () => intersectionCallback?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
    await act(async () => button('外部素材').click());
    await act(async () => finishOldPage(result([{ ...entry, id: 9, image_url: '/old.png' }], 90, 2)));
    expect(host.querySelectorAll('article')).toHaveLength(1);
    expect(host.querySelector('[data-prompt-id="20"]')).not.toBeNull();
    expect(host.querySelector('[data-prompt-id="9"]')).toBeNull();
  });

  it('does not repeat the same visual when later pages contain another database row for it', async () => {
    const repeatedVisual = {
      ...entry,
      id: 8,
      title: '重复图片记录',
      image_url: 'https://cdn.example.com/cover.png?signature=another',
    };
    const nextEntry = {
      ...entry,
      id: 9,
      title: '真正的新灵感',
      image_url: 'https://cdn.example.com/new-cover.png',
    };
    const firstEntry = {
      ...entry,
      image_url: 'https://cdn.example.com/cover.png?signature=first',
    };
    vi.mocked(promptsApi.getPrompts)
      .mockResolvedValueOnce(result([firstEntry], 60, 1))
      .mockResolvedValueOnce(result([repeatedVisual, nextEntry], 60, 2));

    await mount();
    const observer = {} as IntersectionObserver;
    await act(async () => intersectionCallback?.([{ isIntersecting: true } as IntersectionObserverEntry], observer));

    expect(host.querySelector('[aria-label="查看提示词：重复图片记录"]')).toBeNull();
    expect(host.querySelector('[aria-label="查看提示词：真正的新灵感"]')).not.toBeNull();
    expect(host.querySelectorAll('article')).toHaveLength(2);
    expect(host.textContent).toContain('已经浏览完当前标签的全部内容');
  });

  it('ranks semantically related detail recommendations ahead of same-category feed order', async () => {
    const selected = {
      ...entry,
      id: 20,
      title: '极地能量饮料',
      chinese: '冰冻能量饮料罐悬浮在极地冰雪中，罐身覆盖冰霜，纯白影棚背景，商业产品摄影',
      category: '产品与品牌',
      image_url: '/selected.png',
    };
    const unrelated = {
      ...entry,
      id: 21,
      title: '冬季服装海报',
      chinese: '高端球衣悬浮在半空，纯白影棚背景，柔和灯光与商业广告质感',
      category: '产品与品牌',
      image_url: '/unrelated.png',
    };
    const relevant = {
      ...entry,
      id: 22,
      title: '冰块中的罐装饮料',
      chinese: '罐装能量饮料悬浮于蓝色冰块和雪地中，罐身布满冰霜，纯白影棚背景，产品广告',
      category: '产品与品牌',
      image_url: '/relevant.png',
    };
    const crossCategory = {
      ...entry,
      id: 23,
      title: '跨分类近似素材',
      chinese: '冰冻能量饮料罐矗立在极地冰雪中，蓝色冰块覆盖罐身',
      category: '海报设计',
      image_url: '/cross-category.png',
    };
    vi.mocked(promptsApi.getPrompts)
      .mockResolvedValueOnce(result([selected, unrelated, relevant, crossCategory]))
      .mockResolvedValueOnce(result([unrelated, relevant], 2));

    await mount();
    await act(async () => (host.querySelector('[aria-label="查看提示词：极地能量饮料"]') as HTMLButtonElement).click());
    await act(async () => Promise.resolve());

    const recommendations = Array.from(document.querySelectorAll('[aria-label^="查看相关提示词："]'));
    expect(recommendations[0]?.getAttribute('aria-label')).toBe('查看相关提示词：冰块中的罐装饮料');
    expect(recommendations.some(item => item.getAttribute('aria-label') === '查看相关提示词：跨分类近似素材')).toBe(false);
    expect(promptsApi.getPrompts).toHaveBeenLastCalledWith('', '产品与品牌', 1, 600, false, undefined, undefined);
  });

});
