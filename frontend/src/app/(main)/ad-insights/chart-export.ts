import type { XHSAdDashboardResponse } from '@/services/xhsApi';

type Row = Record<string, unknown>;
type Table = { headers: readonly string[]; rows: readonly (readonly unknown[])[] };
type Range = Pick<XHSAdDashboardResponse, 'start_date' | 'end_date'>;
type MetricData = Range & Pick<XHSAdDashboardResponse, 'previous_start_date' | 'previous_end_date' | 'trend'>;

export const TREND_METRICS = [
  { key: 'conversion', label: '有效线索', color: '#166534' },
  { key: 'impression', label: '曝光', color: '#111827' },
  { key: 'click', label: '点击', color: '#2563eb' },
  { key: 'interaction', label: '互动', color: '#d97706' },
  { key: 'openings', label: '开口', color: '#be123c' },
] as const;

export const TOP_NOTE_LABELS: Record<string, string> = {
  conversion: '转化最高笔记', conversion_rate: '转化率最高笔记', impression: '展现最高笔记',
  message_consult: '私信进线最高', initiative_message: '私信开口最高',
};

export function chartNumber(value: unknown) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function conversionCost(point: Row) {
  return chartNumber(point.conversion) > 0 ? chartNumber(point.fee) / chartNumber(point.conversion) : 0;
}

export function metricTrendValues(key: string, trend: Row[]) {
  return trend.map((point) => {
    const ratio = (numerator: string, denominator: string, scale = 1) => (
      chartNumber(point[denominator]) > 0 ? chartNumber(point[numerator]) / chartNumber(point[denominator]) * scale : 0
    );
    switch (key) {
      case 'ctr': return ratio('click', 'impression', 100);
      case 'avg_click_cost': return ratio('fee', 'click');
      case 'interaction_rate': return ratio('interaction', 'click', 100);
      case 'opening_cost': return ratio('fee', 'openings');
      case 'conversion_rate': return ratio('conversion', 'click', 100);
      case 'conversion_cost': return conversionCost(point);
      case 'total_impression': return chartNumber(point.impression);
      case 'total_click': return chartNumber(point.click);
      case 'total_spend': return chartNumber(point.fee);
      default: return chartNumber(point[key]);
    }
  });
}

export function metricTable(metric: XHSAdDashboardResponse['kpis'][number], data: MetricData): Table {
  const unit = metric.value_type === 'percent' ? '%' : metric.value_type === 'currency' ? '元' : '';
  const values = metricTrendValues(metric.key, data.trend);
  return {
    headers: ['统计项', '开始日期', '结束日期', unit ? `${metric.label}（${unit}）` : metric.label, '单位'],
    rows: [
      ['本期', data.start_date, data.end_date, metric.value, unit],
      ['上期', data.previous_start_date, data.previous_end_date, metric.previous_value, unit],
      ['本期减上期', data.start_date, data.end_date, metric.delta, unit === '%' ? '百分点' : unit],
      ...data.trend.map((point, index) => ['按日', point.date, point.date, values[index], unit]),
    ],
  };
}

export function rankOwners(rows: Row[], byEfficiency: boolean): Array<Row & { efficiency: number }> {
  return rows.map((row) => ({
    ...row,
    efficiency: chartNumber(row.fee) > 0 ? (chartNumber(row.conversion) / chartNumber(row.fee)) * 1000 : 0,
  })).sort((a: Row, b: Row) => chartNumber(b[byEfficiency ? 'efficiency' : 'fee']) - chartNumber(a[byEfficiency ? 'efficiency' : 'fee']));
}

export function ownerTable(rows: Row[], accountMode: boolean, byEfficiency = false): Table {
  return {
    headers: ['排名', accountMode ? '投流账号' : '负责人', accountMode ? '广告账户 ID' : '账户数',
      '消耗（元）', '转化数', '转化成本（元）', accountMode ? '开口留资率（%）' : '每千元转化数'],
    rows: rankOwners(rows, byEfficiency).map((row: Row, index) => [
      index + 1, row.owner_name || '未分配', accountMode ? row.account_id : row.account_count,
      chartNumber(row.fee), chartNumber(row.conversion), chartNumber(row.conversion_cost),
      accountMode ? chartNumber(row.opening_conversion_rate) : row.efficiency,
    ]),
  };
}

export function topNotesTable(notes: Record<string, Row>): Table {
  return {
    headers: ['排行维度', '笔记标题', '小红书账号', '笔记 ID', '转化数', '转化率（%）', '展现量', '私信进线', '私信开口', '综合分'],
    rows: Object.entries(notes).map(([key, note]) => [
      TOP_NOTE_LABELS[key] || key, note.note_title || '未命名笔记', note.xhs_account_name || '未知', note.note_id,
      chartNumber(note.conversion), chartNumber(note.conversion_rate), chartNumber(note.impression),
      chartNumber(note.message_consult), chartNumber(note.initiative_message ?? note.openings), chartNumber(note.score),
    ]),
  };
}

export function tagRows(points: Row[]) {
  return points.map((point) => ({
    tag: point.tag, conversion: point.y, conversion_cost: point.x, fee: point.size,
    click: point.click, interaction: point.interaction,
  }));
}

export function tagTable(rows: ReturnType<typeof tagRows>, primaryTag: string): Table {
  return {
    headers: [...(primaryTag ? ['一级标签', '二级标签'] : ['一级标签']), '转化数', '转化成本（元）', '消耗（元）', '点击量', '互动量'],
    rows: rows.map((row) => [
      ...(primaryTag ? [primaryTag] : []), row.tag, chartNumber(row.conversion), chartNumber(row.conversion_cost),
      chartNumber(row.fee), chartNumber(row.click), chartNumber(row.interaction),
    ]),
  };
}

export function funnelTable(rows: Row[]): Table {
  return {
    headers: ['阶段', '数量', '较上一阶段（%）', '较曝光（%）'],
    rows: rows.map((row, index) => [row.label, chartNumber(row.value), index === 0 ? 100 : chartNumber(row.step_rate), chartNumber(row.overall_rate)]),
  };
}

export function spendTrendTable(trend: Row[]): Table {
  return {
    headers: ['日期', '消耗（元）', '转化数', '转化成本（元）', '点击量', '曝光量'],
    rows: trend.map((row) => [row.date, chartNumber(row.fee), chartNumber(row.conversion), conversionCost(row), chartNumber(row.click), chartNumber(row.impression)]),
  };
}

export function selectedTrendMetrics(keys: string[]) {
  return keys.flatMap((key) => TREND_METRICS.filter((metric) => metric.key === key));
}

export function coreTrendTable(trend: Row[], keys: string[]): Table {
  const metrics = selectedTrendMetrics(keys);
  return {
    headers: ['日期', ...metrics.map(({ label }) => label)],
    rows: trend.map((row) => [row.date, ...metrics.map(({ key }) => chartNumber(row[key]))]),
  };
}

const COMPARISON_COLUMNS = [
  { name: '消耗', metric: 'fee', type: 'currency' },
  { name: '转化数', metric: 'conversion', type: 'integer' },
  { name: '转化成本', metric: 'conversion_cost', type: 'currency' },
  { name: '开口率', metric: 'opening_rate', type: 'percent' },
  { name: '开口成本', metric: 'opening_cost', type: 'currency' },
];

export function comparisonColumns(accountMode: boolean) {
  return accountMode ? COMPARISON_COLUMNS.slice(0, -1) : COMPARISON_COLUMNS;
}

export function comparisonRows<T extends Row>(rows: T[]) {
  return rows.filter((row) => String(row.owner_key || '').toLowerCase() !== 'unassigned'
    && !['unassigned', '未分配'].includes(String(row.owner_name || '').toLowerCase()));
}

export function comparisonTable(rows: Row[], accountMode: boolean): Table {
  const columns = comparisonColumns(accountMode);
  return {
    headers: [accountMode ? '投流账号' : '负责人', ...columns.flatMap(({ name, type }) => {
      const unit = type === 'percent' ? '（%）' : type === 'currency' ? '（元）' : '';
      return [`本期${name}${unit}`, `上期${name}${unit}`, `${name}环比差值${type === 'percent' ? '（百分点）' : unit}`];
    })],
    rows: comparisonRows(rows).map((row) => [row.owner_name || '未分配', ...columns.flatMap(({ metric }) => (
      ['current', 'previous', 'delta'].map((period) => chartNumber(row[`${metric}_${period}`]))
    ))]),
  };
}

function csvCell(value: unknown) {
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '';
  const text = typeof value === 'string' ? value : '';
  // Quoting alone does not stop spreadsheet editors from evaluating formulas.
  const safe = /^[=+\-@\uFF1D\uFF0B\uFF0D\uFF20]/u.test(text.trimStart()) || /^[\t\r\n]/u.test(text) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function serializeCsv({ headers, rows }: Table) {
  return `\uFEFF${[headers, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n')}\r\n`;
}

export function downloadFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename.replace(/[<>:"/\\|?*\x00-\x1F]/g, '_');
  document.body.append(link);
  try {
    link.click();
  } finally {
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export function downloadChartTable(title: string, range: Range, table: Table) {
  downloadFile(new Blob([serializeCsv(table)], { type: 'text/csv;charset=utf-8' }), `${title}_${range.start_date}_${range.end_date}.csv`);
}
