'use client';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowUpRight, CarFront, ChevronDown, ChevronUp, FileText, History, Loader2, SlidersHorizontal, Sparkles, UsersRound } from 'lucide-react';
import { toast } from '@/lib/toast';
import { hermesWorkflowApi, type HermesAccount, type HermesPolicy, type HermesReferenceCatalog } from '@/services/hermesWorkflowApi';
import HermesCreationHistory from './HermesCreationHistory';
import { HermesFrame } from './HermesFrame';
import HermesPolicyViewer from './HermesPolicyViewer';
import HermesTypePicker, { HermesTypeChoice } from './HermesTypePicker';
import s from './hermes.module.css';

export default function HermesCreator({ single = false }: { single?: boolean }) {
  const [accounts, setAccounts] = useState<HermesAccount[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [policies, setPolicies] = useState<HermesPolicy[]>([]);
  const [counts, setCounts] = useState<Record<number, number>>({});
  const [defaultCount, setDefaultCount] = useState(5);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [copyType, setCopyType] = useState('');
  const [imageType, setImageType] = useState('');
  const [catalog, setCatalog] = useState<HermesReferenceCatalog | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const [picker, setPicker] = useState<'copy' | 'image' | null>(null);
  const [instruction, setInstruction] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const lock = useRef(false);
  const composer = useRef<HTMLFormElement>(null);
  async function bootstrap() {
    setLoading(true); setError('');
    try { const r = await hermesWorkflowApi.bootstrap(); setAccounts(r.data.accounts); setModels(r.data.vehicle_models); setPolicies(r.data.policies); setError(''); }
    catch (e) { setError(e instanceof Error ? e.message : '无法加载账号与政策'); }
    finally { setLoading(false); }
  }
  useEffect(() => { void bootstrap(); }, []);
  useEffect(() => { if (new URLSearchParams(window.location.search).has('run') || window.location.hash === '#history') setCollapsed(true); }, []);
  async function loadCatalog() {
    setCatalogError('');
    try { setCatalog((await hermesWorkflowApi.referenceTypes()).data); }
    catch (e) { setCatalogError(e instanceof Error ? e.message : '类型案例加载失败'); }
  }
  useEffect(() => { if (single) void loadCatalog(); }, [single]);
  useEffect(() => {
    function outside(event: Event) { composer.current?.querySelectorAll('details[open]').forEach(node => { if (!node.contains(event.target as Node)) node.removeAttribute('open'); }); }
    document.addEventListener('pointerdown', outside); document.addEventListener('click', outside);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('click', outside); };
  }, []);
  const total = Object.values(counts).reduce((n, v) => n + v, 0);
  const selectedCounts = Object.values(counts);
  const uniformCount = selectedCounts.length ? (selectedCounts.every(n => n === selectedCounts[0]) ? String(selectedCounts[0]) : 'custom') : String(defaultCount);
  function setUniformCount(count: number) {
    setDefaultCount(count);
    setCounts(old => Object.fromEntries(Object.keys(old).map(id => [id, count])));
  }
  const quoteAllowed = policies.some(p => p.vehicle_model === selectedModels[0] && p.allow_multi_config_quote && p.quote_rows?.length);
  const imageQuoteBlocked = (catalog?.image_types.find(t => t.id === imageType)?.requires_quote_data || ['quote_table', 'quote_cards'].includes(imageType)) && !quoteAllowed;
  const selectedImageType = catalog?.image_types.find(t => t.id === imageType);
  const imagePoolEmpty = (quoteAllowed ? selectedImageType?.production_reference_count : selectedImageType?.production_without_quote_count) === 0;
  function toggleAccount(id: number) {
    setCounts(old => { const next = { ...old }; if (next[id]) delete next[id]; else { if (Object.keys(next).length >= 8) { toast.error('最多选择8个账号'); return old; } next[id] = uniformCount === 'custom' ? defaultCount : Number(uniformCount); } return next; });
  }
  function toggleModel(model: string) { setSelectedModels(old => old.includes(model) ? old.filter(m => m !== model) : old.length < 12 ? [...old, model] : old); }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (lock.current) return;
    if (!total || !selectedModels.length) return toast.error('请选择账号、篇数与车型');
    if (single && (!copyType || !imageType)) return toast.error('请分别选择文案方向与图片版式');
    if (single && imageQuoteBlocked) return toast.error('该车型没有完整配置报价信息');
    if (single && imagePoolEmpty) return toast.error('当前车型资料条件下，该版式暂无可生产母版，请更换版式');
    lock.current = true; setSubmitting(true);
    try {
      const payload = { instruction: instruction.trim() || undefined };
      const response = single ? await hermesWorkflowApi.createRun({ ...payload, account_id: Number(Object.keys(counts)[0]), vehicle_model: selectedModels[0], post_count: 1, copy_type: copyType, image_type: imageType }) : await hermesWorkflowApi.createBatchRun({ ...payload, accounts: Object.entries(counts).map(([id, post_count]) => ({ environment_id: Number(id), post_count })), vehicle_models: selectedModels });
      toast.success(`任务 #${response.data.id} 已入队，共 ${total} 篇`);
      setRefreshKey(k => k + 1); setCollapsed(true); setInstruction('');
      composer.current?.querySelectorAll('details[open]').forEach(node => node.removeAttribute('open'));
    } catch (e) { toast.error(e instanceof Error ? e.message : '下发失败；请先刷新历史确认是否已入队，避免重复下发'); }
    finally { lock.current = false; setSubmitting(false); }
  }
  return <HermesFrame title={single ? '精准单篇' : '批量创作'} active={single ? 'single' : 'batch'}>
    <form ref={composer} onSubmit={submit} className={s.composer} data-collapsed={collapsed} aria-label={single ? '单篇创作参数' : '批量创作参数'}>
      <div className={s.between}><div className={s.composerTop}><span className={s.composerIcon}>{single ? <FileText size={16} /> : <UsersRound size={16} />}</span><strong>新建创作</strong>{collapsed && total > 0 && <span className={s.muted}>{Object.keys(counts).length} 个账号 · {total} 篇</span>}</div><div className={s.row}><button type="button" className={s.textButton} onClick={() => setPolicyOpen(true)} aria-label="查看全部最新政策"><FileText size={13} />最新政策<ArrowUpRight size={12} /></button><button type="button" className={s.iconButton} onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? '展开创作参数' : '收起创作参数'} title={collapsed ? '展开创作参数' : '收起创作参数'} aria-expanded={!collapsed}>{collapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}</button></div></div>
      {!collapsed && <>
        {loading && <p className={s.notice}><Loader2 className="animate-spin" size={14} />读取已分配账号、车型与政策…</p>}
        {error && <div className={`${s.notice} ${s.error}`} role="alert">{error}<button className={s.textButton} type="button" onClick={bootstrap}>重试</button></div>}
        {!loading && !error && !accounts.length && <p className={s.notice}>你还没有分配负责账号，请管理员在账号管理中分配后再下发任务。历史内容仍可查看。</p>}
        <div className={s.composerInputs} data-mode={single ? 'single' : 'batch'}><div className={s.composerFields} data-mode={single ? 'single' : 'batch'}>
          <div className={s.field}><span className={s.fieldLabel}>创作账号</span>
          {single ? <select className={s.input} aria-label="创作账号" disabled={loading || !!error} value={Object.keys(counts)[0] || ''} onChange={e => setCounts(e.target.value ? { [Number(e.target.value)]: 1 } : {})}><option value="">选择负责账号</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select> : <>
            <details className={s.dropdown}><summary className={s.button}><UsersRound size={15} /><span>{selectedCounts.length ? `已选 ${selectedCounts.length} 个账号` : '选择负责账号'}</span><ChevronDown size={13} /></summary>
              <div className={s.menu}>
                <p className={s.small} style={{ padding: '4px 8px 8px' }}>最多 8 个账号 · 篇数可分别设置</p>
                {accounts.map(a => <div className={s.option} key={a.id}>
                  <label className={s.accountChoice}><input aria-label={`选择${a.name}`} type="checkbox" checked={!!counts[a.id]} onChange={() => toggleAccount(a.id)} /><span>{a.name}</span></label>
                  <select aria-label={`${a.name}篇数`} disabled={!counts[a.id]} value={counts[a.id] || defaultCount} onChange={e => setCounts(old => ({ ...old, [a.id]: Number(e.target.value) }))}>{[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}篇</option>)}</select>
                </div>)}
              </div>
            </details>
          </>}</div>
          {!single && <label className={s.field}><span className={s.fieldLabel}>每账号篇数</span><select className={s.input} aria-label="每个账号生产篇数" title="统一设置所有已选账号的篇数；也可在账号下拉中分别调整" value={uniformCount} onChange={e => setUniformCount(Number(e.target.value))}>
              {uniformCount === 'custom' && <option value="custom" disabled>分别设置</option>}{[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n} 篇</option>)}
            </select></label>}
          <div className={s.field}><span className={s.fieldLabel}>生产车型{!single && <small>可多选</small>}</span>
          {single ? <select aria-label="生产车型" className={s.input} disabled={loading || !!error} value={selectedModels[0] || ''} onChange={e => setSelectedModels(e.target.value ? [e.target.value] : [])}><option value="">选择车型</option>{models.map(m => <option key={m}>{m}</option>)}</select> : <details className={s.dropdown}><summary className={s.button}><CarFront size={15} /><span>{selectedModels.length ? selectedModels.length === 1 ? selectedModels[0] : `已选 ${selectedModels.length} 款车型` : '选择生产车型'}</span><ChevronDown size={13} /></summary><div className={s.menu}><p className={s.small} style={{ padding: '4px 8px' }}>所选车型按篇轮换 · 最多 12 款</p>{models.map(m => <label className={s.option} key={m}><input type="checkbox" checked={selectedModels.includes(m)} onChange={() => toggleModel(m)} /><span>{m}</span><small className={s.small}>{policies.some(p => p.vehicle_model === m) ? '含政策' : '车型库'}</small></label>)}</div></details>}</div>
          <button type="button" className={s.preferenceButton} onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}><SlidersHorizontal size={14} />创作偏好<small>可选</small></button>
        </div>
        {single && (catalog ? <div className={s.typePair}><HermesTypeChoice kind="copy" type={catalog.copy_types.find(t => t.id === copyType)} onClick={() => setPicker('copy')} /><HermesTypeChoice kind="image" type={catalog.image_types.find(t => t.id === imageType)} onClick={() => setPicker('image')} /></div> : <div className={s.notice}>{catalogError || '正在加载文案方向、图片版式与真实案例…'}{catalogError && <button type="button" className={s.textButton} onClick={loadCatalog}>重试案例</button>}</div>)}
        </div>
        {single && imageQuoteBlocked && <p className={`${s.notice} ${s.error}`}>当前车型未提供完整的分配置报价，请更换版式或选择资料完整的车型。</p>}
        {!single && selectedCounts.length > 0 && <div className={s.accountPlan} aria-label="各账号生产篇数预览">{accounts.filter(a => counts[a.id]).map(a => <span key={a.id} className={s.accountChip}>{a.name}<b>{counts[a.id]} 篇</b></span>)}</div>}
        {advanced && <div className={s.preference}>
          <label className={s.label}>创作偏好（可选）<textarea className={s.input} aria-describedby="hermes-preference-help" rows={2} maxLength={1000} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="例如：在母文已有内容内侧重通勤；图片光线稍偏傍晚" /></label>
          <p id="hermes-preference-help" className={s.muted}>偏好仅供参考，不改变母文结构与事实依据；车型、篇数和类型以上方选项为准。</p>
        </div>}
        <div className={s.composerBottom}><div className={s.accountMemoryHint} title="参考所选账号最近 15 条已同步内容，避开高度重复；保留母文结构。"><History size={14} /><span>近 15 篇去重参考</span></div><div className={s.submitGroup}>{!single && <span className={s.small}>{selectedCounts.length} 个账号 · <b>{total}</b> 篇</span>}<button className={s.primary} disabled={submitting || loading || !!error || !total || !selectedModels.length || (single && (!catalog || !copyType || !imageType || imageQuoteBlocked))}>{submitting ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}下发 {total || (single ? 1 : 0)} 篇任务</button></div></div>
      </>}
    </form>
    <HermesCreationHistory key={single ? 'single' : 'batch'} mode={single ? 'single' : 'batch'} refreshKey={refreshKey} accounts={accounts} />
    {policyOpen && <HermesPolicyViewer policies={policies} onClose={() => setPolicyOpen(false)} />}
    {picker && catalog && <HermesTypePicker key={picker} kind={picker} catalog={catalog} value={picker === 'copy' ? copyType : imageType} quoteAllowed={quoteAllowed} onClose={() => setPicker(null)} onSelect={type => { if (picker === 'copy') setCopyType(type.id); else setImageType(type.id); setPicker(null); }} />}
  </HermesFrame>;
}
