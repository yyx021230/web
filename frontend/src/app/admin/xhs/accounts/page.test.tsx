import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Page from './page';

const mocks = vi.hoisted(() => ({ accounts: vi.fn(), preview: vi.fn(), apply: vi.fn() }));
vi.mock('@/services/xhsAccountMasterApi', () => ({ xhsAccountMasterApi: mocks }));
vi.mock('next/link', () => ({ default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  mocks.accounts.mockReset().mockResolvedValue([]);
  mocks.preview.mockReset().mockResolvedValue({ preview_id: 'preview-one', source_hash: 'a'.repeat(64),
    source_url: 'https://example.invalid/master', expires_at: '2026-11-13T12:00:00',
    rows: [{ row: 4, xhs_account_id: '10000001', account_name: 'Example account', owner_name: 'Operator One',
      owner_user_id: 2, department: 'xhs', operation: 'create', warnings: [], history_notes: 10 }],
    skipped: [{ row: 5, reason: 'private_department_excluded' }],
    unlisted_accounts: [{ id: 10, xhs_account_id: '10000099', account_name: 'Empty old account', action: 'delete_empty', references: {} },
      { id: 11, xhs_account_id: '10000098', account_name: 'Historical account', action: 'archive_history', references: { 'notes.account_id': 1 } }],
  });
  mocks.apply.mockReset().mockResolvedValue({ created: 1, updated: 0, history_notes_moved: 10, history_conflicts: [], unlisted_accounts_deleted: 1, unlisted_accounts_archived: 1 });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

async function upload() {
  const input = host.querySelector<HTMLInputElement>('input[type=file]')!;
  Object.defineProperty(input, 'files', { configurable: true, value: [new File(['fixture'], 'master.csv')] });
  await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })));
}
function button(text: string) { return Array.from(host.querySelectorAll('button')).find(b => b.textContent === text)!; }

it('requires a preview and explicit ownership confirmation before applying, with history opt-in', async () => {
  await act(async () => root.render(<Page />));
  expect(mocks.preview).not.toHaveBeenCalled(); expect(mocks.apply).not.toHaveBeenCalled();
  await upload();
  expect(host.textContent).toContain('Operator One'); expect(host.textContent).toContain('跳过 1 行');
  expect(button('确认应用').disabled).toBe(true);
  expect(host.textContent).toContain('无历史引用，剔除空账号');
  expect(host.textContent).toContain('有历史引用，仅归档保留');
  await act(async () => {
    host.querySelector<HTMLInputElement>('[aria-label="归属历史帖"]')!.click();
    host.querySelector<HTMLInputElement>('[aria-label="确认账号归属"]')!.click();
  });
  await act(async () => button('确认应用').click());
  expect(mocks.apply).toHaveBeenCalledWith('preview-one', { source_hash: 'a'.repeat(64), rows: [4], include_history: true, replace_all: true });
  expect(host.querySelector('[role=status]')?.textContent).toContain('未删除历史帖子');
});

it('retains the exact request on uncertain failure; no implicit write retry', async () => {
  mocks.apply.mockRejectedValueOnce(new Error('Network disconnected'));
  await act(async () => root.render(<Page />)); await upload();
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="确认账号归属"]')!.click());
  await act(async () => button('确认应用').click());
  expect(mocks.apply).toHaveBeenCalledTimes(1);
  expect(host.querySelector('[role=alert]')?.textContent).toContain('Network disconnected');
  expect(host.querySelectorAll<HTMLInputElement>('input[type=checkbox]')[0].disabled).toBe(true);
  await act(async () => button('按原选择再次确认').click());
  expect(mocks.apply.mock.calls[0]).toEqual(mocks.apply.mock.calls[1]);
});

it('does not present an empty successful preview when parsing fails', async () => {
  mocks.preview.mockRejectedValue(new Error('master_headers_missing'));
  await act(async () => root.render(<Page />)); await upload();
  expect(host.querySelector('[role=alert]')?.textContent).toContain('master_headers_missing');
  expect(host.textContent).not.toContain('确认应用');
  expect(mocks.apply).not.toHaveBeenCalled();
});

it('full-roster mode locks the complete selection and changing scope needs confirmation again', async () => {
  await act(async () => root.render(<Page />)); await upload();
  const row = host.querySelector<HTMLInputElement>('[aria-label="选择 Example account"]')!;
  expect(row.checked).toBe(true); expect(row.disabled).toBe(true);
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="完整替换主名单"]')!.click());
  expect(row.disabled).toBe(false);
  await act(async () => { row.click(); host.querySelector<HTMLInputElement>('[aria-label="确认账号归属"]')!.click(); });
  expect(button('确认应用').disabled).toBe(true);
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="完整替换主名单"]')!.click());
  expect(row.checked).toBe(true); expect(row.disabled).toBe(true);
  expect(host.querySelector<HTMLInputElement>('[aria-label="确认账号归属"]')!.checked).toBe(false);
  expect(mocks.apply).not.toHaveBeenCalled();
});

it('keeps archived accounts outside the current roster instead of displaying them as active', async () => {
  mocks.accounts.mockResolvedValue([{ id: 42, account_name: 'Archived example', xhs_account_id: '10000042', status: 'archived', department: 'xhs' }]);
  await act(async () => root.render(<Page />));
  expect(host.querySelector('tbody')?.textContent).not.toContain('Archived example');
  expect(host.querySelector('summary')?.textContent).toContain('历史归档 1 个');
  expect(host.textContent).toContain('Archived example');
});
