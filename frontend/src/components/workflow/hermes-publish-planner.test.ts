import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { HermesPost } from '@/services/hermesWorkflowApi';

vi.mock('@/lib/toast', () => ({ toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() } }));
vi.mock('@/services/hermesWorkflowApi', () => ({ hermesWorkflowApi: {
  bootstrap: vi.fn(), adminBootstrap: vi.fn(),
  listPublishCandidates: vi.fn(), adminPublishCandidates: vi.fn(),
  savePublishPlan: vi.fn(), adminSavePublishPlan: vi.fn(), preparePublish: vi.fn(),
  listPublishJobs: vi.fn(), adminPublishJobs: vi.fn(), cancelPublishJob: vi.fn(), adminCancelPublishJob: vi.fn(),
} }));
vi.mock('./HermesPostInspector', () => ({ default: () => null }));
vi.mock('./HermesFrame', () => ({ hermesDate: (value: string) => value }));

import HermesPublishPlanner from './HermesPublishPlanner';
import { hermesWorkflowApi } from '@/services/hermesWorkflowApi';
import { toast } from '@/lib/toast';

let host: HTMLDivElement;
let root: Root;
const post: HermesPost = { id: 12, run_id: 8, slot: 1, environment_id: 42, account_name: '账号甲', vehicle_model: '零跑A05', title: '已审核内容', content: '保留已有图文', image_url: '/test-image.png', status: 'approved', hard_pass: true, publish_status: 'not_ready', version: 'v1' };

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const accounts = { data: { accounts: [{ id: 42, name: '账号甲' }] } };
  vi.mocked(hermesWorkflowApi.bootstrap).mockResolvedValue(accounts as never);
  vi.mocked(hermesWorkflowApi.adminBootstrap).mockResolvedValue(accounts as never);
  vi.mocked(hermesWorkflowApi.listPublishCandidates).mockResolvedValue({ data: { items: [post], total: 1 } } as never);
  vi.mocked(hermesWorkflowApi.adminPublishCandidates).mockResolvedValue({ data: { items: [post], total: 1 } } as never);
  vi.mocked(hermesWorkflowApi.listPublishJobs).mockResolvedValue({ data: { items: [], total: 0, dispatch_enabled: false } } as never);
  vi.mocked(hermesWorkflowApi.adminPublishJobs).mockResolvedValue({ data: { items: [], total: 0, dispatch_enabled: false } } as never);
  vi.mocked(hermesWorkflowApi.savePublishPlan).mockResolvedValue({ data: { items: [post] } } as never);
  vi.mocked(hermesWorkflowApi.adminSavePublishPlan).mockResolvedValue({ data: { items: [post] } } as never);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function render(admin: boolean) {
  await act(async () => root.render(React.createElement(HermesPublishPlanner, { admin })));
  await act(async () => vi.advanceTimersByTimeAsync(350));
}
async function click(label: string) {
  const button = Array.from(host.querySelectorAll('button')).find(item => item.textContent === label);
  expect(button).toBeDefined();
  await act(async () => button!.click());
}
function expectNoWrites() {
  expect(hermesWorkflowApi.savePublishPlan).not.toHaveBeenCalled();
  expect(hermesWorkflowApi.adminSavePublishPlan).not.toHaveBeenCalled();
  expect(hermesWorkflowApi.preparePublish).not.toHaveBeenCalled();
}

describe.each([false, true])('cloud phone publication planner, admin=%s', admin => {
  it('keeps uploaded drafts visible but does not allow scheduling before review', async () => {
    vi.mocked(admin ? hermesWorkflowApi.adminPublishCandidates : hermesWorkflowApi.listPublishCandidates).mockResolvedValue({ data: {
      items: [{ ...post, source_kind: 'user_upload', status: 'review_pending', image_urls: ['/one.png', '/two.png'] }], total: 1,
    } } as never);
    await render(admin);
    expect(host.textContent).toContain('自主上传 · 2张图片');
    expect(host.textContent).toContain('待确认图文');
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.disabled).toBe(true);
    await click('选择本页（最多40篇）'); await click('保存发布计划');
    expectNoWrites();
  });
  it('shows disabled dispatch honestly and requires selected posts', async () => {
    await render(admin);
    expect(host.textContent).toContain('不会下发手机');
    await click('保存发布计划');
    expect(toast.error).toHaveBeenCalledWith('请先选择需要排期的内容');
    expectNoWrites();
  });

  it('saves the exact review version and Beijing time through the correct endpoint', async () => {
    await render(admin);
    await click('选择本页（最多40篇）');
    await click('按账号填入时间');
    const times = Array.from(host.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]')).map(input => input.value);
    expect(times).toHaveLength(2);
    expect(times.every(Boolean)).toBe(true);
    vi.mocked(toast.success).mockClear();
    await click('保存发布计划');
    expect(admin ? hermesWorkflowApi.adminSavePublishPlan : hermesWorkflowApi.savePublishPlan).toHaveBeenCalledWith([
      { post_id: 12, environment_id: 42, expected_version: 'v1', scheduled_at: `${times[1]}+08:00` },
    ]);
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
    expect(toast.success).toHaveBeenCalledWith('发布排期已保存');
    expect(hermesWorkflowApi.preparePublish).not.toHaveBeenCalled();
  });

  it('rejects incomplete times without any write', async () => {
    await render(admin);
    await click('选择本页（最多40篇）');
    await click('保存发布计划');
    expect(toast.error).toHaveBeenCalledWith('请填写每篇发布时间，并确认审核版本已加载');
    expectNoWrites();
  });

  it('keeps the form on a lost save response and never auto-replays POST', async () => {
    vi.mocked(admin ? hermesWorkflowApi.adminSavePublishPlan : hermesWorkflowApi.savePublishPlan).mockRejectedValue(new Error('保存结果未知'));
    await render(admin);
    await click('选择本页（最多40篇）'); await click('按账号填入时间'); await click('保存发布计划');
    expect(admin ? hermesWorkflowApi.adminSavePublishPlan : hermesWorkflowApi.savePublishPlan).toHaveBeenCalledOnce();
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
    expect(toast.error).toHaveBeenCalledWith('保存结果未知');
  });

  it('shows persistent unknown results and does not offer unsafe retry', async () => {
    vi.mocked(admin ? hermesWorkflowApi.adminPublishJobs : hermesWorkflowApi.listPublishJobs).mockResolvedValue({ data: {
      items: [{ id: 9, post_id: 12, environment_id: 42, title: '已审核内容', scheduled_at: '2030-01-01T09:00', status: 'unknown', message: '结果未知，禁止重发', can_cancel: false, events: [] }], total: 1, dispatch_enabled: true,
    } } as never);
    await render(admin);
    expect(host.textContent).toContain('结果未知 · 需核查');
    expect(host.textContent).toContain('结果未知，禁止重发');
    expect(host.textContent).not.toContain('取消发布');
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.disabled).toBe(true);
    await click('选择本页（最多40篇）');
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
    expectNoWrites();
  });

  it('shows cloud success without requesting verification or offering republication', async () => {
    vi.mocked(admin ? hermesWorkflowApi.adminPublishJobs : hermesWorkflowApi.listPublishJobs).mockResolvedValue({ data: {
      items: [{ id: 9, post_id: 12, environment_id: 42, title: '已审核内容', scheduled_at: '2030-01-01T09:00', status: 'submitted', message: '云手机返回发布成功', can_cancel: false, events: [] }], total: 1, dispatch_enabled: true,
    } } as never);
    await render(admin);
    expect(host.textContent).toContain('云手机发布成功');
    expect(host.textContent).not.toContain('待核验');
    expect(host.textContent).not.toContain('取消发布');
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.disabled).toBe(true);
    await click('选择本页（最多40篇）');
    await act(async () => vi.advanceTimersByTimeAsync(10_000));
    expectNoWrites();
  });

  it('requests cancellation through the owner or admin endpoint without promising withdrawal', async () => {
    const list = admin ? hermesWorkflowApi.adminPublishJobs : hermesWorkflowApi.listPublishJobs;
    vi.mocked(list).mockResolvedValue({ data: { items: [{ id: 9, post_id: 12, environment_id: 42, status: 'queued', title: '已审核内容', scheduled_at: '2030-01-01T09:00', can_cancel: true, events: [] }], total: 1, dispatch_enabled: true } } as never);
    vi.mocked(admin ? hermesWorkflowApi.adminCancelPublishJob : hermesWorkflowApi.cancelPublishJob).mockResolvedValue({ data: { status: 'cancel_requested' } } as never);
    await render(admin);
    await click('取消发布');
    expect(window.confirm).toHaveBeenCalledWith('取消这条发布任务？若手机已经提交，取消不能撤回帖子。');
    expect(admin ? hermesWorkflowApi.adminCancelPublishJob : hermesWorkflowApi.cancelPublishJob).toHaveBeenCalledWith(9);
    expectNoWrites();
  });
});
