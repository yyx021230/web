'use client';

import { useEffect, useMemo, useState } from 'react';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';
import { FolderKanban, Search, Trash2, ExternalLink, Loader2 } from 'lucide-react';

type ProjectItem = {
  id: number;
  user_id: number;
  username: string;
  name: string;
  thumbnail: string | null;
  status: string | null;
  updated_at: string;
};

const PAGE_SIZE = 20;

export default function GlobalProjectsPage() {
  const [loading, setLoading] = useState(true);
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [items, setItems] = useState<ProjectItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [username, setUsername] = useState('');
  const [status, setStatus] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await adminApi.getProjects({
        page,
        limit: PAGE_SIZE,
        username: username || undefined,
        status: status || undefined,
      });
      setItems(res.data.items);
      setTotal(res.data.total);
      setSelectedIds(new Set());
    } catch (e: any) {
      toast.error(e.message || '获取项目失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [page, status]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total]);

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchData();
  };

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
      return;
    }
    setSelectedIds(new Set(items.map(i => i.id)));
  };

  const handleDeleteOne = async (id: number) => {
    if (!confirm('确定删除该项目吗？')) return;
    try {
      await adminApi.deleteProject(id);
      toast.success('删除成功');
      fetchData();
    } catch (e: any) {
      toast.error(e.message || '删除失败');
    }
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`确定批量删除 ${selectedIds.size} 个项目吗？`)) return;
    setBatchDeleting(true);
    try {
      const res = await adminApi.batchDeleteProjects(Array.from(selectedIds));
      toast.success(`已删除 ${res.data.deleted} 个项目`);
      fetchData();
    } catch (e: any) {
      toast.error(e.message || '批量删除失败');
    } finally {
      setBatchDeleting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderKanban className="h-5 w-5 text-blue-600" />
          <h2 className="text-lg font-semibold">项目管理</h2>
        </div>
        <div className="text-sm text-gray-500">共 {total} 条</div>
      </div>

      <form onSubmit={onSearch} className="flex flex-wrap gap-2">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input value={username} onChange={e => setUsername(e.target.value)} placeholder="按用户名搜索"
            className="w-56 pl-9 pr-3 py-2 border rounded-lg text-sm" />
        </div>
        <select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }} className="px-3 py-2 border rounded-lg text-sm">
          <option value="">全部状态</option>
          <option value="active">active</option>
          <option value="draft">draft</option>
          <option value="archived">archived</option>
        </select>
        <button type="submit" className="px-3 py-2 rounded-lg border text-sm hover:bg-gray-50">搜索</button>
        <button type="button" disabled={batchDeleting || selectedIds.size === 0} onClick={handleBatchDelete}
          className="px-3 py-2 rounded-lg bg-red-600 text-white text-sm disabled:opacity-50">
          {batchDeleting ? '删除中...' : `批量删除(${selectedIds.size})`}
        </button>
      </form>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中...
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-400 border rounded-xl bg-white">暂无项目</div>
      ) : (
        <>
          <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-3 py-3 text-left"><input type="checkbox" checked={items.length > 0 && selectedIds.size === items.length} onChange={toggleSelectAll} /></th>
                  <th className="px-3 py-3 text-left">缩略图</th>
                  <th className="px-3 py-3 text-left">项目名</th>
                  <th className="px-3 py-3 text-left">状态</th>
                  <th className="px-3 py-3 text-left">用户</th>
                  <th className="px-3 py-3 text-left">更新时间</th>
                  <th className="px-3 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {items.map(item => (
                  <tr key={item.id} className="hover:bg-gray-50">
                    <td className="px-3 py-3"><input type="checkbox" checked={selectedIds.has(item.id)} onChange={() => toggleSelect(item.id)} /></td>
                    <td className="px-3 py-3">
                      {item.thumbnail ? (
                        <img src={item.thumbnail} alt={item.name} className="h-10 w-16 rounded object-cover border" />
                      ) : (
                        <div className="h-10 w-16 rounded border bg-gray-100" />
                      )}
                    </td>
                    <td className="px-3 py-3 max-w-[260px] truncate">{item.name}</td>
                    <td className="px-3 py-3">{item.status || 'active'}</td>
                    <td className="px-3 py-3">{item.username} (UID:{item.user_id})</td>
                    <td className="px-3 py-3 text-xs text-gray-500">{item.updated_at?.slice(0, 19)}</td>
                    <td className="px-3 py-3">
                      <div className="flex justify-end gap-2">
                        <a href={`/projects/${item.id}`} target="_blank" className="p-1.5 rounded border hover:bg-gray-50">
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                        <button onClick={() => handleDeleteOne(item.id)} className="p-1.5 rounded border text-red-600 hover:bg-red-50">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-sm">
            <div className="text-gray-500">第 {page} / {totalPages} 页</div>
            <div className="flex gap-2">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-3 py-1.5 rounded border disabled:opacity-50">上一页</button>
              <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} className="px-3 py-1.5 rounded border disabled:opacity-50">下一页</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
