export type CarCatalogEntry = {
  brand: string;
  model: string;
  brandKeys: string[];
  modelKeys: string[];
};

export type VehicleMatchConfidence = 'model_exact' | 'model_alias' | 'brand_model' | 'brand' | 'none';

export type VehicleMatchResult = {
  brand: string;
  model: string;
  confidence: VehicleMatchConfidence;
  score: number;
  reason: string;
};

export type VehicleCatalogIndex = {
  modelItems: Array<{ key: string; entry: CarCatalogEntry; exactModel: boolean; shortModel: boolean }>;
  brandItems: Array<{ key: string; brand: string }>;
  modelByKey: Map<string, Array<{ key: string; entry: CarCatalogEntry; exactModel: boolean; shortModel: boolean }>>;
  brandByKey: Map<string, Array<{ key: string; brand: string }>>;
  keyLengths: number[];
};

type MatchableNote = {
  title?: string | null;
  content?: string | null;
};

type TextSections = {
  title: string;
  topics: string;
  lead: string;
  full: string;
};

const GENERIC_VEHICLE_TERMS = new Set([
  '汽车',
  '新能源',
  '车',
  'suv',
  'mpv',
  '轿车',
  '买车',
  '车型',
  '政策',
  '新政',
  '电车',
  '油车',
  '燃油车',
  '混动车',
  '插混',
  '纯电',
  '智能',
  '智驾',
]);

const AMBIGUOUS_BRAND_ALIASES = new Set([
  '北京',
  '上海',
  '广州',
  '长城',
  '大运',
  '远程',
  '创维',
  '哪吒',
  '极越',
]);

const BUSINESS_MODEL_ALIASES: Record<string, string[]> = {
  '比亚迪/汉': ['比亚迪汉', '汉ev', '汉dm', '汉dmi', '汉dm-i'],
  '比亚迪/汉L': ['比亚迪汉l', '汉l'],
  '比亚迪/唐': ['比亚迪唐', '唐dm', '唐dmi', '唐dm-i'],
  '比亚迪/大唐': ['比亚迪大唐', '大唐'],
  '比亚迪/宋Pro': ['宋pro'],
  '比亚迪/宋PLUS': ['宋plus'],
  '比亚迪/元UP': ['元up'],
  '比亚迪/海豹06GT': ['海豹06gt'],
  '比亚迪/海狮05EV': ['海狮05ev'],
  '比亚迪/海狮06': ['海狮06'],
  '比亚迪/海狮07EV': ['海狮07ev', '海狮07'],
  '小鹏/小鹏MONA M03': ['小鹏m03', 'monam03', 'mona m03', 'm03'],
  '小鹏/小鹏P7': ['小鹏p7'],
  '小鹏/小鹏G6': ['小鹏g6'],
  '零跑汽车/零跑A10': ['零跑a10', 'a10'],
  '零跑汽车/零跑B01': ['零跑b01', 'b01'],
  '零跑汽车/零跑D19': ['零跑d19', 'd19'],
  '零跑汽车/零跑C10': ['零跑c10', 'c10'],
  '零跑汽车/零跑C11': ['零跑c11', 'c11'],
  '岚图汽车/岚图知音': ['岚图知音', '知音'],
  '岚图汽车/岚图梦想家': ['岚图梦想家', '梦想家'],
  '岚图汽车/岚图泰山X8': ['岚图泰山x8', '泰山x8'],
  '岚图汽车/岚图泰山': ['岚图泰山', '泰山'],
  '岚图汽车/岚图追光L': ['岚图追光l', '追光l'],
  '岚图汽车/岚图追光': ['岚图追光', '追光'],
  '哈弗/哈弗猛龙PHEV': ['哈弗猛龙', '猛龙'],
  '哈弗/哈弗猛龙燃油版': ['猛龙燃油版'],
  '哈弗/哈弗枭龙MAX PHEV': ['哈弗枭龙max', '枭龙max'],
  '领克/领克08 EM-P': ['领克08', '08emp'],
  '领克/领克Z10': ['领克z10', 'z10'],
  '领克/领克02 Hatchback': ['领克02', '领克02hatchback'],
  '奥迪/奥迪A4L': ['奥迪a4l', 'a4l'],
  '奥迪/奥迪A3L': ['奥迪a3l', 'a3l'],
  '奥迪AUDI/奥迪E7X': ['奥迪e7', '奥迪e7x', 'e7x'],
  '奔驰/奔驰C级': ['奔驰c', '奔驰c级'],
  '奔驰/奔驰E级': ['奔驰e', '奔驰e级'],
  '长安/长安CS95': ['长安cs95', 'cs95'],
  '极氪/极氪001': ['极氪001', '001'],
  '极氪/极氪007': ['极氪007', '007'],
  '极氪/极氪009': ['极氪009', '009'],
  '极氪/极氪8X': ['极氪8x', '8x'],
  '吉利银河/银河A7 EM': ['吉利银河a7', '银河a7', 'a7'],
  '吉利汽车/星越L': ['吉利星越l', '星越l'],
  '吉利汽车/博越L': ['吉利博越l', '博越l'],
};

const SUPPLEMENTAL_CATALOG_ROWS: Array<{ brand: string; model: string; aliases?: string[] }> = [
  { brand: '极氪', model: '极氪001', aliases: ['001'] },
  { brand: '极氪', model: '极氪007', aliases: ['007'] },
  { brand: '极氪', model: '极氪009', aliases: ['009'] },
  { brand: '极氪', model: '极氪8X', aliases: ['8x'] },
  { brand: '领克', model: '领克Z10', aliases: ['z10'] },
  { brand: '领克', model: '领克02 Hatchback', aliases: ['领克02'] },
  { brand: '奥迪', model: '奥迪E5', aliases: ['奥迪e5', 'e5'] },
  { brand: '奥迪', model: '奥迪A3L', aliases: ['a3l'] },
  { brand: '奔驰', model: '奔驰C级', aliases: ['奔驰c'] },
  { brand: '奔驰', model: '奔驰E级', aliases: ['奔驰e'] },
  { brand: '长安', model: '长安CS95', aliases: ['cs95'] },
  { brand: '理想汽车', model: '理想L系', aliases: ['理想l系', '理想l'] },
];

export function normalizeVehicleKeyword(value: string): string {
  return value
    .replace(/^\uFEFF/, '')
    .toLowerCase()
    .replace(/[^0-9a-z\u4e00-\u9fa5]+/g, '');
}

function parseCsvLine(line: string): string[] {
  const cells: string[] = [];
  let current = '';
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const next = line[index + 1];
    if (char === '"' && quoted && next === '"') {
      current += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === ',' && !quoted) {
      cells.push(current.trim());
      current = '';
    } else {
      current += char;
    }
  }
  cells.push(current.trim());
  return cells;
}

function uniqueVehicleKeys(keys: string[]): string[] {
  return Array.from(new Set(keys.map((key) => normalizeVehicleKeyword(key)).filter(isUsefulVehicleKey)))
    .sort((a, b) => b.length - a.length);
}

function isUsefulVehicleKey(key: string): boolean {
  if (!key) return false;
  if (GENERIC_VEHICLE_TERMS.has(key)) return false;
  if (key.length < 2) return false;
  return true;
}

function buildBrandKeys(brand: string): string[] {
  const chineseOnly = brand.replace(/[A-Za-z]+/g, '');
  const withoutSuffix = chineseOnly.replace(/(汽车|新能源|集团)$/g, '');
  const englishOnly = brand.replace(/[\u4e00-\u9fa5]+/g, '');
  return uniqueVehicleKeys([brand, chineseOnly, withoutSuffix, englishOnly])
    .filter((key) => !AMBIGUOUS_BRAND_ALIASES.has(key));
}

function stripKnownBrandPrefix(model: string, brand: string): string[] {
  const candidates = [brand, brand.replace(/[A-Za-z]+/g, ''), brand.replace(/(汽车|新能源|集团)$/g, '')]
    .map((item) => item.trim())
    .filter(Boolean);
  return candidates
    .filter((candidate) => model.startsWith(candidate) && model.length > candidate.length)
    .map((candidate) => model.slice(candidate.length));
}

function removePowertrainSuffix(model: string): string[] {
  return [
    model.replace(/\s*(phev|ev|dm-i|dmi|em-p|增程版|纯电版|燃油版|插电混动|新能源|闪充版|hatchback)$/i, ''),
    model.replace(/\s*(phev|ev|dm-i|dmi|em-p|增程版|纯电版|燃油版|插电混动|新能源|闪充版|hatchback).*/i, ''),
  ];
}

function extractAlphaNumericTail(model: string): string[] {
  const normalized = normalizeVehicleKeyword(model);
  const matches = normalized.match(/[a-z]*\d+[a-z0-9]*|[a-z]+\d+[a-z0-9]*/g) || [];
  return matches.filter((match) => match.length >= 3);
}

function buildModelKeys(brand: string, model: string, aliases: string[] = []): string[] {
  const businessAliases = BUSINESS_MODEL_ALIASES[`${brand}/${model}`] || [];
  const strippedModels = stripKnownBrandPrefix(model, brand);
  const suffixless = [model, ...strippedModels].flatMap(removePowertrainSuffix);
  const tails = extractAlphaNumericTail(model);
  return uniqueVehicleKeys([model, ...strippedModels, ...suffixless, ...tails, ...businessAliases, ...aliases]);
}

export function parseCarCatalog(csv: string): CarCatalogEntry[] {
  const lines = csv.split(/\r?\n/).filter((line) => line.trim());
  const header = parseCsvLine(lines[0] || '').map((cell) => cell.replace(/^\uFEFF/, ''));
  const brandIndex = header.indexOf('汽车品牌');
  const modelIndex = header.indexOf('详细车型');
  if (brandIndex < 0 || modelIndex < 0) return [];

  const deduped = new Map<string, CarCatalogEntry>();
  const addEntry = (brand: string, model: string, aliases: string[] = []) => {
    if (!brand || !model) return;
    const brandKeys = buildBrandKeys(brand);
    const modelKeys = buildModelKeys(brand, model, aliases);
    if (!brandKeys.length || !modelKeys.length) return;
    deduped.set(`${normalizeVehicleKeyword(brand)}:${normalizeVehicleKeyword(model)}`, {
      brand,
      model,
      brandKeys,
      modelKeys,
    });
  };

  lines.slice(1).forEach((line) => {
    const cells = parseCsvLine(line);
    const brand = cells[brandIndex]?.trim();
    const model = cells[modelIndex]?.trim();
    addEntry(brand, model);
  });
  SUPPLEMENTAL_CATALOG_ROWS.forEach((row) => addEntry(row.brand, row.model, row.aliases));

  return Array.from(deduped.values())
    .sort((a, b) => longestKey(b.modelKeys) - longestKey(a.modelKeys));
}

export function buildCarCatalogFromRows(rows: Array<{ brand?: string | null; model?: string | null }>): CarCatalogEntry[] {
  const deduped = new Map<string, CarCatalogEntry>();
  const addEntry = (brand: string, model: string, aliases: string[] = []) => {
    if (!brand || !model) return;
    const brandKeys = buildBrandKeys(brand);
    const modelKeys = buildModelKeys(brand, model, aliases);
    if (!brandKeys.length || !modelKeys.length) return;
    deduped.set(`${normalizeVehicleKeyword(brand)}:${normalizeVehicleKeyword(model)}`, {
      brand,
      model,
      brandKeys,
      modelKeys,
    });
  };

  rows.forEach((row) => addEntry(String(row.brand || '').trim(), String(row.model || '').trim()));
  SUPPLEMENTAL_CATALOG_ROWS.forEach((row) => addEntry(row.brand, row.model, row.aliases));

  return Array.from(deduped.values())
    .sort((a, b) => longestKey(b.modelKeys) - longestKey(a.modelKeys));
}

export function buildVehicleCatalogIndex(catalog: CarCatalogEntry[]): VehicleCatalogIndex {
  const brandMap = new Map<string, string>();
  const modelItems: VehicleCatalogIndex['modelItems'] = [];
  catalog.forEach((entry) => {
    entry.brandKeys.forEach((key) => {
      if (!brandMap.has(key)) brandMap.set(key, entry.brand);
    });
    entry.modelKeys.forEach((key) => {
      modelItems.push({
        key,
        entry,
        exactModel: normalizeVehicleKeyword(entry.model) === key,
        shortModel: isShortAmbiguousModelKey(key),
      });
    });
  });
  const modelByKey = new Map<string, VehicleCatalogIndex['modelItems']>();
  modelItems.forEach((item) => {
    const items = modelByKey.get(item.key) || [];
    items.push(item);
    modelByKey.set(item.key, items);
  });
  const brandItems = Array.from(brandMap.entries())
    .map(([key, brand]) => ({ key, brand }))
    .sort((a, b) => b.key.length - a.key.length);
  const brandByKey = new Map<string, typeof brandItems>();
  brandItems.forEach((item) => {
    const items = brandByKey.get(item.key) || [];
    items.push(item);
    brandByKey.set(item.key, items);
  });
  const keyLengths = Array.from(new Set([
    ...modelItems.map((item) => item.key.length),
    ...brandItems.map((item) => item.key.length),
  ])).sort((a, b) => a - b);
  return {
    modelItems: modelItems.sort((a, b) => b.key.length - a.key.length),
    brandItems,
    modelByKey,
    brandByKey,
    keyLengths,
  };
}

function longestKey(keys: string[]): number {
  return keys.reduce((max, key) => Math.max(max, key.length), 0);
}

function buildTextSections(note: MatchableNote): TextSections {
  const title = note.title || '';
  const content = note.content || '';
  const topics = Array.from(`${title} ${content}`.matchAll(/#([^#\[\]\n]+)(?:\[话题\])?#/g))
    .map((match) => match[1])
    .join(' ');
  return {
    title: normalizeVehicleKeyword(title),
    topics: normalizeVehicleKeyword(topics),
    lead: normalizeVehicleKeyword(`${title} ${content.slice(0, 160)}`),
    full: normalizeVehicleKeyword(`${title} ${content}`),
  };
}

function sectionScore(key: string, sections: TextSections): number {
  if (!key) return 0;
  if (sections.title.includes(key)) return 30;
  if (sections.topics.includes(key)) return 25;
  if (sections.lead.includes(key)) return 12;
  if (sections.full.includes(key)) return 5;
  return 0;
}

function hasKey(keys: string[], sections: TextSections): boolean {
  return keys.some((key) => sectionScore(key, sections) > 0);
}

function bestKeyScore(keys: string[], sections: TextSections) {
  return keys.reduce<{ key: string; score: number }>((best, key) => {
    const score = sectionScore(key, sections);
    if (score > best.score || (score === best.score && key.length > best.key.length)) return { key, score };
    return best;
  }, { key: '', score: 0 });
}

function isShortAmbiguousModelKey(key: string): boolean {
  if (!key) return true;
  if (key.length <= 1) return true;
  if (/^\d+$/.test(key)) return true;
  if (/^[a-z]\d{1,2}$/i.test(key)) return true;
  return key.length <= 2 && !/[a-z0-9]/i.test(key);
}

export function resolveVehicleMatch(note: MatchableNote, catalog: CarCatalogEntry[]): VehicleMatchResult {
  const sections = buildTextSections(note);
  if (!sections.full || !catalog.length) {
    return { brand: '未识别品牌', model: '未识别车型', confidence: 'none', score: 0, reason: '无文本或车型词库未加载' };
  }

  let best: VehicleMatchResult | null = null;
  catalog.forEach((entry) => {
    const brandMatched = hasKey(entry.brandKeys, sections);
    const brandBest = bestKeyScore(entry.brandKeys, sections);
    const modelBest = bestKeyScore(entry.modelKeys, sections);
    if (modelBest.score > 0) {
      const shortModel = isShortAmbiguousModelKey(modelBest.key);
      if (!shortModel || brandMatched || sections.topics.includes(modelBest.key) || sections.title.includes(modelBest.key)) {
        const exactModel = normalizeVehicleKeyword(entry.model) === modelBest.key;
        const score = (exactModel ? 100 : 82)
          + modelBest.score
          + (brandMatched ? 24 : 0)
          + Math.min(modelBest.key.length, 12);
        const candidate: VehicleMatchResult = {
          brand: entry.brand,
          model: entry.model,
          confidence: exactModel ? 'model_exact' : brandMatched ? 'brand_model' : 'model_alias',
          score,
          reason: `${brandMatched ? '品牌+' : ''}${exactModel ? '车型完整命中' : '车型别名命中'}：${modelBest.key}`,
        };
        if (!best || candidate.score > best.score) best = candidate;
      }
    }

    if (brandBest.score > 0) {
      const brandCandidate: VehicleMatchResult = {
        brand: entry.brand,
        model: '未识别车型',
        confidence: 'brand',
        score: 20 + brandBest.score + Math.min(brandBest.key.length, 8),
        reason: `只命中品牌：${brandBest.key}`,
      };
      if (!best || brandCandidate.score > best.score) best = brandCandidate;
    }
  });

  if (best) return best;
  return { brand: '未识别品牌', model: '未识别车型', confidence: 'none', score: 0, reason: '未命中品牌或车型' };
}

export function resolveVehicleMatchWithIndex(note: MatchableNote, index: VehicleCatalogIndex): VehicleMatchResult {
  const sections = buildTextSections(note);
  if (!sections.full || !index.modelItems.length) {
    return { brand: '未识别品牌', model: '未识别车型', confidence: 'none', score: 0, reason: '无文本或车型词库未加载' };
  }

  const matchedModelKeys = new Map<string, number>();
  const matchedBrandKeys = new Map<string, number>();
  const collectMatches = (text: string, score: number) => {
    if (!text) return;
    index.keyLengths.forEach((length) => {
      if (length > text.length) return;
      for (let offset = 0; offset <= text.length - length; offset += 1) {
        const key = text.slice(offset, offset + length);
        if (index.modelByKey.has(key) && score > (matchedModelKeys.get(key) || 0)) {
          matchedModelKeys.set(key, score);
        }
        if (index.brandByKey.has(key) && score > (matchedBrandKeys.get(key) || 0)) {
          matchedBrandKeys.set(key, score);
        }
      }
    });
  };
  collectMatches(sections.title, 30);
  collectMatches(sections.topics, 25);
  collectMatches(sections.lead, 12);
  collectMatches(sections.full, 5);

  let bestBrand: { key: string; brand: string; score: number } | null = null;
  for (const [key, score] of matchedBrandKeys.entries()) {
    const items = index.brandByKey.get(key) || [];
    for (const item of items) {
      if (!bestBrand || score > bestBrand.score || (score === bestBrand.score && item.key.length > bestBrand.key.length)) {
        bestBrand = { ...item, score };
      }
    }
  }

  let best: VehicleMatchResult | null = null;
  for (const [key, modelScore] of matchedModelKeys.entries()) {
    const items = index.modelByKey.get(key) || [];
    for (const item of items) {
    const brandMatched = item.entry.brandKeys.some((key) => sectionScore(key, sections) > 0);
    if (item.shortModel && !brandMatched && !sections.topics.includes(item.key) && !sections.title.includes(item.key)) {
      continue;
    }
    const score = (item.exactModel ? 100 : 82)
      + modelScore
      + (brandMatched ? 24 : 0)
      + Math.min(item.key.length, 12);
    const candidate: VehicleMatchResult = {
      brand: item.entry.brand,
      model: item.entry.model,
      confidence: item.exactModel ? 'model_exact' : brandMatched ? 'brand_model' : 'model_alias',
      score,
      reason: `${brandMatched ? '品牌+' : ''}${item.exactModel ? '车型完整命中' : '车型别名命中'}：${item.key}`,
    };
    if (!best || candidate.score > best.score) best = candidate;
  }
  }

  if (best) return best;
  if (bestBrand) {
    return {
      brand: bestBrand.brand,
      model: '未识别车型',
      confidence: 'brand',
      score: 20 + bestBrand.score + Math.min(bestBrand.key.length, 8),
      reason: `只命中品牌：${bestBrand.key}`,
    };
  }
  return { brand: '未识别品牌', model: '未识别车型', confidence: 'none', score: 0, reason: '未命中品牌或车型' };
}
