'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';
import { Trash2, Search, Eye, CheckSquare, Square, Filter } from 'lucide-react';
import { cn } from '@/lib/utils';

interface GalleryItem {
  id: number;
  name: string;
  url: string | null;
  width: number;
  height: number;
  type?: string;
  category?: string | null;
  tags?: string[];
  ai_meta?: Record<string, unknown> | null;
  created_by?: number | null;
  created_by_name?: string | null;
  created_at: string;
}

export default function GalleryAdminPage() {
  const searchParams = useSearchParams();
  const initUsername = searchParams?.get('username') ?? undefined;

  const [activeTab, setActiveTab] = useState<'materials' | 'templates'>('materials');
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [usernameFilter, setUsernameFilter] = useState<string | undefined>(initUsername);
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [onlyAi, setOnlyAi] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [userOptions, setUserOptions] = useState<string[]>([]);

  const fetchData = useCallback(() => {
    setLoading(true);
    const apiCall = activeTab === 'templates'
      ? adminApi.getTemplates(page)
      : adminApi.getMaterials({ page, limit: 20, username: usernameFilter, type: typeFilter || undefined });

    apiCall.then(res => {
      setItems(res.data.items);
      setTotal(res.data.total);
      setSelectedIds(new Set());
    }).catch(console.error).finally(() => setLoading(false));
  }, [activeTab, page, usernameFilter, typeFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    adminApi.getUsers(1, 200)
      .then((res) => {
        const names = (res.data.items || []).map(u => u.username).filter(Boolean);
        setUserOptions(names);
      })
      .catch(() => setUserOptions([]));
  }, []);

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这个素材吗？')) return;
    setDeletingId(id);
    try {
      await adminApi.deleteMaterial(id);
      toast.success('已删除');
      fetchData();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  const filtered = useMemo(() => {
    let list = items;
    if (searchQuery) {
      const kw = searchQuery.toLowerCase();
      list = list.filter(i => i.name.toLowerCase().includes(kw));
    }
    if (onlyAi) {
      list = list.filter(i => Boolean(i.ai_meta));
    }
    return list;
  }, [items, searchQuery, onlyAi]);

  const allSelected = filtered.length > 0 && filtered.every(i => selectedIds.has(i.id));

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(new Set());
      return;
    }
    setSelectedIds(new Set(filtered.map(i => i.id)));
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) {
      toast.error('请先选择要删除的素材');
      return;
    }
    if (!confirm(`确认批量删除 ${selectedIds.size} 个素材吗？`)) return;
    setBatchDeleting(true);
    try {
      const ids = Array.from(selectedIds);
      let ok = 0;
      for (const id of ids) {
        try {
          await adminApi.deleteMaterial(id);
          ok += 1;
        } catch {
          // keep going
        }
      }
      toast.success(`批量删除完成：成功 ${ok} / ${ids.length}`);
      fetchData();
    } finally {
      setBatchDeleting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">资产中心</h2>
        <span className="text-sm text-gray-500">共 {total} 个</span>
      </div>

      <div className="flex gap-2 border-b">
        {([['materials', '素材资产'], ['templates', '模板资产']] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => { setActiveTab(key); setPage(1); setSearchQuery(''); }}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === key ? 'border-indigo-500 text-indigo-700' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <div className="relative max-w-xs">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="搜索素材名..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border bg-white py-1.5 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
          />
        </div>

        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-gray-400" />
          <select value={typeFilter} onChange={e => { setTypeFilter(e.target.value); setPage(1); }}
            className="px-2 py-1.5 rounded-lg border text-xs">
            <option value="">全部类型</option>
            <option value="image">图片</option>
            <option value="video">视频</option>
            <option value="audio">音频</option>
            <option value="template">模板</option>
          </select>
          <label className="inline-flex items-center gap-1 text-xs text-gray-600">
            <input type="checkbox" checked={onlyAi} onChange={e => setOnlyAi(e.target.checked)} className="rounded" />
            仅 AI 元数据
          </label>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-500">用户:</label>
          <select
            className="w-36 px-3 py-1.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
            value={usernameFilter ?? ''}
            onChange={e => { setUsernameFilter(e.target.value || undefined); setPage(1); }}
          >
            <option value="">全部用户</option>
            {userOptions.map(name => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>

        <button onClick={toggleSelectAll} className="ml-auto text-xs px-3 py-1.5 rounded-lg border hover:bg-gray-50 inline-flex items-center gap-1">
          {allSelected ? <CheckSquare className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
          {allSelected ? '取消全选' : '全选当前页'}
        </button>
        <button
          onClick={handleBatchDelete}
          disabled={batchDeleting || selectedIds.size === 0}
          className={cn(
            'text-xs px-3 py-1.5 rounded-lg border inline-flex items-center gap-1',
            selectedIds.size > 0 ? 'text-red-600 border-red-200 hover:bg-red-50' : 'text-gray-400 border-gray-200 cursor-not-allowed',
          )}
        >
          <Trash2 className="h-3.5 w-3.5" />
          {batchDeleting ? '删除中...' : `批量删除(${selectedIds.size})`}
        </button>
      </div>

      {loading ? (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="aspect-square bg-gray-100 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20 text-sm text-gray-500">暂无数据</div>
      ) : (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3">
          {filtered.map(img => (
            <div key={img.id} className="group relative bg-white rounded-xl border shadow-sm overflow-hidden">
              <button
                onClick={() => toggleSelect(img.id)}
                className="absolute top-1.5 left-1.5 z-10 flex h-5 w-5 items-center justify-center rounded bg-white/90 border"
              >
                {selectedIds.has(img.id) ? <CheckSquare className="h-3.5 w-3.5 text-indigo-600" /> : <Square className="h-3.5 w-3.5 text-gray-500" />}
              </button>

              <div className="aspect-square flex items-center justify-center bg-gray-50 p-1">
                {img.url ? (
                  <img src={img.url} alt={img.name} className="w-full h-full object-contain cursor-pointer" onClick={() => setPreviewUrl(img.url)} />
                ) : (
                  <span className="text-xs text-gray-400">无预览</span>
                )}
              </div>

              <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/50 to-transparent p-1.5 pt-4">
                <p className="text-[10px] text-white truncate">{img.name}</p>
              </div>

              <div className="absolute top-1.5 right-1.5 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                {img.url && (
                  <button onClick={() => setPreviewUrl(img.url)} className="flex h-6 w-6 items-center justify-center rounded-full bg-white/90 shadow-sm hover:bg-white">
                    <Eye className="h-3 w-3" />
                  </button>
                )}
                <button onClick={() => handleDelete(img.id)} disabled={deletingId === img.id}
                  className="flex h-6 w-6 items-center justify-center rounded-full bg-red-500/90 shadow-sm hover:bg-red-600 text-white disabled:opacity-50">
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {total > 20 && (
        <div className="flex items-center justify-between border-t bg-white rounded-lg px-4 py-3">
          <span className="text-xs text-gray-500">第 {page} 页 / 共 {Math.ceil(total / 20)} 页</span>
          <div className="flex gap-2">
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
              className="px-3 py-1 text-xs rounded-md border disabled:opacity-40 hover:bg-gray-50">上一页</button>
            <button disabled={page * 20 >= total} onClick={() => setPage(p => p + 1)}
              className="px-3 py-1 text-xs rounded-md border disabled:opacity-40 hover:bg-gray-50">下一页</button>
          </div>
        </div>
      )}

      {previewUrl && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={() => setPreviewUrl(null)}>
          <img src={previewUrl} alt="preview" className="max-w-[90vw] max-h-[90vh] object-contain" />
          <button onClick={() => setPreviewUrl(null)} className="absolute top-4 right-4 text-white text-sm hover:underline">关闭</button>
        </div>
      )}
    </div>
  );
}
