import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AdminXhsSchedulesPage from './page';

const { get, put } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock('@/services/api', () => ({ default: { get, put } }));
vi.mock('@/services/adminApi', () => ({
  adminApi: {
    getUsers: vi.fn(async () => ({ data: { items: [] } })),
    getXhsAdAccountAssignments: vi.fn(async () => ({ data: [] })),
  },
}));
vi.mock('@/lib/toast', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const taskKey = 'ad_data_refresh';
const log = {
  id: 91,
  task_key: taskKey,
  source: 'schedule',
  status: 'partial',
  message: 'Partial refresh',
  token_details_status: 'partial',
  token_issues: [
    { account_id: '8343103', account_name: 'Cloud 3', status: 'missing', reason: 'Missing token', report_types: ['simple'] },
    { account_id: '8829829', account_name: 'Cloud 5', status: 'cached', reason: 'Network timeout', report_types: [] },
  ],
};

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  put.mockReset();
  get.mockReset().mockImplementation(async (url, options) => {
    if (url === '/xhs/accounts/mode') {
      return { data: { mode: 'legacy', ready: true, accounts: [], runners: [] } };
    }
    if (url === '/admin/xhs/schedule-settings') {
      return { data: [{ task_key: taskKey, label: 'Ads refresh', description: '', enabled: true, run_time: '08:30', config: {} }] };
    }
    if (url === '/admin/xhs/schedule-run-logs') {
      const { page, task_key } = options.params;
      const items = page === 1 ? [log] : [{ ...log, id: 90, message: 'Older run', token_details_status: 'unavailable', token_issues: [] }];
      return { data: { items, page, total_pages: 2, total: task_key ? 9 : 16 } };
    }
    return { data: [] };
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it('shows per-account token evidence and pages both histories independently', async () => {
  await act(async () => root.render(<AdminXhsSchedulesPage />));
  const details = host.querySelector('details')!;
  expect(details.querySelector('summary')?.textContent).toContain('2');
  await act(async () => { details.querySelector('summary')!.click(); });
  expect(details.open).toBe(true);
  expect(details.textContent).toContain('Cloud 3');
  expect(details.textContent).toContain('8343103');
  expect(details.textContent).toContain('Network timeout');

  const mainPagination = host.querySelector('nav')!;
  await act(async () => { mainPagination.querySelectorAll('button')[1].click(); });
  expect(get).toHaveBeenCalledWith('/admin/xhs/schedule-run-logs', expect.objectContaining({
    params: { page: 2, limit: 15, task_key: undefined },
  }));
  expect(host.textContent).toContain('Older run');

  const openConfig = Array.from(host.querySelectorAll('button'))
    .find((button) => button.textContent?.trim() === '\u914d\u7f6e')!;
  await act(async () => { openConfig.click(); });
  const detailPagination = host.querySelectorAll('nav')[1];
  expect(detailPagination.querySelector('button')?.disabled).toBe(true);
  await act(async () => { detailPagination.querySelectorAll('button')[1].click(); });
  expect(get).toHaveBeenCalledWith('/admin/xhs/schedule-run-logs', expect.objectContaining({
    params: { page: 2, limit: 8, task_key: taskKey },
  }));
});

it('selects canonical accounts and saves account_ids without reusing environment IDs', async () => {
  get.mockImplementation(async (url) => {
    if (url === '/xhs/accounts/mode') return { data: { mode: 'feishu', ready: true,
      accounts: [{ id: 7, account_name: 'Canonical account', status: 'active', owner_name: 'Current operator' }],
      runners: [{ id: 100, account_name: '测试4' }] } };
    if (url === '/xhs/environments') return { data: [{ id: 7, account_name: 'Unrelated legacy environment', shop_id: 'old', status: 'active' }] };
    if (url === '/admin/xhs/schedule-settings') return { data: [{ task_key: 'account_data_sync', label: 'Account sync',
      description: '', enabled: false, run_time: '03:00', config: {} }] };
    if (url === '/admin/xhs/schedule-run-logs') return { data: { items: [], page: 1, total: 0, total_pages: 1 } };
    return { data: [] };
  });
  put.mockImplementation(async (_url, payload) => ({ data: { task_key: 'account_data_sync', label: 'Account sync', ...payload } }));
  await act(async () => root.render(<AdminXhsSchedulesPage />));
  const button = (label: string) => Array.from(host.querySelectorAll('button')).find(b => b.textContent?.trim() === label)!;
  await act(async () => button('配置').click());
  await act(async () => button('指定账号').click());
  expect(host.textContent).toContain('Canonical account');
  expect(host.textContent).not.toContain('Unrelated legacy environment');
  const account = Array.from(host.querySelectorAll('label')).find(l => l.textContent?.includes('Canonical account'))!;
  await act(async () => account.querySelector<HTMLInputElement>('input')!.click());
  await act(async () => button('保存配置').click());
  expect(put).toHaveBeenCalledWith('/admin/xhs/schedule-settings/account_data_sync', expect.objectContaining({
    config: expect.objectContaining({ target_scope: 'account_ids', target_account_ids: [7], target_environment_ids: [] }),
  }));
});
