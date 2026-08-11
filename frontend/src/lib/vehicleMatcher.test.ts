import { describe, expect, it } from 'vitest';

import {
  buildCarCatalogFromRows,
  buildVehicleCatalogIndex,
  normalizeVehicleKeyword,
  parseCarCatalog,
  resolveVehicleMatch,
  resolveVehicleMatchWithIndex,
} from './vehicleMatcher';

describe('vehicleMatcher', () => {
  it('normalizes keywords and parses quoted CSV rows', () => {
    expect(normalizeVehicleKeyword('\uFEFF零跑 C10 Pro')).toBe('零跑c10pro');
    expect(parseCarCatalog('错误列,车型\n零跑,C10')).toEqual([]);

    const catalog = parseCarCatalog(
      '\uFEFF汽车品牌,详细车型,备注\n零跑汽车,零跑C10,"带,逗号"\n比亚迪,宋PLUS,普通',
    );
    expect(catalog.some((item) => item.brand === '零跑汽车' && item.model === '零跑C10')).toBe(true);
    expect(catalog.some((item) => item.brand === '比亚迪' && item.model === '宋PLUS')).toBe(true);
  });

  it('deduplicates rows and supplements operational aliases', () => {
    const catalog = buildCarCatalogFromRows([
      { brand: '零跑汽车', model: '零跑C10' },
      { brand: '零跑汽车', model: '零跑C10' },
      { brand: '', model: '无效' },
    ]);
    expect(catalog.filter((item) => item.brand === '零跑汽车' && item.model === '零跑C10')).toHaveLength(1);
    expect(catalog.some((item) => item.brand === '极氪' && item.model === '极氪001')).toBe(true);
  });

  it('matches exact models, aliases, brands and empty text', () => {
    const catalog = buildCarCatalogFromRows([
      { brand: '零跑汽车', model: '零跑C10' },
      { brand: '比亚迪', model: '宋PLUS' },
    ]);
    const exact = resolveVehicleMatch({ title: '零跑C10最新价格' }, catalog);
    expect(exact).toMatchObject({ brand: '零跑汽车', model: '零跑C10', confidence: 'model_exact' });

    const alias = resolveVehicleMatch({ title: 'C10限时权益' }, catalog);
    expect(alias).toMatchObject({ brand: '零跑汽车', model: '零跑C10' });

    const brand = resolveVehicleMatch({ title: '比亚迪年中政策' }, catalog);
    expect(brand).toMatchObject({ brand: '比亚迪', model: '未识别车型', confidence: 'brand' });
    expect(resolveVehicleMatch({ title: '' }, catalog).confidence).toBe('none');
  });

  it('indexed and direct matching return the same operational result', () => {
    const catalog = buildCarCatalogFromRows([
      { brand: '小鹏', model: '小鹏G6' },
      { brand: '领克', model: '领克Z10' },
    ]);
    const index = buildVehicleCatalogIndex(catalog);
    const notes = [
      { title: '小鹏G6真实体验', content: '#小鹏G6[话题]#' },
      { title: '领克新车权益', content: '今天介绍领克Z10' },
      { title: '没有车型的普通内容', content: '' },
    ];
    notes.forEach((note) => {
      const direct = resolveVehicleMatch(note, catalog);
      const indexed = resolveVehicleMatchWithIndex(note, index);
      expect(indexed.brand).toBe(direct.brand);
      expect(indexed.model).toBe(direct.model);
      expect(indexed.confidence).toBe(direct.confidence);
    });
  });
});
