import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { HermesPost, HermesReferenceType, HermesRun } from '@/services/hermesWorkflowApi';

vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/services/hermesWorkflowApi', () => ({ hermesWorkflowApi: {
  bootstrap: vi.fn(), referenceTypes: vi.fn(), listRuns: vi.fn(), getRun: vi.fn(),
  createBatchRun: vi.fn(), createRun: vi.fn(), reviewPost: vi.fn(), adminReviewPost: vi.fn(), editPost: vi.fn(),
} }));
vi.mock('./HermesFrame', () => ({
  HermesFrame: ({ children }: { children: React.ReactNode }) => React.createElement('main', null, children),
  HermesModal: ({ title, children, footer }: { title: string; children: React.ReactNode; footer?: React.ReactNode }) => React.createElement('section', { role: 'dialog', 'aria-label': title }, children, footer),
  hermesDate: (value: string) => value || '—',
}));

import HermesCreator from './HermesCreator';
import HermesCreationHistory, { HermesRunGroup } from './HermesCreationHistory';
import HermesPostInspector from './HermesPostInspector';
import HermesTypePicker from './HermesTypePicker';
import HermesTypePreview, { PREVIEW_TYPES } from './HermesTypePreview';
import { hermesWorkflowApi } from '@/services/hermesWorkflowApi';

let host: HTMLDivElement;
let root: Root;
const copy = '完整正文🚗\n\n' + '保留原文的段落结构和表达。'.repeat(30) + '\n#零跑A05[话题]#';
const post: HermesPost = { id: 12, run_id: 8, slot: 1, environment_id: 42, account_name: '账号甲', vehicle_model: '零跑A05', title: '完整标题🚗', content: copy, image_url: '/test-image.png', status: 'review_pending', hard_pass: true, publish_status: 'not_ready', version: 'v1', source_detail: { mother_copy_id: 537, selected_prompt_id: 324 } };
const run: HermesRun = { id: 8, run_key: 'test', source: 'manual', status: 'review_pending', parameters: {}, total_posts: 1, generated_posts: 1, approved_posts: 0, rejected_posts: 0, created_at: '2026-09-07T10:00:00+08:00', posts: [post] };
const reference = (id: string, name: string): HermesReferenceType => ({ id, name, description: '真实类型介绍', structure: '保留母版结构', accent: 'sage', reference_count: 3, preview_count: 1, examples: [{ id: 1, kind: 'copy', title: '原文标题', content: '原文正文与话题' }] });

beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('IntersectionObserver', class {
    constructor(private callback: IntersectionObserverCallback) {}
    observe() { this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver); }
    disconnect() {}
  });
  window.history.replaceState({}, '', '/workflows/hermes');
  vi.mocked(hermesWorkflowApi.bootstrap).mockResolvedValue({ data: { accounts: [{ id: 42, name: '账号甲' }, { id: 27, name: '账号乙' }], vehicle_models: ['零跑A05', '零跑B10'], policies: [], limits: { max_posts_per_run: 40 } } } as never);
  vi.mocked(hermesWorkflowApi.referenceTypes).mockResolvedValue({ data: { copy_types: [reference('drive_review', '试驾测评')], image_types: [reference('note_poster', '手账便签风'), reference('quote_table', '配置报价')], source_note: '真实案例' } } as never);
  vi.mocked(hermesWorkflowApi.listRuns).mockResolvedValue({ data: { items: [], total: 0 } } as never);
  vi.mocked(hermesWorkflowApi.getRun).mockResolvedValue({ data: run } as never);
  vi.mocked(hermesWorkflowApi.createBatchRun).mockResolvedValue({ data: run } as never);
  vi.mocked(hermesWorkflowApi.createRun).mockResolvedValue({ data: run } as never);
  vi.mocked(hermesWorkflowApi.reviewPost).mockResolvedValue({ data: { ...run, regenerated_run_id: 9 } } as never);
  vi.mocked(hermesWorkflowApi.adminReviewPost).mockResolvedValue({ data: { ...run, regenerated_run_id: 9 } } as never);
  vi.mocked(hermesWorkflowApi.editPost).mockResolvedValue({ data: { ...post, revision: 2 } } as never);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.useRealTimers(); });
async function render(element: React.ReactNode) { await act(async () => root.render(element)); }
async function click(element: Element | null) { expect(element).not.toBeNull(); await act(async () => (element as HTMLElement).click()); }
function button(text: string) { return Array.from(host.querySelectorAll('button')).find(b => b.textContent === text) || null; }
async function select(label: string, value: string) { const input = host.querySelector(`select[aria-label="${label}"]`) as HTMLSelectElement; expect(input).not.toBeNull(); await act(async () => { input.value = value; input.dispatchEvent(new Event('change', { bubbles: true })); }); }
async function fill(label: string, value: string) {
  const input = host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement | HTMLTextAreaElement;
  expect(input).not.toBeNull();
  await act(async () => {
    const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('Hermes creation frontend interactions', () => {
  it('uses separate server-side scopes and record headings for both creators', async () => {
    await render(React.createElement(HermesCreator));
    expect(host.querySelector('[aria-label="批量创作记录"]')).not.toBeNull();
    expect(hermesWorkflowApi.listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ workflow_mode: 'batch', page: 1 }));
    await render(React.createElement(HermesCreator, { single: true }));
    expect(host.querySelector('[aria-label="单篇创作记录"]')).not.toBeNull();
    expect(host.querySelector('[aria-label="批量创作记录"]')).toBeNull();
    expect(hermesWorkflowApi.listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ workflow_mode: 'single', page: 1 }));
    await select('审核状态筛选', 'review_pending');
    expect(hermesWorkflowApi.listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ workflow_mode: 'single', status: 'review_pending' }));
  });

  it('preserves module scope across pagination, search, filtering and refresh', async () => {
    vi.useFakeTimers();
    vi.mocked(hermesWorkflowApi.listRuns).mockResolvedValue({ data: { items: [], total: 17 } } as never);
    await render(React.createElement(HermesCreationHistory, { mode: 'single' }));
    host.querySelector<HTMLElement>('#history')!.scrollIntoView = vi.fn();
    await act(async () => { await vi.advanceTimersByTimeAsync(350); });
    await click(button('下一页'));
    expect(hermesWorkflowApi.listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ workflow_mode: 'single', page: 2 }));
    await click(host.querySelector('[aria-label="刷新创作记录"]'));
    expect(hermesWorkflowApi.listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ workflow_mode: 'single', page: 2 }));
    await fill('搜索任务、账号、车型或标题', '通勤');
    await act(async () => { await vi.advanceTimersByTimeAsync(350); });
    expect(hermesWorkflowApi.listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ workflow_mode: 'single', page: 1, search: '通勤' }));
    await select('审核状态筛选', 'approved');
    expect(hermesWorkflowApi.listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ workflow_mode: 'single', status: 'approved', page: 1 }));
    await click(button('清除筛选'));
    expect(hermesWorkflowApi.listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ workflow_mode: 'single', status: undefined, search: undefined, page: 1 }));
  });

  it('ignores a slow batch response after switching to single creation', async () => {
    let resolveBatch!: (value: unknown) => void;
    vi.mocked(hermesWorkflowApi.listRuns).mockImplementation(query => {
      if (typeof query === 'object' && query.workflow_mode === 'batch') return new Promise(resolve => { resolveBatch = resolve; }) as never;
      return Promise.resolve({ data: { items: [{ ...run, workflow_mode: 'single' }], total: 1 } }) as never;
    });
    await render(React.createElement(HermesCreator));
    await render(React.createElement(HermesCreator, { single: true }));
    await act(async () => resolveBatch({ data: { items: [{ ...run, id: 99, source: 'manual_batch', workflow_mode: 'batch' }], total: 12 } }));
    expect(host.querySelector('#run-99')).toBeNull();
    expect(host.querySelector('#run-8')).not.toBeNull();
    expect(host.querySelector('[aria-label="单篇创作记录"]')).not.toBeNull();
  });

  it('does not inject a linked batch task into single history', async () => {
    window.history.replaceState({}, '', '/workflows/hermes/single?run=8');
    vi.mocked(hermesWorkflowApi.getRun).mockResolvedValue({ data: { ...run, source: 'manual_batch', workflow_mode: 'batch' } } as never);
    await render(React.createElement(HermesCreationHistory, { mode: 'single' }));
    expect(host.querySelector('#run-8')).toBeNull();
    expect(host.querySelector('a[href="/workflows/hermes?run=8"]')?.textContent).toContain('前往查看');
  });

  it('renders single history as compact task cards while keeping full text available', async () => {
    vi.mocked(hermesWorkflowApi.listRuns).mockResolvedValue({ data: { items: [{ ...run, workflow_mode: 'single' }], total: 1 } } as never);
    await render(React.createElement(HermesCreationHistory, { mode: 'single' }));
    expect(host.querySelector('[data-mode="single"] [data-compact="true"] article')).not.toBeNull();
    expect(host.querySelector('[aria-label="展开全文与话题"]')).toBeNull();
    await click(host.querySelector('[aria-label="查看第1篇完整图文"]'));
    expect(host.querySelector('[role="dialog"]')?.textContent).toContain(copy);
    await click(host.querySelector('[aria-label="刷新创作记录"]'));
    expect(hermesWorkflowApi.listRuns).toHaveBeenLastCalledWith(expect.objectContaining({ workflow_mode: 'single' }));
  });

  it('polls an active task and exposes a completed card while another stays generating', async () => {
    vi.useFakeTimers();
    const pending = { ...post, title: null, content: null, image_url: null, status: 'generating', hard_pass: false };
    const sibling = { ...pending, id: 13, slot: 2 };
    const active = { ...run, status: 'running', total_posts: 2, generated_posts: 0, posts: [pending, sibling] };
    vi.mocked(hermesWorkflowApi.getRun).mockResolvedValue({ data: active } as never);
    await render(React.createElement(HermesRunGroup, { run: active as HermesRun, onRefresh: vi.fn() }));
    expect(host.querySelectorAll('img')).toHaveLength(0);
    vi.mocked(hermesWorkflowApi.getRun).mockResolvedValue({ data: { ...active, generated_posts: 1, posts: [post, sibling] } } as never);
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    const cards = host.querySelectorAll('article');
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain('待审核');
    expect(cards[0].textContent).toContain('完整标题🚗');
    expect(cards[0].querySelector('img')?.getAttribute('src')).toBe(post.image_url);
    expect(cards[1].textContent).toContain('生产中');
    expect(cards[1].querySelector('img')).toBeNull();
    expect(host.textContent).toContain('已生成 1/2');
    expect(host.textContent).toContain('剩余 1 篇');
    expect(button('编辑')).not.toBeNull();
    await click(button('通过'));
    expect(hermesWorkflowApi.reviewPost).toHaveBeenCalledWith(post.id, 'approve', undefined, post.version);
  });

  it('keeps per-account counts and multi-model choices in the batch payload', async () => {
    await render(React.createElement(HermesCreator));
    await click(host.querySelector('[aria-label="选择账号甲"]'));
    await click(host.querySelector('[aria-label="选择账号乙"]'));
    await select('账号甲篇数', '3');
    await click(Array.from(host.querySelectorAll('label')).find(l => l.textContent === '零跑A05车型库')?.querySelector('input') || null);
    expect(button('下发 8 篇任务')?.disabled).toBe(false);
    expect(host.textContent).toContain('近 15 篇去重参考');
    await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    expect(hermesWorkflowApi.createBatchRun).toHaveBeenCalledWith({ accounts: [{ environment_id: 27, post_count: 5 }, { environment_id: 42, post_count: 3 }], vehicle_models: ['零跑A05'], instruction: undefined });
    expect(host.querySelector('[aria-label="展开创作参数"]')).not.toBeNull();
  });

  it('requires independent copy and image types, preserving both IDs on submit', async () => {
    await render(React.createElement(HermesCreator, { single: true }));
    await select('创作账号', '42'); await select('生产车型', '零跑A05');
    expect(button('下发 1 篇任务')?.disabled).toBe(true);
    await click(host.querySelector('[aria-label="选择文案类型与实例"]')); await click(button('使用试驾测评'));
    expect(button('下发 1 篇任务')?.disabled).toBe(true);
    await click(host.querySelector('[aria-label="选择图片类型与实例"]')); await click(button('使用手账便签风'));
    expect(button('下发 1 篇任务')?.disabled).toBe(false);
    await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    expect(hermesWorkflowApi.createRun).toHaveBeenCalledWith({ account_id: 42, vehicle_model: '零跑A05', post_count: 1, copy_type: 'drive_review', image_type: 'note_poster', instruction: undefined });
  });

  it('copies the complete text without expanding the card or opening the inspector', async () => {
    await render(React.createElement(HermesRunGroup, { run, onRefresh: vi.fn() }));
    expect(host.querySelector('[data-single="true"] article')).not.toBeNull();
    expect(host.querySelector('[aria-label="展开全文与话题"]')).toBeNull();
    expect(host.querySelector('#post-copy-12')?.textContent).toBe(copy);
    await click(host.querySelector('[aria-label="复制第1篇完整文案"]'));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(`完整标题🚗\n\n${copy}`);
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    expect(hermesWorkflowApi.reviewPost).not.toHaveBeenCalled();
  });

  it('has one accessible whole-card opener, separate from editing and review actions', async () => {
    await render(React.createElement(HermesRunGroup, { run, onRefresh: vi.fn() }));
    const card = host.querySelector('[data-post-id="12"]')!;
    expect(card.querySelectorAll('[aria-label="查看第1篇完整图文"]')).toHaveLength(1);
    expect(card.querySelector('button button')).toBeNull();
    await click(button('对照'));
    expect(host.querySelector('[role="dialog"] [role="tab"][aria-selected="true"]')?.textContent).toBe('文案对照');
    expect(host.querySelectorAll('[role="dialog"]')).toHaveLength(1);
  });

  it('preserves full failure and review reasons in the inspector', async () => {
    const failure = '详细失败原因'.repeat(80);
    vi.mocked(hermesWorkflowApi.getRun).mockResolvedValue({ data: { ...run, error: failure, posts: [{ ...post, review_comment: '请调整第二段' }] } } as never);
    await render(React.createElement(HermesRunGroup, { run, compact: true, onRefresh: vi.fn() }));
    await click(host.querySelector('[aria-label="查看第1篇完整图文"]'));
    expect(host.querySelector('[role="dialog"]')?.textContent).toContain(failure);
    expect(host.querySelector('[role="dialog"]')?.textContent).toContain('请调整第二段');
  });

  it('provides distinct schematic previews for all 7 copy and 9 image directions', async () => {
    const signatures = new Set<string>();
    for (const id of PREVIEW_TYPES) {
      await render(React.createElement(HermesTypePreview, { id }));
      const preview = host.querySelector(`[data-type-preview="${id}"]`)!;
      expect(preview.getAttribute('aria-hidden')).toBe('true');
      signatures.add(preview.querySelector('svg')!.innerHTML);
    }
    expect(signatures.size).toBe(16);
  });

  it('shows honest empty-case previews and keeps quote-table requirements intact', async () => {
    const onSelect = vi.fn();
    const catalog = { version: 'test', source: 'test', library_counts: { copy: 0, image: 3 }, copy_types: [], image_types: [reference('quote_table', '多配置报价单'), { ...reference('note_poster', '手账便签风'), examples: [], reference_count: 0 }], source_note: '当前 Web 素材副本' };
    await render(React.createElement(HermesTypePicker, { kind: 'image', catalog, value: 'quote_table', quoteAllowed: false, onSelect, onClose: vi.fn() }));
    expect(button('使用多配置报价单')?.disabled).toBe(true);
    expect(host.textContent).toContain('结构示意 · 非母版');
    await click(host.querySelector('[aria-label="手账便签风"]'));
    expect(host.textContent).toContain('当前库内暂无此类型母版');
    expect(host.querySelectorAll('[data-type-preview="note_poster"]')).toHaveLength(2);
    await click(button('使用手账便签风'));
    expect(button('使用手账便签风')?.disabled).toBe(true);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('keeps card quote prices gated and shows actual classification evidence', async () => {
    const onSelect = vi.fn();
    const card = { ...reference('quote_cards', '卡片报价单'), requires_quote_data: true, examples: [{ id: 335, kind: 'image' as const, title: '真实报价卡', content: '原始提示词', classification_reason: '四个配置分别放入报价卡，不是便签拼贴', style_tags: ['棚拍 / 渐变'] }] };
    const catalog = { version: 'reference-types-v3-layout', source: 'test', library_counts: { copy: 0, image: 1 }, copy_types: [], image_types: [card], source_note: '共用分类规则' };
    await render(React.createElement(HermesTypePicker, { kind: 'image', catalog, value: 'quote_cards', quoteAllowed: false, onSelect, onClose: vi.fn() }));
    expect(button('使用卡片报价单')?.disabled).toBe(true);
    expect(host.textContent).toContain('归类依据');
    expect(host.textContent).toContain('四个配置分别放入报价卡');
    expect(host.textContent).toContain('3 条归类参考');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('rechecks quote-card policy eligibility when the selected vehicle changes', async () => {
    vi.mocked(hermesWorkflowApi.bootstrap).mockResolvedValue({ data: { accounts: [{ id: 42, name: '账号甲' }], vehicle_models: ['零跑A05', '零跑B10'], policies: [{ vehicle_model: '零跑A05', allow_multi_config_quote: true, quote_rows: [{}] }] } } as never);
    vi.mocked(hermesWorkflowApi.referenceTypes).mockResolvedValue({ data: { copy_types: [reference('drive_review', '试驾测评')], image_types: [{ ...reference('quote_cards', '卡片报价单'), requires_quote_data: true }], source_note: '真实案例' } } as never);
    await render(React.createElement(HermesCreator, { single: true }));
    await select('创作账号', '42');
    await select('生产车型', '零跑A05');
    await click(host.querySelector('[aria-label="选择文案类型与实例"]'));
    await click(button('使用试驾测评'));
    await click(host.querySelector('[aria-label="选择图片类型与实例"]'));
    await click(button('使用卡片报价单'));
    expect(button('下发 1 篇任务')?.disabled).toBe(false);
    await select('生产车型', '零跑B10');
    expect(button('下发 1 篇任务')?.disabled).toBe(true);
    expect(host.textContent).toContain('当前车型未提供完整的分配置报价');
    expect(hermesWorkflowApi.createRun).not.toHaveBeenCalled();
  });

  it('shows image-load fallback without removing the copy', async () => {
    await render(React.createElement(HermesRunGroup, { run, onRefresh: vi.fn() }));
    await act(async () => host.querySelector('img')!.dispatchEvent(new Event('error')));
    expect(host.textContent).toContain('图片暂时无法加载');
    expect(host.querySelector('#post-copy-12')?.textContent).toBe(copy);
  });

  it('does not describe a failed post as still generating', async () => {
    vi.mocked(hermesWorkflowApi.getRun).mockResolvedValue({ data: { ...run, posts: [{ ...post, status: 'generation_failed', title: null, content: null, image_url: null }] } } as never);
    await render(React.createElement(HermesRunGroup, { run, onRefresh: vi.fn() }));
    expect(host.querySelector('h4')?.textContent).toBe('本篇生成失败');
    expect(host.textContent).not.toContain('等待创作完成');
  });

  it('does not invent account-history evidence for an older post', async () => {
    await render(React.createElement(HermesPostInspector, { post, onClose: vi.fn(), onSaved: vi.fn() }));
    await click(button('文案对照'));
    expect(host.textContent).toContain('该历史任务未保存账号参考快照');
  });

  it('shows actual history counts and non-blocking similarity warnings', async () => {
    const current = { ...post, source_detail: { account_history: { history_posts: 12, history_missing_body: 3 }, account_repetition: { status: 'high_similarity', closest_title: '近期旧帖', compared_bodies: 7 } } };
    await render(React.createElement(HermesPostInspector, { post: current, onClose: vi.fn(), onSaved: vi.fn() }));
    await click(button('文案对照'));
    expect(host.textContent).toContain('本次参考 12 条已同步帖子');
    expect(host.textContent).toContain('3 条缺正文');
    expect(host.textContent).toContain('近期旧帖');
    expect(host.textContent).toContain('未自动拦截');
    expect(host.textContent).toContain('生成后实际比对 7 篇有效正文');
    expect(host.textContent).toContain('不代表已核对小红书实时最新内容');
  });

  it('opens the editor directly from the card and saves complete text with a reason and version', async () => {
    await render(React.createElement(HermesRunGroup, { run, onRefresh: vi.fn() }));
    await click(button('编辑'));
    expect(host.querySelector('[aria-label="编辑正文"]')).not.toBeNull();
    expect(button('保存新版本 · 重新待审')?.disabled).toBe(true);
    const revised = '只替换车型描述🚗\n其余结构保留\n#零跑A05[话题]#';
    await fill('编辑正文', revised);
    expect(button('保存新版本 · 重新待审')?.disabled).toBe(true);
    await fill('修改说明', '更正车型描述');
    await click(button('保存新版本 · 重新待审'));
    expect(hermesWorkflowApi.editPost).toHaveBeenCalledWith(12, { title: post.title, content: revised, comment: '更正车型描述', expected_version: 'v1' });
    expect(hermesWorkflowApi.reviewPost).not.toHaveBeenCalled();
  });

  it('rejects only by default, requires a reason, and never generates implicitly', async () => {
    await render(React.createElement(HermesRunGroup, { run, onRefresh: vi.fn() }));
    await click(button('不通过'));
    expect(host.querySelector<HTMLInputElement>('input[type="radio"]')?.checked).toBe(true);
    expect(button('确认不通过')?.disabled).toBe(true);
    await fill('不通过原因', '  图片条件缺失  ');
    await click(button('确认不通过'));
    expect(hermesWorkflowApi.reviewPost).toHaveBeenCalledWith(12, 'reject', '图片条件缺失', 'v1', false);
  });

  it('regenerates one post only after explicit selection and uses the admin endpoint when needed', async () => {
    const onSaved = vi.fn(), onClose = vi.fn();
    await render(React.createElement(HermesPostInspector, { post, admin: true, initialTab: 'review', onSaved, onClose }));
    await fill('不通过原因', '修正图中车型配置');
    await click(host.querySelectorAll('input[type="radio"]')[1]);
    expect(host.textContent).toContain('不会重跑同批其他帖子');
    await click(button('不通过并重新生成'));
    expect(hermesWorkflowApi.adminReviewPost).toHaveBeenCalledWith(12, 'reject', '修正图中车型配置', 'v1', true);
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('shows the editor, time, before/after text and exact changed segments in history', async () => {
    const edited = { ...post, revision: 2, source_detail: { events: [{ action: 'edit', user_id: 3, user_name: '运营甲', at: '2026-09-07T12:00:00', revision: 1, result_revision: 2, comment: '修改日期表述', changes: { content: { before: '截至9月30日💌', after: '截至9月底💌', segments: [{ kind: 'equal', text: '截至9月' }, { kind: 'removed', text: '30日' }, { kind: 'added', text: '底' }, { kind: 'equal', text: '💌' }] } } }] } };
    await render(React.createElement(HermesPostInspector, { post: edited, initialTab: 'history', onClose: vi.fn(), onSaved: vi.fn() }));
    expect(host.textContent).toContain('运营甲');
    expect(host.textContent).toContain('2026-09-07T12:00:00');
    expect(host.textContent).toContain('V1 → V2');
    const versions = Array.from(host.querySelectorAll('details article')).map(node => node.textContent);
    expect(versions).toEqual(['修改前截至9月30日💌', '修改后截至9月底💌']);
    expect(host.querySelector('[data-kind="removed"]')?.textContent).toBe('30日');
    expect(host.querySelector('[data-kind="added"]')?.textContent).toBe('底');
  });

  it('does not silently discard unsaved edits when switching to another tab', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await render(React.createElement(HermesPostInspector, { post, initialTab: 'edit', onClose: vi.fn(), onSaved: vi.fn() }));
    await fill('编辑标题', '尚未保存的新标题');
    await click(button('完整图文'));
    expect(confirm).toHaveBeenCalledOnce();
    expect(host.querySelector<HTMLInputElement>('[aria-label="编辑标题"]')?.value).toBe('尚未保存的新标题');
    expect(hermesWorkflowApi.editPost).not.toHaveBeenCalled();
  });
});
