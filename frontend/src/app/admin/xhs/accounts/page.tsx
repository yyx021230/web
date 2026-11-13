'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { xhsAccountMasterApi, type MasterAccount, type MasterApplyRequest, type MasterApplyResult, type MasterPreview } from '@/services/xhsAccountMasterApi';

const departments: Record<string, string> = { xhs: '小红书', brand: '品牌', unresolved: '待确认' };
const statuses: Record<string, string> = { active: '正常', retired: '已注销 · 保留历史', needs_review: '待确认 · 仅管理员可见', archived: '历史归档' };
const warnings: Record<string, string> = { name_missing: '缺少昵称', owner_unresolved: '负责人未能唯一匹配', department_unresolved: '部门待确认', account_type_unresolved: '账号类型待确认' };
const button = 'rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40';

export default function AccountMasterPage() {
  const [accounts, setAccounts] = useState<MasterAccount[]>([]);
  const [preview, setPreview] = useState<MasterPreview | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [history, setHistory] = useState(false);
  const [replaceAll, setReplaceAll] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const [attempt, setAttempt] = useState<MasterApplyRequest | null>(null);
  const [result, setResult] = useState<MasterApplyResult | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [profileEdits,setProfileEdits] = useState<Record<number,string>>({});

  useEffect(() => {
    let active = true;
    xhsAccountMasterApi.accounts().then(data => { if (active) setAccounts(data); })
      .catch(() => { if (active) setError('账号名单加载失败，请刷新重试。'); });
    return () => { active = false; };
  }, []);

  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy('preview'); setError(''); setPreview(null); setResult(null); setAttempt(null); setConfirmed(false); setHistory(false); setReplaceAll(true);
    try {
      const data = await xhsAccountMasterApi.preview(file);
      setPreview(data); setSelected(data.rows.map(row => row.row));
    } catch (e) {
      setError(e instanceof Error ? e.message : '文件预览失败');
    } finally { setBusy(''); }
  }

  async function apply() {
    if (!preview || !confirmed) return;
    const body = attempt || { source_hash: preview.source_hash, rows: selected, include_history: history, replace_all: replaceAll };
    setAttempt(body); setBusy('apply'); setError('');
    try {
      const data = await xhsAccountMasterApi.apply(preview.preview_id, body);
      setResult(data);
      try { setAccounts(await xhsAccountMasterApi.accounts()); }
      catch { setError('应用已成功，但名单刷新失败，请刷新页面查看。'); }
    } catch (e) {
      setError(`${e instanceof Error ? e.message : '应用结果未确认'}。可按原选择再次确认；如提示数据已变化，请重新上传预览。`);
    } finally { setBusy(''); }
  }

  const locked = !!attempt || !!busy || !!result;
  async function saveProfile(account: MasterAccount) {
    setBusy(`profile:${account.id}`);setError('');
    try {
      await xhsAccountMasterApi.profile(account,profileEdits[account.id] ?? account.profile_url ?? '');
      setAccounts(await xhsAccountMasterApi.accounts());
      setProfileEdits(current => { const next={...current};delete next[account.id];return next; });
    } catch(e) { setError(e instanceof Error ? e.message : '主页链接保存失败'); }
    finally { setBusy(''); }
  }
  const currentAccounts = accounts.filter(account => account.status !== 'archived');
  const archivedAccounts = accounts.filter(account => account.status === 'archived');
  return (
    <main className="min-h-screen bg-slate-50 px-5 py-6 text-slate-900 md:px-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Link href="/admin/xhs" className="text-xs text-slate-500 hover:text-slate-900">小红书管理 / 执行环境</Link>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight">账号主名单</h1>
            <p className="mt-2 text-sm text-slate-500">以飞书账号为准。负责人和部门独立维护，不受云登环境增删影响。</p>
          </div>
          <label className={`${button} cursor-pointer bg-white ${busy ? 'pointer-events-none opacity-40' : ''}`}>
            {busy === 'preview' ? '正在核对…' : '导入飞书 CSV'}
            <input type="file" accept=".csv,text/csv" className="sr-only" aria-label="导入飞书CSV" disabled={!!busy}
              onChange={e => { void upload(e.target.files?.[0]); e.target.value = ''; }} />
          </label>
        </header>
        {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</p>}
        {result && <section role="status" className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-900">
          新增 {result.created} 个，更新 {result.updated} 个；归属历史帖 {result.history_notes_moved} 篇。
          剔除空账号 {result.unlisted_accounts_deleted || 0} 个，归档 {result.unlisted_accounts_archived || 0} 个。未删除历史帖子。
          {result.history_conflicts.length > 0 && <details className="mt-3"><summary className="cursor-pointer font-medium">{result.history_conflicts.length} 条冲突原样保留，需人工复核</summary>
            <ul className="mt-2 max-h-48 overflow-auto">{result.history_conflicts.map(item => <li key={item.note_id}>帖子 #{item.note_id} · {item.reason === 'duplicate_identity_retained' ? '重复帖子身份，保留原件' : '身份不一致，未迁移'}</li>)}</ul>
          </details>}
        </section>}
        {preview && !result && <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-5">
            <div><h2 className="font-semibold">导入预览 <span className="ml-2 text-sm font-normal text-slate-400">{preview.rows.length} 个可选账号</span></h2>
              <p className="mt-1 text-xs text-slate-500">预览有效期 30 分钟。私域中心、空 ID 占位均跳过；不移除表外历史资料。</p>
              <a href={preview.source_url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs underline underline-offset-4">查看飞书主表</a>
            </div>
            <button className={button} disabled={locked || replaceAll} onClick={() => setSelected(selected.length === preview.rows.length ? [] : preview.rows.map(row => row.row))}>
              {selected.length === preview.rows.length ? '取消全选' : '全选'}</button>
          </div>
          <div className="max-h-[52vh] overflow-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="sticky top-0 bg-slate-50 text-xs text-slate-500"><tr>{['选择', '账号 / 小红书 ID', '负责人', '部门', '变更', '历史 / 注意事项'].map(text => <th key={text} className="px-4 py-3 font-medium">{text}</th>)}</tr></thead>
              <tbody>{preview.rows.map(row => <tr key={row.row} className="border-t border-slate-100 hover:bg-slate-50/60">
                <td className="px-4 py-3"><input type="checkbox" aria-label={`选择 ${row.account_name}`} disabled={locked || replaceAll} checked={selected.includes(row.row)}
                  onChange={e => setSelected(e.target.checked ? [...selected, row.row] : selected.filter(id => id !== row.row))} /></td>
                <td className="px-4 py-3 font-medium">{row.account_name}<div className="mt-1 font-mono text-xs font-normal text-slate-400">{row.xhs_account_id}</div></td>
                <td className="px-4 py-3">{row.owner_name || '待确认'}</td>
                <td className="px-4 py-3">{departments[row.department] || row.department}</td>
                <td className="px-4 py-3">{row.operation === 'create' ? '新增' : '更新'}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{row.history_notes} 篇旧帖{row.confirmed_old_id && <div className="mt-1">已确认 ID 录入更正</div>}
                  {row.warnings.map(w => <div key={w} className="mt-1 text-amber-700">{warnings[w] || w}</div>)}</td>
              </tr>)}</tbody>
            </table>
          </div>
          {(preview.unlisted_accounts || []).length > 0 && <details className="border-t border-amber-100 bg-amber-50/60 px-5 py-4 text-sm">
            <summary className="cursor-pointer font-medium text-amber-900">完整替换时处理 {preview.unlisted_accounts.length} 个表外账号</summary>
            <ul className="mt-3 max-h-40 space-y-2 overflow-auto text-xs text-slate-600">{preview.unlisted_accounts.map(account => <li key={account.id}>
              {account.account_name} · {account.action === 'delete_empty' ? '无历史引用，剔除空账号' : '有历史引用，仅归档保留'}
            </li>)}</ul>
          </details>}
          <div className="space-y-3 border-t border-slate-100 p-5 text-sm">
            <p className="text-xs text-slate-500">跳过 {preview.skipped.length} 行；已选 {selected.length} 行。</p>
            <label className="flex items-start gap-2"><input type="checkbox" aria-label="归属历史帖" checked={history} disabled={locked} onChange={e => setHistory(e.target.checked)} className="mt-1" />
              同时归属预览中列出的历史帖；三处确认录错 ID 使用更正关系，冲突原件不删除。</label>
            <label className="flex items-start gap-2"><input type="checkbox" aria-label="完整替换主名单" checked={replaceAll} disabled={locked}
              onChange={e => { setReplaceAll(e.target.checked); setConfirmed(false); if (e.target.checked) setSelected(preview.rows.map(row => row.row)); }} className="mt-1" />
              以完整飞书表作为唯一主名单：表外无历史账号剔除，有历史账号仅管理员归档，不再参与同步。</label>
            <label className="flex items-start gap-2"><input type="checkbox" aria-label="确认账号归属" checked={confirmed} disabled={locked} onChange={e => setConfirmed(e.target.checked)} className="mt-1" />
              确认所选账号的负责人、部门以本表为准，历史数据仅对当前负责人和对应部门负责人可见。</label>
            <button className={`${button} bg-slate-900 text-white hover:bg-slate-800`} disabled={!confirmed || selected.length === 0 || !!busy}
              onClick={() => void apply()}>{busy === 'apply' ? '正在应用…' : attempt ? '按原选择再次确认' : '确认应用'}</button>
          </div>
        </section>}
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <h2 className="border-b border-slate-100 px-5 py-4 text-sm font-semibold">当前主名单 <span className="ml-2 font-normal text-slate-400">{currentAccounts.length}</span></h2>
          <div className="overflow-auto"><table className="w-full min-w-[600px] text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500"><tr>{['账号', '小红书 ID', '当前负责人', '部门', '状态', '独立主页链接'].map(text => <th key={text} className="px-5 py-3 font-medium">{text}</th>)}</tr></thead>
            <tbody>{currentAccounts.map(account => <tr key={account.id} className="border-t border-slate-100">
              <td className="px-5 py-3">{account.account_name}</td><td className="px-5 py-3 font-mono text-xs">{account.xhs_account_id}</td>
              <td className="px-5 py-3">{account.owner_name || '待确认'}</td><td className="px-5 py-3">{departments[account.department] || account.department}</td>
              <td className="px-5 py-3 text-xs text-slate-500">{statuses[account.status] || account.status}</td>
              <td className="px-5 py-3"><div className="flex gap-2"><input aria-label={`${account.account_name}主页链接`}
                type="url" value={profileEdits[account.id] ?? account.profile_url ?? ''}
                onChange={e=>setProfileEdits(current=>({...current,[account.id]:e.target.value}))}
                placeholder="https://www.xiaohongshu.com/user/profile/…" className="w-64 rounded-lg border border-slate-200 px-2 py-1 text-xs" />
                <button className={button} disabled={!!busy || profileEdits[account.id]===undefined} onClick={()=>void saveProfile(account)}>保存</button></div></td>
            </tr>)}</tbody>
          </table></div>
          {currentAccounts.length === 0 && <p className="p-8 text-center text-sm text-slate-400">尚未导入当前主名单；既有环境和历史数据未改动。</p>}
          {archivedAccounts.length > 0 && <details className="border-t border-slate-100 p-5 text-sm text-slate-500">
            <summary className="cursor-pointer">历史归档 {archivedAccounts.length} 个 · 仅管理员可见</summary>
            <ul className="mt-3 space-y-2">{archivedAccounts.map(account => <li key={account.id}>{account.account_name}</li>)}</ul>
          </details>}
        </section>
      </div>
    </main>
  );
}
