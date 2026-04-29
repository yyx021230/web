'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';
import { Trash2, Search } from 'lucide-react';

interface Copywriting {
  id: number;
  title: string;
  content: string;
  tags: string[];
  category: string;
  created_by: number | null;
  created_at: string;
}

export default function CopywritingsPage() {
  const searchParams = useSearchParams();
  const initUsername = searchParams?.get('username') ?? undefined;

  const [items, setItems] = useState<Copywriting[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [usernameFilter, setUsernameFilter] = useState<string | undefined>(initUsername);
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>(undefined);

  const fetchData = useCallback(() => {
    setLoading(true);
    adminApi.getAdminCopywritings(page, 20, usernameFilter, categoryFilter, search || undefined)
      .then(res => {
        setItems(res.data.items);
        setTotal(res.data.total);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [page, usernameFilter, categoryFilter, search]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这篇文案吗？')) return;
    setDeletingId(id);
    try {
      await adminApi.deleteAdminCopywriting(id);
      toast.success('已删除');
      fetchData();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-32 bg-gray-100 rounded animate-pulse" />
        <div className="bg-white rounded-xl border shadow-sm">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-16 border-b last:border-0 animate-pulse">
              <div className="mx-4 h-4 bg-gray-100 rounded mt-6" style={{ width: `${30 + Math.random() * 50}%` }} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">文案管理</h2>
        <span className="text-sm text-gray-500">共 {total} 篇文案</span>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            className="w-full pl-9 pr-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="搜索标题..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-500">分类:</label>
          <input
            className="w-28 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="全部"
            value={categoryFilter ?? ''}
            onChange={e => setCategoryFilter(e.target.value || undefined)}
          />
        </div>
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

      {/* List */}
      {items.length === 0 ? (
        <div className="text-center py-20 text-gray-400">暂无文案</div>
      ) : (
        <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">标题</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">内容摘要</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">分类</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">标签</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">创建者</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">创建时间</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.map(c => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{c.title}</td>
                  <td className="px-4 py-3 text-gray-500 max-w-[200px] truncate">{c.content}</td>
                  <td className="px-4 py-3">
                    <span className="px-1.5 py-0.5 rounded text-xs bg-gray-100 text-gray-600">
                      {c.category || '-'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1 flex-wrap">
                      {(c.tags ?? []).slice(0, 2).map(t => (
                        <span key={t} className="px-1.5 py-0.5 rounded text-xs bg-blue-50 text-blue-600">{t}</span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {c.created_by ? (
                      <a href={`/admin/users/${c.created_by}`} className="text-blue-600 hover:underline">
                        #{c.created_by}
                      </a>
                    ) : '-'}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{c.created_at?.slice(0, 19)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      disabled={deletingId === c.id}
                      onClick={() => handleDelete(c.id)}
                      className="text-xs text-red-600 hover:underline disabled:opacity-50 flex items-center gap-1 ml-auto"
                    >
                      <Trash2 className="h-3 w-3" />
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {total > 20 && (
            <div className="flex items-center justify-between border-t px-4 py-3">
              <span className="text-xs text-gray-500">第 {page} 页</span>
              <div className="flex gap-2">
                <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
                  className="px-3 py-1 text-xs rounded-md border disabled:opacity-40 hover:bg-gray-50">上一页</button>
                <button disabled={page * 20 >= total} onClick={() => setPage(p => p + 1)}
                  className="px-3 py-1 text-xs rounded-md border disabled:opacity-40 hover:bg-gray-50">下一页</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
