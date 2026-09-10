import fs from 'node:fs/promises';
import path from 'node:path';

const API_BASE = 'https://car-support.leapmotor.cn';
const COLLECTED_AT = '2026-08-19';
const outputDir = process.argv[2] || path.resolve('dify/knowledge/leapmotor-official-20260819');

const families = [
  { name: 'A10', ids: [20], page: 'https://cn.leapmotor.com/A10.html' },
  { name: 'B01', ids: [15], page: 'https://cn.leapmotor.com/B01-selling.html' },
  { name: 'B10', ids: [14], page: 'https://cn.leapmotor.com/B10-intelligent.html' },
  { name: 'C10', ids: [10, 11], page: 'https://cn.leapmotor.com/C10-26.html' },
  { name: 'C11', ids: [3, 1], page: 'https://cn.leapmotor.com/C11-aggregation.html' },
  { name: 'C16', ids: [12, 13], page: 'https://cn.leapmotor.com/C16-polymerization.html' },
  { name: 'D19', ids: [17, 22], page: 'https://cn.leapmotor.com/D19.html' },
  { name: 'D99', ids: [21, 23], page: 'https://cn.leapmotor.com/D99.html' },
  { name: 'Lafa5', ids: [18], page: 'https://cn.leapmotor.com/Lafa5.html' },
  { name: 'Lafa5 Ultra', ids: [19], page: 'https://cn.leapmotor.com/Lafa5.html' },
];

const keyParams = [
  '长', '宽', '高(mm)', '轴距(mm)', '车身结构',
  'CLTC综合工况纯电续航里程(km)', 'CLTC综合工况续航里程(km)',
  'WLTC综合工况纯电续航里程(km)', 'WLTC综合工况续航里程(km)',
  'WLTC馈电油耗(L/100km)', 'CLTC最低荷电状态油耗(L/100km)',
  '最高车速(km/h)', '0-100km/h加速(s)', '行李箱容积(L)', '后备箱容积(L)',
  '整备质量(kg)', '电机总功率(kW)', '电机总扭矩(N•m)', '电机布局',
  '驱动方式', '电池类型', '电池能量(kWh)', '油箱容积(L)', '电压平台',
  '全域800V高压碳化硅快充平台', '直流快充充电(30%-80%)',
  '前悬架类型', '后悬架类型', '轮胎规格', '前轮胎规格', '后轮胎规格',
  '座位数', '整车质保', '电池组质保',
];

const headers = {
  Origin: 'https://cn.leapmotor.com',
  Referer: 'https://cn.leapmotor.com/',
  'Content-Type': 'application/json',
  'User-Agent': 'Mozilla/5.0 (compatible; product-knowledge-sync/1.0)',
};

async function api(endpoint, body) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: body ? 'POST' : 'GET',
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${endpoint}: HTTP ${response.status}`);
  const json = await response.json();
  if (!json.success) throw new Error(`${endpoint}: ${json.msg || 'unknown error'}`);
  return json;
}

function parseValue(raw) {
  if (!raw) return '';
  let values;
  try { values = JSON.parse(raw); } catch { return String(raw); }
  if (!Array.isArray(values)) return String(raw);
  return values.map((item) => {
    const text = String(item?.text ?? '').trim();
    if (item?.type === '1') return text ? `标配（${text}）` : '标配';
    if (item?.type === '2') return text ? `选配（${text}）` : '选配';
    if (item?.type === '3') return text ? `无（${text}）` : '无';
    return text;
  }).filter(Boolean).join('；');
}

function cell(value) {
  return String(value || '—').replaceAll('|', '\\|').replaceAll('\n', '<br>');
}

function safeName(name) {
  return name.replaceAll(' ', '_').replaceAll('/', '_');
}

function versionLabel(version) {
  const energy = version.typeName.includes('增程') ? '增程' : '纯电';
  return `${energy}·${version.name}`;
}

function buildMatrix(versions, paramsByVersion, onlyKeys = false) {
  const rows = new Map();
  for (const version of versions) {
    for (const param of paramsByVersion.get(version.id) || []) {
      if (param.pinvocation !== 0) continue;
      if (onlyKeys && !keyParams.includes(param.pname)) continue;
      const value = parseValue(param.paramStyleValue);
      if (!value || value === '无') continue;
      const rowKey = `${param.glevel}|${param.gname}|${param.plevel}|${param.pname}`;
      if (!rows.has(rowKey)) rows.set(rowKey, {
        group: param.gname,
        groupLevel: param.glevel,
        param: param.pname,
        paramLevel: param.plevel,
        values: new Map(),
      });
      rows.get(rowKey).values.set(version.id, value);
    }
  }

  const grouped = new Map();
  for (const row of rows.values()) {
    if (!grouped.has(row.group)) grouped.set(row.group, []);
    grouped.get(row.group).push(row);
  }

  const groups = [...grouped.entries()].sort((a, b) =>
    (b[1][0]?.groupLevel || 0) - (a[1][0]?.groupLevel || 0));
  const lines = [];
  for (const [group, groupRows] of groups) {
    lines.push(`### ${group}`, '');
    lines.push(`| 参数 | ${versions.map(versionLabel).map(cell).join(' | ')} |`);
    lines.push(`|---|${versions.map(() => '---').join('|')}|`);
    for (const row of groupRows.sort((a, b) => a.paramLevel - b.paramLevel)) {
      lines.push(`| ${cell(row.param)} | ${versions.map(v => cell(row.values.get(v.id))).join(' | ')} |`);
    }
    lines.push('');
  }
  return lines.join('\n');
}

async function main() {
  await fs.mkdir(outputDir, { recursive: true });
  const payloadDir = path.join(outputDir, '_dify_payloads');
  await fs.mkdir(payloadDir, { recursive: true });
  const allTypesResponse = await api('/queryAllCarType');
  const allTypes = allTypesResponse.data || [];
  const normalizedTypes = allTypes.map(item => ({
    ...item,
    year: item.year || item.yearList?.[0]?.year || '',
  }));
  const typeById = new Map(normalizedTypes.map(item => [item.id, item]));
  const manifest = {
    collectedAt: COLLECTED_AT,
    apiTime: allTypesResponse.time,
    source: `${API_BASE}/queryAllCarType`,
    families: [],
  };

  for (const family of families) {
    const types = family.ids.map(id => typeById.get(id)).filter(Boolean);
    const versions = [];
    const paramsByVersion = new Map();

    for (const type of types) {
      const versionResponse = await api('/queryVersionsByCarTypeAndYear', {
        tid: [type.id],
        year: String(type.year),
      });
      const typeVersions = (versionResponse.data || []).flatMap(item => item.versions || [])
        .map(version => ({ ...version, typeName: type.name, typeSmallName: type.smallName, year: type.year }));
      versions.push(...typeVersions);
      if (typeVersions.length) {
        const paramsResponse = await api('/queryCarVersionParams', { vid: typeVersions.map(v => v.id) });
        for (const item of paramsResponse.data || []) paramsByVersion.set(item.versionId, item.params || []);
      }
    }

    const sourceLinks = types.map(type =>
      `- 官网参数页（${type.name}）：https://cn.leapmotor.com/parameter-pk-web.html?carTypeId=${type.id}&platform=web`);
    const title = `零跑${family.name}官网产品知识补充（${COLLECTED_AT}）`;
    const lines = [
      `# ${title}`,
      '',
      '## 使用规则',
      '',
      `- 采集日期：${COLLECTED_AT}（北京时间）。`,
      '- 本文只补充车型、版本与产品配置事实；营销金融政策、区域权益、限时优惠以用户当次提供的政策表为唯一依据。',
      '- “标配、选配、无”均按零跑官网参数页图例解释；不能把高配或选装配置写成全系标配。',
      '- 车型年款和具体版本必须绑定使用，禁止跨版本拼接参数。',
      '- 官网价格属于易变信息，仅记录采集时页面展示，不可替代当次政策输入。',
      '',
      '## 官方来源',
      '',
      `- 官网车型页：${family.page}`,
      ...sourceLinks,
      `- 官网公开参数数据服务：${API_BASE}`,
      '',
      '## 当前年款与版本',
      '',
    ];

    if (!versions.length) {
      lines.push('- 官网参数接口在采集时尚未返回可用版本；保留车型入口，等待后续更新。', '');
    } else {
      for (const version of versions) {
        const price = version.afterPrice || version.limitTimePrice || '官网未展示';
        lines.push(`- ${version.typeName}｜${version.year}款｜${version.name}｜采集时页面价格：${price}`);
      }
      lines.push('', '## 关键参数快览', '', buildMatrix(versions, paramsByVersion, true));
      lines.push('## 官网完整配置矩阵', '', buildMatrix(versions, paramsByVersion, false));
    }

    lines.push('## 检索锚点', '');
    for (const type of types) {
      lines.push(`- 车型：${type.name}；简称：${type.smallName}；年款：${type.year}；车型ID：${type.id}`);
    }
    lines.push(`- 关键词：零跑 ${family.name} ${versions.map(v => v.name).join(' ')}`, '');

    const file = `${safeName(family.name)}_官网产品知识补充_${COLLECTED_AT.replaceAll('-', '')}.md`;
    const documentText = lines.join('\n');
    await fs.writeFile(path.join(outputDir, file), documentText, 'utf8');
    await fs.writeFile(path.join(payloadDir, `${safeName(family.name)}.json`), JSON.stringify({
      name: file,
      text: documentText,
      indexing_technique: 'high_quality',
      process_rule: { mode: 'automatic' },
    }), 'utf8');
    manifest.families.push({
      family: family.name,
      file,
      typeIds: types.map(t => t.id),
      versions: versions.map(v => ({ id: v.id, name: v.name, typeName: v.typeName, year: v.year })),
    });
    process.stdout.write(`${family.name}: ${versions.length} versions -> ${file}\n`);
  }

  const catalogName = `零跑当前在售车型版本权威索引_${COLLECTED_AT.replaceAll('-', '')}.md`;
  const catalogLines = [
    `# 零跑当前在售车型版本权威索引（${COLLECTED_AT}）`,
    '',
    `采集日期：${COLLECTED_AT}。数据来自零跑官网当前车型参数接口。`,
    '',
    '检索优先级规则：当旧知识文档与本索引发生年款、版本名称冲突时，当前在售年款与版本判定以本索引为准；具体配置再查对应的“官网产品知识补充”文档；营销政策始终以用户当次政策表为准。',
    '',
  ];
  for (const item of manifest.families) {
    const years = [...new Set(item.versions.map(v => v.year))].join('、');
    const versionText = item.versions.map(v => `${v.typeName} ${v.name}`).join('；');
    catalogLines.push(
      `## 零跑${item.family} 当前在售版本`,
      '',
      `- 当前年款：${years || '官网待公布'}`,
      `- 当前版本：${versionText || '官网参数接口暂未返回版本'}`,
      `- 详细配置文档：${item.file}`,
      `- 检索词：零跑${item.family} 最新 当前 在售 官网 ${years}款 ${item.versions.map(v => v.name).join(' ')}`,
      '',
    );
  }
  const catalogText = catalogLines.join('\n');
  await fs.writeFile(path.join(outputDir, catalogName), catalogText, 'utf8');
  await fs.writeFile(path.join(payloadDir, '00_current_catalog.json'), JSON.stringify({
    name: catalogName,
    text: catalogText,
    indexing_technique: 'high_quality',
    process_rule: { mode: 'automatic' },
  }), 'utf8');

  await fs.writeFile(path.join(outputDir, 'manifest.json'), JSON.stringify(manifest, null, 2), 'utf8');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
