'use client';

import { useState, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import { adminApi } from '@/services/adminApi';
import { Loader2, Bot, Clock, CheckCircle, XCircle } from 'lucide-react';

export default function ApiUsagePage() {
  const searchParams = useSearchParams();
  const initUsername = searchParams?.get('username') ?? undefined;

  const [overview, setOverview] = useState<any>(null);
  const [trend, setTrend] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [usernameFilter, setUsernameFilter] = useState<string | undefined>(initUsername);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      adminApi.getOverview(),
      adminApi.getAiTrend(7),
    ]).then(([ov, tr]) => {
      setOverview(ov.data);
      setTrend(tr.data);
    }).catch(console.error).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="flex justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-indigo-500" /></div>;
  }

  if (!overview) {
    return <div className="text-center text-sm text-gray-500 py-20">加载失败</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">API 使用情况</h2>
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-500">用户:</label>
          <input
            className="w-28 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="全部"
            value={usernameFilter ?? ''}
            onChange={e => setUsernameFilter(e.target.value || undefined)}
          />
          {usernameFilter && (
            <button className="text-sm text-blue-600 hover:underline" onClick={() => setUsernameFilter(undefined)}>
              清除
            </button>
          )}
        </div>
      </div>

      {/* Model breakdown */}
      {trend?.ai_models.length ? (
        <div className="bg-white rounded-xl border shadow-sm p-5">
          <h3 className="text-sm font-medium mb-4">AI 模型调用（近 7 天）</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {trend.ai_models.map((m: any) => (
              <div key={m.model} className="border rounded-lg p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Bot className="h-4 w-4 text-indigo-500" />
                  <span className="font-medium text-sm">{m.model}</span>
                </div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-gray-500 text-xs">总调用</p>
                    <p className="text-xl font-bold">{m.total}</p>
                  </div>
                  <div>
                    <p className="text-gray-500 text-xs">成功率</p>
                    <p className="text-xl font-bold text-green-600">
                      {m.total > 0 ? Math.round((m.success / m.total) * 100) : 0}%
                    </p>
                  </div>
                  <div>
                    <div className="flex items-center gap-1 text-green-600">
                      <CheckCircle className="h-3 w-3" />
                      <span className="font-medium">{m.success}</span>
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center gap-1 text-red-500">
                      <XCircle className="h-3 w-3" />
                      <span className="font-medium">{m.failed}</span>
                    </div>
                  </div>
                  <div className="col-span-2">
                    <div className="flex items-center gap-1 text-gray-500">
                      <Clock className="h-3 w-3" />
                      <span>平均 {m.avg_seconds}s</span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="bg-white rounded-xl border shadow-sm p-5 text-center text-sm text-gray-500">
          暂无 AI 调用数据
        </div>
      )}

      {/* Daily trend */}
      {trend?.ai_daily.length ? (
        <div className="bg-white rounded-xl border shadow-sm p-5">
          <h3 className="text-sm font-medium mb-4">近 7 天调用量</h3>
          <div className="flex items-end gap-2 h-48">
            {trend.ai_daily.map((day: any) => {
              const maxVal = Math.max(...trend.ai_daily.map((d: any) => d.total), 1);
              const height = Math.max((day.total / maxVal) * 100, 4);
              return (
                <div key={day.date} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-xs font-bold">{day.total}</span>
                  <div
                    className="w-full bg-gradient-to-t from-indigo-500 to-indigo-400 rounded-t-md"
                    style={{ height: `${height}%` }}
                  />
                  <span className="text-[10px] text-gray-500">{day.date.slice(5)}</span>
                  {/* Model breakdown in bar */}
                  {Object.entries(day.by_model || {}).map(([model, count]: [string, any]) => (
                    <span key={model} className="text-[9px] text-gray-400">{model}: {count}</span>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* Workflow execution stats */}
      {trend?.wf_daily.length ? (
        <div className="bg-white rounded-xl border shadow-sm p-5">
          <h3 className="text-sm font-medium mb-4">工作流执行（近 7 天）</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b bg-gray-50">
                <tr>
                  <th className="text-left px-3 py-2 font-medium text-gray-600">日期</th>
                  <th className="text-right px-3 py-2 font-medium text-gray-600">成功</th>
                  <th className="text-right px-3 py-2 font-medium text-gray-600">失败</th>
                  <th className="text-right px-3 py-2 font-medium text-gray-600">总计</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {trend.wf_daily.map((day: any) => {
                  const total = (day.succeeded || 0) + (day.failed || 0);
                  return (
                    <tr key={day.date}>
                      <td className="px-3 py-2">{day.date}</td>
                      <td className="px-3 py-2 text-right text-green-600 font-medium">{day.succeeded || 0}</td>
                      <td className="px-3 py-2 text-right text-red-500 font-medium">{day.failed || 0}</td>
                      <td className="px-3 py-2 text-right font-medium">{total}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {/* 24h summary */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white rounded-xl border shadow-sm p-5">
          <p className="text-sm text-gray-500 mb-1">近 24 小时 AI 任务</p>
          <p className="text-3xl font-bold">{overview.ai_tasks_24h}</p>
          <p className="text-sm mt-1">
            成功率 <span className="font-semibold text-green-600">{overview.ai_success_rate_24h}%</span>
          </p>
        </div>
        <div className="bg-white rounded-xl border shadow-sm p-5">
          <p className="text-sm text-gray-500 mb-1">总任务数</p>
          <p className="text-3xl font-bold">{overview.ai_task_count}</p>
          <p className="text-sm text-gray-500 mt-1">自系统上线以来</p>
        </div>
      </div>
    </div>
  );
}
