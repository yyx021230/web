import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AdminXhsSchedulesPage from './page';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/services/api', () => ({ default: { get } }));
vi.mock('@/services/adminApi', () => ({
  adminApi: {
    getUsers: vi.fn(async () => ({ data: { items: [] } })),
    getXhsAdAccountAssignments: vi.fn(async () => ({ data: [] })),
  },
}));
vi.mock('@/lib/toast', () => ({ toast: { error: vi.fn() } }));

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
  get.mockReset().mockImplementation(async (url, options) => {
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
