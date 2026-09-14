import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { aiApi } from '@/services/aiApi';
import AIPage from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/components/ai/GalleryPicker', () => ({ default: () => null }));
vi.mock('@/services/aiApi', () => ({ aiApi: {
  getActiveTasks: vi.fn().mockResolvedValue({ data: { active_count: 6, max_active: 6, can_submit: false, items: [] } }),
  getRuntimeConfig: vi.fn().mockResolvedValue({ data: { task_timeout_seconds: 900, poll_interval_seconds: 2 } }),
  generateImage: vi.fn(),
} }));
vi.mock('@/lib/toast', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

let host: HTMLDivElement;
let root: Root;
let currentUserId = 0;
const refs = [{ data: '/uploads/ref.png', name: '车型', source: 'gallery' }];

beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  localStorage.clear();
  window.history.replaceState({}, '', '/ai');
  currentUserId += 1;
  localStorage.setItem('app_current_user', JSON.stringify({ id: currentUserId, username: `tester-${currentUserId}` }));
  localStorage.setItem(`ai_image_messages:uid:${currentUserId}`, JSON.stringify([
    { id: 'prompt-1', type: 'prompt', content: '原始描述\n保持换行', timestamp: '12:00', images: [], refImages: refs,
      params: { model: 'GPT Image 2.5', modelId: 'gptimage25', size: '1536×2048', style: '插画', count: 2, quality: 'high', generationMode: 'precision' } },
    { id: 'result-1', type: 'result', content: '生成失败: 测试错误', timestamp: '12:00', images: [] },
  ]));
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

const restore = () => Array.from(host.querySelectorAll('button')).find(button => button.textContent?.includes('载入参数并修改'))!;

describe('restore generation parameters', () => {
  it('restores all controls and references without submitting or checking a new slot', async () => {
    await act(async () => root.render(<AIPage />));
    const calls = vi.mocked(aiApi.getActiveTasks).mock.calls.length;
    await act(async () => {
      restore().click();
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    });
    const input = host.querySelector('textarea')!;
    expect(input.value).toBe('原始描述\n保持换行');
    expect(document.activeElement).toBe(input);
    const composer = host.querySelector('[aria-label="创作控制台"]')!;
    expect(composer.textContent).toContain('GPT Image 2.5');
    expect(composer.textContent).toContain('精细创作');
    expect(composer.textContent).toContain('1536×2048');
    await act(async () => (composer.querySelector('[aria-label="生成参数"]') as HTMLButtonElement).click());
    expect(composer.querySelector('[aria-label="画面比例"] [aria-pressed="true"]')?.textContent).toContain('3:4');
    expect(composer.querySelector('[aria-label="分辨率"] [aria-pressed="true"]')?.textContent).toContain('2K');
    expect(composer.querySelector('[aria-label="图像质量"] [aria-pressed="true"]')?.textContent).toContain('高质量');
    expect(composer.querySelector('[aria-label="画面风格"] [aria-pressed="true"]')?.textContent).toContain('插画');
    expect(composer.querySelector('[aria-label="生成数量"] [aria-pressed="true"]')?.textContent).toBe('2');
    expect(composer.querySelector('img')?.getAttribute('src')).toBe('/uploads/ref.png');
    expect(aiApi.generateImage).not.toHaveBeenCalled();
    expect(aiApi.getActiveTasks).toHaveBeenCalledTimes(calls);
    expect(host.textContent).toContain('生成失败: 测试错误');
  });

  it('asks before replacing an existing draft and leaves it intact when cancelled', async () => {
    await act(async () => root.render(<AIPage />));
    await act(async () => restore().click());
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await act(async () => restore().click());
    expect(confirm).toHaveBeenCalledOnce();
    expect(host.querySelector('textarea')?.value).toBe('原始描述\n保持换行');
    expect(aiApi.generateImage).not.toHaveBeenCalled();
  });

  it('collapses while reviewing history and expands from the compact composer', async () => {
    await act(async () => root.render(<AIPage />));
    const scroller = host.querySelector('[data-testid="creation-results-scroller"]') as HTMLDivElement;
    const composer = host.querySelector('[aria-label="创作控制台"]') as HTMLElement;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 1600 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 480 },
    });

    await act(async () => scroller.dispatchEvent(new Event('scroll', { bubbles: true })));
    expect(composer.dataset.mode).toBe('compact');
    expect(composer.querySelector('[aria-label="选择 AI 模型"]')).toBeNull();
    expect(composer.querySelector('[aria-label="生成参数"]')?.closest('[aria-hidden="true"]')).not.toBeNull();

    await act(async () => (composer.querySelector('[aria-label="画面描述"]') as HTMLTextAreaElement).click());
    expect(composer.dataset.mode).toBe('expanded');

    scroller.scrollTop = 1000;
    await act(async () => scroller.dispatchEvent(new Event('scroll', { bubbles: true })));
    expect(composer.dataset.mode).toBe('expanded');
  });

  it('restores the current user draft and generation preferences after remounting', async () => {
    await act(async () => root.render(<AIPage />));
    await act(async () => {
      restore().click();
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    });

    await act(async () => root.unmount());
    root = createRoot(host);
    await act(async () => root.render(<AIPage />));

    const composer = host.querySelector('[aria-label="创作控制台"]')!;
    expect(host.querySelector('textarea')?.value).toBe('原始描述\n保持换行');
    expect(composer.textContent).toContain('GPT Image 2.5');
    expect(composer.textContent).toContain('精细创作');
    expect(composer.textContent).toContain('3:4');
    expect(composer.textContent).toContain('2K');
    expect(composer.textContent).toContain('2张');

    await act(async () => (composer.querySelector('[aria-label="生成参数"]') as HTMLButtonElement).click());
    expect(composer.querySelector('[aria-label="图像质量"] [aria-pressed="true"]')?.textContent).toContain('高质量');
    expect(composer.querySelector('[aria-label="画面风格"] [aria-pressed="true"]')?.textContent).toContain('插画');
    expect(localStorage.getItem(`ai_image_preferences:uid:${currentUserId}`)).toBeNull();

    await act(async () => root.unmount());
    window.history.replaceState({}, '', '/ai?from=prompt-library&prompt=%E6%96%B0%E5%AF%BC%E5%85%A5%E7%9A%84%E6%8F%90%E7%A4%BA%E8%AF%8D');
    root = createRoot(host);
    await act(async () => root.render(<AIPage />));
    expect(host.querySelector('textarea')?.value).toBe('新导入的提示词');
  });
});
