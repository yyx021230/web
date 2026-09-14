import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from './api';
import { materialApi } from './materialApi';

vi.mock('./api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

describe('gallery API after editor retirement', () => {
  beforeEach(() => vi.clearAllMocks());

  it('preserves AI template and draft saves with generation metadata', () => {
    const data = { name: 'car', url: '/uploads/car.png', ai_meta: { prompt: 'car portrait' } };
    materialApi.saveAITemplate(data);
    materialApi.saveAIDraft(data);
    expect(api.post).toHaveBeenNthCalledWith(1, '/materials/template', data);
    expect(api.post).toHaveBeenNthCalledWith(2, '/materials/draft-ai', data);
  });

  it('preserves reference-image queries and material metadata updates', () => {
    materialApi.getMaterials(undefined, 2, 30, true, 'ai-template');
    expect(api.get).toHaveBeenCalledWith('/materials', {
      params: { page: 2, limit: 30, owner: true, exclude_category: 'ai-template' },
    });
    materialApi.getMaterial(7);
    expect(api.get).toHaveBeenCalledWith('/materials/7');
    materialApi.updateMaterial(7, { name: 'renamed', tags: ['cars'] });
    expect(api.put).toHaveBeenCalledWith('/materials/7', { name: 'renamed', tags: ['cars'] });
  });

  it('does not expose retired project, template-library or canvas operations', () => {
    for (const key of ['getProjects', 'createProject', 'getTemplates', 'saveDesign']) {
      expect(materialApi).not.toHaveProperty(key);
    }
  });
});
