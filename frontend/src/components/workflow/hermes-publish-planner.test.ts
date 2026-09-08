import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { HermesPost } from '@/services/hermesWorkflowApi';

vi.mock('@/lib/toast', () => ({ toast: { info: vi.fn(), success: vi.fn(), error: vi.fn() } }));
vi.mock('@/services/hermesWorkflowApi', () => ({ hermesWorkflowApi: {
  bootstrap: vi.fn(), adminBootstrap: vi.fn(),
  listPublishCandidates: vi.fn(), adminPublishCandidates: vi.fn(),
  savePublishPlan: vi.fn(), adminSavePublishPlan: vi.fn(), preparePublish: vi.fn(),
} }));
vi.mock('./HermesPostInspector', () => ({ default: () => null }));
vi.mock('./HermesFrame', () => ({ hermesDate: (value: string) => value }));

import HermesPublishPlanner from './HermesPublishPlanner';
import { hermesWorkflowApi } from '@/services/hermesWorkflowApi';
import { toast } from '@/lib/toast';

let host: HTMLDivElement;
let root: Root;
const post: HermesPost = { id: 12, run_id: 8, slot: 1, environment_id: 42, account_name: '账号甲', vehicle_model: '零跑A05', title: '已审核内容', content: '保留已有图文', image_url: '/test-image.png', status: 'approved', hard_pass: true, publish_status: 'not_ready', version: 'v1' };
const message = '发布计划功能开发中，敬请期待。当前设置暂未保存，也不会执行发布。';

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const accounts = { data: { accounts: [{ id: 42, name: '账号甲' }] } };
  vi.mocked(hermesWorkflowApi.bootstrap).mockResolvedValue(accounts as never);
  vi.mocked(hermesWorkflowApi.adminBootstrap).mockResolvedValue(accounts as never);
  vi.mocked(hermesWorkflowApi.listPublishCandidates).mockResolvedValue({ data: { items: [post], total: 1 } } as never);
  vi.mocked(hermesWorkflowApi.adminPublishCandidates).mockResolvedValue({ data: { items: [post], total: 1 } } as never);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });
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

describe.each([false, true])('publication plan placeholder, admin=%s', admin => {
  it('shows the development notice even with no posts selected', async () => {
    await render(admin);
    expect(host.textContent).toContain('暂不保存，也不会自动发布');
    await click('保存发布计划');
    expect(toast.info).toHaveBeenCalledWith(message);
    expect(toast.success).not.toHaveBeenCalled();
    expectNoWrites();
  });

  it('does not save complete selections, clear the form, or reload records', async () => {
    await render(admin);
    await click('选择本页（最多40篇）');
    await click('按账号填入时间');
    const times = Array.from(host.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]')).map(input => input.value);
    expect(times).toHaveLength(2);
    expect(times.every(Boolean)).toBe(true);
    const reads = vi.mocked(admin ? hermesWorkflowApi.adminPublishCandidates : hermesWorkflowApi.listPublishCandidates);
    const readCount = reads.mock.calls.length;
    vi.mocked(toast.success).mockClear();
    await click('保存发布计划');
    await click('保存发布计划');
    expect(toast.info).toHaveBeenCalledTimes(2);
    expect(toast.info).toHaveBeenLastCalledWith(message);
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
    expect(Array.from(host.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]')).map(input => input.value)).toEqual(times);
    expect(reads).toHaveBeenCalledTimes(readCount);
    expect(toast.success).not.toHaveBeenCalled();
    expectNoWrites();
  });

  it('shows the same notice instead of validating an incomplete plan', async () => {
    await render(admin);
    await click('选择本页（最多40篇）');
    await click('保存发布计划');
    expect(toast.info).toHaveBeenCalledWith(message);
    expect(toast.error).not.toHaveBeenCalled();
    expectNoWrites();
  });
});
