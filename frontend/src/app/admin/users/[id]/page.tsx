'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { adminApi } from '@/services/adminApi';
import { UserIcon, ArrowLeft } from 'lucide-react';

interface UserDetail {
  user: { id: number; username: string; display_name?: string | null; email: string; avatar: string | null; role: string; roles?: string[]; is_active: boolean; created_at: string };
  stats: { project_count: number; material_count: number; ai_task_count: number; ai_task_24h: number; workflow_count: number; dify_task_count: number; dify_run_log_count: number; copywriting_count: number };
  recent_ai_tasks: Array<{ id: number; model_name: string; prompt: string; status: string; created_at: string }>;
  recent_dify_tasks: Array<{ id: number; workflow_id: number; status: string; created_at: string }>;
}

const USER_ROLES = [
  { value: 'admin', label: '管理员', badgeClass: 'bg-slate-950 text-white' },
  { value: 'xhs_lead', label: '小红书部门负责人', badgeClass: 'bg-indigo-100 text-indigo-700' },
  { value: 'xhs_ops', label: '小红书运营', badgeClass: 'bg-rose-100 text-rose-700' },
  { value: 'buyer', label: '投手', badgeClass: 'bg-amber-100 text-amber-700' },
  { value: 'brand_lead', label: '品牌责任人', badgeClass: 'bg-sky-100 text-sky-700' },
  { value: 'brand_ops', label: '品牌运营', badgeClass: 'bg-emerald-100 text-emerald-700' },
  { value: 'viewer', label: '普通用户', badgeClass: 'bg-gray-100 text-gray-600' },
];

function getRoleMeta(role: string) {
  return USER_ROLES.find(item => item.value === role) || USER_ROLES[USER_ROLES.length - 1];
}

export default function UserDetailPage() {
  const params = useParams();
  const userId = Number(params.id);
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    adminApi.getUserDetail(userId).then(res => {
      setDetail(res.data);
    }).catch(console.error).finally(() => setLoading(false));
  }, [userId]);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 bg-gray-100 rounded animate-pulse" />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-20 bg-gray-100 rounded-xl animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (!detail) {
    return <div className="text-center py-20 text-gray-400">用户不存在</div>;
  }

  const stats = [
    { label: '项目', value: detail.stats.project_count, href: `/admin/projects?user_id=${userId}` },
    { label: '素材', value: detail.stats.material_count, href: `/admin/gallery?user_id=${userId}` },
    { label: 'AI 生图', value: detail.stats.ai_task_count, href: `/admin/api-usage?user_id=${userId}` },
    { label: 'AI 近24h', value: detail.stats.ai_task_24h },
    { label: '工作流', value: detail.stats.workflow_count, href: `/admin/workflows?user_id=${userId}` },
    { label: 'Dify 任务', value: detail.stats.dify_task_count, href: `/admin/api-usage?user_id=${userId}` },
    { label: '运行日志', value: detail.stats.dify_run_log_count },
    { label: '文案', value: detail.stats.copywriting_count, href: `/admin/copywritings?user_id=${userId}` },
  ];
  const roles = detail.user.roles?.length ? detail.user.roles : [detail.user.role || 'viewer'];

  return (
    <div className="space-y-6">
      <a href="/admin/users" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700">
        <ArrowLeft className="h-4 w-4" />
        返回用户列表
      </a>

      {/* User header */}
      <div className="flex items-center gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-gray-200">
          <UserIcon className="h-6 w-6 text-gray-500" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">{detail.user.display_name || detail.user.username}</h2>
          <p className="text-sm text-gray-500">{detail.user.username} · {detail.user.email}</p>
        </div>
        <div className="ml-auto flex gap-2">
          {roles.map((role) => {
            const roleMeta = getRoleMeta(role);
            return (
              <span key={role} className={`px-2 py-1 rounded-md text-xs font-medium ${roleMeta.badgeClass}`}>
                {roleMeta.label}
              </span>
            );
          })}
          <span className={`px-2 py-1 rounded-md text-xs font-medium ${detail.user.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
            {detail.user.is_active ? '启用中' : '已禁用'}
          </span>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-4 gap-4">
        {stats.map(s => (
          <div key={s.label} className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <div className="text-sm text-gray-500">{s.label}</div>
            <div className="text-2xl font-bold mt-1">
              {'href' in s && s.href ? (
                <a href={s.href} className="hover:text-blue-600">{s.value}</a>
              ) : (
                s.value
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Recent AI tasks */}
      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
        <div className="px-4 py-3 border-b font-medium text-sm">近期 AI 生图任务</div>
        {detail.recent_ai_tasks.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-gray-400">暂无任务</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-gray-600">模型</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">提示词</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">状态</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">时间</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {detail.recent_ai_tasks.map(t => (
                <tr key={t.id}>
                  <td className="px-4 py-2">{t.model_name}</td>
                  <td className="px-4 py-2 text-gray-500 truncate max-w-[300px]">{t.prompt}</td>
                  <td className="px-4 py-2">
                    <span className={`px-1.5 py-0.5 rounded text-xs ${t.status === 'succeeded' ? 'bg-green-100 text-green-700' : t.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'}`}>
                      {t.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{t.created_at?.slice(0, 19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Recent Dify tasks */}
      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
        <div className="px-4 py-3 border-b font-medium text-sm">近期 Dify 任务</div>
        {detail.recent_dify_tasks.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-gray-400">暂无任务</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-2 font-medium text-gray-600">工作流ID</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">状态</th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">时间</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {detail.recent_dify_tasks.map(t => (
                <tr key={t.id}>
                  <td className="px-4 py-2">#{t.workflow_id}</td>
                  <td className="px-4 py-2">
                    <span className={`px-1.5 py-0.5 rounded text-xs ${t.status === 'succeeded' ? 'bg-green-100 text-green-700' : t.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'}`}>
                      {t.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{t.created_at?.slice(0, 19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
