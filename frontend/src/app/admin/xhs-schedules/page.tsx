'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Clock3, RefreshCw, Settings2, X } from 'lucide-react';
import api from '@/services/api';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';

interface XHSEnvironment {
  id: number;
  shop_id: string;
  account_name: string;
  is_sync_runner?: boolean;
  status: string;
}

interface User {
  id: number;
  username: string;
  display_name?: string | null;
  role: string;
  roles?: string[];
}

interface AdAccountOption {
  account_id: string;
  account_name: string;
  token_status?: string | null;
  user_id?: number | null;
  buyer_username?: string | null;
  buyer_display_name?: string | null;
  buyer_email?: string | null;
}

interface ScheduleSetting {
  task_key: string;
  label: string;
  description: string;
  enabled: boolean;
  run_time: string;
  config: {
    target_scope?: 'all' | 'owner_users' | 'environment_ids';
    target_user_ids?: number[];
    target_environment_ids?: number[];
    yundeng_sync_concurrency?: number;
    post_sync_enabled?: boolean;
    post_sync_runner_ids?: number[];
    post_sync_limit_per_env?: number;
    engagement_sync_enabled?: boolean;
    detail_sync_enabled?: boolean;
    detail_sync_mode?: 'all' | 'unpublished_only';
    detail_runner_ids?: number[];
    detail_total_limit?: number;
    detail_limit_per_runner?: number;
    detail_pause_min_seconds?: number;
    detail_pause_max_seconds?: number;
    detail_max_post_age_days?: number;
    content_tag_enabled?: boolean;
    content_tag_ai_origin_type?: string;
    content_tag_status?: string;
    content_tag_concurrency?: number;
    date_range_mode?: 'relative' | 'fixed';
    days?: number;
    start_date?: string;
    end_date?: string;
    report_types?: string[];
    message_title?: string;
    webhook_url?: string;
    account_ids?: string[];
    refresh_before_send?: boolean;
    require_all_accounts_ready?: boolean;
  };
  is_running: boolean;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string | null;
  last_message?: string | null;
}

interface ScheduleRunLog {
  id: number;
  task_key: string;
  source: string;
  status: string;
  message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
}

interface ScheduleDraft {
  enabled: boolean;
  run_time: string;
  target_scope?: 'all' | 'owner_users' | 'environment_ids';
  target_user_ids?: number[];
  target_environment_ids?: number[];
  yundeng_sync_concurrency?: number;
  post_sync_enabled?: boolean;
  post_sync_runner_ids?: number[];
  post_sync_limit_per_env?: number;
  engagement_sync_enabled?: boolean;
  detail_sync_enabled?: boolean;
  detail_sync_mode?: 'all' | 'unpublished_only';
  detail_runner_ids?: number[];
  detail_total_limit?: number;
  detail_limit_per_runner?: number;
  detail_pause_min_seconds?: number;
  detail_pause_max_seconds?: number;
  detail_max_post_age_days?: number;
  content_tag_enabled?: boolean;
  content_tag_ai_origin_type?: string;
  content_tag_status?: string;
  content_tag_concurrency?: number;
  date_range_mode?: 'relative' | 'fixed';
  days?: number;
  start_date?: string;
  end_date?: string;
  message_title?: string;
  webhook_url?: string;
  account_ids?: string[];
  report_types?: string[];
  refresh_before_send?: boolean;
  require_all_accounts_ready?: boolean;
}

function userHasRole(user: { role?: string; roles?: string[] }, roles: string[]): boolean {
  return roles.includes(user.role || '') || roles.some((role) => user.roles?.includes(role));
}

function isSyncRunnerEnv(env: XHSEnvironment): boolean {
  return Boolean(env.is_sync_runner) || /测试[2345]/.test(env.account_name);
}

function formatEventTime(value?: string | null): string {
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

function getUserRoleLabel(role?: string): string {
  if (role === 'xhs_lead') return '小红书部门负责人';
  if (role === 'xhs_ops') return '小红书运营';
  if (role === 'buyer' || role === 'xhs_buyer') return '投手';
  return '普通用户';
}

function getScheduleStatusTone(status?: string | null, running = false): string {
  if (running || status === 'running') return 'border-sky-200 bg-sky-50 text-sky-700';
  if (status === 'succeeded') return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  if (status === 'partial') return 'border-amber-200 bg-amber-50 text-amber-700';
  if (status === 'failed') return 'border-rose-200 bg-rose-50 text-rose-700';
  return 'border-slate-200 bg-slate-100 text-slate-500';
}

function getScheduleStatusLabel(status?: string | null, running = false): string {
  if (running || status === 'running') return '执行中';
  if (status === 'succeeded') return '最近成功';
  if (status === 'partial') return '部分成功';
  if (status === 'failed') return '最近失败';
  return '未执行';
}

function getRunStatusLabel(status?: string | null, running = false): string {
  if (running || status === 'running') return '执行中';
  if (status === 'succeeded') return '成功';
  if (status === 'partial') return '部分成功';
  if (status === 'failed') return '失败';
  return '未执行';
}

function getRunSourceLabel(source?: string | null): string {
  if (source === 'manual') return '手动执行';
  if (source === 'schedule') return '定时执行';
  return source || '-';
}

function getTaskLabel(taskKey: string, scheduleSettings: ScheduleSetting[]): string {
  return scheduleSettings.find((item) => item.task_key === taskKey)?.label || taskKey;
}

function buildScheduleDraft(setting: ScheduleSetting): ScheduleDraft {
  return {
    enabled: !!setting.enabled,
    run_time: setting.run_time || '00:00',
    target_scope: setting.config?.target_scope || 'all',
    target_user_ids: setting.config?.target_user_ids || [],
    target_environment_ids: setting.config?.target_environment_ids || [],
    yundeng_sync_concurrency: setting.config?.yundeng_sync_concurrency ?? 5,
    post_sync_enabled: !!setting.config?.post_sync_enabled,
    post_sync_runner_ids: setting.config?.post_sync_runner_ids || [],
    post_sync_limit_per_env: setting.config?.post_sync_limit_per_env ?? 60,
    engagement_sync_enabled: !!setting.config?.engagement_sync_enabled,
    detail_sync_enabled: !!setting.config?.detail_sync_enabled,
    detail_sync_mode: setting.config?.detail_sync_mode || 'unpublished_only',
    detail_runner_ids: setting.config?.detail_runner_ids || [],
    detail_total_limit: setting.config?.detail_total_limit ?? 20,
    detail_limit_per_runner: setting.config?.detail_limit_per_runner ?? 10,
    detail_pause_min_seconds: setting.config?.detail_pause_min_seconds ?? 45,
    detail_pause_max_seconds: setting.config?.detail_pause_max_seconds ?? 90,
    detail_max_post_age_days: setting.config?.detail_max_post_age_days ?? 30,
    content_tag_enabled: !!setting.config?.content_tag_enabled,
    content_tag_ai_origin_type: setting.config?.content_tag_ai_origin_type || 'all',
    content_tag_status: setting.config?.content_tag_status || 'all',
    content_tag_concurrency: setting.config?.content_tag_concurrency ?? 20,
    date_range_mode: setting.config?.date_range_mode || 'relative',
    days: setting.config?.days ?? 30,
    start_date: setting.config?.start_date || '',
    end_date: setting.config?.end_date || '',
    message_title: setting.config?.message_title || '今日小红书零跑汇总数据',
    webhook_url: setting.config?.webhook_url || '',
    account_ids: setting.config?.account_ids || [],
    report_types: setting.config?.report_types || ['simple', 'standard'],
    refresh_before_send: setting.config?.refresh_before_send ?? true,
    require_all_accounts_ready: setting.config?.require_all_accounts_ready ?? true,
  };
}

function getScopeLabel(scope?: ScheduleDraft['target_scope']): string {
  if (scope === 'owner_users') return '指定负责人';
  if (scope === 'environment_ids') return '指定发布账号';
  return '全部账号';
}

function summarizeSchedule(setting: ScheduleSetting, draft?: ScheduleDraft): string {
  const current = draft || buildScheduleDraft(setting);
  if (setting.task_key === 'account_data_sync') {
    const parts = [];
    parts.push(getScopeLabel(current.target_scope));
    if (current.post_sync_enabled) parts.push('主页帖子');
    if (current.engagement_sync_enabled) parts.push('创作者中心');
    if (current.detail_sync_enabled) parts.push('未同步策略');
    if (current.content_tag_enabled) parts.push('内容打标');
    if (parts.length === 1) parts.push('未配置具体同步项');
    return parts.join(' / ');
  }
  if (setting.task_key === 'ad_report_publish') {
    const accountCount = current.account_ids?.length || 0;
    const reportTypes = (current.report_types || []).map((item) => REPORT_TYPE_LABELS[item] || item);
    return [
      `${accountCount} 个广告账户`,
      reportTypes.join(' + ') || '简单投 + 标准投',
      current.refresh_before_send ? '推送前刷新' : '直接推送',
      current.require_all_accounts_ready ? '全账户就绪校验' : '允许部分到账',
      current.webhook_url ? '已配置飞书' : '未配置飞书',
    ].join(' / ');
  }
  if (current.date_range_mode === 'fixed' && current.start_date && current.end_date) {
    return `固定范围 ${current.start_date} 至 ${current.end_date}`;
  }
  return `回刷截至昨天最近 ${current.days ?? 30} 天`;
}

const REPORT_TYPE_LABELS: Record<string, string> = {
  simple: '简单投',
  standard: '标准投',
  creative: '创意报表',
  simple_note: '简单投笔记',
  standard_note: '标准投笔记',
};

function sortStringList(values: string[]): string[] {
  return [...values].sort((left, right) => left.localeCompare(right, 'zh-CN-u-kn-true'));
}

function parseAccountIdsInput(value: string): string[] {
  return sortStringList(
    Array.from(
      new Set(
        value
          .split(/[\s,，;；]+/)
          .map((item) => item.trim())
          .filter(Boolean),
      ),
    ),
  );
}

function ScheduleToggleSwitch({
  checked,
  disabled,
  loading,
  onToggle,
  compact = false,
}: {
  checked: boolean;
  disabled?: boolean;
  loading?: boolean;
  onToggle: () => void;
  compact?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={onToggle}
      disabled={disabled}
      className={`inline-flex items-center gap-3 rounded-2xl border border-slate-200 bg-white transition-all disabled:cursor-not-allowed disabled:opacity-50 ${
        compact ? 'h-10 px-3' : 'h-11 px-4'
      }`}
    >
      <span
        className={`relative inline-flex shrink-0 rounded-full transition-all ${
          compact ? 'h-5 w-9' : 'h-6 w-11'
        } ${checked ? 'bg-emerald-500' : 'bg-slate-300'}`}
      >
        <span
          className={`absolute left-0.5 top-0.5 rounded-full bg-white shadow-sm transition-all ${
            compact ? 'h-4 w-4' : 'h-5 w-5'
          } ${checked ? (compact ? 'translate-x-4' : 'translate-x-5') : 'translate-x-0'}`}
        />
      </span>
      <span className="text-sm font-semibold text-slate-700">
        {loading ? '提交中...' : checked ? '已开启' : '已关闭'}
      </span>
    </button>
  );
}

export default function AdminXhsSchedulesPage() {
  const [envs, setEnvs] = useState<XHSEnvironment[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [adAccounts, setAdAccounts] = useState<AdAccountOption[]>([]);
  const [scheduleSettings, setScheduleSettings] = useState<ScheduleSetting[]>([]);
  const [scheduleLogs, setScheduleLogs] = useState<ScheduleRunLog[]>([]);
  const [scheduleDrafts, setScheduleDrafts] = useState<Record<string, ScheduleDraft>>({});
  const [loading, setLoading] = useState(false);
  const [actionKey, setActionKey] = useState<string | null>(null);
  const [activeTaskKey, setActiveTaskKey] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [envRes, userRes, adAccountRes, scheduleRes, scheduleLogRes] = await Promise.all([
        api.get('/xhs/environments').catch(() => null),
        adminApi.getUsers(1, 100),
        adminApi.getXhsAdAccountAssignments().catch(() => null),
        api.get('/admin/xhs/schedule-settings'),
        api.get('/admin/xhs/schedule-run-logs?limit=80'),
      ]);
      const nextEnvs = (envRes?.data || []) as XHSEnvironment[];
      const nextUsers = (userRes?.data?.items || []) as User[];
      const nextAdAccounts = (adAccountRes?.data || []) as AdAccountOption[];
      const nextSchedules = (scheduleRes?.data || []) as ScheduleSetting[];
      const nextScheduleLogs = (scheduleLogRes?.data || []) as ScheduleRunLog[];
      setEnvs(nextEnvs);
      setUsers(nextUsers);
      setAdAccounts(nextAdAccounts);
      setScheduleSettings(nextSchedules);
      setScheduleLogs(nextScheduleLogs);
      setScheduleDrafts(Object.fromEntries(nextSchedules.map((item) => [item.task_key, buildScheduleDraft(item)])));
      setActiveTaskKey((current) => (current && nextSchedules.some((item) => item.task_key === current) ? current : null));
    } catch (err: any) {
      toast.error(`获取定时任务失败: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const ownerUsers = useMemo(
    () => users.filter((user) => userHasRole(user, ['xhs_lead', 'xhs_ops'])),
    [users],
  );
  const syncRunnerOptions = useMemo(
    () => envs.filter((env) => isSyncRunnerEnv(env)),
    [envs],
  );
  const publishEnvOptions = useMemo(
    () => envs.filter((env) => !isSyncRunnerEnv(env)),
    [envs],
  );

  const activeSetting = useMemo(
    () => scheduleSettings.find((item) => item.task_key === activeTaskKey) || null,
    [activeTaskKey, scheduleSettings],
  );
  const activeTaskLogs = useMemo(
    () => (activeTaskKey ? scheduleLogs.filter((item) => item.task_key === activeTaskKey) : []),
    [activeTaskKey, scheduleLogs],
  );
  const activeDraft = activeTaskKey ? scheduleDrafts[activeTaskKey] : undefined;
  const selectedAdAccounts = useMemo(() => {
    const selectedIds = new Set(activeDraft?.account_ids || []);
    return adAccounts.filter((item) => selectedIds.has(item.account_id));
  }, [activeDraft?.account_ids, adAccounts]);
  const unmatchedAdAccountIds = useMemo(() => {
    const knownIds = new Set(adAccounts.map((item) => item.account_id));
    return (activeDraft?.account_ids || []).filter((item) => !knownIds.has(item));
  }, [activeDraft?.account_ids, adAccounts]);

  const hasScheduleChanges = useCallback((taskKey: string) => {
    const setting = scheduleSettings.find((item) => item.task_key === taskKey);
    const draft = scheduleDrafts[taskKey];
    if (!setting || !draft) return false;
    return JSON.stringify(buildScheduleDraft(setting)) !== JSON.stringify(draft);
  }, [scheduleDrafts, scheduleSettings]);

  const persistSchedule = useCallback(async (
    taskKey: string,
    options?: { enabled?: boolean; actionKey?: string; successMessage?: string },
  ) => {
    const setting = scheduleSettings.find((item) => item.task_key === taskKey);
    const draft = scheduleDrafts[taskKey];
    if (!setting || !draft) return;
    const nextEnabled = options?.enabled ?? !!draft.enabled;
    setActionKey(options?.actionKey || `save-${taskKey}`);
    try {
      let payload: {
        enabled: boolean;
        run_time: string;
        config: Record<string, unknown>;
      };
      if (taskKey === 'account_data_sync') {
        payload = {
            enabled: nextEnabled,
            run_time: draft.run_time,
            config: {
              ...setting.config,
              target_scope: draft.target_scope || 'all',
              target_user_ids: draft.target_user_ids || [],
              target_environment_ids: draft.target_environment_ids || [],
              yundeng_sync_concurrency: Number(draft.yundeng_sync_concurrency || 5),
              post_sync_enabled: !!draft.post_sync_enabled,
              post_sync_runner_ids: draft.post_sync_runner_ids || [],
              post_sync_limit_per_env: Number(draft.post_sync_limit_per_env || 60),
              engagement_sync_enabled: !!draft.engagement_sync_enabled,
              detail_sync_enabled: !!draft.detail_sync_enabled,
              detail_sync_mode: draft.detail_sync_mode || 'unpublished_only',
              detail_runner_ids: draft.detail_runner_ids || [],
              detail_total_limit: Number(draft.detail_total_limit || 20),
              detail_limit_per_runner: Number(draft.detail_limit_per_runner || 10),
              detail_pause_min_seconds: Number(draft.detail_pause_min_seconds || 45),
              detail_pause_max_seconds: Number(draft.detail_pause_max_seconds || 90),
              detail_max_post_age_days: Number(draft.detail_max_post_age_days || 30),
              content_tag_enabled: !!draft.content_tag_enabled,
              content_tag_ai_origin_type: draft.content_tag_ai_origin_type || 'all',
              content_tag_status: draft.content_tag_status || 'all',
              content_tag_concurrency: Number(draft.content_tag_concurrency || 20),
            },
          };
      } else if (taskKey === 'ad_report_publish') {
        payload = {
          enabled: nextEnabled,
          run_time: draft.run_time,
          config: {
            ...setting.config,
            message_title: (draft.message_title || '今日小红书零跑汇总数据').trim(),
            webhook_url: (draft.webhook_url || '').trim(),
            account_ids: sortStringList((draft.account_ids || []).map((item) => String(item).trim()).filter(Boolean)),
            report_types: (draft.report_types || []).filter((item) => item === 'simple' || item === 'standard'),
            refresh_before_send: !!draft.refresh_before_send,
            require_all_accounts_ready: !!draft.require_all_accounts_ready,
          },
        };
      } else {
        payload = {
            enabled: nextEnabled,
            run_time: draft.run_time,
            config: {
              ...setting.config,
              date_range_mode: draft.date_range_mode || 'relative',
              days: Number(draft.days || 30),
              start_date: (draft.start_date || '').trim(),
              end_date: (draft.end_date || '').trim(),
            },
          };
      }
      const res = await api.put(`/admin/xhs/schedule-settings/${taskKey}`, payload);
      const next = res.data as ScheduleSetting;
      setScheduleSettings((prev) => prev.map((item) => item.task_key === taskKey ? next : item));
      setScheduleDrafts((prev) => ({ ...prev, [taskKey]: buildScheduleDraft(next) }));
      toast.success(options?.successMessage || `${next.label}配置已保存`);
      setActiveTaskKey(next.task_key);
    } catch (err: any) {
      toast.error(`保存失败: ${err.message}`);
    } finally {
      setActionKey(null);
    }
  }, [scheduleDrafts, scheduleSettings]);

  const handleSave = useCallback(async (taskKey: string) => {
    await persistSchedule(taskKey);
  }, [persistSchedule]);

  const handleToggleEnabled = useCallback(async (taskKey: string) => {
    const current = scheduleDrafts[taskKey];
    if (!current) return;
    await persistSchedule(taskKey, {
      enabled: !current.enabled,
      actionKey: `toggle-${taskKey}`,
      successMessage: !current.enabled ? '定时任务已开启' : '定时任务已关闭',
    });
  }, [persistSchedule, scheduleDrafts]);

  if (loading && scheduleSettings.length === 0) {
    return <div className="grid min-h-[320px] place-items-center text-sm text-slate-400">正在加载定时任务...</div>;
  }

  return (
    <div className="min-h-full space-y-5">
      <section className="overflow-hidden rounded-[28px] border border-slate-200 bg-[#10141f] text-white shadow-[0_22px_70px_rgba(15,23,42,0.22)]">
        <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <div>
            <div className="inline-flex rounded-full border border-white/15 bg-white/8 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-white/70">
              XHS Schedule Center
            </div>
            <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em]">小红书定时任务管理</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-white/62">
              默认先看配置表和执行状态。点开某一行的配置，再进入具体设置窗口编辑，执行和配置分开处理。
            </p>
          </div>
          <div className="flex flex-wrap gap-3 lg:justify-end">
            <div className="rounded-2xl bg-white/8 px-5 py-4 text-right">
              <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-white/42">已启用任务</div>
              <div className="mt-1 text-3xl font-semibold tracking-[-0.04em]">{scheduleSettings.filter((item) => item.enabled).length}</div>
            </div>
            <button
              type="button"
              onClick={fetchData}
              disabled={loading}
              className="inline-flex h-11 items-center gap-2 rounded-2xl border border-white/14 bg-white/8 px-4 text-sm font-semibold text-white transition-all hover:bg-white/12 disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </button>
          </div>
        </div>
      </section>

      <section className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_16px_50px_rgba(15,23,42,0.08)]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Schedule List</div>
            <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em] text-slate-950">定时任务配置表</h2>
          </div>
          <div className="text-sm text-slate-500">点击“配置”再打开详细配置窗口</div>
        </div>

        {scheduleSettings.length === 0 ? (
          <div className="grid min-h-[260px] place-items-center px-5 py-10 text-center">
            <div>
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-slate-400">
                <Clock3 className="h-6 w-6" />
              </div>
              <div className="mt-4 text-base font-semibold text-slate-900">暂无定时任务配置</div>
              <div className="mt-2 text-sm text-slate-500">后端返回为空时，这里会先保持空表状态。</div>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full table-fixed">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">
                  <th className="px-5 py-3">任务</th>
                  <th className="px-5 py-3">配置摘要</th>
                  <th className="px-5 py-3">执行时间</th>
                  <th className="px-5 py-3">状态</th>
                  <th className="px-5 py-3">最近执行</th>
                  <th className="px-5 py-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {scheduleSettings.map((item) => {
                  const draft = scheduleDrafts[item.task_key];
                  const toggling = actionKey === `toggle-${item.task_key}`;
                  return (
                    <tr key={item.task_key} className="border-t border-slate-200 align-top">
                      <td className="px-5 py-4">
                        <div className="font-semibold text-slate-950">{item.label}</div>
                        <div className="mt-1 text-sm leading-6 text-slate-500">{item.description}</div>
                      </td>
                      <td className="px-5 py-4">
                        <div className="text-sm leading-6 text-slate-700">{summarizeSchedule(item, draft)}</div>
                        <div className="mt-2">
                          <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${draft?.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                            {draft?.enabled ? '已启用' : '未启用'}
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-4">
                        <div className="text-sm font-semibold text-slate-900">{draft?.run_time || item.run_time || '-'}</div>
                        <div className="mt-1 text-xs text-slate-500">下次执行：{item.next_run_at ? formatEventTime(item.next_run_at) : '未计划'}</div>
                      </td>
                      <td className="px-5 py-4">
                        <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${getScheduleStatusTone(item.last_status, item.is_running)}`}>
                          {getScheduleStatusLabel(item.last_status, item.is_running)}
                        </span>
                      </td>
                      <td className="px-5 py-4">
                        <div className="text-sm text-slate-700">{item.last_run_at ? formatEventTime(item.last_run_at) : '未执行'}</div>
                        <div className="mt-1 line-clamp-2 max-w-[280px] text-xs leading-5 text-slate-500">
                          {item.last_message || '暂无记录'}
                        </div>
                      </td>
                      <td className="px-5 py-4">
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() => setActiveTaskKey(item.task_key)}
                            className="inline-flex h-10 items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 transition-all hover:border-slate-300 hover:bg-slate-50"
                          >
                            <Settings2 className="h-4 w-4" />
                            配置
                          </button>
                          <ScheduleToggleSwitch
                            checked={!!draft?.enabled}
                            loading={toggling}
                            disabled={toggling}
                            compact
                            onToggle={() => handleToggleEnabled(item.task_key)}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_16px_50px_rgba(15,23,42,0.08)]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Run History</div>
            <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em] text-slate-950">历史执行记录</h2>
          </div>
          <div className="text-sm text-slate-500">保留最近 {scheduleLogs.length} 条执行记录</div>
        </div>

        {scheduleLogs.length === 0 ? (
          <div className="grid min-h-[220px] place-items-center px-5 py-10 text-center text-sm text-slate-500">
            暂无执行日志
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full table-fixed">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">
                  <th className="px-5 py-3">任务</th>
                  <th className="px-5 py-3">触发方式</th>
                  <th className="px-5 py-3">状态</th>
                  <th className="px-5 py-3">开始时间</th>
                  <th className="px-5 py-3">结束时间</th>
                  <th className="px-5 py-3">结果</th>
                </tr>
              </thead>
              <tbody>
                {scheduleLogs.map((log) => (
                  <tr key={log.id} className="border-t border-slate-200 align-top">
                    <td className="px-5 py-4 text-sm font-semibold text-slate-900">{getTaskLabel(log.task_key, scheduleSettings)}</td>
                    <td className="px-5 py-4 text-sm text-slate-600">{getRunSourceLabel(log.source)}</td>
                    <td className="px-5 py-4">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${getScheduleStatusTone(log.status, log.status === 'running')}`}>
                        {getRunStatusLabel(log.status, log.status === 'running')}
                      </span>
                    </td>
                    <td className="px-5 py-4 text-sm text-slate-700">{formatEventTime(log.started_at)}</td>
                    <td className="px-5 py-4 text-sm text-slate-700">{formatEventTime(log.finished_at)}</td>
                    <td className="px-5 py-4">
                      <div className="max-w-[520px] text-sm leading-6 text-slate-600">{log.message || '暂无记录'}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {activeSetting && activeDraft ? (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/28 backdrop-blur-sm" onClick={() => setActiveTaskKey(null)}>
          <div
            className="h-full w-full max-w-[760px] overflow-y-auto border-l border-slate-200 bg-[#f8f7f4] shadow-[-18px_0_60px_rgba(15,23,42,0.18)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="sticky top-0 z-10 border-b border-slate-200 bg-white/96 px-5 py-4 backdrop-blur">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Schedule Config</div>
                  <h3 className="mt-1 text-xl font-semibold tracking-[-0.03em] text-slate-950">{activeSetting.label}</h3>
                  <p className="mt-1 text-sm leading-6 text-slate-500">{activeSetting.description}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setActiveTaskKey(null)}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-2xl border border-slate-200 bg-white text-slate-500 transition-all hover:bg-slate-50"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="space-y-4 p-5">
              <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                <div className="grid gap-3 lg:grid-cols-[160px_minmax(0,1fr)] lg:items-end">
                  <label className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-700">
                    <input
                      type="checkbox"
                      checked={!!activeDraft.enabled}
                      onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], enabled: event.target.checked } }))}
                      className="h-4 w-4 rounded border-slate-300 text-slate-950"
                    />
                    启用任务
                  </label>
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">每日执行时间</div>
                    <input
                      type="time"
                      value={activeDraft.run_time || '00:00'}
                      onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], run_time: event.target.value } }))}
                      className="mt-2 h-11 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                    />
                  </div>
                </div>
              </div>

              {activeSetting.task_key === 'account_data_sync' ? (
                <>
                  <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                    <div className="text-sm font-semibold text-slate-950">同步范围</div>
                    <div className="mt-3 grid gap-2 sm:grid-cols-3">
                      {[
                        ['all', '全部账号'],
                        ['owner_users', '指定负责人'],
                        ['environment_ids', '指定发布账号'],
                      ].map(([value, label]) => (
                        <button
                          key={`${activeSetting.task_key}-${value}`}
                          type="button"
                          onClick={() => setScheduleDrafts((prev) => ({
                            ...prev,
                            [activeSetting.task_key]: {
                              ...prev[activeSetting.task_key],
                              target_scope: value as 'all' | 'owner_users' | 'environment_ids',
                            },
                          }))}
                          className={`rounded-2xl border px-3 py-3 text-sm font-semibold transition-all ${activeDraft.target_scope === value ? 'border-slate-950 bg-slate-950 text-white' : 'border-slate-200 bg-slate-50 text-slate-600'}`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    {activeDraft.target_scope === 'owner_users' ? (
                      <div className="mt-3 grid gap-2 md:grid-cols-2">
                        {ownerUsers.map((user) => {
                          const checked = !!activeDraft.target_user_ids?.includes(user.id);
                          return (
                            <label key={user.id} className={`flex items-center justify-between rounded-2xl border px-3 py-3 text-sm ${checked ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                              <span className="min-w-0">
                                <span className="block truncate font-semibold">{user.display_name || user.username}</span>
                                <span className="mt-1 block truncate text-xs text-slate-400">{user.username} · {getUserRoleLabel(user.role)}</span>
                              </span>
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={(event) => setScheduleDrafts((prev) => {
                                  const current = new Set(prev[activeSetting.task_key]?.target_user_ids || []);
                                  if (event.target.checked) current.add(user.id);
                                  else current.delete(user.id);
                                  return { ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], target_user_ids: Array.from(current).sort((a, b) => a - b) } };
                                })}
                                className="h-4 w-4 rounded border-slate-300 text-slate-950"
                              />
                            </label>
                          );
                        })}
                      </div>
                    ) : null}
                    {activeDraft.target_scope === 'environment_ids' ? (
                      <div className="mt-3 max-h-[220px] space-y-2 overflow-y-auto pr-1">
                        {publishEnvOptions.map((env) => {
                          const checked = !!activeDraft.target_environment_ids?.includes(env.id);
                          return (
                            <label key={env.id} className={`flex items-center justify-between rounded-2xl border px-3 py-3 text-sm ${checked ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                              <span className="min-w-0">
                                <span className="block truncate font-semibold">{env.account_name}</span>
                                <span className="mt-1 block truncate text-xs text-slate-400">{env.shop_id}</span>
                              </span>
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={(event) => setScheduleDrafts((prev) => {
                                  const current = new Set(prev[activeSetting.task_key]?.target_environment_ids || []);
                                  if (event.target.checked) current.add(env.id);
                                  else current.delete(env.id);
                                  return { ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], target_environment_ids: Array.from(current).sort((a, b) => a - b) } };
                                })}
                                className="h-4 w-4 rounded border-slate-300 text-slate-950"
                              />
                            </label>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>

                  <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                    <div className="grid items-center gap-4 md:grid-cols-[minmax(0,1fr)_180px]">
                      <div>
                        <div className="text-sm font-semibold text-slate-950">云登同步并发</div>
                        <div className="mt-1 text-xs leading-5 text-slate-500">
                          主页、创作者中心和详情同步共用同一个并发上限；同一云登环境始终串行，服务器硬上限为 5。
                        </div>
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">同时运行环境数</div>
                        <input
                          type="number"
                          min={1}
                          max={5}
                          value={activeDraft.yundeng_sync_concurrency ?? 5}
                          onChange={(event) => setScheduleDrafts((prev) => ({
                            ...prev,
                            [activeSetting.task_key]: {
                              ...prev[activeSetting.task_key],
                              yundeng_sync_concurrency: Number(event.target.value || 5),
                            },
                          }))}
                          className="mt-2 h-10 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                    <div className="text-sm font-semibold text-slate-950">主页帖子同步</div>
                    <div className="mt-3 grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)]">
                      <label className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={!!activeDraft.post_sync_enabled}
                          onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], post_sync_enabled: event.target.checked } }))}
                          className="h-4 w-4 rounded border-slate-300 text-slate-950"
                        />
                        启用主页帖子同步
                      </label>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
                          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">每账号拉取条数</div>
                          <input
                            type="number"
                            min={1}
                            max={60}
                            value={activeDraft.post_sync_limit_per_env ?? 60}
                            onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], post_sync_limit_per_env: Number(event.target.value || 60) } }))}
                            className="mt-2 h-10 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                          />
                        </div>
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
                          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">同步测试环境</div>
                          <div className="mt-2 flex max-h-[120px] flex-wrap gap-2 overflow-y-auto pr-1">
                            {syncRunnerOptions.map((env) => {
                              const checked = !!activeDraft.post_sync_runner_ids?.includes(env.id);
                              return (
                                <label key={env.id} className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold ${checked ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-white text-slate-600'}`}>
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={(event) => setScheduleDrafts((prev) => {
                                      const current = new Set(prev[activeSetting.task_key]?.post_sync_runner_ids || []);
                                      if (event.target.checked) current.add(env.id);
                                      else current.delete(env.id);
                                      return { ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], post_sync_runner_ids: Array.from(current).sort((a, b) => a - b) } };
                                    })}
                                    className="h-3.5 w-3.5 rounded border-slate-300 text-slate-950"
                                  />
                                  {env.account_name}
                                </label>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                    <div className="grid gap-4 xl:grid-cols-3">
                      <label className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={!!activeDraft.engagement_sync_enabled}
                          onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], engagement_sync_enabled: event.target.checked } }))}
                          className="h-4 w-4 rounded border-slate-300 text-slate-950"
                        />
                        启用创作者中心互动同步
                      </label>
                      <label className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={!!activeDraft.content_tag_enabled}
                          onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], content_tag_enabled: event.target.checked } }))}
                          className="h-4 w-4 rounded border-slate-300 text-slate-950"
                        />
                        启用内容打标
                      </label>
                      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
                          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">打标来源筛选</div>
                          <select
                            value={activeDraft.content_tag_ai_origin_type || 'all'}
                            onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], content_tag_ai_origin_type: event.target.value } }))}
                            className="mt-2 h-10 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                          >
                            <option value="all">全部来源</option>
                            <option value="__unset__">未标记</option>
                            <option value="manual">人工素材</option>
                            <option value="text_ai">文生图</option>
                            <option value="image_ai">图生图</option>
                            <option value="all_ai">全 AI</option>
                          </select>
                        </div>
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
                          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">打标并发</div>
                          <input
                            type="number"
                            min={1}
                            max={50}
                            value={activeDraft.content_tag_concurrency ?? 20}
                            onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], content_tag_concurrency: Number(event.target.value || 20) } }))}
                            className="mt-2 h-10 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                          />
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                    <div className="text-sm font-semibold text-slate-950">未同步策略 / 详情补齐</div>
                    <div className="mt-3 grid gap-3 xl:grid-cols-[220px_minmax(0,1fr)]">
                      <div className="space-y-3">
                        <label className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-700">
                          <input
                            type="checkbox"
                            checked={!!activeDraft.detail_sync_enabled}
                            onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], detail_sync_enabled: event.target.checked } }))}
                            className="h-4 w-4 rounded border-slate-300 text-slate-950"
                          />
                          启用未同步策略
                        </label>
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
                          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">同步模式</div>
                          <select
                            value={activeDraft.detail_sync_mode || 'unpublished_only'}
                            onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], detail_sync_mode: event.target.value as 'all' | 'unpublished_only' } }))}
                            className="mt-2 h-10 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                          >
                            <option value="unpublished_only">仅未同步</option>
                            <option value="all">全量详情</option>
                          </select>
                        </div>
                      </div>
                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                        {[
                          ['总条数上限', 'detail_total_limit', activeDraft.detail_total_limit ?? 20, 1, 1000],
                          ['每环境条数', 'detail_limit_per_runner', activeDraft.detail_limit_per_runner ?? 10, 1, 60],
                          ['最小暂停秒数', 'detail_pause_min_seconds', activeDraft.detail_pause_min_seconds ?? 45, 0, 900],
                          ['最大暂停秒数', 'detail_pause_max_seconds', activeDraft.detail_pause_max_seconds ?? 90, 0, 900],
                          ['帖子最大天数', 'detail_max_post_age_days', activeDraft.detail_max_post_age_days ?? 30, 0, 3650],
                        ].map(([label, key, value, min, max]) => (
                          <div key={`${activeSetting.task_key}-${String(key)}`} className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
                            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">{label}</div>
                            <input
                              type="number"
                              min={Number(min)}
                              max={Number(max)}
                              value={Number(value)}
                              onChange={(event) => setScheduleDrafts((prev) => ({ ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], [key]: Number(event.target.value || value) } }))}
                              className="mt-2 h-10 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                            />
                          </div>
                        ))}
                        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 md:col-span-2 xl:col-span-3">
                          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">详情同步环境</div>
                          <div className="mt-2 flex max-h-[120px] flex-wrap gap-2 overflow-y-auto pr-1">
                            {syncRunnerOptions.map((env) => {
                              const checked = !!activeDraft.detail_runner_ids?.includes(env.id);
                              return (
                                <label key={env.id} className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold ${checked ? 'border-amber-200 bg-amber-50 text-amber-700' : 'border-slate-200 bg-white text-slate-600'}`}>
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={(event) => setScheduleDrafts((prev) => {
                                      const current = new Set(prev[activeSetting.task_key]?.detail_runner_ids || []);
                                      if (event.target.checked) current.add(env.id);
                                      else current.delete(env.id);
                                      return { ...prev, [activeSetting.task_key]: { ...prev[activeSetting.task_key], detail_runner_ids: Array.from(current).sort((a, b) => a - b) } };
                                    })}
                                    className="h-3.5 w-3.5 rounded border-slate-300 text-slate-950"
                                  />
                                  {env.account_name}
                                </label>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </>
              ) : activeSetting.task_key === 'ad_report_publish' ? (
                <>
                  <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">汇报标题</div>
                        <input
                          type="text"
                          value={activeDraft.message_title || ''}
                          onChange={(event) => setScheduleDrafts((prev) => ({
                            ...prev,
                            [activeSetting.task_key]: { ...prev[activeSetting.task_key], message_title: event.target.value },
                          }))}
                          placeholder="今日小红书零跑汇总数据"
                          className="mt-2 h-11 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                        />
                      </div>
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">飞书 Webhook</div>
                        <input
                          type="password"
                          value={activeDraft.webhook_url || ''}
                          onChange={(event) => setScheduleDrafts((prev) => ({
                            ...prev,
                            [activeSetting.task_key]: { ...prev[activeSetting.task_key], webhook_url: event.target.value },
                          }))}
                          placeholder="粘贴群机器人 webhook"
                          className="mt-2 h-11 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_220px_220px]">
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">汇报来源</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {['simple', 'standard'].map((reportType) => {
                            const checked = !!activeDraft.report_types?.includes(reportType);
                            return (
                              <label
                                key={`${activeSetting.task_key}-${reportType}`}
                                className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold ${
                                  checked ? 'border-slate-950 bg-slate-950 text-white' : 'border-slate-200 bg-white text-slate-600'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={(event) => setScheduleDrafts((prev) => {
                                    const current = new Set(prev[activeSetting.task_key]?.report_types || []);
                                    if (event.target.checked) current.add(reportType);
                                    else current.delete(reportType);
                                    return {
                                      ...prev,
                                      [activeSetting.task_key]: {
                                        ...prev[activeSetting.task_key],
                                        report_types: sortStringList(Array.from(current)),
                                      },
                                    };
                                  })}
                                  className="h-3.5 w-3.5 rounded border-white/30 text-slate-950"
                                />
                                {REPORT_TYPE_LABELS[reportType]}
                              </label>
                            );
                          })}
                        </div>
                      </div>
                      <label className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={!!activeDraft.refresh_before_send}
                          onChange={(event) => setScheduleDrafts((prev) => ({
                            ...prev,
                            [activeSetting.task_key]: { ...prev[activeSetting.task_key], refresh_before_send: event.target.checked },
                          }))}
                          className="h-4 w-4 rounded border-slate-300 text-slate-950"
                        />
                        推送前先刷新当天数据
                      </label>
                      <label className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-700">
                        <input
                          type="checkbox"
                          checked={!!activeDraft.require_all_accounts_ready}
                          onChange={(event) => setScheduleDrafts((prev) => ({
                            ...prev,
                            [activeSetting.task_key]: { ...prev[activeSetting.task_key], require_all_accounts_ready: event.target.checked },
                          }))}
                          className="h-4 w-4 rounded border-slate-300 text-slate-950"
                        />
                        要求全部账户完成更新
                      </label>
                    </div>
                  </div>

                  <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-slate-950">广告账户范围</div>
                        <div className="mt-1 text-xs text-slate-500">
                          已选 {activeDraft.account_ids?.length || 0} 个，匹配到 {selectedAdAccounts.length} 个
                          {unmatchedAdAccountIds.length ? `，另有 ${unmatchedAdAccountIds.length} 个手填账户未在投手分配表中匹配` : ''}
                        </div>
                      </div>
                    </div>
                    <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">账户 ID（支持逗号、空格、换行）</div>
                      <textarea
                        value={(activeDraft.account_ids || []).join('\n')}
                        onChange={(event) => setScheduleDrafts((prev) => ({
                          ...prev,
                          [activeSetting.task_key]: { ...prev[activeSetting.task_key], account_ids: parseAccountIdsInput(event.target.value) },
                        }))}
                        rows={5}
                        placeholder="一行一个广告账户 ID"
                        className="mt-2 w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm leading-6 text-slate-800 outline-none"
                      />
                    </div>
                    <div className="mt-3 max-h-[320px] space-y-2 overflow-y-auto pr-1">
                      {adAccounts.map((account) => {
                        const checked = !!activeDraft.account_ids?.includes(account.account_id);
                        return (
                          <label
                            key={account.account_id}
                            className={`flex items-center justify-between gap-3 rounded-2xl border px-3 py-3 text-sm ${
                              checked ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-slate-50 text-slate-600'
                            }`}
                          >
                            <span className="min-w-0">
                              <span className="block truncate font-semibold">{account.account_name || '未命名广告账户'}</span>
                              <span className="mt-1 block truncate text-xs text-slate-400">
                                {account.account_id}
                                {account.buyer_display_name || account.buyer_username ? ` / ${account.buyer_display_name || account.buyer_username}` : ''}
                                {account.token_status ? ` / ${account.token_status}` : ''}
                              </span>
                            </span>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(event) => setScheduleDrafts((prev) => {
                                const current = new Set(prev[activeSetting.task_key]?.account_ids || []);
                                if (event.target.checked) current.add(account.account_id);
                                else current.delete(account.account_id);
                                return {
                                  ...prev,
                                  [activeSetting.task_key]: {
                                    ...prev[activeSetting.task_key],
                                    account_ids: sortStringList(Array.from(current)),
                                  },
                                };
                              })}
                              className="h-4 w-4 rounded border-slate-300 text-slate-950"
                            />
                          </label>
                        );
                      })}
                    </div>
                    {unmatchedAdAccountIds.length ? (
                      <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-6 text-amber-800">
                        未匹配到账户池的 ID：{unmatchedAdAccountIds.join('、')}
                      </div>
                    ) : null}
                  </div>
                </>
              ) : (
                <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                  <div className="grid gap-3 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">更新时间范围</div>
                          <div className="mt-1 text-xs text-slate-500">定时执行和手动执行都会按这里配置的日期刷新；最近 N 天默认截至昨天，不刷新当天。</div>
                        </div>
                        <div className="inline-flex rounded-2xl border border-slate-200 bg-white p-1">
                          {[
                            ['relative', '最近 N 天'],
                            ['fixed', '固定日期'],
                          ].map(([mode, label]) => (
                            <button
                              key={mode}
                              type="button"
                              onClick={() => setScheduleDrafts((prev) => ({
                                ...prev,
                                [activeSetting.task_key]: {
                                  ...prev[activeSetting.task_key],
                                  date_range_mode: mode as 'relative' | 'fixed',
                                },
                              }))}
                              className={`rounded-xl px-3 py-2 text-xs font-bold transition ${
                                (activeDraft.date_range_mode || 'relative') === mode
                                  ? 'bg-slate-950 text-white shadow-sm'
                                  : 'text-slate-500 hover:bg-slate-50'
                              }`}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                      {(activeDraft.date_range_mode || 'relative') === 'fixed' ? (
                        <div className="mt-4 grid gap-3 sm:grid-cols-2">
                          <div>
                            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">开始日期</div>
                            <input
                              type="date"
                              value={activeDraft.start_date || ''}
                              onChange={(event) => setScheduleDrafts((prev) => ({
                                ...prev,
                                [activeSetting.task_key]: { ...prev[activeSetting.task_key], start_date: event.target.value },
                              }))}
                              className="mt-2 h-11 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                            />
                          </div>
                          <div>
                            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">结束日期</div>
                            <input
                              type="date"
                              value={activeDraft.end_date || ''}
                              onChange={(event) => setScheduleDrafts((prev) => ({
                                ...prev,
                                [activeSetting.task_key]: { ...prev[activeSetting.task_key], end_date: event.target.value },
                              }))}
                              className="mt-2 h-11 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                            />
                          </div>
                        </div>
                      ) : (
                        <div className="mt-4">
                          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">最近天数（截至昨天）</div>
                          <input
                            type="number"
                            min={1}
                            max={365}
                            value={activeDraft.days ?? 30}
                            onChange={(event) => setScheduleDrafts((prev) => ({
                              ...prev,
                              [activeSetting.task_key]: { ...prev[activeSetting.task_key], days: Number(event.target.value || 30) },
                            }))}
                            className="mt-2 h-11 w-full max-w-[220px] rounded-2xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800"
                          />
                        </div>
                      )}
                    </div>
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">报表类型</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {(activeSetting.config?.report_types || []).map((reportType) => (
                          <span key={`${activeSetting.task_key}-${reportType}`} className="rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-semibold text-slate-600">
                            {REPORT_TYPE_LABELS[reportType] || reportType}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                <div className="grid gap-3 sm:grid-cols-3">
                  {[
                    ['下次执行', activeSetting.next_run_at ? formatEventTime(activeSetting.next_run_at) : '未计划'],
                    ['上次执行', activeSetting.last_run_at ? formatEventTime(activeSetting.last_run_at) : '未执行'],
                    ['最近结果', activeSetting.last_message || '暂无记录'],
                  ].map(([label, value]) => (
                    <div key={`${activeSetting.task_key}-${label}`} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">{label}</div>
                      <div className={`mt-2 ${label === '最近结果' ? 'text-sm leading-6' : 'text-sm font-semibold'} text-slate-800`}>{value}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3 border-b border-slate-200 pb-3">
                  <div className="text-sm font-semibold text-slate-950">当前任务历史记录</div>
                  <div className="text-xs text-slate-500">最近 {activeTaskLogs.length} 条</div>
                </div>
                {activeTaskLogs.length === 0 ? (
                  <div className="py-6 text-sm text-slate-500">当前任务还没有执行记录</div>
                ) : (
                  <div className="mt-3 space-y-3">
                    {activeTaskLogs.slice(0, 12).map((log) => (
                      <div key={log.id} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${getScheduleStatusTone(log.status, log.status === 'running')}`}>
                            {getRunStatusLabel(log.status, log.status === 'running')}
                          </span>
                          <span className="text-xs text-slate-500">{getRunSourceLabel(log.source)}</span>
                          <span className="text-xs text-slate-400">{formatEventTime(log.started_at)}</span>
                          <span className="text-xs text-slate-400">至 {formatEventTime(log.finished_at)}</span>
                        </div>
                        <div className="mt-2 text-sm leading-6 text-slate-700">{log.message || '暂无记录'}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="sticky bottom-0 border-t border-slate-200 bg-white px-5 py-4">
              <div className="flex flex-wrap justify-end gap-2">
                <ScheduleToggleSwitch
                  checked={!!activeDraft.enabled}
                  loading={actionKey === `toggle-${activeSetting.task_key}`}
                  disabled={actionKey === `toggle-${activeSetting.task_key}`}
                  onToggle={() => handleToggleEnabled(activeSetting.task_key)}
                />
                <button
                  type="button"
                  onClick={() => handleSave(activeSetting.task_key)}
                  disabled={actionKey === `save-${activeSetting.task_key}` || !hasScheduleChanges(activeSetting.task_key)}
                  className="inline-flex h-11 items-center rounded-2xl bg-slate-950 px-4 text-sm font-semibold text-white transition-all hover:bg-slate-800 disabled:opacity-50"
                >
                  {actionKey === `save-${activeSetting.task_key}` ? '保存中...' : hasScheduleChanges(activeSetting.task_key) ? '保存配置' : '已保存'}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
