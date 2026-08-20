'use client';

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from 'react';
import {
  batchUpdateXhsAccountNotes,
  cancelPost,
  cancelXhsAccountNoteSyncJob,
  exportXhsReport,
  getEnvironments,
  getXhsBrowserEnvironmentStatuses,
  getXhsAccountNoteSyncJob,
  getXhsAccountNoteSyncHistory,
  getPosts,
  getXhsAccountNotes,
  getXhsCreativeReportCompare,
  getXhsReport,
  getXhsReportAccounts,
  getXhsSyncRunnerBrowseOverview,
  publishPost,
  publishPostNow,
  recordXhsAccountNoteBrowse,
  refreshXhsReportCache,
  syncPostStats,
  syncXhsAccountNoteEngagements,
  syncXhsAccountNotes,
  syncXhsAccountNoteDetails,
  syncXhsAccountNoteEngagementStats,
  syncXhsAccountNoteStats,
  retryFailedXhsAccountNoteSyncHistory,
  tagXhsAccountNoteContent,
  updateXhsAccountNote,
  updatePost,
  uploadImages,
  type XHSAccountNote,
  type XHSAccountNoteSyncJob,
  type XHSAccountSyncHistoryRun,
  type XHSBrowserEnvironmentStatus,
  type XHSCreativeReportCompareResponse,
  type XHSEnvironment,
  type XHSPost,
  type XHSReportResponse,
  type XHSReportType,
  type XHSSyncRunnerBrowseOverview,
} from '@/services/xhsApi';
import { toast } from '@/lib/toast';
import GalleryPicker, { type GalleryPickerImage } from '@/components/ai/GalleryPicker';
import { datetimeLocalToIso, toDatetimeLocalFromISO, toDatetimeLocalValue } from '@/lib/dateTime';

const STATUS_LABELS: Record<string, string> = {
  scheduled: '待发布',
  cancelled: '已取消',
  publishing: '发布中',
  success: '已发布',
  failed: '失败',
  deleted: '已删除',
};

type ManageView = 'auto' | 'account' | 'simple' | 'standard' | 'creative' | 'simple_note' | 'standard_note';

const STATUS_COLORS: Record<string, string> = {
  scheduled: 'bg-amber-50 text-amber-700 border-amber-200',
  cancelled: 'bg-slate-100 text-slate-600 border-slate-200',
  publishing: 'bg-rose-50 text-rose-700 border-rose-200',
  success: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  failed: 'bg-rose-50 text-rose-700 border-rose-200',
  deleted: 'bg-slate-100 text-slate-600 border-slate-200',
};

const AI_ORIGIN_LABELS: Record<string, string> = {
  '': '未设置',
  manual: '纯手工',
  text_ai: '仅文案 AI',
  image_ai: '仅图片 AI',
  all_ai: '图文都 AI',
};

const AI_ORIGIN_ACTIONS: Array<{ value: '' | 'manual' | 'text_ai' | 'image_ai' | 'all_ai'; short: string; full: string }> = [
  { value: '', short: '未设', full: '未设置' },
  { value: 'manual', short: '手工', full: '纯手工' },
  { value: 'text_ai', short: '文AI', full: '仅文案 AI' },
  { value: 'image_ai', short: '图AI', full: '仅图片 AI' },
  { value: 'all_ai', short: '图文AI', full: '图文都 AI' },
];

const ACCOUNT_NOTES_SYNC_JOB_STORAGE_KEY = 'xhs_account_notes_sync_job_id';
const ACCOUNT_ENGAGEMENT_SYNC_JOB_STORAGE_KEY = 'xhs_account_engagement_sync_job_id';
const ACCOUNT_NOTE_DETAILS_SYNC_JOB_STORAGE_KEY = 'xhs_account_note_details_sync_job_id';
const ACCOUNT_SYNC_PROGRESS_PANEL_STORAGE_KEY = 'xhs_account_sync_progress_panel';

function getAiOriginBadgeTone(value: string): string {
  if (!value) return 'border-amber-200 bg-amber-50 text-amber-700';
  if (value === 'manual') return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  if (value === 'text_ai') return 'border-sky-200 bg-sky-50 text-sky-700';
  if (value === 'image_ai') return 'border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700';
  return 'border-violet-200 bg-violet-50 text-violet-700';
}

function getAiOriginDotTone(value: string): string {
  if (!value) return 'bg-amber-500 shadow-[0_0_0_4px_rgba(245,158,11,0.14)]';
  if (value === 'manual') return 'bg-emerald-500';
  if (value === 'text_ai') return 'bg-sky-500';
  if (value === 'image_ai') return 'bg-fuchsia-500';
  return 'bg-violet-500';
}

function getAiOriginDotMotion(value: string): string {
  return value ? '' : 'animate-pulse';
}

function getCreativeColumnCellClass(key: string): string {
  if (key === 'creativity_image') return 'min-w-[116px] w-[116px]';
  if (key === 'note_material') return 'min-w-[220px] max-w-[260px] whitespace-normal break-words leading-5';
  if (key === 'campaign_name' || key === 'unit_name') return 'min-w-[180px] max-w-[220px] whitespace-normal break-words leading-5';
  if (key === 'ai_origin_type') return 'min-w-[92px] whitespace-nowrap';
  if (key === 'time') return 'whitespace-nowrap';
  return 'whitespace-nowrap';
}

function getSimpleStandardColumnCellClass(key: string): string {
  if (key === 'campaign_name') return 'min-w-[240px] max-w-[320px] whitespace-normal break-words leading-5';
  if (key === 'account_name') return 'min-w-[136px] max-w-[176px] whitespace-normal break-words leading-5';
  if (key === 'account_id' || key === 'campaign_id') return 'min-w-[118px] whitespace-nowrap font-mono text-xs tracking-tight text-slate-500';
  if (key === 'time') return 'min-w-[104px] whitespace-nowrap text-xs text-slate-500';
  return 'min-w-[96px] whitespace-nowrap';
}

function getNoteReportColumnCellClass(key: string): string {
  if (key === 'note_image') return 'min-w-[116px] w-[116px]';
  if (key === 'note_title') return 'min-w-[240px] max-w-[320px] whitespace-normal break-words leading-5';
  if (key === 'campaign_name') return 'min-w-[200px] max-w-[260px] whitespace-normal break-words leading-5';
  if (key === 'account_name') return 'min-w-[136px] max-w-[176px] whitespace-normal break-words leading-5';
  if (key === 'account_id' || key === 'note_id' || key === 'campaign_id') return 'min-w-[118px] whitespace-nowrap font-mono text-xs tracking-tight text-slate-500';
  if (key === 'time') return 'min-w-[104px] whitespace-nowrap text-xs text-slate-500';
  return 'min-w-[96px] whitespace-nowrap';
}

function getReportColumnCellClass(
  view: ManageView,
  key: string,
): string {
  if (view === 'creative') return getCreativeColumnCellClass(key);
  if (view === 'simple_note' || view === 'standard_note') return getNoteReportColumnCellClass(key);
  if (view === 'simple' || view === 'standard') return getSimpleStandardColumnCellClass(key);
  return '';
}

function getCreativeReportAiOriginLabel(row: Record<string, any>): string {
  const matched = Boolean(row.account_note_matched);
  const value = String(row.ai_origin_type ?? '').trim();
  if (!matched) return '未找到';
  if (!value) return '未设置';
  return AI_ORIGIN_LABELS[value] ?? '未设置';
}

function normalizeCreativeImageUrl(value: unknown): string {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  if (raw.startsWith('http://')) return `https://${raw.slice('http://'.length)}`;
  return raw;
}

function normalizeAccountNoteCoverUrl(value: unknown): string {
  return normalizeCreativeImageUrl(value);
}

function buildAccountNoteCoverFallbackUrl(value: unknown): string {
  const normalized = normalizeAccountNoteCoverUrl(value);
  if (!normalized) return '';
  return normalized.replace(/![^/?#]+$/, '');
}

function buildAccountNoteCoverRequestUrl(base: string, retrySeed: number): string {
  if (!base) return '';
  if (!retrySeed) return base;
  const connector = base.includes('?') ? '&' : '?';
  return `${base}${connector}xhs_retry=${retrySeed}`;
}

const waitForPaint = () => new Promise<void>((resolve) => {
  requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
});

function isInteractiveAccountNoteTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(target.closest('button, a, input, select, textarea, label, [role="button"], [data-ai-origin-menu-root="true"]'));
}

const ACCOUNT_NOTE_COVER_SUCCESS_CACHE = new Map<string, 'primary' | 'fallback'>();

type AccountNoteCoverThumbProps = {
  src?: string | null;
  title: string;
  onPreview: () => void;
};

function AccountNoteCoverThumb({ src, title, onPreview }: AccountNoteCoverThumbProps) {
  const primarySrc = normalizeAccountNoteCoverUrl(src);
  const fallbackSrc = buildAccountNoteCoverFallbackUrl(src);
  const cacheKey = primarySrc || fallbackSrc;
  const cachedMode = cacheKey ? ACCOUNT_NOTE_COVER_SUCCESS_CACHE.get(cacheKey) : undefined;
  const initialMode =
    cachedMode === 'fallback' && fallbackSrc ? 'fallback' : primarySrc ? 'primary' : 'fallback';
  const [sourceMode, setSourceMode] = useState<'primary' | 'fallback'>(initialMode);
  const [retrySeed, setRetrySeed] = useState(0);
  const [retryCount, setRetryCount] = useState(0);
  const [status, setStatus] = useState<'loading' | 'loaded' | 'error'>(cacheKey ? (cachedMode ? 'loaded' : 'loading') : 'error');
  const currentBaseSrc = sourceMode === 'fallback' && fallbackSrc ? fallbackSrc : primarySrc;
  const currentSrc = useMemo(
    () => buildAccountNoteCoverRequestUrl(currentBaseSrc, retrySeed),
    [currentBaseSrc, retrySeed],
  );

  useEffect(() => {
    const nextCacheKey = primarySrc || fallbackSrc;
    const nextCachedMode = nextCacheKey ? ACCOUNT_NOTE_COVER_SUCCESS_CACHE.get(nextCacheKey) : undefined;
    const nextMode =
      nextCachedMode === 'fallback' && fallbackSrc ? 'fallback' : primarySrc ? 'primary' : 'fallback';
    setSourceMode(nextMode);
    setRetrySeed(0);
    setRetryCount(0);
    setStatus(nextCacheKey ? (nextCachedMode ? 'loaded' : 'loading') : 'error');
  }, [fallbackSrc, primarySrc]);

  useEffect(() => {
    if (status !== 'loading' || !currentBaseSrc) return undefined;
    if (retryCount >= 6 && (sourceMode === 'fallback' || !fallbackSrc || fallbackSrc === primarySrc)) return undefined;

    const timer = window.setTimeout(() => {
      if (sourceMode === 'primary' && fallbackSrc && fallbackSrc !== primarySrc) {
        setSourceMode('fallback');
        setRetrySeed(0);
        setRetryCount((count) => count + 1);
        setStatus('loading');
        return;
      }
      if (retryCount < 6) {
        setRetryCount((count) => count + 1);
        setRetrySeed(Date.now());
        setStatus('loading');
        return;
      }
      setStatus('error');
    }, 2800);

    return () => window.clearTimeout(timer);
  }, [currentBaseSrc, fallbackSrc, primarySrc, retryCount, sourceMode, status]);

  useEffect(() => {
    if (status !== 'error' || !currentBaseSrc || retryCount >= 10) return undefined;
    const timer = window.setTimeout(() => {
      setRetryCount((count) => count + 1);
      setRetrySeed(Date.now());
      setStatus('loading');
    }, 4000);
    return () => window.clearTimeout(timer);
  }, [currentBaseSrc, retryCount, status]);

  return (
    <button
      type="button"
      className="group relative block h-full w-full overflow-hidden"
      onClick={onPreview}
      title="点击放大查看封面"
    >
      {currentSrc ? (
        <>
          <div
            className={`absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(99,102,241,0.16),rgba(226,232,240,0.7)_56%,rgba(255,255,255,0.92))] transition-opacity duration-300 ${
              status === 'loaded' ? 'opacity-100' : 'opacity-0'
            }`}
          />
          <img
            src={currentSrc}
            alt={title}
            className={`relative z-[1] h-full w-full object-contain p-1.5 transition-all duration-300 ${
              status === 'loaded' ? 'scale-100 opacity-100 group-hover:scale-[1.03]' : 'scale-[1.02] opacity-0'
            }`}
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onLoad={() => {
              if (cacheKey) {
                ACCOUNT_NOTE_COVER_SUCCESS_CACHE.set(cacheKey, sourceMode);
              }
              setStatus('loaded');
            }}
            onError={() => {
              if (cacheKey) {
                ACCOUNT_NOTE_COVER_SUCCESS_CACHE.delete(cacheKey);
              }
              if (sourceMode === 'primary' && fallbackSrc && fallbackSrc !== primarySrc) {
                setSourceMode('fallback');
                setRetrySeed(0);
                setRetryCount((count) => count + 1);
                setStatus('loading');
                return;
              }
              if (retryCount < 6) {
                setRetryCount((count) => count + 1);
                setRetrySeed(Date.now());
                setStatus('loading');
                return;
              }
              setStatus('error');
            }}
          />
          {status === 'loading' && (
            <div className="absolute inset-0 grid place-items-center bg-[linear-gradient(145deg,rgba(248,250,252,0.94),rgba(226,232,240,0.92))]">
              <div className="flex flex-col items-center gap-1.5">
                <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" />
                <span className="text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-400">Loading</span>
              </div>
            </div>
          )}
        </>
      ) : null}

      {status === 'error' && (
        <div className="absolute inset-0 flex h-full w-full items-center justify-center bg-[radial-gradient(circle_at_top,_rgba(148,163,184,0.12),_rgba(255,255,255,0.96))]">
          <div className="flex flex-col items-center gap-1 text-slate-400">
            <span className="text-base leading-none">□</span>
            <span className="text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-400">Retrying</span>
          </div>
        </div>
      )}

      <div className="pointer-events-none absolute inset-0 rounded-[inherit] ring-1 ring-inset ring-white/55" />
    </button>
  );
}

function extractHashTags(text: string): string[] {
  const regex = /#([^\s#，。！？、,.!?:;；（）()【】\[\]<>《》]+)/g;
  const found: string[] = [];
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    const tag = (match[1] || '').trim();
    if (tag && !found.includes(tag)) found.push(tag);
  }
  return found.slice(0, 20);
}

function createImageClientId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `img_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

type ReportColumn = {
  key: string;
  label: string;
  getValue: (row: Record<string, any>) => string | number;
};

function fnum(value: unknown): number {
  const num = Number(String(value ?? '').replace('%', '').trim() || 0);
  return Number.isFinite(num) ? num : 0;
}

function round(value: number, digits: number): number {
  const base = 10 ** digits;
  return Math.round(value * base) / base;
}

const SIMPLE_STANDARD_REPORT_COLUMNS: ReportColumn[] = [
  { key: 'account_name', label: '账户名称', getValue: (row) => String(row.account_name ?? '') },
  { key: 'account_id', label: '投放ID', getValue: (row) => String(row.account_id ?? '') },
  { key: 'time', label: '时间', getValue: (row) => String(row.time ?? '') },
  { key: 'campaign_name', label: '计划名称(标的名称)', getValue: (row) => String(row.campaign_name ?? '') },
  { key: 'campaign_id', label: '计划ID(标的ID)', getValue: (row) => String(row.campaign_id ?? '') },
  { key: 'fee', label: '消费', getValue: (row) => round(fnum(row.fee), 2) },
  { key: 'impression', label: '展现量', getValue: (row) => Math.trunc(fnum(row.impression)) },
  { key: 'click', label: '点击量', getValue: (row) => Math.trunc(fnum(row.click)) },
  { key: 'like', label: '点赞', getValue: (row) => Math.trunc(fnum(row.like)) },
  { key: 'comment', label: '评论', getValue: (row) => Math.trunc(fnum(row.comment)) },
  { key: 'collect', label: '收藏', getValue: (row) => Math.trunc(fnum(row.collect)) },
  { key: 'follow', label: '关注', getValue: (row) => Math.trunc(fnum(row.follow)) },
  { key: 'share', label: '分享', getValue: (row) => Math.trunc(fnum(row.share)) },
  { key: 'interaction', label: '互动量', getValue: (row) => Math.trunc(fnum(row.interaction)) },
  { key: 'action_button_click', label: '行动按钮点击量', getValue: (row) => Math.trunc(fnum(row.action_button_click)) },
  { key: 'message_consult', label: '私信进线数', getValue: (row) => Math.trunc(fnum(row.message_consult)) },
  { key: 'msg_leads_num', label: '私信留资数', getValue: (row) => Math.trunc(fnum(row.msg_leads_num)) },
  { key: 'message_user', label: '私信进线人数', getValue: (row) => Math.trunc(fnum(row.message_user)) },
  { key: 'msg_leads_user_cnt', label: '私信留资人数', getValue: (row) => Math.trunc(fnum(row.msg_leads_user_cnt)) },
  { key: 'initiative_message', label: '私信开口数', getValue: (row) => Math.trunc(fnum(row.initiative_message)) },
  { key: 'msg_chat_user_cnt', label: '私信开口人数', getValue: (row) => Math.trunc(fnum(row.msg_chat_user_cnt)) },
  { key: 'message', label: '私信开口条数', getValue: (row) => Math.trunc(fnum(row.message)) },
];

const CREATIVE_REPORT_COLUMNS: ReportColumn[] = [
  { key: 'creativity_image', label: '创意图片', getValue: (row) => String(row.creativity_image ?? '') },
  { key: 'time', label: '时间', getValue: (row) => String(row.time ?? '') },
  { key: 'note_material', label: '笔记/素材', getValue: (row) => String(row.note_material ?? '') },
  { key: 'ai_origin_type', label: '标记', getValue: (row) => getCreativeReportAiOriginLabel(row) },
  { key: 'unit_name', label: '单元名称', getValue: (row) => String(row.unit_name ?? '') },
  { key: 'unit_id', label: '单元ID', getValue: (row) => String(row.unit_id ?? '') },
  { key: 'campaign_name', label: '计划名称', getValue: (row) => String(row.campaign_name ?? '') },
  { key: 'campaign_id', label: '计划ID', getValue: (row) => String(row.campaign_id ?? '') },
  { key: 'fee', label: '消费', getValue: (row) => round(fnum(row.fee), 2) },
  { key: 'impression', label: '展现量', getValue: (row) => Math.trunc(fnum(row.impression)) },
  { key: 'click', label: '点击量', getValue: (row) => Math.trunc(fnum(row.click)) },
  { key: 'ctr', label: '点击率', getValue: (row) => String(row.ctr ?? '') },
  { key: 'cpc', label: '平均点击成本', getValue: (row) => String(row.cpc ?? '') },
  { key: 'cpm', label: '平均千次展示费用', getValue: (row) => String(row.cpm ?? '') },
  { key: 'interaction', label: '互动量', getValue: (row) => Math.trunc(fnum(row.interaction)) },
  { key: 'avg_interaction_cost', label: '平均互动成本', getValue: (row) => String(row.avg_interaction_cost ?? '') },
  { key: 'play_5s', label: '5s播放量', getValue: (row) => String(row.play_5s ?? '') },
  { key: 'message_consult', label: '私信进线数', getValue: (row) => Math.trunc(fnum(row.message_consult)) },
  { key: 'initiative_message', label: '私信开口数', getValue: (row) => Math.trunc(fnum(row.initiative_message)) },
  { key: 'msg_leads_num', label: '私信留资数', getValue: (row) => Math.trunc(fnum(row.msg_leads_num)) },
  { key: 'message_consult_cost', label: '私信进线成本', getValue: (row) => String(row.message_consult_cost ?? '') },
  { key: 'initiative_message_cost', label: '私信开口成本', getValue: (row) => String(row.initiative_message_cost ?? '') },
  { key: 'msg_leads_cost', label: '私信留资成本', getValue: (row) => String(row.msg_leads_cost ?? '') },
  { key: 'shop_pay_order_num_15d', label: '店铺成交订单量(15日)', getValue: (row) => String(row.shop_pay_order_num_15d ?? '') },
  { key: 'shop_pay_order_cvr_15d', label: '店铺成交订单转化率(15日)', getValue: (row) => String(row.shop_pay_order_cvr_15d ?? '') },
];

const EASY_NOTE_REPORT_COLUMNS: ReportColumn[] = [
  { key: 'account_name', label: '账户名称', getValue: (row) => String(row.account_name ?? '') },
  { key: 'account_id', label: '投放ID', getValue: (row) => String(row.account_id ?? '') },
  { key: 'time', label: '时间', getValue: (row) => String(row.time ?? '') },
  { key: 'note_title', label: '笔记标题', getValue: (row) => String(row.note_title ?? '') },
  { key: 'note_id', label: '笔记ID', getValue: (row) => String(row.note_id ?? '') },
  { key: 'creativity_name', label: '创意名称', getValue: (row) => String(row.creativity_name ?? '') },
  { key: 'creativity_id', label: '创意ID', getValue: (row) => String(row.creativity_id ?? '') },
  { key: 'fee', label: '消费', getValue: (row) => round(fnum(row.fee), 2) },
  { key: 'impression', label: '展现量', getValue: (row) => Math.trunc(fnum(row.impression)) },
  { key: 'click', label: '点击量', getValue: (row) => Math.trunc(fnum(row.click)) },
  { key: 'ctr', label: '点击率', getValue: (row) => String(row.ctr ?? '') },
  { key: 'like', label: '点赞', getValue: (row) => Math.trunc(fnum(row.like)) },
  { key: 'comment', label: '评论', getValue: (row) => Math.trunc(fnum(row.comment)) },
  { key: 'collect', label: '收藏', getValue: (row) => Math.trunc(fnum(row.collect)) },
  { key: 'follow', label: '关注', getValue: (row) => Math.trunc(fnum(row.follow)) },
  { key: 'share', label: '分享', getValue: (row) => Math.trunc(fnum(row.share)) },
  { key: 'interaction', label: '互动量', getValue: (row) => Math.trunc(fnum(row.interaction)) },
  { key: 'action_button_click', label: '行动按钮点击量', getValue: (row) => Math.trunc(fnum(row.action_button_click)) },
  { key: 'message_consult', label: '私信进线数', getValue: (row) => Math.trunc(fnum(row.message_consult)) },
  { key: 'msg_leads_num', label: '私信留资数', getValue: (row) => Math.trunc(fnum(row.msg_leads_num)) },
  { key: 'message_user', label: '私信进线人数', getValue: (row) => Math.trunc(fnum(row.message_user)) },
  { key: 'msg_leads_user_cnt', label: '私信留资人数', getValue: (row) => Math.trunc(fnum(row.msg_leads_user_cnt)) },
  { key: 'initiative_message', label: '私信开口数', getValue: (row) => Math.trunc(fnum(row.initiative_message)) },
  { key: 'msg_chat_user_cnt', label: '私信开口人数', getValue: (row) => Math.trunc(fnum(row.msg_chat_user_cnt)) },
  { key: 'message', label: '私信开口条数', getValue: (row) => Math.trunc(fnum(row.message)) },
];

const STANDARD_NOTE_REPORT_COLUMNS: ReportColumn[] = [
  { key: 'account_name', label: '账户名称', getValue: (row) => String(row.account_name ?? '') },
  { key: 'account_id', label: '投放ID', getValue: (row) => String(row.account_id ?? '') },
  { key: 'note_image', label: '笔记图片', getValue: (row) => String(row.note_image ?? '') },
  { key: 'time', label: '时间', getValue: (row) => String(row.time ?? '') },
  { key: 'note_title', label: '笔记标题', getValue: (row) => String(row.note_title ?? '') },
  { key: 'note_id', label: '笔记ID', getValue: (row) => String(row.note_id ?? '') },
  { key: 'fee', label: '消费', getValue: (row) => round(fnum(row.fee), 2) },
  { key: 'impression', label: '展现量', getValue: (row) => Math.trunc(fnum(row.impression)) },
  { key: 'click', label: '点击量', getValue: (row) => Math.trunc(fnum(row.click)) },
  { key: 'ctr', label: '点击率', getValue: (row) => String(row.ctr ?? '') },
  { key: 'like', label: '点赞', getValue: (row) => Math.trunc(fnum(row.like)) },
  { key: 'comment', label: '评论', getValue: (row) => Math.trunc(fnum(row.comment)) },
  { key: 'collect', label: '收藏', getValue: (row) => Math.trunc(fnum(row.collect)) },
  { key: 'follow', label: '关注', getValue: (row) => Math.trunc(fnum(row.follow)) },
  { key: 'share', label: '分享', getValue: (row) => Math.trunc(fnum(row.share)) },
  { key: 'interaction', label: '互动量', getValue: (row) => Math.trunc(fnum(row.interaction)) },
  { key: 'action_button_click', label: '行动按钮点击量', getValue: (row) => Math.trunc(fnum(row.action_button_click)) },
  { key: 'message_consult', label: '私信进线数', getValue: (row) => Math.trunc(fnum(row.message_consult)) },
  { key: 'msg_leads_num', label: '私信留资数', getValue: (row) => Math.trunc(fnum(row.msg_leads_num)) },
  { key: 'message_user', label: '私信进线人数', getValue: (row) => Math.trunc(fnum(row.message_user)) },
  { key: 'msg_leads_user_cnt', label: '私信留资人数', getValue: (row) => Math.trunc(fnum(row.msg_leads_user_cnt)) },
  { key: 'initiative_message', label: '私信开口数', getValue: (row) => Math.trunc(fnum(row.initiative_message)) },
  { key: 'msg_chat_user_cnt', label: '私信开口人数', getValue: (row) => Math.trunc(fnum(row.msg_chat_user_cnt)) },
  { key: 'message', label: '私信开口条数', getValue: (row) => Math.trunc(fnum(row.message)) },
];

type CreativeCompareMetricKey =
  | 'note_count'
  | 'fee'
  | 'impression'
  | 'click'
  | 'ctr'
  | 'cpc'
  | 'cpm'
  | 'interaction'
  | 'avg_interaction_cost'
  | 'message_consult'
  | 'initiative_message'
  | 'msg_leads_num'
  | 'message_consult_cost'
  | 'initiative_message_cost'
  | 'msg_leads_cost'
  ;

const CREATIVE_COMPARE_METRICS: Array<{ key: CreativeCompareMetricKey; label: string; kind: 'money' | 'count' | 'percent' }> = [
  { key: 'fee', label: '消费', kind: 'money' },
  { key: 'impression', label: '展现量', kind: 'count' },
  { key: 'click', label: '点击量', kind: 'count' },
  { key: 'ctr', label: '点击率', kind: 'percent' },
  { key: 'cpc', label: '平均点击成本', kind: 'money' },
  { key: 'cpm', label: '平均千次展示费用', kind: 'money' },
  { key: 'interaction', label: '互动量', kind: 'count' },
  { key: 'avg_interaction_cost', label: '平均互动成本', kind: 'money' },
  { key: 'message_consult', label: '私信进线数', kind: 'count' },
  { key: 'initiative_message', label: '私信开口数', kind: 'count' },
  { key: 'msg_leads_num', label: '私信留资数', kind: 'count' },
  { key: 'message_consult_cost', label: '私信进线成本', kind: 'money' },
  { key: 'initiative_message_cost', label: '私信开口成本', kind: 'money' },
  { key: 'msg_leads_cost', label: '私信留资成本', kind: 'money' },
];

const CREATIVE_COMPARE_CARD_METRICS: Array<{ key: CreativeCompareMetricKey; label: string; kind: 'money' | 'count' | 'percent' }> = [
  { key: 'note_count', label: '帖子总量', kind: 'count' },
  ...CREATIVE_COMPARE_METRICS,
];

const CREATIVE_COMPARE_TAG_STYLES: Record<string, { line: string; fill: string; chip: string; soft: string }> = {
  manual: {
    line: '#16a34a',
    fill: 'rgba(22,163,74,0.14)',
    chip: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    soft: 'bg-emerald-500',
  },
  text_ai: {
    line: '#0284c7',
    fill: 'rgba(2,132,199,0.14)',
    chip: 'border-sky-200 bg-sky-50 text-sky-700',
    soft: 'bg-sky-500',
  },
  image_ai: {
    line: '#c026d3',
    fill: 'rgba(192,38,211,0.14)',
    chip: 'border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700',
    soft: 'bg-fuchsia-500',
  },
  all_ai: {
    line: '#7c3aed',
    fill: 'rgba(124,58,237,0.14)',
    chip: 'border-violet-200 bg-violet-50 text-violet-700',
    soft: 'bg-violet-500',
  },
};

const CREATIVE_COMPARE_CARD_SURFACES: Record<string, { shell: string; hero: string; glow: string; section: string }> = {
  manual: {
    shell: 'border-emerald-200/80 bg-[linear-gradient(180deg,rgba(245,252,247,0.98),rgba(255,255,255,0.98))]',
    hero: 'bg-[linear-gradient(135deg,rgba(12,74,45,0.98),rgba(22,163,74,0.88))] text-white',
    glow: 'shadow-[0_18px_36px_rgba(22,163,74,0.18)]',
    section: 'border-emerald-100 bg-emerald-50/60',
  },
  text_ai: {
    shell: 'border-sky-200/80 bg-[linear-gradient(180deg,rgba(242,249,255,0.98),rgba(255,255,255,0.98))]',
    hero: 'bg-[linear-gradient(135deg,rgba(8,47,73,0.98),rgba(2,132,199,0.9))] text-white',
    glow: 'shadow-[0_18px_36px_rgba(2,132,199,0.2)]',
    section: 'border-sky-100 bg-sky-50/65',
  },
  image_ai: {
    shell: 'border-fuchsia-200/80 bg-[linear-gradient(180deg,rgba(255,246,254,0.98),rgba(255,255,255,0.98))]',
    hero: 'bg-[linear-gradient(135deg,rgba(112,26,117,0.98),rgba(192,38,211,0.9))] text-white',
    glow: 'shadow-[0_18px_36px_rgba(192,38,211,0.18)]',
    section: 'border-fuchsia-100 bg-fuchsia-50/65',
  },
  all_ai: {
    shell: 'border-violet-200/80 bg-[linear-gradient(180deg,rgba(247,245,255,0.98),rgba(255,255,255,0.98))]',
    hero: 'bg-[linear-gradient(135deg,rgba(49,46,129,0.98),rgba(124,58,237,0.9))] text-white',
    glow: 'shadow-[0_18px_36px_rgba(124,58,237,0.18)]',
    section: 'border-violet-100 bg-violet-50/65',
  },
};

function formatCreativeCompareValue(metricKey: CreativeCompareMetricKey, value: unknown): string {
  const metric = CREATIVE_COMPARE_CARD_METRICS.find((item) => item.key === metricKey);
  const num = Number(value ?? 0);
  const normalized = Number.isFinite(num) ? num : 0;
  if (!metric) return String(value ?? '-');
  if (metric.kind === 'percent') return `${normalized.toFixed(2)}%`;
  if (metric.kind === 'money') return normalized.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return Math.round(normalized).toLocaleString('zh-CN');
}

function getCreativeCompareMetricLabel(metricKey: CreativeCompareMetricKey): string {
  return CREATIVE_COMPARE_METRICS.find((item) => item.key === metricKey)?.label || metricKey;
}

function buildSparklinePath(values: number[], width: number, height: number, padding = 8): string {
  if (!values.length) return '';
  const normalized = values.map((value) => (Number.isFinite(value) ? value : 0));
  const max = Math.max(...normalized, 0);
  const min = Math.min(...normalized, 0);
  const range = max - min || 1;
  return normalized
    .map((value, index) => {
      const x = normalized.length === 1
        ? width / 2
        : padding + (index / Math.max(1, normalized.length - 1)) * (width - padding * 2);
      const y = height - padding - ((value - min) / range) * (height - padding * 2);
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

function getReportTypeByView(view: ManageView): XHSReportType | null {
  if (view === 'simple' || view === 'standard' || view === 'creative' || view === 'simple_note' || view === 'standard_note') return view;
  return null;
}

function getReportViewLabel(view: ManageView): string {
  if (view === 'auto') return '自动发布内容';
  if (view === 'account') return '账号数据';
  if (view === 'simple') return '简单投按计划';
  if (view === 'standard') return '标准投按计划';
  if (view === 'simple_note') return '简单投笔记报表';
  if (view === 'standard_note') return '标准投笔记报表';
  return '创意报表';
}

function InlineSpinner({ label }: { label: string }) {
  return (
    <div className="grid place-items-center py-20">
      <div className="flex items-center gap-3 rounded-full border border-slate-200 bg-white/80 px-4 py-2 text-sm text-slate-500 shadow-sm">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-indigo-500" />
        <span>{label}</span>
      </div>
    </div>
  );
}

function formatAccountNotePublishedAt(value?: string | null): string {
  if (!value) return '-';
  const normalized = value.endsWith('Z') ? value : value.replace(' ', 'T');
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return value;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

function getAccountNoteContentPreview(note: XHSAccountNote): string {
  const content = String(note.content || '').trim();
  if (content) return content;
  const reason = String(note.content_missing_reason || '').trim();
  if (reason) return reason;
  return note.detail_synced_at ? '详情已同步，但正文仍为空。' : '暂未同步帖子正文。';
}

function getAccountNoteDetailStatusTone(note: XHSAccountNote): string {
  if (note.detail_synced_at && String(note.content || '').trim()) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  }
  if (note.detail_synced_at) {
    return 'border-amber-200 bg-amber-50 text-amber-700';
  }
  return 'border-slate-200 bg-slate-100 text-slate-500';
}

function getAccountNoteContentStatusLabel(note: XHSAccountNote): string {
  const rawStatus = String(note.content_status || '').trim();
  if (rawStatus === 'from_detail') return '正文已补齐';
  if (rawStatus === 'missing_from_source') return '源站未返回正文';
  if (rawStatus) return rawStatus;
  if (note.detail_synced_at) return '已同步待确认';
  return '未同步详情';
}

function getAccountNoteSourceLabel(note: XHSAccountNote): string {
  if (note.identity_status === 'ambiguous') return '身份待确认';
  if (!note.feed_id) return '待主页补 ID';
  if (note.creator_synced_at && note.homepage_synced_at) return '创作中心 + 主页';
  if (note.creator_synced_at) return '创作中心已同步';
  return '主页已同步';
}

function getAccountNoteSourceTone(note: XHSAccountNote): string {
  if (note.identity_status === 'ambiguous') return 'border-rose-200 bg-rose-50 text-rose-700';
  if (!note.feed_id) return 'border-amber-200 bg-amber-50 text-amber-700';
  return 'border-indigo-200 bg-indigo-50 text-indigo-700';
}

function getAccountNoteGalleryUrls(note: XHSAccountNote): string[] {
  const rawUrls = note.cover_image_url
    ? [note.cover_image_url]
    : note.image_urls?.length
      ? note.image_urls
      : [];
  const normalized = rawUrls
    .map((url) => normalizeAccountNoteCoverUrl(url))
    .filter(Boolean);
  return Array.from(new Set(normalized));
}

function getAccountNoteIdentityLabel(note: XHSAccountNote): string {
  const source = String(note.profile_nickname || note.account_name || note.red_id || 'X').trim();
  return (source[0] || 'X').toUpperCase();
}

function formatAccountNoteMetric(value?: number | null): string {
  const normalized = Number(value ?? 0);
  if (!Number.isFinite(normalized) || normalized <= 0) return '0';
  if (normalized >= 10000) return `${(normalized / 10000).toFixed(normalized >= 100000 ? 0 : 1)}w`;
  return `${Math.round(normalized)}`;
}

function isAccountSyncRunnerEnv(env: XHSEnvironment): boolean {
  return Boolean(env.is_sync_runner) || /测试[2345]/.test(env.account_name);
}

function getEnvironmentSearchText(env: XHSEnvironment): string {
  return `${env.account_name || ''} ${env.shop_id || ''} ${env.id || ''}`.toLowerCase();
}

function getBrowserStatusLabel(status?: string): string {
  if (status === 'online') return '在线';
  if (status === 'offline') return '离线';
  if (status === 'busy') return '占用';
  if (status === 'error') return '异常';
  return '未知';
}

function getBrowserStatusTone(status?: string, active = false): string {
  if (active) {
    if (status === 'online') return 'bg-emerald-600 text-white';
    if (status === 'error') return 'bg-red-600 text-white';
    return 'bg-indigo-600 text-white';
  }
  if (status === 'online') return 'bg-emerald-50 text-emerald-700 border border-emerald-200';
  if (status === 'offline') return 'bg-slate-100 text-slate-500 border border-slate-200';
  if (status === 'busy') return 'bg-amber-50 text-amber-700 border border-amber-200';
  if (status === 'error') return 'bg-red-50 text-red-700 border border-red-200';
  return 'bg-white text-slate-500 border border-slate-200';
}

type AccountNoteDetailModalProps = {
  note: XHSAccountNote;
  onClose: () => void;
  onPreview: (payload: { url: string; title: string }) => void;
};

type AccountDetailSyncStrategyDraft = {
  syncMode: 'all' | 'unpublished_only';
  runnerIds: number[];
  totalLimit: string;
  limitPerRunner: string;
  pauseMinSeconds: string;
  pauseMaxSeconds: string;
  maxPostAgeDays: string;
};

type AccountPostSyncStrategyDraft = {
  activeRunnerId: number | null;
  runnerAssignments: Record<string, number[]>;
  selectedEnvIds: number[];
  accountSearch: string;
};

type AccountEngagementSyncStrategyDraft = {
  selectedEnvIds: number[];
  accountSearch: string;
};

function buildAccountPostRunnerAssignments(
  overview: XHSSyncRunnerBrowseOverview | null,
  runnerOptions: XHSEnvironment[],
  publishOptions: XHSEnvironment[],
): Record<string, number[]> {
  if (!overview) return {};
  const availableRunnerIds = new Set(runnerOptions.map((env) => env.id));
  const availablePublishIds = new Set(publishOptions.map((env) => env.id));
  const winnerByPublishId = new Map<number, { runnerId: number; noteCount: number }>();
  for (const runner of overview.runners) {
    if (!availableRunnerIds.has(runner.environment_id)) continue;
    for (const account of runner.assigned_accounts) {
      const publishId = Number(account.environment_id);
      if (!availablePublishIds.has(publishId)) continue;
      const noteCount = Math.max(0, Number(account.note_count) || 0);
      const current = winnerByPublishId.get(publishId);
      if (!current || noteCount > current.noteCount || (noteCount === current.noteCount && runner.environment_id < current.runnerId)) {
        winnerByPublishId.set(publishId, {
          runnerId: runner.environment_id,
          noteCount,
        });
      }
    }
  }
  const assignments: Record<string, number[]> = {};
  for (const [publishId, winner] of winnerByPublishId.entries()) {
    const runnerKey = String(winner.runnerId);
    assignments[runnerKey] = [...(assignments[runnerKey] || []), publishId];
  }
  return assignments;
}

function normalizeAccountPostRunnerAssignments(assignments: Record<string, number[]>): Record<string, number[]> {
  const winnerByPublishId = new Map<number, string>();
  for (const [runnerId, envIds] of Object.entries(assignments)) {
    const normalizedRunnerId = String(Number.parseInt(runnerId, 10) || '');
    if (!normalizedRunnerId) continue;
    for (const envId of envIds) {
      if (envId > 0) {
        winnerByPublishId.set(envId, normalizedRunnerId);
      }
    }
  }

  const normalized: Record<string, number[]> = {};
  for (const [runnerId, envIds] of Object.entries(assignments)) {
    const normalizedRunnerId = String(Number.parseInt(runnerId, 10) || '');
    if (!normalizedRunnerId) continue;
    const uniqueEnvIds: number[] = [];
    const seenEnvIds = new Set<number>();
    for (const envId of envIds) {
      if (envId <= 0 || seenEnvIds.has(envId) || winnerByPublishId.get(envId) !== normalizedRunnerId) continue;
      seenEnvIds.add(envId);
      uniqueEnvIds.push(envId);
    }
    if (uniqueEnvIds.length > 0) {
      normalized[normalizedRunnerId] = uniqueEnvIds;
    }
  }
  return normalized;
}

type AccountSyncProgressPanelKind = 'account_notes' | 'account_engagement' | 'account_note_details';

function getAccountSyncJobStatusLabel(status: XHSAccountNoteSyncJob['status']): string {
  if (status === 'queued') return '排队中';
  if (status === 'running') return '同步中';
  if (status === 'cancelling') return '中止中';
  if (status === 'succeeded') return '已完成';
  if (status === 'cancelled') return '已中止';
  return '失败';
}

function getAccountSyncJobStatusTone(status: XHSAccountNoteSyncJob['status']): string {
  if (status === 'queued') return 'border-amber-200 bg-amber-50 text-amber-700';
  if (status === 'running') return 'border-sky-200 bg-sky-50 text-sky-700';
  if (status === 'cancelling') return 'border-orange-200 bg-orange-50 text-orange-700';
  if (status === 'succeeded') return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  if (status === 'cancelled') return 'border-slate-200 bg-slate-100 text-slate-600';
  return 'border-rose-200 bg-rose-50 text-rose-700';
}

function formatAccountSyncJobTime(value?: string | null): string {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function getAccountSyncJobPercent(job: XHSAccountNoteSyncJob | null): number {
  const normalized = Number(job?.progress?.percent ?? 0);
  if (!Number.isFinite(normalized)) return 0;
  return Math.max(0, Math.min(100, Math.round(normalized)));
}

function isAccountSyncJobActive(job: XHSAccountNoteSyncJob | null): boolean {
  return !!job && ['queued', 'running', 'cancelling'].includes(job.status);
}

function AccountNoteDetailModal({ note, onClose, onPreview }: AccountNoteDetailModalProps) {
  const galleryUrls = useMemo(() => getAccountNoteGalleryUrls(note), [note]);
  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const [activeImageAspectRatio, setActiveImageAspectRatio] = useState<number | null>(null);
  const activeImageUrl = galleryUrls[activeImageIndex] || '';
  const hashtags = useMemo(() => extractHashTags(`${note.title || ''}\n${note.content || ''}`).slice(0, 8), [note.content, note.title]);

  useEffect(() => {
    setActiveImageIndex(0);
  }, [note.id, note.cover_image_url, note.image_urls]);

  useEffect(() => {
    if (activeImageIndex < galleryUrls.length) return;
    setActiveImageIndex(0);
  }, [activeImageIndex, galleryUrls.length]);

  useEffect(() => {
    setActiveImageAspectRatio(null);
  }, [activeImageUrl]);

  return (
    <div
      className="fixed inset-0 z-[70] overflow-y-auto bg-[radial-gradient(circle_at_top,rgba(15,23,42,0.48),rgba(15,23,42,0.82))] p-3 backdrop-blur-md sm:p-5"
      onClick={onClose}
    >
      <div
        className="mx-auto w-full max-w-[1320px] overflow-hidden rounded-[32px] border border-white/60 bg-[#f7f4ef] shadow-[0_36px_140px_rgba(15,23,42,0.34)] lg:w-fit lg:max-w-[calc(100vw-40px)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex min-h-[82vh] flex-col lg:h-[88vh] lg:max-h-[940px] lg:flex-row">
          <section
            className="relative min-h-[320px] overflow-hidden bg-white lg:h-full lg:shrink-0"
            style={
              activeImageAspectRatio
                ? {
                    aspectRatio: String(activeImageAspectRatio),
                    width: 'auto',
                  }
                : undefined
            }
          >
            <div className="relative flex h-full min-h-0 flex-col">
              <div className="relative min-h-0 flex-1">
                {activeImageUrl ? (
                  <button
                    type="button"
                    className="group relative grid h-full w-full place-items-center overflow-hidden bg-white"
                    onClick={() => onPreview({ url: activeImageUrl, title: note.title || note.feed_id || '待补帖子 ID' })}
                  >
                    <img
                      src={activeImageUrl}
                      alt={note.title || note.feed_id || '待补帖子 ID'}
                      className="relative z-[1] block h-full w-full object-contain object-center transition-transform duration-300 group-hover:scale-[1.01]"
                      loading="lazy"
                      referrerPolicy="no-referrer"
                      onLoad={(event) => {
                        const target = event.currentTarget;
                        if (target.naturalWidth > 0 && target.naturalHeight > 0) {
                          setActiveImageAspectRatio(target.naturalWidth / target.naturalHeight);
                        }
                      }}
                    />
                  </button>
                ) : (
                  <div className="grid h-full w-full place-items-center bg-white text-center text-slate-400">
                    <div>
                      <div className="text-sm font-semibold tracking-[0.24em] text-slate-400">NO IMAGE</div>
                      <div className="mt-2 text-xs text-slate-500">这条帖子还没有同步到图片</div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </section>

          <aside className="relative flex min-h-0 flex-col bg-white lg:w-[460px] xl:w-[500px]">
            <button
              type="button"
              className="absolute right-4 top-4 z-[3] inline-flex h-11 w-11 items-center justify-center rounded-full bg-white/92 text-lg font-semibold text-slate-500 shadow-[0_12px_28px_rgba(15,23,42,0.12)] transition-all hover:-translate-y-0.5 hover:text-slate-800"
              onClick={onClose}
              aria-label="关闭详情"
            >
              ×
            </button>
            <div className="border-b border-slate-200/80 px-5 py-5 sm:px-6">
              <div className="flex items-start gap-3">
                <div className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[linear-gradient(135deg,#ff6a7d,#ff2442)] text-sm font-bold text-white shadow-[0_14px_28px_rgba(255,36,66,0.24)]">
                  {getAccountNoteIdentityLabel(note)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className="truncate text-[15px] font-semibold text-slate-900">
                      {note.profile_nickname || note.account_name}
                    </div>
                    <span className="rounded-full bg-[#fff1f3] px-2 py-0.5 text-[10px] font-semibold text-[#ff2442]">
                      账号帖子
                    </span>
                  </div>
                  <div className="mt-1 truncate text-xs text-slate-400">{note.account_name}</div>
                </div>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
              <h3 className="text-[22px] font-semibold leading-8 text-slate-950">
                {note.title || note.feed_id}
              </h3>

              <div className="mt-4 whitespace-pre-wrap break-words text-[15px] leading-8 text-slate-700">
                {String(note.content || '').trim() || getAccountNoteContentPreview(note)}
              </div>

              {hashtags.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {hashtags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full bg-[#fff1f3] px-3 py-1 text-[12px] font-medium text-[#ff2442]"
                    >
                      #{tag}
                    </span>
                  ))}
                </div>
              )}

              <div className="mt-5 flex items-center gap-5 border-b border-slate-100 pb-5 text-slate-700">
                <div className="flex items-center gap-2">
                  <span className="text-[18px]">◉</span>
                  <span className="text-sm font-medium">{formatAccountNoteMetric(note.view_count)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[17px]">◎</span>
                  <span className="text-sm font-medium">{formatAccountNoteMetric(note.exposure_count)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[17px]">⌁</span>
                  <span className="text-sm font-medium">{Number(note.cover_click_rate || 0).toFixed(2)}%</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[18px] text-[#ff2442]">❤</span>
                  <span className="text-sm font-medium">{formatAccountNoteMetric(note.liked_count)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[18px]">◔</span>
                  <span className="text-sm font-medium">{formatAccountNoteMetric(note.comment_count)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[17px]">☆</span>
                  <span className="text-sm font-medium">{formatAccountNoteMetric(note.collected_count)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[17px]">↗</span>
                  <span className="text-sm font-medium">{formatAccountNoteMetric(note.share_count)}</span>
                </div>
              </div>

              <div className="mt-4 text-xs leading-6 text-slate-400">
                <div>{formatAccountNotePublishedAt(note.published_at)}</div>
                {note.post_url ? (
                  <a
                    href={note.post_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1 inline-block break-all text-slate-500 transition-colors hover:text-[#ff2442]"
                  >
                    查看原帖链接
                  </a>
                ) : null}
              </div>

              <section className="mt-6 rounded-[24px] border border-slate-200 bg-slate-50/90 p-4">
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">同步记录</div>
                <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                  <span className={`rounded-full border px-2.5 py-1 font-semibold ${getAccountNoteSourceTone(note)}`}>
                    {getAccountNoteSourceLabel(note)}
                  </span>
                  <span className={`rounded-full border px-2.5 py-1 font-semibold ${getAccountNoteDetailStatusTone(note)}`}>
                    {note.detail_synced_at ? `详情同步于 ${formatAccountNotePublishedAt(note.detail_synced_at)}` : '未同步详情'}
                  </span>
                  <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 font-semibold text-slate-600">
                    {getAccountNoteContentStatusLabel(note)}
                  </span>
                </div>
                {!!String(note.content_missing_reason || '').trim() && (
                  <div className="mt-3 rounded-2xl bg-white px-3 py-3 text-sm leading-6 text-slate-600">
                    {note.content_missing_reason}
                  </div>
                )}
              </section>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

const MANAGE_VIEW_ORDER: ManageView[] = [
  'auto',
  'account',
  'simple',
  'standard',
  'creative',
  'simple_note',
  'standard_note',
];
const REPORT_PAGE_LIMIT = 20;

function formatDateInputValue(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function getLatestReportEndDate(): Date {
  const latest = new Date();
  latest.setDate(latest.getDate() - 1);
  latest.setHours(0, 0, 0, 0);
  return latest;
}

function getDefaultReportDateRange(): { startDate: string; endDate: string } {
  const end = getLatestReportEndDate();
  const start = new Date(end);
  start.setDate(end.getDate() - 29);
  return {
    startDate: formatDateInputValue(start),
    endDate: formatDateInputValue(end),
  };
}

function parseDateInputValue(value: string): Date | null {
  if (!value) return null;
  const parts = value.split('-').map((part) => Number(part));
  if (parts.length !== 3 || parts.some((part) => !Number.isFinite(part))) return null;
  const [year, month, day] = parts;
  return new Date(year, month - 1, day);
}

function addMonths(base: Date, offset: number): Date {
  return new Date(base.getFullYear(), base.getMonth() + offset, 1);
}

function buildCalendarDays(monthDate: Date): Array<{ value: string; day: number; inMonth: boolean }> {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const firstDay = new Date(year, month, 1);
  const startWeekday = firstDay.getDay();
  const gridStart = new Date(year, month, 1 - startWeekday);
  return Array.from({ length: 42 }, (_, index) => {
    const current = new Date(gridStart);
    current.setDate(gridStart.getDate() + index);
    return {
      value: formatDateInputValue(current),
      day: current.getDate(),
      inMonth: current.getMonth() === month,
    };
  });
}

export default function XHSPublishManagePage() {
  const defaultReportDateRange = useMemo(() => getDefaultReportDateRange(), []);
  const latestReportEndDate = useMemo(() => getLatestReportEndDate(), []);
  const latestReportEndDateValue = useMemo(() => formatDateInputValue(latestReportEndDate), [latestReportEndDate]);
  const reportDatePickerRef = useRef<HTMLDivElement | null>(null);
  const reportAccountPickerRef = useRef<HTMLDivElement | null>(null);
  const accountEnvPickerRef = useRef<HTMLDivElement | null>(null);
  const [currentUser, setCurrentUser] = useState<{ username?: string; role?: string; roles?: string[] } | null>(null);
  const [manageView, setManageView] = useState<ManageView>('auto');
  const [reportAccountId, setReportAccountId] = useState('all');
  const [reportAccountPickerOpen, setReportAccountPickerOpen] = useState(false);
  const [reportAccountSearch, setReportAccountSearch] = useState('');
  const [reportStartDate, setReportStartDate] = useState(defaultReportDateRange.startDate);
  const [reportEndDate, setReportEndDate] = useState(defaultReportDateRange.endDate);
  const [reportDatePickerOpen, setReportDatePickerOpen] = useState(false);
  const [reportSelectingRangeEnd, setReportSelectingRangeEnd] = useState(false);
  const [reportCalendarMonth, setReportCalendarMonth] = useState(() => {
    const start = parseDateInputValue(defaultReportDateRange.startDate);
    return start ? new Date(start.getFullYear(), start.getMonth(), 1) : new Date();
  });
  const [accountEnvId, setAccountEnvId] = useState<number | 'all'>('all');
  const [accountEnvPickerOpen, setAccountEnvPickerOpen] = useState(false);
  const [accountEnvSearch, setAccountEnvSearch] = useState('');
  const [accountSyncScrapeEnvId, setAccountSyncScrapeEnvId] = useState<number | null>(null);
  const [environments, setEnvironments] = useState<XHSEnvironment[]>([]);
  const [browserStatuses, setBrowserStatuses] = useState<XHSBrowserEnvironmentStatus[]>([]);
  const [browserStatusRefreshing, setBrowserStatusRefreshing] = useState(false);
  const [envId, setEnvId] = useState<number | null>(null);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [images, setImages] = useState<{ id: string; file?: File; path?: string; name?: string }[]>([]);
  const [galleryPickerOpen, setGalleryPickerOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishMode, setPublishMode] = useState<'now' | 'scheduled'>('now');
  const [scheduledAt, setScheduledAt] = useState('');

  const [posts, setPosts] = useState<XHSPost[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(20);
  const [statusFilter, setStatusFilter] = useState('');
  const [loadingPosts, setLoadingPosts] = useState(false);
  const [syncingId, setSyncingId] = useState<number | null>(null);
  const [runningNowId, setRunningNowId] = useState<number | null>(null);
  const [cancellingId, setCancellingId] = useState<number | null>(null);

  const [editingPost, setEditingPost] = useState<XHSPost | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editScheduledAt, setEditScheduledAt] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportData, setReportData] = useState<XHSReportResponse | null>(null);
  const [reportRefreshing, setReportRefreshing] = useState(false);
  const [exportingReport, setExportingReport] = useState(false);
  const [creativeAiFilter, setCreativeAiFilter] = useState<'all' | '__missing__' | '__unset__' | 'manual' | 'text_ai' | 'image_ai' | 'all_ai'>('all');
  const [creativeReportMode, setCreativeReportMode] = useState<'rows' | 'compare'>('rows');
  const [creativeCompareMetric, setCreativeCompareMetric] = useState<CreativeCompareMetricKey>('fee');
  const [creativeCompareLoading, setCreativeCompareLoading] = useState(false);
  const [creativeCompareData, setCreativeCompareData] = useState<XHSCreativeReportCompareResponse | null>(null);
  const [creativeCompareHoveredPeriodKey, setCreativeCompareHoveredPeriodKey] = useState<string | null>(null);
  const [reportAccounts, setReportAccounts] = useState<Array<{ account_id: string; account_name: string; has_token: boolean }>>([]);
  const [reportCache, setReportCache] = useState<Record<string, XHSReportResponse>>({});
  const [creativeCompareCache, setCreativeCompareCache] = useState<Record<string, XHSCreativeReportCompareResponse>>({});
  const [accountNotesLoading, setAccountNotesLoading] = useState(false);
  const [accountNotesSyncing, setAccountNotesSyncing] = useState(false);
  const [accountEngagementSyncing, setAccountEngagementSyncing] = useState(false);
  const [accountNoteDetailsSyncing, setAccountNoteDetailsSyncing] = useState(false);
  const [accountContentTagging, setAccountContentTagging] = useState(false);
  const [accountNotesSyncJob, setAccountNotesSyncJob] = useState<XHSAccountNoteSyncJob | null>(null);
  const [accountEngagementSyncJob, setAccountEngagementSyncJob] = useState<XHSAccountNoteSyncJob | null>(null);
  const [accountNoteDetailsSyncJob, setAccountNoteDetailsSyncJob] = useState<XHSAccountNoteSyncJob | null>(null);
  const [accountSyncProgressPanel, setAccountSyncProgressPanel] = useState<AccountSyncProgressPanelKind | null>(null);
  const [accountSyncHistoryOpen, setAccountSyncHistoryOpen] = useState(false);
  const [accountSyncHistory, setAccountSyncHistory] = useState<XHSAccountSyncHistoryRun[]>([]);
  const [accountSyncHistoryLoading, setAccountSyncHistoryLoading] = useState(false);
  const [accountSyncHistoryRetryingId, setAccountSyncHistoryRetryingId] = useState<number | null>(null);
  const [accountNoteSavingId, setAccountNoteSavingId] = useState<number | null>(null);
  const [accountNoteSyncingId, setAccountNoteSyncingId] = useState<number | null>(null);
  const [accountNoteEngagementSyncingId, setAccountNoteEngagementSyncingId] = useState<number | null>(null);
  const [accountNoteSyncDialog, setAccountNoteSyncDialog] = useState<{
    noteId: number;
    noteTitle: string;
    runnerId: number | null;
  } | null>(null);
  const [accountNoteBatchUpdating, setAccountNoteBatchUpdating] = useState(false);
  const [accountBatchSelectMode, setAccountBatchSelectMode] = useState(false);
  const [openAiOriginMenuId, setOpenAiOriginMenuId] = useState<number | null>(null);
  const [accountSearch, setAccountSearch] = useState('');
  const [accountAiFilter, setAccountAiFilter] = useState<'all' | '__unset__' | 'manual' | 'text_ai' | 'image_ai' | 'all_ai'>('all');
  const [accountDetailSyncLimit, setAccountDetailSyncLimit] = useState('20');
  const [accountPostSyncStrategy, setAccountPostSyncStrategy] = useState<AccountPostSyncStrategyDraft | null>(null);
  const [accountEngagementSyncStrategy, setAccountEngagementSyncStrategy] = useState<AccountEngagementSyncStrategyDraft | null>(null);
  const [accountDetailSyncStrategy, setAccountDetailSyncStrategy] = useState<AccountDetailSyncStrategyDraft | null>(null);
  const [syncRunnerOverview, setSyncRunnerOverview] = useState<XHSSyncRunnerBrowseOverview | null>(null);
  const [syncRunnerOverviewLoading, setSyncRunnerOverviewLoading] = useState(false);
  const [activeSyncRunnerInsightId, setActiveSyncRunnerInsightId] = useState<number | null>(null);
  const [selectedAccountNoteIds, setSelectedAccountNoteIds] = useState<number[]>([]);
  const [batchAccountAiOrigin, setBatchAccountAiOrigin] = useState<'manual' | 'text_ai' | 'image_ai' | 'all_ai'>('manual');
  const [hasUnsetAccountNotes, setHasUnsetAccountNotes] = useState(false);
  const [accountNotePreview, setAccountNotePreview] = useState<{ url: string; title: string } | null>(null);
  const [activeAccountNote, setActiveAccountNote] = useState<XHSAccountNote | null>(null);
  const [isAccountNotesRendering, startAccountNotesTransition] = useTransition();
  const [accountNotesData, setAccountNotesData] = useState<{ items: XHSAccountNote[]; total: number; total_accounts: number }>({
    items: [],
    total: 0,
    total_accounts: 0,
  });
  const reportAccountOptions = useMemo(() => {
    return [...reportAccounts].sort((a, b) => {
      if (a.has_token !== b.has_token) return Number(b.has_token) - Number(a.has_token);
      return a.account_name.localeCompare(b.account_name, 'zh-Hans-CN');
    });
  }, [reportAccounts]);
  const filteredReportAccountOptions = useMemo(() => {
    const keyword = reportAccountSearch.trim().toLowerCase();
    if (!keyword) return reportAccountOptions;
    return reportAccountOptions.filter((item) => {
      const haystack = `${item.account_name} ${item.account_id}`.toLowerCase();
      return haystack.includes(keyword);
    });
  }, [reportAccountOptions, reportAccountSearch]);
  const selectedReportAccount = useMemo(
    () => reportAccountOptions.find((item) => item.account_id === reportAccountId) || null,
    [reportAccountId, reportAccountOptions],
  );
  const accountEnvOptions = useMemo(() => {
    return [...environments].sort((a, b) => a.account_name.localeCompare(b.account_name, 'zh-Hans-CN'));
  }, [environments]);
  const accountPostTargetEnvOptions = useMemo(() => {
    return accountEnvOptions.filter((env) => !isAccountSyncRunnerEnv(env));
  }, [accountEnvOptions]);
  const filteredAccountEnvOptions = useMemo(() => {
    const keyword = accountEnvSearch.trim().toLowerCase();
    if (!keyword) return accountEnvOptions;
    return accountEnvOptions.filter((item) => getEnvironmentSearchText(item).includes(keyword));
  }, [accountEnvOptions, accountEnvSearch]);
  const selectedAccountEnv = useMemo(
    () => accountEnvOptions.find((item) => item.id === accountEnvId) || null,
    [accountEnvId, accountEnvOptions],
  );
  const accountSyncRunnerOptions = useMemo(() => {
    const preferred = accountEnvOptions.filter((env) => isAccountSyncRunnerEnv(env));
    return preferred.length > 0 ? preferred : accountEnvOptions;
  }, [accountEnvOptions]);
  const browserStatusByEnvId = useMemo(() => {
    return new Map(browserStatuses.map((item) => [item.environment_id, item]));
  }, [browserStatuses]);
  const refreshBrowserStatuses = useCallback(async (refresh = false) => {
    setBrowserStatusRefreshing(true);
    try {
      const statuses = await getXhsBrowserEnvironmentStatuses({ refresh });
      setBrowserStatuses(statuses);
    } catch (err: any) {
      toast.error(`获取浏览器在线状态失败: ${err.message}`);
    } finally {
      setBrowserStatusRefreshing(false);
    }
  }, []);
  const activeSyncRunnerInsight = useMemo(
    () => syncRunnerOverview?.runners.find((runner) => runner.environment_id === activeSyncRunnerInsightId) || null,
    [activeSyncRunnerInsightId, syncRunnerOverview],
  );
  const accountPostSyncAssignedPublishCount = useMemo(() => {
    if (!accountPostSyncStrategy) return 0;
    return accountPostSyncStrategy.selectedEnvIds.length;
  }, [accountPostSyncStrategy]);
  const accountPostSyncAssignedRunnerCount = useMemo(() => {
    if (!accountPostSyncStrategy) return 0;
    const selectedSet = new Set(accountPostSyncStrategy.selectedEnvIds);
    return Object.entries(accountPostSyncStrategy.runnerAssignments)
      .filter(([, envIds]) => envIds.some((envId) => selectedSet.has(envId)))
      .length;
  }, [accountPostSyncStrategy]);
  const accountPostSyncAssignedRunnerByEnvId = useMemo(() => {
    const mapping = new Map<number, number>();
    if (!accountPostSyncStrategy) return mapping;
    for (const [runnerId, envIds] of Object.entries(accountPostSyncStrategy.runnerAssignments)) {
      const parsedRunnerId = Number.parseInt(runnerId, 10);
      if (!parsedRunnerId) continue;
      for (const envId of envIds) {
        mapping.set(envId, parsedRunnerId);
      }
    }
    return mapping;
  }, [accountPostSyncStrategy]);
  const filteredAccountPostTargetEnvOptions = useMemo(() => {
    if (!accountPostSyncStrategy) return accountPostTargetEnvOptions;
    const keyword = accountPostSyncStrategy.accountSearch.trim().toLowerCase();
    if (!keyword) return accountPostTargetEnvOptions;
    return accountPostTargetEnvOptions.filter((env) => getEnvironmentSearchText(env).includes(keyword));
  }, [accountPostSyncStrategy, accountPostTargetEnvOptions]);
  const accountEngagementSelectedCount = useMemo(
    () => new Set(accountEngagementSyncStrategy?.selectedEnvIds ?? []).size,
    [accountEngagementSyncStrategy],
  );
  const filteredAccountEngagementTargetEnvOptions = useMemo(() => {
    if (!accountEngagementSyncStrategy) return accountPostTargetEnvOptions;
    const keyword = accountEngagementSyncStrategy.accountSearch.trim().toLowerCase();
    if (!keyword) return accountPostTargetEnvOptions;
    return accountPostTargetEnvOptions.filter((env) => getEnvironmentSearchText(env).includes(keyword));
  }, [accountEngagementSyncStrategy, accountPostTargetEnvOptions]);
  const selectedAccountEngagementTargetEnvOptions = useMemo(() => {
    if (!accountEngagementSyncStrategy) return [];
    const accountById = new Map(accountPostTargetEnvOptions.map((env) => [env.id, env]));
    return Array.from(new Set(accountEngagementSyncStrategy.selectedEnvIds))
      .map((envId) => accountById.get(envId))
      .filter((env): env is XHSEnvironment => Boolean(env));
  }, [accountEngagementSyncStrategy, accountPostTargetEnvOptions]);
  const reportDateRangeInvalid = useMemo(() => {
    return !!reportStartDate && !!reportEndDate && reportStartDate > reportEndDate;
  }, [reportStartDate, reportEndDate]);
  const reportRangeLabel = useMemo(() => {
    if (!reportStartDate || !reportEndDate) return '选择日期区间';
    return `${reportStartDate} - ${reportEndDate}`;
  }, [reportStartDate, reportEndDate]);
  const reportCalendarDays = useMemo(() => buildCalendarDays(reportCalendarMonth), [reportCalendarMonth]);
  const isAdmin = currentUser?.role === 'admin' || currentUser?.roles?.includes('admin') || currentUser?.username === 'dev';
  const accountNotesSyncInProgress = isAccountSyncJobActive(accountNotesSyncJob);
  const accountEngagementSyncInProgress = isAccountSyncJobActive(accountEngagementSyncJob);
  const accountNoteDetailsSyncInProgress = isAccountSyncJobActive(accountNoteDetailsSyncJob);
  const activeAccountSyncPanelJob = useMemo(() => {
    if (accountSyncProgressPanel === 'account_notes') return accountNotesSyncJob;
    if (accountSyncProgressPanel === 'account_engagement') return accountEngagementSyncJob;
    if (accountSyncProgressPanel === 'account_note_details') return accountNoteDetailsSyncJob;
    return null;
  }, [accountEngagementSyncJob, accountNoteDetailsSyncJob, accountNotesSyncJob, accountSyncProgressPanel]);
  const tags = useMemo(() => extractHashTags(`${title}\n${content}`), [title, content]);

  const fetchPosts = useCallback(async (overrides?: { page?: number; limit?: number; status?: string }) => {
    const targetPage = overrides?.page ?? page;
    const targetLimit = overrides?.limit ?? limit;
    const targetStatus = overrides?.status ?? statusFilter;
    setLoadingPosts(true);
    try {
      const result = await getPosts({ page: targetPage, limit: targetLimit, status: targetStatus || undefined });
      setPosts(result.items);
      setTotal(result.total);
    } catch (err: any) {
      toast.error(`获取帖子列表失败: ${err.message}`);
    } finally {
      setLoadingPosts(false);
    }
  }, [page, limit, statusFilter]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem('app_current_user');
      setCurrentUser(raw ? JSON.parse(raw) : null);
    } catch {
      setCurrentUser(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const restoreSyncJobs = async () => {
      const restoreEntry = async (
        storageKey: string,
        setter: (job: XHSAccountNoteSyncJob | null) => void,
      ): Promise<boolean> => {
        const jobId = localStorage.getItem(storageKey);
        if (!jobId) return false;
        try {
          const job = await getXhsAccountNoteSyncJob(jobId);
          if (cancelled) return false;
          setter(job);
          if (!isAccountSyncJobActive(job)) {
            localStorage.removeItem(storageKey);
          }
          return isAccountSyncJobActive(job);
        } catch {
          if (!cancelled) setter(null);
          localStorage.removeItem(storageKey);
          return false;
        }
      };

      const [notesActive, engagementActive, detailsActive] = await Promise.all([
        restoreEntry(ACCOUNT_NOTES_SYNC_JOB_STORAGE_KEY, setAccountNotesSyncJob),
        restoreEntry(ACCOUNT_ENGAGEMENT_SYNC_JOB_STORAGE_KEY, setAccountEngagementSyncJob),
        restoreEntry(ACCOUNT_NOTE_DETAILS_SYNC_JOB_STORAGE_KEY, setAccountNoteDetailsSyncJob),
      ]);
      if (cancelled) return;

      const savedPanel = localStorage.getItem(ACCOUNT_SYNC_PROGRESS_PANEL_STORAGE_KEY);
      if (savedPanel === 'account_notes' && notesActive) {
        setAccountSyncProgressPanel('account_notes');
      } else if (savedPanel === 'account_engagement' && engagementActive) {
        setAccountSyncProgressPanel('account_engagement');
      } else if (savedPanel === 'account_note_details' && detailsActive) {
        setAccountSyncProgressPanel('account_note_details');
      } else {
        localStorage.removeItem(ACCOUNT_SYNC_PROGRESS_PANEL_STORAGE_KEY);
      }
    };

    restoreSyncJobs().catch(() => {
      localStorage.removeItem(ACCOUNT_NOTES_SYNC_JOB_STORAGE_KEY);
      localStorage.removeItem(ACCOUNT_ENGAGEMENT_SYNC_JOB_STORAGE_KEY);
      localStorage.removeItem(ACCOUNT_NOTE_DETAILS_SYNC_JOB_STORAGE_KEY);
      localStorage.removeItem(ACCOUNT_SYNC_PROGRESS_PANEL_STORAGE_KEY);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const activeJob = isAccountSyncJobActive(accountNotesSyncJob) ? accountNotesSyncJob : null;
    if (activeJob) {
      localStorage.setItem(ACCOUNT_NOTES_SYNC_JOB_STORAGE_KEY, activeJob.job_id);
    } else {
      localStorage.removeItem(ACCOUNT_NOTES_SYNC_JOB_STORAGE_KEY);
    }
  }, [accountNotesSyncJob]);

  useEffect(() => {
    const activeJob = isAccountSyncJobActive(accountEngagementSyncJob) ? accountEngagementSyncJob : null;
    if (activeJob) {
      localStorage.setItem(ACCOUNT_ENGAGEMENT_SYNC_JOB_STORAGE_KEY, activeJob.job_id);
    } else {
      localStorage.removeItem(ACCOUNT_ENGAGEMENT_SYNC_JOB_STORAGE_KEY);
    }
  }, [accountEngagementSyncJob]);

  useEffect(() => {
    const activeJob = isAccountSyncJobActive(accountNoteDetailsSyncJob) ? accountNoteDetailsSyncJob : null;
    if (activeJob) {
      localStorage.setItem(ACCOUNT_NOTE_DETAILS_SYNC_JOB_STORAGE_KEY, activeJob.job_id);
    } else {
      localStorage.removeItem(ACCOUNT_NOTE_DETAILS_SYNC_JOB_STORAGE_KEY);
    }
  }, [accountNoteDetailsSyncJob]);

  useEffect(() => {
    if (
      accountSyncProgressPanel === 'account_notes' && isAccountSyncJobActive(accountNotesSyncJob)
      || accountSyncProgressPanel === 'account_engagement' && isAccountSyncJobActive(accountEngagementSyncJob)
      || accountSyncProgressPanel === 'account_note_details' && isAccountSyncJobActive(accountNoteDetailsSyncJob)
    ) {
      localStorage.setItem(ACCOUNT_SYNC_PROGRESS_PANEL_STORAGE_KEY, String(accountSyncProgressPanel));
      return;
    }
    localStorage.removeItem(ACCOUNT_SYNC_PROGRESS_PANEL_STORAGE_KEY);
  }, [accountEngagementSyncJob, accountNoteDetailsSyncJob, accountNotesSyncJob, accountSyncProgressPanel]);

  useEffect(() => {
    if (!accountNotePreview && !activeAccountNote) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (accountNotePreview) {
          setAccountNotePreview(null);
          return;
        }
        setActiveAccountNote(null);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [accountNotePreview, activeAccountNote]);

  useEffect(() => {
    if (!reportDatePickerOpen) return;
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (reportDatePickerRef.current?.contains(target)) return;
      setReportDatePickerOpen(false);
      setReportSelectingRangeEnd(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [reportDatePickerOpen]);

  useEffect(() => {
    if (!reportAccountPickerOpen) return;
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (reportAccountPickerRef.current?.contains(target)) return;
      setReportAccountPickerOpen(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [reportAccountPickerOpen]);

  useEffect(() => {
    if (!accountEnvPickerOpen) return;
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (accountEnvPickerRef.current?.contains(target)) return;
      setAccountEnvPickerOpen(false);
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [accountEnvPickerOpen]);

  useEffect(() => {
    getEnvironments()
      .then((res) => {
        setEnvironments(res);
        if (res.length > 0 && !envId) setEnvId(res[0].id);
      })
      .catch(() => toast.error('获取环境列表失败'));
    refreshBrowserStatuses(false);
  }, [envId, refreshBrowserStatuses]);

  useEffect(() => {
    if (!isAdmin || accountSyncRunnerOptions.length === 0) return;
    const exists = accountSyncRunnerOptions.some((env) => env.id === accountSyncScrapeEnvId);
    if (exists) return;
    const preferred = accountSyncRunnerOptions.find((env) => Boolean(env.is_sync_runner))
      || accountSyncRunnerOptions.find((env) => env.account_name.includes('测试2'))
      || accountSyncRunnerOptions[0];
    setAccountSyncScrapeEnvId(preferred?.id ?? null);
  }, [accountSyncRunnerOptions, accountSyncScrapeEnvId, isAdmin]);

  useEffect(() => {
    fetchPosts();
  }, [fetchPosts]);

  useEffect(() => {
    if (manageView === 'auto' || manageView === 'account') return;
    getXhsReportAccounts()
      .then((res) => setReportAccounts(res))
      .catch((err: any) => toast.error(`获取报表账号失败: ${err.message}`));
  }, [manageView]);

  useEffect(() => {
    if (manageView === 'auto' || manageView === 'account') return;
    if (reportDateRangeInvalid) return;
    const reportType = getReportTypeByView(manageView);
    if (!reportType) return;
    const selectedAccountId = reportAccountId === 'all' ? undefined : reportAccountId || undefined;
    const creativeFilterKey = reportType === 'creative' ? creativeAiFilter : 'all';
    const cacheKey = `${reportType}:${selectedAccountId || 'all'}:${reportStartDate}:${reportEndDate}:${page}:${REPORT_PAGE_LIMIT}:${creativeFilterKey}`;
    const cached = reportCache[cacheKey];
    if (cached) {
      setReportData(cached);
      return;
    }
    setReportLoading(true);
    setReportData(null);
    getXhsReport(reportType, {
      account_id: selectedAccountId,
      start_date: reportStartDate,
      end_date: reportEndDate,
      page,
      limit: REPORT_PAGE_LIMIT,
      ai_origin_filter: reportType === 'creative' && creativeAiFilter !== 'all' ? creativeAiFilter : undefined,
    })
      .then((res) => {
        setReportData(res);
        setReportCache((prev) => ({ ...prev, [cacheKey]: res }));
      })
      .catch((err: any) => toast.error(`获取报表失败: ${err.message}`))
      .finally(() => setReportLoading(false));
  }, [manageView, reportAccountId, reportCache, reportStartDate, reportEndDate, page, creativeAiFilter, reportDateRangeInvalid]);

  useEffect(() => {
    if (manageView !== 'creative') {
      setCreativeReportMode('rows');
      return;
    }
  }, [manageView]);

  useEffect(() => {
    if (manageView !== 'creative' || creativeReportMode !== 'compare') return;
    if (reportDateRangeInvalid) return;
    const selectedAccountId = reportAccountId === 'all' ? undefined : reportAccountId || undefined;
    const cacheKey = `creative-compare:${selectedAccountId || 'all'}:${reportStartDate}:${reportEndDate}`;
    const cached = creativeCompareCache[cacheKey];
    if (cached) {
      setCreativeCompareData(cached);
      return;
    }
    setCreativeCompareLoading(true);
    setCreativeCompareData(null);
    getXhsCreativeReportCompare({
      account_id: selectedAccountId,
      start_date: reportStartDate,
      end_date: reportEndDate,
    })
      .then((res) => {
        setCreativeCompareData(res);
        setCreativeCompareCache((prev) => ({ ...prev, [cacheKey]: res }));
      })
      .catch((err: any) => toast.error(`获取标签对比失败: ${err.message}`))
      .finally(() => setCreativeCompareLoading(false));
  }, [manageView, creativeReportMode, reportAccountId, reportStartDate, reportEndDate, creativeCompareCache, reportDateRangeInvalid]);

  useEffect(() => {
    setPage(1);
  }, [manageView, reportAccountId, accountEnvId, accountAiFilter, creativeAiFilter, reportStartDate, reportEndDate]);

  useEffect(() => {
    if (manageView === 'auto' || manageView === 'account') {
      setReportAccountPickerOpen(false);
      setReportAccountSearch('');
    }
  }, [manageView]);

  useEffect(() => {
    if (manageView !== 'account') {
      setAccountEnvPickerOpen(false);
      setAccountEnvSearch('');
    }
  }, [manageView]);

  useEffect(() => {
    if (!accountPostSyncStrategy) return;
    const availableRunnerIds = new Set(accountSyncRunnerOptions.map((env) => env.id));
    const availablePublishEnvIds = new Set(accountPostTargetEnvOptions.map((env) => env.id));
    const nextAssignments = normalizeAccountPostRunnerAssignments(Object.fromEntries(
      Object.entries(accountPostSyncStrategy.runnerAssignments)
        .filter(([runnerId]) => availableRunnerIds.has(Number.parseInt(runnerId, 10)))
        .map(([runnerId, envIds]) => [
          runnerId,
          envIds.filter((envId) => availablePublishEnvIds.has(envId)),
        ])
        .filter(([, envIds]) => envIds.length > 0),
    ));
    const nextActiveRunnerId = accountPostSyncStrategy.activeRunnerId && availableRunnerIds.has(accountPostSyncStrategy.activeRunnerId)
      ? accountPostSyncStrategy.activeRunnerId
      : (Number.parseInt(Object.keys(nextAssignments)[0] || '', 10) || accountSyncRunnerOptions[0]?.id || null);
    const nextSelectedEnvIds = accountPostSyncStrategy.selectedEnvIds.filter((envId) => availablePublishEnvIds.has(envId));
    const changed =
      JSON.stringify(nextAssignments) !== JSON.stringify(accountPostSyncStrategy.runnerAssignments)
      || nextActiveRunnerId !== accountPostSyncStrategy.activeRunnerId
      || JSON.stringify(nextSelectedEnvIds) !== JSON.stringify(accountPostSyncStrategy.selectedEnvIds);
    if (!changed) return;
    setAccountPostSyncStrategy((current) => (
      current
        ? {
            ...current,
            runnerAssignments: nextAssignments,
            selectedEnvIds: nextSelectedEnvIds,
            activeRunnerId: nextActiveRunnerId,
          }
        : current
    ));
  }, [accountPostSyncStrategy, accountPostTargetEnvOptions, accountSyncRunnerOptions]);

  useEffect(() => {
    if (!accountDetailSyncStrategy) return;
    const availableRunnerIds = new Set(accountSyncRunnerOptions.map((env) => env.id));
    const filteredRunnerIds = accountDetailSyncStrategy.runnerIds.filter((id) => availableRunnerIds.has(id));
    if (filteredRunnerIds.length === accountDetailSyncStrategy.runnerIds.length) return;
    setAccountDetailSyncStrategy((current) => (
      current
        ? {
            ...current,
            runnerIds: filteredRunnerIds,
          }
        : current
    ));
  }, [accountDetailSyncStrategy, accountSyncRunnerOptions]);

  const fetchAccountNotes = useCallback(async (overrides?: { page?: number; limit?: number; environment_id?: number | 'all'; keyword?: string; ai_origin_type?: typeof accountAiFilter }) => {
    const targetPage = overrides?.page ?? page;
    const targetLimit = overrides?.limit ?? 20;
    const targetEnvId = overrides?.environment_id ?? accountEnvId;
    const targetKeyword = overrides?.keyword ?? accountSearch;
    const targetAiOriginType = overrides?.ai_origin_type ?? accountAiFilter;
    setAccountNotesLoading(true);
    try {
      const result = await getXhsAccountNotes({
        page: targetPage,
        limit: targetLimit,
        environment_id: targetEnvId === 'all' ? undefined : targetEnvId,
        keyword: targetKeyword.trim() || undefined,
        ai_origin_type: targetAiOriginType === 'all' ? undefined : targetAiOriginType,
        status: 'all',
      });
      await waitForPaint();
      startAccountNotesTransition(() => {
        setAccountNotesData({
          items: result.items,
          total: result.total,
          total_accounts: result.total_accounts,
        });
        setHasUnsetAccountNotes(result.items.some((item) => !String(item.ai_origin_type || '').trim()));
        setAccountNotesLoading(false);
      });
    } catch (err: any) {
      toast.error(`获取账号帖子失败: ${err.message}`);
      setAccountNotesLoading(false);
    }
  }, [page, accountEnvId, accountSearch, accountAiFilter]);

  const loadAccountSyncHistory = useCallback(async () => {
    setAccountSyncHistoryLoading(true);
    try {
      setAccountSyncHistory(await getXhsAccountNoteSyncHistory(30));
    } catch (err: any) {
      toast.error(`获取同步历史失败: ${err.message}`);
    } finally {
      setAccountSyncHistoryLoading(false);
    }
  }, []);

  const handleRetryFailedAccountSyncRun = useCallback(async (runId: number) => {
    setAccountSyncHistoryRetryingId(runId);
    try {
      const job = await retryFailedXhsAccountNoteSyncHistory(runId);
      if (job.job_type === 'account_notes_sync') {
        setAccountNotesSyncJob(job);
        setAccountSyncProgressPanel('account_notes');
      } else if (job.job_type === 'account_note_engagement_sync') {
        setAccountEngagementSyncJob(job);
        setAccountSyncProgressPanel('account_engagement');
      } else {
        setAccountNoteDetailsSyncJob(job);
        setAccountSyncProgressPanel('account_note_details');
      }
      toast.success('失败账号已重新下发，同步历史会持续更新结果');
      await loadAccountSyncHistory();
    } catch (err: any) {
      toast.error(`重跑失败账号失败: ${err.message}`);
    } finally {
      setAccountSyncHistoryRetryingId(null);
    }
  }, [loadAccountSyncHistory]);

  useEffect(() => {
    if (accountSyncHistoryOpen) loadAccountSyncHistory();
  }, [accountSyncHistoryOpen, loadAccountSyncHistory]);

  useEffect(() => {
    if (manageView !== 'account') return;
    fetchAccountNotes({ page, limit: 20, environment_id: accountEnvId, keyword: accountSearch, ai_origin_type: accountAiFilter });
  }, [manageView, page, accountEnvId, accountSearch, accountAiFilter, fetchAccountNotes]);

  useEffect(() => {
    setSelectedAccountNoteIds([]);
    setAccountBatchSelectMode(false);
  }, [manageView, page, accountEnvId, accountSearch, accountAiFilter]);

  useEffect(() => {
    setHasUnsetAccountNotes(accountNotesData.items.some((item) => !String(item.ai_origin_type || '').trim()));
  }, [accountNotesData.items]);

  useEffect(() => {
    if (openAiOriginMenuId === null) return;
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('[data-ai-origin-menu-root="true"]')) return;
      setOpenAiOriginMenuId(null);
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [openAiOriginMenuId]);

  const handleRefreshReport = useCallback(async () => {
    if (manageView === 'auto' || manageView === 'account') return;
    if (reportDateRangeInvalid) {
      toast.error('结束日期不能早于开始日期');
      return;
    }
    const reportType = getReportTypeByView(manageView);
    if (!reportType) return;
    const selectedAccountId = reportAccountId === 'all' ? undefined : reportAccountId || undefined;
    const selectedAiOriginFilter = reportType === 'creative' && creativeAiFilter !== 'all' ? creativeAiFilter : undefined;
    setReportRefreshing(true);
    try {
      const r = await refreshXhsReportCache(reportType, {
        account_id: selectedAccountId,
        start_date: reportStartDate,
        end_date: reportEndDate,
      });
      toast.success(`更新完成：${r.updated_accounts}个账号，${r.updated_rows}条记录`);
      const latest = await getXhsReport(reportType, {
        account_id: selectedAccountId,
        start_date: reportStartDate,
        end_date: reportEndDate,
        page,
        limit: REPORT_PAGE_LIMIT,
        ai_origin_filter: selectedAiOriginFilter,
      });
      setReportData(latest);
      const cacheKey = `${reportType}:${selectedAccountId || 'all'}:${reportStartDate}:${reportEndDate}:${page}:${REPORT_PAGE_LIMIT}:${reportType === 'creative' ? creativeAiFilter : 'all'}`;
      setReportCache((prev) => ({ ...prev, [cacheKey]: latest }));
      if (reportType === 'creative') {
        const compareKey = `creative-compare:${selectedAccountId || 'all'}:${reportStartDate}:${reportEndDate}`;
        setCreativeCompareCache((prev) => {
          const next = { ...prev };
          delete next[compareKey];
          return next;
        });
        if (creativeReportMode === 'compare') {
          const compare = await getXhsCreativeReportCompare({
            account_id: selectedAccountId,
            start_date: reportStartDate,
            end_date: reportEndDate,
          });
          setCreativeCompareData(compare);
          setCreativeCompareCache((prev) => ({ ...prev, [compareKey]: compare }));
        }
      }
    } catch (err: any) {
      toast.error(`更新失败: ${err.message}`);
    } finally {
      setReportRefreshing(false);
    }
  }, [manageView, reportAccountId, reportStartDate, reportEndDate, page, creativeAiFilter, creativeReportMode, reportDateRangeInvalid]);

  const handlePickReportDate = useCallback((value: string) => {
    if (value > latestReportEndDateValue) return;
    if (!reportSelectingRangeEnd) {
      setReportStartDate(value);
      setReportEndDate(value);
      setReportSelectingRangeEnd(true);
      return;
    }
    if (value < reportStartDate) {
      setReportStartDate(value);
      setReportEndDate(reportStartDate);
    } else {
      setReportEndDate(value);
    }
    setReportSelectingRangeEnd(false);
    setReportDatePickerOpen(false);
  }, [latestReportEndDateValue, reportSelectingRangeEnd, reportStartDate]);

  const handleExportReport = useCallback(async () => {
    if (manageView === 'auto' || manageView === 'account') return;
    if (reportDateRangeInvalid) {
      toast.error('结束日期不能早于开始日期');
      return;
    }
    const reportType = getReportTypeByView(manageView);
    if (!reportType) return;
    const selectedAccountId = reportAccountId === 'all' ? undefined : reportAccountId || undefined;
    const selectedAiOriginFilter = reportType === 'creative' && creativeAiFilter !== 'all' ? creativeAiFilter : undefined;
    setExportingReport(true);
    try {
      const blob = await exportXhsReport(reportType, {
        account_id: selectedAccountId,
        start_date: reportStartDate,
        end_date: reportEndDate,
        ai_origin_filter: selectedAiOriginFilter,
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `xhs_${reportType}_${selectedAccountId || 'all'}_${reportStartDate}_${reportEndDate}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      toast.error(`导出失败: ${err.message}`);
    } finally {
      setExportingReport(false);
    }
  }, [manageView, reportAccountId, reportStartDate, reportEndDate, creativeAiFilter, reportDateRangeInvalid]);

  const handleSyncAccountNotes = useCallback(async (strategy: AccountPostSyncStrategyDraft) => {
    const selectedEnvIds = Array.from(new Set(strategy.selectedEnvIds.filter((envId) => envId > 0)));
    if (selectedEnvIds.length === 0) {
      toast.error('请至少勾选一个本轮要同步的发布账号');
      return;
    }
    const selectedEnvIdSet = new Set(selectedEnvIds);
    const normalizedAssignments = normalizeAccountPostRunnerAssignments(Object.fromEntries(
      Object.entries(strategy.runnerAssignments)
        .map(([runnerId, envIds]) => [
          runnerId,
          Array.from(new Set(envIds.filter((envId) => envId > 0 && selectedEnvIdSet.has(envId)))),
        ])
        .filter(([, envIds]) => envIds.length > 0),
    ));
    const normalizedRunnerIds = Object.keys(normalizedAssignments).map((runnerId) => Number.parseInt(runnerId, 10)).filter((id) => id > 0);
    const assignedPublishEnvIds = Object.values(normalizedAssignments).flat();
    const missingAssignedEnvIds = selectedEnvIds.filter((envId) => !assignedPublishEnvIds.includes(envId));
    if (missingAssignedEnvIds.length > 0) {
      toast.error('有勾选的发布账号还没分配测试账号，请先分配后再同步');
      return;
    }
    if (isAdmin && normalizedRunnerIds.length === 0) {
      toast.error('请先给测试账号分配发布账号');
      return;
    }
    setAccountNotesSyncing(true);
    try {
      const job = await syncXhsAccountNotes({
        environment_id: undefined,
        scrape_environment_id: normalizedRunnerIds.length === 1 ? normalizedRunnerIds[0] : undefined,
        scrape_environment_ids: normalizedRunnerIds.length > 1 ? normalizedRunnerIds.join(',') : undefined,
        sync_account_limit: assignedPublishEnvIds.length || undefined,
        runner_account_assignments: JSON.stringify(normalizedAssignments),
      });
      setAccountNotesSyncJob(job);
      setAccountSyncProgressPanel('account_notes');
      setAccountPostSyncStrategy(null);
      toast.success(`账号帖子同步任务已开始：${normalizedRunnerIds.length} 个测试账号，${selectedEnvIds.length} 个发布账号已下发`);
    } catch (err: any) {
      toast.error(`同步失败: ${err.message}`);
    } finally {
      setAccountNotesSyncing(false);
    }
  }, [isAdmin]);

  const handleSyncAccountEngagements = useCallback(async (strategy: AccountEngagementSyncStrategyDraft) => {
    const selectedEnvIds = Array.from(new Set(strategy.selectedEnvIds.filter((envId) => envId > 0)));
    if (selectedEnvIds.length === 0) {
      toast.error('请至少勾选一个本轮要同步互动的发布账号');
      return;
    }
    setAccountEngagementSyncing(true);
    try {
      const job = await syncXhsAccountNoteEngagements({
        environment_id: undefined,
        target_environment_ids: selectedEnvIds.join(','),
        sync_account_limit: selectedEnvIds.length || undefined,
      });
      setAccountEngagementSyncJob(job);
      setAccountSyncProgressPanel('account_engagement');
      setAccountEngagementSyncStrategy(null);
      toast.success(`创作者中心主同步已开始：${selectedEnvIds.length} 个发布账号已下发`);
    } catch (err: any) {
      toast.error(`同步失败: ${err.message}`);
    } finally {
      setAccountEngagementSyncing(false);
    }
  }, []);

  const handleSyncAccountNoteDetails = useCallback(async (strategy: AccountDetailSyncStrategyDraft) => {
    const normalizedRunnerIds = Array.from(new Set(strategy.runnerIds.filter((id) => id > 0)));
    if (isAdmin && normalizedRunnerIds.length === 0) {
      toast.error('请至少选择一个同步环境');
      return;
    }
    const normalizedLimit = Math.max(1, Math.min(1000, Number.parseInt(strategy.totalLimit, 10) || 20));
    const normalizedLimitPerRunner = Math.max(1, Math.min(60, Number.parseInt(strategy.limitPerRunner, 10) || 10));
    const normalizedPauseMin = Math.max(0, Math.min(900, Number.parseFloat(strategy.pauseMinSeconds) || 0));
    const normalizedPauseMax = Math.max(normalizedPauseMin, Math.min(900, Number.parseFloat(strategy.pauseMaxSeconds) || normalizedPauseMin));
    const normalizedMaxPostAgeDays = (() => {
      const parsed = Number.parseInt(strategy.maxPostAgeDays, 10);
      if (!Number.isFinite(parsed) || parsed <= 0) return 0;
      return Math.min(parsed, 3650);
    })();
    setAccountNoteDetailsSyncing(true);
    try {
      const job = await syncXhsAccountNoteDetails({
        environment_id: accountEnvId === 'all' ? undefined : accountEnvId,
        scrape_environment_id: normalizedRunnerIds.length === 1 ? normalizedRunnerIds[0] : undefined,
        scrape_environment_ids: normalizedRunnerIds.length > 1 ? normalizedRunnerIds.join(',') : undefined,
        sync_mode: strategy.syncMode,
        sync_limit: normalizedLimit,
        sync_limit_per_runner: normalizedLimitPerRunner,
        pause_seconds_min: normalizedPauseMin,
        pause_seconds_max: normalizedPauseMax,
        max_post_age_days: normalizedMaxPostAgeDays,
      });
      setAccountNoteDetailsSyncJob(job);
      setAccountSyncProgressPanel('account_note_details');
      setAccountDetailSyncLimit(String(normalizedLimit));
      setAccountDetailSyncStrategy(null);
      toast.success(
        strategy.syncMode === 'all'
          ? `全量账号数据同步任务已开始：${normalizedRunnerIds.length} 个环境轮换，总计最多同步 ${normalizedLimit} 条`
          : `未同步账号数据任务已开始：${normalizedRunnerIds.length} 个环境轮换，总计最多同步 ${normalizedLimit} 条`,
      );
    } catch (err: any) {
      toast.error(`同步失败: ${err.message}`);
    } finally {
      setAccountNoteDetailsSyncing(false);
    }
  }, [accountEnvId, isAdmin]);

  const handleCancelAccountSyncJob = useCallback(async () => {
    if (!activeAccountSyncPanelJob || !['queued', 'running'].includes(activeAccountSyncPanelJob.status)) return;
    try {
      const job = await cancelXhsAccountNoteSyncJob(activeAccountSyncPanelJob.job_id);
      if (accountSyncProgressPanel === 'account_notes') {
        setAccountNotesSyncJob(job);
      } else if (accountSyncProgressPanel === 'account_engagement') {
        setAccountEngagementSyncJob(job);
      } else if (accountSyncProgressPanel === 'account_note_details') {
        setAccountNoteDetailsSyncJob(job);
      }
      toast.success(job.status === 'cancelled' ? '同步任务已中止' : '已发送中止请求，已完成的数据会保留');
    } catch (err: any) {
      toast.error(`中止同步失败: ${err.message}`);
    }
  }, [accountSyncProgressPanel, activeAccountSyncPanelJob]);

  const openAccountPostSyncStrategyModal = useCallback(() => {
    refreshBrowserStatuses(true);
    const defaultAssignments = buildAccountPostRunnerAssignments(syncRunnerOverview, accountSyncRunnerOptions, accountPostTargetEnvOptions);
    const fallbackActiveRunnerId = accountSyncScrapeEnvId && accountSyncRunnerOptions.some((env) => env.id === accountSyncScrapeEnvId)
      ? accountSyncScrapeEnvId
      : accountSyncRunnerOptions[0]?.id ?? null;
    const defaultActiveRunnerId = Number.parseInt(Object.keys(defaultAssignments)[0] || '', 10) || fallbackActiveRunnerId;
    const defaultSelectedEnvIds =
      accountEnvId !== 'all' && accountPostTargetEnvOptions.some((env) => env.id === accountEnvId)
        ? [accountEnvId]
        : [];
    setAccountPostSyncStrategy({
      activeRunnerId: defaultActiveRunnerId,
      runnerAssignments: defaultAssignments,
      selectedEnvIds: defaultSelectedEnvIds,
      accountSearch: '',
    });
    setActiveSyncRunnerInsightId(defaultActiveRunnerId);
  }, [accountEnvId, accountPostTargetEnvOptions, accountSyncRunnerOptions, accountSyncScrapeEnvId, refreshBrowserStatuses, syncRunnerOverview]);

  const openAccountEngagementSyncStrategyModal = useCallback(() => {
    const normalizedKeyword = accountSearch.trim();
    setAccountEngagementSyncStrategy({
      selectedEnvIds: [],
      accountSearch: normalizedKeyword,
    });
  }, [accountSearch]);

  const openAccountDetailSyncStrategyModal = useCallback((syncMode: 'all' | 'unpublished_only') => {
    refreshBrowserStatuses(true);
    const defaultRunnerIds = (() => {
      if (accountSyncScrapeEnvId && accountSyncRunnerOptions.some((env) => env.id === accountSyncScrapeEnvId)) {
        return [accountSyncScrapeEnvId];
      }
      return accountSyncRunnerOptions.slice(0, 2).map((env) => env.id);
    })();
    setAccountDetailSyncStrategy({
      syncMode,
      runnerIds: defaultRunnerIds,
      totalLimit: accountDetailSyncLimit || '20',
      limitPerRunner: '10',
      pauseMinSeconds: '45',
      pauseMaxSeconds: '90',
      maxPostAgeDays: '30',
    });
    setActiveSyncRunnerInsightId(defaultRunnerIds[0] ?? null);
  }, [accountDetailSyncLimit, accountSyncRunnerOptions, accountSyncScrapeEnvId, refreshBrowserStatuses]);

  const fetchSyncRunnerOverview = useCallback(async () => {
    if (!isAdmin) return;
    setSyncRunnerOverviewLoading(true);
    try {
      const result = await getXhsSyncRunnerBrowseOverview({ days: 7, limit: 80 });
      setSyncRunnerOverview(result);
      setActiveSyncRunnerInsightId((current) => current ?? result.runners[0]?.environment_id ?? null);
    } catch (err: any) {
      toast.error(`获取测试账号分配情况失败: ${err.message}`);
    } finally {
      setSyncRunnerOverviewLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    if (!isAdmin) return;
    if (!accountPostSyncStrategy && !accountDetailSyncStrategy) return;
    fetchSyncRunnerOverview();
  }, [accountDetailSyncStrategy, accountPostSyncStrategy, fetchSyncRunnerOverview, isAdmin]);

  useEffect(() => {
    if (!accountPostSyncStrategy || !syncRunnerOverview) return;
    const hasManualAssignments = Object.values(accountPostSyncStrategy.runnerAssignments).some((envIds) => envIds.length > 0);
    if (hasManualAssignments) return;
    const hydratedAssignments = buildAccountPostRunnerAssignments(syncRunnerOverview, accountSyncRunnerOptions, accountPostTargetEnvOptions);
    if (Object.keys(hydratedAssignments).length === 0) return;
    setAccountPostSyncStrategy((current) => {
      if (!current) return current;
      const nextActiveRunnerId = current.activeRunnerId || Number.parseInt(Object.keys(hydratedAssignments)[0] || '', 10) || null;
      return {
        ...current,
        runnerAssignments: hydratedAssignments,
        activeRunnerId: nextActiveRunnerId,
      };
    });
  }, [accountPostSyncStrategy, accountPostTargetEnvOptions, accountSyncRunnerOptions, syncRunnerOverview]);

  const handleUpdateAccountNoteAiOrigin = useCallback(async (
    noteId: number,
    aiOrigin: '' | 'manual' | 'text_ai' | 'image_ai' | 'all_ai',
  ) => {
    setAccountNoteSavingId(noteId);
    try {
      const updated = await updateXhsAccountNote(noteId, { ai_origin_type: aiOrigin || null });
      setAccountNotesData((prev) => ({
        ...prev,
        items: prev.items.map((item) => (item.id === noteId ? updated : item)),
      }));
      setOpenAiOriginMenuId(null);
      toast.success('标记已更新');
    } catch (err: any) {
      toast.error(`更新标记失败: ${err.message}`);
    } finally {
      setAccountNoteSavingId(null);
    }
  }, []);

  const handleBatchUpdateAccountNoteAiOrigin = useCallback(async () => {
    if (selectedAccountNoteIds.length === 0) {
      toast.error('请先勾选至少一条帖子');
      return;
    }
    setAccountNoteBatchUpdating(true);
    try {
      const result = await batchUpdateXhsAccountNotes({
        note_ids: selectedAccountNoteIds,
        ai_origin_type: batchAccountAiOrigin,
      });
      setAccountNotesData((prev) => ({
        ...prev,
        items: prev.items.map((item) => (
          result.note_ids.includes(item.id)
            ? { ...item, ai_origin_type: batchAccountAiOrigin }
            : item
        )),
      }));
      setSelectedAccountNoteIds([]);
      setAccountBatchSelectMode(false);
      setOpenAiOriginMenuId(null);
      toast.success(`已批量更新 ${result.updated_count} 条`);
    } catch (err: any) {
      toast.error(`批量更新失败: ${err.message}`);
    } finally {
      setAccountNoteBatchUpdating(false);
    }
  }, [batchAccountAiOrigin, selectedAccountNoteIds]);

  const handleTagAccountNoteContent = useCallback(async () => {
    setAccountContentTagging(true);
    try {
      const result = await tagXhsAccountNoteContent({
        environment_id: accountEnvId === 'all' ? undefined : accountEnvId,
        keyword: accountSearch.trim() || undefined,
        ai_origin_type: accountAiFilter === 'all' ? undefined : accountAiFilter,
        status: 'all',
        concurrency: 20,
      });
      await fetchAccountNotes({ page, limit: 20, environment_id: accountEnvId, keyword: accountSearch, ai_origin_type: accountAiFilter });
      const failedText = result.failed_count > 0 ? `，失败 ${result.failed_count} 条` : '';
      toast.success(`内容标签已更新 ${result.tagged_count}/${result.matched_count} 条${failedText}`);
    } catch (err: any) {
      toast.error(`内容打标签失败: ${err.message}`);
    } finally {
      setAccountContentTagging(false);
    }
  }, [accountAiFilter, accountEnvId, accountSearch, fetchAccountNotes, page]);

  const handleSyncAccountNoteStats = useCallback(async (noteId: number, scrapeEnvironmentId?: number | null) => {
    setAccountNoteSyncingId(noteId);
    try {
      const updated = await syncXhsAccountNoteStats(noteId, {
        scrape_environment_id: scrapeEnvironmentId || undefined,
      });
      setAccountNotesData((prev) => ({
        ...prev,
        items: prev.items.map((item) => (
          item.id === noteId
            ? {
                ...item,
                ...updated,
                today_browse_count: (item.today_browse_count ?? 0) + 1,
              }
            : item
        )),
      }));
      toast.success('帖子详情已更新');
    } catch (err: any) {
      toast.error(`帖子详情同步失败: ${err.message}`);
    } finally {
      setAccountNoteSyncingId(null);
    }
  }, []);

  const handleSyncAccountNoteEngagementStats = useCallback(async (noteId: number) => {
    setAccountNoteEngagementSyncingId(noteId);
    try {
      const updated = await syncXhsAccountNoteEngagementStats(noteId);
      setAccountNotesData((prev) => ({
        ...prev,
        items: prev.items.map((item) => (
          item.id === noteId
            ? {
                ...item,
                ...updated,
              }
            : item
        )),
      }));
      setActiveAccountNote((prev) => (
        prev && prev.id === noteId
          ? {
              ...prev,
              ...updated,
            }
          : prev
      ));
      toast.success('互动数据已更新');
    } catch (err: any) {
      toast.error(`互动数据同步失败: ${err.message}`);
    } finally {
      setAccountNoteEngagementSyncingId(null);
    }
  }, []);

  const openAccountNoteSyncDialog = useCallback((note: XHSAccountNote) => {
    if (!note.feed_id) {
      toast.error('该帖子尚未由主页同步补齐帖子 ID');
      return;
    }
    if (accountSyncRunnerOptions.length === 0) {
      toast.error('请先配置至少一个测试账号');
      return;
    }
    const preferredRunnerId =
      (accountSyncScrapeEnvId && accountSyncRunnerOptions.some((env) => env.id === accountSyncScrapeEnvId) ? accountSyncScrapeEnvId : null)
      ?? accountSyncRunnerOptions.find((env) => Boolean(env.is_sync_runner))?.id
      ?? accountSyncRunnerOptions[0]?.id
      ?? null;
    setAccountNoteSyncDialog({
      noteId: note.id,
      noteTitle: note.title || note.feed_id || '待补帖子 ID',
      runnerId: preferredRunnerId,
    });
  }, [accountSyncRunnerOptions, accountSyncScrapeEnvId]);

  const handleConfirmAccountNoteSync = useCallback(async () => {
    if (!accountNoteSyncDialog?.noteId) return;
    if (!accountNoteSyncDialog.runnerId) {
      toast.error('请先选择一个测试账号');
      return;
    }
    const runnerId = accountNoteSyncDialog.runnerId;
    setAccountNoteSyncDialog(null);
    await handleSyncAccountNoteStats(accountNoteSyncDialog.noteId, runnerId);
  }, [accountNoteSyncDialog, handleSyncAccountNoteStats]);

  const handleOpenAccountNoteLink = useCallback((note: XHSAccountNote) => {
    if (!note.post_url) return;
    window.open(note.post_url, '_blank', 'noopener,noreferrer');
    recordXhsAccountNoteBrowse(note.id, 'link_click')
      .then((result) => {
        setAccountNotesData((prev) => ({
          ...prev,
          items: prev.items.map((item) => (
            item.id === note.id
              ? {
                  ...item,
                  assigned_runner_environment_id: result.runner_environment_id ?? item.assigned_runner_environment_id,
                  assigned_runner_account_name: result.runner_account_name ?? item.assigned_runner_account_name,
                  today_browse_count: (item.today_browse_count ?? 0) + 1,
                }
              : item
          )),
        }));
      })
      .catch(() => {
        // Keep link opening non-blocking even if browse logging fails.
      });
  }, []);

  useEffect(() => {
    const activeJob = isAccountSyncJobActive(accountNotesSyncJob) ? accountNotesSyncJob : null;
    if (!activeJob) return;
    const jobId = activeJob.job_id;
    const timer = window.setInterval(async () => {
      try {
        const job = await getXhsAccountNoteSyncJob(jobId);
        setAccountNotesSyncJob(job);
        if (job.status === 'succeeded') {
          window.clearInterval(timer);
          const result = job.result as { synced_accounts?: number; updated_notes?: number; deferred_homepage_notes?: number } | null;
          toast.success(`主页补充完成：账号${result?.synced_accounts ?? 0}个，补齐${result?.updated_notes ?? 0}条，待创作者中心建档${result?.deferred_homepage_notes ?? 0}条`);
          await fetchAccountNotes({ page: 1, limit: 20, environment_id: accountEnvId, keyword: accountSearch, ai_origin_type: accountAiFilter });
          await loadAccountSyncHistory();
          setPage(1);
        } else if (job.status === 'failed') {
          window.clearInterval(timer);
          toast.error(`同步失败: ${job.error || job.message || '未知错误'}`);
          await loadAccountSyncHistory();
        } else if (job.status === 'cancelled') {
          window.clearInterval(timer);
          const result = job.result as { synced_accounts?: number; updated_notes?: number; deferred_homepage_notes?: number } | null;
          toast.success(`主页补充已中止：账号${result?.synced_accounts ?? 0}个，已补齐${result?.updated_notes ?? 0}条，待创作者中心建档${result?.deferred_homepage_notes ?? 0}条`);
          await fetchAccountNotes({ page: 1, limit: 20, environment_id: accountEnvId, keyword: accountSearch, ai_origin_type: accountAiFilter });
          await loadAccountSyncHistory();
          setPage(1);
        }
      } catch (err: any) {
        window.clearInterval(timer);
        toast.error(`获取同步状态失败: ${err.message}`);
        setAccountNotesSyncJob(null);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [accountAiFilter, accountEnvId, accountSearch, accountNotesSyncJob, fetchAccountNotes, loadAccountSyncHistory]);

  useEffect(() => {
    const activeJob = isAccountSyncJobActive(accountEngagementSyncJob) ? accountEngagementSyncJob : null;
    if (!activeJob) return;
    const jobId = activeJob.job_id;
    const timer = window.setInterval(async () => {
      try {
        const job = await getXhsAccountNoteSyncJob(jobId);
        setAccountEngagementSyncJob(job);
        if (job.status === 'succeeded') {
          window.clearInterval(timer);
          const result = job.result as { synced_accounts?: number; created_notes?: number; updated_notes?: number; metric_synced_notes?: number } | null;
          toast.success(`创作者中心主同步完成：账号${result?.synced_accounts ?? 0}个，新增主记录${result?.created_notes ?? 0}条，更新${result?.updated_notes ?? 0}条`);
          await fetchAccountNotes({ page: 1, limit: 20, environment_id: accountEnvId, keyword: accountSearch, ai_origin_type: accountAiFilter });
          await loadAccountSyncHistory();
          setPage(1);
        } else if (job.status === 'failed') {
          window.clearInterval(timer);
          toast.error(`创作者中心主同步失败: ${job.error || job.message || '未知错误'}`);
          await loadAccountSyncHistory();
        } else if (job.status === 'cancelled') {
          window.clearInterval(timer);
          const result = job.result as { synced_accounts?: number; metric_synced_notes?: number } | null;
          toast.success(`创作者中心主同步已中止：账号${result?.synced_accounts ?? 0}个，已处理${result?.metric_synced_notes ?? 0}条`);
          await fetchAccountNotes({ page: 1, limit: 20, environment_id: accountEnvId, keyword: accountSearch, ai_origin_type: accountAiFilter });
          await loadAccountSyncHistory();
          setPage(1);
        }
      } catch (err: any) {
        window.clearInterval(timer);
        toast.error(`获取创作者中心主同步状态失败: ${err.message}`);
        setAccountEngagementSyncJob(null);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [accountAiFilter, accountEngagementSyncJob, accountEnvId, accountSearch, fetchAccountNotes, loadAccountSyncHistory]);

  useEffect(() => {
    const activeJob = isAccountSyncJobActive(accountNoteDetailsSyncJob) ? accountNoteDetailsSyncJob : null;
    if (!activeJob) return;
    const jobId = activeJob.job_id;
    const timer = window.setInterval(async () => {
      try {
        const job = await getXhsAccountNoteSyncJob(jobId);
        setAccountNoteDetailsSyncJob(job);
        if (job.status === 'succeeded') {
          window.clearInterval(timer);
          const result = job.result as { total_notes?: number; matched_notes?: number; synced_notes?: number; failed_notes?: number } | null;
          const matchedNotes = result?.matched_notes ?? result?.total_notes ?? 0;
          toast.success(`同步完成：命中${matchedNotes}条，实际执行${result?.total_notes ?? 0}条，成功${result?.synced_notes ?? 0}条，失败${result?.failed_notes ?? 0}条`);
          await fetchAccountNotes({ page, limit: 20, environment_id: accountEnvId, keyword: accountSearch, ai_origin_type: accountAiFilter });
          await loadAccountSyncHistory();
        } else if (job.status === 'failed') {
          window.clearInterval(timer);
          toast.error(`同步失败: ${job.error || job.message || '未知错误'}`);
          await loadAccountSyncHistory();
        } else if (job.status === 'cancelled') {
          window.clearInterval(timer);
          const result = job.result as { total_notes?: number; matched_notes?: number; synced_notes?: number; failed_notes?: number } | null;
          const matchedNotes = result?.matched_notes ?? result?.total_notes ?? 0;
          toast.success(`同步已中止：命中${matchedNotes}条，已完成${result?.synced_notes ?? 0}条，失败${result?.failed_notes ?? 0}条`);
          await fetchAccountNotes({ page, limit: 20, environment_id: accountEnvId, keyword: accountSearch, ai_origin_type: accountAiFilter });
          await loadAccountSyncHistory();
        }
      } catch (err: any) {
        window.clearInterval(timer);
        toast.error(`获取同步状态失败: ${err.message}`);
        setAccountNoteDetailsSyncJob(null);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [accountAiFilter, accountEnvId, accountSearch, accountNoteDetailsSyncJob, fetchAccountNotes, loadAccountSyncHistory, page]);

  const currentPageAccountNoteIds = useMemo(
    () => accountNotesData.items.map((item) => item.id),
    [accountNotesData.items],
  );

  const allCurrentPageAccountNotesSelected = useMemo(
    () => currentPageAccountNoteIds.length > 0 && currentPageAccountNoteIds.every((id) => selectedAccountNoteIds.includes(id)),
    [currentPageAccountNoteIds, selectedAccountNoteIds],
  );

  const selectedAccountNoteCount = selectedAccountNoteIds.length;
  const toggleAccountNoteSelection = useCallback((noteId: number) => {
    setSelectedAccountNoteIds((prev) => (
      prev.includes(noteId)
        ? prev.filter((id) => id !== noteId)
        : Array.from(new Set([...prev, noteId]))
    ));
  }, []);

  useEffect(() => {
    const hasPublishing = posts.some((post) => post.status === 'publishing');
    if (!hasPublishing) return;

    const timer = window.setInterval(() => {
      fetchPosts();
    }, 5000);

    return () => window.clearInterval(timer);
  }, [posts, fetchPosts]);

  const handleImageUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const selectedFiles = Array.from(files);
    if (selectedFiles.length === 0) return;

    const pendingItems = selectedFiles.map((file) => ({
      id: createImageClientId(),
      file,
      name: file.name,
    }));

    setImages(prev => [...prev, ...pendingItems]);
    try {
      const results = await uploadImages(selectedFiles);
      setImages((prev) => {
        const pathById = new Map<string, string>();
        pendingItems.forEach((item, index) => {
          const uploaded = results[index];
          if (uploaded?.file_path) {
            pathById.set(item.id, uploaded.file_path);
          }
        });

        return prev.map((img) => {
          const nextPath = pathById.get(img.id);
          if (!nextPath) return img;
          return { ...img, path: nextPath };
        });
      });
    } catch (err: any) {
      toast.error(`图片上传失败: ${err.message}`);
      const pendingIds = new Set(pendingItems.map((item) => item.id));
      setImages(prev => prev.filter(img => !pendingIds.has(img.id)));
    } finally {
      e.target.value = '';
    }
  }, []);

  const handleGalleryMultiSelect = useCallback((selected: GalleryPickerImage[]) => {
    if (!selected || selected.length === 0) return;
    setImages(prev => {
      const existing = new Set(prev.map(i => i.path).filter(Boolean) as string[]);
      const toAdd = selected
        .filter((img) => !existing.has(img.url))
        .map((img) => ({ id: createImageClientId(), path: img.url, name: img.name || '图库图片' }));
      if (toAdd.length === 0) {
        toast.info('所选图库图片已添加');
        return prev;
      }
      return [...prev, ...toAdd];
    });
    setGalleryPickerOpen(false);
  }, []);

  const removeImage = useCallback((index: number) => {
    setImages(prev => prev.filter((_, i) => i !== index));
  }, []);

  const applyScheduleMinutes = useCallback((minutes: number) => {
    const target = new Date(Date.now() + minutes * 60 * 1000);
    setPublishMode('scheduled');
    setScheduledAt(toDatetimeLocalValue(target));
  }, []);

  const handlePublish = useCallback(async () => {
    if (!envId) return toast.error('请选择发布账号');
    if (!title.trim()) return toast.error('请输入标题');
    if (title.length > 20) return toast.error('标题不能超过20字');
    if (!content.trim()) return toast.error('请输入正文内容');
    if (content.length > 1000) return toast.error('正文不能超过1000字');

    const uploadedPaths = images.filter(img => img.path).map(img => img.path as string);
    if (uploadedPaths.length === 0) return toast.error('请至少上传一张图片');
    let scheduledAtIso: string | undefined;
    if (publishMode === 'scheduled') {
      if (!scheduledAt) return toast.error('请选择定时发布时间');
      const scheduledIso = datetimeLocalToIso(scheduledAt);
      if (!scheduledIso) return toast.error('定时发布时间格式无效');
      const when = new Date(scheduledIso);
      if (when.getTime() <= Date.now() + 60 * 1000) return toast.error('定时发布时间必须至少晚于当前 1 分钟');
      scheduledAtIso = scheduledIso;
    }

    setPublishing(true);
    try {
      const result = await publishPost({
        environment_id: envId,
        title: title.trim(),
        content: content.trim(),
        image_paths: uploadedPaths,
        tags,
        is_original: false,
        visibility: '公开可见',
        scheduled_at: scheduledAtIso,
      });

      if (result.status === 'scheduled') {
        toast.success('定时发布已创建');
      } else if (result.status === 'publishing') {
        toast.success('已提交发布任务，后台正在执行');
      } else {
        toast.success('发布成功');
      }
      setTitle('');
      setContent('');
      setImages([]);
      setPublishMode('now');
      setScheduledAt('');
      setPage(1);
      await fetchPosts({ page: 1 });
    } catch (err: any) {
      toast.error(`发布失败: ${err.message}`);
    } finally {
      setPublishing(false);
    }
  }, [envId, title, content, images, tags, publishMode, scheduledAt, fetchPosts]);

  const handleSync = useCallback(async (postId: number) => {
    setSyncingId(postId);
    try {
      const result = await syncPostStats(postId);
      if (result.status === 'deleted' || result.sync_reason === 'post_deleted') {
        toast.info('帖子已删除，状态已更新');
      } else {
        toast.success('数据同步成功');
      }
    } catch (err: any) {
      toast.error(`同步失败: ${err.message}`);
    } finally {
      setSyncingId(null);
      fetchPosts();
    }
  }, [fetchPosts]);

  const openEdit = useCallback((post: XHSPost) => {
    setEditingPost(post);
    setEditTitle(post.title || '');
    setEditContent(post.content || '');
    setEditScheduledAt(toDatetimeLocalFromISO(post.scheduled_at));
  }, []);

  const closeEdit = useCallback(() => {
    setEditingPost(null);
    setEditTitle('');
    setEditContent('');
    setEditScheduledAt('');
  }, []);

  const handleSaveEdit = useCallback(async () => {
    if (!editingPost) return;
    if (!editTitle.trim()) return toast.error('标题不能为空');
    if (editTitle.trim().length > 20) return toast.error('标题不能超过20字');
    if (!editContent.trim()) return toast.error('正文不能为空');
    if (editContent.trim().length > 1000) return toast.error('正文不能超过1000字');

    const payload: { title: string; content: string; tags: string[]; scheduled_at?: string } = {
      title: editTitle.trim(),
      content: editContent.trim(),
      tags: extractHashTags(`${editTitle}\n${editContent}`),
    };
    if (editingPost.status === 'scheduled') {
      if (!editScheduledAt) return toast.error('请选择定时发布时间');
      const scheduledIso = datetimeLocalToIso(editScheduledAt);
      if (!scheduledIso) return toast.error('定时发布时间格式无效');
      const when = new Date(scheduledIso);
      if (when.getTime() <= Date.now() + 60 * 1000) return toast.error('定时发布时间必须至少晚于当前 1 分钟');
      payload.scheduled_at = scheduledIso;
    }

    setSavingEdit(true);
    try {
      await updatePost(editingPost.id, payload);
      toast.success('保存成功');
      closeEdit();
      fetchPosts();
    } catch (err: any) {
      toast.error(`保存失败: ${err.message}`);
    } finally {
      setSavingEdit(false);
    }
  }, [editingPost, editTitle, editContent, editScheduledAt, closeEdit, fetchPosts]);

  const handleRunNow = useCallback(async (postId: number) => {
    setRunningNowId(postId);
    try {
      await publishPostNow(postId);
      toast.success('已触发立即发布');
      fetchPosts();
    } catch (err: any) {
      toast.error(`执行失败: ${err.message}`);
    } finally {
      setRunningNowId(null);
    }
  }, [fetchPosts]);

  const handleCancelTask = useCallback(async (postId: number) => {
    setCancellingId(postId);
    try {
      await cancelPost(postId);
      toast.success('已取消任务');
      fetchPosts();
    } catch (err: any) {
      toast.error(`取消失败: ${err.message}`);
    } finally {
      setCancellingId(null);
    }
  }, [fetchPosts]);

  const handleRepublish = useCallback((post: XHSPost) => {
    const imagePaths = post.image_urls || [];
    if (imagePaths.length === 0) {
      toast.error('该失败帖子没有可用图片，请先上传图片后再发布');
      return;
    }

    setEnvId(post.environment_id);
    setTitle(post.title || '');
    setContent(post.content || '');
    setImages(imagePaths.map((path, idx) => ({ id: createImageClientId(), path, name: `已存图片${idx + 1}` })));
    setPublishMode('now');
    setScheduledAt('');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    toast.success('内容已带入发布区，请确认后点击“立即发布”');
  }, []);

  const reportRows = useMemo(() => {
    const rows = [...(reportData?.rows || [])];
    rows.sort((a, b) => {
      const ta = String((a as any)?.time || '');
      const tb = String((b as any)?.time || '');
      if (ta !== tb) return tb.localeCompare(ta);
      const ca = String((a as any)?.creative_name || (a as any)?.campaign_name || '');
      const cb = String((b as any)?.creative_name || (b as any)?.campaign_name || '');
      if (ca !== cb) return ca.localeCompare(cb, 'zh-Hans-CN');
      return String((a as any)?.creative_id || (a as any)?.campaign_id || '').localeCompare(
        String((b as any)?.creative_id || (b as any)?.campaign_id || '')
      );
    });
    return rows;
  }, [reportData, manageView, reportAccountId]);
  const creativeCompareGranularityData = useMemo(() => {
    if (!creativeCompareData) return null;
    return creativeCompareData.granularities?.day || null;
  }, [creativeCompareData]);
  const creativeCompareTags = useMemo(
    () => creativeCompareData?.tags || [],
    [creativeCompareData],
  );
  const creativeCompareChartMax = useMemo(() => {
    const periods = creativeCompareGranularityData?.periods || [];
    const values = periods.flatMap((period) =>
      creativeCompareTags.map((tag) => Number(period.tags?.[tag.key]?.[creativeCompareMetric] ?? 0)),
    );
    const max = Math.max(0, ...values);
    return max > 0 ? max : 1;
  }, [creativeCompareGranularityData, creativeCompareMetric, creativeCompareTags]);
  const creativeCompareDetailRows = useMemo(() => {
    const periods = creativeCompareGranularityData?.periods || [];
    return periods.flatMap((period) =>
      creativeCompareTags
        .map((tag) => ({
          period_key: period.period_key,
          period_label: period.period_label,
          period_start: period.period_start,
          period_end: period.period_end,
          tag_key: tag.key,
          tag_label: tag.label,
          metrics: period.tags?.[tag.key] || {},
        }))
        .filter((item) => Object.values(item.metrics).some((value) => Number(value ?? 0) !== 0)),
    );
  }, [creativeCompareGranularityData, creativeCompareTags]);
  const creativeCompareHoveredPeriod = useMemo(() => {
    const periods = creativeCompareGranularityData?.periods || [];
    if (periods.length === 0) return null;
    if (!creativeCompareHoveredPeriodKey) return null;
    return periods.find((period) => period.period_key === creativeCompareHoveredPeriodKey) || null;
  }, [creativeCompareGranularityData, creativeCompareHoveredPeriodKey]);
  const creativeCompareOverviewStats = useMemo(() => {
    const overallMetrics = creativeCompareGranularityData?.overall || {};
    return CREATIVE_COMPARE_CARD_METRICS.map((metric) => ({
      key: metric.key,
      label: metric.label,
      value: formatCreativeCompareValue(metric.key, Number(overallMetrics?.[metric.key] ?? 0)),
      accent:
        metric.key === 'note_count'
          ? 'text-slate-900'
          : metric.kind === 'money'
            ? 'text-emerald-700'
              : metric.kind === 'percent'
              ? 'text-violet-700'
              : 'text-sky-700',
    }));
  }, [creativeCompareGranularityData]);
  const creativeCompareRangeSummaryStats = useMemo(() => {
    const wantedKeys: CreativeCompareMetricKey[] = [
      'note_count',
      'fee',
      'impression',
      'click',
      'message_consult',
      'msg_leads_num',
    ];
    return wantedKeys
      .map((key) => creativeCompareOverviewStats.find((item) => item.key === key))
      .filter((item): item is NonNullable<typeof item> => Boolean(item));
  }, [creativeCompareOverviewStats]);
  const creativeCompareTagCards = useMemo(() => {
    const totalsByTag = creativeCompareGranularityData?.totals_by_tag || {};
    const periods = creativeCompareGranularityData?.periods || [];
    const peak = Math.max(
      0,
      ...creativeCompareTags.map((tag) => Number(totalsByTag?.[tag.key]?.[creativeCompareMetric] ?? 0)),
    );
    return creativeCompareTags
      .map((tag) => {
        const metrics = totalsByTag?.[tag.key] || {};
        const selectedMetricValue = Number(metrics?.[creativeCompareMetric] ?? 0);
        const series = periods.map((period) => Number(period.tags?.[tag.key]?.[creativeCompareMetric] ?? 0));
        return {
          ...tag,
          metrics,
          selectedMetricValue,
          ratio: peak > 0 ? selectedMetricValue / peak : 0,
          sparklinePath: buildSparklinePath(series, 212, 72, 8),
          sparklineValues: series,
        };
      })
      .sort((a, b) => b.selectedMetricValue - a.selectedMetricValue);
  }, [creativeCompareGranularityData, creativeCompareMetric, creativeCompareTags]);
  const currentLimit = manageView === 'auto' ? limit : manageView === 'account' ? 20 : REPORT_PAGE_LIMIT;
  const reportColumns = useMemo(() => {
    if (manageView === 'simple' || manageView === 'standard') return SIMPLE_STANDARD_REPORT_COLUMNS;
    if (manageView === 'creative') return CREATIVE_REPORT_COLUMNS;
    if (manageView === 'simple_note') return EASY_NOTE_REPORT_COLUMNS;
    if (manageView === 'standard_note') return STANDARD_NOTE_REPORT_COLUMNS;
    return [];
  }, [manageView]);
  const filteredPosts = useMemo(() => {
    if (manageView === 'auto') return posts;
    return posts;
  }, [posts, manageView]);
  const currentTotal = manageView === 'auto'
    ? total
    : manageView === 'account'
      ? accountNotesData.total
      : (reportData?.total_rows || 0);
  const accountNotesBusy = accountNotesLoading || isAccountNotesRendering;
  const manageViewCounts: Record<ManageView, number> = {
    auto: total,
    account: accountNotesData.total,
    simple: manageView === 'simple' ? (reportData?.total_rows || 0) : reportCache[`simple:all:${reportStartDate}:${reportEndDate}:1:${REPORT_PAGE_LIMIT}:all`]?.total_rows || 0,
    standard: manageView === 'standard' ? (reportData?.total_rows || 0) : reportCache[`standard:all:${reportStartDate}:${reportEndDate}:1:${REPORT_PAGE_LIMIT}:all`]?.total_rows || 0,
    creative: manageView === 'creative' ? (reportData?.total_rows || 0) : reportCache[`creative:all:${reportStartDate}:${reportEndDate}:1:${REPORT_PAGE_LIMIT}:all`]?.total_rows || 0,
    simple_note: manageView === 'simple_note' ? (reportData?.total_rows || 0) : reportCache[`simple_note:all:${reportStartDate}:${reportEndDate}:1:${REPORT_PAGE_LIMIT}:all`]?.total_rows || 0,
    standard_note: manageView === 'standard_note' ? (reportData?.total_rows || 0) : reportCache[`standard_note:all:${reportStartDate}:${reportEndDate}:1:${REPORT_PAGE_LIMIT}:all`]?.total_rows || 0,
  };
  const totalPages = Math.ceil(currentTotal / currentLimit);
  const pageNumbers = useMemo(() => {
    if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1);
    const numbers: (number | '...')[] = [1];
    const start = Math.max(2, page - 1);
    const end = Math.min(totalPages - 1, page + 1);
    if (start > 2) numbers.push('...');
    for (let i = start; i <= end; i += 1) numbers.push(i);
    if (end < totalPages - 1) numbers.push('...');
    numbers.push(totalPages);
    return numbers;
  }, [page, totalPages]);

  return (
    <div className="relative h-full min-h-0 overflow-hidden bg-[#f5f8ff]">
      <div className="pointer-events-none absolute -left-24 bottom-0 h-72 w-72 rounded-full bg-white blur-2xl" />
      <div className="pointer-events-none absolute -right-24 -top-28 h-96 w-96 rounded-full bg-blue-200/35 blur-3xl" />
      <div className="pointer-events-none absolute left-1/3 top-8 h-80 w-80 rounded-full bg-indigo-100/60 blur-3xl" />
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(120deg,rgba(255,255,255,0.72),rgba(237,244,255,0.45)_48%,rgba(255,255,255,0.86))]" />

      <div
        className="relative z-10 h-full w-[111.111111%] origin-top-left scale-90"
        style={{ height: '111.111111%' }}
      >
        <div className="flex h-full min-h-0 w-full flex-col gap-3 p-2.5 md:p-4 xl:flex-row xl:overflow-hidden">
        <section className="flex min-h-0 w-full shrink-0 flex-col overflow-hidden rounded-[28px] border border-white/80 bg-white/80 shadow-[0_24px_70px_rgba(81,112,160,0.18)] backdrop-blur-xl xl:h-full xl:w-[560px]">
          <div className="flex items-center justify-between border-b border-slate-200/70 px-4 py-3">
            <div>
              <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-600">Cloud Studio</span>
              <h2 className="mt-1 text-base font-semibold tracking-tight text-slate-950">小红书发布</h2>
            </div>
            <span className="rounded-full bg-white/85 px-2.5 py-1 text-xs font-medium text-slate-500 shadow-sm">标签 {tags.length}</span>
          </div>

          <div className="flex-1 min-h-0 overflow-auto px-4 py-3">
            <div className="flex min-h-full flex-col gap-2">
              <div className="rounded-2xl border border-slate-200/80 bg-white/85 p-2.5 shadow-[0_12px_36px_rgba(79,103,146,0.08)]">
                <label className="mb-1 block text-xs font-semibold text-slate-500">发布账号</label>
                <select
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm outline-none transition-all focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                  value={envId || ''}
                  onChange={e => setEnvId(Number(e.target.value))}
                >
                  <option value="">请选择账号</option>
                  {environments.map(env => (
                    <option key={env.id} value={env.id}>
                      {env.account_name}
                      {env.notes ? ` (${env.notes})` : ''}
                      {env.group_name ? ` [${env.group_name}]` : ''}
                    </option>
                  ))}
                </select>
              </div>

              <div className="rounded-2xl border border-slate-200/80 bg-white/70 p-2.5 shadow-[0_12px_36px_rgba(79,103,146,0.07)]">
                <label className="mb-1 block text-xs font-semibold text-slate-500">标题</label>
                <input
                  type="text"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition-all focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                  maxLength={20}
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  placeholder="请输入标题（最多20字）"
                />
                <p className="mt-0.5 text-right text-xs text-slate-400">{title.length}/20</p>
              </div>

              <div className="rounded-2xl border border-slate-200/80 bg-white/70 p-2.5 shadow-[0_12px_36px_rgba(79,103,146,0.07)]">
                <label className="mb-1 block text-xs font-semibold text-slate-500">正文内容</label>
                <textarea
                  className="h-56 w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm leading-5 text-slate-900 shadow-sm outline-none transition-all focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                  maxLength={1000}
                  value={content}
                  onChange={e => setContent(e.target.value)}
                  placeholder="请输入正文，直接写 #话题 自动识别"
                />
                <div className="mt-1.5 flex items-start justify-between gap-2">
                  <div className="flex flex-wrap gap-1.5">
                    {tags.length === 0 ? (
                      <span className="text-xs text-slate-400">示例：#高尔夫 #置换补贴</span>
                    ) : (
                      tags.map(tag => (
                        <span key={tag} className="rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-600">#{tag}</span>
                      ))
                    )}
                  </div>
                  <span className="whitespace-nowrap text-xs text-slate-400">{content.length}/1000</span>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200/80 bg-white/70 p-2.5 shadow-[0_12px_36px_rgba(79,103,146,0.07)]">
                <div className="mb-1.5 flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-500">图片素材</label>
                  <span className="text-xs text-slate-400">{images.filter(i => i.path).length}/{images.length}</span>
                </div>
                <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
                  {images.map((img, idx) => (
                    <div key={img.id} className="relative h-14 w-14 shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-slate-100">
                      {img.file ? (
                        <img src={URL.createObjectURL(img.file)} alt={img.file.name} className="h-full w-full object-cover" />
                      ) : img.path && (img.path.startsWith('/uploads/') || img.path.startsWith('http://') || img.path.startsWith('https://') || img.path.startsWith('data:image/')) ? (
                        <img src={img.path} alt={img.name || '图库图片'} className="h-full w-full object-cover" />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center px-1 text-center text-[9px] text-slate-500">
                          已存图片
                        </div>
                      )}
                      <button
                        className="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full border border-white bg-white/90 text-[10px] text-slate-500"
                        onClick={() => removeImage(idx)}
                      >
                        ×
                      </button>
                      {!img.path && <div className="absolute inset-0 grid place-items-center bg-black/35 text-[10px] text-white">上传中</div>}
                    </div>
                  ))}
                  <label className="grid h-14 w-14 shrink-0 cursor-pointer place-items-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-[10px] font-semibold text-slate-500 transition-all hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-600">
                    添加
                    <input type="file" accept="image/*" multiple className="hidden" onChange={handleImageUpload} />
                  </label>
                  <button
                    type="button"
                    onClick={() => setGalleryPickerOpen(true)}
                    className="grid h-14 w-14 shrink-0 place-items-center rounded-xl border border-dashed border-indigo-200 bg-indigo-50 text-[10px] font-semibold text-indigo-600 transition-all hover:border-indigo-300 hover:bg-indigo-100"
                  >
                    图库
                  </button>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200/80 bg-white/70 p-2.5 shadow-[0_12px_36px_rgba(79,103,146,0.07)]">
                <label className="mb-1 block text-xs font-semibold text-slate-500">发布方式</label>
                <div className="grid grid-cols-2 gap-1.5 rounded-xl border border-slate-200 bg-slate-50 p-1">
                  <button
                    type="button"
                    onClick={() => setPublishMode('now')}
                    className={`rounded-lg px-2 py-1.5 text-xs font-semibold transition-all ${
                      publishMode === 'now'
                        ? 'bg-white text-indigo-600 shadow-sm'
                        : 'text-slate-500 hover:text-indigo-600'
                    }`}
                  >
                    立即发布
                  </button>
                  <button
                    type="button"
                    onClick={() => setPublishMode('scheduled')}
                    className={`rounded-lg px-2 py-1.5 text-xs font-semibold transition-all ${
                      publishMode === 'scheduled'
                        ? 'bg-white text-indigo-600 shadow-sm'
                        : 'text-slate-500 hover:text-indigo-600'
                    }`}
                  >
                    定时发布
                  </button>
                </div>

                {publishMode === 'scheduled' && (
                  <div className="mt-2 space-y-1.5">
                    <input
                      type="datetime-local"
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs outline-none transition-all focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                      value={scheduledAt}
                      onChange={(e) => setScheduledAt(e.target.value)}
                    />
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        onClick={() => applyScheduleMinutes(30)}
                        className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600"
                      >
                        30分钟后
                      </button>
                      <button
                        type="button"
                        onClick={() => applyScheduleMinutes(120)}
                        className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600"
                      >
                        2小时后
                      </button>
                      <button
                        type="button"
                        onClick={() => applyScheduleMinutes(24 * 60)}
                        className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600"
                      >
                        明天同一时间
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <button
                className="mt-auto flex h-9 items-center justify-center gap-1.5 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-3 text-sm font-semibold text-white shadow-lg shadow-indigo-300/40 transition-all hover:-translate-y-0.5 hover:shadow-indigo-300/60 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400 disabled:shadow-none"
                onClick={handlePublish}
                disabled={publishing}
              >
                {publishing ? '处理中...' : publishMode === 'scheduled' ? '创建定时发布' : '立即发布'}
              </button>
            </div>
          </div>
        </section>

        <section className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-visible rounded-[32px] border border-white/80 bg-white/72 shadow-[0_24px_80px_rgba(81,112,160,0.18)] backdrop-blur-xl">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_80%_5%,rgba(129,161,255,0.2),transparent_32%),radial-gradient(circle_at_10%_100%,rgba(255,255,255,0.95),transparent_35%)]" />

          <div className="relative z-30 border-b border-slate-200/70 px-4 py-3">
            <div className="flex flex-col gap-3">
              <div className="grid gap-2 md:grid-cols-4 2xl:grid-cols-7">
                  {MANAGE_VIEW_ORDER.map((view) => {
                    const active = manageView === view;
                    return (
                      <button
                        key={view}
                        type="button"
                        onClick={() => setManageView(view)}
                        className={`rounded-xl border px-3 py-2.5 text-left transition-all ${
                          active
                            ? 'border-indigo-400 bg-[linear-gradient(180deg,#eef4ff_0%,#ffffff_100%)] shadow-[0_16px_36px_rgba(79,103,146,0.18),inset_0_0_0_1px_rgba(99,102,241,0.10)]'
                            : 'border-slate-200 bg-white/75 hover:border-indigo-100 hover:bg-white'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <div className={`text-sm font-semibold ${active ? 'text-indigo-700' : 'text-slate-900'}`}>{getReportViewLabel(view)}</div>
                            {view === 'account' && (
                              <>
                                {hasUnsetAccountNotes && (
                                  <span
                                    className="h-2.5 w-2.5 animate-pulse rounded-full bg-amber-500 shadow-[0_0_0_4px_rgba(245,158,11,0.16)]"
                                    title="存在未设置标记的帖子"
                                  />
                                )}
                                {(accountNotesSyncInProgress || accountNoteDetailsSyncInProgress) && (
                                  <span
                                    className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600"
                                    title="账号数据同步中"
                                  />
                                )}
                              </>
                            )}
                          </div>
                          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${active ? 'bg-indigo-600 text-white shadow-[0_8px_18px_rgba(99,102,241,0.28)]' : 'bg-slate-100 text-slate-500'}`}>
                            {manageViewCounts[view]}
                          </span>
                        </div>
                      </button>
                    );
                  })}
              </div>

              <div className="relative z-30 flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-2.5 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex flex-1 flex-wrap gap-2">
                    {manageView === 'account' && (
                      <>
                        <div className={`relative min-w-[150px] flex-1 max-w-[220px] ${accountEnvPickerOpen ? 'z-[95]' : 'z-10'}`} ref={accountEnvPickerRef}>
                          <button
                            type="button"
                            onClick={() => setAccountEnvPickerOpen((open) => !open)}
                            className="inline-flex h-9 w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 text-left text-xs font-semibold text-slate-700 outline-none transition-all hover:border-indigo-200 hover:bg-indigo-50/50"
                          >
                            <span className="truncate">
                              {selectedAccountEnv ? selectedAccountEnv.account_name : '全部账号'}
                            </span>
                            <span className="shrink-0 text-slate-400">▾</span>
                          </button>
                          {accountEnvPickerOpen && (
                            <div className="absolute left-0 top-[calc(100%+8px)] z-[100] w-full rounded-[24px] border border-slate-200 bg-white p-3 shadow-[0_24px_60px_rgba(15,23,42,0.14)]">
                              <div className="relative">
                                <input
                                  type="text"
                                  value={accountEnvSearch}
                                  onChange={(event) => setAccountEnvSearch(event.target.value)}
                                  placeholder="搜索账号名"
                                  className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 pl-3 pr-9 text-xs font-medium text-slate-700 outline-none transition-all placeholder:text-slate-400 focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                                />
                                {accountEnvSearch && (
                                  <button
                                    type="button"
                                    onClick={() => setAccountEnvSearch('')}
                                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md px-1.5 py-0.5 text-[11px] font-semibold text-slate-400 transition-all hover:bg-slate-100 hover:text-slate-600"
                                  >
                                    清空
                                  </button>
                                )}
                              </div>
                              <div className="mt-3 max-h-[320px] overflow-y-auto pr-1">
                                <button
                                  type="button"
                                  onClick={() => {
                                    setAccountEnvId('all');
                                    setAccountEnvPickerOpen(false);
                                    setAccountEnvSearch('');
                                  }}
                                  className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-xs font-semibold transition-all ${
                                    accountEnvId === 'all'
                                      ? 'bg-slate-900 text-white'
                                      : 'text-slate-700 hover:bg-slate-50'
                                  }`}
                                >
                                  <span>全部账号</span>
                                </button>
                                {filteredAccountEnvOptions.length === 0 ? (
                                  <div className="px-3 py-6 text-center text-xs text-slate-400">没有匹配到账号</div>
                                ) : (
                                  filteredAccountEnvOptions.map((item) => {
                                    const active = accountEnvId === item.id;
                                    return (
                                      <button
                                        key={item.id}
                                        type="button"
                                        onClick={() => {
                                          setAccountEnvId(item.id);
                                          setAccountEnvPickerOpen(false);
                                          setAccountEnvSearch('');
                                        }}
                                        className={`mt-1 flex w-full items-center rounded-xl px-3 py-2 text-left text-xs font-semibold transition-all ${
                                          active
                                            ? 'bg-slate-900 text-white'
                                            : 'text-slate-700 hover:bg-slate-50'
                                        }`}
                                      >
                                        <span className="block truncate">{item.account_name}</span>
                                      </button>
                                    );
                                  })
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                        {isAdmin && (
                          <select
                            className="h-9 min-w-[180px] rounded-xl border border-indigo-200 bg-indigo-50 px-3 text-xs font-semibold text-indigo-700 outline-none transition-all focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                            value={accountSyncScrapeEnvId ?? ''}
                            onChange={(e) => setAccountSyncScrapeEnvId(e.target.value ? Number(e.target.value) : null)}
                          >
                            <option value="">选择同步环境</option>
                            {accountSyncRunnerOptions.map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.account_name}
                              </option>
                            ))}
                          </select>
                        )}
                        <select
                          className="h-9 min-w-[132px] rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 outline-none transition-all focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                          value={accountAiFilter}
                          onChange={(e) => setAccountAiFilter(e.target.value as typeof accountAiFilter)}
                        >
                          <option value="all">全部标记</option>
                          <option value="__unset__">未设置</option>
                          <option value="manual">纯手工</option>
                          <option value="text_ai">仅文案 AI</option>
                          <option value="image_ai">仅图片 AI</option>
                          <option value="all_ai">图文都 AI</option>
                        </select>
                        <div className="relative min-w-[280px] flex-1 max-w-[420px]">
                          <input
                            type="text"
                            value={accountSearch}
                            onChange={(e) => {
                              setAccountSearch(e.target.value);
                              setPage(1);
                            }}
                            placeholder="筛选标题 / Feed ID / 小红书号"
                            className="h-9 w-full rounded-xl border border-slate-200 bg-white pl-3 pr-9 text-xs font-medium text-slate-700 outline-none transition-all placeholder:text-slate-400 focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                          />
                          {accountSearch && (
                            <button
                              type="button"
                              onClick={() => {
                                setAccountSearch('');
                                setPage(1);
                              }}
                              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md px-1.5 py-0.5 text-[11px] font-semibold text-slate-400 transition-all hover:bg-slate-100 hover:text-slate-600"
                            >
                              清空
                            </button>
                          )}
                        </div>
                      </>
                    )}
                    {manageView !== 'auto' && manageView !== 'account' && (
                      <>
                        <div className={`relative min-w-[160px] flex-1 max-w-[220px] ${reportAccountPickerOpen ? 'z-[95]' : 'z-10'}`} ref={reportAccountPickerRef}>
                          <button
                            type="button"
                            onClick={() => setReportAccountPickerOpen((open) => !open)}
                            className="inline-flex h-9 w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 text-left text-xs font-semibold text-slate-700 outline-none transition-all hover:border-indigo-200 hover:bg-indigo-50/50"
                          >
                            <span className="truncate">
                              {selectedReportAccount ? `${selectedReportAccount.account_name} (${selectedReportAccount.account_id})` : '全部账号数据'}
                            </span>
                            <span className="shrink-0 text-slate-400">▾</span>
                          </button>
                          {reportAccountPickerOpen && (
                            <div className="absolute left-0 top-[calc(100%+8px)] z-[100] w-full rounded-[24px] border border-slate-200 bg-white p-3 shadow-[0_24px_60px_rgba(15,23,42,0.14)]">
                              <div className="relative">
                                <input
                                  type="text"
                                  value={reportAccountSearch}
                                  onChange={(event) => setReportAccountSearch(event.target.value)}
                                  placeholder="搜索账号名 / 账户ID"
                                  className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 pl-3 pr-9 text-xs font-medium text-slate-700 outline-none transition-all placeholder:text-slate-400 focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                                />
                                {reportAccountSearch && (
                                  <button
                                    type="button"
                                    onClick={() => setReportAccountSearch('')}
                                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md px-1.5 py-0.5 text-[11px] font-semibold text-slate-400 transition-all hover:bg-slate-100 hover:text-slate-600"
                                  >
                                    清空
                                  </button>
                                )}
                              </div>
                              <div className="mt-3 max-h-[320px] overflow-y-auto pr-1">
                                <button
                                  type="button"
                                  onClick={() => {
                                    setReportAccountId('all');
                                    setReportAccountPickerOpen(false);
                                    setReportAccountSearch('');
                                  }}
                                  className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-xs font-semibold transition-all ${
                                    reportAccountId === 'all'
                                      ? 'bg-slate-900 text-white'
                                      : 'text-slate-700 hover:bg-slate-50'
                                  }`}
                                >
                                  <span>全部账号数据</span>
                                </button>
                                {filteredReportAccountOptions.length === 0 ? (
                                  <div className="px-3 py-6 text-center text-xs text-slate-400">没有匹配到账号</div>
                                ) : (
                                  filteredReportAccountOptions.map((item) => {
                                    const active = reportAccountId === item.account_id;
                                    return (
                                      <button
                                        key={item.account_id}
                                        type="button"
                                        onClick={() => {
                                          setReportAccountId(item.account_id);
                                          setReportAccountPickerOpen(false);
                                          setReportAccountSearch('');
                                        }}
                                        className={`mt-1 flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-xs font-semibold transition-all ${
                                          active
                                            ? 'bg-slate-900 text-white'
                                            : 'text-slate-700 hover:bg-slate-50'
                                        }`}
                                      >
                                        <span className="min-w-0">
                                          <span className="block truncate">{item.account_name}</span>
                                          <span className={`block truncate text-[10px] ${active ? 'text-white/80' : 'text-slate-400'}`}>{item.account_id}</span>
                                        </span>
                                      </button>
                                    );
                                  })
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                        <div className={`relative ${reportDatePickerOpen ? 'z-[90]' : 'z-10'}`} ref={reportDatePickerRef}>
                          <button
                            type="button"
                            onClick={() => {
                              setReportDatePickerOpen((open) => {
                                const next = !open;
                                if (next) {
                                  setReportSelectingRangeEnd(false);
                                  setReportCalendarMonth(parseDateInputValue(reportStartDate) || new Date());
                                }
                                return next;
                              });
                            }}
                            className="inline-flex h-9 min-w-[260px] items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 outline-none transition-all hover:border-indigo-200 hover:bg-indigo-50/50"
                          >
                            <span>{reportRangeLabel}</span>
                            <span className="text-slate-400">▾</span>
                          </button>
                          {reportDatePickerOpen && (
                            <div className="absolute left-0 top-[calc(100%+8px)] z-[100] w-[320px] rounded-[24px] border border-slate-200 bg-white p-4 shadow-[0_24px_60px_rgba(15,23,42,0.14)]">
                              <div className="flex items-center justify-between gap-2">
                                <button
                                  type="button"
                                  onClick={() => setReportCalendarMonth((current) => addMonths(current, -1))}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-200 text-slate-500 transition-all hover:bg-slate-50 hover:text-slate-800"
                                >
                                  ‹
                                </button>
                                <div className="text-sm font-semibold text-slate-900">
                                  {reportCalendarMonth.getFullYear()}年{reportCalendarMonth.getMonth() + 1}月
                                </div>
                                <button
                                  type="button"
                                  onClick={() => setReportCalendarMonth((current) => addMonths(current, 1))}
                                  disabled={
                                    reportCalendarMonth.getFullYear() >= latestReportEndDate.getFullYear()
                                    && reportCalendarMonth.getMonth() >= latestReportEndDate.getMonth()
                                  }
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-200 text-slate-500 transition-all hover:bg-slate-50 hover:text-slate-800"
                                >
                                  ›
                                </button>
                              </div>

                              <div className="mt-3 grid grid-cols-7 gap-1 text-center text-[11px] font-semibold text-slate-400">
                                {['日', '一', '二', '三', '四', '五', '六'].map((label) => (
                                  <div key={`weekday-${label}`} className="py-1">{label}</div>
                                ))}
                              </div>

                              <div className="mt-1 grid grid-cols-7 gap-1">
                                {reportCalendarDays.map((day) => {
                                  const isDisabled = day.value > latestReportEndDateValue;
                                  const isStart = day.value === reportStartDate;
                                  const isEnd = day.value === reportEndDate;
                                  const inRange = day.value >= reportStartDate && day.value <= reportEndDate;
                                  return (
                                    <button
                                      key={day.value}
                                      type="button"
                                      disabled={isDisabled}
                                      onClick={() => handlePickReportDate(day.value)}
                                      className={`h-9 rounded-xl text-sm transition-all ${
                                        isDisabled
                                          ? 'cursor-not-allowed bg-slate-50 text-slate-300'
                                          : isStart || isEnd
                                          ? 'bg-slate-900 font-semibold text-white shadow-[0_10px_20px_rgba(15,23,42,0.16)]'
                                          : inRange
                                            ? 'bg-indigo-50 text-indigo-700'
                                            : day.inMonth
                                              ? 'text-slate-700 hover:bg-slate-50'
                                              : 'text-slate-300 hover:bg-slate-50'
                                      }`}
                                    >
                                      {day.day}
                                    </button>
                                  );
                                })}
                              </div>

                              <div className="mt-3 flex items-center justify-between text-[11px] text-slate-500">
                                <span>先选开始日期，再选结束日期，最晚只能选昨天</span>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setReportStartDate(defaultReportDateRange.startDate);
                                    setReportEndDate(defaultReportDateRange.endDate);
                                    setReportSelectingRangeEnd(false);
                                    setReportCalendarMonth(parseDateInputValue(defaultReportDateRange.startDate) || new Date());
                                  }}
                                  className="font-semibold text-slate-700 transition-all hover:text-slate-900"
                                >
                                  重置
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      </>
                    )}
                    {manageView === 'creative' && (
                      <>
                        <div className="grid h-9 grid-cols-2 rounded-xl border border-slate-200 bg-slate-50 p-1">
                          <button
                            type="button"
                            onClick={() => setCreativeReportMode('rows')}
                            className={`rounded-lg px-3 text-xs font-semibold transition-all ${
                              creativeReportMode === 'rows'
                                ? 'bg-white text-indigo-600 shadow-sm'
                                : 'text-slate-500 hover:text-indigo-600'
                            }`}
                          >
                            原始明细
                          </button>
                          <button
                            type="button"
                            onClick={() => setCreativeReportMode('compare')}
                            className={`rounded-lg px-3 text-xs font-semibold transition-all ${
                              creativeReportMode === 'compare'
                                ? 'bg-white text-indigo-600 shadow-sm'
                                : 'text-slate-500 hover:text-indigo-600'
                            }`}
                          >
                            标签对比
                          </button>
                        </div>
                        {creativeReportMode === 'rows' ? (
                          <select
                            className="h-9 min-w-[136px] rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 outline-none transition-all focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                            value={creativeAiFilter}
                            onChange={(e) => {
                              setCreativeAiFilter(e.target.value as typeof creativeAiFilter);
                              setPage(1);
                            }}
                          >
                            <option value="all">全部标记</option>
                            <option value="__missing__">未找到</option>
                            <option value="__unset__">未设置</option>
                            <option value="manual">纯手工</option>
                            <option value="text_ai">仅文案 AI</option>
                            <option value="image_ai">仅图片 AI</option>
                            <option value="all_ai">图文都 AI</option>
                          </select>
                        ) : (
                          <div className="flex h-9 items-center rounded-xl border border-indigo-200 bg-indigo-50 px-3 text-xs font-semibold text-indigo-700">
                            标签对比视图固定排除未找到 / 未设置
                          </div>
                        )}
                      </>
                    )}
                    {manageView === 'auto' && (
                      <>
                        <select
                          className="h-9 min-w-[128px] rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 outline-none transition-all focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                          value={limit}
                          onChange={(e) => {
                            setLimit(Number(e.target.value));
                            setPage(1);
                          }}
                        >
                          <option value={10}>每页10条</option>
                          <option value={20}>每页20条</option>
                          <option value={50}>每页50条</option>
                        </select>
                        <select
                          className="h-9 min-w-[128px] rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 outline-none transition-all focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                          value={statusFilter}
                          onChange={(e) => {
                            setStatusFilter(e.target.value);
                            setPage(1);
                          }}
                        >
                          <option value="">全部状态</option>
                          <option value="publishing">发布中</option>
                          <option value="success">已发布</option>
                          <option value="scheduled">待发布</option>
                          <option value="cancelled">已取消</option>
                          <option value="failed">失败</option>
                          <option value="deleted">已删除</option>
                        </select>
                      </>
                    )}
                </div>

                <div className="flex flex-wrap gap-2">
                    {manageView === 'auto' && statusFilter && (
                      <button
                        className="h-9 rounded-xl border border-slate-200 bg-slate-50 px-4 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600"
                        onClick={() => {
                          setStatusFilter('');
                          setPage(1);
                        }}
                      >
                        清空筛选
                      </button>
                    )}
                    {manageView === 'account' && (
                      <>
                        {isAdmin && (
                          <button
                            className="h-9 rounded-xl border border-emerald-200 bg-emerald-50 px-4 text-xs font-semibold text-emerald-700 transition-all hover:bg-emerald-100 disabled:opacity-50"
                            onClick={() => {
                              if (accountEngagementSyncInProgress) {
                                setAccountSyncProgressPanel('account_engagement');
                                return;
                              }
                              openAccountEngagementSyncStrategyModal();
                            }}
                            disabled={accountEngagementSyncing || (!accountEngagementSyncInProgress && (accountNotesSyncInProgress || accountNoteDetailsSyncInProgress))}
                            title={accountEngagementSyncInProgress ? '查看当前主同步进度' : '唯一的新增帖子入口：从创作者中心创建主记录并刷新互动数据'}
                          >
                            {accountEngagementSyncing ? '下发中...' : accountEngagementSyncInProgress ? '同步中 · 查看进度' : '创作中心主同步'}
                          </button>
                        )}
                        {isAdmin && (
                          <button
                            className="h-9 rounded-xl border border-indigo-200 bg-indigo-50 px-4 text-xs font-semibold text-indigo-700 transition-all hover:bg-indigo-100 disabled:opacity-50"
                            onClick={() => {
                              if (accountNotesSyncInProgress) {
                                setAccountSyncProgressPanel('account_notes');
                                return;
                              }
                              openAccountPostSyncStrategyModal();
                            }}
                            disabled={accountNotesSyncing || (!accountNotesSyncInProgress && (accountEngagementSyncInProgress || accountNoteDetailsSyncInProgress))}
                            title={
                              accountNotesSyncInProgress
                                ? '查看当前账号帖子同步进度'
                                : '主页同步只补齐创作者中心已有帖子的帖子 ID、链接、封面和账号信息，不再新增帖子'
                            }
                          >
                            {accountNotesSyncing ? '提交中...' : accountNotesSyncInProgress ? '同步中 · 查看进度' : '主页帖子补充策略'}
                          </button>
                        )}
                        {isAdmin && (
                          <button
                            className="h-9 rounded-xl border border-amber-200 bg-amber-50 px-4 text-xs font-semibold text-amber-700 transition-all hover:bg-amber-100 disabled:opacity-50"
                            onClick={() => {
                              if (accountNoteDetailsSyncInProgress) {
                                setAccountSyncProgressPanel('account_note_details');
                                return;
                              }
                              openAccountDetailSyncStrategyModal('unpublished_only');
                            }}
                            disabled={accountNoteDetailsSyncing || (!accountNoteDetailsSyncInProgress && (accountNotesSyncInProgress || accountEngagementSyncInProgress))}
                            title={accountNoteDetailsSyncInProgress ? '查看当前详情同步进度' : '选择测试账号轮换、每个账号处理条数与暂停节奏后，再执行未同步数据补齐'}
                          >
                            {accountNoteDetailsSyncing ? '提交中...' : accountNoteDetailsSyncInProgress ? '同步中 · 查看进度' : '未同步策略'}
                          </button>
                        )}
                        {isAdmin && (
                          <button
                            className="h-9 rounded-xl border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700"
                            onClick={() => setAccountSyncHistoryOpen(true)}
                            title="查看每次账号主页同步的成功、失败与可重跑项"
                          >
                            同步历史
                          </button>
                        )}
                        {isAdmin && (
                          <button
                            className="h-9 rounded-xl border border-violet-200 bg-violet-50 px-4 text-xs font-semibold text-violet-700 transition-all hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-50"
                            onClick={handleTagAccountNoteContent}
                            disabled={accountContentTagging || accountNotesSyncInProgress || accountEngagementSyncInProgress || accountNoteDetailsSyncInProgress}
                            title="按当前账号数据筛选范围统一进行内容标签打标，模型并发 20 个帖子"
                          >
                            {accountContentTagging ? '打标签中...' : '内容打标签'}
                          </button>
                        )}
                        <button
                          className={`h-9 rounded-xl border px-4 text-xs font-semibold transition-all ${
                            accountBatchSelectMode
                              ? 'border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
                              : 'border-slate-200 bg-white text-slate-700 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600'
                          }`}
                          onClick={() => {
                            if (accountBatchSelectMode) {
                              setAccountBatchSelectMode(false);
                              setSelectedAccountNoteIds([]);
                            } else {
                              setAccountBatchSelectMode(true);
                            }
                          }}
                        >
                          {accountBatchSelectMode ? '退出批量标记' : '批量标记'}
                        </button>
                      </>
                    )}
                    {manageView !== 'auto' && manageView !== 'account' && (
                      <>
                        {isAdmin && (
                          <button
                            className="h-9 rounded-xl border border-slate-200 bg-slate-50 px-4 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600"
                            onClick={handleRefreshReport}
                            disabled={reportRefreshing || reportDateRangeInvalid}
                          >
                            {reportRefreshing ? '更新中...' : '更新数据'}
                          </button>
                        )}
                        <button
                          className="h-9 rounded-xl border border-emerald-200 bg-emerald-50 px-4 text-xs font-semibold text-emerald-700 transition-all hover:bg-emerald-100 disabled:opacity-50"
                          onClick={handleExportReport}
                          disabled={exportingReport || reportDateRangeInvalid}
                        >
                          {exportingReport ? '导出中...' : '导出表格'}
                        </button>
                      </>
                    )}
                  </div>
                  {manageView !== 'auto' && manageView !== 'account' && reportDateRangeInvalid && (
                    <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs font-medium text-amber-700">
                      结束日期不能早于开始日期。
                    </div>
                  )}
                </div>
              </div>
            </div>

          <div className="relative z-10 flex min-h-0 min-w-0 flex-1 flex-col overflow-visible px-5 py-4">
            <div
              className={`min-h-0 flex-1 ${
                manageView === 'creative' && creativeReportMode === 'compare'
                  ? 'overflow-auto'
                  : 'overflow-hidden'
              }`}
            >
            {manageView === 'auto' ? (
              loadingPosts ? (
              <InlineSpinner label="加载中..." />
            ) : filteredPosts.length === 0 ? (
              <div className="grid place-items-center rounded-[24px] border border-dashed border-slate-200 bg-white/55 py-20 text-sm text-slate-400">暂无帖子数据</div>
            ) : (
              <div className="flex h-full min-h-0 flex-col">
                <div className="min-h-0 flex-1 overflow-auto rounded-[24px] border border-slate-200/90 bg-white/85 shadow-[0_14px_36px_rgba(79,103,146,0.1)]">
                  <table className="w-full min-w-[860px] text-sm">
                    <thead className="sticky top-0 z-10 bg-slate-50/95 text-slate-600 backdrop-blur">
                      <tr>
                        <th className="px-4 py-3 text-left font-medium">
                          {manageView === 'auto'
                            ? '标题 / 正文'
                            : manageView === 'simple'
                              ? '简单投标的 / 正文'
                              : manageView === 'standard'
                                ? '标准投计划 / 正文'
                                : '创意 / 计划'}
                        </th>
                        <th className="px-4 py-3 text-left font-medium">状态</th>
                        <th className="px-4 py-3 text-left font-medium">发布账号</th>
                        <th className="px-4 py-3 text-center font-medium">点赞</th>
                        <th className="px-4 py-3 text-center font-medium">评论</th>
                        <th className="px-4 py-3 text-center font-medium">收藏</th>
                        <th className="px-4 py-3 text-center font-medium">转发</th>
                        <th className="px-4 py-3 text-center font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPosts.map(post => (
                        <tr key={post.id} className="border-t border-slate-100 hover:bg-indigo-50/35">
                          <td className="px-4 py-3">
                            <div className="max-w-[260px] truncate font-medium text-slate-900">
                              {post.post_url ? (
                                <a href={post.post_url} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline">
                                  {post.title}
                                </a>
                              ) : post.title}
                            </div>
                            <div className="mt-0.5 max-w-[300px] truncate text-xs text-slate-400">{post.content}</div>
                          </td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs ${STATUS_COLORS[post.status] || 'bg-slate-100 text-slate-600 border-slate-200'}`}>
                              {STATUS_LABELS[post.status] || post.status}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-sm text-slate-600">{post.account_name || '-'}</td>
                          <td className="px-4 py-3 text-center">{post.like_count}</td>
                          <td className="px-4 py-3 text-center">{post.comment_count}</td>
                          <td className="px-4 py-3 text-center">{post.collect_count}</td>
                          <td className="px-4 py-3 text-center">{post.share_count}</td>
                          <td className="px-4 py-3 text-center">
                            <div className="flex flex-wrap items-center justify-center gap-1.5">
                              {post.status === 'success' && (
                                <button
                                  className="rounded-xl border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:cursor-not-allowed disabled:opacity-45"
                                  onClick={() => handleSync(post.id)}
                                  disabled={syncingId === post.id}
                                  title="使用当前同步环境采集账号同步互动数据"
                                >
                                  {syncingId === post.id ? '同步中' : '同步'}
                                </button>
                              )}
                              {post.status === 'scheduled' && (
                                <button
                                  className="rounded-xl border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-600 transition-all hover:bg-indigo-100"
                                  onClick={() => openEdit(post)}
                                >
                                  编辑
                                </button>
                              )}
                              {(post.status === 'failed' || post.status === 'cancelled') && (
                                <button
                                  className="rounded-xl border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700 transition-all hover:bg-amber-100"
                                  onClick={() => handleRepublish(post)}
                                >
                                  重新发布
                                </button>
                              )}
                              {post.status === 'scheduled' && (
                                <>
                                  <button
                                    className="rounded-xl border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 transition-all hover:bg-emerald-100 disabled:opacity-45"
                                    onClick={() => handleRunNow(post.id)}
                                    disabled={runningNowId === post.id}
                                  >
                                    {runningNowId === post.id ? '执行中' : '立即发布'}
                                  </button>
                                  <button
                                    className="rounded-xl border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 transition-all hover:bg-slate-50 disabled:opacity-45"
                                    onClick={() => handleCancelTask(post.id)}
                                    disabled={cancellingId === post.id}
                                  >
                                    {cancellingId === post.id ? '取消中' : '取消'}
                                  </button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {totalPages > 1 && (
                  <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
                    <span>第 {page} / {totalPages} 页 · 共 {total} 条</span>
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                        disabled={page <= 1}
                        onClick={() => setPage(1)}
                      >
                        首页
                      </button>
                      <button
                        className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                        disabled={page <= 1}
                        onClick={() => setPage(p => p - 1)}
                      >
                        上一页
                      </button>
                      {pageNumbers.map((item, index) => (
                        item === '...' ? (
                          <span key={`ellipsis-${index}`} className="px-1 text-slate-400">...</span>
                        ) : (
                          <button
                            key={item}
                            className={`rounded-xl border px-3 py-1 text-xs font-semibold transition-all ${
                              page === item
                                ? 'border-indigo-300 bg-indigo-50 text-indigo-600'
                                : 'border-slate-200 bg-white text-slate-600 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600'
                            }`}
                            onClick={() => setPage(item)}
                          >
                            {item}
                          </button>
                        )
                      ))}
                      <button
                        className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                        disabled={page >= totalPages}
                        onClick={() => setPage(p => p + 1)}
                      >
                        下一页
                      </button>
                      <button
                        className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                        disabled={page >= totalPages}
                        onClick={() => setPage(totalPages)}
                      >
                        末页
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
            ) : manageView === 'account' ? (
              accountNotesBusy && accountNotesData.items.length === 0 ? (
                <InlineSpinner label="账号帖子加载中..." />
              ) : accountNotesData.items.length === 0 ? (
                <div className="grid place-items-center rounded-[24px] border border-dashed border-slate-200 bg-white/55 py-20 text-sm text-slate-400">
                  暂无账号帖子数据，先点击“创作中心主同步”建立帖子主记录
                </div>
              ) : (
                <div className="flex h-full min-h-0 flex-col">
                  {accountNotesBusy && (
                    <div className="mb-3 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white/85 px-4 py-2 text-xs font-semibold text-slate-500 shadow-sm">
                      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" />
                      {isAccountNotesRendering ? '正在渲染账号帖子...' : '正在刷新账号帖子...'}
                    </div>
                  )}
                  {accountBatchSelectMode && (
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-indigo-200 bg-indigo-50/80 px-4 py-3 shadow-[0_10px_24px_rgba(99,102,241,0.12)]">
                      <div className="flex items-center gap-3">
                        <span className="inline-flex h-8 min-w-8 items-center justify-center rounded-full bg-indigo-600 px-2 text-xs font-bold text-white">
                          {selectedAccountNoteCount}
                        </span>
                        <div className="text-sm">
                          <div className="font-semibold text-slate-900">批量标记模式</div>
                          <div className="text-xs text-slate-500">先勾选帖子，再选择目标标记并确认</div>
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <select
                          className="h-9 min-w-[136px] rounded-xl border border-indigo-200 bg-white px-3 text-xs font-semibold text-slate-700 outline-none transition-all focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                          value={batchAccountAiOrigin}
                          onChange={(e) => setBatchAccountAiOrigin(e.target.value as typeof batchAccountAiOrigin)}
                        >
                          <option value="manual">纯手工</option>
                          <option value="text_ai">仅文案 AI</option>
                          <option value="image_ai">仅图片 AI</option>
                          <option value="all_ai">图文都 AI</option>
                        </select>
                        <button
                          className="h-9 rounded-xl bg-slate-900 px-4 text-xs font-semibold text-white transition-all hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-45"
                          onClick={handleBatchUpdateAccountNoteAiOrigin}
                          disabled={accountNoteBatchUpdating || selectedAccountNoteCount === 0}
                        >
                          {accountNoteBatchUpdating ? '处理中...' : '确认批量标记'}
                        </button>
                        <button
                          className="h-9 rounded-xl border border-transparent px-3 text-xs font-semibold text-slate-500 transition-all hover:bg-white/80 hover:text-slate-700"
                          onClick={() => {
                            setSelectedAccountNoteIds([]);
                            setAccountBatchSelectMode(false);
                          }}
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  )}
                  <div className="min-h-0 flex-1 overflow-auto rounded-[24px] border border-slate-200/90 bg-white/85 shadow-[0_14px_36px_rgba(79,103,146,0.1)]">
                    <table className="w-full min-w-[1500px] text-sm">
                      <thead className="sticky top-0 z-10 bg-slate-50/95 text-slate-600 backdrop-blur">
                        <tr>
                          {accountBatchSelectMode && (
                            <th className="px-4 py-3 text-center font-medium">
                              <input
                                type="checkbox"
                                className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                                checked={allCurrentPageAccountNotesSelected}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    setSelectedAccountNoteIds(currentPageAccountNoteIds);
                                  } else {
                                    setSelectedAccountNoteIds([]);
                                  }
                                }}
                              />
                            </th>
                          )}
                          <th className="px-4 py-3 text-left font-medium">帖子标题 / 链接</th>
                          <th className="px-4 py-3 text-left font-medium">发布账号</th>
                          {isAdmin && <th className="px-4 py-3 text-left font-medium">获取链接账号 / 今日浏览</th>}
                          <th className="px-4 py-3 text-left font-medium">小红书号</th>
                          <th className="px-4 py-3 text-left font-medium">发布时间</th>
                          <th className="px-4 py-3 text-center font-medium">曝光</th>
                          <th className="px-4 py-3 text-center font-medium">浏览</th>
                          <th className="px-4 py-3 text-center font-medium">封面点击率</th>
                          <th className="px-4 py-3 text-center font-medium">点赞</th>
                          <th className="px-4 py-3 text-center font-medium">评论</th>
                          <th className="px-4 py-3 text-center font-medium">收藏</th>
                          <th className="px-4 py-3 text-center font-medium">转发</th>
                          <th className="px-4 py-3 text-left font-medium">标记</th>
                          <th className="px-4 py-3 text-left font-medium">一级标签</th>
                          <th className="px-4 py-3 text-left font-medium">二级标签</th>
                          {isAdmin && <th className="px-4 py-3 text-center font-medium">操作</th>}
                        </tr>
                      </thead>
                      <tbody>
                        {accountNotesData.items.map((note) => {
                          const selected = selectedAccountNoteIds.includes(note.id);
                          return (
                            <tr
                              key={note.id}
                              className={`border-t border-slate-100 hover:bg-indigo-50/35 ${accountBatchSelectMode ? 'cursor-pointer' : ''} ${selected ? 'bg-indigo-50/55' : ''}`}
                              onClick={(event) => {
                                if (!accountBatchSelectMode || isInteractiveAccountNoteTarget(event.target)) return;
                                toggleAccountNoteSelection(note.id);
                              }}
                            >
                              {accountBatchSelectMode && (
                                <td className="px-4 py-3 text-center">
                                  <input
                                    type="checkbox"
                                    className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                                    checked={selected}
                                    onChange={() => {
                                      toggleAccountNoteSelection(note.id);
                                    }}
                                  />
                                </td>
                              )}
                              <td className="px-4 py-3">
                                <div className="flex items-start gap-3">
                                  <div className="h-24 w-24 shrink-0 overflow-hidden rounded-[24px] border border-slate-200 bg-slate-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
                                    {note.cover_image_url ? (
                                      <AccountNoteCoverThumb
                                        src={note.cover_image_url}
                                        title={note.title || note.feed_id || '待补帖子 ID'}
                                        onPreview={() => setAccountNotePreview({ url: normalizeAccountNoteCoverUrl(note.cover_image_url), title: note.title || note.feed_id || '待补帖子 ID' })}
                                      />
                                    ) : (
                                      <div className="flex h-full w-full items-center justify-center bg-[radial-gradient(circle_at_top,_rgba(99,102,241,0.18),_rgba(148,163,184,0.08)_55%,_rgba(255,255,255,0.95))] text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                                        XHS
                                      </div>
                                    )}
                                  </div>
                                  <div className="min-w-0">
                                    <div className="max-w-[360px] truncate font-medium text-slate-900">
                                      {note.post_url ? (
                                        <button
                                          type="button"
                                          onClick={() => handleOpenAccountNoteLink(note)}
                                          className="text-left text-indigo-600 hover:underline"
                                        >
                                          {note.title || note.feed_id}
                                        </button>
                                      ) : (
                                        note.title || note.feed_id
                                      )}
                                    </div>
                                    <div className="mt-2 max-w-[420px] whitespace-pre-line break-words text-xs leading-5 text-slate-500 line-clamp-2">
                                      {getAccountNoteContentPreview(note)}
                                    </div>
                                    <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                                      <span className={`rounded-full border px-2 py-0.5 font-semibold ${getAccountNoteSourceTone(note)}`}>
                                        {getAccountNoteSourceLabel(note)}
                                      </span>
                                      <span className={`rounded-full border px-2 py-0.5 font-semibold ${getAccountNoteDetailStatusTone(note)}`}>
                                        {note.detail_synced_at ? `详情同步 ${formatAccountNotePublishedAt(note.detail_synced_at)}` : '未同步详情'}
                                      </span>
                                      {isAdmin && (
                                        <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 font-semibold text-sky-700">
                                          今日浏览 {note.today_browse_count ?? 0}
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              </td>
                              <td className="px-4 py-3 text-sm text-slate-700">
                                <div className="font-medium">{note.account_name}</div>
                                <div className="text-xs text-slate-400">{note.profile_nickname || '-'}</div>
                              </td>
                              {isAdmin && (
                                <td className="px-4 py-3 text-sm text-slate-700">
                                  <div className="font-medium">{note.assigned_runner_account_name || '待分配'}</div>
                                  <div className="text-xs text-slate-400">
                                    {note.assignment_updated_at ? `获取于 ${formatAccountNotePublishedAt(note.assignment_updated_at)}` : '尚未记录获取链接账号'}
                                  </div>
                                </td>
                              )}
                              <td className="px-4 py-3 text-sm text-slate-600">{note.red_id || '-'}</td>
                              <td className="px-4 py-3 text-sm text-slate-600 whitespace-nowrap">{formatAccountNotePublishedAt(note.published_at)}</td>
                              <td className="px-4 py-3 text-center">{note.exposure_count}</td>
                              <td className="px-4 py-3 text-center">{note.view_count}</td>
                              <td className="px-4 py-3 text-center">{Number(note.cover_click_rate || 0).toFixed(2)}%</td>
                              <td className="px-4 py-3 text-center">{note.liked_count}</td>
                              <td className="px-4 py-3 text-center">{note.comment_count}</td>
                              <td className="px-4 py-3 text-center">{note.collected_count}</td>
                              <td className="px-4 py-3 text-center">{note.share_count}</td>
                              <td className="px-4 py-3">
                                <div className="relative min-w-[180px]" data-ai-origin-menu-root="true">
                                  <button
                                    type="button"
                                    disabled={accountNoteSavingId === note.id}
                                    onClick={() => setOpenAiOriginMenuId((current) => current === note.id ? null : note.id)}
                                    className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-semibold transition-all hover:shadow-sm disabled:cursor-not-allowed disabled:opacity-45 ${getAiOriginBadgeTone(note.ai_origin_type || '')}`}
                                  >
                                    <span className={`h-1.5 w-1.5 rounded-full ${getAiOriginDotTone(note.ai_origin_type || '')} ${getAiOriginDotMotion(note.ai_origin_type || '')}`} />
                                    <span>{note.ai_origin_type ? (AI_ORIGIN_LABELS[note.ai_origin_type] || note.ai_origin_type) : '未设置'}</span>
                                    <span className="text-[10px] text-slate-400">▾</span>
                                  </button>
                                  {openAiOriginMenuId === note.id && (
                                    <div className="absolute left-0 top-[calc(100%+8px)] z-20 w-[180px] rounded-2xl border border-slate-200 bg-white p-1.5 shadow-[0_18px_40px_rgba(15,23,42,0.12)]">
                                      {AI_ORIGIN_ACTIONS.filter((option) => option.value !== '').map((option) => {
                                        const active = (note.ai_origin_type || '') === option.value;
                                        return (
                                          <button
                                            key={`${note.id}-${option.value || 'unset'}`}
                                            type="button"
                                            disabled={accountNoteSavingId === note.id}
                                            onClick={() => handleUpdateAccountNoteAiOrigin(note.id, option.value)}
                                            className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-xs font-semibold transition-all ${
                                              active
                                                ? 'bg-slate-900 text-white'
                                                : option.value === ''
                                                  ? 'text-amber-700 hover:bg-amber-50'
                                                  : 'text-slate-700 hover:bg-slate-50'
                                            } disabled:cursor-not-allowed disabled:opacity-45`}
                                          >
                                            <span>{option.full}</span>
                                            {active && <span className="text-[10px]">✓</span>}
                                          </button>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>
                              </td>
                              <td className="px-4 py-3">
                                {note.primary_content_tag ? (
                                  <span className="inline-flex max-w-[160px] items-center rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-[11px] font-semibold text-violet-700">
                                    {note.primary_content_tag}
                                  </span>
                                ) : (
                                  <span className="text-xs text-slate-300">-</span>
                                )}
                              </td>
                              <td className="px-4 py-3">
                                {note.secondary_content_tag ? (
                                  <span className="inline-flex max-w-[180px] items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-slate-600">
                                    {note.secondary_content_tag}
                                  </span>
                                ) : (
                                  <span className="text-xs text-slate-300">-</span>
                                )}
                              </td>
                              <td className="px-4 py-3 text-center">
                                <div className="flex flex-wrap items-center justify-center gap-1.5">
                                  <button
                                    className="rounded-xl border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600"
                                    onClick={() => setActiveAccountNote(note)}
                                  >
                                    查看详情
                                  </button>
                                  {isAdmin && (
                                    <button
                                      className="rounded-xl border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-600 disabled:cursor-not-allowed disabled:opacity-45"
                                      onClick={() => handleSyncAccountNoteEngagementStats(note.id)}
                                      disabled={accountNoteEngagementSyncingId === note.id}
                                      title="打开该发布账号的创作中心，同步浏览/点赞/评论/收藏/转发"
                                    >
                                      {accountNoteEngagementSyncingId === note.id ? '同步中' : '同步互动'}
                                    </button>
                                  )}
                                  {isAdmin && (
                                    <button
                                      className="rounded-xl border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:cursor-not-allowed disabled:opacity-45"
                                      onClick={() => openAccountNoteSyncDialog(note)}
                                      disabled={accountNoteSyncingId === note.id || !note.feed_id}
                                      title={note.feed_id ? '先选测试账号，再打开该笔记详情，同步这条帖子的点赞/评论/收藏/转发与正文图片' : '等待主页同步补齐帖子 ID 后可用'}
                                    >
                                      {accountNoteSyncingId === note.id ? '同步中' : '选账号同步'}
                                    </button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {totalPages > 1 && (
                    <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
                      <span>第 {page} / {totalPages} 页 · 共 {accountNotesData.total} 条</span>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                          disabled={page <= 1}
                          onClick={() => setPage(1)}
                        >
                          首页
                        </button>
                        <button
                          className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                          disabled={page <= 1}
                          onClick={() => setPage((p) => p - 1)}
                        >
                          上一页
                        </button>
                        {pageNumbers.map((item, idx) => (
                          item === '...' ? (
                            <span key={`ellipsis-account-${idx}`} className="px-1 text-slate-300">...</span>
                          ) : (
                            <button
                              key={`account-${item}`}
                              className={`rounded-xl border px-3 py-1 text-xs font-semibold transition-all ${
                                page === item
                                  ? 'border-indigo-300 bg-indigo-50 text-indigo-600'
                                  : 'border-slate-200 bg-white text-slate-600 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600'
                              }`}
                              onClick={() => setPage(item)}
                            >
                              {item}
                            </button>
                          )
                        ))}
                        <button
                          className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                          disabled={page >= totalPages}
                          onClick={() => setPage((p) => p + 1)}
                        >
                          下一页
                        </button>
                        <button
                          className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                          disabled={page >= totalPages}
                          onClick={() => setPage(totalPages)}
                        >
                          末页
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )
            ) : manageView === 'creative' && creativeReportMode === 'compare' ? (
              creativeCompareLoading ? (
                <InlineSpinner label="标签对比加载中..." />
              ) : !creativeCompareGranularityData || (creativeCompareGranularityData.periods || []).length === 0 ? (
                <div className="grid place-items-center rounded-[24px] border border-dashed border-slate-200 bg-white/55 py-20 text-sm text-slate-400">
                  当前时间范围内暂无可对比的有效标签数据
                </div>
              ) : (
                <div className="space-y-5 pb-6 pr-1">
                  <div className="relative overflow-hidden rounded-[36px] border border-slate-200/90 bg-[linear-gradient(180deg,rgba(250,252,255,0.98),rgba(255,255,255,0.98))] p-5 shadow-[0_24px_70px_rgba(79,103,146,0.12)]">
                    <div className="absolute inset-x-0 top-0 h-52 bg-[radial-gradient(circle_at_top_left,rgba(14,165,233,0.16),transparent_42%),radial-gradient(circle_at_top_right,rgba(245,158,11,0.12),transparent_34%),linear-gradient(180deg,rgba(255,255,255,0),rgba(255,255,255,0.92))]" />
                    <div className="absolute inset-x-10 top-28 h-px bg-[linear-gradient(90deg,transparent,rgba(148,163,184,0.34),transparent)]" />

                    <div className="relative grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(360px,0.9fr)]">
                      <div>
                        <div className="inline-flex items-center gap-2 rounded-full border border-white/90 bg-white/78 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500 shadow-[0_10px_24px_rgba(148,163,184,0.14)] backdrop-blur">
                          <span className="h-1.5 w-1.5 rounded-full bg-sky-500" />
                          Creative Compare Studio
                        </div>
                        <h3 className="mt-4 text-[28px] font-semibold tracking-[-0.04em] text-slate-950">标签对比看板</h3>
                        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
                          这块只看已经打过标签的创意表现，用统一时间区间比较四个标签的规模、效率和私信结果。顶部先看总览，再往下看标签结构、趋势和明细。
                        </p>

                        <div className="mt-5 rounded-[28px] border border-white/90 bg-white/78 p-4 shadow-[0_18px_36px_rgba(148,163,184,0.12)] backdrop-blur">
                          <div className="mb-3 flex items-center justify-between gap-3">
                            <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Overview Metrics</div>
                            <div className="text-xs text-slate-500">当前区间全指标总览</div>
                          </div>
                          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
                          {creativeCompareOverviewStats.map((item) => (
                            <div key={item.key} className="rounded-[22px] border border-white/90 bg-white/84 px-4 py-3 shadow-[0_10px_24px_rgba(148,163,184,0.1)] backdrop-blur">
                              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-400">{item.label}</div>
                              <div className={`mt-2 text-[20px] font-semibold tracking-[-0.04em] ${item.accent}`}>{item.value}</div>
                            </div>
                          ))}
                        </div>
                        </div>
                      </div>

                      <div className="rounded-[30px] border border-slate-200/80 bg-[linear-gradient(145deg,rgba(15,23,42,0.96),rgba(30,41,59,0.94))] p-5 text-white shadow-[0_24px_60px_rgba(15,23,42,0.28)]">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-white/45">区间总数据</div>
                            <div className="mt-2 text-xl font-semibold tracking-[-0.03em]">当前所选时间范围整体汇总</div>
                          </div>
                          <div className="rounded-full border border-white/12 bg-white/10 px-3 py-1 text-[11px] font-semibold text-white/70 backdrop-blur">
                            {creativeCompareData?.start_date} 至 {creativeCompareData?.end_date}
                          </div>
                        </div>
                        <div className="mt-5 grid grid-cols-2 gap-3">
                          {creativeCompareRangeSummaryStats.map((item) => (
                            <div key={`range-summary-${item.key}`} className="rounded-[22px] border border-white/10 bg-white/8 px-4 py-3">
                              <div className="text-[11px] uppercase tracking-[0.18em] text-white/45">{item.label}</div>
                              <div className="mt-2 text-lg font-semibold text-white">{item.value}</div>
                            </div>
                          ))}
                        </div>
                        <div className="mt-4 grid grid-cols-2 gap-3">
                          <div className="rounded-[22px] border border-white/10 bg-white/8 px-4 py-3">
                            <div className="text-[11px] uppercase tracking-[0.18em] text-white/45">按天走势</div>
                            <div className="mt-2 text-sm font-semibold text-white/90">{creativeCompareGranularityData.periods.length} 个周期节点</div>
                          </div>
                          <div className="rounded-[22px] border border-white/10 bg-white/8 px-4 py-3">
                            <div className="text-[11px] uppercase tracking-[0.18em] text-white/45">标签参与数</div>
                            <div className="mt-2 text-sm font-semibold text-white/90">{creativeCompareTagCards.length} 个有效标签</div>
                          </div>
                        </div>
                      </div>
                    </div>

                  </div>

                  <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-4">
                    {creativeCompareTagCards.map((card, index) => {
                      const surface = CREATIVE_COMPARE_CARD_SURFACES[card.key] || CREATIVE_COMPARE_CARD_SURFACES.manual;
                      const style = CREATIVE_COMPARE_TAG_STYLES[card.key] || CREATIVE_COMPARE_TAG_STYLES.manual;
                      return (
                        <div key={card.key} className={`overflow-hidden rounded-[30px] border ${surface.shell} ${surface.glow}`}>
                          <div className={`relative overflow-hidden px-5 pb-5 pt-5 ${surface.hero}`}>
                            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(255,255,255,0.24),transparent_42%)]" />
                            <div className="relative flex items-start justify-between gap-3">
                              <div>
                                <div className="inline-flex items-center gap-2 rounded-full border border-white/18 bg-white/10 px-3 py-1 text-[11px] font-semibold backdrop-blur">
                                  <span className="text-white/70">#{String(index + 1).padStart(2, '0')}</span>
                                  <span className="h-2 w-2 rounded-full bg-white/80" />
                                  <span>{card.label}</span>
                                </div>
                                <div className="mt-4 text-[11px] uppercase tracking-[0.18em] text-white/58">{getCreativeCompareMetricLabel(creativeCompareMetric)}</div>
                                <div className="mt-1 text-[28px] font-semibold tracking-[-0.04em] text-white">
                                  {formatCreativeCompareValue(creativeCompareMetric, card.selectedMetricValue)}
                                </div>
                              </div>
                              <div className="rounded-[20px] border border-white/12 bg-white/10 px-3 py-2 text-right backdrop-blur">
                                <div className="text-[10px] uppercase tracking-[0.18em] text-white/58">帖子总量</div>
                                <div className="mt-1 text-xl font-semibold text-white">{formatCreativeCompareValue('note_count', card.metrics?.note_count ?? 0)}</div>
                              </div>
                            </div>

                            <div className="mt-4">
                              <div className="flex items-center justify-between text-[11px] text-white/64">
                                <span>相对强度</span>
                                <span>{Math.round(card.ratio * 100)}%</span>
                              </div>
                              <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/12">
                                <div
                                  className="h-full rounded-full bg-white/90 shadow-[0_0_18px_rgba(255,255,255,0.34)]"
                                  style={{ width: `${Math.max(6, Math.round(card.ratio * 100))}%` }}
                                />
                              </div>
                            </div>

                            <div className="mt-4 grid grid-cols-3 gap-2">
                              {[
                                { key: 'fee', label: '消费' },
                                { key: 'click', label: '点击' },
                                { key: 'ctr', label: '点击率' },
                              ].map((metric) => (
                                <div key={`${card.key}-${metric.key}`} className="rounded-[18px] border border-white/12 bg-white/10 px-3 py-3 backdrop-blur">
                                  <div className="text-[10px] text-white/62">{metric.label}</div>
                                  <div className="mt-1 text-sm font-semibold text-white">
                                    {formatCreativeCompareValue(metric.key as CreativeCompareMetricKey, card.metrics?.[metric.key] ?? 0)}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>

                          <div className="space-y-3 p-4">
                            <div className="rounded-[22px] border border-white/80 bg-white/86 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.72)]">
                              <div className="mb-3 flex items-center justify-between">
                                <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">趋势速览</div>
                                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px] font-semibold ${style.chip}`}>
                                  <span className={`h-1.5 w-1.5 rounded-full ${style.soft}`} />
                                  {card.label}
                                </span>
                              </div>
                              <svg viewBox="0 0 212 72" className="h-[72px] w-full overflow-visible">
                                <defs>
                                  <linearGradient id={`spark-gradient-${card.key}`} x1="0%" x2="100%" y1="0%" y2="0%">
                                    <stop offset="0%" stopColor={style.line} stopOpacity="0.45" />
                                    <stop offset="100%" stopColor={style.line} stopOpacity="0.9" />
                                  </linearGradient>
                                </defs>
                                <path d={card.sparklinePath} fill="none" stroke={`url(#spark-gradient-${card.key})`} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            </div>

                            <div className="grid gap-2">
                              {CREATIVE_COMPARE_CARD_METRICS.map((metric) => (
                                <div
                                  key={`${card.key}-${metric.key}`}
                                  className="flex items-center justify-between gap-4 rounded-[18px] border border-slate-200/80 bg-white/84 px-3 py-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]"
                                >
                                  <div className="text-[11px] text-slate-500">{metric.label}</div>
                                  <div className="text-sm font-semibold text-slate-800">
                                    {formatCreativeCompareValue(metric.key, card.metrics?.[metric.key] ?? 0)}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_320px]">
                    <div className="rounded-[32px] border border-slate-200/90 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(247,250,255,0.98))] p-5 shadow-[0_20px_48px_rgba(79,103,146,0.1)]">
                      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                        <div>
                          <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Trend Canvas</div>
                          <div className="mt-1 text-[22px] font-semibold tracking-[-0.03em] text-slate-950">多标签趋势主舞台</div>
                          <div className="mt-1 text-xs text-slate-500">
                            当前指标：{getCreativeCompareMetricLabel(creativeCompareMetric)}，鼠标移到节点上可看四个标签的同期数值。
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {[
                            { key: 'fee', label: '消费' },
                            { key: 'impression', label: '展现' },
                            { key: 'click', label: '点击' },
                            { key: 'ctr', label: '点击率' },
                            { key: 'message_consult', label: '进线' },
                          ].map((metric) => (
                            <button
                              key={`trend-metric-quick-${metric.key}`}
                              type="button"
                              onClick={() => setCreativeCompareMetric(metric.key as CreativeCompareMetricKey)}
                              className={`h-10 rounded-full px-4 text-xs font-semibold transition-all ${
                                creativeCompareMetric === metric.key
                                  ? 'bg-slate-900 text-white shadow-[0_12px_24px_rgba(15,23,42,0.16)]'
                                  : 'border border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-900'
                              }`}
                            >
                              {metric.label}
                            </button>
                          ))}
                          <select
                            className="h-10 min-w-[190px] rounded-full border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 outline-none transition-all focus:border-slate-300 focus:ring-4 focus:ring-slate-100"
                            value={creativeCompareMetric}
                            onChange={(e) => setCreativeCompareMetric(e.target.value as CreativeCompareMetricKey)}
                          >
                            {CREATIVE_COMPARE_METRICS.map((metric) => (
                              <option key={metric.key} value={metric.key}>
                                {metric.label}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                            {creativeCompareTags.map((tag) => (
                              <div
                                key={`legend-${tag.key}`}
                                className={`inline-flex h-9 items-center gap-2 rounded-full border px-3 text-xs font-semibold ${CREATIVE_COMPARE_TAG_STYLES[tag.key]?.chip || 'border-slate-200 bg-slate-50 text-slate-700'}`}
                              >
                                <span className={`h-2 w-2 rounded-full ${CREATIVE_COMPARE_TAG_STYLES[tag.key]?.soft || 'bg-slate-400'}`} />
                                <span>{tag.label}</span>
                              </div>
                            ))}
                      </div>

                        <div className="mt-4 overflow-x-auto rounded-[24px] border border-slate-200/90 bg-white/88 p-3">
                          {(() => {
                            const periods = creativeCompareGranularityData.periods || [];
                            const width = Math.max(920, periods.length * 96);
                            const height = 320;
                            const paddingLeft = 56;
                            const paddingRight = 24;
                            const paddingTop = 24;
                            const paddingBottom = 52;
                            const plotWidth = width - paddingLeft - paddingRight;
                            const plotHeight = height - paddingTop - paddingBottom;
                            const ticks = 4;
                            const hoveredPeriod = creativeCompareHoveredPeriod;
                            const hoveredIndex = hoveredPeriod
                              ? periods.findIndex((period) => period.period_key === hoveredPeriod.period_key)
                              : -1;
                            const hoveredX = hoveredIndex >= 0
                              ? (
                                periods.length === 1
                                  ? paddingLeft + plotWidth / 2
                                  : paddingLeft + (hoveredIndex / Math.max(1, periods.length - 1)) * plotWidth
                              )
                              : null;
                            return (
                              <svg
                                width={width}
                                height={height}
                                viewBox={`0 0 ${width} ${height}`}
                                className="min-w-full"
                                onMouseLeave={() => setCreativeCompareHoveredPeriodKey(null)}
                              >
                                <rect x="0" y="0" width={width} height={height} rx="18" fill="rgba(248,250,252,0.7)" />
                                {Array.from({ length: ticks + 1 }, (_, idx) => {
                                  const ratio = idx / ticks;
                                  const y = paddingTop + plotHeight - ratio * plotHeight;
                                  const value = creativeCompareChartMax * ratio;
                                  return (
                                    <g key={`grid-${idx}`}>
                                      <line
                                        x1={paddingLeft}
                                        y1={y}
                                        x2={width - paddingRight}
                                        y2={y}
                                        stroke="rgba(148,163,184,0.18)"
                                        strokeDasharray={idx === 0 ? '0' : '4 6'}
                                      />
                                      <text x={paddingLeft - 10} y={y + 4} textAnchor="end" fontSize="11" fill="#94a3b8">
                                        {formatCreativeCompareValue(creativeCompareMetric, value)}
                                      </text>
                                    </g>
                                  );
                                })}

                                {creativeCompareTags.map((tag) => {
                                  const style = CREATIVE_COMPARE_TAG_STYLES[tag.key] || CREATIVE_COMPARE_TAG_STYLES.manual;
                                  const points = periods.map((period, index) => {
                                    const value = Number(period.tags?.[tag.key]?.[creativeCompareMetric] ?? 0);
                                    const x = periods.length === 1
                                      ? paddingLeft + plotWidth / 2
                                      : paddingLeft + (index / Math.max(1, periods.length - 1)) * plotWidth;
                                    const y = paddingTop + plotHeight - (value / creativeCompareChartMax) * plotHeight;
                                    return { x, y };
                                  });
                                  const polyline = points.map((point) => `${point.x},${point.y}`).join(' ');
                                  return (
                                    <g key={`series-${tag.key}`}>
                                      <polyline
                                        fill="none"
                                        stroke={style.line}
                                        strokeWidth="3.5"
                                        strokeLinejoin="round"
                                        strokeLinecap="round"
                                        points={polyline}
                                      />
                                      {points.map((point, idx) => (
                                        <g key={`point-${tag.key}-${idx}`}>
                                          <circle cx={point.x} cy={point.y} r="4.5" fill={style.line} />
                                          <circle cx={point.x} cy={point.y} r="8" fill={style.fill} />
                                        </g>
                                      ))}
                                    </g>
                                  );
                                })}

                                {hoveredX !== null && (
                                  <line
                                    x1={hoveredX}
                                    y1={paddingTop}
                                    x2={hoveredX}
                                    y2={paddingTop + plotHeight}
                                    stroke="rgba(79,70,229,0.28)"
                                    strokeDasharray="5 6"
                                  />
                                )}

                                {periods.map((period, index) => {
                                  const x = periods.length === 1
                                    ? paddingLeft + plotWidth / 2
                                    : paddingLeft + (index / Math.max(1, periods.length - 1)) * plotWidth;
                                  const prevX = index === 0
                                    ? paddingLeft
                                    : (
                                      periods.length === 1
                                        ? paddingLeft
                                        : paddingLeft + ((index - 0.5) / Math.max(1, periods.length - 1)) * plotWidth
                                    );
                                  const nextX = index === periods.length - 1
                                    ? width - paddingRight
                                    : (
                                      periods.length === 1
                                        ? width - paddingRight
                                        : paddingLeft + ((index + 0.5) / Math.max(1, periods.length - 1)) * plotWidth
                                    );
                                  return (
                                    <g key={`label-${period.period_key}`}>
                                      <rect
                                        x={prevX}
                                        y={paddingTop}
                                        width={Math.max(18, nextX - prevX)}
                                        height={plotHeight}
                                        fill="transparent"
                                        onMouseEnter={() => setCreativeCompareHoveredPeriodKey(period.period_key)}
                                        onMouseMove={() => setCreativeCompareHoveredPeriodKey(period.period_key)}
                                      />
                                      <line x1={x} y1={paddingTop + plotHeight} x2={x} y2={paddingTop + plotHeight + 6} stroke="rgba(148,163,184,0.4)" />
                                      <text
                                        x={x}
                                        y={height - 18}
                                        textAnchor="middle"
                                        fontSize="11"
                                        fill="#64748b"
                                      >
                                        {period.period_label}
                                      </text>
                                    </g>
                                  );
                                })}

                                {hoveredPeriod && hoveredX !== null && (
                                  <foreignObject
                                    x={Math.max(14, Math.min(width - 280, hoveredX - 128))}
                                    y={14}
                                    width={256}
                                    height={188}
                                  >
                                    <div className="rounded-2xl border border-slate-200/90 bg-white/96 p-3 shadow-[0_16px_32px_rgba(15,23,42,0.14)] backdrop-blur">
                                      <div className="text-xs font-semibold text-slate-900">{hoveredPeriod.period_label}</div>
                                      <div className="mt-1 text-[11px] text-slate-400">
                                        {hoveredPeriod.period_start} 至 {hoveredPeriod.period_end}
                                      </div>
                                      <div className="mt-3 space-y-1.5">
                                        {creativeCompareTags.map((tag) => (
                                          <div key={`tooltip-${tag.key}`} className="flex items-center justify-between gap-3 text-[11px]">
                                            <div className="flex items-center gap-2 text-slate-600">
                                              <span className={`h-2 w-2 rounded-full ${CREATIVE_COMPARE_TAG_STYLES[tag.key]?.soft || 'bg-slate-400'}`} />
                                              <span>{tag.label}</span>
                                            </div>
                                            <span className="font-semibold text-slate-900">
                                              {formatCreativeCompareValue(
                                                creativeCompareMetric,
                                                hoveredPeriod.tags?.[tag.key]?.[creativeCompareMetric] ?? 0,
                                              )}
                                            </span>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  </foreignObject>
                                )}
                              </svg>
                            );
                          })()}
                        </div>
                    </div>

                    <div className="rounded-[32px] border border-slate-200/90 bg-white/90 p-5 shadow-[0_20px_48px_rgba(79,103,146,0.1)]">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Leaderboard</div>
                      <div className="mt-1 text-[22px] font-semibold tracking-[-0.03em] text-slate-950">标签排名</div>
                      <div className="mt-1 text-xs leading-5 text-slate-500">按当前指标实时排序，方便你快速看到哪个标签正在领跑。</div>

                      <div className="mt-5 space-y-3">
                        {creativeCompareTagCards.map((card, index) => (
                          <div key={`rank-${card.key}`} className="rounded-[22px] border border-slate-200/90 bg-slate-50/80 p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="flex items-center gap-3">
                                <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white text-sm font-semibold text-slate-700 shadow-sm">
                                  {index + 1}
                                </div>
                                <div>
                                  <div className="text-sm font-semibold text-slate-900">{card.label}</div>
                                  <div className="mt-1 text-[11px] text-slate-400">帖子 {formatCreativeCompareValue('note_count', card.metrics?.note_count ?? 0)}</div>
                                </div>
                              </div>
                              <div className="text-right">
                                <div className="text-sm font-semibold text-slate-900">
                                  {formatCreativeCompareValue(creativeCompareMetric, card.selectedMetricValue)}
                                </div>
                                <div className="mt-1 text-[11px] text-slate-400">{getCreativeCompareMetricLabel(creativeCompareMetric)}</div>
                              </div>
                            </div>
                            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white">
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${Math.max(6, Math.round(card.ratio * 100))}%`,
                                  backgroundColor: CREATIVE_COMPARE_TAG_STYLES[card.key]?.line || '#64748b',
                                }}
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-4 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
                    <div className="rounded-[30px] border border-slate-200/90 bg-white/92 p-4 shadow-[0_18px_40px_rgba(79,103,146,0.1)]">
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Matrix</div>
                        <div className="mt-1 text-lg font-semibold tracking-[-0.02em] text-slate-950">显著对比表</div>
                        <div className="mt-1 text-xs text-slate-500">横向看同一天四个标签在当前指标上的差异和总量。</div>
                      </div>
                      <div className="mt-4 overflow-auto rounded-[22px] border border-slate-200/90 bg-white">
                        <table className="w-full min-w-[820px] text-sm">
                          <thead className="bg-slate-50/95 text-slate-600">
                            <tr>
                              <th className="sticky left-0 bg-slate-50/95 px-4 py-3 text-left font-medium">日期</th>
                              {creativeCompareTags.map((tag) => (
                                <th key={`pivot-${tag.key}`} className="px-4 py-3 text-right font-medium">{tag.label}</th>
                              ))}
                              <th className="px-4 py-3 text-right font-medium">合计</th>
                            </tr>
                          </thead>
                          <tbody>
                            {creativeCompareGranularityData.periods.map((period) => {
                              const overall = creativeCompareTags.reduce((sum, tag) => sum + Number(period.tags?.[tag.key]?.[creativeCompareMetric] ?? 0), 0);
                              return (
                                <tr key={`pivot-row-${period.period_key}`} className="border-t border-slate-100 hover:bg-slate-50/80">
                                  <td className="sticky left-0 bg-white px-4 py-3 font-medium text-slate-800">{period.period_label}</td>
                                  {creativeCompareTags.map((tag) => (
                                    <td key={`pivot-cell-${period.period_key}-${tag.key}`} className="px-4 py-3 text-right text-slate-700">
                                      {formatCreativeCompareValue(creativeCompareMetric, period.tags?.[tag.key]?.[creativeCompareMetric] ?? 0)}
                                    </td>
                                  ))}
                                  <td className="px-4 py-3 text-right font-semibold text-slate-900">
                                    {formatCreativeCompareValue(creativeCompareMetric, overall)}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <div className="rounded-[30px] border border-slate-200/90 bg-white/92 p-4 shadow-[0_18px_40px_rgba(79,103,146,0.1)]">
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Ledger</div>
                        <div className="mt-1 text-lg font-semibold tracking-[-0.02em] text-slate-950">标签聚合明细</div>
                        <div className="mt-1 text-xs text-slate-500">按天、按标签把全部指标展开，适合核数和精细对照。</div>
                      </div>
                      <div className="mt-4 overflow-auto rounded-[22px] border border-slate-200/90 bg-white">
                        <table className="w-full min-w-[2400px] text-sm">
                          <thead className="bg-slate-50/95 text-slate-600">
                            <tr>
                              <th className="sticky left-0 bg-slate-50/95 px-4 py-3 text-left font-medium">日期</th>
                              <th className="sticky left-[112px] bg-slate-50/95 px-4 py-3 text-left font-medium">标签</th>
                              {CREATIVE_COMPARE_METRICS.map((metric) => (
                                <th key={`detail-head-${metric.key}`} className="px-4 py-3 text-right font-medium">{metric.label}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {creativeCompareDetailRows.map((item) => (
                              <tr key={`${item.period_key}-${item.tag_key}`} className="border-t border-slate-100 hover:bg-slate-50/80">
                                <td className="sticky left-0 bg-white px-4 py-3 font-medium text-slate-800">{item.period_label}</td>
                                <td className="sticky left-[112px] bg-white px-4 py-3">
                                  <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-semibold ${CREATIVE_COMPARE_TAG_STYLES[item.tag_key]?.chip || 'border-slate-200 bg-slate-50 text-slate-700'}`}>
                                    <span className={`h-2 w-2 rounded-full ${CREATIVE_COMPARE_TAG_STYLES[item.tag_key]?.soft || 'bg-slate-400'}`} />
                                    {item.tag_label}
                                  </span>
                                </td>
                                {CREATIVE_COMPARE_METRICS.map((metric) => (
                                  <td key={`${item.period_key}-${item.tag_key}-${metric.key}`} className="px-4 py-3 text-right text-slate-700">
                                    {formatCreativeCompareValue(metric.key, item.metrics?.[metric.key] ?? 0)}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                </div>
              )
            ) : reportLoading ? (
              <InlineSpinner label="报表加载中..." />
            ) : reportRows.length === 0 ? (
              <div className="space-y-2">
                <div className="grid place-items-center rounded-[24px] border border-dashed border-slate-200 bg-white/55 py-16 text-sm text-slate-400">报表暂无数据</div>
                {(reportData?.items || []).some((x) => x.error) && (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
                    {(reportData?.items || []).filter((x) => x.error).map((x) => `${x.account_name}: ${x.error}`).join('；')}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex h-full min-h-0 flex-col">
                <div className="min-h-0 flex-1 overflow-auto rounded-[24px] border border-slate-200/90 bg-white/85 shadow-[0_14px_36px_rgba(79,103,146,0.1)]">
                  <table
                    className={`w-full text-sm ${
                      manageView === 'creative'
                        ? 'min-w-[1320px]'
                        : manageView === 'simple_note' || manageView === 'standard_note'
                          ? 'min-w-[2160px]'
                        : manageView === 'simple' || manageView === 'standard'
                          ? 'min-w-[1880px]'
                          : 'min-w-[1320px]'
                    }`}
                  >
                    <thead className="sticky top-0 z-10 bg-slate-50/95 text-slate-600 backdrop-blur">
                      <tr>
                        {reportColumns.map((col) => (
                          <th key={col.key} className={`px-4 py-3 text-left font-medium ${getReportColumnCellClass(manageView, col.key)}`}>{col.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {reportRows.map((row, idx) => (
                        <tr key={idx} className="border-t border-slate-100 hover:bg-indigo-50/35">
                          {reportColumns.map((col) => (
                            <td key={`${idx}-${col.key}`} className={`px-4 py-3 align-top text-sm text-slate-700 ${getReportColumnCellClass(manageView, col.key)}`}>
                              {col.key === 'creativity_image' || col.key === 'note_image' ? (
                                (() => {
                                  const imageUrl = normalizeCreativeImageUrl(col.getValue(row));
                                  const imageTitle = String(row.note_title || row.note_material || row.campaign_name || '笔记图片');
                                  return imageUrl ? (
                                    <button
                                      type="button"
                                      className="inline-flex"
                                      onClick={() => setAccountNotePreview({
                                        url: imageUrl,
                                        title: imageTitle,
                                      })}
                                    >
                                      <span className="flex h-24 w-24 items-center justify-center overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 shadow-sm transition-all hover:scale-[1.03] hover:shadow-md">
                                        <img
                                          src={imageUrl}
                                          alt={imageTitle}
                                          className="h-full w-full object-cover object-center"
                                          referrerPolicy="no-referrer"
                                          loading="lazy"
                                          decoding="async"
                                        />
                                      </span>
                                    </button>
                                  ) : (
                                    <span className="text-xs text-slate-300">-</span>
                                  );
                                })()
                              ) : (
                                <div className={getReportColumnCellClass(manageView, col.key) || 'whitespace-nowrap'}>
                                  {String(col.getValue(row as any) ?? '')}
                                </div>
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {totalPages > 1 && (
                  <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
                    <span>第 {page} / {totalPages} 页 · 共 {currentTotal} 条</span>
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                        disabled={page <= 1}
                        onClick={() => setPage(1)}
                      >
                        首页
                      </button>
                      <button
                        className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                        disabled={page <= 1}
                        onClick={() => setPage((p) => p - 1)}
                      >
                        上一页
                      </button>
                      {pageNumbers.map((item, idx) => (
                        item === '...' ? (
                          <span key={`ellipsis-${idx}`} className="px-1 text-slate-300">...</span>
                        ) : (
                          <button
                            key={item}
                            className={`rounded-xl border px-3 py-1 text-xs font-semibold transition-all ${
                              page === item
                                ? 'border-indigo-300 bg-indigo-50 text-indigo-600'
                                : 'border-slate-200 bg-white text-slate-600 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600'
                            }`}
                            onClick={() => setPage(item)}
                          >
                            {item}
                          </button>
                        )
                      ))}
                      <button
                        className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                        disabled={page >= totalPages}
                        onClick={() => setPage((p) => p + 1)}
                      >
                        下一页
                      </button>
                      <button
                        className="rounded-xl border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                        disabled={page >= totalPages}
                        onClick={() => setPage(totalPages)}
                      >
                        末页
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
            </div>
          </div>
        </section>
        </div>
      </div>

      {accountSyncHistoryOpen && (
        <div
          className="fixed inset-0 z-[81] grid place-items-center bg-slate-950/42 p-4 backdrop-blur-sm"
          onClick={() => setAccountSyncHistoryOpen(false)}
        >
          <div
            className="flex max-h-[calc(100vh-32px)] w-full max-w-4xl flex-col overflow-hidden rounded-[28px] border border-white/80 bg-white p-5 shadow-[0_32px_90px_rgba(15,23,42,0.26)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Sync History</div>
                <h3 className="mt-1 text-xl font-semibold tracking-[-0.02em] text-slate-950">账号主页同步历史</h3>
                <p className="mt-2 text-sm leading-6 text-slate-500">每一轮会保留账号级成功、失败和错误原因。失败账号可单独重跑，不会重复跑已成功账号。</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="h-9 rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition-all hover:bg-slate-50 disabled:opacity-50"
                  onClick={loadAccountSyncHistory}
                  disabled={accountSyncHistoryLoading}
                >
                  {accountSyncHistoryLoading ? '刷新中...' : '刷新'}
                </button>
                <button
                  type="button"
                  className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-lg font-semibold text-slate-500 transition-all hover:bg-slate-200 hover:text-slate-800"
                  onClick={() => setAccountSyncHistoryOpen(false)}
                  aria-label="关闭同步历史"
                >
                  ×
                </button>
              </div>
            </div>

            <div className="mt-5 min-h-0 flex-1 overflow-y-auto pr-1">
              {accountSyncHistoryLoading && accountSyncHistory.length === 0 ? (
                <div className="grid min-h-44 place-items-center text-sm text-slate-400">正在读取同步历史...</div>
              ) : accountSyncHistory.length === 0 ? (
                <div className="grid min-h-44 place-items-center rounded-2xl border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-400">还没有同步历史。发起一次创作者中心主同步、主页补充或详情补充后会显示在这里。</div>
              ) : (
                <div className="space-y-3">
                  {accountSyncHistory.map((run) => {
                    const kindLabel = run.sync_kind === 'posts' ? '主页帖子补充' : run.sync_kind === 'engagement' ? '创作中心主同步' : '帖子详情补充';
                    const canRetry = run.summary.failed > 0;
                    return (
                      <section key={`account-sync-history-${run.id}`} className="overflow-hidden rounded-[22px] border border-slate-200 bg-slate-50/70">
                        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-semibold text-slate-900">{kindLabel}</span>
                              <span className={`rounded-full border px-2 py-0.5 text-[11px] font-bold ${getAccountSyncJobStatusTone(run.status)}`}>{getAccountSyncJobStatusLabel(run.status)}</span>
                              {run.source === 'retry_failed' && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">失败项重跑</span>}
                            </div>
                            <div className="mt-1 text-xs text-slate-400">{formatAccountSyncJobTime(run.created_at)} · 成功 {run.summary.succeeded} · 失败 {run.summary.failed} · 已取消 {run.summary.cancelled ?? 0} · 进行中 {run.summary.running}</div>
                          </div>
                          {canRetry && (
                            <button
                              type="button"
                              className="h-9 rounded-xl border border-rose-200 bg-rose-50 px-3 text-xs font-semibold text-rose-700 transition-all hover:bg-rose-100 disabled:opacity-50"
                              onClick={() => handleRetryFailedAccountSyncRun(run.id)}
                              disabled={accountSyncHistoryRetryingId === run.id}
                            >
                              {accountSyncHistoryRetryingId === run.id ? '下发中...' : `重跑失败账号 (${run.summary.failed})`}
                            </button>
                          )}
                        </div>
                        {run.items.length > 0 ? (
                          <div className="max-h-56 divide-y divide-slate-200 overflow-y-auto bg-white">
                            {run.items.map((item) => (
                              <div key={`account-sync-history-item-${item.id}`} className="flex items-center justify-between gap-3 px-4 py-2.5 text-xs">
                                <div className="min-w-0">
                                  <div className="truncate font-semibold text-slate-700">{item.account_name}</div>
                                  {(item.error || item.message) && <div className={`mt-0.5 truncate ${item.status === 'failed' ? 'text-rose-600' : 'text-slate-400'}`}>{item.error || item.message}</div>}
                                </div>
                                <span className={`shrink-0 rounded-full border px-2 py-0.5 font-semibold ${getAccountSyncJobStatusTone(item.status === 'succeeded' ? 'succeeded' : item.status === 'failed' ? 'failed' : 'running')}`}>
                                  {item.status === 'succeeded' ? '成功' : item.status === 'failed' ? '失败' : item.status === 'running' ? '进行中' : '排队中'}
                                </span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="px-4 py-3 text-xs leading-5 text-slate-500">此类任务按帖子执行，当前批次已记录任务结果；账号级成功/失败明细适用于主页帖子和互动同步。</div>
                        )}
                      </section>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {accountSyncProgressPanel && activeAccountSyncPanelJob && (
        <div
          className="fixed inset-0 z-[81] grid place-items-center bg-slate-950/42 p-4 backdrop-blur-sm"
          onClick={() => setAccountSyncProgressPanel(null)}
        >
          <div
            className="w-full max-w-xl rounded-[28px] border border-white/80 bg-white p-5 shadow-[0_32px_90px_rgba(15,23,42,0.26)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Sync Progress</div>
                <h3 className="mt-1 text-xl font-semibold tracking-[-0.02em] text-slate-950">
                  {accountSyncProgressPanel === 'account_notes'
                    ? '账号帖子同步进度'
                    : accountSyncProgressPanel === 'account_engagement'
                      ? '创作者中心主同步进度'
                      : '账号详情同步进度'}
                </h3>
                <p className="mt-2 text-sm leading-6 text-slate-500">
                  {activeAccountSyncPanelJob.progress?.detail || activeAccountSyncPanelJob.message || '任务已创建，等待最新进度。'}
                </p>
              </div>
              <button
                type="button"
                className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-lg font-semibold text-slate-500 transition-all hover:bg-slate-200 hover:text-slate-800"
                onClick={() => setAccountSyncProgressPanel(null)}
                aria-label="关闭进度弹窗"
              >
                ×
              </button>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${getAccountSyncJobStatusTone(activeAccountSyncPanelJob.status)}`}>
                {getAccountSyncJobStatusLabel(activeAccountSyncPanelJob.status)}
              </span>
              <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-500">
                Job ID · {activeAccountSyncPanelJob.job_id.slice(0, 8)}
              </span>
              {activeAccountSyncPanelJob.progress?.runner_name && (
                <span className="inline-flex items-center rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-600">
                  当前账号 · {activeAccountSyncPanelJob.progress.runner_name}
                </span>
              )}
              {['queued', 'running'].includes(activeAccountSyncPanelJob.status) && (
                <button
                  type="button"
                  className="inline-flex items-center rounded-full border border-rose-200 bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700 transition-all hover:bg-rose-100"
                  onClick={handleCancelAccountSyncJob}
                >
                  中止任务
                </button>
              )}
            </div>

            <div className="mt-5 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between gap-3 text-sm font-semibold text-slate-700">
                <span>整体进度</span>
                <span>{getAccountSyncJobPercent(activeAccountSyncPanelJob)}%</span>
              </div>
              <div className="mt-3 h-3 overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full rounded-full bg-[linear-gradient(90deg,#0f172a_0%,#4f46e5_55%,#38bdf8_100%)] transition-all duration-500"
                  style={{ width: `${getAccountSyncJobPercent(activeAccountSyncPanelJob)}%` }}
                />
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl border border-white bg-white px-3 py-3">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">已处理</div>
                  <div className="mt-1 text-2xl font-semibold text-slate-950">
                    {activeAccountSyncPanelJob.progress?.current ?? 0}
                    <span className="ml-1 text-sm font-medium text-slate-400">/ {activeAccountSyncPanelJob.progress?.total ?? 0}</span>
                  </div>
                </div>
                <div className="rounded-2xl border border-white bg-white px-3 py-3">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                    {accountSyncProgressPanel === 'account_notes'
                      ? '已同步账号'
                      : accountSyncProgressPanel === 'account_engagement'
                        ? '已同步账号 / 互动'
                      : '成功 / 失败'}
                  </div>
                  <div className="mt-1 text-2xl font-semibold text-slate-950">
                    {accountSyncProgressPanel === 'account_notes'
                      ? (activeAccountSyncPanelJob.progress?.synced_accounts ?? (activeAccountSyncPanelJob.result as { synced_accounts?: number } | null)?.synced_accounts ?? 0)
                      : accountSyncProgressPanel === 'account_engagement'
                        ? `${activeAccountSyncPanelJob.progress?.synced_accounts ?? (activeAccountSyncPanelJob.result as { synced_accounts?: number } | null)?.synced_accounts ?? 0} / ${activeAccountSyncPanelJob.progress?.metric_synced_notes ?? (activeAccountSyncPanelJob.result as { metric_synced_notes?: number } | null)?.metric_synced_notes ?? 0}`
                      : `${activeAccountSyncPanelJob.progress?.synced_notes ?? (activeAccountSyncPanelJob.result as { synced_notes?: number } | null)?.synced_notes ?? 0} / ${activeAccountSyncPanelJob.progress?.failed_notes ?? (activeAccountSyncPanelJob.result as { failed_notes?: number } | null)?.failed_notes ?? 0}`}
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {accountSyncProgressPanel === 'account_notes' ? (
                <>
                  <div className="rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-600">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">已补齐 / 待主数据</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {activeAccountSyncPanelJob.progress?.updated_notes ?? (activeAccountSyncPanelJob.result as { updated_notes?: number } | null)?.updated_notes ?? 0}
                      <span className="mx-1 text-slate-300">/</span>
                      {activeAccountSyncPanelJob.progress?.deferred_homepage_notes ?? (activeAccountSyncPanelJob.result as { deferred_homepage_notes?: number } | null)?.deferred_homepage_notes ?? 0}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-600">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">当前主页</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {activeAccountSyncPanelJob.progress?.account_name || activeAccountSyncPanelJob.message || '-'}
                    </div>
                  </div>
                </>
              ) : accountSyncProgressPanel === 'account_engagement' ? (
                <>
                  <div className="rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-600">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">新增主记录 / 更新互动</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {activeAccountSyncPanelJob.progress?.created_notes ?? (activeAccountSyncPanelJob.result as { created_notes?: number } | null)?.created_notes ?? 0}
                      <span className="mx-1 text-slate-300">/</span>
                      {activeAccountSyncPanelJob.progress?.updated_notes ?? (activeAccountSyncPanelJob.result as { updated_notes?: number } | null)?.updated_notes ?? 0}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-600">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">当前账号</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {activeAccountSyncPanelJob.progress?.account_name || activeAccountSyncPanelJob.message || '-'}
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-600">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">命中 / 跳过</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      {activeAccountSyncPanelJob.progress?.matched_notes ?? (activeAccountSyncPanelJob.result as { matched_notes?: number } | null)?.matched_notes ?? 0}
                      <span className="mx-1 text-slate-300">/</span>
                      {activeAccountSyncPanelJob.progress?.skipped_notes ?? (activeAccountSyncPanelJob.result as { skipped_notes?: number } | null)?.skipped_notes ?? 0}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-600">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">轮次 / 环境</div>
                    <div className="mt-1 font-semibold text-slate-900">
                      第 {activeAccountSyncPanelJob.progress?.round ?? 1} 轮
                      <span className="mx-1 text-slate-300">·</span>
                      {activeAccountSyncPanelJob.progress?.runner_index ?? 1}/{activeAccountSyncPanelJob.progress?.runner_count ?? 1}
                    </div>
                  </div>
                </>
              )}
            </div>

            <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-xs leading-6 text-slate-500">
              <div>开始时间：{formatAccountSyncJobTime(activeAccountSyncPanelJob.started_at || activeAccountSyncPanelJob.created_at)}</div>
              <div>最近更新：{formatAccountSyncJobTime(activeAccountSyncPanelJob.progress?.updated_at || activeAccountSyncPanelJob.updated_at)}</div>
              {activeAccountSyncPanelJob.finished_at && <div>完成时间：{formatAccountSyncJobTime(activeAccountSyncPanelJob.finished_at)}</div>}
              {activeAccountSyncPanelJob.error && <div className="text-rose-600">错误信息：{activeAccountSyncPanelJob.error}</div>}
            </div>
            {activeAccountSyncPanelJob.history_run_id && !['queued', 'running', 'cancelling'].includes(activeAccountSyncPanelJob.status) && (
              <button
                type="button"
                className="mt-4 h-10 w-full rounded-xl border border-indigo-200 bg-indigo-50 px-4 text-sm font-semibold text-indigo-700 transition-all hover:bg-indigo-100"
                onClick={() => {
                  setAccountSyncProgressPanel(null);
                  setAccountSyncHistoryOpen(true);
                }}
              >
                查看账号成功 / 失败明细
              </button>
            )}
          </div>
        </div>
      )}

      {activeAccountNote && (
        <AccountNoteDetailModal
          note={activeAccountNote}
          onClose={() => setActiveAccountNote(null)}
          onPreview={(payload) => setAccountNotePreview(payload)}
        />
      )}

      {accountNoteSyncDialog && (
        <div
          className="fixed inset-0 z-[82] grid place-items-center bg-slate-950/42 p-4 backdrop-blur-sm"
          onClick={() => setAccountNoteSyncDialog(null)}
        >
          <div
            className="w-full max-w-lg rounded-[28px] border border-white/80 bg-white p-5 shadow-[0_32px_90px_rgba(15,23,42,0.26)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Sync Runner</div>
                <h3 className="mt-1 text-xl font-semibold tracking-[-0.02em] text-slate-950">选择同步测试账号</h3>
                <p className="mt-2 text-sm leading-6 text-slate-500">
                  这次同步会用你选中的测试账号去打开帖子详情并更新数据。
                </p>
                <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
                  当前帖子：<span className="font-semibold text-slate-700">{accountNoteSyncDialog.noteTitle}</span>
                </div>
              </div>
              <button
                type="button"
                className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-lg font-semibold text-slate-500 transition-all hover:bg-slate-200 hover:text-slate-800"
                onClick={() => setAccountNoteSyncDialog(null)}
                aria-label="关闭测试账号选择框"
              >
                ×
              </button>
            </div>

            <div className="mt-5 grid gap-2">
              {accountSyncRunnerOptions.map((env) => {
                const active = accountNoteSyncDialog.runnerId === env.id;
                return (
                  <button
                    key={`single-account-note-sync-runner-${env.id}`}
                    type="button"
                    onClick={() => setAccountNoteSyncDialog((current) => current ? { ...current, runnerId: env.id } : current)}
                    className={`flex items-center justify-between rounded-2xl border px-3 py-3 text-left transition-all ${
                      active
                        ? 'border-indigo-300 bg-indigo-50 text-indigo-700 shadow-[0_8px_20px_rgba(99,102,241,0.14)]'
                        : 'border-slate-200 bg-white text-slate-700 hover:border-indigo-200 hover:bg-indigo-50/40'
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold">{env.account_name}</span>
                      <span className={`mt-1 block truncate text-[11px] ${active ? 'text-indigo-500' : 'text-slate-400'}`}>{env.shop_id}</span>
                    </span>
                    <span className={`inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1 text-[11px] font-bold ${
                      active ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-400'
                    }`}>
                      {active ? '✓' : env.id}
                    </span>
                  </button>
                );
              })}
            </div>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
              <div className="text-xs text-slate-400">
                选中后，这条帖子会只用该测试账号执行本次同步。
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-600 transition-all hover:bg-slate-50"
                  onClick={() => setAccountNoteSyncDialog(null)}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="h-10 rounded-xl bg-slate-900 px-5 text-sm font-semibold text-white transition-all hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-45"
                  disabled={!accountNoteSyncDialog.runnerId || accountNoteSyncingId === accountNoteSyncDialog.noteId}
                  onClick={handleConfirmAccountNoteSync}
                >
                  {accountNoteSyncingId === accountNoteSyncDialog.noteId ? '同步中...' : '开始同步'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {accountPostSyncStrategy && (
        <div
          className="fixed inset-0 z-[82] grid place-items-center bg-slate-950/42 p-4 backdrop-blur-sm"
          onClick={() => setAccountPostSyncStrategy(null)}
        >
          <div
            className="w-full max-w-2xl rounded-[28px] border border-white/80 bg-white p-5 shadow-[0_32px_90px_rgba(15,23,42,0.26)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Sync Strategy</div>
                <h3 className="mt-1 text-xl font-semibold tracking-[-0.02em] text-slate-950">主页帖子同步策略</h3>
                <p className="mt-2 text-sm leading-6 text-slate-500">
                  左边先点测试账号，右边再把发布账号明确分配给它。主页任务只补齐创作者中心主记录的帖子 ID、访问令牌、链接、封面和账号信息；主页存在但创作者中心尚未建档的帖子会暂缓，不会直接入库。
                </p>
              </div>
              <button
                type="button"
                className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-lg font-semibold text-slate-500 transition-all hover:bg-slate-200 hover:text-slate-800"
                onClick={() => setAccountPostSyncStrategy(null)}
                aria-label="关闭策略弹窗"
              >
                ×
              </button>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-[0.92fr_1.08fr]">
              <section className="rounded-[24px] border border-slate-200 bg-slate-50/80 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-slate-900">测试账号</div>
                  <button
                    type="button"
                    className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-500 transition-all hover:border-indigo-200 hover:text-indigo-600 disabled:opacity-50"
                    onClick={() => refreshBrowserStatuses(true)}
                    disabled={browserStatusRefreshing}
                  >
                    {browserStatusRefreshing ? '探测中...' : '刷新状态'}
                  </button>
                </div>
                <div className="mt-1 text-xs text-slate-400">先点左侧账号，再去右边分配发布账号；任务会自动启动对应环境。</div>
                <div className="mt-3 grid gap-2">
                  {accountSyncRunnerOptions.map((env) => {
                    const active = accountPostSyncStrategy.activeRunnerId === env.id;
                    const assignedCount = accountPostSyncStrategy.runnerAssignments[String(env.id)]?.length ?? 0;
                    const browserStatus = browserStatusByEnvId.get(env.id);
                    return (
                      <button
                        key={`account-post-sync-runner-${env.id}`}
                        type="button"
                        onClick={() => {
                          setAccountPostSyncStrategy((current) => current ? { ...current, activeRunnerId: env.id } : current);
                          setActiveSyncRunnerInsightId(env.id);
                        }}
                        className={`flex items-center justify-between rounded-2xl border px-3 py-3 text-left transition-all ${
                          active
                            ? 'border-indigo-300 bg-indigo-50 text-indigo-700 shadow-[0_8px_20px_rgba(99,102,241,0.14)]'
                            : 'border-slate-200 bg-white text-slate-700 hover:border-indigo-200 hover:bg-indigo-50/40'
                        }`}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold">{env.account_name}</span>
                          <span className={`mt-1 block truncate text-[11px] ${active ? 'text-indigo-500' : 'text-slate-400'}`}>{env.shop_id}</span>
                          <span className={`mt-1 block text-[11px] ${active ? 'text-indigo-500' : 'text-slate-400'}`}>
                            本轮分配 {assignedCount} 个发布账号
                          </span>
                          <span className={`mt-2 inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold ${getBrowserStatusTone(browserStatus?.browser_status, active)}`}>
                            {getBrowserStatusLabel(browserStatus?.browser_status)}
                          </span>
                        </span>
                        <span className={`inline-flex min-w-10 items-center justify-center rounded-full px-2 py-1 text-[11px] font-bold ${
                          active ? 'bg-indigo-600 text-white' : assignedCount > 0 ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-400'
                        }`}>
                          {assignedCount > 0 ? assignedCount : env.id}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="rounded-[24px] border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-slate-900">
                    {accountPostSyncStrategy.activeRunnerId
                      ? `${accountSyncRunnerOptions.find((env) => env.id === accountPostSyncStrategy.activeRunnerId)?.account_name || '当前测试账号'} 负责的发布账号`
                      : '选择测试账号后分配发布账号'}
                  </div>
                  <div className="text-xs text-slate-400">
                    当前共 {accountPostTargetEnvOptions.length} 个发布账号，不含测试账号
                  </div>
                </div>

                <div className="mt-4">
                  <input
                    type="search"
                    value={accountPostSyncStrategy.accountSearch}
                    onChange={(event) => setAccountPostSyncStrategy((current) => current ? { ...current, accountSearch: event.target.value } : current)}
                    placeholder="搜索发布账号名称或环境 ID"
                    className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm text-slate-900 outline-none transition-all focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                  />
                </div>

                <div className="mt-4 rounded-[20px] border border-slate-200 bg-slate-50/80 p-3">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs leading-6 text-slate-500">
                      勾选决定这次实际要跑哪些发布账号；分配关系会保留，不会因为你本轮少跑几个就被改掉。
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-600 transition-all hover:bg-slate-50"
                        onClick={() => setAccountPostSyncStrategy((current) => current ? {
                          ...current,
                          selectedEnvIds: Array.from(new Set([
                            ...current.selectedEnvIds,
                            ...filteredAccountPostTargetEnvOptions.map((env) => env.id),
                          ])),
                        } : current)}
                      >
                        全选当前结果
                      </button>
                      <button
                        type="button"
                        className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-600 transition-all hover:bg-slate-50"
                        onClick={() => setAccountPostSyncStrategy((current) => current ? { ...current, selectedEnvIds: [] } : current)}
                      >
                        清空勾选
                      </button>
                    </div>
                  </div>
                  <div className="text-xs leading-6 text-slate-500">
                    点左侧小勾是“本轮执行”；右侧按钮才是“改分配”。
                  </div>
                  <div className="mt-3 max-h-[340px] overflow-auto rounded-2xl border border-white bg-white">
                    {!accountPostSyncStrategy.activeRunnerId ? (
                      <div className="px-3 py-4 text-xs text-slate-400">请先在左侧点一个测试账号。</div>
                    ) : filteredAccountPostTargetEnvOptions.length === 0 ? (
                      <div className="px-3 py-4 text-xs text-slate-400">没有匹配到发布账号。</div>
                    ) : (
                      <div className="divide-y divide-slate-100">
                        {filteredAccountPostTargetEnvOptions.map((account) => {
                          const assignedRunnerId = accountPostSyncAssignedRunnerByEnvId.get(account.id) ?? null;
                          const isAssignedToActive = assignedRunnerId === accountPostSyncStrategy.activeRunnerId;
                          const assignedRunnerName = assignedRunnerId
                            ? accountSyncRunnerOptions.find((env) => env.id === assignedRunnerId)?.account_name || `测试账号 ${assignedRunnerId}`
                            : null;
                          const isSelectedForRun = accountPostSyncStrategy.selectedEnvIds.includes(account.id);
                          return (
                            <div
                              key={`post-target-${account.id}`}
                              className={`flex items-center justify-between gap-3 px-3 py-2.5 transition-all ${
                                isSelectedForRun ? 'bg-indigo-50/70' : 'hover:bg-slate-50'
                              }`}
                            >
                              <button
                                type="button"
                                onClick={() => {
                                  setAccountPostSyncStrategy((current) => {
                                    if (!current) return current;
                                    const exists = current.selectedEnvIds.includes(account.id);
                                    return {
                                      ...current,
                                      selectedEnvIds: exists
                                        ? current.selectedEnvIds.filter((envId) => envId !== account.id)
                                        : [...current.selectedEnvIds, account.id],
                                    };
                                  });
                                }}
                                className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded border text-[11px] font-bold transition-all ${
                                  isSelectedForRun
                                    ? 'border-indigo-500 bg-indigo-600 text-white'
                                    : 'border-slate-300 bg-white text-transparent hover:border-indigo-300'
                                }`}
                                aria-label={`选择 ${account.account_name}`}
                              >
                                ✓
                              </button>
                              <div className="min-w-0">
                                <div className="truncate text-sm font-semibold text-slate-800">{account.account_name}</div>
                                <div className="mt-0.5 text-[11px] text-slate-400">环境 ID · {account.id}</div>
                              </div>
                              <div className="flex shrink-0 items-center gap-2">
                                {isAssignedToActive ? (
                                  <span className="rounded-full bg-indigo-600 px-2 py-1 text-[11px] font-semibold text-white">当前负责</span>
                                ) : assignedRunnerName ? (
                                  <>
                                    <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-500">{assignedRunnerName}</span>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setAccountPostSyncStrategy((current) => {
                                          if (!current || !current.activeRunnerId) return current;
                                          const nextAssignments = Object.fromEntries(
                                            Object.entries(current.runnerAssignments)
                                              .map(([runnerId, envIds]) => [runnerId, envIds.filter((envId) => envId !== account.id)])
                                              .filter(([, envIds]) => envIds.length > 0),
                                          ) as Record<string, number[]>;
                                          const activeKey = String(current.activeRunnerId);
                                          nextAssignments[activeKey] = [...(nextAssignments[activeKey] || []), account.id];
                                          return {
                                            ...current,
                                            runnerAssignments: nextAssignments,
                                            selectedEnvIds: current.selectedEnvIds.includes(account.id)
                                              ? current.selectedEnvIds
                                              : [...current.selectedEnvIds, account.id],
                                          };
                                        });
                                      }}
                                      className="rounded-full border border-indigo-200 bg-indigo-50 px-2 py-1 text-[11px] font-semibold text-indigo-600 transition-all hover:bg-indigo-100"
                                    >
                                      改给当前
                                    </button>
                                  </>
                                ) : (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setAccountPostSyncStrategy((current) => {
                                        if (!current || !current.activeRunnerId) return current;
                                        const activeKey = String(current.activeRunnerId);
                                        const nextAssignments = Object.fromEntries(
                                          Object.entries(current.runnerAssignments)
                                            .map(([runnerId, envIds]) => [runnerId, envIds.filter((envId) => envId !== account.id)])
                                            .filter(([, envIds]) => envIds.length > 0),
                                        ) as Record<string, number[]>;
                                        return {
                                          ...current,
                                          runnerAssignments: {
                                            ...nextAssignments,
                                            [activeKey]: [...(nextAssignments[activeKey] || []), account.id],
                                          },
                                          selectedEnvIds: current.selectedEnvIds.includes(account.id)
                                            ? current.selectedEnvIds
                                            : [...current.selectedEnvIds, account.id],
                                        };
                                      });
                                    }}
                                    className="rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-600 transition-all hover:bg-amber-100"
                                  >
                                    分配给当前
                                  </button>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              </section>
            </div>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
              <div className="text-xs text-slate-400">
                本轮已勾选 {accountPostSyncAssignedPublishCount} 个发布账号，涉及 {accountPostSyncAssignedRunnerCount} 个测试账号
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-600 transition-all hover:bg-slate-50"
                  onClick={() => setAccountPostSyncStrategy(null)}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="h-10 rounded-xl bg-slate-900 px-5 text-sm font-semibold text-white transition-all hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-45"
                  disabled={accountNotesSyncing || accountPostSyncAssignedPublishCount === 0}
                  onClick={() => handleSyncAccountNotes(accountPostSyncStrategy)}
                >
                  {accountNotesSyncing ? '提交中...' : '按策略开始同步'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {accountEngagementSyncStrategy && (
        <div
          className="fixed inset-0 z-[82] grid place-items-center bg-slate-950/55 p-4 backdrop-blur-sm"
          onClick={() => setAccountEngagementSyncStrategy(null)}
        >
          <div
            className="max-h-[92vh] w-full max-w-5xl overflow-hidden rounded-[30px] border border-white/80 bg-white shadow-[0_34px_110px_rgba(15,23,42,0.32)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="border-b border-slate-200 bg-[radial-gradient(circle_at_12%_10%,rgba(16,185,129,0.18),transparent_32%),linear-gradient(135deg,#f8fafc,#ffffff)] p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-[11px] font-black uppercase tracking-[0.24em] text-emerald-600">Creator Center MCP Sync</div>
                  <h3 className="mt-1 text-2xl font-black tracking-[-0.04em] text-slate-950">创作中心帖子主同步</h3>
                  <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
                    这是帖子主数据的唯一新增入口。每个发布账号会启动自己的浏览器环境和 MCP，导出创作者中心数据：新帖子创建标题、发布时间和互动指标，已有帖子只刷新互动数据。
                  </p>
                </div>
                <button
                  type="button"
                  className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-lg font-semibold text-slate-500 shadow-sm ring-1 ring-slate-200 transition-all hover:bg-slate-100 hover:text-slate-800"
                  onClick={() => setAccountEngagementSyncStrategy(null)}
                  aria-label="关闭策略弹窗"
                >
                  ×
                </button>
              </div>

              <div className="mt-4 grid gap-3 md:grid-cols-4">
                {[
                  ['1', '选发布账号', '只选择本轮要建立或更新帖子主数据的发布账号'],
                  ['2', '自启 MCP', '每个账号打开自己的环境，不借用测试号'],
                  ['3', '读创作中心', '导出标题、发布时间和完整互动数据'],
                  ['4', '主记录入库', '新增帖子主记录或刷新已有帖子的互动指标'],
                ].map(([index, title, desc]) => (
                  <div key={index} className="rounded-2xl border border-white bg-white/80 p-3 shadow-sm">
                    <div className="flex items-center gap-2">
                      <span className="grid h-6 w-6 place-items-center rounded-full bg-emerald-600 text-xs font-black text-white">{index}</span>
                      <span className="text-sm font-black text-slate-900">{title}</span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-slate-500">{desc}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid max-h-[calc(92vh-210px)] gap-0 overflow-hidden lg:grid-cols-[minmax(0,1fr)_330px]">
              <section className="min-h-0 overflow-auto p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-black text-slate-950">选择本轮发布账号</div>
                    <div className="mt-1 text-xs text-slate-500">
                      当前共 {accountPostTargetEnvOptions.length} 个发布账号，已勾选 {accountEngagementSelectedCount} 个。
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[11px] font-bold text-emerald-700 transition-all hover:bg-emerald-100"
                      onClick={() => setAccountEngagementSyncStrategy((current) => current ? {
                        ...current,
                        selectedEnvIds: Array.from(new Set([
                          ...current.selectedEnvIds,
                          ...filteredAccountEngagementTargetEnvOptions.map((env) => env.id),
                        ])),
                      } : current)}
                    >
                      全选当前结果
                    </button>
                    <button
                      type="button"
                      className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-bold text-slate-600 transition-all hover:bg-slate-50"
                      onClick={() => setAccountEngagementSyncStrategy((current) => current ? { ...current, selectedEnvIds: [] } : current)}
                    >
                      清空勾选
                    </button>
                  </div>
                </div>

                <input
                  type="search"
                  value={accountEngagementSyncStrategy.accountSearch}
                  onChange={(event) => setAccountEngagementSyncStrategy((current) => current ? { ...current, accountSearch: event.target.value } : current)}
                  placeholder="搜索发布账号名称或环境 ID"
                  className="mt-4 h-11 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 text-sm text-slate-900 outline-none transition-all focus:border-emerald-300 focus:bg-white focus:ring-4 focus:ring-emerald-100"
                />

                <div className="mt-4 overflow-hidden rounded-[22px] border border-slate-200 bg-slate-50/80">
                  {filteredAccountEngagementTargetEnvOptions.length === 0 ? (
                    <div className="px-4 py-8 text-center text-sm text-slate-400">没有匹配到发布账号。</div>
                  ) : (
                    <div className="max-h-[390px] divide-y divide-slate-100 overflow-auto bg-white">
                      {filteredAccountEngagementTargetEnvOptions.map((account) => {
                        const isSelectedForRun = accountEngagementSyncStrategy.selectedEnvIds.includes(account.id);
                        const runIndex = selectedAccountEngagementTargetEnvOptions.findIndex((item) => item.id === account.id) + 1;
                        return (
                          <button
                            type="button"
                            key={`engagement-target-${account.id}`}
                            onClick={() => {
                              setAccountEngagementSyncStrategy((current) => {
                                if (!current) return current;
                                const exists = current.selectedEnvIds.includes(account.id);
                                return {
                                  ...current,
                                  selectedEnvIds: exists
                                    ? current.selectedEnvIds.filter((envId) => envId !== account.id)
                                    : [...current.selectedEnvIds, account.id],
                                };
                              });
                            }}
                            className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-all ${isSelectedForRun ? 'bg-emerald-50/80' : 'hover:bg-slate-50'}`}
                            aria-pressed={isSelectedForRun}
                          >
                            <span
                              className={`inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border text-[11px] font-black transition-all ${
                                isSelectedForRun
                                  ? 'border-emerald-500 bg-emerald-600 text-white'
                                  : 'border-slate-300 bg-white text-transparent'
                              }`}
                            >
                              ✓
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex min-w-0 flex-wrap items-center gap-2">
                                <div className="truncate text-sm font-black text-slate-900">{account.account_name}</div>
                                {isSelectedForRun && (
                                  <span className="rounded-full bg-emerald-600 px-2 py-0.5 text-[10px] font-black text-white">第 {runIndex} 个执行</span>
                                )}
                              </div>
                              <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-slate-400">
                                <span>环境 ID · {account.id}</span>
                                <span>Shop · {account.shop_id || '-'}</span>
                                {account.login_phone_number && <span>手机号 · {account.login_phone_number}</span>}
                              </div>
                            </div>
                            <span className="hidden rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[10px] font-black text-slate-500 sm:inline-flex">
                              自启 MCP
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              </section>

              <aside className="min-h-0 overflow-auto border-t border-slate-200 bg-slate-50/80 p-5 lg:border-l lg:border-t-0">
                <div className="rounded-[24px] border border-emerald-200 bg-emerald-50 p-4">
                  <div className="text-[11px] font-black uppercase tracking-[0.18em] text-emerald-700">Execution Order</div>
                  <div className="mt-1 text-lg font-black tracking-[-0.03em] text-slate-950">执行顺序确认</div>
                  <p className="mt-2 text-xs leading-5 text-emerald-900/75">
                    后端会按下面顺序逐个执行。每个账号都会获取自己的浏览器连接，启动自己的 MCP，完成后停止 MCP，再进入下一个账号。
                  </p>
                </div>

                <div className="mt-4 rounded-[24px] border border-slate-200 bg-white p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-black text-slate-900">已选发布账号</span>
                    <span className="rounded-full bg-slate-900 px-2.5 py-1 text-[11px] font-black text-white">{accountEngagementSelectedCount}</span>
                  </div>
                  <div className="mt-3 max-h-[250px] space-y-2 overflow-auto">
                    {selectedAccountEngagementTargetEnvOptions.length === 0 ? (
                      <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-3 py-6 text-center text-xs text-slate-400">
                        还没选择账号。左侧勾选后，这里会显示实际执行顺序。
                      </div>
                    ) : (
                      selectedAccountEngagementTargetEnvOptions.map((account, index) => (
                        <div key={`selected-engagement-${account.id}`} className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2">
                          <div className="flex items-center gap-2">
                            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-slate-900 text-[11px] font-black text-white">{index + 1}</span>
                            <div className="min-w-0">
                              <div className="truncate text-xs font-black text-slate-900">{account.account_name}</div>
                              <div className="mt-0.5 text-[10px] text-slate-400">环境 ID {account.id} · 自己的创作中心</div>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                <div className="mt-4 rounded-[24px] border border-amber-200 bg-amber-50 p-4">
                  <div className="text-sm font-black text-amber-900">同步口径</div>
                  <div className="mt-2 space-y-1.5 text-xs leading-5 text-amber-900/80">
                    <div>只更新已入库帖子的数据，不自动新增主页帖子。</div>
                    <div>匹配成功才写回互动指标，标题重复会被标记为跳过风险。</div>
                    <div>任务执行中可以在进度面板查看当前账号和命中数量。</div>
                  </div>
                </div>
              </aside>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white p-5">
              <div className="text-xs leading-5 text-slate-500">
                即将按顺序同步 <b className="text-slate-900">{accountEngagementSelectedCount}</b> 个发布账号；不使用测试账号轮换。
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="h-11 rounded-2xl border border-slate-200 bg-white px-5 text-sm font-bold text-slate-600 transition-all hover:bg-slate-50"
                  onClick={() => setAccountEngagementSyncStrategy(null)}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="h-11 rounded-2xl bg-emerald-600 px-5 text-sm font-black text-white shadow-lg shadow-emerald-600/20 transition-all hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-45"
                  disabled={accountEngagementSyncing || accountEngagementSelectedCount === 0}
                  onClick={() => handleSyncAccountEngagements(accountEngagementSyncStrategy)}
                >
                  {accountEngagementSyncing ? '下发中...' : '开始创作者中心主同步'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {accountDetailSyncStrategy && (
        <div
          className="fixed inset-0 z-[82] grid place-items-center bg-slate-950/42 p-4 backdrop-blur-sm"
          onClick={() => setAccountDetailSyncStrategy(null)}
        >
          <div
            className="w-full max-w-2xl rounded-[28px] border border-white/80 bg-white p-5 shadow-[0_32px_90px_rgba(15,23,42,0.26)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Sync Strategy</div>
                <h3 className="mt-1 text-xl font-semibold tracking-[-0.02em] text-slate-950">
                  {accountDetailSyncStrategy.syncMode === 'all' ? '全量同步策略' : '未同步数据策略'}
                </h3>
                <p className="mt-2 text-sm leading-6 text-slate-500">
                  先选轮换的测试账号，再决定每个账号处理多少条、切换前暂停多久，避免一个测试账号连续跑太久。
                </p>
              </div>
              <button
                type="button"
                className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-lg font-semibold text-slate-500 transition-all hover:bg-slate-200 hover:text-slate-800"
                onClick={() => setAccountDetailSyncStrategy(null)}
                aria-label="关闭策略弹窗"
              >
                ×
              </button>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
              <section className="rounded-[24px] border border-slate-200 bg-slate-50/80 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-slate-900">轮换同步环境</div>
                  <button
                    type="button"
                    className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-500 transition-all hover:border-indigo-200 hover:text-indigo-600 disabled:opacity-50"
                    onClick={() => refreshBrowserStatuses(true)}
                    disabled={browserStatusRefreshing}
                  >
                    {browserStatusRefreshing ? '探测中...' : '刷新状态'}
                  </button>
                </div>
                <div className="mt-1 text-xs text-slate-400">建议选 2-3 个测试账号轮换；任务会自动启动对应环境。</div>
                <div className="mt-3 grid gap-2">
                  {accountSyncRunnerOptions.map((env) => {
                    const active = accountDetailSyncStrategy.runnerIds.includes(env.id);
                    const browserStatus = browserStatusByEnvId.get(env.id);
                    return (
                      <button
                        key={`sync-runner-${env.id}`}
                        type="button"
                        onClick={() => {
                          setAccountDetailSyncStrategy((current) => {
                            if (!current) return current;
                            const exists = current.runnerIds.includes(env.id);
                            const nextRunnerIds = exists
                              ? current.runnerIds.filter((id) => id !== env.id)
                              : [...current.runnerIds, env.id];
                            return {
                              ...current,
                              runnerIds: nextRunnerIds,
                            };
                          });
                          setActiveSyncRunnerInsightId(env.id);
                        }}
                        className={`flex items-center justify-between rounded-2xl border px-3 py-3 text-left transition-all ${
                          active
                            ? 'border-indigo-300 bg-indigo-50 text-indigo-700 shadow-[0_8px_20px_rgba(99,102,241,0.14)]'
                            : 'border-slate-200 bg-white text-slate-700 hover:border-indigo-200 hover:bg-indigo-50/40'
                        }`}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold">{env.account_name}</span>
                          <span className={`mt-1 block truncate text-[11px] ${active ? 'text-indigo-500' : 'text-slate-400'}`}>{env.shop_id}</span>
                          <span className={`mt-2 inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold ${getBrowserStatusTone(browserStatus?.browser_status, active)}`}>
                            {getBrowserStatusLabel(browserStatus?.browser_status)}
                          </span>
                        </span>
                        <span className={`inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1 text-[11px] font-bold ${
                          active ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-400'
                        }`}>
                          {active ? '✓' : env.id}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="rounded-[24px] border border-slate-200 bg-white p-4">
                <div className="text-sm font-semibold text-slate-900">节奏参数</div>
                <div className="mt-4 space-y-3">
                  <label className="block">
                    <div className="mb-1 text-xs font-semibold text-slate-500">总同步条数上限</div>
                    <input
                      type="number"
                      min={1}
                      max={1000}
                      inputMode="numeric"
                      className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm text-slate-900 outline-none transition-all focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                      value={accountDetailSyncStrategy.totalLimit}
                      onChange={(event) => setAccountDetailSyncStrategy((current) => current ? { ...current, totalLimit: event.target.value } : current)}
                    />
                  </label>
                  <label className="block">
                    <div className="mb-1 text-xs font-semibold text-slate-500">每个账号本轮处理条数</div>
                    <input
                      type="number"
                      min={1}
                      max={60}
                      inputMode="numeric"
                      className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm text-slate-900 outline-none transition-all focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                      value={accountDetailSyncStrategy.limitPerRunner}
                      onChange={(event) => setAccountDetailSyncStrategy((current) => current ? { ...current, limitPerRunner: event.target.value } : current)}
                    />
                  </label>
                  <label className="block">
                    <div className="mb-1 text-xs font-semibold text-slate-500">只同步近多少天帖子</div>
                    <input
                      type="number"
                      min={0}
                      max={3650}
                      inputMode="numeric"
                      className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm text-slate-900 outline-none transition-all focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                      value={accountDetailSyncStrategy.maxPostAgeDays}
                      onChange={(event) => setAccountDetailSyncStrategy((current) => current ? { ...current, maxPostAgeDays: event.target.value } : current)}
                    />
                    <div className="mt-1 text-[11px] text-slate-400">填 0 表示不限制；默认 30 天。</div>
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="block">
                      <div className="mb-1 text-xs font-semibold text-slate-500">切换前最少暂停秒数</div>
                      <input
                        type="number"
                        min={0}
                        max={900}
                        inputMode="decimal"
                        className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm text-slate-900 outline-none transition-all focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                        value={accountDetailSyncStrategy.pauseMinSeconds}
                        onChange={(event) => setAccountDetailSyncStrategy((current) => current ? { ...current, pauseMinSeconds: event.target.value } : current)}
                      />
                    </label>
                    <label className="block">
                      <div className="mb-1 text-xs font-semibold text-slate-500">切换前最多暂停秒数</div>
                      <input
                        type="number"
                        min={0}
                        max={900}
                        inputMode="decimal"
                        className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm text-slate-900 outline-none transition-all focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                        value={accountDetailSyncStrategy.pauseMaxSeconds}
                        onChange={(event) => setAccountDetailSyncStrategy((current) => current ? { ...current, pauseMaxSeconds: event.target.value } : current)}
                      />
                    </label>
                  </div>
                </div>

                <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-xs leading-6 text-slate-500">
                  当前会按所选测试账号轮换执行。
                  每个账号跑完一批后暂停，再切到下一个账号继续。
                </div>

                <div className="mt-4 rounded-[20px] border border-slate-200 bg-slate-50/80 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold text-slate-900">
                      {activeSyncRunnerInsight ? `${activeSyncRunnerInsight.account_name} 获取链接名下的发布账号` : '获取链接名下的发布账号'}
                    </div>
                    {activeSyncRunnerInsight && (
                      <div className="text-xs text-slate-400">
                        {activeSyncRunnerInsight.assigned_accounts.length} 个账号
                      </div>
                    )}
                  </div>
                  <div className="mt-3 max-h-[220px] overflow-auto rounded-2xl border border-white bg-white">
                    {syncRunnerOverviewLoading ? (
                      <div className="px-3 py-4 text-xs text-slate-400">正在加载当前分配...</div>
                    ) : !activeSyncRunnerInsight ? (
                      <div className="px-3 py-4 text-xs text-slate-400">点左侧测试账号后，这里会显示它当前获取链接名下的发布账号。</div>
                    ) : activeSyncRunnerInsight.assigned_accounts.length === 0 ? (
                      <div className="px-3 py-4 text-xs text-slate-400">这个测试账号当前还没有获取链接归属的发布账号。</div>
                    ) : (
                      <div className="divide-y divide-slate-100">
                        {activeSyncRunnerInsight.assigned_accounts.map((account) => (
                          <div key={`detail-${activeSyncRunnerInsight.environment_id}-${account.environment_id}`} className="flex items-center justify-between gap-3 px-3 py-2.5">
                            <div className="min-w-0">
                              <div className="truncate text-sm font-semibold text-slate-800">{account.account_name}</div>
                              <div className="mt-0.5 text-[11px] text-slate-400">环境 ID · {account.environment_id}</div>
                            </div>
                            <div className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-500">
                              {account.note_count} 条
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </section>
            </div>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
              <div className="text-xs text-slate-400">
                已选 {accountDetailSyncStrategy.runnerIds.length} 个同步环境
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-600 transition-all hover:bg-slate-50"
                  onClick={() => setAccountDetailSyncStrategy(null)}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="h-10 rounded-xl bg-slate-900 px-5 text-sm font-semibold text-white transition-all hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-45"
                  disabled={accountNoteDetailsSyncing || accountDetailSyncStrategy.runnerIds.length === 0}
                  onClick={() => handleSyncAccountNoteDetails(accountDetailSyncStrategy)}
                >
                  {accountNoteDetailsSyncing ? '提交中...' : '按策略开始同步'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {accountNotePreview && (
        <div
          className="fixed inset-0 z-[80] grid place-items-center bg-slate-950/82 p-4 backdrop-blur-sm"
          onClick={() => setAccountNotePreview(null)}
        >
          <div
            className="relative inline-flex max-h-[88vh] max-w-[92vw] items-center justify-center"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className="absolute right-3 top-3 z-10 inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-950 text-lg font-semibold text-white shadow-[0_18px_40px_rgba(0,0,0,0.42)] transition-all hover:bg-black"
              onClick={() => setAccountNotePreview(null)}
              aria-label="关闭预览"
            >
              ×
            </button>
            <img
              src={normalizeAccountNoteCoverUrl(accountNotePreview.url)}
              alt={accountNotePreview.title}
              className="block max-h-[88vh] w-auto max-w-[92vw] rounded-[20px] object-contain shadow-[0_32px_96px_rgba(0,0,0,0.45)]"
              referrerPolicy="no-referrer"
              onError={(event) => {
                const img = event.currentTarget;
                const fallback = buildAccountNoteCoverFallbackUrl(accountNotePreview.url);
                if (!fallback || img.dataset.fallbackApplied === '1' || img.src === fallback) return;
                img.dataset.fallbackApplied = '1';
                img.src = fallback;
              }}
            />
          </div>
        </div>
      )}

      {editingPost && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/35 p-4">
          <div className="w-full max-w-2xl rounded-2xl border border-white/80 bg-white p-4 shadow-2xl">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900">
                编辑帖子
                <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                  {STATUS_LABELS[editingPost.status] || editingPost.status}
                </span>
              </h3>
              <button className="rounded-lg px-2 py-1 text-sm text-slate-500 hover:bg-slate-100" onClick={closeEdit}>关闭</button>
            </div>

            <div className="space-y-3">
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                发布账号：{editingPost.account_name || '-'}
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-500">标题</label>
                <input
                  className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  maxLength={20}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-500">正文</label>
                <textarea
                  className="h-40 w-full resize-none rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  maxLength={1000}
                />
              </div>
              {editingPost.status === 'scheduled' && (
                <div>
                  <label className="mb-1 block text-xs font-semibold text-slate-500">发布时间</label>
                  <input
                    type="datetime-local"
                    className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100"
                    value={editScheduledAt}
                    onChange={(e) => setEditScheduledAt(e.target.value)}
                  />
                </div>
              )}
            </div>

            <div className="mt-4 flex items-center justify-end gap-2">
              <button className="rounded-xl border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50" onClick={closeEdit}>
                取消
              </button>
              <button
                className="rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-3 py-1.5 text-sm font-semibold text-white disabled:bg-slate-200 disabled:text-slate-400"
                onClick={handleSaveEdit}
                disabled={savingEdit}
              >
                {savingEdit ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      <GalleryPicker
        open={galleryPickerOpen}
        onClose={() => setGalleryPickerOpen(false)}
        onSelect={() => {}}
        multiSelect
        onMultiSelect={handleGalleryMultiSelect}
        existingIds={images.map((img) => img.path || '').filter(Boolean)}
      />
    </div>
  );
}
