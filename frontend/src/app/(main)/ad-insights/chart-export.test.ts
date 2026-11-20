import { describe, expect, it } from 'vitest';
import {
  comparisonTable, coreTrendTable, funnelTable, metricTable, metricTrendValues, ownerTable,
  serializeCsv, spendTrendTable, tagRows, tagTable, topNotesTable,
} from './chart-export';

const trend = [
  { date: '2026-11-18', fee: 72.25, conversion: 4, impression: 1000, click: 50, interaction: 15, openings: 5 },
  { date: '2026-11-19', fee: 3, conversion: 0, impression: 0, click: 0, interaction: 0, openings: 0 },
];

describe('ad dashboard chart export tables', () => {
  it('preserves KPI period totals, signed differences and the plotted daily values', () => {
    const dates = {
      start_date: '2026-11-18', end_date: '2026-11-19', previous_start_date: '2026-11-16', previous_end_date: '2026-11-17',
    };
    const output = metricTable({ key: 'ctr', label: '点击率', value: 5, previous_value: 7, delta: -2, delta_rate: -28.57, value_type: 'percent' }, { ...dates, trend });
    expect(output.rows).toEqual([
      ['本期', '2026-11-18', '2026-11-19', 5, '%'],
      ['上期', '2026-11-16', '2026-11-17', 7, '%'],
      ['本期减上期', '2026-11-18', '2026-11-19', -2, '百分点'],
      ['按日', '2026-11-18', '2026-11-18', 5, '%'],
      ['按日', '2026-11-19', '2026-11-19', 0, '%'],
    ]);
    expect(metricTrendValues('opening_cost', trend)).toEqual([14.45, 0]);
    expect(metricTrendValues('total_impression', trend)).toEqual([1000, 0]);
  });

  it('exports all rows even when the visual ranking is limited and follows the ranking metric', () => {
    const a = { owner_name: '负责人甲', account_id: '123', account_count: 2, fee: 100, conversion: 1, conversion_cost: 100, opening_conversion_rate: 25 };
    const b = { ...a, owner_name: '负责人乙', fee: 25 };
    const rows = [a, b, ...Array.from({ length: 15 }, () => ({ fee: 0, conversion: 1 }))];
    const efficiency = ownerTable(rows, false, true);
    expect(efficiency.rows).toHaveLength(17);
    expect(efficiency.rows[0]).toEqual([1, '负责人乙', 2, 25, 1, 100, 40]);
    expect(ownerTable(rows, true).rows[0]).toEqual([1, '负责人甲', '123', 100, 1, 100, 25]);
    expect(rows[0]).toBe(a);
  });

  it('uses top-note dimensions and content-tag points without substituting unrelated totals', () => {
    expect(topNotesTable({ conversion: { note_title: '汽车笔记', xhs_account_name: '汽车账号', openings: 3 } }).rows[0])
      .toEqual(['转化最高笔记', '汽车笔记', '汽车账号', undefined, 0, 0, 0, 0, 3, 0]);
    const rows = tagRows([{ tag: '二级分类', x: 1.25, y: 14, size: 17.5, click: 110, interaction: 5 }]);
    expect(tagTable(rows, '一级分类').rows).toEqual([['一级分类', '二级分类', 14, 1.25, 17.5, 110, 5]]);
    expect(tagTable(rows, '').headers[0]).toBe('一级标签');
  });

  it('exports daily spend, zeros and only the chosen core trend series in UI order', () => {
    expect(spendTrendTable(trend).rows).toEqual([['2026-11-18', 72.25, 4, 18.0625, 50, 1000], ['2026-11-19', 3, 0, 0, 0, 0]]);
    expect(coreTrendTable(trend, ['interaction', 'click'])).toEqual({ headers: ['日期', '互动', '点击'], rows: [['2026-11-18', 15, 50], ['2026-11-19', 0, 0]] });
  });

  it('preserves funnel steps and only the comparison entities and metrics shown in the current mode', () => {
    expect(funnelTable([{ label: '曝光', value: 10, overall_rate: 100 }, { label: '开口', value: 1, step_rate: 25, overall_rate: 10 }]).rows)
      .toEqual([['曝光', 10, 100, 100], ['开口', 1, 25, 10]]);
    const rows = [{ owner_key: 'unassigned' }, { owner_name: '未分配' }, { owner_name: '甲', opening_rate_current: 0.25, opening_rate_previous: 1, opening_rate_delta: -0.75 }];
    expect(comparisonTable(rows, true).rows[0].slice(-3)).toEqual([0.25, 1, -0.75]);
    expect(comparisonTable(rows, true).headers).not.toContain('本期开口成本（元）');
    expect(comparisonTable(rows, false).headers).toContain('本期开口成本（元）');
    expect(comparisonTable(rows, false).rows).toHaveLength(1);
  });

  it('writes UTF-8 Excel-compatible CSV and keeps text inert without corrupting signed numbers', () => {
    expect(serializeCsv({ headers: ['中文', '金额'], rows: [['甲,"乙"\n丙', -10.25], [' =1+1', 0], ['\t关键词', null], ['＠公式', 1]] }))
      .toBe('\uFEFF"中文","金额"\r\n"甲,""乙""\n丙",-10.25\r\n"\' =1+1",0\r\n"\'\t关键词",""\r\n"\'＠公式",1\r\n');
  });
});
