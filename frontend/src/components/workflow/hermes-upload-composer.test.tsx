import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { hermesWorkflowApi, type HermesPost } from '@/services/hermesWorkflowApi';
import HermesUploadComposer from './HermesUploadComposer';

vi.mock('@/services/hermesWorkflowApi', () => ({ hermesWorkflowApi: { uploadPost: vi.fn() } }));
vi.mock('./HermesFrame', () => ({ HermesModal: ({ children, footer }: { children: React.ReactNode; footer: React.ReactNode }) => <div>{children}{footer}</div> }));

let host: HTMLDivElement, root: Root;
const onSaved = vi.fn(), onClose = vi.fn();
const createObjectURL = vi.fn((file: File) => `blob:${file.name}`);
const revokeObjectURL = vi.fn();
const NativeURL = URL;
const draft = { id: 13, status: 'review_pending', source_kind: 'user_upload' } as HermesPost;
beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  class TestURL extends NativeURL {
    static createObjectURL = createObjectURL;
    static revokeObjectURL = revokeObjectURL;
  }
  vi.stubGlobal('URL', TestURL);
  vi.mocked(hermesWorkflowApi.uploadPost).mockResolvedValue({ data: draft } as never);
  onSaved.mockReset().mockResolvedValue(undefined); onClose.mockReset();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function render(maxImages = 5) {
  await act(async () => root.render(<HermesUploadComposer accounts={[{ id: 42, name: '账号甲', owner_name: '小王' }]} maxImages={maxImages} onClose={onClose} onSaved={onSaved} />));
}
async function text(label: string, value: string) {
  const input = host.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(`[aria-label="${label}"]`)!;
  const proto = input instanceof HTMLSelectElement ? HTMLSelectElement.prototype : input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(input, value); input.dispatchEvent(new Event(input instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true })); });
}
async function images(files: File[]) {
  const input = host.querySelector<HTMLInputElement>('[type="file"]')!;
  await act(async () => { Object.defineProperty(input, 'files', { configurable: true, value: files }); input.dispatchEvent(new Event('change', { bubbles: true })); });
}
async function save() { await act(async () => Array.from(host.querySelectorAll('button')).find(button => /保存草稿|核查并重试保存|正在保存/.test(button.textContent || ''))!.click()); }
async function fill() {
  await text('上传图文发布账号', '42'); await text('上传图文标题', '周末看车'); await text('上传图文正文', '完整文案 #看车');
  await images([new File(['one'], 'cover.png', { type: 'image/png' }), new File(['two'], 'second.jpg', { type: 'image/jpeg' })]);
}

describe('user-authored publication drafts', () => {
  it('requires the complete draft without any request', async () => {
    await render(); await save();
    expect(host.textContent).toContain('请选择发布账号，填写标题、正文并上传图片');
    expect(hermesWorkflowApi.uploadPost).not.toHaveBeenCalled();
  });
  it('saves uploaded images in explicit order, without approving or publishing', async () => {
    await render(); await fill();
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="前移第2张"]')!.click());
    await save();
    expect(hermesWorkflowApi.uploadPost).toHaveBeenCalledOnce();
    const [metadata, files] = vi.mocked(hermesWorkflowApi.uploadPost).mock.calls[0];
    expect(metadata).toEqual({ environment_id: 42, title: '周末看车', content: '完整文案 #看车', request_id: expect.any(String) });
    expect(files.map(file => file.name)).toEqual(['second.jpg', 'cover.png']);
    expect(onSaved).toHaveBeenCalledWith(draft);
    expect(host.textContent).toContain('不立即发布');
  });
  it('enforces type and configured image count', async () => {
    await render(1);
    await images([new File(['a'], 'file.svg', { type: 'image/svg+xml' })]);
    expect(host.textContent).toContain('仅支持PNG、JPEG、WebP');
    await images([new File(['a'], 'one.png', { type: 'image/png' }), new File(['b'], 'two.png', { type: 'image/png' })]);
    expect(host.textContent).toContain('一篇最多上传1张图片');
    expect(hermesWorkflowApi.uploadPost).not.toHaveBeenCalled();
  });
  it('enforces the per-image size before making a request', async () => {
    await render();
    await images([new File([new Uint8Array(3_000_001)], 'large.png', { type: 'image/png' })]);
    expect(host.textContent).toContain('每张不超过3MB');
    expect(host.querySelectorAll('img')).toHaveLength(0);
  });
  it('keeps the same request key and frozen form after an uncertain save', async () => {
    vi.mocked(hermesWorkflowApi.uploadPost).mockRejectedValueOnce(new Error('network timeout'));
    await render(); await fill(); await save();
    const first = vi.mocked(hermesWorkflowApi.uploadPost).mock.calls[0][0];
    expect(host.textContent).toContain('保存结果未确认');
    expect(host.querySelector<HTMLInputElement>('[aria-label="上传图文标题"]')!.disabled).toBe(true);
    expect(hermesWorkflowApi.uploadPost).toHaveBeenCalledOnce();
    await save();
    expect(vi.mocked(hermesWorkflowApi.uploadPost).mock.calls[1][0]).toEqual(first);
    expect(onSaved).toHaveBeenCalledOnce();
  });
  it('does not replay a slow upload and releases preview URLs', async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(hermesWorkflowApi.uploadPost).mockImplementation(() => new Promise(resolve => { finish = resolve; }) as never);
    await render(); await fill();
    await save(); await save();
    expect(hermesWorkflowApi.uploadPost).toHaveBeenCalledOnce();
    await act(async () => finish({ data: draft }));
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="移除第1张"]')!.click());
    expect(host.querySelectorAll('img')).toHaveLength(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:cover.png');
  });
});
