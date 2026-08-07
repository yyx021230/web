'use client';

import { useEffect, useMemo, useState } from 'react';
import { adminApi } from '@/services/adminApi';
import { Activity, Bot, HardDrive, Workflow } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatLocalDateTime } from '@/lib/dateTime';

type Granularity = 'hour' | 'day' | 'week';

type UsageData = {
  granularity: Granularity;
  buckets: Array<{ key: string; label: string; start: string; end: string }>;
  ai: {
    names?: string[];
    series: Record<string, number[]>;
    total_records: number;
    matched_records: number;
    raw_model_counts: Record<string, number>;
  };
  workflow: {
    names: string[];
    series: Record<string, number[]>;
    total_records: number;
  };
};

type SeriesMap = Record<string, number[]>;

type XHSPublishData = {
  granularity: Granularity;
  buckets: Array<{ key: string; label: string; start: string; end: string }>;
  series: Record<string, number[]>;
  total_records: number;
};

type PublishedPostItem = {
  id: number;
  source_type: string;
  source_label: string;
  title: string;
  username: string;
  environment_name: string;
  post_url: string | null;
  feed_id: string | null;
  published_at: string | null;
  like_count: number;
  comment_count: number;
  collect_count: number;
  share_count: number;
  created_at: string | null;
};

const CHART_W = 900;
const CHART_H = 240;
const PAD = 16;

function MultiBarChart({ title, buckets, series, names }: { title: string; buckets: UsageData['buckets']; series: SeriesMap; names: string[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null);

  const palette = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#8b5cf6', '#f97316', '#22c55e'];
  const maxY = Math.max(1, ...names.flatMap((n) => series[n] || [0]));
  const innerW = CHART_W - PAD * 2;
  const innerH = CHART_H - PAD * 2;
  const bucketStep = buckets.length > 0 ? innerW / buckets.length : innerW;
  const groupW = bucketStep * 0.8;
  const barW = Math.max(2, names.length > 0 ? groupW / names.length : groupW);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!buckets.length) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const chartX = (x / rect.width) * CHART_W;
    // Snap to nearest bucket center to avoid rightward cumulative drift.
    const idxFloat = (chartX - PAD) / Math.max(bucketStep, 1);
    const idx = Math.max(0, Math.min(buckets.length - 1, Math.round(idxFloat - 0.5)));
    setHoverIndex(idx);
    const snappedX = ((PAD + bucketStep * idx + bucketStep * 0.5) / CHART_W) * rect.width;
    setTip({ x: snappedX, y: e.clientY - rect.top });
  };

  return (
    <div className="rounded-xl border bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">{title}</h3>
        <div className="flex flex-wrap gap-2 text-[11px] text-gray-500">
          {names.map((name, i) => (
            <span key={name} className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: palette[i % palette.length] }} />{name}</span>
          ))}
        </div>
      </div>

      <div className="relative">
        <svg
          viewBox={`0 0 ${CHART_W} ${CHART_H}`}
          preserveAspectRatio="none"
          className="h-64 w-full rounded-lg bg-gray-50"
          onMouseMove={onMove}
          onMouseLeave={() => { setHoverIndex(null); setTip(null); }}
        >
          {buckets.map((_, bucketIdx) => (
            <g key={`bucket-${bucketIdx}`}>
              {names.map((name, i) => {
                const v = series[name]?.[bucketIdx] || 0;
                const h = (v / Math.max(maxY, 1)) * innerH;
                const x = PAD + bucketStep * bucketIdx + bucketStep * 0.1 + i * barW;
                const y = PAD + innerH - h;
                return <rect key={`${name}-${bucketIdx}`} x={x} y={y} width={Math.max(1, barW - 1)} height={Math.max(0, h)} fill={palette[i % palette.length]} opacity={hoverIndex === null || hoverIndex === bucketIdx ? 0.95 : 0.5} rx={1} />;
              })}
            </g>
          ))}
          {hoverIndex !== null && (
            <line x1={PAD + bucketStep * hoverIndex + bucketStep * 0.5} y1={PAD} x2={PAD + bucketStep * hoverIndex + bucketStep * 0.5} y2={CHART_H - PAD} stroke="#9ca3af" strokeDasharray="4 4" />
          )}
        </svg>

        {hoverIndex !== null && tip && buckets[hoverIndex] && (
          <div
            className="pointer-events-none absolute z-20 rounded-md border bg-white/95 px-3 py-2 text-xs shadow"
            style={{ left: Math.max(tip.x + 10, 8), top: Math.max(tip.y - 70, 8) }}
          >
            <div className="mb-1 text-gray-500">{buckets[hoverIndex].key}</div>
            {names.map((name, i) => (<div key={name} style={{ color: palette[i % palette.length] }}>{name}: {series[name]?.[hoverIndex] || 0}</div>))}
          </div>
        )}

        <div className="mt-2 grid gap-1 text-[10px] text-gray-400" style={{ gridTemplateColumns: `repeat(${Math.max(1, buckets.length)}, minmax(0, 1fr))` }}>
          {buckets.map((b) => (<div key={b.key} className="truncate text-center">{b.label}</div>))}
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [overview, setOverview] = useState<any>(null);
  const [activeTasks, setActiveTasks] = useState<any[]>([]);
  const [rankings, setRankings] = useState<any>(null);
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [xhsPublish, setXhsPublish] = useState<XHSPublishData | null>(null);
  const [publishedPosts, setPublishedPosts] = useState<{ items: PublishedPostItem[]; total: number; page: number; limit: number } | null>(null);
  const [users, setUsers] = useState<string[]>([]);
  const [selectedUser, setSelectedUser] = useState<string>('');
  const [granularity, setGranularity] = useState<Granularity>('hour');
  const [xhsPage, setXhsPage] = useState<number>(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setXhsPage(1);
  }, [selectedUser]);

  useEffect(() => {
    setLoading(true);
    const username = selectedUser || undefined;
    Promise.all([
      adminApi.getOverview(username),
      adminApi.getActiveTasks(username),
      adminApi.getRankings(username),
      adminApi.getUsageSeries(granularity, username),
      adminApi.getXhsPublishSeries(granularity, username),
      adminApi.getXhsPublishedPosts({ page: xhsPage, limit: 20, username }),
      adminApi.getUsers(1, 100).catch(() => ({ data: { items: [] } } as any)),
    ]).then(([ov, ac, rk, us, xhsSeriesRes, xhsPostsRes, userRes]) => {
      setOverview(ov.data);
      setActiveTasks(ac.data || []);
      setRankings(rk.data || {});
      setUsage(us.data);
      setXhsPublish(xhsSeriesRes.data || null);
      setPublishedPosts(xhsPostsRes.data || null);
      setUsers((userRes.data.items || []).map((u: any) => u.username).filter(Boolean));
    }).catch(console.error).finally(() => setLoading(false));
  }, [granularity, selectedUser, xhsPage]);

  const aiSeriesNames = (usage?.ai?.names && usage.ai.names.length > 0)
    ? usage.ai.names
    : Object.keys(usage?.ai?.series || {});
  const aiSeries = usage?.ai?.series || {};
  const wfSeriesNames = usage?.workflow?.names || [];
  const wfSeries = usage?.workflow?.series || {};
  const xhsSeriesNames = xhsPublish ? Object.keys(xhsPublish.series || {}) : [];
  const xhsSeries = xhsPublish?.series || {};
  const scopeLabel = selectedUser ? `用户 ${selectedUser}` : '全用户';
  const aiTodayCount = overview?.ai_tasks_today ?? overview?.ai_tasks_24h ?? 0;
  const xhsTotal = xhsPublish?.total_records || 0;

  const aiBucketedTotal = useMemo(
    () => aiSeriesNames.reduce((sum, name) => sum + (aiSeries[name] || []).reduce((a: number, b: number) => a + b, 0), 0),
    [aiSeries, aiSeriesNames],
  );

  if (loading) return <div className="py-20 text-center text-sm text-gray-500">加载中...</div>;
  if (!usage) return <div className="py-20 text-center text-sm text-red-500">运营聚合数据加载失败，请重新登录后刷新页面</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">运营总览</h1>
          <p className="mt-1 text-xs text-gray-500">{scopeLabel} 聚合统计（直接基于任务表，不依赖分页列表）</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={selectedUser}
            onChange={(e) => setSelectedUser(e.target.value)}
            className="rounded-md border bg-white px-2.5 py-1 text-xs text-gray-700"
          >
            <option value="">全部用户</option>
            {users.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
          {(['hour', 'day', 'week'] as Granularity[]).map((g) => (
            <button key={g} type="button" onClick={() => setGranularity(g)} className={cn('rounded-md border px-2.5 py-1 text-xs', granularity === g ? 'border-indigo-600 bg-indigo-600 text-white' : 'bg-white text-gray-600')}>
              {g === 'hour' ? '按小时' : g === 'day' ? '按日' : '按周'}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border bg-white p-4 shadow-sm"><Bot className="mb-2 h-4 w-4 text-indigo-600" /><div className="text-xl font-bold">{aiTodayCount}</div><div className="text-xs text-gray-500">AI任务(今日)</div></div>
        <div className="rounded-xl border bg-white p-4 shadow-sm"><Activity className="mb-2 h-4 w-4 text-cyan-600" /><div className="text-xl font-bold">{activeTasks.length}</div><div className="text-xs text-gray-500">当前活跃任务</div></div>
        <div className="rounded-xl border bg-white p-4 shadow-sm"><HardDrive className="mb-2 h-4 w-4 text-purple-600" /><div className="text-xl font-bold">{overview?.storage_mb || 0} MB</div><div className="text-xs text-gray-500">存储使用</div></div>
        <div className="rounded-xl border bg-white p-4 shadow-sm"><Workflow className="mb-2 h-4 w-4 text-emerald-600" /><div className="text-xl font-bold">{usage?.workflow?.total_records || 0}</div><div className="text-xs text-gray-500">工作流任务总数(窗口内)</div></div>
      </div>

      <MultiBarChart title={`小红书发帖趋势（自动工具 + 自主发布，${scopeLabel}）`} buckets={xhsPublish?.buckets || []} series={xhsSeries} names={xhsSeriesNames} />
      <div className="rounded-lg border bg-gray-50 px-3 py-2 text-xs text-gray-700">
        小红书发帖总数（当前窗口）: {xhsTotal}
      </div>

      <MultiBarChart title={`工作流调用趋势（${scopeLabel}）`} buckets={usage?.buckets || []} series={wfSeries} names={wfSeriesNames} />
      <MultiBarChart title={`生图调用趋势（全模型，${scopeLabel}）`} buckets={usage?.buckets || []} series={aiSeries} names={aiSeriesNames} />

      <div className="rounded-lg border bg-gray-50 px-3 py-2 text-xs text-gray-700">
        <div className="font-medium mb-1">生图统计校验</div>
        <div>窗口内原始记录总数: {usage?.ai?.total_records || 0}，映射命中: {usage?.ai?.matched_records || 0}，图表柱累计: {aiBucketedTotal}</div>
        <div>原始模型TOP: {Object.entries(usage?.ai?.raw_model_counts || {}).map(([k, v]) => `${k}(${v})`).join('，') || '无'}</div>
      </div>

      <div className="rounded-xl border bg-white p-5 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold">资源与压力点</h3>
        <div className="space-y-2 text-sm">
          {(rankings?.storage_ranking || []).slice(0, 5).map((item: any, i: number) => (
            <div key={item.username} className="flex items-center justify-between"><span className="text-gray-600">TOP{i + 1} {item.username}</span><span className="font-semibold">{item.total_mb} MB</span></div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold">小红书发帖总览（自动工具 + 自主发布，只读）</h3>
          <div className="text-xs text-gray-500">来源字段区分自动工具发布和自主发布，仅展示已发布数据</div>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-gray-500">
                <th className="px-2 py-2">发布时间</th>
                <th className="px-2 py-2">来源</th>
                <th className="px-2 py-2">用户</th>
                <th className="px-2 py-2">环境</th>
                <th className="px-2 py-2">标题</th>
                <th className="px-2 py-2 text-right">点赞</th>
                <th className="px-2 py-2 text-right">评论</th>
                <th className="px-2 py-2 text-right">收藏</th>
                <th className="px-2 py-2 text-right">转发</th>
              </tr>
            </thead>
            <tbody>
              {(publishedPosts?.items || []).map((item) => (
                <tr key={`${item.source_type}-${item.id}`} className="border-b last:border-b-0">
                  <td className="px-2 py-2 text-xs text-gray-600">{formatLocalDateTime(item.published_at)}</td>
                  <td className="px-2 py-2">
                    <span className={cn(
                      'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium',
                      item.source_type === 'auto_tool'
                        ? 'bg-indigo-50 text-indigo-700'
                        : 'bg-emerald-50 text-emerald-700',
                    )}
                    >
                      {item.source_label}
                    </span>
                  </td>
                  <td className="px-2 py-2">{item.username}</td>
                  <td className="px-2 py-2 text-gray-600">{item.environment_name || '-'}</td>
                  <td className="px-2 py-2">
                    {item.post_url ? (
                      <a href={item.post_url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">{item.title}</a>
                    ) : (
                      <span>{item.title}</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-right">{item.like_count}</td>
                  <td className="px-2 py-2 text-right">{item.comment_count}</td>
                  <td className="px-2 py-2 text-right">{item.collect_count}</td>
                  <td className="px-2 py-2 text-right">{item.share_count}</td>
                </tr>
              ))}
              {(!publishedPosts || publishedPosts.items.length === 0) && (
                <tr>
                  <td colSpan={9} className="px-2 py-6 text-center text-xs text-gray-500">暂无已发布帖子数据</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-gray-600">
          <div>共 {publishedPosts?.total || 0} 条</div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setXhsPage((p) => Math.max(1, p - 1))}
              disabled={(publishedPosts?.page || 1) <= 1}
              className="rounded border px-2 py-1 disabled:opacity-50"
            >
              上一页
            </button>
            <span>第 {publishedPosts?.page || 1} 页</span>
            <button
              type="button"
              onClick={() => setXhsPage((p) => p + 1)}
              disabled={Boolean(publishedPosts && publishedPosts.page * publishedPosts.limit >= publishedPosts.total)}
              className="rounded border px-2 py-1 disabled:opacity-50"
            >
              下一页
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
