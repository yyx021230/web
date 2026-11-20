import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { exportXhsAdDashboardTable, getXhsAdDashboard, getXhsAdDashboardContentTags, type XHSAdDashboardResponse } from '@/services/xhsApi';
import AdInsightsPage from './page';

vi.mock('next/script', () => ({ default: () => null }));
vi.mock('@/services/xhsApi', () => ({
  getXhsAdDashboard: vi.fn(), getXhsAdDashboardContentTags: vi.fn(), exportXhsAdDashboardTable: vi.fn(),
}));
vi.mock('@/lib/toast', () => ({ toast: { error: vi.fn() } }));

const quadrant = (tag: string, y: number) => ({ avg_x: 2, avg_y: y, points: [{ tag, x: 2, y, size: y * 2, click: 90, interaction: 10 }] });
const account = { account_id: '111', account_name: '广告账户甲', has_token: true, buyer_user_id: 3, xhs_account_id: '12345', xhs_account_name: '小红书号甲', xhs_owner_name: '内容负责人' };
const data: XHSAdDashboardResponse = {
  start_date: '2026-11-18', end_date: '2026-11-19', previous_start_date: '2026-11-16', previous_end_date: '2026-11-17',
  filters: { account_ids: [], report_type: 'all', accounts: [account], buyers: [{ user_id: 3, username: 'buyer', display_name: '投手甲', account_count: 1 }] },
  summary: {},
  kpis: [{ key: 'total_spend', label: '总消耗', value: 123.45, previous_value: 80, value_type: 'currency', delta: 43.45, delta_rate: 54.31 }],
  owner_rows: [{ owner_key: 'user:3', owner_name: '投手甲', account_count: 1, fee: 123.45, conversion: 5 }],
  quadrant: { avg_x: 0, avg_y: 0, points: [] }, creative_tags: [], top_notes: {}, note_rows: [], brand_rows: [],
  funnel: [{ label: '曝光', value: 100, step_rate: 100, overall_rate: 100 }],
  comparison_rows: [{ owner_key: 'user:3', owner_name: '投手甲', fee_current: 123.45, fee_previous: 80, fee_delta: 43.45 }],
  trend: [{ date: '2026-11-18', fee: 123.45, conversion: 5, impression: 100, click: 20 }],
  ai_summary: { title: '', summary: '', actions: [] },
};
const content = {
  quadrant: quadrant('实拍', 5), creative_tags: [],
  top_notes: { conversion: { note_title: '热销车型', note_id: 'ffffffffffffffffff', conversion: 5 } },
  note_rows: [{ note_title: '完整笔记表' }],
  content_tag_children: { 实拍: { quadrant: quadrant('试驾体验', 3), creative_tags: [] } },
};

let host: HTMLDivElement;
let root: Root;
let files: { blob: Blob; filename?: string }[];
const exportButton = (title: string) => host.querySelector<HTMLButtonElement>(`button[aria-label="导出表格：${title}"]`)!;
const button = (label: string) => [...host.querySelectorAll('button')].find((element) => element.textContent?.trim() === label)!;

function readFile(blob: Blob) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

async function advance(ms = 600) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

async function render() {
  await act(async () => root.render(<AdInsightsPage />));
}

beforeEach(() => {
  vi.stubGlobal('React', React);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  files = [];
  class DownloadUrl extends URL {
    static createObjectURL = vi.fn((blob: Blob) => { files.push({ blob }); return `blob:export-${files.length}`; });
    static revokeObjectURL = vi.fn();
  }
  vi.stubGlobal('URL', DownloadUrl);
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    files.at(-1)!.filename = this.download;
  });
  vi.mocked(getXhsAdDashboard).mockReset().mockResolvedValue(data);
  vi.mocked(getXhsAdDashboardContentTags).mockReset().mockResolvedValue(content);
  vi.mocked(exportXhsAdDashboardTable).mockReset().mockResolvedValue(new Blob(['excel']));
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('ad dashboard export actions', () => {
  it('downloads every panel as a table, without requesting new dashboard data', async () => {
    await render();
    await advance();
    const titles = ['总消耗', '投手转化消耗效率排行', '笔记排行', '内容标签分析', '投手消耗 / 转化排行', '转化漏斗', '消耗转化趋势', '环比数据', '核心指标趋势'];
    for (const title of titles) {
      expect(exportButton(title).disabled).toBe(false);
      await act(async () => exportButton(title).click());
    }
    expect(files).toHaveLength(titles.length);
    expect(files.every((file) => file.filename?.endsWith('_2026-11-18_2026-11-19.csv'))).toBe(true);
    expect(await readFile(files[0].blob)).toContain('123.45');
    expect(await readFile(files[6].blob)).toContain('24.69');
    expect(getXhsAdDashboard).toHaveBeenCalledTimes(1);
    expect(getXhsAdDashboardContentTags).toHaveBeenCalledTimes(1);
    expect(exportXhsAdDashboardTable).not.toHaveBeenCalled();
    await advance(1000);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(titles.length);
  });

  it('exports the selected trend curves and the currently opened child tag only', async () => {
    await render();
    await advance();
    await act(async () => button('点击').click());
    await act(async () => exportButton('核心指标趋势').click());
    expect(await readFile(files[0].blob)).toContain('"日期","曝光","点击"');
    await act(async () => host.querySelector<HTMLButtonElement>('button[title="查看该一级标签下的二级标签"]')!.click());
    await act(async () => exportButton('内容标签分析_实拍').click());
    const csv = await readFile(files[1].blob);
    expect(csv).toContain('"一级标签","二级标签"');
    expect(csv).toContain('"实拍","试驾体验",3,2,6');
    await act(async () => button('返回上一级').click());
    await act(async () => exportButton('内容标签分析').click());
    expect(await readFile(files[2].blob)).not.toContain('试驾体验');
  });

  it('keeps export disabled during refresh and pairs content even when it returns before core data', async () => {
    await render();
    await advance();
    let resolveDashboard!: (result: XHSAdDashboardResponse) => void;
    vi.mocked(getXhsAdDashboard).mockImplementationOnce(() => new Promise((resolve) => { resolveDashboard = resolve; }));
    vi.mocked(getXhsAdDashboardContentTags).mockResolvedValueOnce({ ...content, quadrant: quadrant('新范围标签', 8) });
    const selector = host.querySelector('select')!;
    await act(async () => { selector.value = '3'; selector.dispatchEvent(new Event('change', { bubbles: true })); });
    expect(exportButton('总消耗').disabled).toBe(true);
    expect(exportButton('内容标签分析').disabled).toBe(true);
    await advance();
    expect(exportButton('内容标签分析').disabled).toBe(true);
    await act(async () => resolveDashboard({ ...data, owner_rows: [{ ...account, owner_name: account.account_name, fee: 4 }] }));
    await act(async () => exportButton('内容标签分析').click());
    expect(await readFile(files[0].blob)).toContain('新范围标签');
    expect(exportButton('投流账号排行').disabled).toBe(false);
    expect(getXhsAdDashboard).toHaveBeenLastCalledWith(expect.objectContaining({ buyer_user_id: 3 }));
  });

  it('retains both full Excel endpoints and passes the active professional-account filter', async () => {
    await render();
    await advance();
    await act(async () => button('全部小红书号').click());
    await act(async () => host.querySelector<HTMLInputElement>('label[title^="小红书号甲"] input')!.click());
    expect(exportButton('品牌消耗转化表').disabled).toBe(true);
    await advance();
    await act(async () => exportButton('品牌消耗转化表').click());
    await act(async () => exportButton('笔记消耗转化表').click());
    for (const table of ['brand', 'note']) {
      expect(exportXhsAdDashboardTable).toHaveBeenCalledWith(table, expect.objectContaining({ account_ids: ['111'], report_type: 'all' }));
    }
    expect(files.map((file) => file.filename)).toEqual(['小红书投流品牌表_2026-11-18_2026-11-19.xlsx', '小红书投流笔记表_2026-11-18_2026-11-19.xlsx']);
  });

  it('does not enable old chart exports if a new scope fails to load', async () => {
    await render();
    await advance();
    vi.mocked(getXhsAdDashboard).mockRejectedValueOnce(new Error('暂时不可用'));
    const selector = host.querySelector('select')!;
    await act(async () => { selector.value = '3'; selector.dispatchEvent(new Event('change', { bubbles: true })); });
    await advance();
    expect(exportButton('消耗转化趋势').disabled).toBe(true);
    expect(exportButton('内容标签分析').disabled).toBe(true);
    expect(files).toHaveLength(0);
  });
});
