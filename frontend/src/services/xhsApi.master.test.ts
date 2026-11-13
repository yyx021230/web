import { beforeEach, expect, it, vi } from 'vitest';
import { getXhsDataDirectory, getXhsAccountNotes, importXhsCreatorExport,
  syncXhsAccountNotes, syncXhsAccountNoteEngagements, syncXhsAccountNoteDetails } from './xhsApi';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('./api', () => ({ default: mocks, resolveDirectApiBaseURL: () => '/api/v1' }));
beforeEach(() => { mocks.get.mockReset(); mocks.post.mockReset().mockResolvedValue({ data: { job_id: 'test-job' } }); });

it('uses the master directory without fetching browser environments or inventing shop IDs', async () => {
  const account = { id: 1, account_name: 'Canonical account', department: 'xhs', owner_name: 'Owner' };
  mocks.get.mockResolvedValue({ data: { mode: 'feishu', ready: true, accounts: [account], runners: [{ id: 100, account_name: '测试4' }] } });
  const result = await getXhsDataDirectory();
  expect(result.accounts).toEqual([account]);
  expect(result.accounts[0].shop_id).toBeUndefined();
  expect(mocks.get).toHaveBeenCalledTimes(1);
});

it('does not silently fall back when the canonical roster has not been initialized', async () => {
  mocks.get.mockResolvedValue({ data: { mode: 'feishu', ready: false, accounts: [], runners: [] } });
  await expect(getXhsDataDirectory()).rejects.toThrow('尚未完整初始化');
  expect(mocks.get).toHaveBeenCalledTimes(1);
});

it('retains the legacy environment API only when the backend explicitly selects legacy mode', async () => {
  mocks.get.mockResolvedValueOnce({ data: { mode: 'legacy', ready: true, accounts: [], runners: [] } })
    .mockResolvedValueOnce({ data: [{ id: 100, account_name: '测试4', is_sync_runner: true }] });
  expect((await getXhsDataDirectory()).runners[0].id).toBe(100);
  expect(mocks.get).toHaveBeenLastCalledWith('/xhs/environments');
});

it('sends native read and manual-import IDs under account_id, never environment_id', async () => {
  mocks.get.mockResolvedValue({ data: { items: [] } });
  await getXhsAccountNotes({ account_id: 1 });
  expect(mocks.get).toHaveBeenCalledWith('/xhs/account-notes', { params: { account_id: 1 } });
  const file = new File(['fixture'], 'creator.xlsx');
  await importXhsCreatorExport(1, file, 'feishu');
  expect(mocks.post.mock.calls[0][2].params).toEqual({ account_id: 1 });
  expect(mocks.post.mock.calls[0][1].get('file')).toBe(file);
});

it('separates native homepage targets from browser runner IDs', async () => {
  await syncXhsAccountNotes({ identity_source: 'feishu', runner_account_assignments: '{"100":[1,2]}',
    scrape_environment_id: 100, homepage_sync_mode: 'supplement_only', concurrency: 2 });
  expect(mocks.post).toHaveBeenCalledWith('/xhs/accounts/sync', expect.objectContaining({
    kind: 'posts', account_ids: [1, 2], runner_ids: [100], runner_assignments: { '100': [1, 2] },
  }));
  expect(mocks.post.mock.calls[0][1]).not.toHaveProperty('environment_id');
});

it('routes creator results and exact detail selection through the canonical sync contract', async () => {
  await syncXhsAccountNoteEngagements({ identity_source: 'feishu', target_environment_ids: '1,2' });
  expect(mocks.post.mock.calls[0][1]).toMatchObject({ kind: 'engagement', account_ids: [1, 2] });
  await syncXhsAccountNoteDetails({ identity_source: 'feishu', environment_id: 1, scrape_environment_ids: '100,101',
    target_note_ids: '30,31', sync_limit: 2, sync_mode: 'unpublished_only' });
  expect(mocks.post.mock.calls[1][1]).toMatchObject({ kind: 'details', account_ids: [1], runner_ids: [100, 101],
    target_note_ids: [30, 31], sync_limit: 2, sync_mode: 'unpublished_only' });
  expect(mocks.post.mock.calls[1][1]).not.toHaveProperty('environment_id');
});
