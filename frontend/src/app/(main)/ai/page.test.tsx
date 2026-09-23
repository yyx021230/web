import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { aiApi } from '@/services/aiApi';
import { promptsApi } from '@/services/promptsApi';
import { toast } from '@/lib/toast';
import AIPage from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/components/ai/GalleryPicker', () => ({ default: () => null }));
vi.mock('@/services/aiApi', () => ({ aiApi: {
  getActiveTasks: vi.fn().mockResolvedValue({ data: { active_count: 6, max_active: 6, can_submit: false, items: [] } }),
  getRuntimeConfig: vi.fn().mockResolvedValue({ data: { task_timeout_seconds: 900, poll_interval_seconds: 2 } }),
  getHistory: vi.fn().mockResolvedValue({ data: { items: [], total: 0, page: 1, limit: 50 } }),
  hideHistoryTask: vi.fn().mockResolvedValue({ data: { hidden: true, task_id: 1 } }),
  clearHistory: vi.fn().mockResolvedValue({ data: { hidden_count: 0 } }),
  generateImage: vi.fn(),
  getTaskStatus: vi.fn(),
  reversePrompt: vi.fn(),
  modifyPrompt: vi.fn(),
  polishPrompt: vi.fn(),
} }));
vi.mock('@/lib/toast', () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }));

let host: HTMLDivElement;
let root: Root;
let currentUserId = 0;
const refs = [{ data: '/uploads/ref.png', name: '车型', source: 'gallery' }];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(aiApi.getActiveTasks).mockResolvedValue({ data: { active_count: 6, max_active: 6, can_submit: false, items: [] } } as never);
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
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });

const restore = () => Array.from(host.querySelectorAll('button')).find(button => button.textContent?.includes('载入参数并修改'))!;
const referencePreviews = () => host.querySelectorAll('[aria-label="创作控制台"] button[aria-label^="放大查看参考图"]');
const openToolbarMenu = async (label: string) => {
  await act(async () => (host.querySelector(`[aria-label="${label}"]`) as HTMLButtonElement).click());
};
const uploadFiles = async (files: File[]) => {
  const input = host.querySelector('input[type="file"]') as HTMLInputElement;
  Object.defineProperty(input, 'files', { configurable: true, value: files });
  await act(async () => {
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await new Promise(resolve => setTimeout(resolve, 30));
  });
  expect(input.value).toBe('');
};

describe('restore generation parameters', () => {
  it('retains images returned with a failed polling response', async () => {
    localStorage.removeItem(`ai_image_messages:uid:${currentUserId}`);
    const imageSrc = vi.spyOn(HTMLImageElement.prototype, 'src', 'set').mockImplementation(function (this: HTMLImageElement, value: string) {
      this.setAttribute('src', value);
      queueMicrotask(() => this.dispatchEvent(new Event('load')));
    });
    vi.mocked(aiApi.getHistory).mockResolvedValueOnce({ data: {
      items: [{ id: 890, model_name: 'gptimage2', prompt: '轮询四张', params: { count: 4 },
        status: 'processing', result_urls: [] }], total: 1,
    } } as never);
    vi.mocked(aiApi.getTaskStatus).mockResolvedValue({ data: {
      task_id: '890', status: 'failed', image_urls: ['/uploads/poll-partial.png'],
      error: '图片数量不足：请求 4 张，实际返回 1 张',
    } } as never);
    try {
      await act(async () => root.render(<AIPage />));
      for (let attempt = 0; attempt < 30 && !host.textContent?.includes('部分完成'); attempt += 1) {
        await act(async () => new Promise(resolve => setTimeout(resolve, 100)));
      }
      expect(aiApi.getTaskStatus).toHaveBeenCalled();
      expect(host.textContent).toContain('部分完成');
      expect(host.querySelector('img[src="/uploads/poll-partial.png"]')).not.toBeNull();
      expect(aiApi.generateImage).not.toHaveBeenCalled();
    } finally {
      imageSrc.mockRestore();
    }
  });

  it('keeps partially generated images visible without claiming full completion', async () => {
    localStorage.removeItem(`ai_image_messages:uid:${currentUserId}`);
    vi.mocked(aiApi.getHistory).mockResolvedValueOnce({ data: {
      items: [{ id: 889, model_name: 'gptimage2', prompt: '四张图片测试', params: { count: 4 },
        status: 'failed', result_urls: ['/uploads/partial.png'],
        error: '图片数量不足：请求 4 张，实际返回 1 张；未自动重新生成' }], total: 1,
    } } as never);
    await act(async () => root.render(<AIPage />));
    for (let attempt = 0; attempt < 20 && !host.textContent?.includes('部分完成'); attempt += 1) {
      await act(async () => new Promise(resolve => setTimeout(resolve, 10)));
    }
    expect(host.textContent).toContain('部分完成');
    expect(host.textContent).toContain('请求 4 张，实际返回 1 张');
    expect(host.querySelector('img[src="/uploads/partial.png"]')).not.toBeNull();
    expect(aiApi.generateImage).not.toHaveBeenCalled();
  });

  it.each(['waiting_provider', 'review_required', 'postprocess_failed'])('shows the server phase %s instead of generic generating text', async (phase) => {
    localStorage.removeItem(`ai_image_messages:uid:${currentUserId}`);
    const progress = {
      phase,
      message: phase === 'waiting_provider' ? '可用入口并发已满，正在等待名额' :
        phase === 'review_required' ? '上游结果待核验，请勿重复提交以免重复计费' : '图片已生成，去水印处理失败，请勿重新生图',
      wait_seconds: 42,
    };
    const status = phase === 'waiting_provider' ? 'processing' : 'failed';
    vi.mocked(aiApi.getHistory).mockResolvedValueOnce({ data: {
      items: [{ id: 888, model_name: 'gptimage2', prompt: '状态回填测试', params: {}, status,
        progress, result_urls: [], error: status === 'failed' ? '上游原始错误' : null }], total: 1,
    } } as never);
    vi.mocked(aiApi.getTaskStatus).mockResolvedValue({ data: { task_id: '888', status, image_urls: [], progress } } as never);
    await act(async () => root.render(<AIPage />));
    for (let attempt = 0; attempt < 20 && !host.textContent?.includes(progress.message); attempt += 1) {
      await act(async () => new Promise(resolve => setTimeout(resolve, 10)));
    }
    expect(host.textContent).toContain(progress.message);
    if (phase === 'waiting_provider') expect(host.textContent).toContain('已等待 42 秒');
    else {
      expect(host.querySelector('.lucide-loader-circle')).toBeNull();
      expect(localStorage.getItem(`ai_image_messages:uid:${currentUserId}`)).toContain(progress.message);
      expect(host.textContent).not.toContain('载入参数并修改');
    }
    expect(aiApi.generateImage).not.toHaveBeenCalled();
  });

  it('restores persisted server history when browser storage has no messages', async () => {
    localStorage.removeItem(`ai_image_messages:uid:${currentUserId}`);
    vi.mocked(aiApi.getHistory).mockResolvedValueOnce({ data: {
      items: [{
        id: 88,
        client_request_id: 'history-request-88',
        model_name: 'gptimage2',
        prompt: '服务端保存的海报',
        params: { width: 768, height: 1024, style: '插画', quality: 'high', count: 1 },
        status: 'completed',
        result_urls: ['/uploads/ai-images/history-88.png'],
        error: null,
        elapsed_seconds: 12,
        created_at: '2026-09-16T06:25:00Z',
        finished_at: '2026-09-16T06:25:12Z',
      }],
      total: 1,
      page: 1,
      limit: 50,
    } } as never);

    await act(async () => root.render(<AIPage />));
    for (let attempt = 0; attempt < 20 && !host.textContent?.includes('服务端保存的海报'); attempt += 1) {
      await act(async () => new Promise(resolve => setTimeout(resolve, 10)));
    }

    expect(host.textContent).toContain('服务端保存的海报');
    expect(host.textContent).toContain('GPT Image 2');
    expect(host.textContent).toContain('768×1024');
    expect(host.querySelector('img[src="/uploads/ai-images/history-88.png"]')).not.toBeNull();
  });

  it('clears settled history on the server as well as in browser storage', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await act(async () => root.render(<AIPage />));
    const clearButton = Array.from(host.querySelectorAll('button'))
      .find(button => button.textContent?.includes('清空记录')) as HTMLButtonElement;

    await act(async () => {
      clearButton.click();
      await Promise.resolve();
    });

    expect(aiApi.clearHistory).toHaveBeenCalledOnce();
    expect(host.textContent).not.toContain('原始描述');
  });

  it('keeps image and plain text paste working alongside local uploads', async () => {
    await act(async () => root.render(<AIPage />));
    expect(host.querySelector('[aria-label="添加素材"]')).not.toBeNull();

    const input = host.querySelector('[aria-label="画面描述"]') as HTMLTextAreaElement;
    const file = new File([new Uint8Array([137, 80, 78, 71])], 'clipboard.png', { type: 'image/png' });
    const pasteEvent = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(pasteEvent, 'clipboardData', {
      value: {
        items: [{ kind: 'file', type: 'image/png', getAsFile: () => file }],
        files: [file],
      },
    });

    await act(async () => input.dispatchEvent(pasteEvent));
    for (let attempt = 0; attempt < 20 && !host.querySelector('img[alt="clipboard.png"]'); attempt += 1) {
      await act(async () => new Promise(resolve => setTimeout(resolve, 10)));
    }

    expect(pasteEvent.defaultPrevented).toBe(true);
    expect(host.querySelector('img[alt="clipboard.png"]')).not.toBeNull();
    expect(host.textContent).toContain('本地');

    const textPasteEvent = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(textPasteEvent, 'clipboardData', {
      value: { items: [{ kind: 'string', type: 'text/plain', getAsFile: () => null }], files: [] },
    });
    await act(async () => input.dispatchEvent(textPasteEvent));
    expect(textPasteEvent.defaultPrevented).toBe(false);
  });

  it('opens the local picker, imports multiple files, previews them and allows reselection', async () => {
    await act(async () => root.render(<AIPage />));
    const fileInput = host.querySelector('input[type="file"]') as HTMLInputElement;
    const open = vi.spyOn(fileInput, 'click');
    await openToolbarMenu('添加素材');
    await act(async () => (host.querySelector('[aria-label="本地上传参考图"]') as HTMLButtonElement).click());
    expect(open).toHaveBeenCalledOnce();
    expect(fileInput.accept).toBe('image/*');
    expect(fileInput.multiple).toBe(true);
    const files = ['local-one.png', 'local-two.png'].map(name => new File(['image'], name, { type: 'image/png' }));
    await uploadFiles(files);
    expect(referencePreviews()).toHaveLength(2);
    expect(host.querySelector('img[alt="local-one.png"]')?.getAttribute('src')).toMatch(/^data:image\/png;base64,/);

    await act(async () => (referencePreviews()[0] as HTMLButtonElement).click());
    expect(host.querySelector('[role="dialog"][aria-label="参考图预览"]')).not.toBeNull();
    await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    await act(async () => (host.querySelector('[aria-label="移除参考图 1"]') as HTMLButtonElement).click());
    await uploadFiles([files[0]]);
    expect(referencePreviews()).toHaveLength(2);
    expect(host.querySelector('img[alt="local-one.png"]')).not.toBeNull();
    expect(aiApi.generateImage).not.toHaveBeenCalled();
  });

  it('loads source-specific prompt materials and brings post text and cover into the draft', async () => {
    const getPrompts = vi.spyOn(promptsApi, 'getPrompts').mockImplementation(async (...args) => {
      const source = args[6] || 'internal';
      return { data: { items: [{
        id: source === 'performance' ? -12 : 12,
        title: source === 'performance' ? '优质帖子样本' : '创意样本',
        chinese: source === 'performance' ? '帖子正文' : '画面描述样本',
        english: '', image_url: '/post-cover.png', category: '汽车', param_type: '海报', source_kind: source,
      }], total: 1, page: 1, limit: 24 } } as never;
    });
    try {
      await act(async () => root.render(<AIPage />));
      await openToolbarMenu('添加素材');
      await act(async () => (host.querySelector('[aria-label="从提示词库选择素材"]') as HTMLButtonElement).click());
      expect(host.querySelector('[role="dialog"][aria-label="从提示词库选择素材"]')).not.toBeNull();
      expect(getPrompts).toHaveBeenCalledWith(undefined, undefined, 1, 24, false, undefined, 'internal');

      const externalTab = Array.from(host.querySelectorAll('[role="tab"]'))
        .find(tab => tab.textContent === '外部素材') as HTMLButtonElement;
      await act(async () => externalTab.click());
      expect(getPrompts).toHaveBeenCalledWith(undefined, undefined, 1, 24, false, undefined, 'external');

      const performanceTab = Array.from(host.querySelectorAll('[role="tab"]'))
        .find(tab => tab.textContent === '优质帖子') as HTMLButtonElement;
      await act(async () => performanceTab.click());
      expect(getPrompts).toHaveBeenCalledWith(undefined, undefined, 1, 24, false, undefined, 'performance');
      expect(host.textContent).toContain('优质帖子样本');

      const useWithImage = Array.from(host.querySelectorAll('[role="dialog"] button'))
        .find(button => button.textContent === '文字 + 参考图') as HTMLButtonElement;
      await act(async () => useWithImage.click());
      expect((host.querySelector('[aria-label="画面描述"]') as HTMLTextAreaElement).value).toBe('帖子正文');
      expect(host.querySelector('img[alt="优质帖子样本"]')).not.toBeNull();
      expect(host.querySelector('[role="dialog"][aria-label="从提示词库选择素材"]')).toBeNull();
      expect(aiApi.generateImage).not.toHaveBeenCalled();
    } finally {
      getPrompts.mockRestore();
    }
  });

  it('shares the ten-image limit with gallery references and rejects invalid or oversized uploads', async () => {
    await act(async () => root.render(<AIPage />));
    await act(async () => restore().click());
    const oversized = new File(['image'], 'large.png', { type: 'image/png' });
    Object.defineProperty(oversized, 'size', { value: 10 * 1024 * 1024 + 1 });
    await uploadFiles([
      new File(['text'], 'not-an-image.txt', { type: 'text/plain' }), oversized,
      ...Array.from({ length: 11 }, (_, index) => new File(['image'], `file-${index}.png`, { type: 'image/png' })),
    ]);
    expect(referencePreviews()).toHaveLength(10);
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('不是图片'));
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('10MB'));
    expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining('9 张'));
    await openToolbarMenu('添加素材');
    expect((host.querySelector('[aria-label="本地上传参考图"]') as HTMLButtonElement).disabled).toBe(true);
    expect((host.querySelector('[aria-label="从我的图库选择图片"]') as HTMLButtonElement).disabled).toBe(true);
    expect(aiApi.generateImage).not.toHaveBeenCalled();
  });

  it('reports local file read errors without adding a broken reference', async () => {
    await act(async () => root.render(<AIPage />));
    vi.stubGlobal('FileReader', class {
      onerror: (() => void) | null = null;
      readAsDataURL() { this.onerror?.(); }
    });
    await uploadFiles([new File(['image'], 'broken.png', { type: 'image/png' })]);
    expect(referencePreviews()).toHaveLength(0);
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('无法读取图片'));
  });

  it('polishes the current draft without starting an image task', async () => {
    vi.mocked(aiApi.polishPrompt).mockResolvedValueOnce({ data: { prompt: '主体与场景\n润色后的内容' } } as never);
    await act(async () => root.render(<AIPage />));
    await act(async () => restore().click());
    await openToolbarMenu('优化提示词');
    const polish = Array.from(host.querySelectorAll('button')).find(button => button.textContent?.includes('智能润色')) as HTMLButtonElement;
    await act(async () => {
      polish.click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });

    expect(aiApi.polishPrompt).toHaveBeenCalledWith('原始描述\n保持换行');
    expect((host.querySelector('[aria-label="画面描述"]') as HTMLTextAreaElement).value).toBe('主体与场景\n润色后的内容');
    expect(aiApi.generateImage).not.toHaveBeenCalled();
  });

  it('modifies the prompt with a separate edit instruction', async () => {
    vi.mocked(aiApi.modifyPrompt).mockResolvedValueOnce({ data: { prompt: '只改了雨夜，其他内容保持不变' } } as never);
    await act(async () => root.render(<AIPage />));
    await act(async () => restore().click());
    await openToolbarMenu('优化提示词');
    const modify = Array.from(host.querySelectorAll('button')).find(button => button.textContent?.includes('AI 帮改')) as HTMLButtonElement;
    await act(async () => modify.click());
    const instruction = host.querySelector('[aria-label="提示词修改要求"]') as HTMLTextAreaElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
      setter?.call(instruction, '把背景改为雨夜');
      instruction.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const apply = Array.from(host.querySelectorAll('button')).find(button => button.textContent?.includes('应用修改')) as HTMLButtonElement;
    await act(async () => {
      apply.click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });

    expect(aiApi.modifyPrompt).toHaveBeenCalledWith('原始描述\n保持换行', '把背景改为雨夜');
    expect((host.querySelector('[aria-label="画面描述"]') as HTMLTextAreaElement).value).toBe('只改了雨夜，其他内容保持不变');
    expect(host.querySelector('[aria-label="提示词修改要求"]')).toBeNull();
  });

  it('reverses a selected image into prompt text without adding a reference image', async () => {
    vi.mocked(aiApi.reversePrompt).mockResolvedValueOnce({ data: { prompt: 'A faithful image prompt' } } as never);
    await act(async () => root.render(<AIPage />));
    const reverseInput = host.querySelector('[aria-label="选择需要反推提示词的图片"]') as HTMLInputElement;
    const file = new File(['image'], 'reverse.webp', { type: 'image/webp' });
    Object.defineProperty(reverseInput, 'files', { configurable: true, value: [file] });
    await act(async () => {
      reverseInput.dispatchEvent(new Event('change', { bubbles: true }));
      await new Promise(resolve => setTimeout(resolve, 30));
    });

    expect(aiApi.reversePrompt).toHaveBeenCalledWith(expect.stringMatching(/^data:image\/webp;base64,/));
    expect((host.querySelector('[aria-label="画面描述"]') as HTMLTextAreaElement).value).toBe('A faithful image prompt');
    expect(referencePreviews()).toHaveLength(0);
    expect(aiApi.generateImage).not.toHaveBeenCalled();
  });

  it.each([false, true])('submits local image data through the existing generation API, mixed gallery=%s', async (withGallery) => {
    vi.mocked(aiApi.getActiveTasks).mockResolvedValue({ data: { active_count: 0, max_active: 6, can_submit: true, items: [] } } as never);
    vi.mocked(aiApi.generateImage).mockResolvedValueOnce({ data: { task_id: 'test-only', status: 'failed', error: '模拟结束，不调用生图服务' } } as never);
    await act(async () => root.render(<AIPage />));
    await act(async () => restore().click());
    if (!withGallery) await act(async () => (host.querySelector('[aria-label="移除参考图 1"]') as HTMLButtonElement).click());
    await uploadFiles([new File(['image'], 'upload.png', { type: 'image/png' })]);
    const composer = host.querySelector('[aria-label="创作控制台"]')!;
    const data = composer.querySelector('img[alt="upload.png"]')?.getAttribute('src');
    await act(async () => (composer.querySelector('button[aria-label="开始生成"]') as HTMLButtonElement).click());

    expect(aiApi.generateImage).toHaveBeenCalledOnce();
    expect(aiApi.generateImage).toHaveBeenCalledWith(expect.objectContaining({
      prompt: '原始描述\n保持换行', model: 'gptimage25', generation_mode: 'precision',
      ...(withGallery ? { images_data: ['/uploads/ref.png', data] } : { image_data: data }),
    }));
  });

  it('expands and collapses the prompt with a button without losing the draft', async () => {
    await act(async () => root.render(<AIPage />));
    await act(async () => restore().click());
    const toggle = host.querySelector('[aria-label="展开输入框"]') as HTMLButtonElement;
    const composer = host.querySelector('[aria-label="创作控制台"]') as HTMLElement;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(composer.closest('[style]')?.getAttribute('style')).toContain('--prompt-height: 112px');
    await act(async () => toggle.click());
    expect(host.querySelector('[aria-label="收起输入框"]')?.getAttribute('aria-expanded')).toBe('true');
    expect(composer.closest('[style]')?.getAttribute('style')).toContain('--prompt-height: 360px');
    await act(async () => (host.querySelector('[aria-label="收起输入框"]') as HTMLButtonElement).click());
    expect(host.querySelector('[aria-label="展开输入框"]')?.getAttribute('aria-expanded')).toBe('false');
    const scroller = host.querySelector('[data-testid="creation-results-scroller"]') as HTMLDivElement;
    Object.defineProperties(scroller, {
      scrollHeight: { configurable: true, value: 1600 },
      clientHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, writable: true, value: 480 },
    });
    await act(async () => scroller.dispatchEvent(new Event('scroll', { bubbles: true })));
    expect(composer.dataset.mode).toBe('expanded');
    expect(host.querySelector('textarea')?.value).toBe('原始描述\n保持换行');
    expect(referencePreviews()).toHaveLength(1);
    expect(aiApi.generateImage).not.toHaveBeenCalled();

    scroller.scrollTop = 300;
    await act(async () => scroller.dispatchEvent(new Event('scroll', { bubbles: true })));
    expect(composer.dataset.mode).toBe('compact');
    expect(host.querySelector('[aria-label="展开输入框"]')).toBeNull();
    await act(async () => (host.querySelector('[aria-label="画面描述"]') as HTMLTextAreaElement).click());
    expect(host.querySelector('[aria-label="展开输入框"]')).not.toBeNull();
  });

  it('reclamps the expanded prompt when the window shrinks', async () => {
    await act(async () => root.render(<AIPage />));
    await act(async () => (host.querySelector('[aria-label="展开输入框"]') as HTMLButtonElement).click());
    vi.stubGlobal('innerHeight', 400);
    await act(async () => window.dispatchEvent(new Event('resize')));
    const composer = host.querySelector('[aria-label="创作控制台"]') as HTMLElement;
    expect(composer.closest('[style]')?.getAttribute('style')).toContain('--prompt-height: 166px');
    await act(async () => (host.querySelector('[aria-label="收起输入框"]') as HTMLButtonElement).click());
    expect(composer.closest('[style]')?.getAttribute('style')).toContain('--prompt-height: 112px');
  });

  it('renders short text-only prompts compactly without dropping parameter details', async () => {
    localStorage.setItem(`ai_image_messages:uid:${currentUserId}`, JSON.stringify([
      {
        id: 'short-prompt',
        type: 'prompt',
        content: '美景图\n\n\n',
        timestamp: '14:25',
        images: [],
        refImages: [],
        params: {
          model: 'GPT Image 2',
          modelId: 'gptimage2',
          size: '1024×1024',
          style: '写实',
          count: 1,
          quality: 'low',
          generationMode: 'fast',
        },
      },
      { id: 'short-result', type: 'result', content: '', timestamp: '14:25', images: [] },
    ]));

    await act(async () => root.render(<AIPage />));

    const compactPrompt = host.querySelector('[data-compact="true"]') as HTMLElement;
    const parameters = compactPrompt?.querySelector('[data-testid="prompt-parameters"]');
    expect(compactPrompt).not.toBeNull();
    expect(compactPrompt.textContent).toContain('美景图');
    expect(compactPrompt.querySelector('p')?.textContent).toBe('美景图');
    expect(parameters?.getAttribute('title')).toContain('尺寸：1024×1024');
    expect(parameters?.getAttribute('title')).toContain('风格：写实');
    expect(parameters?.getAttribute('title')).toContain('质量：低质量');
    expect(parameters?.getAttribute('title')).toContain('模式：快速出图');
  });

  it('keeps prompts with references in the full record layout', async () => {
    await act(async () => root.render(<AIPage />));
    expect(host.querySelector('[data-compact="true"]')).toBeNull();
    expect(host.querySelector('img[alt="车型"]')).not.toBeNull();
  });

  it('restores all controls and references without submitting or checking a new slot', async () => {
    // Periodic queue refresh is independent of restoring a draft.
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'requestAnimationFrame', 'cancelAnimationFrame'] });
    await act(async () => root.render(<AIPage />));
    const calls = vi.mocked(aiApi.getActiveTasks).mock.calls.length;
    await act(async () => {
      restore().click();
      await vi.advanceTimersByTimeAsync(20);
    });
    const input = host.querySelector('textarea')!;
    expect(input.value).toBe('原始描述\n保持换行');
    expect(document.activeElement).toBe(input);
    const composer = host.querySelector('[aria-label="创作控制台"]')!;
    expect(composer.textContent).toContain('GPT Image 2.5');
    expect(composer.textContent).toContain('精细');
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
    expect(composer.textContent).toContain('精细');
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

  it('imports the selected inspiration image and opens it in a full preview', async () => {
    window.history.replaceState({}, '', '/ai?from=prompt-library&prompt=%E6%B5%B7%E6%8A%A5%E5%88%9B%E6%84%8F&reference=%2Fcover.png');
    await act(async () => root.render(<AIPage />));

    const previewButton = host.querySelector('[aria-label="放大查看参考图 1：提示词宝库参考图"]') as HTMLButtonElement;
    expect(host.querySelector('textarea')?.value).toBe('海报创意');
    expect(host.querySelector('img[src="/cover.png"]')).not.toBeNull();
    expect(previewButton).not.toBeNull();

    await act(async () => previewButton.click());
    const dialog = document.querySelector('[role="dialog"][aria-label="参考图预览"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.querySelector('img[src="/cover.png"]')).not.toBeNull();

    await act(async () => (dialog?.querySelector('[aria-label="关闭参考图预览"]') as HTMLButtonElement).click());
    expect(document.querySelector('[role="dialog"][aria-label="参考图预览"]')).toBeNull();
  });
});
