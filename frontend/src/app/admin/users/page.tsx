'use client';

import { useState, useEffect } from 'react';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';
import { Shield, User as UserIcon, Eye, Plus, Trash2, X, Workflow } from 'lucide-react';

interface AppUser {
  id: number;
  username: string;
  display_name?: string | null;
  email: string;
  avatar: string | null;
  is_active: boolean;
  role: string;
  roles?: string[];
  created_at: string;
}

const USER_ROLES = [
  { value: 'admin', label: '管理员', badgeClass: 'bg-slate-950 text-white border-slate-950' },
  { value: 'xhs_lead', label: '小红书部门负责人', badgeClass: 'bg-indigo-50 text-indigo-700 border-indigo-100' },
  { value: 'xhs_ops', label: '小红书运营', badgeClass: 'bg-rose-50 text-rose-700 border-rose-100' },
  { value: 'buyer', label: '投手', badgeClass: 'bg-amber-50 text-amber-700 border-amber-100' },
  { value: 'brand_lead', label: '品牌责任人', badgeClass: 'bg-sky-50 text-sky-700 border-sky-100' },
  { value: 'brand_ops', label: '品牌运营', badgeClass: 'bg-emerald-50 text-emerald-700 border-emerald-100' },
  { value: 'viewer', label: '普通用户', badgeClass: 'bg-gray-50 text-gray-600 border-gray-100' },
];

function getUserRoles(user: Pick<AppUser, 'role' | 'roles'>): string[] {
  return user.roles?.length ? user.roles : [user.role || 'viewer'];
}

export default function UsersPage() {
  const [users, setUsers] = useState<AppUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState<number | null>(null);
  const [editingName, setEditingName] = useState<Record<number, string>>({});
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [showWorkflowModal, setShowWorkflowModal] = useState(false);
  const [selectedUserForStats, setSelectedUserForStats] = useState<AppUser | null>(null);

  const fetchUsers = () => {
    setLoading(true);
    adminApi.getUsers(page).then(res => {
      setUsers(res.data.items);
      setTotal(res.data.total);
    }).catch(console.error).finally(() => setLoading(false));
  };

  useEffect(() => { fetchUsers(); }, [page]);

  const updateRoles = async (userId: number, roles: string[]) => {
    setUpdating(userId);
    try {
      await adminApi.updateUserRoles(userId, roles.length ? roles : ['viewer']);
      toast.success('角色已更新');
      fetchUsers();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '更新失败');
    } finally {
      setUpdating(null);
    }
  };

  const updateActive = async (userId: number, active: boolean) => {
    setUpdating(userId);
    try {
      await adminApi.updateUserActive(userId, active);
      toast.success(active ? '已启用' : '已禁用');
      fetchUsers();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '操作失败');
    } finally {
      setUpdating(null);
    }
  };

  const updateDisplayName = async (userId: number) => {
    const displayName = (editingName[userId] ?? '').trim();
    setUpdating(userId);
    try {
      await adminApi.updateUserProfile(userId, { display_name: displayName || null });
      toast.success('展示名已更新');
      setEditingName((prev) => {
        const next = { ...prev };
        delete next[userId];
        return next;
      });
      fetchUsers();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '更新失败');
    } finally {
      setUpdating(null);
    }
  };

  const handleDelete = async (userId: number, username: string) => {
    if (!confirm(`确定要删除用户 "${username}" 吗？`)) return;
    try {
      await adminApi.deleteUser(userId);
      toast.success('用户已删除');
      fetchUsers();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="h-6 w-24 bg-gray-100 rounded animate-pulse" />
          <div className="h-4 w-20 bg-gray-100 rounded animate-pulse" />
        </div>
        <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                {['用户', '邮箱', '角色', '状态', '注册时间', '操作'].map(h => (
                  <th key={h} className="text-left px-4 py-3 font-medium text-gray-600">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 6 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-gray-100 rounded animate-pulse" style={{ width: `${40 + Math.random() * 40}%` }} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">用户管理</h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">共 {total} 个用户</span>
          <button onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-foreground text-white hover:bg-foreground/90 transition-colors">
            <Plus className="h-4 w-4" /> 新建用户
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">用户</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">邮箱</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">角色</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">状态</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">注册时间</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {users.map(u => (
              <tr key={u.id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-100">
                      <UserIcon className="h-4 w-4 text-gray-500" />
                    </div>
                    <div className="min-w-[160px]">
                      <input
                        value={editingName[u.id] ?? u.display_name ?? ''}
                        onChange={(event) => setEditingName((prev) => ({ ...prev, [u.id]: event.target.value }))}
                        onBlur={() => {
                          const nextName = (editingName[u.id] ?? u.display_name ?? '').trim();
                          if (nextName !== (u.display_name ?? '')) updateDisplayName(u.id);
                        }}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') event.currentTarget.blur();
                        }}
                        disabled={updating === u.id}
                        placeholder="填写展示名"
                        className="w-full rounded-md border border-transparent bg-transparent px-2 py-1 font-medium text-slate-950 outline-none transition hover:border-slate-200 hover:bg-white focus:border-slate-300 focus:bg-white"
                      />
                      <div className="px-2 text-xs text-gray-400">登录账号：{u.username}</div>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3 text-gray-500">{u.email}</td>
                <td className="px-4 py-3">
                  <RoleMultiSelect
                    roles={getUserRoles(u)}
                    disabled={updating === u.id}
                    onChange={(roles) => updateRoles(u.id, roles)}
                  />
                </td>
                <td className="px-4 py-3">
                  <button
                    disabled={updating === u.id}
                    onClick={() => updateActive(u.id, !u.is_active)}
                    className={u.is_active
                      ? 'text-green-600 text-xs font-medium'
                      : 'text-red-500 text-xs font-medium'}
                  >
                    {u.is_active ? '启用中' : '已禁用'}
                  </button>
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">{u.created_at?.slice(0, 10)}</td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-3">
                    <button
                      onClick={() => {
                        setSelectedUserId(u.id);
                        setShowWorkflowModal(true);
                      }}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
                    >
                      <Workflow className="h-3.5 w-3.5" />
                      工作流
                    </button>
                    <button
                      onClick={() => setSelectedUserForStats(u)}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-emerald-600 bg-emerald-50 rounded-lg hover:bg-emerald-100 transition-colors"
                    >
                      <Eye className="h-3.5 w-3.5" />
                      详情
                    </button>
                    <button
                      disabled={updating === u.id}
                      onClick={() => handleDelete(u.id, u.username)}
                      className="flex items-center gap-1 text-xs text-red-600 hover:underline disabled:opacity-50"
                    >
                      <Trash2 className="h-3 w-3" />
                      删除
                    </button>
                  </div>
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

      {showCreateModal && (
        <CreateUserModal onClose={() => setShowCreateModal(false)}
          onCreated={() => { setShowCreateModal(false); fetchUsers(); }} />
      )}

      {showWorkflowModal && selectedUserId && (
        <WorkflowAccessModal
          userId={selectedUserId}
          onClose={() => {
            setShowWorkflowModal(false);
            setSelectedUserId(null);
          }}
        />
      )}

      {selectedUserForStats && (
        <UserStatsModal
          user={selectedUserForStats}
          onClose={() => setSelectedUserForStats(null)}
        />
      )}
    </div>
  );
}

function UserStatsModal({ user, onClose }: { user: AppUser; onClose: () => void }) {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminApi.getUserStats(user.id)
      .then(res => setStats(res.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [user.id]);

  const handleDeleteTasks = async (type: 'ai' | 'workflow') => {
    if (!confirm(`确定要清空该用户的所有${type === 'ai' ? 'AI 生图' : '工作流'}任务记录吗？此操作不可撤销。`)) return;
    try {
      await adminApi.batchDeleteUserTasks(user.id, type);
      toast.success('已清空记录');
      // Refresh stats
      const res = await adminApi.getUserStats(user.id);
      setStats(res.data);
    } catch (e: any) {
      toast.error(e.message || '操作失败');
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in duration-200">
        <div className="px-6 py-4 border-b flex items-center justify-between bg-gray-50/50">
          <div>
            <h3 className="font-semibold text-gray-900">用户资源统计</h3>
            <p className="text-xs text-gray-500 mt-0.5">{user.username} ({user.email})</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-200 rounded-full transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-6">
          {loading ? (
            <div className="flex justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500"></div>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-indigo-50 border border-indigo-100">
                  <div className="text-xs text-indigo-600 font-medium mb-1">AI 生图任务</div>
                  <div className="text-2xl font-bold text-indigo-900">{stats?.ai_tasks}</div>
                </div>
                <div className="p-4 rounded-xl bg-cyan-50 border border-cyan-100">
                  <div className="text-xs text-cyan-600 font-medium mb-1">工作流任务</div>
                  <div className="text-2xl font-bold text-cyan-900">{stats?.wf_tasks}</div>
                </div>
                <div className="p-4 rounded-xl bg-amber-50 border border-amber-100">
                  <div className="text-xs text-amber-600 font-medium mb-1">项目总数</div>
                  <div className="text-2xl font-bold text-amber-900">{stats?.projects}</div>
                </div>
                <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-100">
                  <div className="text-xs text-emerald-600 font-medium mb-1">存储占用</div>
                  <div className="text-2xl font-bold text-emerald-900">{stats?.storage_mb} MB</div>
                </div>
              </div>

              <div className="space-y-3 pt-4 border-t">
                <h4 className="text-sm font-semibold text-gray-900">危险操作</h4>
                <div className="flex flex-col gap-2">
                  <button
                    onClick={() => handleDeleteTasks('ai')}
                    className="w-full flex items-center justify-between px-4 py-2 text-sm text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-colors group"
                  >
                    <span>清空 AI 生图记录</span>
                    <Trash2 className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </button>
                  <button
                    onClick={() => handleDeleteTasks('workflow')}
                    className="w-full flex items-center justify-between px-4 py-2 text-sm text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-colors group"
                  >
                    <span>清空工作流运行记录</span>
                    <Trash2 className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="px-6 py-4 bg-gray-50 border-t flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   WORKFLOW ACCESS MODAL
   ============================================================ */

function WorkflowAccessModal({ userId, onClose }: { userId: number; onClose: () => void }) {
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [allWfRes, userWfRes] = await Promise.all([
          adminApi.getAdminWorkflows(1, 100),
          adminApi.getUserWorkflows(userId)
        ]);
        setWorkflows(allWfRes.data.items);
        setSelectedIds(userWfRes.data.map((w: any) => w.id));
      } catch (e) {
        toast.error('获取工作流失败');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [userId]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await adminApi.setUserWorkflows(userId, selectedIds);
      toast.success('权限已更新');
      onClose();
    } catch (e) {
      toast.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const toggleWorkflow = (id: number) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
    );
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl border w-[500px] max-h-[80vh] flex flex-col overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h3 className="text-sm font-semibold">工作流权限配置</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 overflow-y-auto flex-1">
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-10 bg-gray-100 rounded animate-pulse" />
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              {workflows.map(w => (
                <label key={w.id} className="flex items-center gap-3 p-3 rounded-xl border hover:bg-gray-50 transition-colors cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(w.id)}
                    onChange={() => toggleWorkflow(w.id)}
                    className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-600"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-medium">{w.app_name}</div>
                    {w.description && <div className="text-xs text-gray-500 line-clamp-1">{w.description}</div>}
                  </div>
                  <div className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 uppercase">
                    {w.app_type}
                  </div>
                </label>
              ))}
              {workflows.length === 0 && (
                <div className="text-center py-10 text-gray-500 text-sm">
                  暂无工作流
                </div>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-2 p-5 border-t bg-gray-50">
          <button onClick={onClose} disabled={saving}
            className="flex-1 rounded-lg border bg-white py-2 text-sm hover:bg-neutral-50 transition-colors disabled:opacity-50">取消</button>
          <button onClick={handleSave} disabled={saving || loading}
            className="flex-1 rounded-lg bg-foreground text-white py-2 text-sm hover:bg-foreground/90 transition-colors disabled:opacity-50">
            {saving ? '保存中...' : '确认保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   CREATE USER MODAL
   ============================================================ */

function RoleMultiSelect({ roles, disabled, onChange }: { roles: string[]; disabled?: boolean; onChange: (roles: string[]) => void }) {
  const selected = roles.length ? roles : ['viewer'];
  const toggle = (role: string) => {
    const exists = selected.includes(role);
    let next = exists ? selected.filter(item => item !== role) : [...selected.filter(item => item !== 'viewer'), role];
    if (role === 'viewer' && !exists) next = ['viewer'];
    if (!next.length) next = ['viewer'];
    onChange(next);
  };

  return (
    <div className="flex flex-wrap gap-1.5">
      {USER_ROLES.map((role) => {
        const active = selected.includes(role.value);
        return (
          <button
            key={role.value}
            type="button"
            disabled={disabled}
            onClick={() => toggle(role.value)}
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-semibold transition disabled:opacity-50 ${
              active ? role.badgeClass : 'border-gray-200 bg-white text-gray-400 hover:border-gray-300'
            }`}
          >
            <Shield className="h-3 w-3" />
            {role.label}
          </button>
        );
      })}
    </div>
  );
}

function CreateUserModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [roles, setRoles] = useState<string[]>(['viewer']);
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    if (!username.trim() || !email.trim() || !password.trim()) {
      toast.error('请填写所有必填字段');
      return;
    }
    setLoading(true);
    try {
      await adminApi.createUser({
        username: username.trim(),
        display_name: displayName.trim(),
        email: email.trim().toLowerCase(),
        password,
        roles,
      });
      toast.success('用户创建成功');
      onCreated();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '创建失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl border w-[420px] overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h3 className="text-sm font-semibold">新建用户</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100 transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">用户名</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)}
              placeholder="用于登录，例如 zt123"
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">展示名</label>
            <input type="text" value={displayName} onChange={e => setDisplayName(e.target.value)}
              placeholder="看板显示，例如 张婷"
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">邮箱</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="请输入邮箱"
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">密码</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
              placeholder="请设置密码"
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/10 focus:border-foreground/20 transition-all" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">角色</label>
            <RoleMultiSelect roles={roles} onChange={setRoles} />
          </div>
        </div>
        <div className="flex gap-2 p-5 border-t">
          <button onClick={onClose} disabled={loading}
            className="flex-1 rounded-lg border py-2 text-sm hover:bg-neutral-50 transition-colors disabled:opacity-50">取消</button>
          <button onClick={handleCreate} disabled={loading}
            className="flex-1 rounded-lg bg-foreground text-white py-2 text-sm hover:bg-foreground/90 transition-colors disabled:opacity-50">
            {loading ? '创建中...' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
}
