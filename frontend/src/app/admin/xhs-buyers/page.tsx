'use client';

import { useEffect, useMemo, useState } from 'react';
import { Pencil, Plus, Search, Target, Trash2, UserRoundCheck, X } from 'lucide-react';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';

type User = {
  id: number;
  username: string;
  display_name?: string | null;
  email: string;
  role: string;
  roles?: string[];
};

type Assignment = {
  account_id: string;
  account_name: string;
  token_status?: string | null;
  user_id?: number | null;
  buyer_username?: string | null;
  buyer_display_name?: string | null;
  buyer_email?: string | null;
  xhs_account_id?: string | null;
  xhs_account_name?: string | null;
  xhs_owner_name?: string | null;
};

type AccountForm = {
  account_id: string;
  account_name: string;
};

type ProfessionalDraft = {
  xhs_account_id: string;
  xhs_account_name: string;
  xhs_owner_name: string;
};

const emptyAccountForm: AccountForm = {
  account_id: '',
  account_name: '',
};

function hasRole(user: User, role: string) {
  return user.role === role || Boolean(user.roles?.includes(role));
}

export default function XhsBuyersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null);
  const [accountForm, setAccountForm] = useState<AccountForm>(emptyAccountForm);
  const [professionalDrafts, setProfessionalDrafts] = useState<Record<string, ProfessionalDraft>>({});

  const buyers = useMemo(
    () => users.filter((user) => (
      hasRole(user, 'buyer')
      || hasRole(user, 'xhs_ops')
      || hasRole(user, 'xhs_lead')
      || hasRole(user, 'admin')
    )),
    [users],
  );

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return assignments;
    return assignments.filter((item) => (
      item.account_id.toLowerCase().includes(q)
      || item.account_name.toLowerCase().includes(q)
      || String(item.buyer_username || '').toLowerCase().includes(q)
      || String(item.buyer_display_name || '').toLowerCase().includes(q)
      || String(item.xhs_account_id || '').toLowerCase().includes(q)
      || String(item.xhs_account_name || '').toLowerCase().includes(q)
      || String(item.xhs_owner_name || '').toLowerCase().includes(q)
    ));
  }, [assignments, keyword]);

  const loadData = () => {
    setLoading(true);
    Promise.all([
      adminApi.getUsers(1, 100),
      adminApi.getXhsAdAccountAssignments(),
    ])
      .then(([userRes, assignmentRes]) => {
        setUsers(userRes.data.items);
        setAssignments(assignmentRes.data);
      })
      .catch((error) => toast.error(error instanceof Error ? error.message : '加载失败'))
      .finally(() => setLoading(false));
  };

  const startCreate = () => {
    setEditingAccountId(null);
    setAccountForm(emptyAccountForm);
  };

  const startEdit = (item: Assignment) => {
    setEditingAccountId(item.account_id);
    setAccountForm({
      account_id: item.account_id,
      account_name: item.account_name,
    });
  };

  const resetForm = () => {
    setEditingAccountId(null);
    setAccountForm(emptyAccountForm);
  };

  const saveAccount = async () => {
    const accountId = accountForm.account_id.trim();
    const accountName = accountForm.account_name.trim();
    if (!accountId || !accountName) {
      toast.error('请填写广告账户 ID 和名称');
      return;
    }
    setSavingKey(editingAccountId ? `edit:${editingAccountId}` : 'create');
    try {
      if (editingAccountId) {
        await adminApi.updateXhsAdAccount({
          account_id: editingAccountId,
          new_account_id: accountId,
          account_name: accountName,
        });
        toast.success('广告账户已更新');
      } else {
        await adminApi.createXhsAdAccount({
          account_id: accountId,
          account_name: accountName,
        });
        toast.success('广告账户已新增');
      }
      resetForm();
      await adminApi.getXhsAdAccountAssignments().then((res) => setAssignments(res.data));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSavingKey(null);
    }
  };

  const deleteAccount = async (item: Assignment) => {
    if (!window.confirm(`确定删除广告账户「${item.account_name}」吗？该账号的投手分配和历史投流报表行也会一起删除。`)) return;
    setSavingKey(`delete:${item.account_id}`);
    try {
      await adminApi.deleteXhsAdAccount(item.account_id);
      toast.success('广告账户已删除');
      if (editingAccountId === item.account_id) resetForm();
      await adminApi.getXhsAdAccountAssignments().then((res) => setAssignments(res.data));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '删除失败');
    } finally {
      setSavingKey(null);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    setProfessionalDrafts(Object.fromEntries(assignments.map((item) => [
      item.account_id,
      {
        xhs_account_id: item.xhs_account_id || '',
        xhs_account_name: item.xhs_account_name || '',
        xhs_owner_name: item.xhs_owner_name || '',
      },
    ])));
  }, [assignments]);

  const assign = async (accountId: string, userId: string) => {
    setSavingKey(accountId);
    try {
      if (userId) {
        await adminApi.assignXhsAdAccountBuyer(accountId, Number(userId));
        toast.success('投手已分配');
      } else {
        await adminApi.unassignXhsAdAccountBuyer(accountId);
        toast.success('已解除分配');
      }
      await adminApi.getXhsAdAccountAssignments().then((res) => setAssignments(res.data));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSavingKey(null);
    }
  };

  const updateProfessionalDraft = (accountId: string, patch: Partial<ProfessionalDraft>) => {
    setProfessionalDrafts((current) => {
      const existing = current[accountId] || { xhs_account_id: '', xhs_account_name: '', xhs_owner_name: '' };
      return {
        ...current,
        [accountId]: {
          ...existing,
          ...patch,
        },
      };
    });
  };

  const saveProfessionalMapping = async (accountId: string) => {
    const draft = professionalDrafts[accountId] || { xhs_account_id: '', xhs_account_name: '', xhs_owner_name: '' };
    setSavingKey(`professional:${accountId}`);
    try {
      await adminApi.updateXhsAdAccountProfessionalMapping({
        account_id: accountId,
        xhs_account_id: draft.xhs_account_id.trim() || null,
        xhs_account_name: draft.xhs_account_name.trim() || null,
        xhs_owner_name: draft.xhs_owner_name.trim() || null,
      });
      toast.success('专业号映射已保存');
      await adminApi.getXhsAdAccountAssignments().then((res) => setAssignments(res.data));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-amber-50 px-3 py-1 text-xs font-bold uppercase tracking-[0.18em] text-amber-700">
              <Target className="h-3.5 w-3.5" />
              Buyer Assignment
            </div>
            <h1 className="mt-3 text-2xl font-black tracking-[-0.04em] text-slate-950">投手分配</h1>
            <p className="mt-2 text-sm text-slate-500">一个广告账户只归属一个投流负责人；投流看板会用这里的关系计算负责人维度。</p>
          </div>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div className="text-2xl font-black text-slate-950">{assignments.length}</div>
              <div className="text-xs font-semibold text-slate-500">广告账户</div>
            </div>
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
              <div className="text-2xl font-black text-amber-700">{assignments.filter((item) => item.user_id).length}</div>
              <div className="text-xs font-semibold text-amber-700/75">已分配</div>
            </div>
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
              <div className="text-2xl font-black text-emerald-700">{buyers.length}</div>
              <div className="text-xs font-semibold text-emerald-700/75">可分配用户</div>
            </div>
          </div>
        </div>

        <div className="mt-6 flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <Search className="h-4 w-4 text-slate-400" />
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="搜索广告账户、投手、专业号、专业号负责人"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"
          />
          <button onClick={startCreate} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 hover:border-slate-300 hover:text-slate-950"><Plus className="h-3.5 w-3.5" />新增账户</button>
          <button onClick={loadData} className="rounded-xl bg-slate-950 px-4 py-2 text-xs font-bold text-white hover:bg-slate-800">刷新</button>
        </div>
      </div>

      {(editingAccountId || accountForm.account_id || accountForm.account_name) ? (
        <div className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-black text-slate-950">{editingAccountId ? '编辑广告账户' : '新增广告账户'}</h2>
              <p className="mt-1 text-xs font-medium text-slate-500">账户 ID 用于匹配投流报表，修改 ID 会同步历史报表和分配关系。</p>
            </div>
            <button type="button" onClick={resetForm} className="grid h-9 w-9 place-items-center rounded-xl border border-slate-200 text-slate-500 hover:text-slate-950"><X className="h-4 w-4" /></button>
          </div>
          <div className="grid gap-3 md:grid-cols-[180px_minmax(0,1fr)_auto] md:items-end">
            <label className="block">
              <span className="text-xs font-bold text-slate-500">广告账户 ID</span>
              <input
                value={accountForm.account_id}
                onChange={(event) => setAccountForm((current) => ({ ...current, account_id: event.target.value }))}
                className="mt-1 h-10 w-full rounded-xl border border-slate-200 px-3 text-sm outline-none focus:border-amber-300 focus:ring-4 focus:ring-amber-100"
                placeholder="account_id"
              />
            </label>
            <label className="block">
              <span className="text-xs font-bold text-slate-500">广告账户名称</span>
              <input
                value={accountForm.account_name}
                onChange={(event) => setAccountForm((current) => ({ ...current, account_name: event.target.value }))}
                className="mt-1 h-10 w-full rounded-xl border border-slate-200 px-3 text-sm outline-none focus:border-amber-300 focus:ring-4 focus:ring-amber-100"
                placeholder="账户名称"
              />
            </label>
            <button
              type="button"
              disabled={savingKey === 'create' || savingKey === `edit:${editingAccountId}`}
              onClick={saveAccount}
              className="h-10 rounded-xl bg-slate-950 px-5 text-xs font-bold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {editingAccountId ? '保存修改' : '新增账户'}
            </button>
          </div>
        </div>
      ) : null}

      <div className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-bold uppercase tracking-[0.14em] text-slate-400">
            <tr>
              <th className="px-5 py-4">广告账户</th>
              <th className="px-5 py-4">当前投手</th>
              <th className="px-5 py-4">对应专业号</th>
              <th className="px-5 py-4">分配</th>
              <th className="px-5 py-4 text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan={5} className="px-5 py-14 text-center text-slate-400">加载中...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={5} className="px-5 py-14 text-center text-slate-400">没有匹配的广告账户</td></tr>
            ) : filtered.map((item) => {
              const draft = professionalDrafts[item.account_id] || {
                xhs_account_id: item.xhs_account_id || '',
                xhs_account_name: item.xhs_account_name || '',
                xhs_owner_name: item.xhs_owner_name || '',
              };
              return (
              <tr key={item.account_id} className="hover:bg-slate-50/70">
                <td className="px-5 py-4">
                  <div className="font-bold text-slate-900">{item.account_name}</div>
                  <div className="mt-1 font-mono text-xs text-slate-400">{item.account_id}</div>
                </td>
                <td className="px-5 py-4">
                  {item.user_id ? (
                    <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-700">
                      <UserRoundCheck className="h-3.5 w-3.5" />
                      {item.buyer_display_name || item.buyer_username}
                    </div>
                  ) : (
                    <span className="text-xs font-semibold text-slate-400">未分配</span>
                  )}
                </td>
                <td className="px-5 py-4">
                  <div className="grid min-w-[420px] gap-2 lg:grid-cols-[1.1fr_1fr_0.9fr_auto]">
                    <input
                      value={draft.xhs_account_name}
                      onChange={(event) => updateProfessionalDraft(item.account_id, { xhs_account_name: event.target.value })}
                      placeholder="专业号名称"
                      className="h-9 rounded-xl border border-slate-200 bg-white px-3 text-xs outline-none focus:border-amber-300 focus:ring-4 focus:ring-amber-100"
                    />
                    <input
                      value={draft.xhs_account_id}
                      onChange={(event) => updateProfessionalDraft(item.account_id, { xhs_account_id: event.target.value })}
                      placeholder="专业号ID"
                      className="h-9 rounded-xl border border-slate-200 bg-white px-3 text-xs outline-none focus:border-amber-300 focus:ring-4 focus:ring-amber-100"
                    />
                    <input
                      value={draft.xhs_owner_name}
                      onChange={(event) => updateProfessionalDraft(item.account_id, { xhs_owner_name: event.target.value })}
                      placeholder="负责人"
                      className="h-9 rounded-xl border border-slate-200 bg-white px-3 text-xs outline-none focus:border-amber-300 focus:ring-4 focus:ring-amber-100"
                    />
                    <button
                      type="button"
                      disabled={savingKey === `professional:${item.account_id}`}
                      onClick={() => saveProfessionalMapping(item.account_id)}
                      className="h-9 rounded-xl border border-amber-200 bg-amber-50 px-3 text-xs font-bold text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                    >
                      保存
                    </button>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-400">一个广告账户只能绑定一个专业号；同一专业号可绑定多个广告账户。</p>
                </td>
                <td className="px-5 py-4">
                  <select
                    value={item.user_id || ''}
                    disabled={savingKey === item.account_id}
                    onChange={(event) => assign(item.account_id, event.target.value)}
                    className="w-56 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-amber-300 focus:ring-4 focus:ring-amber-100 disabled:opacity-50"
                  >
                    <option value="">未分配</option>
                    {buyers.map((buyer) => (
                      <option key={buyer.id} value={buyer.id}>{buyer.display_name || buyer.username}</option>
                    ))}
                  </select>
                </td>
                <td className="px-5 py-4">
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => startEdit(item)}
                      className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-slate-200 px-3 text-xs font-bold text-slate-600 hover:border-slate-300 hover:text-slate-950"
                    >
                      <Pencil className="h-3.5 w-3.5" />编辑
                    </button>
                    <button
                      type="button"
                      disabled={savingKey === `delete:${item.account_id}`}
                      onClick={() => deleteAccount(item)}
                      className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-rose-100 bg-rose-50 px-3 text-xs font-bold text-rose-600 hover:border-rose-200 hover:bg-rose-100 disabled:opacity-50"
                    >
                      <Trash2 className="h-3.5 w-3.5" />删除
                    </button>
                  </div>
                </td>
              </tr>
            );})}
          </tbody>
        </table>
      </div>
    </div>
  );
}
