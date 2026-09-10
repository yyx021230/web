'use client';
import { useState } from 'react';
import type { HermesPolicy } from '@/services/hermesWorkflowApi';
import { HermesModal } from './HermesFrame';
import s from './hermes.module.css';

export default function HermesPolicyViewer({ policies, onClose }: { policies: HermesPolicy[]; onClose: () => void }) {
  const [search, setSearch] = useState('');
  return <HermesModal title="全部车型最新政策" description={`共 ${policies.length} 款车型 · 与当前任务是否勾选无关 · 下发时记录政策快照`} onClose={onClose}>
    <input className={s.input} style={{ width: '100%', marginBottom: 18 }} placeholder="搜索车型或政策内容" aria-label="搜索政策" value={search} onChange={e => setSearch(e.target.value)} />
    <div className={s.policyList}>{policies.filter(p => `${p.vehicle_model} ${p.policy_text}`.toLowerCase().includes(search.toLowerCase())).map(p => <article key={p.case_id} className={s.paper}>
      <div className={s.between}><div className={s.row}><h3 style={{ margin: 0 }}>{p.vehicle_model}</h3><span className={s.badge} data-tone={p.allow_multi_config_quote ? 'green' : 'gray'}>{p.allow_multi_config_quote ? '含配置报价信息' : '不支持多配置报价单'}</span></div>{p.policy_source_url && <a href={p.policy_source_url} target="_blank" rel="noreferrer" className={s.textButton}>打开政策原文 ↗</a>}</div>
      <p className={s.small} style={{ margin: '10px 0' }}>{p.policy_source_title || p.policy_source} · 对外期限：{p.public_deadline || p.policy_deadline || '未填写'}</p>
      {!!p.quote_rows?.length && <div className={s.tableWrap}><table className={s.table}><thead><tr><th>配置</th><th>指导价</th><th>国补后价格</th><th>省补后价格</th></tr></thead><tbody>{p.quote_rows.map((r, i) => <tr key={i}><td>{r.configuration}</td><td>{r.official_guide_price}</td><td>{r.national_scrappage_after_price}</td><td>{r.provincial_trade_in_after_price}</td></tr>)}</tbody></table></div>}
      <details style={{ marginTop: 16 }}><summary style={{ cursor: 'pointer' }}>完整政策内容</summary><div className={s.copy} style={{ marginTop: 12 }}>{p.policy_text || '未记录完整政策'}</div></details>
    </article>)}</div>{!policies.length && <div className={s.empty}>未读取到政策，请刷新检查配置。</div>}
  </HermesModal>;
}
