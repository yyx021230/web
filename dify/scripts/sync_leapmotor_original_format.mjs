import fs from 'node:fs/promises';
import path from 'node:path';

const API_BASE = 'https://car-support.leapmotor.cn';
const COLLECTED_AT = '2026-08-19';
const ORIGINAL_FILE = '/Users/yyx/ztqc/milvus_car/kb_output/零跑汽车/零跑汽车.md';
const OUTPUT_DIR = path.resolve('dify/knowledge/leapmotor-original-format-20260819');
const OUTPUT_FILE = path.join(OUTPUT_DIR, '零跑汽车.md');

const families = [
  { ids: [20] }, { ids: [15] }, { ids: [14] }, { ids: [10, 11] },
  { ids: [3, 1] }, { ids: [12, 13] }, { ids: [17, 22] },
  { ids: [21, 23] }, { ids: [18] }, { ids: [19] },
];

const headers = {
  Origin: 'https://cn.leapmotor.com',
  Referer: 'https://cn.leapmotor.com/',
  'Content-Type': 'application/json',
  'User-Agent': 'Mozilla/5.0 (compatible; product-knowledge-sync/2.0)',
};

async function api(endpoint, body) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: body ? 'POST' : 'GET', headers,
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
  try { values = JSON.parse(raw); } catch { return String(raw).trim(); }
  if (!Array.isArray(values)) return String(raw).trim();
  return values.map((item) => {
    const text = String(item?.text ?? '').trim();
    if (item?.type === '1') return text ? `标配（${text}）` : '标配';
    if (item?.type === '2') return text ? `选配（${text}）` : '选配';
    if (item?.type === '3') return '';
    return text;
  }).filter(Boolean).join('；');
}

function cleanLine(value) {
  return String(value || '').replaceAll('\r', '').replaceAll('\n', '；').trim();
}

function parseHistorical(text) {
  const groups = new Map();
  const blocks = text.replaceAll('\r\n', '\n').split(/\n(?:---|====)\n/);
  for (const raw of blocks) {
    const block = raw.trim();
    const match = block.match(/^品牌:\s*零跑汽车\s*\|\s*车型:\s*([^|\n]+)\s*\|\s*版本:\s*(.+)$/m);
    if (!match) continue;
    const model = match[1].trim();
    if (!groups.has(model)) groups.set(model, []);
    groups.get(model).push(block);
  }
  return groups;
}

function officialBlock(type, version, params, allVersions) {
  const versionName = `${version.year}款 ${cleanLine(version.name)}`;
  const shortName = cleanLine(type.smallName || type.name.replace(/^零跑/, ''));
  const lines = [
    `品牌: 零跑汽车 | 车型: ${cleanLine(type.name)} | 版本: ${versionName}`,
    '基本信息',
    `- 车款名称: ${versionName}`,
    '- 厂商: 零跑汽车',
    `- 车型全称: ${cleanLine(type.name)}`,
    `- 车型简称: ${shortName}`,
    `- 当前年款: ${version.year}款`,
    `- 当前在售版本总览: ${allVersions.map((item) => cleanLine(item.name)).join('；')}`,
    '- 产品参数范围: 续航、电池、动力、尺寸、快充、底盘、智驾、标配、选配',
    `- 能源类型: ${type.name.includes('增程') ? '增程式' : '纯电'}`,
    '- 数据状态: 当前在售',
    `- 数据来源: 零跑官网参数接口（采集日期 ${COLLECTED_AT}）`,
  ];
  const grouped = new Map();
  for (const param of params || []) {
    if (param.pinvocation !== 0) continue;
    const value = parseValue(param.paramStyleValue);
    if (!value) continue;
    const group = cleanLine(param.gname) || '其他配置';
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group).push({
      name: cleanLine(param.pname), value: cleanLine(value),
      groupLevel: Number(param.glevel || 0), paramLevel: Number(param.plevel || 0),
    });
  }
  const groupEntries = [...grouped.entries()].sort((a, b) =>
    (b[1][0]?.groupLevel || 0) - (a[1][0]?.groupLevel || 0));
  for (const [group, rows] of groupEntries) {
    const section = group === '基本参数' ? '官网基本参数' : group;
    lines.push(section);
    for (const row of rows.sort((a, b) => a.paramLevel - b.paramLevel)) {
      lines.push(`- ${row.name}: ${row.value}`);
    }
  }
  return lines.join('\n');
}

async function collectOfficial() {
  const allTypesResponse = await api('/queryAllCarType');
  const types = (allTypesResponse.data || []).map((item) => ({
    ...item, year: item.year || item.yearList?.[0]?.year || '',
  }));
  const typeById = new Map(types.map((item) => [item.id, item]));
  const groups = new Map();
  const manifest = [];
  for (const family of families) {
    for (const typeId of family.ids) {
      const type = typeById.get(typeId);
      if (!type) continue;
      const versionResponse = await api('/queryVersionsByCarTypeAndYear', {
        tid: [type.id], year: String(type.year),
      });
      const versions = (versionResponse.data || []).flatMap((item) => item.versions || [])
        .map((version) => ({ ...version, year: type.year }));
      const paramsByVersion = new Map();
      if (versions.length) {
        const paramsResponse = await api('/queryCarVersionParams', { vid: versions.map((v) => v.id) });
        for (const item of paramsResponse.data || []) paramsByVersion.set(item.versionId, item.params || []);
      }
      groups.set(type.name, versions.map((version) =>
        officialBlock(type, version, paramsByVersion.get(version.id) || [], versions)));
      manifest.push({ model: type.name, year: type.year, versions: versions.map((v) => v.name) });
    }
  }
  return { groups, manifest };
}

async function main() {
  const historicalText = await fs.readFile(ORIGINAL_FILE, 'utf8');
  const historical = parseHistorical(historicalText);
  const { groups: current, manifest } = await collectOfficial();
  const preferredOrder = [
    '零跑A05', '零跑A10', '零跑B01', '零跑B10',
    '零跑C10', '零跑C10增程', '零跑C11', '零跑C11增程',
    '零跑C16', '零跑C16增程', '零跑D19', '零跑D19增程',
    '零跑D99', '零跑D99增程', '零跑Lafa5', '零跑Lafa5 Ultra', '零跑T03',
  ];
  const allModels = new Set(current.keys());
  const modelOrder = [
    ...preferredOrder.filter((model) => allModels.has(model)),
    ...[...allModels].filter((model) => !preferredOrder.includes(model)).sort(),
  ];
  const sections = [];
  for (const model of modelOrder) {
    const blocks = [...(current.get(model) || [])];
    if (blocks.length) sections.push(blocks.join('\n---\n'));
  }
  const result = sections.join('\n====\n');
  await fs.mkdir(OUTPUT_DIR, { recursive: true });
  await fs.writeFile(OUTPUT_FILE, result, 'utf8');
  await fs.writeFile(path.join(OUTPUT_DIR, 'dify_payload.json'), JSON.stringify({
    name: `零跑汽车_官网当前在售_${COLLECTED_AT.replaceAll('-', '')}_v2.md`,
    text: result,
    indexing_technique: 'high_quality',
    process_rule: {
      mode: 'custom',
      rules: {
        pre_processing_rules: [
          { id: 'remove_extra_spaces', enabled: true },
          { id: 'remove_urls_emails', enabled: false },
        ],
        segmentation: { separator: '---', max_tokens: 4000, chunk_overlap: 50 },
        parent_mode: null,
        subchunk_segmentation: null,
      },
    },
  }), 'utf8');
  const lines = result.split('\n');
  const headersFound = lines.filter((line) => line.startsWith('品牌:'));
  const summary = {
    collectedAt: COLLECTED_AT,
    source: API_BASE,
    document: OUTPUT_FILE,
    models: modelOrder,
    currentVersions: [...current.values()].reduce((total, rows) => total + rows.length, 0),
    archivedHistoricalVersions: [...historical.values()].reduce((total, rows) => total + rows.length, 0),
    totalVersions: headersFound.length,
    variantSeparators: lines.filter((line) => line === '---').length,
    modelSeparators: lines.filter((line) => line === '====').length,
    blankLines: lines.filter((line) => line === '').length,
    bytes: Buffer.byteLength(result),
    manifest,
  };
  await fs.writeFile(path.join(OUTPUT_DIR, 'manifest.json'), JSON.stringify(summary, null, 2), 'utf8');
  console.log(JSON.stringify(summary, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
