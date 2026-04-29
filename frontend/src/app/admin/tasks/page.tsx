'use client';

import { useState, useEffect } from 'react';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';
import { 
  Activity, Bot, Workflow, Search, Trash2,
  ChevronLeft, ChevronRight, AlertCircle
} from 'lucide-react';
import { cn } from '@/lib/utils';

export default function GlobalTasksPage() {
  const [activeTab, setActiveTab] = useState<'workflow' | 'ai'>('workflow');
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [username, setUsername] = useState('');
  const [status, setStatus] = useState('');

  const fetchData = async () => {
    setLoading(true);
    try {
      if (activeTab === 'workflow') {
        const res = await adminApi.getWorkflowTasks({ page, limit: 15, username, status });
        setData(res.data.items);
        setTotal(res.data.total);
      } else {
        const res = await adminApi.getAiTasks({ page, limit: 15, username, status });
        setData(res.data.items);
        setTotal(res.data.total);
      }
    } catch (e: any) {
      toast.error(e.message || '获取数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [activeTab, page, status]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchData();
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除此任务记录吗？')) return;
    try {
      if (activeTab === 'workflow') {
        await adminApi.deleteWorkflowTask(id);
      } else {
        // AI task deletion endpoint might need to be added or used from common resources
        // For now just alert or implementation if exists
        toast.error('AI 任务暂不支持从此处直接删除');
        return;
      }
      toast.success('已删除');
      fetchData();
    } catch (e: any) {
      toast.error(e.message || '删除失败');
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Activity className="h-6 w-6 text-indigo-500" />
            任务中心
          </h1>
          <p className="text-sm text-gray-500 mt-1">统一查看 AI 生图任务与工作流执行任务。工作流页面中的“运行日志”用于审计回溯，这里用于任务运营与状态处理。</p>
        </div>

        <div className="flex bg-gray-100 p-1 rounded-xl">
          <button
            onClick={() => { setActiveTab('workflow'); setPage(1); }}
            className={cn(
              "px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2",
              activeTab === 'workflow' ? "bg-white text-indigo-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
            )}
          >
            <Workflow className="h-4 w-4" />
            工作流任务
          </button>
          <button
            onClick={() => { setActiveTab('ai'); setPage(1); }}
            className={cn(
              "px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2",
              activeTab === 'ai' ? "bg-white text-indigo-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
            )}
          >
            <Bot className="h-4 w-4" />
            AI 生图任务
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white p-4 rounded-xl border shadow-sm flex flex-wrap items-center gap-4">
        <form onSubmit={handleSearch} className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="按用户名搜索..."
            value={username}
            onChange={e => setUsername(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none transition-all"
          />
        </form>

        <select
          value={status}
          onChange={e => setStatus(e.target.value)}
          className="px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all"
        >
          <option value="">所有状态</option>
          {activeTab === 'workflow' ? (
            <>
              <option value="pending">排队中</option>
              <option value="running">运行中</option>
              <option value="succeeded">成功</option>
              <option value="failed">失败</option>
            </>
          ) : (
            <>
              <option value="pending">排队中</option>
              <option value="processing">处理中</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
            </>
          )}
        </select>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-6 py-4 font-semibold text-gray-700">任务 ID</th>
                <th className="px-6 py-4 font-semibold text-gray-700">用户</th>
                <th className="px-6 py-4 font-semibold text-gray-700">
                  {activeTab === 'workflow' ? '工作流名称' : '模型'}
                </th>
                <th className="px-6 py-4 font-semibold text-gray-700">状态</th>
                <th className="px-6 py-4 font-semibold text-gray-700">创建时间</th>
                <th className="px-6 py-4 font-semibold text-gray-700 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    <td colSpan={6} className="px-6 py-4"><div className="h-4 bg-gray-100 rounded w-full"></div></td>
                  </tr>
                ))
              ) : data.length > 0 ? (
                data.map((item) => (
                  <tr key={item.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4 font-mono text-xs text-gray-500">#{item.id}</td>
                    <td className="px-6 py-4">
                      <div className="font-medium text-gray-900">{item.username}</div>
                      <div className="text-[10px] text-gray-400">UID: {item.user_id}</div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-gray-700 font-medium">
                        {activeTab === 'workflow' ? item.workflow_name : item.model_name}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={cn(
                        "px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider",
                        item.status === 'succeeded' || item.status === 'completed' ? "bg-green-50 text-green-600" :
                        item.status === 'failed' ? "bg-red-50 text-red-600" :
                        "bg-blue-50 text-blue-600"
                      )}>
                        {item.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-gray-500 text-xs">
                      {item.created_at.slice(0, 19).replace('T', ' ')}
                    </td>
                    <td className="px-6 py-4 text-right space-x-2">
                      <button 
                        onClick={() => handleDelete(item.id)}
                        className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="px-6 py-20 text-center text-gray-500">
                    <div className="flex flex-col items-center gap-2">
                      <AlertCircle className="h-8 w-8 text-gray-200" />
                      <p>暂无符合条件的任务记录</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {total > 15 && (
          <div className="px-6 py-4 border-t flex items-center justify-between bg-gray-50/50">
            <div className="text-xs text-gray-500">
              共 {total} 条记录，第 {page} / {Math.ceil(total / 15)} 页
            </div>
            <div className="flex items-center gap-2">
              <button
                disabled={page === 1}
                onClick={() => setPage(p => p - 1)}
                className="p-1.5 rounded-lg border bg-white hover:bg-gray-50 disabled:opacity-50 transition-all"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                disabled={page >= Math.ceil(total / 15)}
                onClick={() => setPage(p => p + 1)}
                className="p-1.5 rounded-lg border bg-white hover:bg-gray-50 disabled:opacity-50 transition-all"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
