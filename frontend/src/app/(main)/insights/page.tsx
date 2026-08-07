'use client';

import Script from 'next/script';
import type { MouseEvent } from 'react';
import { startTransition, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState, useTransition } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDot,
  HelpCircle,
  Layers3,
  Loader2,
  Search,
  Sparkles,
  Target,
  Users,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  buildVehicleCatalogIndex,
  buildCarCatalogFromRows,
  resolveVehicleMatchWithIndex,
  type CarCatalogEntry,
  type VehicleCatalogIndex,
  type VehicleMatchResult,
} from '@/lib/vehicleMatcher';
import { AccountMultiSelect } from '@/components/ui/account-multi-select';
import { carModelsApi } from '@/services/carModelsApi';
import { getXhsInsightAccountNotes, getXhsProfileStatOwnerRows, type XHSAccountNote, type XHSInsightsDashboard, type XHSProfileStatOwnerRow } from '@/services/xhsApi';

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

type AccountStatus = '主推' | '修正' | '补样本' | '观察';
type DepartmentFilter = 'all' | 'xhs' | 'brand';
type RankingSortKey = 'score' | 'views' | 'comments' | 'engagement';

type AccountSummary = {
  accountName: string;
  posts: number;
  totalViews: number;
  totalComments: number;
  totalEngagement: number;
  avgViews: number;
  avgComments: number;
  avgEngagement: number;
  weakRate: number;
  strongRate: number;
  strongPostCount: number;
  weakPostCount: number;
  activePostCount: number;
  missingInteractionMetrics: boolean;
  score: number;
  scoreBreakdown: {
    sampleConfidenceScore: number;
    avgViewsScore: number;
    avgCommentsScore: number;
    avgEngagementScore: number;
    avgCollectShareScore: number;
    avgLikesScore: number;
    strongRateScore: number;
    weakPenalty: number;
  };
  status: AccountStatus;
  strongestSignal: string;
  biggestProblem: string;
  nextAction: string;
};

type TrendPoint = {
  label: string;
  posts: number;
  views: number;
  engagement: number;
  comments: number;
};

type OperatorPerformanceRow = {
  ownerId: string;
  ownerName: string;
  ownerRole: string;
  accountNames: string[];
  accountCount: number;
  posts: number;
  views: number;
  likes: number;
  collects: number;
  comments: number;
  shares: number;
  engagement: number;
  qualityCount: number;
  lowQualityCount: number;
  paidPosts: number;
  organicPosts: number;
  paidRatio: number;
  naturalLeads: number;
  specialNaturalLeads: number;
  adLeads: number;
};

type AiReport = {
  badge: string;
  headline: string;
  summary: string;
  stats: Array<{ label: string; value: string; detail: string }>;
  actions: Array<{ title: string; body: string; tone: 'sky' | 'emerald' | 'amber' }>;
};

type TagMatrixItem = {
  dimension: '决策主题' | '购车场景' | '标题钩子' | '证据结构' | '承接动作' | '车型锚点';
  label: string;
  count: number;
  paidCount: number;
  organicCount: number;
  consult: number;
  leads: number;
  organicEngagement: number;
};

type TagRelationData = {
  accountName: string;
  tagMatrix: TagMatrixItem[];
};

type CarTypeStats = {
  name: string;
  brand: string;
  model?: string;
  posts: number;
  totalViews: number;
  totalComments: number;
  totalEngagement: number;
  avgViews: number;
  avgComments: number;
  qualityCount: number;
  share: number;
  models?: CarTypeStats[];
};

type PostRankingItem = {
  id: string;
  title: string;
  accountName: string;
  coverImageUrl: string;
  postUrl: string;
  views: number;
  comments: number;
  engagement: number;
  score: number;
  note: XHSAccountNote;
};

type DateRange = {
  start: Date;
  end: Date;
};

type AccountOption = {
  key: string;
  label: string;
  noteCount: number;
};

type OwnerOption = {
  key: string;
  label: string;
  accountCount: number;
  noteCount: number;
};

type InsightsDataStatus = 'loading' | 'real' | 'empty' | 'error';

const INSIGHT_NOTE_LIMIT = 10000;

const CARD_CLASS = 'border border-slate-100 bg-white shadow-[0_24px_70px_rgba(15,23,42,0.08)] ring-1 ring-slate-100';
const PANEL_CLASS = 'rounded-[28px] border border-slate-100 bg-white shadow-[0_18px_54px_rgba(15,23,42,0.07)] ring-1 ring-slate-100';
const CONTROL_CLASS = 'h-10 rounded-2xl border border-slate-200 bg-white text-sm shadow-[0_10px_24px_rgba(15,23,42,0.06)] outline-none transition focus:border-slate-400 focus:ring-4 focus:ring-slate-100';

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
const toNumber = (value: unknown) => {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : 0;
};
const formatInteger = (value: number) => Math.round(value).toLocaleString('zh-CN');
const formatScore = (value: number) => roundNumber(value, 1).toLocaleString('zh-CN');
const waitForPaint = () => new Promise<void>((resolve) => {
  requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
});
const isQualityNote = (note: XHSAccountNote) => toNumber(note.view_count) >= 4000 || toNumber(note.comment_count) >= 30;
const isLowQualityNote = (note: XHSAccountNote) => toNumber(note.view_count) < 100 && toNumber(note.comment_count) < 3;
const isPromotedNote = (note: XHSAccountNote) => {
  const promotedMeta = note as XHSAccountNote & {
    is_promoted?: boolean | number | string | null;
    has_paid_report?: boolean | number | string | null;
    has_creative_report?: boolean | number | string | null;
    paid?: boolean | number | string | null;
  };
  return Boolean(promotedMeta.is_promoted || promotedMeta.has_paid_report || promotedMeta.has_creative_report || promotedMeta.paid);
};
const AI_ACTION_TONE: Record<AiReport['actions'][number]['tone'], string> = {
  sky: 'bg-slate-50 text-slate-800 ring-slate-200',
  emerald: 'bg-slate-50 text-slate-700 ring-slate-100',
  amber: 'bg-slate-50 text-slate-700 ring-slate-100',
};
const TAG_RELATION_DIMENSIONS: TagMatrixItem['dimension'][] = ['决策主题', '购车场景', '标题钩子', '证据结构', '承接动作', '车型锚点'];
const TAG_RELATION_THEME = {
  rust: '#7f1d1d',
  gold: '#4d7c0f',
  blue: '#4c1d95',
  green: '#166534',
  danger: '#581c87',
  text: '#111827',
  muted: '#64748b',
};
const CAR_TYPE_PALETTE = ['#111827', '#14532d', '#312e81', '#7f1d1d', '#334155', '#4d7c0f', '#0f766e', '#9a3412', '#1d4ed8', '#64748b'];

function formatDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getStartOfDay(date: Date): Date {
  const result = new Date(date);
  result.setHours(0, 0, 0, 0);
  return result;
}

function getEndOfDay(date: Date): Date {
  const result = new Date(date);
  result.setHours(23, 59, 59, 999);
  return result;
}

function getYesterday(): Date {
  const date = new Date();
  date.setDate(date.getDate() - 1);
  return getStartOfDay(date);
}

function getDefaultDateRange(): DateRange {
  const end = getYesterday();
  const start = new Date(end);
  start.setDate(end.getDate() - 29);
  return { start: getStartOfDay(start), end: getEndOfDay(end) };
}

function getRangeDays(range: DateRange): number {
  return Math.max(1, Math.round((getStartOfDay(range.end).getTime() - getStartOfDay(range.start).getTime()) / 86400000) + 1);
}

function getDateRangeLabel(range: DateRange): string {
  return `${formatDateKey(range.start)} - ${formatDateKey(range.end)}`;
}

function getMonthTitle(date: Date): string {
  return `${date.getFullYear()}年${date.getMonth() + 1}月`;
}

function isSameDay(a: Date, b: Date): boolean {
  return formatDateKey(a) === formatDateKey(b);
}

function isBeforeDay(a: Date, b: Date): boolean {
  return getStartOfDay(a).getTime() < getStartOfDay(b).getTime();
}

function isAfterDay(a: Date, b: Date): boolean {
  return getStartOfDay(a).getTime() > getStartOfDay(b).getTime();
}

function isDateInRange(date: Date, range: DateRange): boolean {
  const time = getStartOfDay(date).getTime();
  return time >= getStartOfDay(range.start).getTime() && time <= getStartOfDay(range.end).getTime();
}

function getCalendarDays(viewMonth: Date): Date[] {
  const firstDay = new Date(viewMonth.getFullYear(), viewMonth.getMonth(), 1);
  const start = new Date(firstDay);
  start.setDate(firstDay.getDate() - firstDay.getDay());
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
}

function parseNoteDate(note: XHSAccountNote): Date | null {
  const raw = note.published_at || note.created_at || note.updated_at;
  if (!raw) return null;
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? null : date;
}

function getDateLabel(dateKey: string): string {
  const [, month, day] = dateKey.split('-');
  return `${month}-${day}`;
}

function normalizeContentAccountName(value = ''): string {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function normalizeProfileStatAccountName(value = ''): string {
  return normalizeContentAccountName(value).replace(/^【小红书】/, '').trim();
}

function getNoteAccountName(note: Pick<XHSAccountNote, 'account_name' | 'profile_nickname'>): string {
  return normalizeContentAccountName(note.account_name || note.profile_nickname || '') || '未命名账号';
}

function getNoteAccountKey(note: Pick<XHSAccountNote, 'environment_id' | 'account_name' | 'profile_nickname'>): string {
  const environmentId = Number(note.environment_id || 0);
  return environmentId > 0 ? `env:${environmentId}` : `name:${getNoteAccountName(note)}`;
}

function getDominantAccountName(notes: Array<Pick<XHSAccountNote, 'account_name' | 'profile_nickname'>>): string {
  const counts = new Map<string, number>();
  notes.forEach((note) => {
    const name = getNoteAccountName(note);
    counts.set(name, (counts.get(name) || 0) + 1);
  });
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-Hans-CN'))[0]?.[0] || '未命名账号';
}

function buildAccountOptions(notes: XHSAccountNote[], search: string): AccountOption[] {
  const grouped = new Map<string, XHSAccountNote[]>();
  notes.forEach((note) => {
    const key = getNoteAccountKey(note);
    const items = grouped.get(key);
    if (items) {
      items.push(note);
    } else {
      grouped.set(key, [note]);
    }
  });

  const keyword = search.trim().toLowerCase();
  return Array.from(grouped.entries())
    .map(([key, items]) => ({
      key,
      label: getDominantAccountName(items),
      noteCount: items.length,
    }))
    .filter((account) => !keyword || account.label.toLowerCase().includes(keyword))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'));
}

function buildOwnerOptions(notes: XHSAccountNote[], profileRows: XHSProfileStatOwnerRow[]): OwnerOption[] {
  const grouped = new Map<string, { label: string; accountKeys: Set<string>; noteCount: number }>();
  notes.forEach((note) => {
    if (!note.owner_user_id || !isReportableOperatorRole(note.owner_role)) return;
    const key = String(note.owner_user_id);
    const current = grouped.get(key) || {
      label: note.owner_username || '未分配',
      accountKeys: new Set<string>(),
      noteCount: 0,
    };
    current.label = note.owner_username || current.label;
    current.accountKeys.add(getNoteAccountKey(note));
    current.noteCount += 1;
    grouped.set(key, current);
  });
  profileRows.forEach((row) => {
    const key = String(row.owner_id || '');
    if (!key || key === 'unassigned') return;
    const current = grouped.get(key) || {
      label: row.owner_name || '未分配',
      accountKeys: new Set<string>(),
      noteCount: 0,
    };
    current.label = row.owner_name || current.label;
    (row.account_names || []).forEach((accountName) => {
      const normalized = normalizeContentAccountName(accountName);
      if (normalized) current.accountKeys.add(normalized);
    });
    grouped.set(key, current);
  });
  return Array.from(grouped.entries())
    .map(([key, item]) => ({
      key,
      label: item.label,
      accountCount: item.accountKeys.size,
      noteCount: item.noteCount,
    }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'));
}

function scoreCurve(value: number, points: Array<[number, number]>): number {
  if (!points.length) return 0;
  if (value <= points[0][0]) return points[0][1];
  for (let index = 1; index < points.length; index += 1) {
    const [x2, y2] = points[index];
    const [x1, y1] = points[index - 1];
    if (value <= x2) {
      const ratio = (value - x1) / Math.max(1e-9, x2 - x1);
      return y1 + (y2 - y1) * ratio;
    }
  }
  return points[points.length - 1][1];
}

function safeRatio(num: number, den: number): number {
  return den ? num / den : 0;
}

function roundNumber(value: number, digits = 2): number {
  const base = 10 ** digits;
  return Math.round((Number(value) || 0) * base) / base;
}

function isNaturalStrongRankingNote(note: XHSAccountNote): boolean {
  return toNumber(note.view_count) > 4000 && toNumber(note.comment_count) > 30;
}

function isNaturalWeakRankingNote(note: XHSAccountNote): boolean {
  return toNumber(note.view_count) < 100 && toNumber(note.comment_count) < 3;
}

function determinePortfolioNaturalStatus(metrics: {
  posts: number;
  avgViews: number;
  avgComments: number;
  avgEngagement: number;
  strongPostCount: number;
  weakPostCount: number;
  activePostCount: number;
}): AccountStatus {
  if (metrics.posts >= 8 && metrics.avgViews < 200 && metrics.avgComments < 1 && metrics.avgEngagement < 3) {
    return '观察';
  }
  if (metrics.strongPostCount >= 1 || metrics.avgViews >= 2000 || metrics.avgComments >= 30 || metrics.avgEngagement >= 200) {
    return '主推';
  }
  if (metrics.posts < 3 && metrics.avgViews < 800 && metrics.avgComments < 6 && metrics.avgEngagement < 18) return '补样本';
  if (metrics.avgViews >= 800 && metrics.avgComments < 3 && metrics.avgEngagement < 12) {
    return '修正';
  }
  if (metrics.weakPostCount >= Math.max(2, Math.ceil(metrics.posts / 3)) || (metrics.avgViews < 500 && metrics.avgComments < 2 && metrics.avgEngagement < 8)) {
    return '观察';
  }
  if (metrics.avgViews >= 500 || metrics.avgComments >= 3 || metrics.avgEngagement >= 10 || metrics.activePostCount >= 2) {
    return '补样本';
  }
  return '观察';
}

function classifyRoute(note: XHSAccountNote): string {
  const text = `${note.title || ''} ${note.content || ''}`.toLowerCase();
  if (/避坑|别乱|别急|别买|检查|踩坑|防坑/.test(text)) return '避坑指南';
  if (/对比|怎么选|选哪|差别|区别|pk|同价位/.test(text)) return '对比决策';
  if (/本地|城市|到店|门店|区域|行情|落地/.test(text)) return '本地方案';
  if (/政策|新政|补贴|置换|权益|金融|分期/.test(text)) return '车型政策';
  if (/验车|提车|交付|合同|签约/.test(text)) return '交付验车';
  if (/配置|版本|内饰|续航|空间|动力/.test(text)) return '配置解析';
  if (/价格|好价|预算|参考|方案/.test(text)) return '价格参考';
  return '泛内容观察';
}

function isInRange(note: XHSAccountNote, start: Date, end: Date): boolean {
  const date = parseNoteDate(note);
  return Boolean(date && date.getTime() >= start.getTime() && date.getTime() <= end.getTime());
}

function getTrendBucket(date: Date, range: DateRange): { key: string; label: string } {
  if (getRangeDays(range) <= 31) {
    const key = formatDateKey(date);
    return { key, label: getDateLabel(key) };
  }

  const offset = Math.max(0, Math.floor((getStartOfDay(date).getTime() - getStartOfDay(range.start).getTime()) / (86400000 * 7)));
  const weekStart = new Date(range.start);
  weekStart.setDate(range.start.getDate() + offset * 7);
  const weekEnd = new Date(weekStart);
  weekEnd.setDate(weekStart.getDate() + 6);
  const cappedEnd = isAfterDay(weekEnd, range.end) ? range.end : weekEnd;
  return {
    key: `week-${offset}`,
    label: `${getDateLabel(formatDateKey(weekStart))}~${getDateLabel(formatDateKey(cappedEnd))}`,
  };
}

function buildAccountSummaries(notes: XHSAccountNote[]): AccountSummary[] {
  const grouped = new Map<string, XHSAccountNote[]>();
  notes.forEach((note) => {
    const accountKey = getNoteAccountKey(note);
    const items = grouped.get(accountKey);
    if (items) {
      items.push(note);
    } else {
      grouped.set(accountKey, [note]);
    }
  });

  return Array.from(grouped.values()).map((items) => {
    const accountName = getDominantAccountName(items);
    const posts = items.length;
    const totalViews = items.reduce((sum, note) => sum + toNumber(note.view_count), 0);
    const totalLikes = items.reduce((sum, note) => sum + toNumber(note.liked_count), 0);
    const totalComments = items.reduce((sum, note) => sum + toNumber(note.comment_count), 0);
    const totalCollects = items.reduce((sum, note) => sum + toNumber(note.collected_count), 0);
    const totalShares = items.reduce((sum, note) => sum + toNumber(note.share_count), 0);
    const totalEngagement = totalLikes + totalComments + totalCollects + totalShares;
    const avgViews = roundNumber(safeRatio(totalViews, posts), 2);
    const avgLikes = roundNumber(safeRatio(totalLikes, posts), 2);
    const avgComments = roundNumber(safeRatio(totalComments, posts), 2);
    const avgCollects = roundNumber(safeRatio(totalCollects, posts), 2);
    const avgShares = roundNumber(safeRatio(totalShares, posts), 2);
    const avgEngagement = roundNumber(safeRatio(totalEngagement, posts), 2);
    const strongPostCount = items.filter(isNaturalStrongRankingNote).length;
    const weakPostCount = items.filter(isNaturalWeakRankingNote).length;
    const activePostCount = items.filter((note) => toNumber(note.view_count) >= 300 || toNumber(note.comment_count) >= 3 || toNumber(note.liked_count) >= 8).length;
    const missingInteractionMetrics = posts > 0 && totalViews > 0 && totalComments === 0 && totalCollects === 0 && totalShares === 0;
    const weakRate = safeRatio(weakPostCount, posts);
    const strongRate = safeRatio(strongPostCount, posts);
    const sampleConfidenceScore = scoreCurve(posts, [[0, 0], [1, 1], [3, 3], [7, 5]]);
    const avgViewsScore = scoreCurve(avgViews, [[0, 0], [100, 5], [300, 14], [600, 19], [1000, 22], [2000, 27], [4000, 32]]);
    const avgCommentsScore = scoreCurve(avgComments, [[0, 0], [1, 4], [3, 9], [8, 16], [15, 19], [20, 21], [30, 25], [45, 28]]);
    const avgEngagementScore = scoreCurve(avgEngagement, [[0, 0], [3, 4], [8, 10], [15, 13], [20, 15], [30, 17], [50, 20], [80, 22]]);
    const avgCollectShareScore = scoreCurve(avgCollects + avgShares * 1.4, [[0, 0], [0.5, 1.5], [1.5, 3.5], [3, 6], [6, 8], [12, 9]]);
    const avgLikesScore = scoreCurve(avgLikes, [[0, 0], [1, 1], [3, 2.5], [8, 4], [20, 4]]);
    const strongRateScore = scoreCurve(strongRate, [[0, 0], [0.05, 2], [0.1, 3.5], [0.2, 5]]);
    const weakPenalty = scoreCurve(weakRate, [[0, 0], [0.2, 2], [0.5, 5], [1, 6]]);
    const priorityScore =
      sampleConfidenceScore +
      avgViewsScore +
      avgCommentsScore +
      avgEngagementScore +
      avgCollectShareScore +
      avgLikesScore +
      strongRateScore -
      weakPenalty;
    const finalScore = roundNumber(clamp(priorityScore, 0, 100), 2);
    const topRoute = Array.from(items.reduce((map, note) => {
      const route = classifyRoute(note);
      map.set(route, (map.get(route) || 0) + 1);
      return map;
    }, new Map<string, number>())).sort((a, b) => b[1] - a[1])[0]?.[0] || '暂无路线';
    const status = determinePortfolioNaturalStatus({
      posts,
      avgViews,
      avgComments,
      avgEngagement,
      strongPostCount,
      weakPostCount,
      activePostCount,
    });

    return {
      accountName,
      posts,
      totalViews,
      totalComments,
      totalEngagement,
      avgViews,
      avgComments,
      avgEngagement,
      weakRate,
      strongRate,
      strongPostCount,
      weakPostCount,
      activePostCount,
      missingInteractionMetrics,
      score: finalScore,
      scoreBreakdown: {
        sampleConfidenceScore: roundNumber(sampleConfidenceScore, 2),
        avgViewsScore: roundNumber(avgViewsScore, 2),
        avgCommentsScore: roundNumber(avgCommentsScore, 2),
        avgEngagementScore: roundNumber(avgEngagementScore, 2),
        avgCollectShareScore: roundNumber(avgCollectShareScore, 2),
        avgLikesScore: roundNumber(avgLikesScore, 2),
        strongRateScore: roundNumber(strongRateScore, 2),
        weakPenalty: roundNumber(weakPenalty, 2),
      },
      status,
      strongestSignal: totalViews === 0 && totalEngagement === 0
        ? `${formatInteger(posts)} 条内容暂无可识别自然浏览/互动回流，先按低反馈样本处理。`
        : strongPostCount > 0
          ? `${topRoute} 已出现 ${formatInteger(strongPostCount)} 条高信号自然样本，浏览 ${formatInteger(totalViews)}、评论 ${formatInteger(totalComments)}。`
          : totalComments >= 10
            ? `${topRoute} 仍能带起讨论，当前累计 ${formatInteger(totalComments)} 条评论。`
            : `${topRoute} 目前是自然浏览最有反馈的内容带。`,
      biggestProblem: totalViews === 0 && totalEngagement === 0
        ? '本期已发内容但自然浏览、点赞、评论、收藏、分享都没有回流，优先检查内容首屏与数据口径。'
        : weakPostCount >= Math.max(2, Math.ceil(posts / 3))
          ? `低信号样本 ${formatInteger(weakPostCount)} 条，说明当前大量内容浏览和讨论都起不来。`
          : totalComments === 0
            ? '有浏览但没有讨论，说明内容停留在信息路过，没有形成互动。'
            : avgViews < 150
              ? '单帖平均浏览偏低，首屏识别和题材切口都还不够稳。'
              : '当前自然反馈还不够稳定，先补样本再判断是否值得放大。',
      nextAction: status === '主推' ? `保留 ${topRoute}，继续放大` : status === '修正' ? '有浏览但讨论和收藏偏弱，先修表达' : status === '补样本' ? '已有局部自然反馈，继续补控变量样本' : '当前自然反馈分散，先收缩方向',
    };
  }).sort((a, b) => b.score - a.score || b.avgComments - a.avgComments || b.avgViews - a.avgViews);
}

function deriveSceneTag(route: string) {
  if (/交付|验车|家庭/.test(route)) return '家庭用车';
  if (/对比|配置|换购/.test(route)) return '换购升级';
  return '首购入门';
}

function deriveHookTag(note: XHSAccountNote, route: string) {
  const text = `${note.title || ''} ${note.content || ''}`;
  if (/风险|避坑|别买|注意/.test(text) || /避坑/.test(route)) return '风险提醒型';
  if (/政策|补贴|权益|限时/.test(text) || /政策/.test(route)) return '政策提醒型';
  if (/价格|行情|预算|优惠/.test(text) || /价格/.test(route)) return '价格情报型';
  return '对比设问型';
}

function deriveEvidenceTag(note: XHSAccountNote, route: string) {
  const text = `${note.title || ''} ${note.content || ''}`;
  if (/案例|真实|车主|样本/.test(text)) return '案例证明';
  if (/清单|步骤| checklist|Checklist/i.test(text) || /交付|验车/.test(route)) return '清单拆解';
  if (/痛点|问题|担心|焦虑/.test(text) || /避坑/.test(route)) return '痛点切入';
  return '情报先抛';
}

function deriveActionTag(note: XHSAccountNote) {
  const text = `${note.title || ''} ${note.content || ''}`;
  if (/试驾|到店|预约/.test(text)) return '试驾邀约';
  if (toNumber(note.comment_count) >= 5 || /评论|咨询|私信/.test(text)) return '后续咨询承接';
  return '无明确动作';
}

function getNoteCacheKey(note: XHSAccountNote): string {
  return String(note.id || note.feed_id || `${getNoteAccountName(note)}-${note.title || ''}`);
}

function getCachedVehicleMatch(note: XHSAccountNote, vehicleMatches: Map<string, VehicleMatchResult>): VehicleMatchResult {
  return vehicleMatches.get(getNoteCacheKey(note)) || {
    brand: '未识别品牌',
    model: '未识别车型',
    confidence: 'none',
    score: 0,
    reason: '未生成车型缓存',
  };
}

function extractVehicleTag(note: XHSAccountNote, vehicleMatches: Map<string, VehicleMatchResult>) {
  return getCachedVehicleMatch(note, vehicleMatches).model;
}

function buildTagRelationData(notes: XHSAccountNote[], accountName: string, vehicleMatches: Map<string, VehicleMatchResult>): TagRelationData {
  const tagMap = new Map<string, TagMatrixItem>();
  const addTag = (dimension: TagMatrixItem['dimension'], label: string, note?: XHSAccountNote) => {
    const key = `${dimension}-${label}`;
    const current = tagMap.get(key) || {
      dimension,
      label,
      count: 0,
      paidCount: 0,
      organicCount: 0,
      consult: 0,
      leads: 0,
      organicEngagement: 0,
    };
    const engagement = note
      ? toNumber(note.liked_count) + toNumber(note.comment_count) + toNumber(note.collected_count) + toNumber(note.share_count)
      : 0;
    tagMap.set(key, {
      ...current,
      count: current.count + 1,
      organicCount: current.organicCount + 1,
      consult: current.consult + (note ? toNumber(note.comment_count) : 0),
      leads: current.leads + (note && isQualityNote(note) ? 1 : 0),
      organicEngagement: current.organicEngagement + engagement,
    });
  };

  notes.forEach((note) => {
    const route = classifyRoute(note);
    addTag('决策主题', /避坑|风险/.test(route) ? '风险避坑' : '选车对比', note);
    addTag('购车场景', deriveSceneTag(route), note);
    addTag('标题钩子', deriveHookTag(note, route), note);
    addTag('证据结构', deriveEvidenceTag(note, route), note);
    addTag('承接动作', deriveActionTag(note), note);
    addTag('车型锚点', extractVehicleTag(note, vehicleMatches), note);
  });

  return {
    accountName,
    tagMatrix: Array.from(tagMap.values()),
  };
}

function buildTrend(notes: XHSAccountNote[], range: DateRange): TrendPoint[] {
  const map = new Map<string, TrendPoint>();
  if (getRangeDays(range) <= 31) {
    const cursor = new Date(range.start);
    while (cursor.getTime() <= range.end.getTime()) {
      const key = formatDateKey(cursor);
      map.set(key, { label: getDateLabel(key), posts: 0, views: 0, engagement: 0, comments: 0 });
      cursor.setDate(cursor.getDate() + 1);
    }
  }
  notes.forEach((note) => {
    const date = parseNoteDate(note);
    if (!date) return;
    const { key, label } = getTrendBucket(date, range);
    const current = map.get(key) || { label, posts: 0, views: 0, engagement: 0, comments: 0 };
    current.posts += 1;
    current.views += toNumber(note.view_count);
    current.comments += toNumber(note.comment_count);
    current.engagement += toNumber(note.liked_count) + toNumber(note.comment_count) + toNumber(note.collected_count) + toNumber(note.share_count);
    map.set(key, current);
  });
  return Array.from(map.values()).filter((point) => (
    point.posts > 0
    || point.views > 0
    || point.comments > 0
    || point.engagement > 0
  ));
}

function getOwnerRoleLabel(role?: string | null): string {
  if (role === 'xhs_lead') return '小红书部门负责人';
  if (role === 'xhs_ops') return '小红书运营';
  if (role === 'buyer' || role === 'xhs_buyer') return '投手';
  if (role === 'brand_lead') return '品牌责任人';
  if (role === 'brand_ops') return '品牌运营';
  if (role === 'admin') return '管理员';
  return '未分配';
}

const RANKING_SORT_OPTIONS: Array<{ value: RankingSortKey; label: string }> = [
  { value: 'score', label: '评分' },
  { value: 'views', label: '浏览量' },
  { value: 'comments', label: '评论量' },
  { value: 'engagement', label: '互动量' },
];

function getRankingSortLabel(sortKey: RankingSortKey): string {
  return RANKING_SORT_OPTIONS.find((option) => option.value === sortKey)?.label || '评分';
}

function getAccountRankingValue(account: AccountSummary, sortKey: RankingSortKey): number {
  if (sortKey === 'views') return account.totalViews;
  if (sortKey === 'comments') return account.totalComments;
  if (sortKey === 'engagement') return account.totalEngagement;
  return account.score;
}

function getPostRankingValue(post: PostRankingItem, sortKey: RankingSortKey): number {
  if (sortKey === 'views') return post.views;
  if (sortKey === 'comments') return post.comments;
  if (sortKey === 'engagement') return post.engagement;
  return post.score;
}

function getDepartmentLabel(department: DepartmentFilter): string {
  if (department === 'xhs') return '小红书部门';
  if (department === 'brand') return '品牌中心';
  return '全部部门';
}

function getOwnerDepartment(role?: string | null): DepartmentFilter | 'other' {
  if (role === 'xhs_lead' || role === 'xhs_ops') return 'xhs';
  if (role === 'brand_lead' || role === 'brand_ops') return 'brand';
  return 'other';
}

function matchesDepartmentFilter(role: string | null | undefined, department: DepartmentFilter): boolean {
  if (department === 'all') return isReportableOperatorRole(role);
  return getOwnerDepartment(role) === department;
}

function isReportableOperatorRole(role?: string | null): boolean {
  return role === 'xhs_ops' || role === 'xhs_lead' || role === 'brand_ops' || role === 'brand_lead' || role === 'admin';
}

function buildOperatorPerformanceRows(notes: XHSAccountNote[]): OperatorPerformanceRow[] {
  const grouped = new Map<string, { row: OperatorPerformanceRow; accounts: Map<string, string> }>();
  notes.forEach((note) => {
    if (!note.owner_user_id) return;
    if (!isReportableOperatorRole(note.owner_role)) return;
    const ownerId = note.owner_user_id ? String(note.owner_user_id) : 'unassigned';
    const current = grouped.get(ownerId) || {
      row: {
        ownerId,
        ownerName: note.owner_username || '未分配',
        ownerRole: getOwnerRoleLabel(note.owner_role),
        accountNames: [],
        accountCount: 0,
        posts: 0,
        views: 0,
        likes: 0,
        collects: 0,
        comments: 0,
        shares: 0,
        engagement: 0,
        qualityCount: 0,
        lowQualityCount: 0,
        paidPosts: 0,
        organicPosts: 0,
        paidRatio: 0,
        naturalLeads: 0,
        specialNaturalLeads: 0,
        adLeads: 0,
      },
      accounts: new Map<string, string>(),
    };
    current.accounts.set(getNoteAccountKey(note), getNoteAccountName(note));
    current.row.posts += 1;
    current.row.views += toNumber(note.view_count);
    current.row.likes += toNumber(note.liked_count);
    current.row.collects += toNumber(note.collected_count);
    current.row.comments += toNumber(note.comment_count);
    current.row.shares += toNumber(note.share_count);
    current.row.engagement += toNumber(note.liked_count) + toNumber(note.collected_count) + toNumber(note.comment_count) + toNumber(note.share_count);
    current.row.qualityCount += isQualityNote(note) ? 1 : 0;
    current.row.lowQualityCount += isLowQualityNote(note) ? 1 : 0;
    if (isPromotedNote(note)) {
      current.row.paidPosts += 1;
    } else {
      current.row.organicPosts += 1;
    }
    grouped.set(ownerId, current);
  });
  return Array.from(grouped.values())
    .map((item) => {
      item.row.paidRatio = item.row.posts > 0 ? item.row.paidPosts / item.row.posts : 0;
      item.row.accountNames = Array.from(item.accounts.values())
        .filter(Boolean)
        .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
      item.row.accountCount = item.accounts.size;
      return item.row;
    })
    .sort((a, b) => b.posts - a.posts || b.views - a.views || a.ownerName.localeCompare(b.ownerName, 'zh-Hans-CN'));
}

function mergeProfileStatOwnerRows(rows: OperatorPerformanceRow[], profileRows: XHSProfileStatOwnerRow[]): OperatorPerformanceRow[] {
  const byOwnerId = new Map(profileRows.map((row) => [String(row.owner_id || ''), row]));
  const used = new Set<string>();
  const merged = rows.map((row) => {
    const profile = byOwnerId.get(row.ownerId);
    if (profile) used.add(String(profile.owner_id || ''));
    const accountNames = profile
      ? Array.from(new Set([...row.accountNames, ...(profile.account_names || []).map(normalizeProfileStatAccountName)]))
        .filter(Boolean)
        .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
      : row.accountNames;
    return {
      ...row,
      ownerName: profile?.owner_name || row.ownerName,
      ownerRole: profile?.owner_role ? getOwnerRoleLabel(profile.owner_role) : row.ownerRole,
      accountNames,
      accountCount: Math.max(row.accountCount, profile?.account_count || 0, accountNames.length),
      naturalLeads: profile?.natural_leads || 0,
      specialNaturalLeads: profile?.special_natural_leads || 0,
      adLeads: profile?.ad_leads || 0,
    };
  });
  profileRows.forEach((profile) => {
    const ownerId = String(profile.owner_id || 'unassigned');
    if (used.has(ownerId)) return;
    merged.push({
      ownerId,
      ownerName: profile.owner_name || '未分配',
      ownerRole: getOwnerRoleLabel(profile.owner_role),
      accountNames: (profile.account_names || []).map(normalizeProfileStatAccountName).filter(Boolean),
      accountCount: profile.account_count || 0,
      posts: 0,
      views: 0,
      likes: 0,
      collects: 0,
      comments: 0,
      shares: 0,
      engagement: 0,
      qualityCount: 0,
      lowQualityCount: 0,
      paidPosts: 0,
      organicPosts: 0,
      paidRatio: 0,
      naturalLeads: profile.natural_leads || 0,
      specialNaturalLeads: profile.special_natural_leads || 0,
      adLeads: profile.ad_leads || 0,
    });
  });
  return merged.sort((a, b) => (
    b.posts - a.posts
    || (b.naturalLeads + b.specialNaturalLeads + b.adLeads) - (a.naturalLeads + a.specialNaturalLeads + a.adLeads)
    || b.views - a.views
    || a.ownerName.localeCompare(b.ownerName, 'zh-Hans-CN')
  ));
}

function exportOperatorPerformanceRows(rows: OperatorPerformanceRow[], range: DateRange) {
  const headers = ['运营负责人', '角色', '负责账号', '账号数', '笔记数', '阅读量', '收藏量', '评论量', '点赞量', '分享量', '互动量', '优质笔记数', '低效笔记数', '投流笔记量', '未投流笔记量', '投流占比', '自然来源客资数', '特殊自然来源数', '广告客资数'];
  const csvRows = [
    headers,
    ...rows.map((row) => [
      row.ownerName,
      row.ownerRole,
      row.accountNames.join('、'),
      row.accountCount,
      row.posts,
      row.views,
      row.collects,
      row.comments,
      row.likes,
      row.shares,
      row.engagement,
      row.qualityCount,
      row.lowQualityCount,
      row.paidPosts,
      row.organicPosts,
      `${roundNumber(row.paidRatio * 100, 1)}%`,
      row.naturalLeads,
      row.specialNaturalLeads,
      row.adLeads,
    ]),
  ];
  const csv = csvRows.map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n');
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `运营负责人数据_${formatDateKey(range.start)}_${formatDateKey(range.end)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function buildMockAiReport(selectedAccount: string): AiReport {
  const isPortfolio = selectedAccount === 'all';
  return {
    badge: isPortfolio ? 'Mock 全量摘要' : 'Mock 账号摘要',
    headline: isPortfolio
      ? '本周期 20 位运营负责人整体发帖稳定，但高阅读和高优质笔记仍集中在头部 6 位运营。'
      : `${selectedAccount} 当前内容节奏正常，下一步重点是提高收藏和评论承接，而不是继续盲目加发帖量。`,
    summary: isPortfolio
      ? '模拟结果显示：60 个账号共形成 3 个明显梯队。第一梯队负责账号的阅读效率更高，第二梯队发帖量足但优质率偏低，第三梯队需要先收缩选题范围。建议下周把优质帖子模板拆成封面、标题、价格钩子、评论引导四个变量复测。'
      : '模拟摘要：该账号近期内容基础流量尚可，但优质笔记占比一般。建议保留当前主车型方向，同时把低互动选题从排期里移除，集中测试价格政策、真实用车成本和竞品对比三类钩子。',
    stats: [
      { label: '重点动作', value: '优先复制头部运营模板', detail: '不要平均分配排期，把高优质率运营的标题/封面结构做成团队模板。' },
      { label: '风险点', value: '中腰部账号产出偏散', detail: '发帖数量不低，但阅读和评论没有同步增长，需要收缩选题池。' },
      { label: '下周期目标', value: '优质笔记率提升 15%', detail: '先盯阅读效率和评论质量，再看总发布量。' },
    ],
    actions: [
      { title: '建立 Top 模板池', body: '把优质帖子数排名前 5 的运营拆出标题、封面、正文前 3 行和评论 CTA，作为下一周复用模板。', tone: 'sky' },
      { title: '压缩低效账号排期', body: '低效笔记连续偏高的账号先减少泛资讯内容，改为车型价格、优惠节点、竞品对比三类可验证内容。', tone: 'amber' },
      { title: '按负责人复盘', body: '周会不只看账号排名，也看运营负责人维度：发帖量、阅读量、优质帖数和低效帖数一起看。', tone: 'emerald' },
    ],
  };
}

function buildAiReport({
  selectedAccount,
}: {
  selectedAccount: string;
}): AiReport {
  return buildMockAiReport(selectedAccount);
}

type CarMetric = {
  posts: number;
  totalViews: number;
  totalComments: number;
  totalEngagement: number;
  qualityCount: number;
};

function createEmptyCarMetric(): CarMetric {
  return {
    posts: 0,
    totalViews: 0,
    totalComments: 0,
    totalEngagement: 0,
    qualityCount: 0,
  };
}

function addCarMetric(metric: CarMetric, note: XHSAccountNote) {
  const engagement = toNumber(note.liked_count) + toNumber(note.comment_count) + toNumber(note.collected_count) + toNumber(note.share_count);
  metric.posts += 1;
  metric.totalViews += toNumber(note.view_count);
  metric.totalComments += toNumber(note.comment_count);
  metric.totalEngagement += engagement;
  metric.qualityCount += isQualityNote(note) ? 1 : 0;
}

function metricToCarTypeStats(name: string, brand: string, metric: CarMetric, totalPosts: number, model?: string): CarTypeStats {
  return {
    name,
    brand,
    model,
    posts: metric.posts,
    totalViews: metric.totalViews,
    totalComments: metric.totalComments,
    totalEngagement: metric.totalEngagement,
    avgViews: metric.totalViews / Math.max(1, metric.posts),
    avgComments: metric.totalComments / Math.max(1, metric.posts),
    qualityCount: metric.qualityCount,
    share: metric.posts / Math.max(1, totalPosts),
  };
}

function buildCarTypeStats(notes: XHSAccountNote[], vehicleMatches: Map<string, VehicleMatchResult>): CarTypeStats[] {
  const brandMap = new Map<string, {
    brand: string;
    metric: CarMetric;
    models: Map<string, { model: string; metric: CarMetric }>;
  }>();

  notes.forEach((note) => {
    const match = getCachedVehicleMatch(note, vehicleMatches);
    const brandGroup = brandMap.get(match.brand) || {
      brand: match.brand,
      metric: createEmptyCarMetric(),
      models: new Map<string, { model: string; metric: CarMetric }>(),
    };
    const modelGroup = brandGroup.models.get(match.model) || {
      model: match.model,
      metric: createEmptyCarMetric(),
    };
    addCarMetric(brandGroup.metric, note);
    addCarMetric(modelGroup.metric, note);
    brandGroup.models.set(match.model, modelGroup);
    brandMap.set(match.brand, brandGroup);
  });

  const totalPosts = Math.max(1, notes.length);
  const rows = Array.from(brandMap.values()).map((group) => ({
    ...metricToCarTypeStats(group.brand, group.brand, group.metric, totalPosts),
    models: Array.from(group.models.values())
      .map((modelGroup) => metricToCarTypeStats(modelGroup.model, group.brand, modelGroup.metric, group.metric.posts, modelGroup.model))
      .sort((a, b) => b.posts - a.posts || b.totalViews - a.totalViews),
  })).sort((a, b) => b.posts - a.posts || b.totalViews - a.totalViews);

  return rows.length > 0 ? rows : [{
    name: '暂无样本',
    brand: '暂无样本',
    posts: 0,
    totalViews: 0,
    totalComments: 0,
    totalEngagement: 0,
    avgViews: 0,
    avgComments: 0,
    qualityCount: 0,
    share: 0,
    models: [],
  }];
}

function buildPostRankings(notes: XHSAccountNote[], limit = 7): PostRankingItem[] {
  return notes.map((note) => {
    const views = toNumber(note.view_count);
    const comments = toNumber(note.comment_count);
    const engagement = toNumber(note.liked_count) + comments + toNumber(note.collected_count) + toNumber(note.share_count);
    const title = (note.title || note.content || '未命名帖子').replace(/\s+/g, ' ').trim();
    return {
      id: String(note.id || note.feed_id || `${getNoteAccountName(note)}-${title}`),
      title,
      accountName: getNoteAccountName(note),
      coverImageUrl: normalizeImageUrl(note.cover_image_url || note.image_urls?.[0] || ''),
      postUrl: note.post_url || '',
      views,
      comments,
      engagement,
      score: views + comments * 180 + engagement * 18,
      note,
    };
  }).sort((a, b) => b.score - a.score).slice(0, limit);
}

function normalizeImageUrl(value: unknown): string {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  if (raw.startsWith('http://')) return `https://${raw.slice('http://'.length)}`;
  return raw;
}

function getInsightNoteGalleryUrls(note: XHSAccountNote): string[] {
  const urls = [
    note.cover_image_url,
    ...(Array.isArray(note.image_urls) ? note.image_urls : []),
  ]
    .map((url) => normalizeImageUrl(url))
    .filter(Boolean);
  return Array.from(new Set(urls));
}

function formatInsightPublishedAt(value?: string | null): string {
  if (!value) return '发布时间未记录';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${formatDateKey(date)} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function getInsightAccountInitial(note: XHSAccountNote): string {
  return String(note.profile_nickname || note.account_name || '账号').trim().slice(0, 1) || '账';
}

function getInsightContentPreview(note: XHSAccountNote): string {
  if (String(note.content || '').trim()) return String(note.content || '').trim();
  if (note.detail_synced_at) return '详情已同步，但正文仍为空。';
  return '暂未同步帖子正文。';
}

function buildTrendOption(trend: TrendPoint[], intro = false, chartWidth = 760): Record<string, unknown> {
  const maxViews = Math.max(1, ...trend.map((point) => point.views));
  const maxComments = Math.max(1, ...trend.map((point) => point.comments));
  const maxPosts = Math.max(1, ...trend.map((point) => point.posts));
  const lineMax = Math.max(1, maxComments, maxPosts);
  const isDense = trend.length > 14;
  const plotWidth = Math.max(220, chartWidth - 108);
  const slotWidth = plotWidth / Math.max(1, trend.length);
  const barWidth = Math.round(clamp(slotWidth * (isDense ? 0.42 : 0.52), isDense ? 10 : 24, isDense ? 28 : 56));
  const viewColor = '#111827';
  const viewHoverColor = '#020617';
  const commentColor = '#166534';
  const commentHoverColor = '#14532d';
  const postColor = '#6d28d9';
  const postHoverColor = '#4c1d95';
  const axisFormatter = (value: number) => {
    if (Math.abs(value) >= 10000) return `${Number((value / 10000).toFixed(1))}万`;
    return formatInteger(value);
  };

  return {
    animation: true,
    animationThreshold: 2000,
    animationDuration: 320,
    animationDurationUpdate: 260,
    animationEasing: 'quarticOut',
    animationEasingUpdate: 'quarticOut',
    stateAnimation: { duration: 160, easing: 'cubicOut' },
    color: [viewColor, commentColor, postColor],
    grid: { left: 56, right: 52, top: 52, bottom: isDense ? 30 : 40 },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 9,
      itemHeight: 9,
      icon: 'circle',
      itemGap: 16,
      textStyle: { color: '#334155', fontSize: 12, fontWeight: 900 },
      data: ['浏览', '评论', '发帖'],
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(15,23,42,0.96)',
      borderWidth: 0,
      padding: [10, 12],
      textStyle: { color: '#f8fbff', fontSize: 12 },
      axisPointer: {
        type: 'line',
        lineStyle: { color: 'rgba(15,23,42,0.20)', width: 1.5, type: 'solid' },
      },
      formatter(params: any[]) {
        const list = Array.isArray(params) ? params : [];
        const point = trend[list[0]?.dataIndex || 0];
        if (!point) return '';
        return [
          `<strong>${point.label}</strong> <span style="color:#cbd5e1">日趋势</span>`,
          `<span style="color:${viewColor}">●</span> 浏览 <b style="float:right;margin-left:18px">${formatInteger(point.views)}</b>`,
          `<span style="color:${commentColor}">●</span> 评论 <b style="float:right;margin-left:18px">${formatInteger(point.comments)}</b>`,
          `<span style="color:${postColor}">●</span> 发帖 <b style="float:right;margin-left:18px">${formatInteger(point.posts)}</b>`,
          `<span style="color:#cbd5e1">●</span> 互动 <b style="float:right;margin-left:18px">${formatInteger(point.engagement)}</b>`,
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'category',
      data: trend.map((point) => point.label),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: 'rgba(15,23,42,0.12)' } },
      axisLabel: {
        color: '#334155',
        fontSize: 11,
        fontWeight: 900,
        margin: 14,
        interval: isDense ? Math.ceil(trend.length / 8) : 0,
      },
    },
    yAxis: [
      {
        type: 'value',
        min: 0,
        max: Math.ceil(maxViews * 1.12),
        splitNumber: 4,
        name: '浏览',
        nameTextStyle: {
          color: '#64748b',
          fontSize: 11,
          fontWeight: 800,
          padding: [0, 0, 4, 0],
        },
        axisLabel: {
          show: true,
          color: '#64748b',
          fontSize: 11,
          fontWeight: 800,
          formatter: axisFormatter,
        },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: {
          show: true,
          lineStyle: {
            color: 'rgba(15,23,42,0.10)',
            type: 'dashed',
            width: 1,
          },
        },
      },
      {
        type: 'value',
        min: 0,
        max: Math.ceil(lineMax * 1.18),
        splitNumber: 4,
        name: '评论 / 发帖',
        nameTextStyle: {
          color: '#64748b',
          fontSize: 11,
          fontWeight: 800,
          padding: [0, 0, 4, 0],
        },
        axisLabel: {
          show: true,
          color: '#64748b',
          fontSize: 11,
          fontWeight: 800,
          formatter: axisFormatter,
        },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '浏览',
        type: 'bar',
        yAxisIndex: 0,
        data: trend.map((point) => intro ? 0 : point.views),
        barWidth,
        barMaxWidth: isDense ? 30 : 60,
        barCategoryGap: isDense ? '28%' : '36%',
        cursor: 'pointer',
        itemStyle: {
          color: viewColor,
          borderRadius: [10, 10, 3, 3],
          shadowBlur: 6,
          shadowOffsetY: 3,
          shadowColor: 'rgba(15,23,42,0.12)',
        },
        blur: {
          itemStyle: { opacity: 0.28 },
        },
        emphasis: {
          focus: 'self',
          itemStyle: { color: viewHoverColor, shadowBlur: 12, shadowOffsetY: 6, shadowColor: 'rgba(15,23,42,0.24)' },
        },
        animationDuration: 280,
        animationDurationUpdate: 240,
        animationDelay: (index: number) => index * 12,
        animationDelayUpdate: (index: number) => index * 8,
        z: 2,
      },
      {
        name: '评论',
        type: 'line',
        yAxisIndex: 1,
        data: trend.map((point) => intro ? 0 : point.comments),
        smooth: true,
        smoothMonotone: 'x',
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: false,
        cursor: 'pointer',
        lineStyle: { color: commentColor, width: 2.8, cap: 'round', join: 'round' },
        itemStyle: { color: commentColor, borderWidth: 0, shadowBlur: 8, shadowColor: 'rgba(22,101,52,0.20)' },
        blur: {
          lineStyle: { opacity: 0.2 },
          itemStyle: { opacity: 0.2 },
        },
        emphasis: {
          scale: 1.65,
          focus: 'self',
          showSymbol: true,
          itemStyle: { color: commentHoverColor, borderWidth: 0, shadowBlur: 14, shadowColor: 'rgba(20,83,45,0.28)' },
          lineStyle: { width: 3.8 },
        },
        animationDuration: 260,
        animationDurationUpdate: 220,
        animationDelay: (index: number) => 60 + index * 8,
        animationDelayUpdate: (index: number) => 40 + index * 6,
        z: 4,
      },
      {
        name: '发帖',
        type: 'line',
        yAxisIndex: 1,
        data: trend.map((point) => point.posts),
        smooth: false,
        symbol: 'circle',
        symbolSize: 5,
        showSymbol: false,
        cursor: 'pointer',
        lineStyle: { color: postColor, width: 2, type: 'dashed', cap: 'round', join: 'round' },
        itemStyle: { color: postColor, borderWidth: 0 },
        blur: {
          lineStyle: { opacity: 0.18 },
          itemStyle: { opacity: 0.2 },
        },
        emphasis: {
          scale: 1.7,
          focus: 'self',
          showSymbol: true,
          itemStyle: { color: postHoverColor, borderWidth: 0, shadowBlur: 12, shadowColor: 'rgba(76,29,149,0.28)' },
          lineStyle: { width: 3.2 },
        },
        animation: false,
        animationDuration: 0,
        animationDurationUpdate: 0,
        z: 5,
      },
    ],
  };
}

function buildOperatorPostOption(rows: OperatorPerformanceRow[], chartWidth = 760): Record<string, unknown> {
  const names = rows.map((row) => row.ownerName);
  const maxViews = Math.max(1, ...rows.map((row) => row.views));
  const maxLine = Math.max(1, ...rows.flatMap((row) => [row.comments, row.posts]));
  const slotWidth = Math.max(220, chartWidth - 112) / Math.max(1, rows.length);
  const barWidth = Math.round(clamp(slotWidth * 0.42, 18, 52));
  const denseAxis = rows.length > 14;
  const axisFormatter = (value: number) => Math.abs(value) >= 10000 ? `${Number((value / 10000).toFixed(1))}万` : formatInteger(value);
  return {
    animation: true,
    animationDuration: 240,
    animationDurationUpdate: 200,
    stateAnimation: { duration: 140, easing: 'cubicOut' },
    color: ['#111827', '#166534', '#6d28d9'],
    grid: { left: 56, right: 54, top: 52, bottom: denseAxis ? 72 : 46 },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 9,
      itemHeight: 9,
      icon: 'circle',
      itemGap: 16,
      textStyle: { color: '#334155', fontSize: 12, fontWeight: 900 },
      data: ['发帖数', '阅读量', '评论量'],
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(15,23,42,0.96)',
      borderWidth: 0,
      padding: [10, 12],
      textStyle: { color: '#f8fbff', fontSize: 12 },
      formatter(params: any[]) {
        const list = Array.isArray(params) ? params : [];
        const row = rows[list[0]?.dataIndex || 0];
        if (!row) return '';
        return [
          `<strong>${row.ownerName}</strong> <span style="color:#cbd5e1">${row.ownerRole}</span>`,
          `<span style="color:#111827">●</span> 发帖 <b style="float:right;margin-left:18px">${formatInteger(row.posts)}</b>`,
          `<span style="color:#166534">●</span> 阅读 <b style="float:right;margin-left:18px">${formatInteger(row.views)}</b>`,
          `<span style="color:#6d28d9">●</span> 评论 <b style="float:right;margin-left:18px">${formatInteger(row.comments)}</b>`,
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'category',
      data: names,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: 'rgba(15,23,42,0.12)' } },
      axisLabel: { color: '#334155', fontSize: 11, fontWeight: 900, margin: 14, interval: 0, rotate: denseAxis ? 35 : 0 },
    },
    yAxis: [
      {
        type: 'value',
        min: 0,
        max: Math.ceil(maxLine * 1.2),
        name: '发帖 / 评论',
        axisLabel: { color: '#64748b', fontSize: 11, fontWeight: 800, formatter: axisFormatter },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: true, lineStyle: { color: 'rgba(15,23,42,0.10)', type: 'dashed', width: 1 } },
      },
      {
        type: 'value',
        min: 0,
        max: Math.ceil(maxViews * 1.12),
        name: '阅读',
        axisLabel: { color: '#64748b', fontSize: 11, fontWeight: 800, formatter: axisFormatter },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '发帖数',
        type: 'bar',
        yAxisIndex: 0,
        data: rows.map((row) => row.posts),
        barWidth,
        itemStyle: { color: '#111827', borderRadius: [10, 10, 3, 3], shadowBlur: 6, shadowOffsetY: 3, shadowColor: 'rgba(15,23,42,0.12)' },
      },
      {
        name: '阅读量',
        type: 'line',
        yAxisIndex: 1,
        data: rows.map((row) => row.views),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#166534', width: 2.8, cap: 'round', join: 'round' },
        itemStyle: { color: '#166534' },
      },
      {
        name: '评论量',
        type: 'line',
        yAxisIndex: 0,
        data: rows.map((row) => row.comments),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#6d28d9', width: 2.4, type: 'dashed', cap: 'round', join: 'round' },
        itemStyle: { color: '#6d28d9' },
      },
    ],
  };
}

function buildOperatorQualityOption(rows: OperatorPerformanceRow[], chartWidth = 760): Record<string, unknown> {
  const slotWidth = Math.max(320, chartWidth - 90) / Math.max(1, rows.length);
  const barWidth = Math.round(clamp(slotWidth * 0.42, 18, 44));
  const denseAxis = rows.length > 14;
  return {
    animation: true,
    animationDuration: 220,
    animationDurationUpdate: 180,
    stateAnimation: { duration: 140, easing: 'cubicOut' },
    grid: { left: 48, right: 24, top: 36, bottom: denseAxis ? 72 : 46 },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(15,23,42,0.96)',
      borderWidth: 0,
      padding: [10, 12],
      textStyle: { color: '#f8fbff', fontSize: 12 },
      formatter(params: any[]) {
        const row = rows[(Array.isArray(params) ? params[0]?.dataIndex : 0) || 0];
        if (!row) return '';
        return [
          `<strong>${row.ownerName}</strong>`,
          `优质笔记 <b style="float:right;margin-left:18px">${formatInteger(row.qualityCount)}</b>`,
          `低效笔记 <b style="float:right;margin-left:18px">${formatInteger(row.lowQualityCount)}</b>`,
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'category',
      data: rows.map((row) => row.ownerName),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: 'rgba(15,23,42,0.12)' } },
      axisLabel: { color: '#334155', fontSize: 11, fontWeight: 900, margin: 14, interval: 0, rotate: denseAxis ? 35 : 0 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      axisLabel: { color: '#64748b', fontSize: 11, fontWeight: 800 },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: true, lineStyle: { color: 'rgba(15,23,42,0.10)', type: 'dashed', width: 1 } },
    },
    series: [{
      name: '优质笔记数',
      type: 'bar',
      data: rows.map((row) => row.qualityCount),
      barWidth,
      label: { show: true, position: 'top', color: '#166534', fontSize: 11, fontWeight: 900 },
      itemStyle: { color: '#166534', borderRadius: [10, 10, 3, 3], shadowBlur: 6, shadowOffsetY: 3, shadowColor: 'rgba(22,101,52,0.14)' },
    }],
  };
}

function buildOperatorPaidRatioOption(rows: OperatorPerformanceRow[], chartWidth = 760): Record<string, unknown> {
  const slotWidth = Math.max(320, chartWidth - 112) / Math.max(1, rows.length);
  const barWidth = Math.round(clamp(slotWidth * 0.5, 18, 46));
  const denseAxis = rows.length > 14;
  const maxPosts = Math.max(1, ...rows.map((row) => row.posts));
  return {
    animation: true,
    animationDuration: 240,
    animationDurationUpdate: 200,
    stateAnimation: { duration: 140, easing: 'cubicOut' },
    color: ['#0f766e', '#cbd5e1', '#ea580c'],
    grid: { left: 50, right: 58, top: 52, bottom: denseAxis ? 72 : 46 },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 9,
      itemHeight: 9,
      icon: 'circle',
      itemGap: 16,
      textStyle: { color: '#334155', fontSize: 12, fontWeight: 900 },
      data: ['投流笔记量', '未投流笔记量', '投流占比'],
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(15,23,42,0.96)',
      borderWidth: 0,
      padding: [10, 12],
      textStyle: { color: '#f8fbff', fontSize: 12 },
      formatter(params: any[]) {
        const row = rows[(Array.isArray(params) ? params[0]?.dataIndex : 0) || 0];
        if (!row) return '';
        return [
          `<strong>${row.ownerName}</strong>`,
          `<span style="color:#0f766e">●</span> 投流笔记 <b style="float:right;margin-left:18px">${formatInteger(row.paidPosts)}</b>`,
          `<span style="color:#cbd5e1">●</span> 未投流笔记 <b style="float:right;margin-left:18px">${formatInteger(row.organicPosts)}</b>`,
          `<span style="color:#ea580c">●</span> 投流占比 <b style="float:right;margin-left:18px">${roundNumber(row.paidRatio * 100, 1)}%</b>`,
          `<span style="color:#94a3b8">总笔记</span> <b style="float:right;margin-left:18px">${formatInteger(row.posts)}</b>`,
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'category',
      data: rows.map((row) => row.ownerName),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: 'rgba(15,23,42,0.12)' } },
      axisLabel: { color: '#334155', fontSize: 11, fontWeight: 900, margin: 14, interval: 0, rotate: denseAxis ? 35 : 0 },
    },
    yAxis: [
      {
        type: 'value',
        min: 0,
        max: Math.ceil(maxPosts * 1.16),
        name: '笔记量',
        axisLabel: { color: '#64748b', fontSize: 11, fontWeight: 800 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: true, lineStyle: { color: 'rgba(15,23,42,0.10)', type: 'dashed', width: 1 } },
      },
      {
        type: 'value',
        min: 0,
        max: 100,
        name: '投流占比',
        axisLabel: { color: '#64748b', fontSize: 11, fontWeight: 800, formatter: '{value}%' },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '投流笔记量',
        type: 'bar',
        stack: 'posts',
        yAxisIndex: 0,
        data: rows.map((row) => row.paidPosts),
        barWidth,
        itemStyle: { color: '#0f766e', borderRadius: [0, 0, 4, 4] },
      },
      {
        name: '未投流笔记量',
        type: 'bar',
        stack: 'posts',
        yAxisIndex: 0,
        data: rows.map((row) => row.organicPosts),
        barWidth,
        itemStyle: { color: '#cbd5e1', borderRadius: [10, 10, 0, 0] },
      },
      {
        name: '投流占比',
        type: 'line',
        yAxisIndex: 1,
        data: rows.map((row) => roundNumber(row.paidRatio * 100, 1)),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#ea580c', width: 2.8, cap: 'round', join: 'round' },
        itemStyle: { color: '#ea580c' },
      },
    ],
  };
}

function EchartPanel({ ready, optionBuilder, className }: { ready: boolean; optionBuilder: (width: number) => Record<string, unknown>; className?: string }) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<any>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  useEffect(() => {
    if (!ready || !chartRef.current || typeof window === 'undefined' || !window.echarts) return undefined;
    const chart = window.echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    chartInstanceRef.current = chart;
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserverRef.current = resizeObserver;
    resizeObserver.observe(chartRef.current);
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
      chartInstanceRef.current = null;
      resizeObserverRef.current = null;
    };
  }, [ready]);

  useEffect(() => {
    const chart = chartInstanceRef.current;
    if (!ready || !chart || !chartRef.current) return;
    chart.setOption(optionBuilder(chartRef.current.clientWidth || 760), true);
    chart.resize();
  }, [optionBuilder, ready]);

  return ready ? <div ref={chartRef} className={cn('h-full w-full', className)} /> : <div className="grid h-full place-items-center text-sm font-medium text-slate-500">正在加载图表...</div>;
}

type OperatorAccountScope = {
  assigned_owner_count: number;
  assigned_account_count: number;
  assigned_active_account_count: number;
  covered_owner_count: number;
  covered_account_count: number;
  unmatched_profile_account_count: number;
};

function OperatorPerformanceSection({ rows, range, ready, accountScope }: { rows: OperatorPerformanceRow[]; range: DateRange; ready: boolean; accountScope: OperatorAccountScope | null }) {
  const chartRows = rows;
  const postOptionBuilder = useCallback((width: number) => buildOperatorPostOption(chartRows, width), [chartRows]);
  const qualityOptionBuilder = useCallback((width: number) => buildOperatorQualityOption(chartRows, width), [chartRows]);
  const paidRatioOptionBuilder = useCallback((width: number) => buildOperatorPaidRatioOption(chartRows, width), [chartRows]);

  if (rows.length === 0) {
    return (
      <section className={cn('p-5', PANEL_CLASS)}>
        <PanelTitle eyebrow="运营负责人" title="运营负责人总表" suffix="当前时间段" />
        <div className="mt-4">
          <EmptyBlock text="当前时间段暂无可统计的运营负责人数据" />
        </div>
      </section>
    );
  }
  const accountCount = new Set(rows.flatMap((row) => row.accountNames)).size;
  const scopeLabel = accountScope
    ? `最新分配 · ${accountScope.assigned_owner_count} 人 / ${accountScope.assigned_account_count} 账号`
    : `最新分配 · ${rows.length} 人 / ${accountCount} 账号`;
  return (
    <section className={cn('p-5', PANEL_CLASS)}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <PanelTitle eyebrow="运营负责人" title="运营负责人总表" suffix={scopeLabel} />
        <button
          type="button"
          onClick={() => exportOperatorPerformanceRows(rows, range)}
          className="inline-flex h-9 items-center justify-center rounded-2xl border border-slate-200 bg-white px-4 text-xs font-bold text-slate-700 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:bg-slate-50"
        >
          导出表格
        </button>
      </div>

      <div className="mt-4 overflow-hidden rounded-[26px] border border-slate-100 shadow-[0_18px_46px_rgba(15,23,42,0.06)]">
        <div className="overflow-x-auto">
          <div className="min-w-[1340px]">
            <div className="sticky top-0 z-[1] grid grid-cols-[48px_1fr_2fr_repeat(10,minmax(78px,1fr))] bg-slate-950 px-4 py-3 text-[11px] font-bold uppercase tracking-[0.08em] text-white/70">
              <span>#</span>
              <span>运营负责人</span>
              <span>负责账号</span>
              <span className="text-right">笔记</span>
              <span className="text-right">阅读</span>
              <span className="text-right">收藏</span>
              <span className="text-right">评论</span>
              <span className="text-right">互动</span>
              <span className="text-right">优质</span>
              <span className="text-right">低效</span>
              <span className="text-right">自然客资</span>
              <span className="text-right">特殊自然</span>
              <span className="text-right">广告客资</span>
            </div>
            <div className="max-h-[224px] overflow-y-auto bg-white">
              {rows.map((row, index) => (
                <div key={row.ownerId} className="grid grid-cols-[48px_1fr_2fr_repeat(10,minmax(78px,1fr))] items-center border-t border-slate-100 px-4 py-3 text-sm transition hover:bg-slate-50/80">
                  <span className="grid h-7 w-7 place-items-center rounded-full bg-slate-100 text-xs font-black text-slate-500">{index + 1}</span>
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-slate-950">{row.ownerName}</div>
                    <div className="mt-0.5 text-[11px] font-semibold text-slate-400">{row.ownerRole}</div>
                  </div>
                  <div className="min-w-0 pr-4" title={row.accountNames.join(' / ')}>
                    <div className="truncate text-xs font-semibold text-slate-600">{row.accountNames.join(' / ')}</div>
                    <div className="mt-0.5 text-[11px] font-bold text-slate-400">{row.accountCount} 个账号</div>
                  </div>
                  <span className="text-right font-semibold text-slate-700">{formatInteger(row.posts)}</span>
                  <span className="text-right font-semibold text-slate-950">{formatInteger(row.views)}</span>
                  <span className="text-right font-semibold text-slate-700">{formatInteger(row.collects)}</span>
                  <span className="text-right font-semibold text-slate-700">{formatInteger(row.comments)}</span>
                  <span className="text-right font-semibold text-slate-950">{formatInteger(row.engagement)}</span>
                  <span className="text-right font-semibold text-emerald-700">{formatInteger(row.qualityCount)}</span>
                  <span className="text-right font-semibold text-rose-700">{formatInteger(row.lowQualityCount)}</span>
                  <span className="text-right font-semibold text-sky-700">{formatInteger(row.naturalLeads)}</span>
                  <span className="text-right font-semibold text-amber-700">{formatInteger(row.specialNaturalLeads)}</span>
                  <span className="text-right font-semibold text-indigo-700">{formatInteger(row.adLeads)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4">
        <div className="overflow-hidden rounded-[26px] border border-slate-100 shadow-[0_18px_46px_rgba(15,23,42,0.06)]">
          <div className="rounded-[24px] border border-slate-100 bg-slate-50/55 p-4">
            <div className="mb-2 flex items-center justify-between">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">全部 {rows.length} 人</div>
                <h3 className="mt-1 text-base font-semibold text-slate-950">各运营对应发帖数 / 阅读量 / 评论量</h3>
              </div>
              <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-500 shadow-sm">柱=发帖 · 线=阅读/评论</span>
            </div>
            <div className="h-[360px]">
              <EchartPanel ready={ready} optionBuilder={postOptionBuilder} />
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4">
        <div className="overflow-hidden rounded-[26px] border border-slate-100 shadow-[0_18px_46px_rgba(15,23,42,0.06)]">
          <div className="rounded-[24px] border border-slate-100 bg-slate-50/55 p-4">
            <div className="mb-2 flex items-center justify-between">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">全部 {rows.length} 人</div>
                <h3 className="mt-1 text-base font-semibold text-slate-950">各运营对应优质帖子数</h3>
              </div>
              <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-500 shadow-sm">柱=优质帖子</span>
            </div>
            <div className="h-[300px]">
              <EchartPanel ready={ready} optionBuilder={qualityOptionBuilder} />
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4">
        <div className="overflow-hidden rounded-[26px] border border-slate-100 shadow-[0_18px_46px_rgba(15,23,42,0.06)]">
          <div className="rounded-[24px] border border-slate-100 bg-slate-50/55 p-4">
            <div className="mb-2 flex items-center justify-between">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">版面4 · 全部 {rows.length} 人</div>
                <h3 className="mt-1 text-base font-semibold text-slate-950">投流占比</h3>
              </div>
              <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-500 shadow-sm">柱=投流/未投流 · 线=投流占比</span>
            </div>
            <p className="mb-2 text-xs font-medium text-slate-500">
              判断逻辑：创意报表或简单投报表存在对应笔记 ID 即视为投流；投流占比 = 投流笔记量 / 总笔记量。
            </p>
            <div className="h-[340px]">
              <EchartPanel ready={ready} optionBuilder={paidRatioOptionBuilder} />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function TrendChart({ trend, ready, className }: { trend: TrendPoint[]; ready: boolean; className?: string }) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<any>(null);

  useEffect(() => {
    if (!ready || !chartRef.current || typeof window === 'undefined' || !window.echarts) return undefined;
    const chart = window.echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    chartInstanceRef.current = chart;
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(chartRef.current);
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
      chartInstanceRef.current = null;
    };
  }, [ready]);

  useEffect(() => {
    const chart = chartInstanceRef.current;
    if (!ready || !chart || !chartRef.current) return;
    chart.setOption(buildTrendOption(trend, false, chartRef.current.clientWidth || 760), true);
    chart.resize();
  }, [trend, ready]);

  return (
    <div className={cn('relative h-[288px]', className)}>
      {ready ? (
        <div ref={chartRef} className="h-full w-full" />
      ) : (
        <div className="grid h-full place-items-center text-sm font-medium text-slate-500">正在加载趋势图...</div>
      )}
      </div>
  );
}

function DateRangePicker({ range, onChange }: { range: DateRange; onChange: (range: DateRange) => void }) {
  const maxDate = useMemo(() => getYesterday(), []);
  const [open, setOpen] = useState(false);
  const [viewMonth, setViewMonth] = useState(() => new Date(range.end.getFullYear(), range.end.getMonth(), 1));
  const [draftStart, setDraftStart] = useState<Date | null>(null);
  const days = useMemo(() => getCalendarDays(viewMonth), [viewMonth]);

  useEffect(() => {
    if (!open) return;
    setViewMonth(new Date(range.end.getFullYear(), range.end.getMonth(), 1));
  }, [open, range.end]);

  const applyDate = (date: Date) => {
    if (isAfterDay(date, maxDate)) return;
    const picked = getStartOfDay(date);
    if (!draftStart) {
      setDraftStart(picked);
      onChange({ start: picked, end: getEndOfDay(picked) });
      return;
    }

    const start = isBeforeDay(picked, draftStart) ? picked : draftStart;
    const end = isBeforeDay(picked, draftStart) ? draftStart : picked;
    onChange({ start: getStartOfDay(start), end: getEndOfDay(end) });
    setDraftStart(null);
    setOpen(false);
  };

  const resetRange = () => {
    const nextRange = getDefaultDateRange();
    onChange(nextRange);
    setDraftStart(null);
    setViewMonth(new Date(nextRange.end.getFullYear(), nextRange.end.getMonth(), 1));
  };

  return (
    <div className="relative z-50">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex h-10 min-w-[238px] items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white px-3.5 text-sm font-semibold text-slate-800 shadow-[0_12px_28px_rgba(15,23,42,0.08)] outline-none transition hover:border-slate-400"
      >
        <span>{getDateRangeLabel(range)}</span>
        <ChevronDown className={cn('h-3.5 w-3.5 text-slate-400 transition', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute right-0 z-[80] mt-2 w-[320px] rounded-[26px] border border-slate-200 bg-white p-3 shadow-[0_24px_70px_rgba(15,23,42,0.14)] ring-1 ring-slate-100">
          <div className="flex items-center justify-between px-1 pb-3">
            <button
              type="button"
              onClick={() => setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() - 1, 1))}
              className="grid h-8 w-8 place-items-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:border-slate-400 hover:text-slate-950"
              aria-label="上个月"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <div className="text-base font-black tracking-[-0.02em] text-slate-950">{getMonthTitle(viewMonth)}</div>
            <button
              type="button"
              onClick={() => setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() + 1, 1))}
              className="grid h-8 w-8 place-items-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:border-slate-400 hover:text-slate-950"
              aria-label="下个月"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          <div className="grid grid-cols-7 gap-1 px-1 text-center text-[11px] font-bold text-slate-400">
            {['日', '一', '二', '三', '四', '五', '六'].map((day) => <div key={day} className="py-1">{day}</div>)}
          </div>

          <div className="mt-1 grid grid-cols-7 gap-1">
            {days.map((date) => {
              const disabled = isAfterDay(date, maxDate);
              const muted = date.getMonth() !== viewMonth.getMonth();
              const selectedStart = isSameDay(date, range.start);
              const selectedEnd = isSameDay(date, range.end);
              const selected = selectedStart || selectedEnd;
              const inRange = isDateInRange(date, range);
              const drafting = Boolean(draftStart && isSameDay(date, draftStart));
              return (
                <button
                  key={formatDateKey(date)}
                  type="button"
                  disabled={disabled}
                  onClick={() => applyDate(date)}
                  className={cn(
                    'grid h-9 place-items-center rounded-xl text-sm font-semibold transition',
                    muted ? 'text-slate-300' : 'text-slate-700',
                    inRange && !selected && 'bg-slate-100 text-slate-900',
                    selected && 'bg-slate-950 text-white shadow-[0_10px_20px_rgba(15,23,42,0.22)]',
                    drafting && 'ring-2 ring-slate-400',
                    disabled && 'cursor-not-allowed bg-slate-50 text-slate-200',
                    !disabled && !selected && 'hover:bg-slate-100 hover:text-slate-950',
                  )}
                >
                  {date.getDate()}
                </button>
              );
            })}
          </div>

          <div className="mt-3 flex items-center justify-between gap-3 px-1 text-[11px] font-medium text-slate-500">
            <span>{draftStart ? '请选择结束日期' : '先选择开始日期，再选择结束日期，最晚只能选昨天'}</span>
            <button type="button" onClick={resetRange} className="shrink-0 font-bold text-slate-700 transition hover:text-slate-950">重置</button>
          </div>
        </div>
      )}
    </div>
  );
}

function MiniSparkline({ id, values }: { id: string; values: number[] }) {
  const safeValues = values.length > 0 ? values : [0];
  const max = Math.max(1, ...safeValues);
  const step = safeValues.length <= 1 ? 144 : 144 / (safeValues.length - 1);
  const points = safeValues.map((value, index) => `${index * step},${56 - (value / max) * 42}`).join(' ');
  return (
    <svg viewBox="0 0 144 60" className="h-12 w-full overflow-visible">
      <defs>
        <linearGradient id={`spark-${id}`} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#111827" />
          <stop offset="100%" stopColor="#166534" />
        </linearGradient>
      </defs>
      <polyline points={`0,60 ${points} 144,60`} fill="rgba(15,23,42,0.08)" stroke="none" />
      <polyline points={points} fill="none" stroke="#e2e8f0" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points={points} fill="none" stroke={`url(#spark-${id})`} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function buildScoreFormulaParts(account: AccountSummary) {
  return [
    { label: '样本信心', value: account.scoreBreakdown.sampleConfidenceScore, sign: '+' },
    { label: '均浏览', value: account.scoreBreakdown.avgViewsScore, sign: '+' },
    { label: '均评论', value: account.scoreBreakdown.avgCommentsScore, sign: '+' },
    { label: '均互动', value: account.scoreBreakdown.avgEngagementScore, sign: '+' },
    { label: '收藏分享', value: account.scoreBreakdown.avgCollectShareScore, sign: '+' },
    { label: '点赞', value: account.scoreBreakdown.avgLikesScore, sign: '+' },
    { label: '强样本率', value: account.scoreBreakdown.strongRateScore, sign: '+' },
    { label: '低信号惩罚', value: account.scoreBreakdown.weakPenalty, sign: '-' },
  ];
}

function AccountRankingPanel({
  accounts,
  posts,
  accountSort,
  postSort,
  onAccountSortChange,
  onPostSortChange,
}: {
  accounts: AccountSummary[];
  posts: PostRankingItem[];
  accountSort: RankingSortKey;
  postSort: RankingSortKey;
  onAccountSortChange: (value: RankingSortKey) => void;
  onPostSortChange: (value: RankingSortKey) => void;
}) {
  const maxScore = Math.max(1, ...accounts.map((account) => getAccountRankingValue(account, accountSort)));
  const maxPostScore = Math.max(1, ...posts.map((post) => getPostRankingValue(post, postSort)));
  const [tooltip, setTooltip] = useState<
    | { kind: 'account'; account: AccountSummary; x: number; y: number }
    | { kind: 'post'; post: PostRankingItem; x: number; y: number }
    | null
  >(null);
  const placeTooltip = (
    event: MouseEvent,
    payload: { kind: 'account'; account: AccountSummary } | { kind: 'post'; post: PostRankingItem },
  ) => {
    const width = payload.kind === 'account' ? 360 : 290;
    const height = payload.kind === 'account' ? 420 : 210;
    const padding = 14;
    const left = Math.max(padding, Math.min(event.clientX + 16, window.innerWidth - width - padding));
    const top = Math.max(padding, Math.min(event.clientY + 16, window.innerHeight - height - padding));
    setTooltip({ ...payload, x: left, y: top });
  };

  return (
    <div className="relative h-full min-h-0 overflow-hidden p-0">
      {accounts.length > 0 || posts.length > 0 ? (
        <div className="grid h-full min-h-0 gap-3 overflow-hidden sm:grid-cols-2">
          <div className="min-h-0 space-y-2 overflow-y-auto pr-1">
            <div className="sticky top-0 z-10 mb-2 flex items-center justify-between gap-3 rounded-2xl bg-slate-50/95 px-2 py-1.5 backdrop-blur">
              <span className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">账号排行</span>
              <select
                value={accountSort}
                onChange={(event) => onAccountSortChange(event.target.value as RankingSortKey)}
                className={cn(CONTROL_CLASS, 'h-8 w-28 px-2 text-xs shadow-sm')}
              >
                {RANKING_SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </div>
            {accounts.slice(0, 7).map((account, index) => {
              const rankingValue = getAccountRankingValue(account, accountSort);
              const width = Math.max(8, (rankingValue / maxScore) * 100);
              return (
                <div
                  key={account.accountName}
                  onMouseEnter={(event) => placeTooltip(event, { kind: 'account', account })}
                  onMouseMove={(event) => placeTooltip(event, { kind: 'account', account })}
                  onMouseLeave={() => setTooltip(null)}
                  className="group relative grid grid-cols-[28px_minmax(0,1fr)_62px] items-center gap-2 rounded-2xl border border-slate-100 bg-white px-2.5 py-2 shadow-sm transition hover:z-40 hover:-translate-y-0.5 hover:border-slate-200 hover:shadow-md"
                >
                  <div className={cn(
                    'grid h-7 w-7 place-items-center rounded-xl text-[11px] font-bold shadow-sm',
                    index === 0 ? 'bg-slate-950 text-white' : 'bg-white text-slate-500',
                  )}>
                    {index + 1}
                  </div>
                  <div className="min-w-0">
                    <div className="mb-1.5 flex items-center justify-between gap-2">
                      <span className="truncate text-xs font-bold text-slate-800">{account.accountName}</span>
                      <span className="shrink-0 text-[10px] font-bold text-slate-500">{getRankingSortLabel(accountSort)} {formatInteger(rankingValue)}</span>
                    </div>
                    <div className="h-2.5 overflow-hidden rounded-full bg-slate-100 shadow-inner">
                      <div
                        className={cn(
                          'h-full rounded-full ring-1 ring-inset ring-white/60',
                          index === 0 ? 'bg-slate-950' : index === 1 ? 'bg-emerald-800' : 'bg-slate-200',
                        )}
                        style={{ width: `${width}%` }}
                      />
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] font-semibold text-slate-500">
                      <span>均评 {formatScore(account.avgComments)}</span>
                      <span>均互动 {formatScore(account.avgEngagement)}</span>
                      <span>强 {formatInteger(account.strongPostCount)} / 弱 {formatInteger(account.weakPostCount)}</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-base font-semibold tracking-tight text-slate-950">{accountSort === 'score' ? formatScore(rankingValue) : formatInteger(rankingValue)}</div>
                    <div className="text-[10px] font-semibold text-slate-500">{getRankingSortLabel(accountSort)}</div>
                    <div className="text-[10px] font-semibold text-slate-400">{formatInteger(account.posts)} 帖</div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="min-h-0 space-y-2 overflow-hidden rounded-[22px] border border-slate-100 bg-white p-2 shadow-sm">
            <div className="h-full min-h-0 space-y-2 overflow-y-auto pr-1">
              <div className="sticky top-0 z-10 mb-2 flex items-center justify-between gap-3 rounded-2xl bg-white/95 px-1 py-1.5 backdrop-blur">
                <span className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">帖子排行</span>
                <select
                  value={postSort}
                  onChange={(event) => onPostSortChange(event.target.value as RankingSortKey)}
                  className={cn(CONTROL_CLASS, 'h-8 w-28 px-2 text-xs shadow-sm')}
                >
                  {RANKING_SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </div>
              {posts.length > 0 ? posts.slice(0, 7).map((post, index) => {
                const rankingValue = getPostRankingValue(post, postSort);
                const width = Math.max(8, (rankingValue / maxPostScore) * 100);
                return (
                  <div
                    key={post.id}
                    onMouseEnter={(event) => placeTooltip(event, { kind: 'post', post })}
                    onMouseMove={(event) => placeTooltip(event, { kind: 'post', post })}
                    onMouseLeave={() => setTooltip(null)}
                    className="group relative rounded-2xl border border-slate-100 bg-white px-2.5 py-2 shadow-sm transition hover:z-40 hover:-translate-y-0.5 hover:border-slate-200 hover:shadow-md"
                  >
                    <div className="flex items-start gap-2">
                      <div className={cn(
                        'mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-lg text-[10px] font-black',
                        index === 0 ? 'bg-slate-950 text-white' : 'bg-white text-slate-500',
                      )}>
                        {index + 1}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="line-clamp-1 text-xs font-bold text-slate-800">{post.title}</div>
                        <div className="mt-1 flex items-center justify-between gap-2 text-[10px] font-semibold text-slate-500">
                          <span className="truncate">{post.accountName}</span>
                          <span className="shrink-0">{getRankingSortLabel(postSort)} {formatInteger(rankingValue)}</span>
                        </div>
                        <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100 shadow-inner">
                          <div className={cn('h-full rounded-full', index === 0 ? 'bg-slate-950' : index === 1 ? 'bg-emerald-800' : 'bg-slate-200')} style={{ width: `${width}%` }} />
                        </div>
                        <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] font-semibold text-slate-500">
                          <span>评论 {formatInteger(post.comments)}</span>
                          <span>互动 {formatInteger(post.engagement)}</span>
                        </div>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="text-sm font-bold text-slate-950">{postSort === 'score' ? formatInteger(rankingValue) : formatInteger(rankingValue)}</div>
                        <div className="text-[10px] font-semibold text-slate-500">{getRankingSortLabel(postSort)}</div>
                      </div>
                    </div>
                  </div>
                );
              }) : (
                <EmptyBlock text="当前范围暂无帖子样本" />
              )}
            </div>
          </div>
        </div>
      ) : (
        <EmptyBlock text="当前范围暂无账号样本" />
      )}
      {tooltip && typeof document !== 'undefined' ? createPortal(
        <div
          className="pointer-events-none fixed z-[9999] max-h-[calc(100vh-28px)] overflow-y-auto rounded-[20px] border border-slate-700 bg-slate-950 p-3 text-white shadow-[0_22px_60px_rgba(15,23,42,0.38)]"
          style={{ left: tooltip.x, top: tooltip.y, width: tooltip.kind === 'account' ? 360 : 290 }}
        >
          {tooltip.kind === 'account' ? (
            (() => {
              const scoreFormulaParts = buildScoreFormulaParts(tooltip.account);
              const positiveScoreTotal = scoreFormulaParts
                .filter((part) => part.sign === '+')
                .reduce((sum, part) => sum + part.value, 0);
              return (
            <>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-xs font-black">{tooltip.account.accountName}</div>
                  <div className="mt-1 text-[10px] font-semibold text-slate-300">{tooltip.account.status} · {tooltip.account.nextAction}</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-lg font-black">{formatScore(tooltip.account.score)}</div>
                  <div className="text-[10px] font-semibold text-slate-400">综合分</div>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-1.5">
                {[
                  ['发帖', `${formatInteger(tooltip.account.posts)} 条`],
                  ['总浏览', formatInteger(tooltip.account.totalViews)],
                  ['均浏览', formatInteger(tooltip.account.avgViews)],
                  ['总评论', formatInteger(tooltip.account.totalComments)],
                  ['均评论', formatScore(tooltip.account.avgComments)],
                  ['总互动', formatInteger(tooltip.account.totalEngagement)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl bg-white/10 px-2 py-1.5">
                    <div className="text-[9px] font-semibold text-slate-400">{label}</div>
                    <div className="mt-0.5 truncate text-[11px] font-black text-white">{value}</div>
                  </div>
                ))}
              </div>
              {tooltip.account.missingInteractionMetrics && (
                <div className="mt-3 rounded-xl border border-amber-300/30 bg-amber-300/10 px-2 py-1.5 text-[10px] font-semibold leading-relaxed text-amber-100">
                  当前 account-notes 返回的评论/收藏/分享字段为 0；如果对齐 prototype 历史缓存口径，需要接入 analysis_runs 里的已生成样本。
                </div>
              )}
              <div className="mt-3 rounded-2xl border border-white/10 bg-slate-950/70 p-2.5 text-[10px] font-semibold leading-relaxed text-slate-300">
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <span className="text-slate-100">综合分计算公式</span>
                  <span className="text-[11px] font-black text-emerald-300">{formatScore(tooltip.account.score)}</span>
                </div>
                <div className="text-slate-400">
                  综合分 = {scoreFormulaParts.map((part, index) => (
                    <span key={part.label}>
                      {index === 0 ? '' : ` ${part.sign} `}
                      {formatScore(part.value)}
                    </span>
                  ))} = <span className="text-slate-100">{formatScore(tooltip.account.score)}</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
                  {scoreFormulaParts.map((part) => (
                    <div key={part.label} className="flex items-center justify-between gap-2">
                      <span>{part.label}</span>
                      <span className={part.sign === '-' ? 'text-rose-300' : 'text-emerald-300'}>
                        {part.sign}{formatScore(part.value)}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex items-center justify-between border-t border-white/10 pt-2">
                  <span>正向项合计</span>
                  <span className="text-emerald-300">+{formatScore(positiveScoreTotal)}</span>
                </div>
              </div>
            </>
              );
            })()
          ) : (
            <>
              <div className="line-clamp-2 text-xs font-black leading-snug">{tooltip.post.title}</div>
              <div className="mt-1 truncate text-[10px] font-semibold text-slate-400">{tooltip.post.accountName}</div>
              <div className="mt-3 grid grid-cols-2 gap-1.5">
                {[
                  ['综合分', formatInteger(tooltip.post.score)],
                  ['浏览', formatInteger(tooltip.post.views)],
                  ['评论', formatInteger(tooltip.post.comments)],
                  ['互动', formatInteger(tooltip.post.engagement)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl bg-white/10 px-2 py-1.5">
                    <div className="text-[9px] font-semibold text-slate-400">{label}</div>
                    <div className="mt-0.5 truncate text-[11px] font-black text-white">{value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 rounded-xl bg-white/10 px-2 py-1.5 text-[10px] font-semibold text-slate-300">
                计算口径：浏览 + 评论 * 180 + 互动 * 18
              </div>
            </>
          )}
        </div>,
        document.body,
      ) : null}
    </div>
  );
}

function RankingDetailModal({
  accounts,
  posts,
  accountSort,
  postSort,
  onClose,
  onOpenPost,
}: {
  accounts: AccountSummary[];
  posts: PostRankingItem[];
  accountSort: RankingSortKey;
  postSort: RankingSortKey;
  onClose: () => void;
  onOpenPost: (note: XHSAccountNote) => void;
}) {
  const maxAccountScore = Math.max(1, ...accounts.map((account) => getAccountRankingValue(account, accountSort)));
  const maxPostScore = Math.max(1, ...posts.map((post) => getPostRankingValue(post, postSort)));

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[75] overflow-y-auto bg-slate-950/58 p-3 backdrop-blur-md sm:p-5"
      onClick={onClose}
    >
      <div
        className="mx-auto flex max-h-[90vh] w-full max-w-[1320px] flex-col overflow-hidden rounded-[32px] border border-slate-200 bg-white shadow-[0_34px_120px_rgba(15,23,42,0.32)]"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 px-5 py-4 sm:px-6">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-slate-400">排行详情</div>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">账号 / 帖子排行详情</h2>
            <p className="mt-2 text-sm font-medium text-slate-500">账号展示完整排行，帖子展示当前时间范围内综合分 Top 50。</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
          >
            关闭
          </button>
        </header>

        <div className="grid min-h-0 flex-1 gap-4 overflow-hidden p-4 lg:grid-cols-[minmax(420px,0.9fr)_minmax(520px,1.1fr)]">
          <section className="flex min-h-0 flex-col overflow-hidden rounded-[26px] border border-slate-100 bg-slate-50/60 p-4">
            <div className="mb-3 flex items-end justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-slate-950">账号完整排行</h3>
                <p className="mt-1 text-xs font-semibold text-slate-500">共 {formatInteger(accounts.length)} 个账号</p>
              </div>
              <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-500 shadow-sm">{getRankingSortLabel(accountSort)}排序</span>
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
              {accounts.length > 0 ? accounts.map((account, index) => {
                const rankingValue = getAccountRankingValue(account, accountSort);
                const width = Math.max(8, (rankingValue / maxAccountScore) * 100);
                return (
                  <div
                    key={account.accountName}
                    className="grid grid-cols-[34px_minmax(0,1fr)_86px] items-center gap-3 rounded-2xl border border-slate-100 bg-white px-3 py-2.5 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-200 hover:shadow-md"
                  >
                    <div className={cn(
                      'grid h-8 w-8 place-items-center rounded-xl text-xs font-black',
                      index < 3 ? 'bg-slate-950 text-white' : 'bg-slate-50 text-slate-500',
                    )}>
                      {index + 1}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center justify-between gap-3">
                        <div className="truncate text-sm font-bold text-slate-900">{account.accountName}</div>
                        <div className="shrink-0 text-[11px] font-bold text-slate-500">{getRankingSortLabel(accountSort)} {formatInteger(rankingValue)}</div>
                      </div>
                      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                        <div className={cn('h-full rounded-full', index === 0 ? 'bg-slate-950' : index === 1 ? 'bg-emerald-800' : 'bg-slate-300')} style={{ width: `${width}%` }} />
                      </div>
                      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] font-semibold text-slate-500">
                        <span>发帖 {formatInteger(account.posts)}</span>
                        <span>总浏览 {formatInteger(account.totalViews)}</span>
                        <span>均评论 {formatScore(account.avgComments)}</span>
                        <span>强 {formatInteger(account.strongPostCount)} / 弱 {formatInteger(account.weakPostCount)}</span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-xl font-semibold tracking-tight text-slate-950">{accountSort === 'score' ? formatScore(rankingValue) : formatInteger(rankingValue)}</div>
                      <div className="text-[11px] font-semibold text-slate-500">{getRankingSortLabel(accountSort)}</div>
                    </div>
                  </div>
                );
              }) : (
                <EmptyBlock text="当前范围暂无账号样本" />
              )}
            </div>
          </section>

          <section className="flex min-h-0 flex-col overflow-hidden rounded-[26px] border border-slate-100 bg-slate-50/60 p-4">
            <div className="mb-3 flex items-end justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-slate-950">帖子 Top 50</h3>
                <p className="mt-1 text-xs font-semibold text-slate-500">点击帖子可查看发布管理同款详情。</p>
              </div>
              <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-500 shadow-sm">{getRankingSortLabel(postSort)}排序</span>
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
              {posts.length > 0 ? posts.map((post, index) => {
                const rankingValue = getPostRankingValue(post, postSort);
                const width = Math.max(8, (rankingValue / maxPostScore) * 100);
                return (
                  <button
                    type="button"
                    key={post.id}
                    onClick={() => onOpenPost(post.note)}
                    className="group grid w-full grid-cols-[34px_minmax(0,1fr)_96px] items-center gap-3 rounded-2xl border border-slate-100 bg-white px-3 py-2.5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
                  >
                    <div className={cn(
                      'grid h-8 w-8 place-items-center rounded-xl text-xs font-black',
                      index < 3 ? 'bg-slate-950 text-white' : 'bg-slate-50 text-slate-500',
                    )}>
                      {index + 1}
                    </div>
                    <div className="min-w-0">
                      <div className="line-clamp-1 text-sm font-bold text-slate-900 group-hover:text-slate-950">{post.title}</div>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] font-semibold text-slate-500">
                        <span className="truncate">{post.accountName}</span>
                        <span>{getRankingSortLabel(postSort)} {formatInteger(rankingValue)}</span>
                        <span>评论 {formatInteger(post.comments)}</span>
                        <span>互动 {formatInteger(post.engagement)}</span>
                      </div>
                      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                        <div className={cn('h-full rounded-full', index === 0 ? 'bg-slate-950' : index === 1 ? 'bg-emerald-800' : 'bg-slate-300')} style={{ width: `${width}%` }} />
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-lg font-semibold tracking-tight text-slate-950">{formatInteger(rankingValue)}</div>
                      <div className="text-[11px] font-semibold text-slate-500">{getRankingSortLabel(postSort)}</div>
                    </div>
                  </button>
                );
              }) : (
                <EmptyBlock text="当前范围暂无帖子样本" />
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function PersonalPostRankingChart({
  posts,
  postSort,
  onOpenPost,
}: {
  posts: PostRankingItem[];
  postSort: RankingSortKey;
  ready: boolean;
  onOpenPost: (note: XHSAccountNote) => void;
}) {
  const rows = posts.slice(0, 6);
  const maxViews = Math.max(1, ...rows.map((post) => getPostRankingValue(post, postSort)));
  return (
    <div className="relative">
      {rows.length > 0 ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((post, index) => {
            const rankingValue = getPostRankingValue(post, postSort);
            const width = Math.max(10, (rankingValue / maxViews) * 100);
            const isHero = index === 0;
            return (
              <button
                type="button"
                key={post.id}
                onClick={() => onOpenPost(post.note)}
                className={cn(
                  'group relative overflow-hidden rounded-[24px] border p-2.5 text-left transition duration-300 hover:-translate-y-1',
                  isHero
                    ? 'border-slate-800 bg-slate-950 text-white shadow-[0_20px_42px_rgba(15,23,42,0.22)]'
                    : 'border-white/75 bg-white/64 text-slate-900 shadow-sm hover:bg-white/90',
                )}
              >
                <div className="relative grid grid-cols-[96px_minmax(0,1fr)] gap-3">
                  <div className="relative h-[116px] overflow-hidden rounded-[18px] bg-slate-100">
                    {post.coverImageUrl ? (
                      <img
                        src={post.coverImageUrl}
                        alt={post.title}
                        className="h-full w-full object-cover transition duration-500 group-hover:scale-105"
                        onError={(event) => {
                          event.currentTarget.style.display = 'none';
                        }}
                      />
                    ) : null}
                    <div className="absolute inset-0 bg-[linear-gradient(160deg,rgba(15,23,42,0.06),rgba(15,23,42,0.16))]" />
                    <div className={cn('absolute left-2 top-2 grid h-7 w-7 place-items-center rounded-xl text-xs font-black shadow-sm', isHero ? 'bg-white text-slate-950' : 'bg-slate-950 text-white')}>
                      {index + 1}
                    </div>
                  </div>
                  <div className="min-w-0 py-1">
                    <div className={cn('line-clamp-2 text-sm font-black leading-snug', isHero ? 'text-white' : 'text-slate-950')}>{post.title}</div>
                    <div className={cn('mt-2 text-[11px] font-semibold', isHero ? 'text-slate-300' : 'text-slate-500')}>{post.accountName}</div>
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/60">
                      <div className={cn('h-full rounded-full transition-all duration-700', isHero ? 'bg-emerald-400' : 'bg-slate-950')} style={{ width: `${width}%` }} />
                    </div>
                    <div className="mt-3 grid grid-cols-3 gap-1 text-center">
                      {[
                        [getRankingSortLabel(postSort), formatInteger(rankingValue)],
                        ['评论', formatInteger(post.comments)],
                        ['互动', formatInteger(post.engagement)],
                      ].map(([label, value]) => (
                        <div key={label} className={cn('rounded-xl px-1.5 py-1', isHero ? 'bg-white/10' : 'bg-slate-50')}>
                          <div className={cn('text-[10px] font-semibold', isHero ? 'text-slate-300' : 'text-slate-500')}>{label}</div>
                          <div className={cn('mt-0.5 truncate text-xs font-black', isHero ? 'text-white' : 'text-slate-950')}>{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="grid h-full place-items-center text-sm font-medium text-slate-500">当前范围暂无帖子样本</div>
      )}
    </div>
  );
}

function mergeCarStatsGroup(name: string, rows: CarTypeStats[], totalPosts: number): CarTypeStats {
  const merged = rows.reduce<CarTypeStats>((acc, item) => ({
    ...acc,
    posts: acc.posts + item.posts,
    totalViews: acc.totalViews + item.totalViews,
    totalComments: acc.totalComments + item.totalComments,
    totalEngagement: acc.totalEngagement + item.totalEngagement,
    qualityCount: acc.qualityCount + item.qualityCount,
  }), {
    name,
    brand: name,
    posts: 0,
    totalViews: 0,
    totalComments: 0,
    totalEngagement: 0,
    avgViews: 0,
    avgComments: 0,
    qualityCount: 0,
    share: 0,
    models: [],
  });
  merged.avgViews = merged.totalViews / Math.max(1, merged.posts);
  merged.avgComments = merged.totalComments / Math.max(1, merged.posts);
  merged.share = merged.posts / Math.max(1, totalPosts);
  return merged;
}

function aggregateCarStatsForPie(data: CarTypeStats[], limit = 12): CarTypeStats[] {
  if (data.length <= limit + 1) return data;
  const visible = data.slice(0, limit);
  const rest = data.slice(limit);
  const restPosts = rest.reduce((sum, item) => sum + item.posts, 0);
  if (restPosts <= 0) return visible;
  const totalPosts = Math.max(1, data.reduce((sum, item) => sum + item.posts, 0));
  const restShare = restPosts / totalPosts;
  if (restShare <= 0.24 || rest.length <= 5) return [...visible, mergeCarStatsGroup('其他', rest, totalPosts)];
  const bucketSize = Math.ceil(rest.length / 2);
  const otherGroups = [0, 1]
    .map((bucket) => rest.slice(bucket * bucketSize, (bucket + 1) * bucketSize))
    .filter((bucketRows) => bucketRows.length > 0)
    .map((bucketRows, index) => mergeCarStatsGroup(index === 0 ? '其他品牌' : '更多品牌', bucketRows, totalPosts));
  return [...visible, ...otherGroups];
}

function buildCarTypePieOption(data: CarTypeStats[], centerLabel: string): Record<string, unknown> {
  const pieData = data.map((item) => ({
    name: item.name,
    value: item.posts,
    stats: item,
    itemStyle: item.name === '其他' ? { color: '#cbd5e1' } : undefined,
  }));
  const totalPosts = data.reduce((sum, item) => sum + item.posts, 0);
  return {
    animation: true,
    animationDuration: 260,
    animationDurationUpdate: 220,
    animationEasing: 'cubicOut',
    animationEasingUpdate: 'quarticOut',
    stateAnimation: { duration: 160, easing: 'cubicOut' },
    color: CAR_TYPE_PALETTE,
    graphic: {
      type: 'group',
      left: '58%',
      top: '50%',
      bounding: 'raw',
      children: [
        {
          type: 'text',
          left: 'center',
          top: -16,
          style: {
            text: formatInteger(totalPosts),
            fill: '#0f172a',
            fontSize: 20,
            fontWeight: 900,
            textAlign: 'center',
          },
        },
        {
          type: 'text',
          left: 'center',
          top: 8,
          style: {
            text: centerLabel,
            fill: '#64748b',
            fontSize: 11,
            fontWeight: 800,
            textAlign: 'center',
          },
        },
      ],
    },
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: 'rgba(15,23,42,0.95)',
      borderWidth: 0,
      padding: [9, 11],
      textStyle: { color: '#f8fbff', fontSize: 12 },
      formatter(params: any) {
        const stats = params.data?.stats as CarTypeStats | undefined;
        if (!stats) return `${params.name}<br/>样本 ${formatInteger(toNumber(params.value))} 条`;
        return [
          `${params.name}`,
          `样本 ${formatInteger(stats.posts)} 条 · ${Math.round(stats.share * 100)}%`,
          `浏览 ${formatInteger(stats.totalViews)} · 评论 ${formatInteger(stats.totalComments)}`,
          `互动 ${formatInteger(stats.totalEngagement)} · 优质 ${formatInteger(stats.qualityCount)}`,
        ].join('<br/>');
      },
    },
    legend: { show: false },
    series: [{
      name: centerLabel,
      type: 'pie',
      animationType: 'expansion',
      animationDuration: 300,
      animationDurationUpdate: 220,
      animationEasing: 'cubicOut',
      animationEasingUpdate: 'quarticOut',
      animationDelay: (index: number) => index * 6,
      animationDelayUpdate: (index: number) => index * 4,
      radius: ['46%', '98%'],
      center: ['58%', '50%'],
      startAngle: 92,
      clockwise: true,
      avoidLabelOverlap: true,
      padAngle: 3,
      minAngle: 4,
      data: pieData,
      itemStyle: {
        borderColor: '#ffffff',
        borderWidth: 3,
        shadowBlur: 10,
        shadowColor: 'rgba(15,23,42,0.08)',
      },
      label: {
        show: true,
        position: 'inside',
        color: '#f8fbff',
        fontSize: 12,
        fontWeight: 900,
        formatter(params: any) {
          const percent = Math.round(toNumber(params.percent));
          return percent >= 8 ? `${percent}%` : '';
        },
      },
      labelLine: {
        show: false,
      },
      emphasis: {
        scale: true,
        scaleSize: 7,
        itemStyle: {
          shadowBlur: 18,
          shadowOffsetY: 5,
          shadowColor: 'rgba(15,23,42,0.18)',
        },
      },
    }],
  };
}

function CarTypePieChart({
  data,
  ready,
  centerLabel,
  onSelect,
}: {
  data: CarTypeStats[];
  ready: boolean;
  centerLabel: string;
  onSelect?: (item: CarTypeStats) => void;
}) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<any>(null);
  const onSelectRef = useRef(onSelect);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    if (!ready || !chartRef.current || typeof window === 'undefined' || !window.echarts) return undefined;
    const chart = window.echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    chartInstanceRef.current = chart;
    const handleClick = (params: any) => {
      const stats = params.data?.stats as CarTypeStats | undefined;
      if (stats) onSelectRef.current?.(stats);
    };
    chart.on('click', handleClick);
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(chartRef.current);
    return () => {
      resizeObserver.disconnect();
      chart.off?.('click', handleClick);
      chart.dispose();
      chartInstanceRef.current = null;
    };
  }, [ready]);

  useEffect(() => {
    const chart = chartInstanceRef.current;
    if (!ready || !chart) return;
    chart.setOption(buildCarTypePieOption(data, centerLabel), true);
    chart.resize();
  }, [centerLabel, data, ready]);

  return (
    <div className="relative h-full min-h-[132px]">
      {ready ? (
        <div ref={chartRef} className="h-full w-full origin-center" />
      ) : (
        <div className="grid h-full place-items-center text-sm font-medium text-slate-500">正在加载车型占比...</div>
      )}
    </div>
  );
}

function CarTypeStatsPanel({ data, ready }: { data: CarTypeStats[]; ready: boolean }) {
  const [selectedBrand, setSelectedBrand] = useState<string | null>(null);
  const activeBrand = useMemo(() => data.find((item) => item.brand === selectedBrand) || null, [data, selectedBrand]);
  const chartData = activeBrand ? (activeBrand.models || []) : data;
  const chartSlices = useMemo(() => activeBrand ? chartData : aggregateCarStatsForPie(chartData, 12), [activeBrand, chartData]);
  const legendRows = chartSlices.slice(0, 6);
  const tableRows = chartData;

  useEffect(() => {
    if (selectedBrand && !data.some((item) => item.brand === selectedBrand)) {
      setSelectedBrand(null);
    }
  }, [data, selectedBrand]);

  return (
    <div className="grid h-full min-h-0 grid-rows-[28px_148px_minmax(0,1fr)] gap-2 overflow-hidden">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="min-w-0 text-xs font-bold text-slate-500">
          {activeBrand ? (
            <span><span className="text-slate-950">{activeBrand.brand}</span> 车型分布</span>
          ) : (
            <span>品牌分布 · 点击品牌看车型</span>
          )}
        </div>
        {activeBrand && (
          <button
            type="button"
            onClick={() => setSelectedBrand(null)}
            className="shrink-0 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-bold text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-950"
          >
            返回品牌
          </button>
        )}
      </div>

      <div className="grid min-h-0 grid-cols-[92px_minmax(0,1fr)] gap-2">
        <div className="flex min-w-0 flex-col justify-center gap-2 pl-1">
          {legendRows.map((item, index) => (
            <div key={item.name} className="flex min-w-0 items-center gap-2 text-xs font-bold text-slate-600">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: CAR_TYPE_PALETTE[index % CAR_TYPE_PALETTE.length] }} />
              <span className="truncate">{item.name}</span>
            </div>
          ))}
        </div>
        <div className="min-h-0">
          <CarTypePieChart
            data={chartSlices}
            ready={ready}
            centerLabel="样本"
            onSelect={(item) => {
              if (!activeBrand && item.models?.length) setSelectedBrand(item.brand);
            }}
          />
        </div>
      </div>

      <div className="flex min-h-0 flex-col overflow-hidden rounded-[22px] border border-white/70 bg-white/54 shadow-sm">
        <div className="grid shrink-0 grid-cols-[1.1fr_0.7fr_1fr_0.8fr_0.8fr_0.8fr] border-b border-slate-200/70 bg-white/50 px-3 py-1.5 text-[10px] font-black uppercase tracking-[0.08em] text-slate-500">
          <span>{activeBrand ? '车型' : '品牌'}</span>
          <span className="text-right">样本</span>
          <span className="text-right">浏览</span>
          <span className="text-right">评论</span>
          <span className="text-right">互动</span>
          <span className="text-right">均浏览</span>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {tableRows.map((item, index) => (
            <div key={`${item.name}-row`} className="grid grid-cols-[1.1fr_0.7fr_1fr_0.8fr_0.8fr_0.8fr] items-center px-3 py-1.5 text-[11px] font-semibold text-slate-700 odd:bg-white/30">
              <span className="flex min-w-0 items-center gap-2">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: CAR_TYPE_PALETTE[index % CAR_TYPE_PALETTE.length] }} />
                <span className="truncate">{item.name}</span>
              </span>
              <span className="text-right text-slate-950">{formatInteger(item.posts)}</span>
              <span className="text-right">{formatInteger(item.totalViews)}</span>
              <span className="text-right">{formatInteger(item.totalComments)}</span>
              <span className="text-right">{formatInteger(item.totalEngagement)}</span>
              <span className="text-right">{formatInteger(item.avgViews)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function buildTagRelationOption(size: { width: number; height: number }, data: TagRelationData, intro = false): Record<string, unknown> {
  const palette: Record<TagMatrixItem['dimension'], string> = {
    决策主题: TAG_RELATION_THEME.rust,
    购车场景: TAG_RELATION_THEME.gold,
    标题钩子: TAG_RELATION_THEME.blue,
    证据结构: TAG_RELATION_THEME.green,
    承接动作: TAG_RELATION_THEME.gold,
    车型锚点: TAG_RELATION_THEME.danger,
  };
  const scoreOf = (item: TagMatrixItem) => item.leads * 6 + item.consult * 2.5 + item.organicEngagement * 0.18 + item.count;
  const width = Math.max(360, size.width);
  const height = Math.max(260, size.height);
  const maxItemsPerGroup = width < 520 ? 3 : width < 700 ? 4 : 5;
  const groups = TAG_RELATION_DIMENSIONS
    .map((dimension) => ({
      dimension,
      items: data.tagMatrix
        .filter((item) => item.dimension === dimension)
        .sort((a, b) => scoreOf(b) - scoreOf(a))
        .slice(0, maxItemsPerGroup),
    }))
    .filter((group) => group.items.length);

  if (!groups.length) {
    return {
      animation: false,
      graphic: {
        type: 'text',
        left: 'center',
        top: 'middle',
        style: { text: '暂无足够标签样本', fill: TAG_RELATION_THEME.muted, fontSize: 15, fontWeight: 800 },
      },
    };
  }

  const allItems = groups.flatMap((group) => group.items);
  const maxCount = Math.max(1, ...allItems.map((item) => item.count));
  const maxGroupCount = Math.max(1, ...groups.map((group) => group.items.reduce((sum, item) => sum + item.count, 0)));
  const compact = width < 560;
  const nodes: Array<Record<string, unknown>> = [];
  const links: Array<Record<string, unknown>> = [];
  const categories = groups.map((group) => ({
    name: group.dimension,
    itemStyle: { color: palette[group.dimension] },
  }));

  const layoutMap: Record<string, { x: number; y: number; side: 'left' | 'right' }> = {
    决策主题: { x: width * 0.38, y: height * 0.27, side: 'left' },
    标题钩子: { x: width * 0.62, y: height * 0.27, side: 'right' },
    购车场景: { x: width * 0.38, y: height * 0.52, side: 'left' },
    承接动作: { x: width * 0.62, y: height * 0.52, side: 'right' },
    证据结构: { x: width * 0.38, y: height * 0.76, side: 'left' },
    车型锚点: { x: width * 0.62, y: height * 0.76, side: 'right' },
  };

  groups.forEach((group) => {
      const color = palette[group.dimension];
      const groupId = `dimension-${group.dimension}`;
      const groupScore = group.items.reduce((sum, item) => sum + scoreOf(item), 0);
      const groupCount = group.items.reduce((sum, item) => sum + item.count, 0);
      const layout = layoutMap[group.dimension] || { x: width / 2, y: height / 2, side: 'right' as const };
      const groupX = Math.round(layout.x);
      const groupY = Math.round(layout.y);
      const side = layout.side;
      const labelSafeInset = compact ? 104 : 132;
      const itemOffset = compact ? 58 : 90;
      const itemX = side === 'left'
        ? Math.max(labelSafeInset, groupX - itemOffset)
        : Math.min(width - labelSafeInset, groupX + itemOffset);
      nodes.push({
        id: groupId,
        name: group.dimension,
        category: TAG_RELATION_DIMENSIONS.indexOf(group.dimension),
        x: groupX,
        y: groupY,
        symbolSize: compact
          ? Math.max(42, Math.min(54, 42 + (groupCount / maxGroupCount) * 12))
          : Math.max(48, Math.min(62, 48 + (groupCount / maxGroupCount) * 14)),
        value: [groupScore, group.items.length],
        draggable: false,
        itemStyle: {
          color,
          borderColor: '#f8fbff',
          borderWidth: 2,
          shadowBlur: 12,
          shadowColor: 'rgba(71,85,105,0.18)',
        },
        label: {
          show: true,
          position: 'inside',
          color: '#f8fbff',
          fontSize: compact ? 10 : 11,
          fontWeight: 900,
          formatter: group.dimension.length > 4 ? group.dimension.slice(0, 4) : group.dimension,
        },
        z: 80,
        meta: { type: 'dimension', detail: `${group.items.length} 个重点标签` },
      });

      const itemGap = compact ? 20 : 30;
      const startY = groupY - ((group.items.length - 1) * itemGap) / 2;
      group.items.forEach((item, itemIndex) => {
        const y = Math.round(startY + itemIndex * itemGap);
        const symbolSize = compact
          ? Math.max(10, Math.min(22, 10 + (item.count / maxCount) * 12))
          : Math.max(12, Math.min(28, 12 + (item.count / maxCount) * 16));
        const itemId = `${group.dimension}-${item.label}`;
        nodes.push({
          id: itemId,
          name: item.label,
          category: TAG_RELATION_DIMENSIONS.indexOf(group.dimension),
          x: itemX,
          y,
          symbolSize,
          draggable: false,
          itemStyle: {
            color,
            opacity: 0.94,
            borderColor: '#f8fbff',
            borderWidth: 1.5,
            shadowBlur: 8,
            shadowColor: 'rgba(71,85,105,0.14)',
          },
          label: {
            show: true,
            position: side === 'left' ? 'left' : 'right',
            distance: compact ? 7 : 8,
            align: side === 'left' ? 'right' : 'left',
            verticalAlign: 'middle',
            color: TAG_RELATION_THEME.text,
            fontSize: compact ? 9 : 10,
            fontWeight: 800,
            width: compact ? 56 : 92,
            overflow: 'truncate',
            formatter: item.label,
          },
          z: 60,
          meta: {
            type: 'item',
            dimension: group.dimension,
            count: item.count,
            paidCount: item.paidCount,
            organicCount: item.organicCount,
            consult: item.consult,
            leads: item.leads,
            organicEngagement: item.organicEngagement,
          },
        });
        links.push({
          source: groupId,
          target: itemId,
          value: item.count,
          lineStyle: {
            color,
            opacity: 0.34,
            width: Math.max(1.2, 1.2 + (item.count / maxCount) * (compact ? 3.2 : 4)),
            curveness: side === 'left' ? -0.06 : 0.06,
          },
        });
      });
  });

  const renderedNodes = intro
    ? nodes.map((node) => ({
        ...node,
        x: width / 2,
        y: height / 2,
        symbolSize: 2,
        label: {
          ...(node.label as Record<string, unknown> | undefined),
          show: false,
        },
        itemStyle: {
          ...(node.itemStyle as Record<string, unknown> | undefined),
          opacity: 0,
          shadowBlur: 0,
        },
      }))
    : nodes;
  const renderedLinks = intro
    ? links.map((link) => ({
        ...link,
        lineStyle: {
          ...(link.lineStyle as Record<string, unknown> | undefined),
          opacity: 0,
          width: 0,
        },
      }))
    : links;

  return {
    animationDuration: 280,
    animationDurationUpdate: 220,
    animationEasing: 'quarticOut',
    animationEasingUpdate: 'quarticOut',
    stateAnimation: { duration: 160, easing: 'cubicOut' },
    color: categories.map((item) => item.itemStyle.color),
    tooltip: {
      backgroundColor: 'rgba(15,23,42,0.94)',
      borderWidth: 0,
      padding: [9, 11],
      textStyle: { color: '#f8fbff', fontSize: 12 },
      formatter(params: any) {
        if (params.dataType === 'edge') {
          const source = String(params.data.source).replace('dimension-', '').replace('account-root', data.accountName);
          const target = String(params.data.target).replace('dimension-', '').replace('account-root', data.accountName).replace(/^.+?-/, '');
          return `${source} -> ${target}<br/>连接强度 ${formatInteger(toNumber(params.data.value))}`;
        }
        const meta = params.data.meta || {};
        if (meta.type === 'account') return `${data.accountName}<br/>内容标签关系中心`;
        if (meta.type === 'dimension') return `${params.data.name}<br/>${meta.detail}`;
        return [
          `${meta.dimension || '标签'} / ${params.data.name}`,
          `${formatInteger(meta.count)} 条 · 自然 ${formatInteger(meta.organicCount)}`,
          `${formatInteger(meta.consult)} 评论 · 优质 ${formatInteger(meta.leads)} · 互动 ${formatInteger(meta.organicEngagement)}`,
        ].join('<br/>');
      },
    },
    legend: { show: false },
    series: [{
      type: 'graph',
      layout: 'none',
      coordinateSystem: null,
      data: renderedNodes,
      links: renderedLinks,
      categories,
      roam: false,
      draggable: false,
      edgeSymbol: ['none', 'none'],
      edgeLabel: { show: false },
      lineStyle: { color: 'source', opacity: 0.3, width: 2 },
      labelLayout: { hideOverlap: true },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { opacity: 0.78, width: 3 },
      },
    }],
  };
}

function ContentTagGraphPanel({ data, ready, className }: { data: TagRelationData; ready: boolean; className?: string }) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<any>(null);

  useEffect(() => {
    if (!ready || !chartRef.current || typeof window === 'undefined' || !window.echarts) return undefined;
    const chart = window.echarts.init(chartRef.current, undefined, { renderer: 'canvas' });
    chartInstanceRef.current = chart;
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(chartRef.current);
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
      chartInstanceRef.current = null;
    };
  }, [ready]);

  useEffect(() => {
    const chart = chartInstanceRef.current;
    if (!ready || !chart || !chartRef.current) return;
    chart.setOption(buildTagRelationOption({
      width: chartRef.current.clientWidth || 640,
      height: chartRef.current.clientHeight || 288,
    }, data, false), true);
    chart.resize();
  }, [data, ready]);

  return (
    <div className={cn('relative h-[288px]', className)}>
      {ready ? (
        <div ref={chartRef} className="h-full w-full" />
      ) : (
        <div className="grid h-full place-items-center text-sm font-medium text-slate-400">正在加载 ECharts 图谱...</div>
      )}
    </div>
  );
}

function InsightPostDetailModal({ note, onClose }: { note: XHSAccountNote; onClose: () => void }) {
  const galleryUrls = useMemo(() => getInsightNoteGalleryUrls(note), [note]);
  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const activeImageUrl = galleryUrls[activeImageIndex] || '';
  const metrics = [
    { label: '曝光', value: note.exposure_count },
    { label: '浏览', value: note.view_count },
    { label: '点击率', value: note.cover_click_rate, format: (value: number) => `${Number(value || 0).toFixed(2)}%` },
    { label: '点赞', value: note.liked_count },
    { label: '评论', value: note.comment_count },
    { label: '收藏', value: note.collected_count },
    { label: '转发', value: note.share_count },
  ];

  useEffect(() => {
    setActiveImageIndex(0);
  }, [note.id]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[80] overflow-y-auto bg-slate-950/68 p-3 backdrop-blur-md sm:p-5"
      onClick={onClose}
    >
      <div
        className="mx-auto grid w-full max-w-[1180px] overflow-hidden rounded-[32px] border border-white/70 bg-white shadow-[0_34px_120px_rgba(15,23,42,0.34)] lg:grid-cols-[minmax(360px,0.9fr)_minmax(420px,1fr)]"
        onClick={(event) => event.stopPropagation()}
      >
        <section className="relative min-h-[360px] bg-slate-50">
          {activeImageUrl ? (
            <img
              src={activeImageUrl}
              alt={note.title || note.feed_id}
              className="h-full max-h-[82vh] min-h-[360px] w-full object-contain"
              loading="lazy"
              referrerPolicy="no-referrer"
            />
          ) : (
            <div className="grid h-full min-h-[360px] place-items-center text-center">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-slate-400">No Image</div>
                <div className="mt-2 text-sm font-medium text-slate-500">这条帖子还没有同步封面图</div>
              </div>
            </div>
          )}
          {galleryUrls.length > 1 && (
            <div className="absolute bottom-4 left-4 right-4 flex gap-2 overflow-x-auto rounded-2xl bg-white/90 p-2 shadow-[0_14px_34px_rgba(15,23,42,0.16)] backdrop-blur">
              {galleryUrls.slice(0, 8).map((url, index) => (
                <button
                  key={url}
                  type="button"
                  onClick={() => setActiveImageIndex(index)}
                  className={cn(
                    'h-14 w-14 shrink-0 overflow-hidden rounded-xl border transition',
                    activeImageIndex === index ? 'border-slate-950 ring-2 ring-slate-950/10' : 'border-white',
                  )}
                >
                  <img src={url} alt={`${note.title || note.feed_id}-${index + 1}`} className="h-full w-full object-cover" referrerPolicy="no-referrer" />
                </button>
              ))}
            </div>
          )}
        </section>

        <aside className="relative flex max-h-[82vh] min-h-[520px] flex-col">
          <button
            type="button"
            className="absolute right-4 top-4 z-[2] grid h-10 w-10 place-items-center rounded-full bg-slate-100 text-xl font-semibold text-slate-500 transition hover:bg-slate-950 hover:text-white"
            onClick={onClose}
            aria-label="关闭详情"
          >
            ×
          </button>
          <div className="border-b border-slate-100 px-6 py-5 pr-16">
            <div className="flex items-center gap-3">
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-slate-950 text-sm font-black text-white">
                {getInsightAccountInitial(note)}
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-black text-slate-950">{note.profile_nickname || note.account_name}</div>
                <div className="mt-1 truncate text-xs font-semibold text-slate-400">{note.account_name}</div>
              </div>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            <h3 className="text-[24px] font-semibold leading-8 tracking-tight text-slate-950">{note.title || note.feed_id}</h3>
            <div className="mt-4 whitespace-pre-wrap break-words text-[15px] leading-8 text-slate-700">
              {getInsightContentPreview(note)}
            </div>

            <div className="mt-5 grid grid-cols-7 gap-2">
              {metrics.map((metric) => (
                <div key={metric.label} className="rounded-2xl bg-slate-50 px-3 py-3 text-center">
                  <div className="text-[11px] font-bold text-slate-400">{metric.label}</div>
                  <div className="mt-1 text-sm font-black text-slate-950">
                    {metric.format ? metric.format(toNumber(metric.value)) : formatInteger(toNumber(metric.value))}
                  </div>
                </div>
              ))}
            </div>

            <section className="mt-5 rounded-[24px] border border-slate-100 bg-slate-50/80 p-4">
              <div className="text-[11px] font-black uppercase tracking-[0.16em] text-slate-400">同步信息</div>
              <div className="mt-3 grid gap-2 text-sm font-medium text-slate-600">
                <div>发布时间：{formatInsightPublishedAt(note.published_at)}</div>
                <div>详情同步：{note.detail_synced_at ? formatInsightPublishedAt(note.detail_synced_at) : '未同步详情'}</div>
                <div>正文状态：{note.content_status || (note.content ? '已补齐' : '未同步正文')}</div>
              </div>
            </section>

            {note.post_url ? (
              <a
                href={note.post_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-5 inline-flex rounded-2xl bg-slate-950 px-4 py-2.5 text-sm font-bold text-white transition hover:-translate-y-0.5 hover:bg-slate-800"
              >
                查看原帖链接
              </a>
            ) : null}
          </div>
        </aside>
      </div>
    </div>
  );
}

function AiSummaryModal({ report, onClose }: { report: AiReport; onClose: () => void }) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[90] overflow-y-auto bg-slate-950/60 p-4 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        className="mx-auto mt-10 w-full max-w-[860px] overflow-hidden rounded-[34px] border border-white/70 bg-white shadow-[0_38px_130px_rgba(15,23,42,0.38)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="relative overflow-hidden bg-slate-950 px-7 py-6 text-white">
          <div className="pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full bg-emerald-400/20 blur-3xl" />
          <div className="relative flex items-start justify-between gap-4">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-white/10 px-3 py-1 text-[11px] font-black uppercase tracking-[0.16em] text-white/70">
                <Sparkles className="h-3.5 w-3.5" />
                AI Mock Summary
              </div>
              <h2 className="mt-4 max-w-3xl text-[26px] font-semibold leading-tight tracking-[-0.045em]">{report.headline}</h2>
              <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-300">{report.summary}</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-white/10 text-2xl leading-none text-white/70 transition hover:bg-white hover:text-slate-950"
              aria-label="关闭 AI 摘要"
            >
              ×
            </button>
          </div>
        </div>

        <div className="grid gap-4 p-6 lg:grid-cols-[0.95fr_1.05fr]">
          <section className="rounded-[26px] border border-slate-100 bg-slate-50/80 p-4">
            <div className="text-[11px] font-black uppercase tracking-[0.16em] text-slate-400">Key Signals</div>
            <div className="mt-3 grid gap-3">
              {report.stats.map((stat) => (
                <div key={stat.label} className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-100">
                  <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">{stat.label}</div>
                  <div className="mt-1 text-lg font-semibold tracking-tight text-slate-950">{stat.value}</div>
                  <p className="mt-1 text-sm leading-6 text-slate-500">{stat.detail}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-[26px] border border-slate-100 bg-white p-4">
            <div className="text-[11px] font-black uppercase tracking-[0.16em] text-slate-400">Next Actions</div>
            <div className="mt-3 space-y-3">
              {report.actions.map((card, index) => {
                const Icon = index === 0 ? ArrowUpRight : index === 1 ? Target : Layers3;
                return (
                  <div key={card.title} className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
                    <div className="flex items-center gap-3">
                      <div className={cn('rounded-xl p-2 ring-1', AI_ACTION_TONE[card.tone])}>
                        <Icon className="h-4 w-4" />
                      </div>
                      <h3 className="font-semibold text-slate-950">{card.title}</h3>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-500">{card.body}</p>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

export default function XhsInsightsPage() {
  const [dateRange, setDateRange] = useState<DateRange>(() => getDefaultDateRange());
  const [selectedDepartment, setSelectedDepartment] = useState<DepartmentFilter>('all');
  const [selectedOwner, setSelectedOwner] = useState('all');
  const [selectedAccountKeys, setSelectedAccountKeys] = useState<string[]>([]);
  const [accountRankingSort, setAccountRankingSort] = useState<RankingSortKey>('score');
  const [postRankingSort, setPostRankingSort] = useState<RankingSortKey>('score');
  const [search, setSearch] = useState('');
  const [notes, setNotes] = useState<XHSAccountNote[]>([]);
  const [insightsDashboard, setInsightsDashboard] = useState<XHSInsightsDashboard | null>(null);
  const [profileStatOwnerRows, setProfileStatOwnerRows] = useState<XHSProfileStatOwnerRow[]>([]);
  const [profileStatAccountScope, setProfileStatAccountScope] = useState<OperatorAccountScope | null>(null);
  const [viewerRoles, setViewerRoles] = useState<string[]>([]);
  const [accountCount, setAccountCount] = useState(0);
  const [carCatalog, setCarCatalog] = useState<CarCatalogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [dataStatus, setDataStatus] = useState<InsightsDataStatus>('loading');
  const [loadError, setLoadError] = useState('');
  const [echartsReady, setEchartsReady] = useState(false);
  const [activeDetailNote, setActiveDetailNote] = useState<XHSAccountNote | null>(null);
  const [rankingDetailOpen, setRankingDetailOpen] = useState(false);
  const [aiSummaryOpen, setAiSummaryOpen] = useState(false);
  const [detailStage, setDetailStage] = useState(0);
  const [vehicleMatches, setVehicleMatches] = useState<Map<string, VehicleMatchResult>>(new Map());
  const [vehicleMatchingDone, setVehicleMatchingDone] = useState(false);
  const [vehicleMatchProgress, setVehicleMatchProgress] = useState(0);
  const [isDataRendering, startDataRenderTransition] = useTransition();
  const hasLoadedOnceRef = useRef(false);
  const vehicleMatchCacheRef = useRef<Map<string, VehicleMatchResult>>(new Map());
  const rankingReady = detailStage >= 1;
  const vehicleReady = detailStage >= 2;
  const operatorReady = detailStage >= 3;
  const tagReady = detailStage >= 4;
  const detailsReady = detailStage >= 4;

  useEffect(() => {
    if (typeof window !== 'undefined' && window.echarts) setEchartsReady(true);
  }, []);

  useEffect(() => {
    try {
      const currentUser = JSON.parse(localStorage.getItem('app_current_user') || 'null') as { role?: string; roles?: string[] } | null;
      setViewerRoles(Array.from(new Set([currentUser?.role, ...(currentUser?.roles || [])].filter(Boolean) as string[])));
    } catch {
      setViewerRoles([]);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadCarCatalog() {
      try {
        const response = await carModelsApi.getVehicleCatalog();
        if (!cancelled) setCarCatalog(buildCarCatalogFromRows(response.data));
      } catch {
        if (!cancelled) setCarCatalog([]);
      }
    }
    loadCarCatalog();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setDetailStage(0);
      if (!hasLoadedOnceRef.current) setDataStatus('loading');
      setLoadError('');
      try {
        const startDate = formatDateKey(dateRange.start);
        const endDate = formatDateKey(dateRange.end);
        const [insightsNotes, profileStatRows] = await Promise.all([
          getXhsInsightAccountNotes({
            start_date: startDate,
            end_date: endDate,
            limit: INSIGHT_NOTE_LIMIT,
            status: 'all',
          }),
          getXhsProfileStatOwnerRows({ start_date: startDate, end_date: endDate }).catch(() => null),
        ]);
        const allNotes = insightsNotes.items;
        if (!cancelled) {
          await waitForPaint();
          if (cancelled) return;
          startDataRenderTransition(() => {
            if (allNotes.length > 0 || (profileStatRows?.owner_rows?.length || 0) > 0) {
              setNotes(allNotes);
              setInsightsDashboard(insightsNotes.dashboard || null);
              setDataStatus('real');
            } else {
              setNotes([]);
              setInsightsDashboard(null);
              setDataStatus('empty');
            }
            setProfileStatOwnerRows(profileStatRows?.owner_rows || []);
            setProfileStatAccountScope(profileStatRows?.assignment_summary || null);
            setAccountCount(insightsNotes.total_accounts || new Set(allNotes.map(getNoteAccountKey)).size);
            hasLoadedOnceRef.current = true;
            setHasLoadedOnce(true);
            setLoading(false);
          });
        }
      } catch (error) {
        if (!cancelled) {
          if (!hasLoadedOnceRef.current) {
            setNotes([]);
            setInsightsDashboard(null);
            setProfileStatOwnerRows([]);
            setProfileStatAccountScope(null);
            setAccountCount(0);
          }
          setDataStatus('error');
          setLoadError(error instanceof Error ? error.message : '真实数据加载失败');
          hasLoadedOnceRef.current = true;
          setHasLoadedOnce(true);
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [dateRange]);

  const range = useMemo(() => dateRange, [dateRange]);
  const deferredSearch = useDeferredValue(search);
  const departmentScopedNotes = useMemo(() => notes.filter((note) => (
    isInRange(note, range.start, range.end) && matchesDepartmentFilter(note.owner_role, selectedDepartment)
  )), [notes, range, selectedDepartment]);
  const departmentScopedProfileStatRows = useMemo(() => profileStatOwnerRows.filter((row) => (
    matchesDepartmentFilter(row.owner_role, selectedDepartment)
  )), [profileStatOwnerRows, selectedDepartment]);
  const ownerOptions = useMemo(() => (
    buildOwnerOptions(departmentScopedNotes, departmentScopedProfileStatRows)
  ), [departmentScopedNotes, departmentScopedProfileStatRows]);
  const selectedOwnerProfileAccountNames = useMemo(() => {
    if (selectedOwner === 'all') return new Set<string>();
    const names = departmentScopedProfileStatRows
      .filter((row) => String(row.owner_id || '') === selectedOwner)
      .flatMap((row) => row.account_names || [])
      .map((accountName) => normalizeContentAccountName(accountName))
      .filter(Boolean);
    return new Set(names);
  }, [departmentScopedProfileStatRows, selectedOwner]);
  const ownerScopedNotes = useMemo(() => departmentScopedNotes.filter((note) => (
    selectedOwner === 'all'
    || String(note.owner_user_id || '') === selectedOwner
    || selectedOwnerProfileAccountNames.has(normalizeContentAccountName(getNoteAccountName(note)))
  )), [departmentScopedNotes, selectedOwner, selectedOwnerProfileAccountNames]);
  const allAccountOptions = useMemo(() => buildAccountOptions(ownerScopedNotes, ''), [ownerScopedNotes]);
  const searchedAccounts = useMemo(() => buildAccountOptions(ownerScopedNotes, deferredSearch), [ownerScopedNotes, deferredSearch]);
  const availableAccounts = useMemo(() => {
    if (!selectedAccountKeys.length) return searchedAccounts;
    const selectedSet = new Set(selectedAccountKeys);
    const next = [...searchedAccounts];
    allAccountOptions.forEach((account) => {
      if (selectedSet.has(account.key) && !next.some((item) => item.key === account.key)) {
        next.unshift(account);
      }
    });
    return next;
  }, [allAccountOptions, searchedAccounts, selectedAccountKeys]);
  const selectedAccountLabels = useMemo(() => {
    const optionMap = new Map(allAccountOptions.map((account) => [account.key, account.label]));
    return selectedAccountKeys
      .map((key) => optionMap.get(key))
      .filter((label): label is string => Boolean(label));
  }, [allAccountOptions, selectedAccountKeys]);
  const isAllAccountsSelected = selectedAccountKeys.length === 0;
  const selectedOwnerLabel = useMemo(() => {
    if (selectedOwner === 'all') {
      return selectedDepartment === 'all' ? '全部负责人' : getDepartmentLabel(selectedDepartment);
    }
    return ownerOptions.find((owner) => owner.key === selectedOwner)?.label || selectedOwner;
  }, [ownerOptions, selectedDepartment, selectedOwner]);
  const departmentScopedAccountCount = useMemo(() => {
    if (selectedDepartment === 'all') return accountCount || allAccountOptions.length;
    const accountKeys = new Set<string>();
    departmentScopedNotes.forEach((note) => accountKeys.add(getNoteAccountKey(note)));
    departmentScopedProfileStatRows.forEach((row) => {
      (row.account_names || []).forEach((accountName) => {
        const normalized = normalizeContentAccountName(accountName);
        if (normalized) accountKeys.add(normalized);
      });
    });
    return accountKeys.size || allAccountOptions.length;
  }, [accountCount, allAccountOptions.length, departmentScopedNotes, departmentScopedProfileStatRows, selectedDepartment]);
  const selectedAccountScopeLabel = useMemo(() => {
    if (isAllAccountsSelected) return selectedOwnerLabel;
    if (selectedAccountLabels.length === 1) return selectedAccountLabels[0];
    return `${selectedAccountLabels.length} 个账号`;
  }, [isAllAccountsSelected, selectedAccountLabels, selectedOwnerLabel]);
  const scopedAccountCount = useMemo(() => {
    if (selectedOwner === 'all') return departmentScopedAccountCount;
    return ownerOptions.find((owner) => owner.key === selectedOwner)?.accountCount || allAccountOptions.length;
  }, [allAccountOptions.length, departmentScopedAccountCount, ownerOptions, selectedOwner]);
  const filteredNotes = useMemo(() => {
    if (isAllAccountsSelected) return ownerScopedNotes;
    const selectedSet = new Set(selectedAccountKeys);
    return ownerScopedNotes.filter((note) => selectedSet.has(getNoteAccountKey(note)));
  }, [isAllAccountsSelected, ownerScopedNotes, selectedAccountKeys]);
  const deferredFilteredNotes = useDeferredValue(filteredNotes);
  const canUseBackendDashboard = Boolean(insightsDashboard && selectedDepartment === 'all' && selectedOwner === 'all' && isAllAccountsSelected);

  useEffect(() => {
    if (!hasLoadedOnce || dataStatus !== 'real') return undefined;
    setDetailStage(0);
    let cancelled = false;
    const timers: number[] = [];
    const advance = (stage: number, delay: number) => {
      timers.push(window.setTimeout(() => {
        if (!cancelled) startTransition(() => setDetailStage(stage));
      }, delay));
    };
    advance(1, 120);
    advance(2, 320);
    advance(3, 560);
    advance(4, 860);
    return () => {
      cancelled = true;
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [dataStatus, filteredNotes.length, hasLoadedOnce, selectedAccountKeys, selectedDepartment, selectedOwner]);

  useEffect(() => {
    const validKeys = new Set(allAccountOptions.map((account) => account.key));
    setSelectedAccountKeys((current) => {
      const next = current.filter((key) => validKeys.has(key));
      return next.length === current.length ? current : next;
    });
  }, [allAccountOptions]);
  useEffect(() => {
    if (selectedOwner !== 'all' && !ownerOptions.some((owner) => owner.key === selectedOwner)) {
      setSelectedOwner('all');
      setSelectedAccountKeys([]);
    }
  }, [ownerOptions, selectedOwner]);
  const vehicleCatalogIndex = useMemo<VehicleCatalogIndex | null>(() => {
    if (!carCatalog.length) return null;
    return buildVehicleCatalogIndex(carCatalog);
  }, [carCatalog]);

  useEffect(() => {
    if (canUseBackendDashboard && insightsDashboard?.carTypeStats?.length) {
      setVehicleMatches(new Map());
      setVehicleMatchingDone(true);
      setVehicleMatchProgress(100);
      return undefined;
    }
    if (!vehicleReady) {
      setVehicleMatches(new Map());
      setVehicleMatchingDone(false);
      setVehicleMatchProgress(0);
      return undefined;
    }

    let cancelled = false;
    const nextMatches = new Map<string, VehicleMatchResult>();
    const notesToMatch = deferredFilteredNotes;
    let index = 0;
    setVehicleMatches(new Map());
    setVehicleMatchingDone(notesToMatch.length === 0);
    setVehicleMatchProgress(notesToMatch.length === 0 ? 100 : 0);

    const runChunk = () => {
      if (cancelled) return;
      const startedAt = performance.now();
      let processed = 0;
      while (index < notesToMatch.length && processed < 3000 && performance.now() - startedAt < 80) {
        const note = notesToMatch[index];
        const key = getNoteCacheKey(note);
        let match = vehicleMatchCacheRef.current.get(key);
        if (!match && vehicleCatalogIndex) {
          match = resolveVehicleMatchWithIndex(note, vehicleCatalogIndex);
          vehicleMatchCacheRef.current.set(key, match);
        }
        if (match) nextMatches.set(key, match);
        index += 1;
        processed += 1;
      }

      if (index < notesToMatch.length) {
        setVehicleMatchProgress(Math.min(99, Math.round((index / Math.max(1, notesToMatch.length)) * 100)));
        window.setTimeout(runChunk, 0);
        return;
      }
      if (!cancelled) {
        setVehicleMatches(nextMatches);
        setVehicleMatchingDone(true);
        setVehicleMatchProgress(100);
      }
    };

    window.setTimeout(runChunk, 0);
    return () => {
      cancelled = true;
    };
  }, [canUseBackendDashboard, deferredFilteredNotes, insightsDashboard, vehicleCatalogIndex, vehicleReady]);

  const vehicleStatsReady = (canUseBackendDashboard && Boolean(insightsDashboard?.carTypeStats?.length)) || (vehicleReady && vehicleMatchingDone);
  const carTypeStats = useMemo(() => {
    if (canUseBackendDashboard && insightsDashboard?.carTypeStats?.length) {
      return insightsDashboard.carTypeStats as CarTypeStats[];
    }
    return vehicleStatsReady ? buildCarTypeStats(deferredFilteredNotes, vehicleMatches) : buildCarTypeStats([], vehicleMatches);
  }, [canUseBackendDashboard, deferredFilteredNotes, insightsDashboard, vehicleMatches, vehicleStatsReady]);
  const accountSummaries = useMemo(() => {
    if (canUseBackendDashboard && insightsDashboard?.accountSummaries) {
      return insightsDashboard.accountSummaries as AccountSummary[];
    }
    return rankingReady ? buildAccountSummaries(filteredNotes) : [];
  }, [canUseBackendDashboard, filteredNotes, insightsDashboard, rankingReady]);
  const trend = useMemo(() => {
    if (canUseBackendDashboard && insightsDashboard?.trend) {
      return insightsDashboard.trend as TrendPoint[];
    }
    return buildTrend(filteredNotes, range);
  }, [canUseBackendDashboard, filteredNotes, insightsDashboard, range]);
  const teamOperatorRows = useMemo(() => {
    const rows = buildOperatorPerformanceRows(departmentScopedNotes);
    return mergeProfileStatOwnerRows(rows, departmentScopedProfileStatRows);
  }, [departmentScopedNotes, departmentScopedProfileStatRows]);

  const metrics = useMemo(() => {
    if (canUseBackendDashboard && insightsDashboard?.metrics) {
      return insightsDashboard.metrics;
    }
    const totalPosts = filteredNotes.length;
    let totalViews = 0;
    let totalLikes = 0;
    let totalComments = 0;
    let totalCollects = 0;
    let totalShares = 0;
    let qualityCount = 0;
    let lowQualityCount = 0;
    const activeAccountSet = new Set<string>();
    filteredNotes.forEach((note) => {
      const views = toNumber(note.view_count);
      const comments = toNumber(note.comment_count);
      totalViews += views;
      totalLikes += toNumber(note.liked_count);
      totalComments += comments;
      totalCollects += toNumber(note.collected_count);
      totalShares += toNumber(note.share_count);
      if (views >= 4000 || comments >= 30) qualityCount += 1;
      if (views < 100 && comments < 3) lowQualityCount += 1;
      activeAccountSet.add(getNoteAccountKey(note));
    });
    return {
      activeAccounts: activeAccountSet.size,
      totalPosts,
      totalViews,
      totalLikes,
      totalComments,
      totalCollects,
      totalShares,
      totalEngagement: totalLikes + totalComments + totalCollects + totalShares,
      avgViews: totalViews / Math.max(1, totalPosts),
      avgComments: totalComments / Math.max(1, totalPosts),
      qualityCount,
      lowQualityCount,
    };
  }, [canUseBackendDashboard, filteredNotes, insightsDashboard]);

  const isPortfolioView = isAllAccountsSelected;
  const canViewTeamOperatorTable = viewerRoles.includes('admin') || viewerRoles.includes('xhs_lead') || viewerRoles.includes('brand_lead');
  const showOperatorOverview = isPortfolioView || canViewTeamOperatorTable;
  const rankedAccounts = useMemo(() => (
    [...accountSummaries].sort((a, b) => (
      getAccountRankingValue(b, accountRankingSort) - getAccountRankingValue(a, accountRankingSort)
      || b.score - a.score
      || b.totalViews - a.totalViews
      || b.totalComments - a.totalComments
      || b.totalEngagement - a.totalEngagement
    ))
  ), [accountRankingSort, accountSummaries]);
  const rankedPostsTop50 = useMemo(() => {
    if (!rankingReady && !canUseBackendDashboard) return [];
    return buildPostRankings(filteredNotes, 50).sort((a, b) => (
      getPostRankingValue(b, postRankingSort) - getPostRankingValue(a, postRankingSort)
      || b.score - a.score
      || b.views - a.views
      || b.comments - a.comments
      || b.engagement - a.engagement
    ));
  }, [canUseBackendDashboard, filteredNotes, postRankingSort, rankingReady]);
  const rankedPosts = useMemo(() => rankedPostsTop50.slice(0, 7), [rankedPostsTop50]);
  const personalCarTypeStats = carTypeStats;
  const trendExtrasByLabel = useMemo(() => {
    const grouped = new Map<string, {
      accountKeys: Set<string>;
      qualityCount: number;
      lowQualityCount: number;
      collectCount: number;
    }>();
    filteredNotes.forEach((note) => {
      const date = parseNoteDate(note);
      if (!date) return;
      const label = getTrendBucket(date, range).label;
      const views = toNumber(note.view_count);
      const comments = toNumber(note.comment_count);
      const current = grouped.get(label) || {
        accountKeys: new Set<string>(),
        qualityCount: 0,
        lowQualityCount: 0,
        collectCount: 0,
      };
      current.accountKeys.add(getNoteAccountKey(note));
      if (views >= 4000 || comments >= 30) current.qualityCount += 1;
      if (views < 100 && comments < 3) current.lowQualityCount += 1;
      current.collectCount += toNumber(note.collected_count);
      grouped.set(label, current);
    });
    return grouped;
  }, [filteredNotes, range]);
  const activeAccountTrend = useMemo(() => trend.map((point) => {
    return trendExtrasByLabel.get(point.label)?.accountKeys.size || 0;
  }), [trend, trendExtrasByLabel]);
  const qualityTrend = useMemo(() => trend.map((point) => {
    return trendExtrasByLabel.get(point.label)?.qualityCount || 0;
  }), [trend, trendExtrasByLabel]);
  const lowQualityTrend = useMemo(() => trend.map((point) => {
    return trendExtrasByLabel.get(point.label)?.lowQualityCount || 0;
  }), [trend, trendExtrasByLabel]);
  const collectTrend = useMemo(() => trend.map((point) => {
    return trendExtrasByLabel.get(point.label)?.collectCount || 0;
  }), [trend, trendExtrasByLabel]);
  const kpiCards = [
    { label: '账号数', value: formatInteger(metrics.activeAccounts), note: `当前纳入统计${scopedAccountCount && isAllAccountsSelected ? ` / 账户池 ${formatInteger(scopedAccountCount)}` : ''}`, icon: Users, spark: activeAccountTrend },
    { label: '笔记数', value: formatInteger(metrics.totalPosts), note: '统计周期内发布', icon: CalendarDays, spark: trend.map((point) => point.posts) },
    { label: '浏览/阅读量', value: formatInteger(metrics.totalViews), note: `平均阅读 ${formatInteger(metrics.avgViews)}`, icon: BarChart3, spark: trend.map((point) => point.views) },
    { label: '收藏量', value: formatInteger(metrics.totalCollects), note: '所有笔记累计收藏', icon: Layers3, spark: collectTrend },
    { label: '评论量', value: formatInteger(metrics.totalComments), note: `平均评论 ${formatInteger(metrics.avgComments)}`, icon: CircleDot, spark: trend.map((point) => point.comments) },
    { label: '互动量', value: formatInteger(metrics.totalEngagement), note: '点赞+收藏+评论+分享', icon: Target, spark: trend.map((point) => point.engagement) },
    { label: '优质笔记数量', value: formatInteger(metrics.qualityCount), note: '优质标准：阅读量 ≥ 4000，或评论数 ≥ 30；满足任一条件即计入。', icon: ArrowUpRight, spark: qualityTrend },
    { label: '低效笔记数', value: formatInteger(metrics.lowQualityCount), note: '低效标准：阅读量 < 100，且评论数 < 3；两个条件同时满足才计入。', icon: ArrowDownRight, spark: lowQualityTrend },
  ];
  const aiReport = useMemo(() => buildAiReport({ selectedAccount: isAllAccountsSelected ? selectedOwnerLabel : selectedAccountScopeLabel }), [isAllAccountsSelected, selectedAccountScopeLabel, selectedOwnerLabel]);
  const tagRelation = useMemo(() => (
    tagReady && vehicleStatsReady
      ? buildTagRelationData(deferredFilteredNotes, selectedAccountScopeLabel, vehicleMatches)
      : { accountName: selectedAccountScopeLabel, tagMatrix: [] }
  ), [deferredFilteredNotes, selectedAccountScopeLabel, tagReady, vehicleMatches, vehicleStatsReady]);
  const isDashboardBusy = loading || isDataRendering;
  const showBlockingLoader = loading && !hasLoadedOnce;
  const hasProfileStatData = profileStatOwnerRows.length > 0;
  const isProfileOnlyRange = dataStatus === 'real' && notes.length === 0 && hasProfileStatData;
  const dataStatusLabel = isProfileOnlyRange
    ? '笔记未同步 · 客资统计已更新'
    : dataStatus === 'real' && !detailsReady
    ? '基础看板已显示 · 细节模块准备中...'
    : isDataRendering
    ? '正在渲染看板数据...'
    : loading && hasLoadedOnce
    ? '正在刷新真实数据...'
    : dataStatus === 'real'
    ? `真实数据 · ${formatInteger(filteredNotes.length)} 条笔记 · ${formatInteger(isAllAccountsSelected ? scopedAccountCount : metrics.activeAccounts)} 个账号`
    : dataStatus === 'empty'
      ? '真实接口已连接 · 当前暂无笔记数据'
      : dataStatus === 'error'
        ? `真实数据加载失败：${loadError || '请检查登录态或后端服务'}`
        : '正在加载真实数据';

  return (
    <div className="relative h-full overflow-y-auto bg-white text-slate-900">
      <Script src="/vendor/echarts.min.js" strategy="afterInteractive" onLoad={() => setEchartsReady(true)} />
      <div className="pointer-events-none absolute inset-0 bg-white" />
      <div className="pointer-events-none absolute inset-0 hidden" />

      <main className="relative min-h-full p-3 lg:p-4">
        <div className="mx-auto w-full max-w-none space-y-4">
          <section className={cn('relative z-40 overflow-visible rounded-[28px] p-4', CARD_CLASS)}>
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-bold tracking-[0.14em] text-slate-700">运营数据看板</span>
                  <span className={cn(
                    'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-bold tracking-[0.08em]',
                    dataStatus === 'real' && 'border-emerald-200 bg-emerald-50 text-emerald-800',
                    dataStatus === 'empty' && 'border-slate-200 bg-slate-50 text-slate-600',
                    dataStatus === 'error' && 'border-rose-200 bg-rose-50 text-rose-700',
                    (dataStatus === 'loading' || isDashboardBusy) && 'border-slate-200 bg-slate-50 text-slate-500',
                  )}>
                    {isDashboardBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                    {dataStatusLabel}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-1">
                  <h1 className="text-[30px] font-semibold leading-tight tracking-[-0.045em] text-slate-950 lg:text-[36px]">小红书运营数据看板</h1>
                </div>
              </div>

              <div className="flex flex-col gap-2 xl:min-w-[820px]">
                <div className="flex flex-wrap items-center justify-end gap-3">
                  <DateRangePicker range={range} onChange={setDateRange} />
                  <select
                    value={selectedDepartment}
                    onChange={(event) => {
                      startTransition(() => {
                        setSelectedDepartment(event.target.value as DepartmentFilter);
                        setSelectedOwner('all');
                        setSelectedAccountKeys([]);
                      });
                    }}
                    className={cn(CONTROL_CLASS, 'w-40 px-3')}
                  >
                    <option value="all">全部部门</option>
                    <option value="xhs">小红书部门</option>
                    <option value="brand">品牌中心</option>
                  </select>
                  <select
                    value={selectedOwner}
                    onChange={(event) => {
                      startTransition(() => {
                        setSelectedOwner(event.target.value);
                        setSelectedAccountKeys([]);
                      });
                    }}
                    className={cn(CONTROL_CLASS, 'w-44 px-3')}
                  >
                    <option value="all">全部负责人</option>
                    {ownerOptions.map((owner) => <option key={owner.key} value={owner.key}>{owner.label}</option>)}
                  </select>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索账号" className={cn(CONTROL_CLASS, 'w-40 pl-9 pr-3')} />
                  </div>
                  <AccountMultiSelect
                    className="w-52"
                    options={availableAccounts.map((account) => ({ value: account.key, label: account.label }))}
                    selectedValues={selectedAccountKeys}
                    onChange={(values) => startTransition(() => setSelectedAccountKeys(values))}
                    placeholder={selectedOwner === 'all' ? '全量账户' : '该负责人全部账号'}
                    clearLabel={selectedOwner === 'all' ? '全量账户' : '该负责人全部账号'}
                    emptyLabel="没有匹配的账号"
                  />
                  <button onClick={() => setAiSummaryOpen(true)} className="flex h-10 items-center gap-2 rounded-2xl bg-slate-950 px-4 text-sm font-semibold text-white shadow-[0_16px_34px_rgba(15,23,42,0.22)] transition hover:-translate-y-0.5 hover:bg-slate-800">
                    <Sparkles className="h-4 w-4" />
                    生成 AI 摘要
                  </button>
                </div>
              </div>
            </div>
          </section>

        {showBlockingLoader ? (
          <div className={cn('grid min-h-[520px] place-items-center rounded-[32px]', CARD_CLASS)}>
            <div className="flex items-center gap-3 text-sm font-medium text-slate-500">
              <Loader2 className="h-5 w-5 animate-spin text-slate-700" />
              {isDataRendering ? '正在渲染小红书看板数据...' : '正在加载小红书看板数据...'}
            </div>
          </div>
        ) : (
          <>
            <section className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8">
              {kpiCards.map((metric) => {
                const Icon = metric.icon;
                return (
                <div key={metric.label} className={cn('group relative min-h-[88px] overflow-hidden rounded-[22px] p-3 transition hover:-translate-y-0.5', PANEL_CLASS)}>
                  <div className="absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent via-slate-300 to-transparent" />
                  <div className="absolute -right-8 -top-10 h-28 w-28 rounded-full bg-slate-100/70 blur-2xl transition group-hover:bg-slate-200/80" />
                  <div className="relative grid h-full grid-rows-[auto_1fr] gap-1">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-2xl border border-slate-100 bg-white text-slate-700 shadow-sm">
                        <Icon className="h-4 w-4" />
                      </span>
                      <div className="flex min-w-0 items-center gap-1.5">
                        <div className="whitespace-nowrap text-[10px] font-bold uppercase tracking-[0.04em] text-slate-400">{metric.label}</div>
                        <span className="group/help relative grid h-4 w-4 shrink-0 place-items-center rounded-full text-slate-300 transition hover:text-slate-700">
                          <HelpCircle className="h-3.5 w-3.5" />
                          <span className="pointer-events-none absolute left-1/2 top-6 z-20 w-48 -translate-x-1/2 rounded-2xl border border-slate-200 bg-slate-950 px-3 py-2 text-left text-[11px] font-medium leading-relaxed tracking-normal text-white opacity-0 shadow-[0_18px_44px_rgba(15,23,42,0.22)] transition group-hover/help:translate-y-1 group-hover/help:opacity-100">
                            {metric.note}
                          </span>
                        </span>
                      </div>
                    </div>
                    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_80px] items-center gap-3">
                      <div className="min-w-0 whitespace-nowrap text-left text-[26px] font-semibold leading-none tracking-[-0.04em] text-slate-950 tabular-nums">{metric.value}</div>
                      <div className="w-20 shrink-0 justify-self-end opacity-90">
                        <MiniSparkline id={metric.label} values={metric.spark} />
                      </div>
                    </div>
                  </div>
                </div>
              );})}
            </section>

            {isProfileOnlyRange && (
              <section className="rounded-[24px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 shadow-sm">
                <span className="font-bold">当前日期没有入库笔记。</span>
                笔记、阅读、互动等指标因此为 0；自然客资、特殊自然和广告客资已按当天统计，可在运营负责人总表查看。
              </section>
            )}

            <section className="grid items-start gap-4">
              {isPortfolioView ? (
                <div className="min-w-0 space-y-4 xl:col-start-1 xl:row-start-1">
                  <div className="grid items-stretch gap-4 xl:grid-cols-[minmax(0,1.34fr)_minmax(340px,0.86fr)]">
                    <div className="min-w-0">
                      <section className={cn('relative h-[400px] overflow-hidden p-5', PANEL_CLASS)}>
                        <div className="pointer-events-none absolute inset-0 hidden" />
                        <div className="relative flex h-full flex-col">
                          <div className="flex items-start justify-between gap-3">
                            <PanelTitle eyebrow="排行总览" title="账号 / 帖子排行" />
                            <button
                              type="button"
                              onClick={() => setRankingDetailOpen(true)}
                              className="shrink-0 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950"
                            >
                              查看更多详情
                            </button>
                          </div>
                          <div className="mt-4 min-h-0 flex-1">{rankingReady || canUseBackendDashboard ? (
                            <AccountRankingPanel
                              accounts={rankedAccounts}
                              posts={rankedPosts}
                              accountSort={accountRankingSort}
                              postSort={postRankingSort}
                              onAccountSortChange={setAccountRankingSort}
                              onPostSortChange={setPostRankingSort}
                            />
                          ) : <DetailWarmupBlock />}</div>
                        </div>
                      </section>
                    </div>

                    <div className="min-w-0">
                      <section className={cn('relative h-[400px] overflow-hidden p-5', PANEL_CLASS)}>
                        <div className="pointer-events-none absolute inset-0 hidden" />
                        <div className="relative flex h-full flex-col">
                          <PanelTitle title="车型统计" />
                          <div className="mt-4 min-h-0 flex-1">{vehicleStatsReady ? <CarTypeStatsPanel data={carTypeStats} ready={echartsReady} /> : <DetailWarmupBlock text={`正在分批计算车型统计 ${vehicleMatchProgress}%`} />}</div>
                        </div>
                      </section>
                    </div>
                  </div>

                  <section className={cn('relative overflow-hidden p-5', PANEL_CLASS)}>
                    <div className="pointer-events-none absolute inset-0 hidden" />
                    <div className="relative">
                      <PanelTitle eyebrow="趋势表现" title="发布表现趋势" suffix="柱=浏览 · 线=评论/发帖" />
                      <div className="mt-2"><TrendChart trend={trend} ready={echartsReady} className="h-[380px]" /></div>
                    </div>
                  </section>
                </div>
              ) : (
                <div className="min-w-0 space-y-4 xl:col-start-1 xl:row-start-1">
                  <div className="grid items-stretch gap-4 xl:grid-cols-[440px_minmax(0,1fr)]">
                    <div className="grid min-w-0 gap-4">
                      <section className={cn('relative h-[330px] overflow-hidden p-4', PANEL_CLASS)}>
                        <div className="pointer-events-none absolute inset-0 hidden" />
                        <div className="relative flex h-full flex-col">
                          <PanelTitle title="内容标签" />
                          <div className="mt-1 min-h-0 flex-1">
                            {tagReady && vehicleStatsReady ? <ContentTagGraphPanel data={tagRelation} ready={echartsReady} className="h-full" /> : <DetailWarmupBlock text={`正在分批计算内容标签 ${vehicleMatchProgress}%`} />}
                          </div>
                        </div>
                      </section>

                      <section className={cn('relative h-[390px] overflow-hidden p-4', PANEL_CLASS)}>
                        <div className="pointer-events-none absolute inset-0 hidden" />
                        <div className="relative flex h-full flex-col">
                          <PanelTitle title="车型分布" />
                          <div className="mt-3 min-h-0 flex-1">{vehicleStatsReady ? <CarTypeStatsPanel data={personalCarTypeStats} ready={echartsReady} /> : <DetailWarmupBlock text={`正在分批计算车型分布 ${vehicleMatchProgress}%`} />}</div>
                        </div>
                      </section>
                    </div>

                    <section className={cn('relative h-[736px] overflow-hidden p-5', PANEL_CLASS)}>
                      <div className="pointer-events-none absolute inset-0 hidden" />
                      <div className="relative flex h-full flex-col">
                        <PanelTitle eyebrow="趋势表现" title="发布表现趋势" suffix="柱=浏览 · 线=评论/发帖" />
                        <div className="mt-3 min-h-0 flex-1"><TrendChart trend={trend} ready={echartsReady} className="h-full" /></div>
                      </div>
                    </section>
                  </div>

                  <section className={cn('relative overflow-hidden p-5', PANEL_CLASS)}>
                    <div className="pointer-events-none absolute inset-0 hidden" />
                    <div className="relative">
                      <div className="flex items-start justify-between gap-3">
                        <PanelTitle eyebrow="帖子表现" title="账号帖子排行" suffix="含封面缩略图" />
                        <select
                          value={postRankingSort}
                          onChange={(event) => setPostRankingSort(event.target.value as RankingSortKey)}
                          className={cn(CONTROL_CLASS, 'h-9 w-28 px-2 text-xs shadow-sm')}
                        >
                          {RANKING_SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                      </div>
                      <div className="mt-4">{rankingReady || canUseBackendDashboard ? <PersonalPostRankingChart posts={rankedPosts} postSort={postRankingSort} ready={echartsReady} onOpenPost={setActiveDetailNote} /> : <DetailWarmupBlock />}</div>
                    </div>
                  </section>
                </div>
              )}

              {showOperatorOverview && (operatorReady || canUseBackendDashboard ? <OperatorPerformanceSection rows={teamOperatorRows} range={range} ready={echartsReady} accountScope={profileStatAccountScope} /> : (
                <section className={cn('p-5', PANEL_CLASS)}>
                  <PanelTitle eyebrow="运营负责人" title="运营负责人总表" suffix="细节模块准备中" />
                  <div className="mt-4"><DetailWarmupBlock /></div>
                </section>
              ))}

            </section>
          </>
        )}
          </div>
        </main>
        {activeDetailNote && (
          <InsightPostDetailModal
            note={activeDetailNote}
            onClose={() => setActiveDetailNote(null)}
          />
        )}
        {rankingDetailOpen && (
          <RankingDetailModal
            accounts={rankedAccounts}
            posts={rankedPostsTop50}
            accountSort={accountRankingSort}
            postSort={postRankingSort}
            onClose={() => setRankingDetailOpen(false)}
            onOpenPost={(note) => {
              setRankingDetailOpen(false);
              setActiveDetailNote(note);
            }}
          />
        )}
        {aiSummaryOpen && (
          <AiSummaryModal
            report={aiReport}
            onClose={() => setAiSummaryOpen(false)}
          />
        )}
    </div>
  );
}

function PanelTitle({ eyebrow, title, suffix }: { eyebrow?: string; title: string; suffix?: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        {eyebrow && <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">{eyebrow}</div>}
        <h2 className={cn('text-xl font-semibold tracking-tight text-slate-950', eyebrow && 'mt-1')}>{title}</h2>
      </div>
      {suffix && <span className="shrink-0 whitespace-nowrap rounded-full bg-white/80 px-3 py-1 text-xs font-medium text-slate-500 shadow-sm">{suffix}</span>}
    </div>
  );
}

function EmptyBlock({ text }: { text: string }) {
  return <div className="grid place-items-center rounded-3xl border border-dashed border-slate-200 bg-white/55 py-10 text-sm text-slate-400">{text}</div>;
}

function DetailWarmupBlock({ text = '正在渲染细节模块...' }: { text?: string }) {
  return (
    <div className="grid h-full min-h-[220px] place-items-center rounded-3xl border border-slate-100 bg-white/65 px-4 text-center">
      <div className="flex flex-col items-center gap-3 text-sm font-medium text-slate-400">
        <Loader2 className="h-6 w-6 animate-spin text-slate-700" />
        <span>{text}</span>
      </div>
    </div>
  );
}
