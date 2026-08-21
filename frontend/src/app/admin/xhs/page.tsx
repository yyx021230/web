'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '@/services/api';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';

interface XHSEnvironment {
  id: number;
  shop_id: string;
  account_name: string;
  profile_url?: string;
  sync_cloud_session_id?: string;
  sync_cloud_api_key?: string;
  sync_cloud_update_config?: string;
  sync_browser_start_config?: string;
  xhs_account_id?: string;
  login_phone_number?: string;
  xhs_account_type?: XHSAccountType | string;
  is_sync_runner?: boolean;
  notes?: string;
  group_name?: string;
  proxy_info?: string;
  labels?: string;
  department?: 'xhs' | 'brand' | string;
  status: string;
}

interface User {
  id: number;
  username: string;
  display_name?: string | null;
  email: string;
  role: string;
  roles?: string[];
}

interface BrowserEnvironmentStatus {
  environment_id: number;
  shop_id: string;
  account_name: string;
  browser_status: 'online' | 'offline' | 'busy' | 'error' | 'unknown' | string;
  is_online: boolean;
  checked_at?: string | null;
  source?: string | null;
  error?: string | null;
}

interface SyncRunnerBrowseOverview {
  date: string;
  days: number;
  total_views_today: number;
  runners: Array<{
    environment_id: number;
    account_name: string;
    assigned_notes: number;
    today_link_clicks: number;
    today_sync_views: number;
    today_total_views: number;
    today_executor_link_clicks: number;
    today_executor_sync_views: number;
    today_executor_total_views: number;
    timeline: Array<{
      date: string;
      link_clicks: number;
      sync_views: number;
      total_views: number;
      executor_link_clicks?: number;
      executor_sync_views?: number;
    }>;
  }>;
  recent_events: Array<{
    id: number;
    runner_environment_id: number;
    runner_account_name?: string | null;
    owner_runner_environment_id?: number | null;
    owner_runner_account_name?: string | null;
    note_id: number;
    note_feed_id?: string | null;
    note_title?: string | null;
    note_post_url?: string | null;
    source_environment_id?: number | null;
    source_account_name?: string | null;
    browse_source: string;
    job_id?: string | null;
    created_at?: string | null;
  }>;
}

type EnvFilterKey = 'all' | 'configured' | 'unconfigured' | 'sync_runner' | 'online' | 'offline' | 'unassigned';
type DepartmentKey = 'all' | 'xhs' | 'brand';
type XHSAccountType = 'enterprise_professional' | 'enterprise_employee' | 'personal';
type XHSAccountTypeFilter = 'all' | XHSAccountType;
type WorkbenchPanelKey = 'profile' | 'users' | 'browser' | 'activity';

const ENV_FILTER_OPTIONS: Array<{ key: EnvFilterKey; label: string }> = [
  { key: 'all', label: '全部环境' },
  { key: 'online', label: '在线' },
  { key: 'offline', label: '离线/未知' },
  { key: 'configured', label: '已配主页' },
  { key: 'unconfigured', label: '待配主页' },
  { key: 'sync_runner', label: '同步环境' },
  { key: 'unassigned', label: '未分配用户' },
];

const WORKBENCH_PANELS: Array<{ key: WorkbenchPanelKey; label: string; desc: string }> = [
  { key: 'profile', label: '采集配置', desc: '主页链接与历史参数' },
  { key: 'users', label: '运营负责人', desc: '账号归属' },
  { key: 'browser', label: '浏览器状态', desc: '在线探测与同步条件' },
  { key: 'activity', label: '同步监控', desc: '浏览流水与测试账号负载' },
];

function getUserRoleLabel(role?: string): string {
  if (role === 'admin') return '管理员';
  if (role === 'xhs_lead') return '小红书部门负责人';
  if (role === 'xhs_ops') return '小红书运营';
  if (role === 'buyer' || role === 'xhs_buyer') return '投手';
  if (role === 'brand_lead') return '品牌责任人';
  if (role === 'brand_ops') return '品牌运营';
  return '普通用户';
}

function normalizeDepartment(value?: string): Exclude<DepartmentKey, 'all'> {
  return value === 'brand' ? 'brand' : 'xhs';
}

function getDepartmentLabel(value?: string): string {
  return normalizeDepartment(value) === 'brand' ? '品牌' : '小红书';
}

function getDepartmentTone(value?: string, selected = false): string {
  if (selected) return 'bg-white/10 text-white';
  return normalizeDepartment(value) === 'brand'
    ? 'bg-sky-50 text-sky-700'
    : 'bg-violet-50 text-violet-700';
}

function normalizeXHSAccountType(value?: string): XHSAccountType {
  if (value === 'enterprise_employee' || value === 'personal') return value;
  return 'enterprise_professional';
}

function getXHSAccountTypeLabel(value?: string): string {
  const normalized = normalizeXHSAccountType(value);
  if (normalized === 'enterprise_employee') return '员工号';
  if (normalized === 'personal') return '个人号';
  return '企业号';
}

function getXHSAccountTypeTone(value?: string, selected = false): string {
  if (selected) return 'bg-white/10 text-white';
  const normalized = normalizeXHSAccountType(value);
  if (normalized === 'enterprise_employee') return 'bg-orange-50 text-orange-700';
  if (normalized === 'personal') return 'bg-sky-50 text-sky-700';
  return 'bg-emerald-50 text-emerald-700';
}

function userHasRole(user: { role?: string; roles?: string[] }, roles: string[]): boolean {
  return roles.includes(user.role || '') || roles.some((role) => user.roles?.includes(role));
}

function isSyncRunnerEnv(env: XHSEnvironment): boolean {
  return Boolean(env.is_sync_runner) || /测试[2345]/.test(env.account_name);
}

function getEnvConfigTone(env: XHSEnvironment): string {
  return env.profile_url
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : 'border-amber-200 bg-amber-50 text-amber-700';
}

function getBrowserStatusLabel(status?: string): string {
  if (status === 'online') return '浏览器在线';
  if (status === 'offline') return '浏览器离线';
  if (status === 'busy') return '浏览器占用';
  if (status === 'error') return '连接异常';
  return '状态未知';
}

function getBrowserStatusTone(status?: string, selected = false): string {
  if (selected) return 'border-white/15 bg-white/10 text-white';
  if (status === 'online') return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  if (status === 'offline') return 'border-slate-200 bg-slate-100 text-slate-500';
  if (status === 'busy') return 'border-amber-200 bg-amber-50 text-amber-700';
  if (status === 'error') return 'border-red-200 bg-red-50 text-red-700';
  return 'border-slate-200 bg-white text-slate-500';
}

function getBrowserDotTone(status?: string): string {
  if (status === 'online') return 'bg-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,0.14)]';
  if (status === 'busy') return 'bg-amber-500 shadow-[0_0_0_4px_rgba(245,158,11,0.14)]';
  if (status === 'error') return 'bg-red-500 shadow-[0_0_0_4px_rgba(239,68,68,0.14)]';
  return 'bg-slate-300';
}

function buildEnvSearchText(env: XHSEnvironment): string {
  return [
    env.account_name,
    env.shop_id,
    env.xhs_account_id,
    env.login_phone_number,
    env.notes,
    env.group_name,
    env.proxy_info,
    env.labels,
    getXHSAccountTypeLabel(env.xhs_account_type),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

function getBrowseSourceLabel(source: string): string {
  if (source === 'link_click') return '点开链接';
  if (source === 'single_sync') return '单条同步';
  if (source === 'bulk_sync') return '批量同步';
  return source || '未知来源';
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

function formatBrowserCheckedAt(value?: string | null): string {
  if (!value) return '未刷新';
  return formatEventTime(value);
}

export default function AdminXhsPage() {
  const [envs, setEnvs] = useState<XHSEnvironment[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [assignments, setAssignments] = useState<{ user_id: number; environment_id: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [actionKey, setActionKey] = useState<string | null>(null);
  const [profileDrafts, setProfileDrafts] = useState<Record<number, string>>({});
  const [syncCloudSessionDrafts, setSyncCloudSessionDrafts] = useState<Record<number, string>>({});
  const [syncCloudApiKeyDrafts, setSyncCloudApiKeyDrafts] = useState<Record<number, string>>({});
  const [syncCloudUpdateConfigDrafts, setSyncCloudUpdateConfigDrafts] = useState<Record<number, string>>({});
  const [syncBrowserConfigDrafts, setSyncBrowserConfigDrafts] = useState<Record<number, string>>({});
  const [xhsAccountIdDrafts, setXhsAccountIdDrafts] = useState<Record<number, string>>({});
  const [loginPhoneDrafts, setLoginPhoneDrafts] = useState<Record<number, string>>({});
  const [accountTypeDrafts, setAccountTypeDrafts] = useState<Record<number, XHSAccountType>>({});
  const [departmentDrafts, setDepartmentDrafts] = useState<Record<number, Exclude<DepartmentKey, 'all'>>>({});
  const [savingProfileId, setSavingProfileId] = useState<number | null>(null);
  const [selectedEnvId, setSelectedEnvId] = useState<number | null>(null);
  const [envQuery, setEnvQuery] = useState('');
  const [envFilter, setEnvFilter] = useState<EnvFilterKey>('all');
  const [departmentFilter, setDepartmentFilter] = useState<DepartmentKey>('xhs');
  const [accountTypeFilter, setAccountTypeFilter] = useState<XHSAccountTypeFilter>('all');
  const [activePanel, setActivePanel] = useState<WorkbenchPanelKey>('profile');
  const [browseOverview, setBrowseOverview] = useState<SyncRunnerBrowseOverview | null>(null);
  const [browserStatuses, setBrowserStatuses] = useState<BrowserEnvironmentStatus[]>([]);
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [envRes, userRes, assignRes, browseRes, browserStatusRes] = await Promise.all([
        api.get('/xhs/environments').catch(() => null),
        adminApi.getUsers(1, 100),
        api.get('/admin/xhs/assignments'),
        api.get('/admin/xhs/sync-runner-browse-overview', { params: { days: 7, limit: 60 } }).catch(() => null),
        api.get('/admin/xhs/browser-statuses').catch(() => null),
      ]);
      const nextEnvs = (envRes?.data || []) as XHSEnvironment[];
      setEnvs(nextEnvs);
      setProfileDrafts(Object.fromEntries(nextEnvs.map((env) => [env.id, env.profile_url || ''])));
      setSyncCloudSessionDrafts(Object.fromEntries(nextEnvs.map((env) => [env.id, env.sync_cloud_session_id || ''])));
      setSyncCloudApiKeyDrafts(Object.fromEntries(nextEnvs.map((env) => [env.id, env.sync_cloud_api_key || ''])));
      setSyncCloudUpdateConfigDrafts(Object.fromEntries(nextEnvs.map((env) => [env.id, env.sync_cloud_update_config || ''])));
      setSyncBrowserConfigDrafts(Object.fromEntries(nextEnvs.map((env) => [env.id, env.sync_browser_start_config || ''])));
      setXhsAccountIdDrafts(Object.fromEntries(nextEnvs.map((env) => [env.id, env.xhs_account_id || ''])));
      setLoginPhoneDrafts(Object.fromEntries(nextEnvs.map((env) => [env.id, env.login_phone_number || ''])));
      setAccountTypeDrafts(Object.fromEntries(nextEnvs.map((env) => [env.id, normalizeXHSAccountType(env.xhs_account_type)])));
      setDepartmentDrafts(Object.fromEntries(nextEnvs.map((env) => [env.id, normalizeDepartment(env.department)])));
      setUsers(userRes?.data?.items || []);
      setAssignments(assignRes?.data || []);
      setBrowseOverview((browseRes?.data || null) as SyncRunnerBrowseOverview | null);
      setBrowserStatuses((browserStatusRes?.data || []) as BrowserEnvironmentStatus[]);
    } catch (err: any) {
      toast.error(`获取数据失败: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const assignmentsByEnv = useMemo(() => {
    const map = new Map<number, number[]>();
    assignments.forEach((item) => {
      map.set(item.environment_id, [item.user_id]);
    });
    return map;
  }, [assignments]);

  const userById = useMemo(() => {
    return new Map(users.map((user) => [user.id, user]));
  }, [users]);

  const getEnvironmentOwnerName = useCallback((envId: number) => {
    const userId = assignmentsByEnv.get(envId)?.[0];
    if (!userId) return '';
    const user = userById.get(userId);
    if (!user) return `用户 #${userId}`;
    return user.display_name || user.username || `用户 #${userId}`;
  }, [assignmentsByEnv, userById]);

  const browserStatusByEnv = useMemo(() => {
    return new Map(browserStatuses.map((item) => [item.environment_id, item]));
  }, [browserStatuses]);

  const filteredEnvs = useMemo(() => {
    const normalizedQuery = envQuery.trim().toLowerCase();
    return envs.filter((env) => {
      const assignedCount = assignmentsByEnv.get(env.id)?.length || 0;
      const browserStatus = browserStatusByEnv.get(env.id)?.browser_status || 'unknown';
      if (envFilter === 'configured' && !env.profile_url) return false;
      if (envFilter === 'unconfigured' && env.profile_url) return false;
      if (envFilter === 'sync_runner' && !isSyncRunnerEnv(env)) return false;
      if (envFilter === 'online' && browserStatus !== 'online') return false;
      if (envFilter === 'offline' && browserStatus === 'online') return false;
      if (envFilter === 'unassigned' && assignedCount > 0) return false;
      if (departmentFilter !== 'all' && normalizeDepartment(env.department) !== departmentFilter) return false;
      if (accountTypeFilter !== 'all' && normalizeXHSAccountType(env.xhs_account_type) !== accountTypeFilter) return false;
      if (normalizedQuery && !buildEnvSearchText(env).includes(normalizedQuery)) return false;
      return true;
    });
  }, [accountTypeFilter, assignmentsByEnv, browserStatusByEnv, departmentFilter, envFilter, envQuery, envs]);

  useEffect(() => {
    if (filteredEnvs.length === 0) {
      if (selectedEnvId !== null) setSelectedEnvId(null);
      return;
    }
    const exists = filteredEnvs.some((env) => env.id === selectedEnvId);
    if (!exists) setSelectedEnvId(filteredEnvs[0].id);
  }, [filteredEnvs, selectedEnvId]);

  const selectedEnv = useMemo(
    () => envs.find((env) => env.id === selectedEnvId) || null,
    [envs, selectedEnvId],
  );

  const selectedAssignedUserIds = useMemo(
    () => new Set(selectedEnv ? assignmentsByEnv.get(selectedEnv.id) || [] : []),
    [assignmentsByEnv, selectedEnv],
  );

  const selectedOwnerUserId = useMemo(
    () => selectedEnv ? assignmentsByEnv.get(selectedEnv.id)?.[0] || null : null,
    [assignmentsByEnv, selectedEnv],
  );

  const selectedOwnerUser = useMemo(
    () => users.find((user) => user.id === selectedOwnerUserId) || null,
    [selectedOwnerUserId, users],
  );

  const assignableUsers = useMemo(() => {
    const departmentRoles = normalizeDepartment(selectedEnv?.department) === 'brand'
      ? ['brand_lead', 'brand_ops']
      : ['xhs_lead', 'xhs_ops'];
    return users.filter((user) => userHasRole(user, departmentRoles));
  }, [selectedEnv?.department, users]);

  const selectedBrowserStatus = selectedEnv ? browserStatusByEnv.get(selectedEnv.id) : undefined;
  const selectedRunnerOverview = useMemo(
    () => selectedEnv ? browseOverview?.runners.find((runner) => runner.environment_id === selectedEnv.id) || null : null,
    [browseOverview, selectedEnv],
  );
  const selectedRecentEvents = useMemo(() => {
    if (!selectedEnv) return [];
    return (browseOverview?.recent_events || []).filter((event) => (
      event.runner_environment_id === selectedEnv.id
      || event.owner_runner_environment_id === selectedEnv.id
      || event.source_environment_id === selectedEnv.id
    ));
  }, [browseOverview, selectedEnv]);

  const hasDraftChanges = useMemo(() => {
    if (!selectedEnv) return false;
    return (
      (profileDrafts[selectedEnv.id] || '') !== (selectedEnv.profile_url || '') ||
      (syncCloudSessionDrafts[selectedEnv.id] || '') !== (selectedEnv.sync_cloud_session_id || '') ||
      (syncCloudApiKeyDrafts[selectedEnv.id] || '') !== (selectedEnv.sync_cloud_api_key || '') ||
      (syncCloudUpdateConfigDrafts[selectedEnv.id] || '') !== (selectedEnv.sync_cloud_update_config || '') ||
      (syncBrowserConfigDrafts[selectedEnv.id] || '') !== (selectedEnv.sync_browser_start_config || '') ||
      (xhsAccountIdDrafts[selectedEnv.id] || '') !== (selectedEnv.xhs_account_id || '') ||
      (loginPhoneDrafts[selectedEnv.id] || '') !== (selectedEnv.login_phone_number || '') ||
      (accountTypeDrafts[selectedEnv.id] || 'enterprise_professional') !== normalizeXHSAccountType(selectedEnv.xhs_account_type) ||
      (departmentDrafts[selectedEnv.id] || 'xhs') !== normalizeDepartment(selectedEnv.department)
    );
  }, [
    profileDrafts,
    accountTypeDrafts,
    departmentDrafts,
    loginPhoneDrafts,
    selectedEnv,
    syncBrowserConfigDrafts,
    syncCloudApiKeyDrafts,
    syncCloudSessionDrafts,
    syncCloudUpdateConfigDrafts,
    xhsAccountIdDrafts,
  ]);

  const stats = useMemo(() => {
    const configured = envs.filter((env) => !!env.profile_url).length;
    const syncRunner = envs.filter((env) => isSyncRunnerEnv(env)).length;
    const assigned = envs.filter((env) => (assignmentsByEnv.get(env.id)?.length || 0) > 0).length;
    const online = browserStatuses.filter((item) => item.browser_status === 'online').length;
    const errors = browserStatuses.filter((item) => item.browser_status === 'error').length;
    const xhs = envs.filter((env) => normalizeDepartment(env.department) === 'xhs').length;
    const brand = envs.filter((env) => normalizeDepartment(env.department) === 'brand').length;
    const enterprise = envs.filter((env) => normalizeXHSAccountType(env.xhs_account_type) === 'enterprise_professional').length;
    const employee = envs.filter((env) => normalizeXHSAccountType(env.xhs_account_type) === 'enterprise_employee').length;
    const personal = envs.filter((env) => normalizeXHSAccountType(env.xhs_account_type) === 'personal').length;
    return {
      total: envs.length,
      configured,
      unconfigured: envs.length - configured,
      syncRunner,
      online,
      errors,
      assigned,
      unassigned: envs.length - assigned,
      xhs,
      brand,
      enterprise,
      employee,
      personal,
    };
  }, [assignmentsByEnv, browserStatuses, envs]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await api.post('/admin/xhs/sync-environments');
      toast.success(`环境同步完成: ${res.data?.synced_count || 0} 条`);
      await fetchData();
    } catch (err: any) {
      toast.error(`同步失败: ${err.message}`);
    } finally {
      setSyncing(false);
    }
  };

  const isAssigned = (userId: number, envId: number) => {
    return assignmentsByEnv.get(envId)?.[0] === userId;
  };

  const handleToggle = async (userId: number, envId: number) => {
    const key = `${userId}-${envId}`;
    setActionKey(key);
    try {
      if (isAssigned(userId, envId)) {
        await api.post('/admin/xhs/unassign', { user_id: userId, environment_id: envId });
        toast.success('已移除负责人');
      } else {
        await api.post('/admin/xhs/assign', { user_id: userId, environment_id: envId });
        toast.success('负责人已更新');
      }
      await fetchData();
    } catch (err: any) {
      toast.error(`操作失败: ${err.message}`);
    } finally {
      setActionKey(null);
    }
  };

  const resetSelectedDrafts = useCallback(() => {
    if (!selectedEnv) return;
    setProfileDrafts((prev) => ({ ...prev, [selectedEnv.id]: selectedEnv.profile_url || '' }));
    setSyncCloudSessionDrafts((prev) => ({ ...prev, [selectedEnv.id]: selectedEnv.sync_cloud_session_id || '' }));
    setSyncCloudApiKeyDrafts((prev) => ({ ...prev, [selectedEnv.id]: selectedEnv.sync_cloud_api_key || '' }));
    setSyncCloudUpdateConfigDrafts((prev) => ({ ...prev, [selectedEnv.id]: selectedEnv.sync_cloud_update_config || '' }));
    setSyncBrowserConfigDrafts((prev) => ({ ...prev, [selectedEnv.id]: selectedEnv.sync_browser_start_config || '' }));
    setXhsAccountIdDrafts((prev) => ({ ...prev, [selectedEnv.id]: selectedEnv.xhs_account_id || '' }));
    setLoginPhoneDrafts((prev) => ({ ...prev, [selectedEnv.id]: selectedEnv.login_phone_number || '' }));
    setAccountTypeDrafts((prev) => ({ ...prev, [selectedEnv.id]: normalizeXHSAccountType(selectedEnv.xhs_account_type) }));
    setDepartmentDrafts((prev) => ({ ...prev, [selectedEnv.id]: normalizeDepartment(selectedEnv.department) }));
  }, [selectedEnv]);

  const handleSaveProfileUrl = async (envId: number) => {
    setSavingProfileId(envId);
    try {
      await api.post('/admin/xhs/profile-url', {
        environment_id: envId,
        profile_url: (profileDrafts[envId] || '').trim(),
        sync_cloud_session_id: (syncCloudSessionDrafts[envId] || '').trim(),
        sync_cloud_api_key: (syncCloudApiKeyDrafts[envId] || '').trim(),
        sync_cloud_update_config: (syncCloudUpdateConfigDrafts[envId] || '').trim(),
        sync_browser_start_config: (syncBrowserConfigDrafts[envId] || '').trim(),
        xhs_account_id: (xhsAccountIdDrafts[envId] || '').trim(),
        login_phone_number: (loginPhoneDrafts[envId] || '').trim(),
        xhs_account_type: accountTypeDrafts[envId] || 'enterprise_professional',
        department: departmentDrafts[envId] || 'xhs',
      });
      toast.success('配置已保存');
      await fetchData();
    } catch (err: any) {
      toast.error(`保存失败: ${err.message}`);
    } finally {
      setSavingProfileId(null);
    }
  };

  const handleToggleSyncRunner = async (env: XHSEnvironment) => {
    setActionKey(`sync-runner-${env.id}`);
    try {
      await api.post('/admin/xhs/sync-runner', {
        environment_id: env.id,
        is_sync_runner: !isSyncRunnerEnv(env),
      });
      toast.success(!isSyncRunnerEnv(env) ? '已设为同步环境' : '已取消同步环境');
      await fetchData();
    } catch (err: any) {
      toast.error(`设置失败: ${err.message}`);
    } finally {
      setActionKey(null);
    }
  };

  const handleRefreshBrowserStatuses = async () => {
    setActionKey('refresh-browser-statuses');
    try {
      const res = await api.get('/admin/xhs/browser-statuses', { params: { refresh: true } });
      setBrowserStatuses((res.data || []) as BrowserEnvironmentStatus[]);
      toast.success('浏览器在线状态已刷新');
    } catch (err: any) {
      toast.error(`刷新失败: ${err.message}`);
    } finally {
      setActionKey(null);
    }
  };

  const handleRefreshSelectedBrowserStatus = async (envId: number) => {
    setActionKey(`refresh-browser-${envId}`);
    try {
      const res = await api.post(`/admin/xhs/browser-status/${envId}/refresh`);
      const nextStatus = res.data as BrowserEnvironmentStatus;
      setBrowserStatuses((prev) => {
        const others = prev.filter((item) => item.environment_id !== envId);
        return [...others, nextStatus];
      });
      toast.success(`${nextStatus.account_name}：${getBrowserStatusLabel(nextStatus.browser_status)}`);
    } catch (err: any) {
      toast.error(`刷新失败: ${err.message}`);
    } finally {
      setActionKey(null);
    }
  };

  return (
    <div className="min-h-screen bg-[#f4f3ef] text-slate-950">
      <div className="mx-auto max-w-[1760px] px-5 py-5">
        <header className="overflow-hidden rounded-[28px] border border-slate-200 bg-[#10141f] text-white shadow-[0_22px_70px_rgba(15,23,42,0.22)]">
          <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
            <div>
              <div className="inline-flex rounded-full border border-white/15 bg-white/8 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-white/70">
                XHS Environment Ops
              </div>
              <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em]">小红书账号管理</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-white/62">
                小红书与品牌是独立账号部门。这里集中处理账号归属、主页采集、同步账号标记和对应部门负责人分配。
              </p>
            </div>
            <div className="flex flex-wrap gap-2 lg:justify-end">
              <button
                className="inline-flex h-11 items-center rounded-2xl border border-emerald-400/30 bg-emerald-400/12 px-4 text-sm font-semibold text-emerald-100 transition-all hover:bg-emerald-400/18 disabled:opacity-50"
                onClick={handleRefreshBrowserStatuses}
                disabled={actionKey === 'refresh-browser-statuses'}
              >
                {actionKey === 'refresh-browser-statuses' ? '探测中...' : '刷新在线状态'}
              </button>
              <button
                className="inline-flex h-11 items-center rounded-2xl border border-white/14 bg-white/8 px-4 text-sm font-semibold text-white transition-all hover:bg-white/12 disabled:opacity-50"
                onClick={fetchData}
                disabled={loading}
              >
                {loading ? '刷新中...' : '刷新数据'}
              </button>
              <button
                className="inline-flex h-11 items-center rounded-2xl bg-white px-4 text-sm font-semibold text-slate-950 transition-all hover:-translate-y-0.5 hover:bg-slate-100 disabled:opacity-50"
                onClick={handleSync}
                disabled={syncing}
              >
                {syncing ? '同步中...' : '从云登同步环境'}
              </button>
            </div>
          </div>
          <div className="grid border-t border-white/10 bg-white/[0.03] sm:grid-cols-3 xl:grid-cols-8">
            {[
              ['总环境', stats.total, '全部云登环境'],
              ['小红书', stats.xhs, '小红书部门'],
              ['品牌', stats.brand, '品牌部门'],
              ['在线', stats.online, '可执行同步'],
              ['异常', stats.errors, '需人工检查'],
              ['同步环境', stats.syncRunner, '测试账号池'],
              ['待配主页', stats.unconfigured, '缺主页链接'],
              ['未分配', stats.unassigned, '无负责人'],
            ].map(([label, value, desc]) => (
              <div key={String(label)} className="border-b border-r border-white/10 px-5 py-4 last:border-r-0 xl:border-b-0">
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/42">{label}</div>
                <div className="mt-1 text-3xl font-semibold tracking-[-0.05em] text-white">{value}</div>
                <div className="mt-1 text-xs text-white/42">{desc}</div>
              </div>
            ))}
          </div>
        </header>

        <section className="mt-5 overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_16px_50px_rgba(15,23,42,0.08)]">
          <div className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">Task Schedules</div>
              <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em] text-slate-950">定时任务已独立管理</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
                账户同步、投流回刷、主页帖子同步、内容打标和未同步策略，现在统一在单独页面维护，避免这里和配置页重复。
              </p>
            </div>
            <Link
              href="/admin/xhs-schedules"
              className="inline-flex h-11 items-center justify-center rounded-2xl bg-slate-950 px-4 text-sm font-semibold text-white transition-all hover:bg-slate-800"
            >
              打开定时任务页
            </Link>
          </div>
        </section>

        <section className="mt-5 overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_16px_50px_rgba(15,23,42,0.08)]">
          <div className="grid gap-4 border-b border-slate-200 bg-[#fbfaf7] p-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">Runner Monitor</div>
              <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em] text-slate-950">测试账号浏览记录</h2>
              <p className="mt-1 text-sm leading-6 text-slate-500">
                全局查看所有测试账号名下链接浏览、同步执行和最近流水；右侧工作台里的“同步监控”只看当前选中环境。
              </p>
            </div>
            <div className="rounded-2xl bg-slate-950 px-5 py-3 text-right text-white">
              <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-white/42">名下链接今日总浏览</div>
              <div className="mt-1 text-2xl font-semibold tracking-[-0.04em]">{browseOverview?.total_views_today ?? 0}</div>
            </div>
          </div>

          <div className="grid gap-0 xl:grid-cols-[minmax(0,1fr)_430px]">
            <div className="border-b border-slate-200 p-4 xl:border-b-0 xl:border-r">
              {(browseOverview?.runners || []).length === 0 ? (
                <div className="grid min-h-[180px] place-items-center rounded-[24px] border border-dashed border-slate-200 bg-[#fbfaf7] text-sm text-slate-400">
                  还没有测试账号浏览记录
                </div>
              ) : (
                <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
                  {(browseOverview?.runners || []).map((runner) => {
                    const browserStatus = browserStatusByEnv.get(runner.environment_id);
                    return (
                      <div key={`runner-overview-${runner.environment_id}`} className="rounded-[24px] border border-slate-200 bg-[#fbfaf7] p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className={`h-2.5 w-2.5 rounded-full ${getBrowserDotTone(browserStatus?.browser_status)}`} />
                              <div className="truncate text-sm font-semibold text-slate-950">{runner.account_name}</div>
                            </div>
                            <div className="mt-1 text-xs text-slate-400">名下 {runner.assigned_notes} 条</div>
                          </div>
                          <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${getBrowserStatusTone(browserStatus?.browser_status)}`}>
                            {getBrowserStatusLabel(browserStatus?.browser_status)}
                          </span>
                        </div>
                        <div className="mt-4 grid grid-cols-4 gap-2 text-center">
                          {[
                            ['浏览', runner.today_total_views],
                            ['点开', runner.today_link_clicks],
                            ['名下同步', runner.today_sync_views],
                            ['执行同步', runner.today_executor_sync_views],
                          ].map(([label, value]) => (
                            <div key={`${runner.environment_id}-${label}`} className="rounded-2xl bg-white px-2 py-3">
                              <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{label}</div>
                              <div className="mt-1 text-lg font-semibold text-slate-950">{value}</div>
                            </div>
                          ))}
                        </div>
                        <div className="mt-3 space-y-1.5">
                          {runner.timeline.slice(-3).map((item) => (
                            <div key={`${runner.environment_id}-${item.date}`} className="flex items-center justify-between rounded-xl bg-white px-3 py-2 text-xs text-slate-500">
                              <span>{item.date}</span>
                              <span className="font-semibold text-slate-900">{item.total_views}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="bg-[#fbfaf7] p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-slate-950">最近浏览流水</div>
                  <div className="mt-1 text-xs text-slate-400">最近 {Math.min(browseOverview?.recent_events?.length || 0, 60)} 条</div>
                </div>
              </div>
              <div className="mt-3 max-h-[430px] space-y-2 overflow-y-auto pr-1">
                {(browseOverview?.recent_events || []).map((event) => (
                  <div key={`browse-event-${event.id}`} className="rounded-2xl border border-slate-200 bg-white px-3 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-slate-900">
                          {event.note_title || event.note_feed_id || `笔记 #${event.note_id}`}
                        </div>
                        <div className="mt-1 truncate text-xs text-slate-500">
                          {event.source_account_name || '未知账号'} · 执行 {event.runner_account_name || '未识别测试账号'}
                          {(event.owner_runner_account_name || event.owner_runner_environment_id) ? ` · 归属 ${event.owner_runner_account_name || `测试账号 #${event.owner_runner_environment_id}`}` : ''}
                        </div>
                      </div>
                      <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600">
                        {getBrowseSourceLabel(event.browse_source)}
                      </span>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-3 text-xs text-slate-400">
                      <span>{formatEventTime(event.created_at)}</span>
                      {event.note_post_url ? (
                        <a href={event.note_post_url} target="_blank" rel="noreferrer" className="font-semibold text-slate-900 hover:underline">
                          打开链接
                        </a>
                      ) : (
                        <span>{event.note_feed_id || '-'}</span>
                      )}
                    </div>
                  </div>
                ))}
                {(browseOverview?.recent_events || []).length === 0 && (
                  <div className="rounded-2xl border border-dashed border-slate-200 bg-white py-12 text-center text-sm text-slate-400">
                    暂无浏览流水
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>

        <main className="mt-5 grid gap-5 xl:grid-cols-[430px_minmax(0,1fr)]">
          <aside className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_16px_50px_rgba(15,23,42,0.08)] xl:sticky xl:top-5 xl:max-h-[calc(100vh-40px)]">
            <div className="border-b border-slate-200 bg-[#fbfaf7] p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-slate-950">环境目录</div>
                  <div className="mt-1 text-xs text-slate-500">{filteredEnvs.length} / {envs.length} 个环境</div>
                </div>
                <span className="rounded-full bg-slate-900 px-3 py-1 text-[11px] font-semibold text-white">
                  {envFilter === 'all' ? '全部' : ENV_FILTER_OPTIONS.find((item) => item.key === envFilter)?.label}
                </span>
              </div>
              <input
                type="text"
                value={envQuery}
                onChange={(event) => setEnvQuery(event.target.value)}
                placeholder="搜索账号、shop_id、备注、分组"
                className="mt-4 h-11 w-full rounded-2xl border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none transition-all placeholder:text-slate-400 focus:border-slate-400 focus:ring-4 focus:ring-slate-100"
              />
              <div className="mt-3 grid grid-cols-3 gap-2 rounded-2xl bg-slate-100 p-1">
                {([
                  ['xhs', `小红书 ${stats.xhs}`],
                  ['brand', `品牌 ${stats.brand}`],
                  ['all', `全部 ${stats.total}`],
                ] as Array<[DepartmentKey, string]>).map(([department, label]) => (
                  <button
                    key={department}
                    type="button"
                    onClick={() => setDepartmentFilter(department)}
                    className={`rounded-xl px-2 py-2 text-xs font-semibold transition-all ${
                      departmentFilter === department
                        ? 'bg-slate-950 text-white shadow-sm'
                        : 'text-slate-500 hover:bg-white hover:text-slate-900'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="mt-3 grid grid-cols-4 gap-1 rounded-2xl bg-slate-100 p-1">
                {([
                  ['all', `全部 ${stats.total}`],
                  ['enterprise_professional', `企业号 ${stats.enterprise}`],
                  ['enterprise_employee', `员工号 ${stats.employee}`],
                  ['personal', `个人号 ${stats.personal}`],
                ] as Array<[XHSAccountTypeFilter, string]>).map(([accountType, label]) => (
                  <button
                    key={accountType}
                    type="button"
                    onClick={() => setAccountTypeFilter(accountType)}
                    className={`rounded-xl px-1.5 py-2 text-[11px] font-semibold transition-all ${
                      accountTypeFilter === accountType
                        ? 'bg-white text-slate-950 shadow-sm'
                        : 'text-slate-500 hover:bg-white/70 hover:text-slate-900'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {ENV_FILTER_OPTIONS.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => setEnvFilter(option.key)}
                    className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-all ${
                      envFilter === option.key
                        ? 'bg-slate-950 text-white shadow-[0_10px_20px_rgba(15,23,42,0.14)]'
                        : 'border border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-950'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="max-h-[calc(100vh-300px)] overflow-y-auto p-3">
              {loading ? (
                <div className="grid place-items-center py-12 text-sm text-slate-400">加载中...</div>
              ) : filteredEnvs.length === 0 ? (
                <div className="grid place-items-center rounded-[24px] border border-dashed border-slate-200 bg-slate-50 py-12 text-sm text-slate-400">
                  没找到符合条件的环境
                </div>
              ) : (
                <div className="space-y-2">
                  {filteredEnvs.map((env) => {
                    const assignedCount = assignmentsByEnv.get(env.id)?.length || 0;
                    const ownerName = getEnvironmentOwnerName(env.id);
                    const browserStatus = browserStatusByEnv.get(env.id);
                    const selected = env.id === selectedEnvId;
                    return (
                      <button
                        key={env.id}
                        type="button"
                        onClick={() => setSelectedEnvId(env.id)}
                        className={`w-full rounded-[22px] border px-4 py-3 text-left transition-all ${
                          selected
                            ? 'border-slate-950 bg-slate-950 text-white shadow-[0_18px_38px_rgba(15,23,42,0.2)]'
                            : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-[#fbfaf7]'
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${getBrowserDotTone(browserStatus?.browser_status)}`} />
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <span className="truncate text-sm font-semibold">{env.account_name}</span>
                              {isSyncRunnerEnv(env) ? (
                                <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${selected ? 'bg-white/12 text-white' : 'bg-slate-100 text-slate-600'}`}>
                                  同步
                                </span>
                              ) : null}
                            </span>
                            <span className={`mt-1 block truncate text-[11px] ${selected ? 'text-white/58' : 'text-slate-400'}`}>{env.shop_id}</span>
                            <span className="mt-2 flex flex-wrap gap-1.5">
                              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${selected ? 'bg-white/10 text-white' : env.xhs_account_id ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-500'}`}>
                                {env.xhs_account_id ? `ID：${env.xhs_account_id}` : '缺小红书 ID'}
                              </span>
                              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${selected ? 'bg-white/10 text-white' : env.profile_url ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                                {env.profile_url ? '主页' : '缺主页'}
                              </span>
                              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${getDepartmentTone(env.department, selected)}`}>
                                {getDepartmentLabel(env.department)}
                              </span>
                              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${getXHSAccountTypeTone(env.xhs_account_type, selected)}`}>
                                {getXHSAccountTypeLabel(env.xhs_account_type)}
                              </span>
                              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${selected ? 'bg-white/10 text-white' : 'bg-slate-100 text-slate-600'}`}>
                                {getBrowserStatusLabel(browserStatus?.browser_status)}
                              </span>
                              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${selected ? 'bg-white/10 text-white' : 'bg-slate-100 text-slate-600'}`}>
                                {assignedCount > 0 ? `负责人：${ownerName || '未找到用户'}` : '无负责人'}
                              </span>
                            </span>
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </aside>

          <section className="min-w-0">
            {!selectedEnv ? (
              <div className="grid min-h-[520px] place-items-center rounded-[28px] border border-dashed border-slate-300 bg-white text-slate-400">
                先从左侧选择一个环境
              </div>
            ) : (
              <div className="space-y-5">
                <div className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_16px_50px_rgba(15,23,42,0.08)]">
                  <div className="grid gap-5 border-b border-slate-200 bg-[#fbfaf7] p-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="truncate text-2xl font-semibold tracking-[-0.04em] text-slate-950">{selectedEnv.account_name}</h2>
                        <span className={`rounded-full border px-3 py-1 text-[11px] font-bold ${getBrowserStatusTone(selectedBrowserStatus?.browser_status)}`}>
                          {getBrowserStatusLabel(selectedBrowserStatus?.browser_status)}
                        </span>
                        <span className={`rounded-full px-3 py-1 text-[11px] font-bold ${getDepartmentTone(selectedEnv.department)}`}>
                          {getDepartmentLabel(selectedEnv.department)}部门
                        </span>
                        <span className="rounded-full bg-amber-50 px-3 py-1 text-[11px] font-bold text-amber-700">
                          {getXHSAccountTypeLabel(selectedEnv.xhs_account_type)}
                        </span>
                        {isSyncRunnerEnv(selectedEnv) ? (
                          <span className="rounded-full bg-slate-950 px-3 py-1 text-[11px] font-bold text-white">同步环境</span>
                        ) : null}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                        <span className="rounded-full bg-white px-3 py-1">shop_id: {selectedEnv.shop_id}</span>
                        <span className="rounded-full bg-white px-3 py-1">小红书 ID: {selectedEnv.xhs_account_id || '未配置'}</span>
                        <span className="rounded-full bg-white px-3 py-1">{selectedEnv.group_name || '未分组'}</span>
                        <span className="rounded-full bg-white px-3 py-1">{selectedEnv.notes || '无备注'}</span>
                        <span className="rounded-full bg-white px-3 py-1">{selectedEnv.proxy_info || '未记录代理'}</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2 lg:justify-end">
                      {selectedEnv.profile_url ? (
                        <a
                          href={selectedEnv.profile_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex h-10 items-center rounded-2xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 transition-all hover:border-slate-300 hover:bg-slate-50"
                        >
                          打开主页
                        </a>
                      ) : null}
                      <button
                        type="button"
                        className="inline-flex h-10 items-center rounded-2xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 transition-all hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
                        onClick={() => handleRefreshSelectedBrowserStatus(selectedEnv.id)}
                        disabled={actionKey === `refresh-browser-${selectedEnv.id}`}
                      >
                        {actionKey === `refresh-browser-${selectedEnv.id}` ? '探测中...' : '刷新此环境'}
                      </button>
                      <button
                        type="button"
                        className={`inline-flex h-10 items-center rounded-2xl px-3 text-xs font-semibold transition-all disabled:opacity-50 ${
                          isSyncRunnerEnv(selectedEnv)
                            ? 'bg-slate-200 text-slate-700 hover:bg-slate-300'
                            : 'bg-slate-950 text-white hover:bg-slate-800'
                        }`}
                        onClick={() => handleToggleSyncRunner(selectedEnv)}
                        disabled={actionKey === `sync-runner-${selectedEnv.id}`}
                      >
                        {actionKey === `sync-runner-${selectedEnv.id}` ? '处理中...' : isSyncRunnerEnv(selectedEnv) ? '取消同步环境' : '设为同步环境'}
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-10 items-center rounded-2xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition-all hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
                        onClick={resetSelectedDrafts}
                        disabled={!hasDraftChanges || savingProfileId === selectedEnv.id}
                      >
                        撤销
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-10 items-center rounded-2xl bg-emerald-600 px-4 text-xs font-semibold text-white transition-all hover:bg-emerald-700 disabled:opacity-50"
                        onClick={() => handleSaveProfileUrl(selectedEnv.id)}
                        disabled={!hasDraftChanges || savingProfileId === selectedEnv.id}
                      >
                        {savingProfileId === selectedEnv.id ? '保存中...' : hasDraftChanges ? '保存修改' : '已保存'}
                      </button>
                    </div>
                  </div>

                  <div className="grid border-b border-slate-200 bg-white md:grid-cols-4">
                    {WORKBENCH_PANELS.map((panel) => (
                      <button
                        key={panel.key}
                        type="button"
                        onClick={() => setActivePanel(panel.key)}
                        className={`border-b px-5 py-4 text-left transition-all md:border-b-0 md:border-r md:last:border-r-0 ${
                          activePanel === panel.key
                            ? 'border-slate-950 bg-slate-950 text-white'
                            : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                        }`}
                      >
                        <div className="text-sm font-semibold">{panel.label}</div>
                        <div className={`mt-1 text-xs ${activePanel === panel.key ? 'text-white/52' : 'text-slate-400'}`}>{panel.desc}</div>
                      </button>
                    ))}
                  </div>

                  <div className="p-5">
                    {activePanel === 'profile' && (
                      <div className="grid gap-5 2xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.75fr)]">
                        <div className="rounded-[24px] border border-slate-200 bg-white p-5">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-slate-950">主页采集配置</div>
                              <div className="mt-1 text-sm leading-6 text-slate-500">粘贴完整个人主页链接，建议包含 <code>xsec_token</code>。</div>
                            </div>
                            <span className={`rounded-full border px-3 py-1 text-[11px] font-bold ${getEnvConfigTone(selectedEnv)}`}>
                              {selectedEnv.profile_url ? '已配置' : '待配置'}
                            </span>
                          </div>
                          <div className="mt-4">
                            <label className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">账号部门</label>
                            <select
                              value={departmentDrafts[selectedEnv.id] || 'xhs'}
                              onChange={(event) => setDepartmentDrafts((prev) => ({
                                ...prev,
                                [selectedEnv.id]: event.target.value === 'brand' ? 'brand' : 'xhs',
                              }))}
                              className="mt-2 h-11 w-full rounded-2xl border border-slate-200 bg-[#fbfaf7] px-3 text-sm font-semibold text-slate-800 outline-none transition-all focus:border-slate-400 focus:bg-white focus:ring-4 focus:ring-slate-100"
                            >
                              <option value="xhs">小红书部门</option>
                              <option value="brand">品牌部门</option>
                            </select>
                            <div className="mt-2 text-xs leading-5 text-slate-400">保存后，负责人候选人和部门负责人可见范围会按这个部门生效。</div>
                          </div>
                          <div className="mt-4">
                            <label className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">小红书 ID</label>
                            <input
                              value={xhsAccountIdDrafts[selectedEnv.id] ?? ''}
                              onChange={(event) => setXhsAccountIdDrafts((prev) => ({ ...prev, [selectedEnv.id]: event.target.value }))}
                              placeholder="例如：26819980796"
                              inputMode="text"
                              autoComplete="off"
                              maxLength={100}
                              className="mt-2 h-11 w-full rounded-2xl border border-slate-200 bg-[#fbfaf7] px-3 text-sm text-slate-800 outline-none transition-all placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-4 focus:ring-slate-100"
                            />
                            <div className="mt-2 text-xs leading-5 text-slate-400">填写账号主页对应的小红书 ID；按文本保存，不会丢失长数字。</div>
                          </div>
                          <div className="mt-4">
                            <label className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">登录账号类型</label>
                            <select
                              value={accountTypeDrafts[selectedEnv.id] || 'enterprise_professional'}
                              onChange={(event) => setAccountTypeDrafts((prev) => ({
                                ...prev,
                                [selectedEnv.id]: normalizeXHSAccountType(event.target.value),
                              }))}
                              className="mt-2 h-11 w-full rounded-2xl border border-slate-200 bg-[#fbfaf7] px-3 text-sm font-semibold text-slate-800 outline-none transition-all focus:border-slate-400 focus:bg-white focus:ring-4 focus:ring-slate-100"
                            >
                              <option value="enterprise_professional">企业号（短信验证码优先）</option>
                              <option value="enterprise_employee">员工号（扫码优先）</option>
                              <option value="personal">个人号</option>
                            </select>
                            <div className="mt-2 text-xs leading-5 text-slate-400">员工号未登录时先走扫码；企业号未登录时先走手机号验证码，首次验证码失败后再切换扫码。</div>
                          </div>
                          <textarea
                            value={profileDrafts[selectedEnv.id] ?? ''}
                            onChange={(event) => setProfileDrafts((prev) => ({ ...prev, [selectedEnv.id]: event.target.value }))}
                            placeholder="https://www.xiaohongshu.com/user/profile/..."
                            rows={5}
                            className="mt-4 w-full resize-y rounded-[20px] border border-slate-200 bg-[#fbfaf7] px-4 py-3 text-sm leading-6 text-slate-800 outline-none transition-all placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-4 focus:ring-slate-100"
                          />
                          <div className="mt-4">
                            <label className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">手机号登录</label>
                            <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                              <input
                                value={loginPhoneDrafts[selectedEnv.id] ?? ''}
                                onChange={(event) => setLoginPhoneDrafts((prev) => ({ ...prev, [selectedEnv.id]: event.target.value }))}
                                placeholder="用于自动接码登录的小红书手机号"
                                className="h-11 min-w-0 flex-1 rounded-2xl border border-slate-200 bg-[#fbfaf7] px-3 text-sm text-slate-800 outline-none transition-all placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-4 focus:ring-slate-100"
                              />
                              <button
                                type="button"
                                className="h-11 rounded-2xl bg-slate-950 px-4 text-xs font-semibold text-white transition-all hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-45"
                                onClick={() => handleSaveProfileUrl(selectedEnv.id)}
                                disabled={savingProfileId === selectedEnv.id || !hasDraftChanges}
                              >
                                {savingProfileId === selectedEnv.id ? '保存中...' : '保存账号配置'}
                              </button>
                            </div>
                            <div className="mt-2 text-xs leading-5 text-slate-400">未登录时会用这个手机号向验证码中台创建取码订单。</div>
                          </div>
                        </div>

                        <div className="rounded-[24px] border border-slate-200 bg-[#fbfaf7] p-5">
                          <div className="text-sm font-semibold text-slate-950">操作提醒</div>
                          <div className="mt-3 space-y-3 text-sm leading-6 text-slate-600">
                            <div className="rounded-2xl bg-white px-4 py-3">先同步云登环境，再配置主页和运营负责人。</div>
                            <div className="rounded-2xl bg-white px-4 py-3">同步任务只认在线环境，离线环境会直接失败。</div>
                            <div className="rounded-2xl bg-white px-4 py-3">“测试1”这类账号也可以手动设为同步环境，不再依赖名称。</div>
                          </div>
                        </div>

                        <div className="rounded-[24px] border border-slate-200 bg-white p-5">
                          <div className="text-sm font-semibold text-slate-950">开放平台历史配置</div>
                          <div className="mt-1 text-sm leading-6 text-slate-500">当前不会自动启动、停止或重启云登环境；这里仅保留备查。</div>
                          <div className="mt-4 grid gap-3 lg:grid-cols-2">
                            <input
                              value={syncCloudSessionDrafts[selectedEnv.id] ?? ''}
                              onChange={(event) => setSyncCloudSessionDrafts((prev) => ({ ...prev, [selectedEnv.id]: event.target.value }))}
                              placeholder="云登 sessionId"
                              className="h-11 rounded-2xl border border-slate-200 bg-[#fbfaf7] px-3 text-sm text-slate-800 outline-none transition-all placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-4 focus:ring-slate-100"
                            />
                            <input
                              type="password"
                              value={syncCloudApiKeyDrafts[selectedEnv.id] ?? ''}
                              onChange={(event) => setSyncCloudApiKeyDrafts((prev) => ({ ...prev, [selectedEnv.id]: event.target.value }))}
                              placeholder="云登 apiKey"
                              className="h-11 rounded-2xl border border-slate-200 bg-[#fbfaf7] px-3 text-sm text-slate-800 outline-none transition-all placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-4 focus:ring-slate-100"
                            />
                          </div>
                          <textarea
                            value={syncCloudUpdateConfigDrafts[selectedEnv.id] ?? ''}
                            onChange={(event) => setSyncCloudUpdateConfigDrafts((prev) => ({ ...prev, [selectedEnv.id]: event.target.value }))}
                            placeholder={'{\n  "flag": 2,\n  "sessionName": {"$pick": ["测试2-同步A", "测试2-同步B"]}\n}'}
                            rows={9}
                            className="mt-4 w-full resize-y rounded-[20px] border border-slate-200 bg-[#fbfaf7] px-4 py-3 font-mono text-[12px] leading-6 text-slate-800 outline-none transition-all placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-4 focus:ring-slate-100"
                          />
                        </div>

                        <div className="rounded-[24px] border border-slate-200 bg-white p-5">
                          <div className="text-sm font-semibold text-slate-950">历史启动模板</div>
                          <div className="mt-1 text-sm leading-6 text-slate-500">新同步策略不会读取这段配置自动启动环境。</div>
                          <textarea
                            value={syncBrowserConfigDrafts[selectedEnv.id] ?? ''}
                            onChange={(event) => setSyncBrowserConfigDrafts((prev) => ({ ...prev, [selectedEnv.id]: event.target.value }))}
                            placeholder={'{\n  "headless": "0"\n}'}
                            rows={9}
                            className="mt-4 w-full resize-y rounded-[20px] border border-slate-200 bg-[#fbfaf7] px-4 py-3 font-mono text-[12px] leading-6 text-slate-800 outline-none transition-all placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-4 focus:ring-slate-100"
                          />
                        </div>
                      </div>
                    )}

                    {activePanel === 'users' && (
                      <div className="grid gap-5 xl:grid-cols-[minmax(0,0.8fr)_minmax(420px,1fr)]">
                        <div className="rounded-[24px] border border-slate-200 bg-[#fbfaf7] p-5">
                          <div className="text-sm font-semibold text-slate-950">当前运营负责人</div>
                          <div className="mt-2 text-sm text-slate-500">一个账号只归属一个负责人；当前为{getDepartmentLabel(selectedEnv.department)}部门，只展示对应部门可分配人员。</div>
                          {selectedOwnerUser ? (
                            <div className="mt-4 rounded-[20px] border border-emerald-100 bg-emerald-50 px-4 py-3">
                              <div className="text-sm font-semibold text-emerald-900">{selectedOwnerUser.display_name || selectedOwnerUser.username}</div>
                              <div className="mt-1 text-xs font-semibold text-emerald-700/75">{selectedOwnerUser.username} · {selectedOwnerUser.email || getUserRoleLabel(selectedOwnerUser.role)}</div>
                              <div className="mt-2 inline-flex rounded-full bg-white px-2.5 py-1 text-[11px] font-bold text-emerald-700">{getUserRoleLabel(selectedOwnerUser.role)}</div>
                            </div>
                          ) : (
                            <div className="mt-4 rounded-[20px] border border-dashed border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-500">还没有设置负责人</div>
                          )}
                        </div>
                        <div className="rounded-[24px] border border-slate-200 bg-white p-4">
                          <div className="grid gap-2 md:grid-cols-2">
                            {assignableUsers.map((user) => {
                              const key = `${user.id}-${selectedEnv.id}`;
                              const assigned = selectedAssignedUserIds.has(user.id);
                              const acting = actionKey === key;
                              return (
                                <button
                                  key={user.id}
                                  type="button"
                                  className={`flex items-center justify-between rounded-2xl border px-4 py-3 text-left text-sm transition-all disabled:opacity-50 ${
                                    assigned
                                      ? 'border-emerald-200 bg-emerald-50 text-emerald-800 hover:border-red-200 hover:bg-red-50 hover:text-red-700'
                                      : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-[#fbfaf7]'
                                  }`}
                                  onClick={() => handleToggle(user.id, selectedEnv.id)}
                                  disabled={acting}
                                >
                                  <span className="min-w-0">
                                    <span className="block truncate font-semibold">{user.display_name || user.username}</span>
                                    <span className={`mt-1 block truncate text-xs ${assigned ? 'text-emerald-700/75' : 'text-slate-400'}`}>
                                      {user.username} · {user.email || getUserRoleLabel(user.role)}
                                    </span>
                                  </span>
                                  <span className="ml-3 shrink-0 text-xs font-semibold">{acting ? '处理中' : assigned ? '移除' : '设为负责人'}</span>
                                </button>
                              );
                            })}
                            {assignableUsers.length === 0 ? (
                              <div className="rounded-2xl border border-dashed border-slate-200 bg-[#fbfaf7] px-4 py-6 text-center text-sm font-semibold text-slate-500 md:col-span-2">
                                还没有可分配的{getDepartmentLabel(selectedEnv.department)}部门负责人或运营用户
                              </div>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    )}

                    {activePanel === 'browser' && (
                      <div className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(360px,1fr)]">
                        <div className="rounded-[24px] border border-slate-200 bg-[#10141f] p-6 text-white">
                          <div className="flex items-center gap-3">
                            <span className={`h-3 w-3 rounded-full ${getBrowserDotTone(selectedBrowserStatus?.browser_status)}`} />
                            <div className="text-sm font-semibold uppercase tracking-[0.18em] text-white/48">Browser Status</div>
                          </div>
                          <div className="mt-5 text-4xl font-semibold tracking-[-0.05em]">
                            {getBrowserStatusLabel(selectedBrowserStatus?.browser_status)}
                          </div>
                          <div className="mt-2 text-sm text-white/52">
                            最近探测：{formatBrowserCheckedAt(selectedBrowserStatus?.checked_at)}
                          </div>
                          {selectedBrowserStatus?.error ? (
                            <div className="mt-4 rounded-2xl border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100">
                              {selectedBrowserStatus.error}
                            </div>
                          ) : null}
                          <button
                            type="button"
                            className="mt-5 inline-flex h-11 items-center rounded-2xl bg-white px-4 text-sm font-semibold text-slate-950 transition-all hover:-translate-y-0.5 hover:bg-slate-100 disabled:opacity-50"
                            onClick={() => handleRefreshSelectedBrowserStatus(selectedEnv.id)}
                            disabled={actionKey === `refresh-browser-${selectedEnv.id}`}
                          >
                            {actionKey === `refresh-browser-${selectedEnv.id}` ? '探测中...' : '重新探测当前环境'}
                          </button>
                        </div>
                        <div className="grid gap-3 sm:grid-cols-2">
                          {[
                            ['同步资格', selectedBrowserStatus?.browser_status === 'online' ? '可执行' : '不可执行'],
                            ['同步环境', isSyncRunnerEnv(selectedEnv) ? '是' : '否'],
                            ['开放平台', selectedEnv.sync_cloud_session_id && selectedEnv.sync_cloud_api_key ? '已配置' : '未配置'],
                            ['小红书 ID', selectedEnv.xhs_account_id || '未配置'],
                            ['登录手机号', selectedEnv.login_phone_number ? '已配置' : '未配置'],
                            ['账号类型', getXHSAccountTypeLabel(selectedEnv.xhs_account_type)],
                            ['运营负责人', selectedOwnerUser ? (selectedOwnerUser.display_name || selectedOwnerUser.username) : '未设置'],
                          ].map(([label, value]) => (
                            <div key={label} className="rounded-[24px] border border-slate-200 bg-white p-5">
                              <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</div>
                              <div className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-slate-950">{value}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {activePanel === 'activity' && (
                      <div className="grid gap-5 2xl:grid-cols-[minmax(0,0.9fr)_minmax(440px,1fr)]">
                        <div className="rounded-[24px] border border-slate-200 bg-white p-5">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-slate-950">当前环境同步负载</div>
                              <div className="mt-1 text-sm text-slate-500">名下链接浏览与该测试账号执行情况。</div>
                            </div>
                            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
                              今日总浏览 {browseOverview?.total_views_today ?? 0}
                            </span>
                          </div>
                          <div className="mt-4 grid gap-3 sm:grid-cols-4">
                            {[
                              ['名下笔记', selectedRunnerOverview?.assigned_notes ?? 0],
                              ['今日浏览', selectedRunnerOverview?.today_total_views ?? 0],
                              ['名下同步', selectedRunnerOverview?.today_sync_views ?? 0],
                              ['执行同步', selectedRunnerOverview?.today_executor_sync_views ?? 0],
                            ].map(([label, value]) => (
                              <div key={label} className="rounded-2xl border border-slate-200 bg-[#fbfaf7] px-3 py-4 text-center">
                                <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">{label}</div>
                                <div className="mt-1 text-xl font-semibold text-slate-950">{value}</div>
                              </div>
                            ))}
                          </div>
                          <div className="mt-4 space-y-2">
                            {(selectedRunnerOverview?.timeline || []).slice(-5).map((item) => (
                              <div key={`${selectedEnv.id}-${item.date}`} className="flex items-center justify-between rounded-2xl bg-[#fbfaf7] px-3 py-2 text-xs text-slate-500">
                                <span>{item.date}</span>
                                <span className="font-semibold text-slate-900">{item.total_views} 次</span>
                              </div>
                            ))}
                            {!selectedRunnerOverview && (
                              <div className="rounded-2xl border border-dashed border-slate-200 bg-[#fbfaf7] py-10 text-center text-sm text-slate-400">
                                当前环境暂无同步负载记录
                              </div>
                            )}
                          </div>
                        </div>

                        <div className="rounded-[24px] border border-slate-200 bg-[#fbfaf7] p-4">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-sm font-semibold text-slate-950">相关浏览流水</div>
                            <div className="text-xs text-slate-400">{selectedRecentEvents.length} 条</div>
                          </div>
                          <div className="mt-3 max-h-[520px] space-y-2 overflow-y-auto pr-1">
                            {selectedRecentEvents.map((event) => (
                              <div key={`selected-browse-event-${event.id}`} className="rounded-2xl border border-slate-200 bg-white px-3 py-3">
                                <div className="flex items-center justify-between gap-3">
                                  <div className="min-w-0">
                                    <div className="truncate text-sm font-semibold text-slate-900">{event.note_title || event.note_feed_id || `笔记 #${event.note_id}`}</div>
                                    <div className="mt-1 text-xs text-slate-500">
                                      {event.source_account_name || '未知账号'} · 执行 {event.runner_account_name || '未识别测试账号'}
                                    </div>
                                  </div>
                                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600">
                                    {getBrowseSourceLabel(event.browse_source)}
                                  </span>
                                </div>
                                <div className="mt-2 flex items-center justify-between gap-3 text-xs text-slate-400">
                                  <span>{formatEventTime(event.created_at)}</span>
                                  {event.note_post_url ? (
                                    <a href={event.note_post_url} target="_blank" rel="noreferrer" className="font-semibold text-slate-900 hover:underline">
                                      打开链接
                                    </a>
                                  ) : <span>{event.note_feed_id || '-'}</span>}
                                </div>
                              </div>
                            ))}
                            {selectedRecentEvents.length === 0 && (
                              <div className="rounded-2xl border border-dashed border-slate-200 bg-white py-12 text-center text-sm text-slate-400">
                                暂无相关流水
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}
