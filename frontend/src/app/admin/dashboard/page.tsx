'use client';

import { useEffect, useMemo, useState } from 'react';
import { adminApi } from '@/services/adminApi';
import { Activity, Bot, HardDrive, Workflow } from 'lucide-react';
import { cn } from '@/lib/utils';

type Granularity = 'hour' | 'day' | 'week';

type UsageData = {
  granularity: Granularity;
  buckets: Array<{ key: string; label: string; start: string; end: string }>;
  ai: {
    series: { image2: number[]; seedream: number[] };
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
  const [users, setUsers] = useState<string[]>([]);
  const [selectedUser, setSelectedUser] = useState<string>('');
  const [granularity, setGranularity] = useState<Granularity>('hour');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      adminApi.getOverview(),
      adminApi.getActiveTasks(),
      adminApi.getRankings(),
      adminApi.getUsageSeries(granularity, selectedUser || undefined),
      adminApi.getUsers(1, 100).catch(() => ({ data: { items: [] } } as any)),
    ]).then(([ov, ac, rk, us, userRes]) => {
      setOverview(ov.data);
      setActiveTasks(ac.data || []);
      setRankings(rk.data || {});
      setUsage(us.data);
      setUsers((userRes.data.items || []).map((u: any) => u.username).filter(Boolean));
    }).catch(console.error).finally(() => setLoading(false));
  }, [granularity, selectedUser]);

  const aiSeriesNames = ['image2', 'seedream'];
  const aiSeries = usage?.ai?.series || { image2: [], seedream: [] };
  const wfSeriesNames = usage?.workflow?.names || [];
  const wfSeries = usage?.workflow?.series || {};

  const aiBucketedTotal = useMemo(
    () => (aiSeries.image2 || []).reduce((a: number, b: number) => a + b, 0) + (aiSeries.seedream || []).reduce((a: number, b: number) => a + b, 0),
    [aiSeries],
  );

  if (loading) return <div className="py-20 text-center text-sm text-gray-500">加载中...</div>;
  if (!usage) return <div className="py-20 text-center text-sm text-red-500">运营聚合数据加载失败，请重新登录后刷新页面</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">运营总览</h1>
          <p className="mt-1 text-xs text-gray-500">全用户聚合统计（直接基于任务表，不依赖分页列表）</p>
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
        <div className="rounded-xl border bg-white p-4 shadow-sm"><Bot className="mb-2 h-4 w-4 text-indigo-600" /><div className="text-xl font-bold">{overview?.ai_tasks_24h || 0}</div><div className="text-xs text-gray-500">AI任务(24h)</div></div>
        <div className="rounded-xl border bg-white p-4 shadow-sm"><Activity className="mb-2 h-4 w-4 text-cyan-600" /><div className="text-xl font-bold">{activeTasks.length}</div><div className="text-xs text-gray-500">当前活跃任务</div></div>
        <div className="rounded-xl border bg-white p-4 shadow-sm"><HardDrive className="mb-2 h-4 w-4 text-purple-600" /><div className="text-xl font-bold">{overview?.storage_mb || 0} MB</div><div className="text-xs text-gray-500">存储使用</div></div>
        <div className="rounded-xl border bg-white p-4 shadow-sm"><Workflow className="mb-2 h-4 w-4 text-emerald-600" /><div className="text-xl font-bold">{usage?.workflow?.total_records || 0}</div><div className="text-xs text-gray-500">工作流任务总数(窗口内)</div></div>
      </div>

      <MultiBarChart title="工作流调用趋势（全用户）" buckets={usage?.buckets || []} series={wfSeries} names={wfSeriesNames} />
      <MultiBarChart title="生图调用趋势（image2 / seedream，全用户）" buckets={usage?.buckets || []} series={aiSeries} names={aiSeriesNames} />

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
    </div>
  );
}
