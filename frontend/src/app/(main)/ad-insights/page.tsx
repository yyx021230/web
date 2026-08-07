'use client';

import Script from 'next/script';
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import {
  BarChart3,
  Bot,
  CalendarDays,
  ChevronLeft,
  ChevronDown,
  Download,
  Filter,
  HelpCircle,
  Loader2,
  PieChart,
  Sparkles,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  exportXhsAdDashboardTable,
  getXhsAdDashboard,
  getXhsAdDashboardContentTags,
  type XHSAdDashboardResponse,
} from '@/services/xhsApi';
import { AccountMultiSelect } from '@/components/ui/account-multi-select';
import { toast } from '@/lib/toast';

declare global {
  interface Window {
    echarts?: {
      init: (element: HTMLElement, theme?: unknown, options?: Record<string, unknown>) => {
        setOption: (option: Record<string, unknown>, notMerge?: boolean) => void;
        dispatchAction?: (payload: Record<string, unknown>) => void;
        on: (eventName: string, handler: (params: any) => void) => void;
        off?: (eventName: string, handler?: (params: any) => void) => void;
        resize: () => void;
        dispose: () => void;
      };
    };
  }
}

type DateRange = { start: string; end: string };
type ContentTagData = Pick<XHSAdDashboardResponse, 'quadrant' | 'creative_tags' | 'top_notes' | 'note_rows' | 'content_tag_level' | 'content_tag_primary' | 'content_tag_children'>;
const DASHBOARD_REQUEST_DEBOUNCE_MS = 160;
const CONTENT_TAG_REQUEST_DEBOUNCE_MS = 520;

function professionalAccountKey(account: Record<string, any>): string {
  return [
    String(account.xhs_account_id || '').trim(),
    String(account.xhs_account_name || '').trim(),
    String(account.xhs_owner_name || '').trim(),
  ].join('\u001f');
}

const TREND_METRICS = [
  { key: 'conversion', label: '有效线索', color: '#166534' },
  { key: 'impression', label: '曝光', color: '#111827' },
  { key: 'click', label: '点击', color: '#2563eb' },
  { key: 'interaction', label: '互动', color: '#d97706' },
  { key: 'openings', label: '开口', color: '#be123c' },
] as const;

function isCanceledRequest(error: unknown): boolean {
  const err = error as { code?: string; name?: string; message?: string };
  return err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError' || err?.message === 'canceled';
}

const CARD_CLASS = 'border border-slate-100 bg-white shadow-[0_24px_70px_rgba(15,23,42,0.08)] ring-1 ring-slate-100';
const PANEL_CLASS = 'rounded-[28px] border border-slate-100 bg-white shadow-[0_18px_54px_rgba(15,23,42,0.07)] ring-1 ring-slate-100';
const CONTROL_CLASS = 'h-10 rounded-2xl border border-slate-200 bg-white text-sm shadow-[0_10px_24px_rgba(15,23,42,0.06)] outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-slate-100';

function dateKey(date: Date) {
  return date.toISOString().slice(0, 10);
}

function defaultStart() {
  const date = new Date();
  date.setDate(date.getDate() - 30);
  return dateKey(date);
}

function defaultEnd() {
  const date = new Date();
  date.setDate(date.getDate() - 1);
  return dateKey(date);
}

function num(value: unknown) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function fmt(value: unknown, type?: string) {
  const parsed = num(value);
  if (type === 'currency') {
    const digits = Math.abs(parsed) >= 100 ? 0 : 2;
    return `¥${parsed.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
  }
  if (type === 'percent') return `${parsed.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}%`;
  return Math.round(parsed).toLocaleString('zh-CN');
}

function compact(value: unknown) {
  const parsed = num(value);
  if (Math.abs(parsed) >= 10000) return `${(parsed / 10000).toFixed(1)}w`;
  return parsed.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
}

function formatDelta(value: unknown, type?: string) {
  const parsed = num(value);
  return `${parsed > 0 ? '+' : ''}${fmt(parsed, type)}`;
}

function axisFormatter(value: number) {
  if (Math.abs(value) >= 10000) return `${Number((value / 10000).toFixed(1))}万`;
  return Math.round(value).toLocaleString('zh-CN');
}

function kpiSparkValues(key: string, trend: Array<Record<string, any>>) {
  return trend.map((point) => {
    if (key === 'ctr') return num(point.impression) > 0 ? (num(point.click) / num(point.impression)) * 100 : 0;
    if (key === 'avg_click_cost') return num(point.click) > 0 ? num(point.fee) / num(point.click) : 0;
    if (key === 'interaction_rate') return num(point.click) > 0 ? (num(point.interaction) / num(point.click)) * 100 : 0;
    if (key === 'opening_cost') return num(point.openings) > 0 ? num(point.fee) / num(point.openings) : 0;
    if (key === 'conversion_rate') return num(point.click) > 0 ? (num(point.conversion) / num(point.click)) * 100 : 0;
    if (key === 'conversion_cost') return num(point.conversion) > 0 ? num(point.fee) / num(point.conversion) : 0;
    const fieldMap: Record<string, string> = {
      total_spend: 'fee',
      total_impression: 'impression',
      total_click: 'click',
      openings: 'openings',
      interaction: 'interaction',
      conversion: 'conversion',
    };
    return num(point[fieldMap[key] || 'fee']);
  });
}

function PanelTitle({ eyebrow, title, suffix, icon }: { eyebrow?: string; title: string; suffix?: string; icon?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div>
        {eyebrow ? <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-slate-400">{eyebrow}</div> : null}
        <h2 className="mt-1 text-[18px] font-semibold tracking-[-0.035em] text-slate-950">{title}</h2>
      </div>
      {suffix ? <span className="rounded-full bg-slate-50 px-3 py-1 text-xs font-bold text-slate-500 shadow-sm">{suffix}</span> : null}
      {icon ? <div className="grid h-9 w-9 place-items-center rounded-2xl border border-slate-100 bg-slate-50 text-slate-400">{icon}</div> : null}
    </div>
  );
}

function MiniSparkline({ id, values }: { id: string; values: number[] }) {
  const safeValues = values.length > 0 ? values : [0];
  const max = Math.max(1, ...safeValues);
  const step = safeValues.length <= 1 ? 144 : 144 / (safeValues.length - 1);
  const points = safeValues.map((value, index) => `${index * step},${56 - (value / max) * 42}`).join(' ');
  const safeId = id.replace(/[^a-zA-Z0-9_-]/g, '-');
  return (
    <svg viewBox="0 0 144 60" className="h-12 w-full overflow-visible">
      <defs>
        <linearGradient id={`ad-spark-${safeId}`} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#111827" />
          <stop offset="100%" stopColor="#166534" />
        </linearGradient>
      </defs>
      <polyline points={`0,60 ${points} 144,60`} fill="rgba(15,23,42,0.08)" stroke="none" />
      <polyline points={points} fill="none" stroke="#e2e8f0" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points={points} fill="none" stroke={`url(#ad-spark-${safeId})`} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DateRangePicker({ range, onChange }: { range: DateRange; onChange: (range: DateRange) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(range);

  useEffect(() => setDraft(range), [range]);

  return (
    <div className="relative z-50">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex h-10 min-w-[238px] items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white px-3.5 text-sm font-semibold text-slate-800 shadow-[0_12px_28px_rgba(15,23,42,0.08)] outline-none transition hover:border-slate-400"
      >
        <span>{range.start} 至 {range.end}</span>
        <ChevronDown className={cn('h-3.5 w-3.5 text-slate-400 transition', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute right-0 z-[80] mt-2 w-[330px] rounded-[26px] border border-slate-200 bg-white p-4 shadow-[0_24px_70px_rgba(15,23,42,0.14)] ring-1 ring-slate-100">
          <div className="flex items-center gap-2 text-xs font-bold text-slate-500">
            <CalendarDays className="h-4 w-4" />
            选择统计周期
          </div>
          <div className="mt-3 grid gap-3">
            <label className="grid gap-1.5 text-xs font-semibold text-slate-500">
              开始日期
              <input type="date" value={draft.start} onChange={(event) => setDraft((value) => ({ ...value, start: event.target.value }))} className={cn(CONTROL_CLASS, 'px-3')} />
            </label>
            <label className="grid gap-1.5 text-xs font-semibold text-slate-500">
              结束日期
              <input type="date" value={draft.end} onChange={(event) => setDraft((value) => ({ ...value, end: event.target.value }))} className={cn(CONTROL_CLASS, 'px-3')} />
            </label>
          </div>
          <div className="mt-4 flex items-center justify-between">
            <button type="button" onClick={() => setDraft({ start: defaultStart(), end: defaultEnd() })} className="text-xs font-bold text-slate-500 transition hover:text-slate-950">重置</button>
            <button
              type="button"
              onClick={() => {
                onChange(draft);
                setOpen(false);
              }}
              className="rounded-2xl bg-slate-950 px-4 py-2 text-xs font-bold text-white shadow-[0_12px_26px_rgba(15,23,42,0.22)] transition hover:bg-slate-800"
            >
              应用日期
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function DashboardRefreshOverlay({ active }: { active: boolean }) {
  if (!active) return null;

  return (
    <div className="absolute inset-0 z-[45] cursor-wait bg-white/34 backdrop-blur-[1px]" aria-live="polite" aria-busy="true">
      <div className="absolute inset-x-0 top-0 h-[3px] overflow-hidden bg-slate-100">
        <div className="h-full w-1/3 animate-pulse rounded-r-full bg-slate-950 shadow-[0_0_18px_rgba(15,23,42,0.34)]" />
      </div>
      <div className="sticky top-4 z-10 mx-auto mt-4 flex w-fit items-center gap-2 rounded-full border border-slate-200/80 bg-white/94 px-4 py-2 text-sm font-black text-slate-700 shadow-[0_16px_44px_rgba(15,23,42,0.14)] ring-1 ring-white/80">
        <Loader2 className="h-4 w-4 animate-spin text-slate-950" />
        正在刷新看板
        <span className="h-1 w-1 rounded-full bg-slate-300" />
        <span className="text-xs font-bold text-slate-400">旧数据已暂存，新数据返回后自动替换</span>
      </div>
    </div>
  );
}

function EchartPanel({
  ready,
  optionBuilder,
  className,
  onPointClick,
}: {
  ready: boolean;
  optionBuilder: (width: number) => Record<string, unknown>;
  className?: string;
  onPointClick?: (tag: string) => void;
}) {
  const chartRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ready || !chartRef.current || typeof window === 'undefined' || !window.echarts) return undefined;
    const chart = window.echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    const handleClick = (params: any) => {
      const tag = String(params?.value?.[5] || params?.data?.[5] || '').trim();
      if (tag) onPointClick?.(tag);
    };
    if (onPointClick) {
      chart.on('click', handleClick);
    }
    const render = () => {
      if (!chartRef.current) return;
      chart.dispatchAction?.({ type: 'hideTip' });
      chart.setOption(optionBuilder(chartRef.current.clientWidth || 760), true);
      chart.resize();
    };
    render();
    const resizeObserver = new ResizeObserver(render);
    resizeObserver.observe(chartRef.current);
    return () => {
      resizeObserver.disconnect();
      chart.off?.('click', handleClick);
      chart.dispatchAction?.({ type: 'hideTip' });
      chart.dispose();
    };
  }, [onPointClick, optionBuilder, ready]);

  return (
    <div className={cn('relative h-[320px]', className)}>
      {ready ? <div ref={chartRef} className="h-full w-full" /> : <div className="grid h-full place-items-center text-sm font-medium text-slate-500">正在加载图表...</div>}
    </div>
  );
}

function buildAdTrendOption(trend: Array<Record<string, any>>, metricKeys: string[], chartWidth = 760): Record<string, unknown> {
  const metrics = metricKeys
    .map((key) => TREND_METRICS.find((metric) => metric.key === key))
    .filter(Boolean) as Array<(typeof TREND_METRICS)[number]>;
  const isDense = trend.length > (chartWidth < 680 ? 10 : 14);
  return {
    animation: true,
    animationDuration: 1000,
    animationEasing: 'quarticOut',
    color: metrics.map((metric) => metric.color),
    grid: { left: 58, right: metrics.length > 1 ? 58 : 28, top: 52, bottom: isDense ? 30 : 40 },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 9,
      itemHeight: 9,
      icon: 'circle',
      itemGap: 16,
      textStyle: { color: '#334155', fontSize: 12, fontWeight: 900 },
      data: metrics.map((metric) => metric.label),
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(15,23,42,0.96)',
      borderWidth: 0,
      padding: [10, 12],
      textStyle: { color: '#f8fbff', fontSize: 12 },
      axisPointer: { type: 'line', lineStyle: { color: 'rgba(15,23,42,0.20)', width: 1.5 } },
      formatter(params: any[]) {
        const list = Array.isArray(params) ? params : [];
        const point = trend[list[0]?.dataIndex || 0];
        if (!point) return '';
        return [
          `<strong>${point.date}</strong> <span style="color:#cbd5e1">日趋势</span>`,
          ...metrics.map((metric) => `<span style="color:${metric.color}">●</span> ${metric.label} <b style="float:right;margin-left:18px">${fmt(point[metric.key])}</b>`),
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'category',
      data: trend.map((point) => String(point.date || '').slice(5)),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: 'rgba(15,23,42,0.12)' } },
      axisLabel: { color: '#64748b', fontSize: 11, fontWeight: 700, interval: isDense ? Math.ceil(trend.length / 6) : 0 },
    },
    yAxis: [
      {
        type: 'value',
        name: metrics[0]?.label || '',
        nameTextStyle: { color: '#64748b', fontWeight: 800, padding: [0, 0, 0, -26] },
        axisLabel: { color: '#64748b', fontSize: 11, formatter: (value: number) => axisFormatter(value) },
        splitLine: { lineStyle: { color: 'rgba(15,23,42,0.08)', type: 'dashed' } },
      },
      {
        type: 'value',
        name: metrics[1]?.label || '',
        nameTextStyle: { color: '#64748b', fontWeight: 800, padding: [0, -26, 0, 0] },
        axisLabel: { color: '#64748b', fontSize: 11, formatter: (value: number) => axisFormatter(value) },
        splitLine: { show: false },
      },
    ],
    series: metrics.map((metric, index) => ({
      name: metric.label,
      type: 'line',
      yAxisIndex: index,
      smooth: true,
      symbol: 'circle',
      symbolSize: 7,
      lineStyle: { width: 3, color: metric.color },
      itemStyle: { color: metric.color },
      areaStyle: index === 0 ? { color: `${metric.color}14` } : undefined,
      data: trend.map((point) => num(point[metric.key])),
    })),
  };
}

function buildSpendConversionTrendOption(trend: Array<Record<string, any>>, chartWidth = 760): Record<string, unknown> {
  const isDense = trend.length > 14;
  const plotWidth = Math.max(220, chartWidth - 108);
  const slotWidth = plotWidth / Math.max(1, trend.length);
  const barWidth = Math.round(Math.max(isDense ? 10 : 24, Math.min(isDense ? 28 : 56, slotWidth * (isDense ? 0.42 : 0.52))));
  return {
    animation: true,
    animationDuration: 1000,
    animationEasing: 'quarticOut',
    color: ['#111827', '#166534', '#2563eb'],
    grid: { left: 56, right: 52, top: 52, bottom: isDense ? 30 : 40 },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 9,
      itemHeight: 9,
      icon: 'circle',
      itemGap: 16,
      textStyle: { color: '#334155', fontSize: 12, fontWeight: 900 },
      data: ['消耗', '转化', '转化成本'],
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(15,23,42,0.96)',
      borderWidth: 0,
      padding: [10, 12],
      textStyle: { color: '#f8fbff', fontSize: 12 },
      axisPointer: { type: 'line', lineStyle: { color: 'rgba(15,23,42,0.20)', width: 1.5 } },
      formatter(params: any[]) {
        const list = Array.isArray(params) ? params : [];
        const point = trend[list[0]?.dataIndex || 0];
        if (!point) return '';
        return [
          `<strong>${point.date}</strong> <span style="color:#cbd5e1">日趋势</span>`,
          `<span style="color:#111827">●</span> 消耗 <b style="float:right;margin-left:18px">${fmt(point.fee, 'currency')}</b>`,
          `<span style="color:#166534">●</span> 转化 <b style="float:right;margin-left:18px">${fmt(point.conversion)}</b>`,
          `<span style="color:#2563eb">●</span> 转化成本 <b style="float:right;margin-left:18px">${fmt(num(point.conversion) > 0 ? num(point.fee) / num(point.conversion) : 0, 'currency')}</b>`,
          `<span style="color:#94a3b8">●</span> 点击 <b style="float:right;margin-left:18px">${fmt(point.click)}</b>`,
          `<span style="color:#cbd5e1">●</span> 曝光 <b style="float:right;margin-left:18px">${fmt(point.impression)}</b>`,
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'category',
      data: trend.map((point) => String(point.date || '').slice(5)),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: 'rgba(15,23,42,0.12)' } },
      axisLabel: { color: '#64748b', fontSize: 11, fontWeight: 700, interval: isDense ? Math.ceil(trend.length / 6) : 0 },
    },
    yAxis: [
      {
        type: 'value',
        name: '消耗',
        nameTextStyle: { color: '#64748b', fontWeight: 800, padding: [0, 0, 0, -26] },
        axisLabel: { color: '#64748b', fontSize: 11, formatter: (value: number) => axisFormatter(value) },
        splitLine: { lineStyle: { color: 'rgba(15,23,42,0.08)', type: 'dashed' } },
      },
      {
        type: 'value',
        name: '转化',
        nameTextStyle: { color: '#64748b', fontWeight: 800, padding: [0, -26, 0, 0] },
        axisLabel: { color: '#64748b', fontSize: 11, formatter: (value: number) => axisFormatter(value) },
        splitLine: { show: false },
      },
    ],
    series: [
      { name: '消耗', type: 'bar', barWidth, data: trend.map((point) => num(point.fee)), itemStyle: { color: '#111827', borderRadius: [8, 8, 3, 3] }, emphasis: { itemStyle: { color: '#020617' } } },
      { name: '转化', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'circle', symbolSize: 7, lineStyle: { width: 3, color: '#166534' }, itemStyle: { color: '#166534' }, areaStyle: { color: 'rgba(22,101,52,0.08)' }, data: trend.map((point) => num(point.conversion)) },
      { name: '转化成本', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'circle', symbolSize: 6, lineStyle: { width: 2.5, color: '#2563eb', type: 'dashed' }, itemStyle: { color: '#2563eb' }, data: trend.map((point) => num(point.conversion) > 0 ? num(point.fee) / num(point.conversion) : 0) },
    ],
  };
}

function buildOwnerPerformanceOption(rows: Array<Record<string, any>>, chartWidth = 760, accountMode = false): Record<string, unknown> {
  const items = [...rows].sort((a, b) => num(b.fee) - num(a.fee)).slice(0, chartWidth < 680 ? 8 : 14).reverse();
  return {
    animation: true,
    grid: { left: 92, right: 48, top: 48, bottom: 28 },
    legend: { top: 0, right: 0, itemWidth: 9, itemHeight: 9, icon: 'circle', textStyle: { color: '#334155', fontSize: 12, fontWeight: 900 }, data: ['消耗', '转化'] },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(15,23,42,0.96)',
      borderWidth: 0,
      textStyle: { color: '#f8fbff', fontSize: 12 },
      formatter(params: any[]) {
        const item = items[params?.[0]?.dataIndex || 0];
        if (!item) return '';
        return [
          `<strong>${item.owner_name || '未分配'}</strong>`,
          `消耗 <b style="float:right;margin-left:18px">${fmt(item.fee, 'currency')}</b>`,
          `转化 <b style="float:right;margin-left:18px">${fmt(item.conversion)}</b>`,
          `CPA <b style="float:right;margin-left:18px">${fmt(item.conversion_cost, 'currency')}</b>`,
          accountMode
            ? `开口留资率 <b style="float:right;margin-left:18px">${fmt(item.opening_conversion_rate, 'percent')}</b>`
            : `账户 <b style="float:right;margin-left:18px">${fmt(item.account_count)}</b>`,
        ].join('<br/>');
      },
    },
    xAxis: [
      { type: 'value', axisLabel: { color: '#64748b', formatter: (value: number) => axisFormatter(value) }, splitLine: { lineStyle: { color: 'rgba(15,23,42,0.08)', type: 'dashed' } } },
      { type: 'value', axisLabel: { show: false }, splitLine: { show: false } },
    ],
    yAxis: { type: 'category', data: items.map((item) => item.owner_name || '未分配'), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: '#334155', fontWeight: 800, width: 78, overflow: 'truncate' } },
    series: [
      { name: '消耗', type: 'bar', data: items.map((item) => num(item.fee)), barWidth: 14, itemStyle: { color: '#111827', borderRadius: [0, 8, 8, 0] } },
      { name: '转化', type: 'line', xAxisIndex: 1, data: items.map((item) => num(item.conversion)), smooth: true, symbol: 'circle', symbolSize: 7, lineStyle: { color: '#166534', width: 3 }, itemStyle: { color: '#166534' } },
    ],
  };
}

function buildQuadrantOption(data: XHSAdDashboardResponse['quadrant']): Record<string, unknown> {
  const points = data.points || [];
  const niceMax = (value: number) => {
    if (!Number.isFinite(value) || value <= 0) return 1;
    const exponent = Math.floor(Math.log10(value));
    const base = Math.pow(10, exponent);
    return Math.ceil(value / base) * base;
  };
  const costs = points.map((item) => num(item.x)).filter((value) => value > 0);
  const conversions = points.map((item) => num(item.y)).filter((value) => value > 0);
  const minConversion = Math.max(1, Math.min(...conversions, 1));
  const maxConversion = Math.max(1, ...conversions);
  const useLogConversionAxis = maxConversion / minConversion >= 25;
  const yMin = useLogConversionAxis ? 1 : 0;
  const avgCost = num(data.avg_x) > 0
    ? num(data.avg_x)
    : (costs.length ? costs.reduce((sum, value) => sum + value, 0) / costs.length : 0);
  const avgConversion = num(data.avg_y) > 0
    ? num(data.avg_y)
    : (conversions.length ? conversions.reduce((sum, value) => sum + value, 0) / conversions.length : 0);
  const costMax = niceMax(Math.max(1, avgCost, ...costs) * 1.12);
  const conversionMax = niceMax(Math.max(1, avgConversion, maxConversion) * 1.18);
  const maxSpend = Math.max(1, ...points.map((item) => num(item.size)));
  const currencyTick = (value: number) => `¥${Math.round(value).toLocaleString('zh-CN')}`;
  const pointColor = (item: Record<string, any> | undefined) => {
    if (!item) return '#64748b';
    const lowCost = num(item.x) <= avgCost;
    const highConversion = num(item.y) >= avgConversion;
    if (lowCost && highConversion) return '#047857';
    if (!lowCost && highConversion) return '#2563eb';
    if (lowCost && !highConversion) return '#d97706';
    return '#94a3b8';
  };
  return {
    animation: true,
    animationDuration: 520,
    animationEasing: 'quarticOut',
    grid: { left: 38, right: 24, top: 30, bottom: 34, containLabel: true },
    tooltip: {
      show: true,
      trigger: 'item',
      renderMode: 'richText',
      confine: true,
      transitionDuration: 0.12,
      backgroundColor: 'rgba(15,23,42,0.96)',
      borderWidth: 0,
      padding: [10, 12],
      textStyle: { color: '#f8fbff', fontSize: 12, lineHeight: 20 },
      formatter(params: any) {
        const value = params.value || [];
        const label = String(value[5] || '未标记');
        return [
          `{title|${label}}`,
          `转化成本  ${fmt(value[0], 'currency')}`,
          `转化量    ${fmt(value[1])}`,
          `消耗      ${fmt(value[2], 'currency')}`,
          `点击      ${fmt(points[params.dataIndex]?.click || 0)}`,
          `互动      ${fmt(points[params.dataIndex]?.interaction || 0)}`,
        ].join('\n');
      },
      rich: {
        title: {
          fontSize: 13,
          fontWeight: 900,
          color: '#ffffff',
          padding: [0, 0, 4, 0],
        },
      },
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: costMax,
      inverse: true,
      axisLine: { lineStyle: { color: 'rgba(15,23,42,0.16)' } },
      axisTick: { show: false },
      axisLabel: { color: '#64748b', fontSize: 11, fontWeight: 700, formatter: (value: number) => currencyTick(value) },
      splitLine: { lineStyle: { color: 'rgba(15,23,42,0.05)' } },
    },
    yAxis: {
      type: useLogConversionAxis ? 'log' : 'value',
      logBase: 10,
      min: yMin,
      max: conversionMax,
      axisLine: { lineStyle: { color: 'rgba(15,23,42,0.16)' } },
      axisTick: { show: false },
      axisLabel: { color: '#64748b', fontSize: 11, fontWeight: 700, formatter: (value: number) => compact(value) },
      minorSplitLine: useLogConversionAxis ? { show: true, lineStyle: { color: 'rgba(15,23,42,0.025)' } } : undefined,
      splitLine: { lineStyle: { color: 'rgba(15,23,42,0.05)' } },
    },
    graphic: [
      {
        type: 'text',
        left: 42,
        top: 8,
        silent: true,
        style: {
          text: '转化量',
          fill: '#475569',
          fontSize: 12,
          fontWeight: 900,
        },
      },
      {
        type: 'text',
        left: 'center',
        bottom: 18,
        silent: true,
        style: {
          text: '转化成本',
          fill: '#475569',
          fontSize: 12,
          fontWeight: 900,
        },
      },
    ],
    series: [{
      type: 'scatter',
      symbolSize(value: number[]) { return 14 + Math.sqrt(num(value[2]) / maxSpend) * 34; },
      label: {
        show: true,
        position: 'top',
        distance: 10,
        formatter(params: any) {
          const label = String(params.value?.[5] || '');
          return label.length > 8 ? `${label.slice(0, 8)}…` : label;
        },
        color: '#0f172a',
        fontSize: 12,
        fontWeight: 900,
        width: 86,
        overflow: 'truncate',
        backgroundColor: 'rgba(255,255,255,0.92)',
        borderColor: 'rgba(203,213,225,0.9)',
        borderWidth: 1,
        borderRadius: 8,
        padding: [4, 7],
      },
      labelLayout(params: any) {
        const point = points[params.dataIndex];
        const cost = num(point?.x);
        const conversion = num(point?.y);
        return {
          align: cost > avgCost ? 'right' : 'left',
          verticalAlign: conversion > avgConversion ? 'bottom' : 'top',
          dx: cost > avgCost ? -12 : 12,
          dy: conversion > avgConversion ? -12 : 12,
          hideOverlap: false,
          moveOverlap: 'shiftY',
        };
      },
      itemStyle: {
        color(params: any) {
          const point = points[params.dataIndex];
          return pointColor(point);
        },
        borderColor: 'rgba(255,255,255,0.92)',
        borderWidth: 1.5,
        opacity: 0.82,
        shadowBlur: 6,
        shadowColor: 'rgba(15,23,42,0.10)',
      },
      emphasis: {
        focus: 'self',
        scale: 1.22,
        label: {
          show: true,
          formatter(params: any) {
            const label = String(params.value?.[5] || '');
            return label.length > 10 ? `${label.slice(0, 10)}…` : label;
          },
          color: '#0f172a',
          fontSize: 13,
          fontWeight: 900,
          backgroundColor: 'rgba(255,255,255,0.96)',
          borderColor: 'rgba(15,23,42,0.16)',
          borderWidth: 1,
          shadowBlur: 12,
          shadowColor: 'rgba(15,23,42,0.16)',
        },
        itemStyle: {
          borderColor: '#ffffff',
          borderWidth: 3,
          opacity: 1,
          shadowBlur: 18,
          shadowColor: 'rgba(15,23,42,0.22)',
        },
      },
      data: points.map((item) => [num(item.x), num(item.y), num(item.size), num(item.x), num(item.y), item.tag]),
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: 'rgba(15,23,42,0.18)', type: 'dashed' },
        label: { color: '#94a3b8', fontSize: 10, fontWeight: 800 },
        data: [
          { name: '平均成本', xAxis: avgCost, label: { formatter: `平均成本 ${currencyTick(avgCost)}` } },
          { name: '平均转化', yAxis: Math.max(yMin, avgConversion), label: { formatter: `平均转化 ${compact(avgConversion)}` } },
        ],
      },
    }],
  };
}

function OwnerRankingPanel({ rows, notes, notesLoading = false, accountMode = false }: { rows: Array<Record<string, any>>; notes: Record<string, Record<string, any>>; notesLoading?: boolean; accountMode?: boolean }) {
  const displayRows: Array<Record<string, any>> = accountMode
    ? [...rows].sort((a, b) => num(b.fee) - num(a.fee))
    : [...rows]
      .map((row) => ({ ...row, efficiency: num(row.fee) > 0 ? (num(row.conversion) / num(row.fee)) * 1000 : 0 }))
      .sort((a, b) => num(b.efficiency) - num(a.efficiency))
      .slice(0, 8);
  const maxPrimaryMetric = Math.max(1, ...displayRows.map((row) => accountMode ? num(row.fee) : num(row.efficiency)));
  const renderRows = (items: Array<Record<string, any>>) => (
    <div className="space-y-2">
      {items.map((row, index) => {
        const width = Math.max(8, ((accountMode ? num(row.fee) : num(row.efficiency)) / maxPrimaryMetric) * 100);
        return (
          <div key={`efficiency-${row.owner_key || row.owner_name || index}`} className="group grid grid-cols-[30px_minmax(0,1fr)_92px] items-center gap-2 rounded-2xl border border-slate-100 bg-white px-2.5 py-2 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-200 hover:shadow-md">
            <div className={cn('grid h-7 w-7 place-items-center rounded-xl text-[11px] font-bold shadow-sm', index === 0 ? 'bg-slate-950 text-white' : 'bg-white text-slate-500')}>{index + 1}</div>
            <div className="min-w-0">
              <div className="mb-1.5 flex items-center justify-between gap-2"><span className="truncate text-xs font-bold text-slate-800">{row.owner_name || '未分配'}</span><span className="shrink-0 text-[10px] font-bold text-slate-500">{accountMode ? '投流账号' : `${row.account_count || 0} 账户`}</span></div>
              <div className="h-2.5 overflow-hidden rounded-full bg-slate-100 shadow-inner"><div className={cn('h-full rounded-full ring-1 ring-inset ring-white/60', index === 0 ? 'bg-slate-950' : index === 1 ? 'bg-emerald-800' : 'bg-slate-200')} style={{ width: `${width}%` }} /></div>
              <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] font-semibold text-slate-500">
                <span>消耗 {fmt(row.fee, 'currency')}</span>
                <span>转化 {fmt(row.conversion)}</span>
                <span>CPA {fmt(row.conversion_cost, 'currency')}</span>
                {accountMode ? <span>开口留资率 {fmt(row.opening_conversion_rate, 'percent')}</span> : null}
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm font-semibold tracking-tight text-slate-950">{accountMode ? fmt(row.opening_conversion_rate, 'percent') : num(row.efficiency).toFixed(1)}</div>
              <div className="text-[10px] font-semibold text-slate-500">{accountMode ? '留资率' : '转化/千元'}</div>
              <div className="text-[10px] font-semibold text-slate-400">{accountMode ? '开口留资' : '效率'}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
  if (!rows.length) return <div className="grid h-[300px] place-items-center text-sm font-medium text-slate-500">当前范围暂无负责人数据</div>;
  return (
    <div className="grid h-full min-h-0 gap-4 overflow-hidden px-3 pb-3 pt-1 lg:grid-cols-2">
      <div className="flex min-h-0 flex-col overflow-hidden">
        <div className="mb-1.5 flex shrink-0 items-center justify-between px-1 text-[11px] font-bold text-slate-400"><span>{accountMode ? '投流账号排行' : '转化:消耗排行'}</span><span>{accountMode ? '柱长=消耗' : '柱长=每千元转化'}</span></div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1">{renderRows(displayRows)}</div>
      </div>
      <div className="flex min-h-0 flex-col overflow-hidden border-l border-slate-200 pl-4">
        <div className="mb-0.5 flex shrink-0 items-center justify-between px-1 text-[11px] font-bold text-slate-400"><span>笔记排行</span><span>TOP 维度</span></div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1"><TopNotesBoard notes={notes} loading={notesLoading} /></div>
      </div>
    </div>
  );
}

function TopNotesBoard({ notes, loading = false }: { notes: Record<string, Record<string, any>>; loading?: boolean }) {
  const rows = Object.entries(notes || {});
  const maxScore = Math.max(1, ...rows.map(([, note]) => num(note.score)));
  const labelMap: Record<string, string> = { conversion: '转化最高笔记', conversion_rate: '转化率最高笔记', impression: '展现最高笔记', message_consult: '私信进线最高', initiative_message: '私信开口最高' };
  if (loading && !rows.length) return <div className="grid h-[220px] place-items-center text-sm font-medium text-slate-500"><span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />笔记样本加载中...</span></div>;
  if (!rows.length) return <div className="grid h-[220px] place-items-center text-sm font-medium text-slate-500">当前范围暂无笔记样本</div>;
  return (
    <div className="mt-2 grid gap-3">
      {rows.map(([key, note], index) => {
        const width = Math.max(10, (num(note.score) / maxScore) * 100);
        const isHero = index === 0;
        return (
          <div key={key} className={cn('group relative overflow-hidden rounded-[22px] border p-3 transition hover:-translate-y-0.5', isHero ? 'border-slate-800 bg-slate-950 text-white shadow-[0_18px_36px_rgba(15,23,42,0.22)]' : 'border-slate-100 bg-white text-slate-900 shadow-sm hover:border-slate-200 hover:shadow-md')}>
            <div className="flex items-start gap-3">
              <div className={cn('grid h-8 w-8 shrink-0 place-items-center rounded-xl text-xs font-black shadow-sm', isHero ? 'bg-white text-slate-950' : 'bg-slate-950 text-white')}>{index + 1}</div>
              <div className="min-w-0 flex-1">
                <div className={cn('text-[11px] font-bold uppercase tracking-[0.16em]', isHero ? 'text-emerald-300' : 'text-slate-400')}>{labelMap[key] || key}</div>
                <div className={cn('mt-1 line-clamp-2 text-sm font-semibold leading-snug', isHero ? 'text-white' : 'text-slate-950')}>{note.note_title || '未命名笔记'}</div>
                <div className={cn('mt-1 text-[11px] font-semibold', isHero ? 'text-slate-300' : 'text-slate-500')}>
                  小红书账号：<span className={cn(isHero ? 'text-white' : 'text-slate-700')}>{String(note.xhs_account_name || '未知')}</span>
                </div>
                <div className={cn('mt-2 h-1.5 overflow-hidden rounded-full', isHero ? 'bg-white/16' : 'bg-slate-100')}><div className={cn('h-full rounded-full', isHero ? 'bg-emerald-400' : 'bg-slate-950')} style={{ width: `${width}%` }} /></div>
                <div className="mt-3 grid grid-cols-3 gap-1 text-center sm:grid-cols-5">
                  {[
                    ['转化', compact(note.conversion)],
                    ['转化率', `${num(note.conversion_rate).toFixed(2)}%`],
                    ['展现', compact(note.impression)],
                    ['进线', compact(note.message_consult)],
                    ['开口', compact(note.initiative_message ?? note.openings)],
                  ].map(([label, value]) => <div key={label} className={cn('rounded-xl px-1.5 py-1', isHero ? 'bg-white/10' : 'bg-slate-50')}><div className={cn('text-[10px] font-semibold', isHero ? 'text-slate-300' : 'text-slate-500')}>{label}</div><div className={cn('mt-0.5 truncate text-xs font-black', isHero ? 'text-white' : 'text-slate-950')}>{value}</div></div>)}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CreativeTagList({
  rows,
  mode = 'primary',
  onSelectPrimary,
}: {
  rows: Array<Record<string, any>>;
  mode?: 'primary' | 'secondary';
  onSelectPrimary?: (tag: string) => void;
}) {
  if (!rows.length) return <div className="grid h-full place-items-center text-sm font-medium text-slate-500">当前范围暂无内容标签数据</div>;
  return (
    <div className="flex min-h-0 h-full flex-col overflow-hidden">
      <div className="grid shrink-0 grid-cols-[1.2fr_0.72fr_0.82fr_0.82fr_0.82fr_0.82fr] border-b border-slate-200 px-2 py-1.5 text-[10px] font-black uppercase tracking-[0.08em] text-slate-500">
        <span>{mode === 'primary' ? '一级标签' : '二级标签'}</span>
        <span className="text-right">转化</span>
        <span className="text-right">成本</span>
        <span className="text-right">消耗</span>
        <span className="text-right">点击</span>
        <span className="text-right">互动</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {rows.map((item, index) => {
          const clickable = mode === 'primary' && !!onSelectPrimary;
          const rowClassName = cn(
            'grid w-full grid-cols-[1.2fr_0.72fr_0.82fr_0.82fr_0.82fr_0.82fr] items-center border-b border-slate-100 px-2 py-1.5 text-[11px] font-semibold text-slate-700 last:border-b-0 odd:bg-slate-50/40',
            clickable ? 'transition hover:bg-slate-50' : '',
          );
          const content = (
            <>
              <span className="flex min-w-0 items-center gap-2">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: index === 0 ? '#111827' : index === 1 ? '#166534' : '#cbd5e1' }} />
                <span className="truncate">{item.tag}</span>
              </span>
              <span className="text-right text-slate-950">{fmt(item.conversion)}</span>
              <span className="text-right">{fmt(item.conversion_cost, 'currency')}</span>
              <span className="text-right">{fmt(item.fee, 'currency')}</span>
              <span className="text-right">{fmt(item.click)}</span>
              <span className="text-right">{fmt(item.interaction)}</span>
            </>
          );
          if (!clickable) {
            return <div key={item.tag || index} className={rowClassName}>{content}</div>;
          }
          return (
            <button
              key={item.tag || index}
              type="button"
              onClick={() => onSelectPrimary?.(String(item.tag || ''))}
              className={cn(rowClassName, 'text-left')}
              title="查看该一级标签下的二级标签"
            >
              {content}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function FunnelPanel({ rows }: { rows: Array<Record<string, any>> }) {
  if (!rows.length) return <div className="grid h-[220px] place-items-center text-sm font-medium text-slate-500">当前范围暂无漏斗数据</div>;
  return (
    <div className="mt-4 max-h-[430px] space-y-2.5 overflow-y-auto pr-1">
      {rows.map((item, index) => {
        const width = index === 0
          ? 100
          : Math.max(4, Math.min(100, num(item.step_rate)));
        const isLast = index === rows.length - 1;
        const rateLabel = index === 0 ? '基准 100%' : `上一步 ${num(item.step_rate).toFixed(2)}%`;
        return (
          <div key={item.label}>
            <div className="rounded-[20px] border border-slate-100 bg-white px-3 py-2.5 shadow-sm">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className={cn('grid h-6 w-6 place-items-center rounded-xl text-[10px] font-black', index === 0 ? 'bg-slate-950 text-white' : 'bg-slate-100 text-slate-500')}>{index + 1}</span>
                  <span className="text-xs font-black text-slate-800">{item.label}</span>
                </div>
                <div className="text-right">
                  <div className="text-sm font-black tabular-nums text-slate-950">{compact(item.value)}</div>
                  <div className="text-[10px] font-bold text-slate-400">{rateLabel}</div>
                </div>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-slate-100 shadow-inner">
                <div className={cn('h-full rounded-full', isLast ? 'bg-emerald-700' : 'bg-slate-950')} style={{ width: `${width}%` }} />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ComparisonList({ rows, accountMode = false }: { rows: Array<Record<string, any>>; accountMode?: boolean }) {
  const visibleRows = rows.filter((row) => {
    const ownerKey = String(row.owner_key || '').toLowerCase();
    const ownerName = String(row.owner_name || '').toLowerCase();
    return ownerKey !== 'unassigned' && ownerName !== 'unassigned' && ownerName !== '未分配';
  });
  const columns: Array<{ label: string; metric: string; type: string }> = accountMode ? [
    { label: '消耗环比', metric: 'fee', type: 'currency' },
    { label: '转化数环比', metric: 'conversion', type: 'integer' },
    { label: '转化成本环比', metric: 'conversion_cost', type: 'currency' },
    { label: '开口率环比', metric: 'opening_rate', type: 'percent' },
  ] : [
    { label: '消耗环比', metric: 'fee', type: 'currency' },
    { label: '转化数环比', metric: 'conversion', type: 'integer' },
    { label: '转化成本环比', metric: 'conversion_cost', type: 'currency' },
    { label: '开口率环比', metric: 'opening_rate', type: 'percent' },
    { label: '开口成本环比', metric: 'opening_cost', type: 'currency' },
];
  const renderMetricCell = (row: Record<string, any>, metric: string, type: string) => {
    const deltaKey = `${metric}_delta`;
    const currentKey = `${metric}_current`;
    const previousKey = `${metric}_previous`;
    const delta = num(row[deltaKey]);
    const currentValue = row[currentKey];
    const previousValue = row[previousKey];
    const favorable = metric.includes('cost') || metric === 'fee' ? delta <= 0 : delta >= 0;
    return (
      <div className="space-y-1.5">
        <span className={cn(
          'inline-flex max-w-full justify-center rounded-full px-2 py-1 text-[11px] font-black tabular-nums',
          favorable ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-600',
        )}>
          {formatDelta(delta, type)}
        </span>
        <div className="space-y-0.5 text-[10px] font-semibold leading-4 text-slate-500 break-words">
          <div>本期 {fmt(currentValue, type)}</div>
          <div>上期 {fmt(previousValue, type)}</div>
        </div>
      </div>
    );
  };
  return (
    <div className="mt-4 overflow-hidden rounded-[24px] border border-slate-100 bg-white shadow-sm">
      <div className="max-h-[360px] overflow-y-auto overflow-x-hidden">
        <table className="w-full table-fixed text-sm">
          <colgroup>
            <col style={{ width: accountMode ? '16%' : '14%' }} />
            {columns.map((column) => (
              <col key={column.metric} style={{ width: `${84 / columns.length}%` }} />
            ))}
          </colgroup>
          <thead className="sticky top-0 z-10 bg-slate-50/95 text-xs text-slate-400 backdrop-blur">
            <tr>
              <th className="px-3 py-3 text-left font-black">{accountMode ? '投流账号' : '负责人'}</th>
              {columns.map((column) => <th key={column.label} className="px-3 py-3 text-left font-black leading-4">{column.label}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {visibleRows.length === 0 ? (
              <tr><td colSpan={columns.length + 1} className="px-4 py-12 text-center text-slate-400">暂无环比数据</td></tr>
            ) : visibleRows.map((row) => (
              <tr key={row.owner_key} className="transition hover:bg-slate-50/70">
                <td className="px-3 py-3 align-top text-xs font-black leading-5 text-slate-900 break-words">{row.owner_name || '未分配'}</td>
                {columns.map((column) => (
                  <td key={column.metric} className="px-3 py-3 align-top text-slate-600">{renderMetricCell(row, column.metric, column.type)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DataTable({ title, eyebrow, rows, columns, onExport }: { title: string; eyebrow: string; rows: Array<Record<string, any>>; columns: Array<[string, string]>; onExport: () => void }) {
  const [sortKey, setSortKey] = useState<string>('');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows;
    const getSortableValue = (value: unknown) => {
      if (Array.isArray(value)) return value.join('、');
      if (typeof value === 'number') return value;
      const text = String(value ?? '').trim();
      if (!text) return '';
      const numericText = text.replace(/[%¥,\s]/g, '');
      const numericValue = Number(numericText);
      return Number.isFinite(numericValue) && numericText !== '' ? numericValue : text.toLowerCase();
    };
    return [...rows].sort((left, right) => {
      const leftValue = getSortableValue(left[sortKey]);
      const rightValue = getSortableValue(right[sortKey]);
      if (typeof leftValue === 'number' && typeof rightValue === 'number') {
        return sortDirection === 'asc' ? leftValue - rightValue : rightValue - leftValue;
      }
      return sortDirection === 'asc'
        ? String(leftValue).localeCompare(String(rightValue), 'zh-CN')
        : String(rightValue).localeCompare(String(leftValue), 'zh-CN');
    });
  }, [rows, sortDirection, sortKey]);

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDirection((current) => current === 'desc' ? 'asc' : 'desc');
      return;
    }
    const sample = rows.find((row) => row[key] !== null && row[key] !== undefined && row[key] !== '');
    const firstValue = sample?.[key];
    const defaultDirection = typeof firstValue === 'number' ? 'desc' : 'asc';
    setSortKey(key);
    setSortDirection(defaultDirection);
  };

  return (
    <div className={`${PANEL_CLASS} overflow-hidden`}>
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4"><PanelTitle eyebrow={eyebrow} title={title} /><button onClick={onExport} className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 shadow-[0_10px_24px_rgba(15,23,42,0.04)] hover:bg-slate-50"><Download className="h-4 w-4" />导出表格</button></div>
      <div className="max-h-[460px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-slate-50 text-xs text-slate-400">
            <tr>
              {columns.map(([label, key]) => {
                const active = sortKey === key;
                return (
                  <th key={label} className="px-4 py-3 text-left font-bold">
                    <button
                      type="button"
                      onClick={() => toggleSort(key)}
                      className={cn('inline-flex items-center gap-1.5 transition', active ? 'text-slate-900' : 'text-slate-500 hover:text-slate-900')}
                    >
                      <span>{label}</span>
                      <ChevronDown className={cn('h-3.5 w-3.5 transition', active && sortDirection === 'asc' ? 'rotate-180' : '')} />
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {sortedRows.length === 0 ? <tr><td colSpan={columns.length} className="px-4 py-12 text-center text-slate-400">暂无数据</td></tr> : sortedRows.map((row, index) => <tr key={`${row.note_id || row.brand || index}`} className="hover:bg-slate-50/70">{columns.map(([label, key]) => {
              const value = row[key];
              const displayValue = Array.isArray(value) ? value.join('、') : key === 'ctr' || key.endsWith('_rate') ? `${value}%` : typeof value === 'number' ? compact(value) : String(value || '-');
              return <td key={key} className={cn('px-4 py-3', label.includes('笔记') ? 'max-w-[260px] truncate font-semibold text-slate-900' : 'text-slate-600')}>{displayValue}</td>;
            })}</tr>)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function XhsAdInsightsPage() {
  const [range, setRange] = useState<DateRange>(() => ({ start: defaultStart(), end: defaultEnd() }));
  const [selectedAccountIds, setSelectedAccountIds] = useState<string[]>([]);
  const [selectedXhsAccountIds, setSelectedXhsAccountIds] = useState<string[]>([]);
  const [buyerUserId, setBuyerUserId] = useState('');
  const [data, setData] = useState<XHSAdDashboardResponse | null>(null);
  const [primaryContentTags, setPrimaryContentTags] = useState<ContentTagData | null>(null);
  const [loading, setLoading] = useState(true);
  const [contentLoading, setContentLoading] = useState(false);
  const [contentError, setContentError] = useState('');
  const [selectedPrimaryTag, setSelectedPrimaryTag] = useState('');
  const [loadError, setLoadError] = useState('');
  const [showAi, setShowAi] = useState(false);
  const [echartsReady, setEchartsReady] = useState(false);
  const [trendMetricKeys, setTrendMetricKeys] = useState<string[]>(['conversion', 'impression']);
  const contentTagRequestSeq = useRef(0);

  const selectedProfessionalAccountIds = useMemo(() => {
    if (!selectedXhsAccountIds.length) return [];
    const selectedSet = new Set(selectedXhsAccountIds);
    const selectedBuyerId = buyerUserId ? Number(buyerUserId) : null;
    return (data?.filters.accounts || [])
      .filter((account) => {
        if (selectedBuyerId && Number(account.buyer_user_id || 0) !== selectedBuyerId) return false;
        return selectedSet.has(professionalAccountKey(account));
      })
      .map((account) => account.account_id);
  }, [buyerUserId, data?.filters.accounts, selectedXhsAccountIds]);

  const selectedAccountIdKey = selectedAccountIds.join('\u001f');
  const selectedProfessionalAccountIdKey = selectedProfessionalAccountIds.join('\u001f');

  const params = useMemo(() => ({
    start_date: range.start,
    end_date: range.end,
    report_type: 'all' as const,
    account_ids: selectedAccountIds.length
      ? selectedAccountIds
      : selectedProfessionalAccountIds.length
        ? selectedProfessionalAccountIds
        : undefined,
    buyer_user_id: buyerUserId ? Number(buyerUserId) : undefined,
  }), [buyerUserId, range.end, range.start, selectedAccountIdKey, selectedProfessionalAccountIdKey]);
  const isBuyerScoped = Boolean(buyerUserId);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const requestSeq = contentTagRequestSeq.current + 1;
    contentTagRequestSeq.current = requestSeq;
    setLoading(true);
    setContentLoading(true);
    setSelectedPrimaryTag('');
    setPrimaryContentTags(null);
    setContentError('');
    setLoadError('');

    const dashboardTimer = window.setTimeout(() => {
      getXhsAdDashboard({ ...params, include_content_tags: false, signal: controller.signal })
        .then((nextData) => {
          if (!cancelled && contentTagRequestSeq.current === requestSeq) {
            setData(nextData);
          }
        })
        .catch((error) => {
          if (isCanceledRequest(error)) return;
          const message = error instanceof Error ? error.message : '投流看板加载失败';
          if (!cancelled && contentTagRequestSeq.current === requestSeq) {
            setLoadError(message);
          }
          toast.error(message);
        })
        .finally(() => {
          if (!cancelled && contentTagRequestSeq.current === requestSeq) {
            setLoading(false);
          }
        });
    }, DASHBOARD_REQUEST_DEBOUNCE_MS);

    const contentTimer = window.setTimeout(() => {
      getXhsAdDashboardContentTags({ ...params, signal: controller.signal })
        .then((contentData) => {
          if (!cancelled && contentTagRequestSeq.current === requestSeq) {
            setPrimaryContentTags(contentData);
            setData((current) => current ? { ...current, ...contentData } : current);
          }
        })
        .catch((error) => {
          if (isCanceledRequest(error)) return;
          const message = error instanceof Error ? error.message : '内容标签加载失败';
          if (!cancelled && contentTagRequestSeq.current === requestSeq) {
            setContentError(message);
          }
          toast.error(message);
        })
        .finally(() => {
          if (!cancelled && contentTagRequestSeq.current === requestSeq) {
            setContentLoading(false);
          }
        });
    }, CONTENT_TAG_REQUEST_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(dashboardTimer);
      window.clearTimeout(contentTimer);
    };
  }, [params]);

  const switchContentTags = (primaryTag?: string) => {
    const nextPrimaryTag = primaryTag || '';
    setContentError('');
    if (nextPrimaryTag && !primaryContentTags?.content_tag_children?.[nextPrimaryTag]) {
      toast.error('这个一级标签暂无二级标签数据');
      return;
    }
    setSelectedPrimaryTag(nextPrimaryTag);
    setData((current) => {
      if (!current || !primaryContentTags) return current;
      if (!nextPrimaryTag) {
        return { ...current, ...primaryContentTags };
      }
      const child = primaryContentTags.content_tag_children?.[nextPrimaryTag];
      if (!child) {
        return current;
      }
      return {
        ...current,
        quadrant: child.quadrant,
        creative_tags: child.creative_tags,
        content_tag_level: 'secondary',
        content_tag_primary: nextPrimaryTag,
      };
    });
  };

  const buyerScopedAccounts = useMemo(() => {
    const accounts = data?.filters.accounts || [];
    const selectedBuyerId = buyerUserId ? Number(buyerUserId) : null;
    return accounts.filter((account) => {
      if (selectedBuyerId && Number(account.buyer_user_id || 0) !== selectedBuyerId) return false;
      return true;
    });
  }, [buyerUserId, data?.filters.accounts]);

  const xhsScopedAccounts = useMemo(() => {
    if (!selectedXhsAccountIds.length) return buyerScopedAccounts;
    const selectedSet = new Set(selectedXhsAccountIds);
    return buyerScopedAccounts.filter((account) => selectedSet.has(professionalAccountKey(account)));
  }, [buyerScopedAccounts, selectedXhsAccountIds]);

  const filteredAccounts = useMemo(() => {
    const selectedSet = new Set(selectedAccountIds);
    return xhsScopedAccounts.filter((account) => {
      if (selectedSet.has(account.account_id)) return true;
      return true;
    });
  }, [selectedAccountIds, xhsScopedAccounts]);

  const accountOptions = useMemo(() => (
    filteredAccounts.map((account) => ({ value: account.account_id, label: account.account_name }))
  ), [filteredAccounts]);

  const xhsAccountOptions = useMemo(() => {
    const grouped = new Map<string, { value: string; label: string; accountIds: Set<string> }>();
    buyerScopedAccounts.forEach((account) => {
      const value = professionalAccountKey(account);
      const xhsId = String(account.xhs_account_id || '').trim();
      const xhsName = String(account.xhs_account_name || '').trim();
      const ownerName = String(account.xhs_owner_name || '').trim();
      if (!xhsId && !xhsName && !ownerName) return;
      const existing = grouped.get(value);
      if (existing) {
        existing.accountIds.add(account.account_id);
        return;
      }
      grouped.set(value, {
        value,
        label: `${xhsName || '未命名专业号'}${ownerName ? ` · ${ownerName}` : ''}`,
        accountIds: new Set([account.account_id]),
      });
    });
    return Array.from(grouped.values()).map((item) => ({
      value: item.value,
      label: `${item.label}（${item.accountIds.size}个广告账户）`,
    }));
  }, [buyerScopedAccounts]);

  useEffect(() => {
    const validIds = new Set(xhsScopedAccounts.map((account) => account.account_id));
    setSelectedAccountIds((current) => {
      const next = current.filter((accountId) => validIds.has(accountId));
      return next.length === current.length ? current : next;
    });
  }, [xhsScopedAccounts]);

  useEffect(() => {
    const validIds = new Set(buyerScopedAccounts.map((account) => professionalAccountKey(account)));
    setSelectedXhsAccountIds((current) => {
      const next = current.filter((accountId) => validIds.has(accountId));
      return next.length === current.length ? current : next;
    });
  }, [buyerScopedAccounts]);

  const kpis = useMemo(() => {
    const order = ['total_spend', 'total_impression', 'total_click', 'ctr', 'avg_click_cost', 'openings', 'interaction', 'interaction_rate', 'opening_cost', 'conversion', 'conversion_rate', 'conversion_cost'];
    const source = data?.kpis || [];
    return order.map((key) => source.find((item) => item.key === key)).filter(Boolean) as XHSAdDashboardResponse['kpis'];
  }, [data?.kpis]);

  const contentTagRows = useMemo(() => {
    return (data?.quadrant.points || []).map((point) => ({
      tag: point.tag,
      conversion: point.y,
      conversion_cost: point.x,
      fee: point.size,
      click: point.click,
      interaction: point.interaction,
    }));
  }, [data?.quadrant.points]);

  const toggleTrendMetric = (metricKey: string) => {
    setTrendMetricKeys((current) => {
      if (current.includes(metricKey)) {
        return current.length <= 1 ? current : current.filter((key) => key !== metricKey);
      }
      return [...current.slice(-1), metricKey];
    });
  };

  const exportTable = async (table: 'brand' | 'note') => {
    try {
      const blob = await exportXhsAdDashboardTable(table, params);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `小红书投流${table === 'brand' ? '品牌' : '笔记'}表_${range.start}_${range.end}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '导出失败');
    }
  };

  const dataStatusLabel = loading ? '正在刷新投流数据...' : loadError ? `投流数据加载失败：${loadError}` : data ? `真实数据 · ${fmt(data.filters.accounts.length)} 个广告账户 · ${fmt(data.owner_rows.length)} ${isBuyerScoped ? '个投流账号' : '位投手'}` : '等待加载投流数据';
  const isDashboardRefreshing = loading && Boolean(data);

  return (
    <div className="relative h-full overflow-y-auto bg-white text-slate-900">
      <Script src="/vendor/echarts.min.js" strategy="afterInteractive" onLoad={() => setEchartsReady(true)} />
      <div className="pointer-events-none absolute inset-0 bg-white" />
      <main className="relative min-h-full p-3 lg:p-4">
        <div className="mx-auto w-full max-w-none space-y-4">
          <section className={cn('relative z-40 overflow-visible rounded-[28px] p-4', CARD_CLASS)}>
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2"><span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-bold tracking-[0.14em] text-slate-700">投流数据看板</span><span className={cn('inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-bold tracking-[0.08em]', loadError ? 'border-rose-200 bg-rose-50 text-rose-700' : loading ? 'border-slate-200 bg-slate-50 text-slate-500' : 'border-emerald-200 bg-emerald-50 text-emerald-800')}>{loading ? <Loader2 className="h-3 w-3 animate-spin" /> : null}{dataStatusLabel}</span></div>
                <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-1"><h1 className="text-[30px] font-semibold leading-tight tracking-[-0.045em] text-slate-950 lg:text-[36px]">小红书投流数据面板</h1></div>
              </div>
              <div className="flex flex-col gap-2 xl:min-w-[680px]">
                <div className="flex flex-wrap items-center justify-end gap-3">
                  <DateRangePicker range={range} onChange={setRange} />
                  <select
                    value={buyerUserId}
                    onChange={(event) => {
                      setBuyerUserId(event.target.value);
                      setSelectedAccountIds([]);
                      setSelectedXhsAccountIds([]);
                    }}
                    className={cn(CONTROL_CLASS, 'w-40 px-3')}
                  >
                    <option value="">全部投手</option>
                    {data?.filters.buyers.map((buyer) => <option key={buyer.user_id} value={buyer.user_id}>{buyer.display_name || buyer.username}</option>)}
                  </select>
                  <AccountMultiSelect
                    className="w-64"
                    options={xhsAccountOptions}
                    selectedValues={selectedXhsAccountIds}
                    onChange={setSelectedXhsAccountIds}
                    placeholder="全部小红书号"
                    clearLabel="全部小红书号"
                    emptyLabel="没有匹配的小红书号"
                  />
                  <AccountMultiSelect
                    className="w-52"
                    options={accountOptions}
                    selectedValues={selectedAccountIds}
                    onChange={setSelectedAccountIds}
                    placeholder={buyerUserId ? '该投手全部广告账户' : '全部广告账户'}
                    clearLabel={buyerUserId ? '该投手全部广告账户' : '全部广告账户'}
                    emptyLabel="没有匹配的广告账户"
                  />
                  <button onClick={() => setShowAi(true)} className="flex h-10 items-center gap-2 rounded-2xl bg-slate-950 px-4 text-sm font-semibold text-white shadow-[0_16px_34px_rgba(15,23,42,0.22)] transition hover:-translate-y-0.5 hover:bg-slate-800"><Sparkles className="h-4 w-4" />生成 AI 摘要</button>
                </div>
              </div>
            </div>
          </section>

          {loading && !data ? (
            <div className={cn('grid min-h-[520px] place-items-center rounded-[32px]', CARD_CLASS)}><div className="flex items-center gap-3 text-sm font-medium text-slate-500"><Loader2 className="h-5 w-5 animate-spin text-slate-700" />正在加载投流看板数据...</div></div>
          ) : data ? (
            <>
              <section className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-6">{kpis.map((metric) => <div key={metric.key} className={cn('group relative min-h-[138px] overflow-hidden rounded-[22px] p-3 transition hover:-translate-y-0.5', PANEL_CLASS)}><div className="absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-slate-300 to-transparent" /><div className="absolute -right-8 -top-10 h-28 w-28 rounded-full bg-slate-100/70 blur-2xl transition group-hover:bg-slate-200/80" /><div className="relative grid h-full grid-rows-[auto_1fr] gap-1"><div className="flex items-center justify-between gap-2"><div className="flex min-w-0 items-center gap-1.5"><div className="whitespace-nowrap text-[10px] font-bold uppercase tracking-[0.04em] text-slate-400">{metric.label}</div><span className="group/help relative grid h-4 w-4 shrink-0 place-items-center rounded-full text-slate-300 transition hover:text-slate-700"><HelpCircle className="h-3.5 w-3.5" /><span className="pointer-events-none absolute left-1/2 top-6 z-20 w-48 -translate-x-1/2 rounded-2xl border border-slate-200 bg-slate-950 px-3 py-2 text-left text-[11px] font-medium leading-relaxed tracking-normal text-white opacity-0 shadow-[0_18px_44px_rgba(15,23,42,0.22)] transition group-hover/help:translate-y-1 group-hover/help:opacity-100">对比上一周期：{formatDelta(metric.delta, metric.value_type)}</span></span></div><span className={cn('shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold', num(metric.delta) >= 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-600')}>{formatDelta(metric.delta, metric.value_type)}</span></div><div className="grid min-w-0 grid-cols-[minmax(0,1fr)_88px] items-center gap-3"><div className="min-w-0 whitespace-nowrap text-left text-[28px] font-semibold leading-none tracking-[-0.05em] text-slate-950 tabular-nums">{fmt(metric.value, metric.value_type)}</div><div className="w-[88px] shrink-0 justify-self-end opacity-90"><MiniSparkline id={metric.key} values={kpiSparkValues(metric.key, data.trend)} /></div></div></div></div>)}</section>

              <section className="grid items-stretch gap-4 xl:grid-cols-[minmax(0,1.16fr)_minmax(0,0.84fr)]">
                <section className={cn('relative h-[620px] overflow-hidden p-5', PANEL_CLASS)}>
                  <PanelTitle eyebrow={isBuyerScoped ? '账号排行' : '负责人排行'} title={isBuyerScoped ? '投流账号排行条' : '投手排行条'} suffix={isBuyerScoped ? '左=账号 · 右=笔记' : '左=效率 · 右=笔记'} icon={<Filter className="h-4 w-4" />} />
                  <div className="mt-2 h-[calc(100%-54px)] min-h-0 overflow-hidden">
                    <OwnerRankingPanel rows={data.owner_rows} notes={data.top_notes} notesLoading={contentLoading} accountMode={isBuyerScoped} />
                  </div>
                </section>
                <section className={cn('relative h-[620px] overflow-hidden p-4', PANEL_CLASS)}>
                  <PanelTitle eyebrow="内容标签" title="内容标签分析" suffix={selectedPrimaryTag ? '二级下钻 · 右=矩阵' : '一级总览 · 右=矩阵'} icon={<PieChart className="h-4 w-4" />} />
                  {contentLoading ? (
                    <div className="absolute right-4 top-4 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-bold text-slate-500 shadow-sm">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />内容标签加载中
                    </div>
                  ) : contentError ? (
                    <div className="absolute right-4 top-4 rounded-full border border-rose-100 bg-rose-50 px-3 py-1 text-[11px] font-bold text-rose-600">{contentError}</div>
                  ) : null}
                  <div className="mt-3 flex h-[calc(100%-58px)] min-h-0 flex-col">
                    <div className="relative flex min-h-0 flex-1 flex-col">
                      {selectedPrimaryTag ? (
                        <button
                          type="button"
                          onClick={() => switchContentTags()}
                          className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white/95 px-2.5 py-1 text-[11px] font-bold text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-900"
                        >
                          <ChevronLeft className="h-3.5 w-3.5" />
                          返回上一级
                        </button>
                      ) : null}
                      {contentLoading && !contentTagRows.length ? (
                        <div className="grid min-h-0 flex-1 place-items-center text-sm font-medium text-slate-500">
                          <span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />矩阵计算中...</span>
                        </div>
                      ) : (
                        <EchartPanel
                          ready={echartsReady}
                          optionBuilder={() => buildQuadrantOption(data.quadrant)}
                          className="min-h-0 flex-1"
                          onPointClick={selectedPrimaryTag ? undefined : (tag) => switchContentTags(tag)}
                        />
                      )}
                    </div>
                    <div className="mt-2 h-[136px] min-h-0 overflow-hidden border-t border-slate-200 pt-2">
                      {contentLoading && !contentTagRows.length ? (
                        <div className="grid h-full place-items-center text-sm font-medium text-slate-500">
                          <span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />内容标签加载中...</span>
                        </div>
                      ) : (
                        <CreativeTagList
                          rows={contentTagRows}
                          mode={selectedPrimaryTag ? 'secondary' : 'primary'}
                          onSelectPrimary={(tag) => switchContentTags(tag)}
                        />
                      )}
                    </div>
                  </div>
                </section>
              </section>

              <section className="grid gap-4 xl:grid-cols-[430px_minmax(0,1fr)]">
                <div className="space-y-4">
                  <section className={cn('relative h-[300px] overflow-hidden p-5', PANEL_CLASS)}>
                    <div className="relative flex h-full flex-col">
                      <PanelTitle eyebrow={isBuyerScoped ? '账号表现' : '负责人表现'} title={isBuyerScoped ? '投流账号消耗 / 转化排行' : '投手消耗 / 转化排行'} suffix="柱=消耗 · 线=转化" icon={<Filter className="h-4 w-4" />} />
                      <div className="mt-3 min-h-0 flex-1"><EchartPanel ready={echartsReady} optionBuilder={(width) => buildOwnerPerformanceOption(data.owner_rows, width, isBuyerScoped)} className="h-full" /></div>
                    </div>
                  </section>
                  <section className={cn('relative min-h-[500px] overflow-visible p-5', PANEL_CLASS)}>
                    <PanelTitle eyebrow="转化链路" title="转化漏斗" icon={<BarChart3 className="h-4 w-4" />} />
                    <FunnelPanel rows={data.funnel} />
                  </section>
                </div>
                <section className={cn('relative h-[816px] overflow-hidden p-5', PANEL_CLASS)}>
                  <div className="relative flex h-full flex-col">
                    <PanelTitle eyebrow="经营趋势" title="消耗转化趋势" suffix="柱=消耗 · 线=转化/转化成本" />
                    <div className="mt-3 min-h-0 flex-1">
                      <EchartPanel ready={echartsReady} optionBuilder={(width) => buildSpendConversionTrendOption(data.trend, width)} className="h-full" />
                    </div>
                  </div>
                </section>
              </section>

              <section className="grid gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
                <section className={cn('relative h-[430px] overflow-hidden p-5', PANEL_CLASS)}>
                  <PanelTitle eyebrow="周期对比" title={isBuyerScoped ? '账号环比数据' : '环比数据'} />
                  <ComparisonList rows={data.comparison_rows} accountMode={isBuyerScoped} />
                </section>
                <section className={cn('relative h-[430px] overflow-hidden p-5', PANEL_CLASS)}>
                  <div className="relative flex h-full flex-col">
                    <PanelTitle eyebrow="趋势表现" title="核心指标趋势" suffix="单次最多展示 2 条" />
                    <div className="mt-4 flex flex-wrap gap-2">
                      {TREND_METRICS.map((metric) => {
                        const active = trendMetricKeys.includes(metric.key);
                        return (
                          <button
                            key={metric.key}
                            type="button"
                            onClick={() => toggleTrendMetric(metric.key)}
                            className={cn(
                              'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-black transition',
                              active
                                ? 'border-slate-950 bg-slate-950 text-white shadow-[0_12px_28px_rgba(15,23,42,0.16)]'
                                : 'border-slate-200 bg-slate-50 text-slate-500 hover:border-slate-300 hover:bg-white hover:text-slate-900',
                            )}
                          >
                            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: active ? '#fff' : metric.color }} />
                            {metric.label}
                          </button>
                        );
                      })}
                    </div>
                    <div className="mt-3 min-h-0 flex-1">
                      <EchartPanel ready={echartsReady} optionBuilder={(width) => buildAdTrendOption(data.trend, trendMetricKeys, width)} className="h-full" />
                    </div>
                  </div>
                </section>
              </section>
              <section className="grid gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]"><DataTable title="品牌消耗转化表" eyebrow="明细导出" rows={data.brand_rows.slice(0, 80)} columns={[['品牌', 'brand'], ['消费', 'fee'], ['展现', 'impression'], ['点击', 'click'], ['点击率', 'ctr'], ['转化', 'conversion'], ['转化成本', 'conversion_cost']]} onExport={() => exportTable('brand')} /><DataTable title="笔记消耗转化表" eyebrow="明细导出" rows={data.note_rows.slice(0, 80)} columns={[['笔记/素材', 'note_title'], ['小红书账号', 'xhs_account_name'], ['消费', 'fee'], ['展现', 'impression'], ['点击', 'click'], ['点击率', 'ctr'], ['开口数', 'openings'], ['转化', 'conversion'], ['转化成本', 'conversion_cost'], ['开口转化率', 'opening_conversion_rate']]} onExport={() => exportTable('note')} /></section>
            </>
          ) : (
            <div className={cn('grid min-h-[520px] place-items-center rounded-[32px]', CARD_CLASS)}><div className="text-sm font-medium text-slate-500">暂无投流看板数据</div></div>
          )}
        </div>
      </main>

      <DashboardRefreshOverlay active={isDashboardRefreshing} />
      {showAi && data && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-6 backdrop-blur-sm" onClick={() => setShowAi(false)}><div className={cn('w-full max-w-2xl rounded-[32px] p-6', CARD_CLASS)} onClick={(event) => event.stopPropagation()}><div className="flex items-start justify-between"><div><div className="inline-flex items-center gap-2 rounded-full bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700"><Bot className="h-3.5 w-3.5" />AI 投流摘要</div><h3 className="mt-4 text-2xl font-semibold tracking-[-0.04em] text-slate-950">{data.ai_summary.title}</h3></div><button onClick={() => setShowAi(false)} className="rounded-full bg-slate-100 p-2 text-slate-500 hover:bg-slate-200"><X className="h-4 w-4" /></button></div><p className="mt-5 text-sm leading-7 text-slate-600">{data.ai_summary.summary}</p><div className="mt-5 space-y-3">{data.ai_summary.actions.map((action, index) => <div key={action} className="rounded-2xl border border-slate-100 bg-slate-50 p-4 text-sm font-semibold leading-6 text-slate-700">{index + 1}. {action}</div>)}</div></div></div>}
    </div>
  );
}
