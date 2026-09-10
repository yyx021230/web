import { describe, expect, it, vi } from 'vitest';
vi.mock('./api', () => ({ default: { get: vi.fn().mockResolvedValue({ data: {} }), post: vi.fn().mockResolvedValue({ data: {} }), patch: vi.fn().mockResolvedValue({ data: {} }), put: vi.fn().mockResolvedValue({ data: {} }) } }));
import api from './api';
import { hermesWorkflowApi } from './hermesWorkflowApi';

describe('Hermes real workflow API contracts', () => {
  it('loads real reference examples and sends independent type IDs', async () => {
    await hermesWorkflowApi.referenceTypes();
    expect(api.get).toHaveBeenCalledWith('/hermes-workflows/reference-types', { timeout: 20000 });
    const payload = { account_id: 2, vehicle_model: '零跑A05', post_count: 1, copy_type: 'drive_review', image_type: 'note_poster' };
    await hermesWorkflowApi.createRun(payload);
    expect(api.post).toHaveBeenCalledWith('/hermes-workflows/runs', payload);
  });
  it('loads paginated history instead of 500 heavy records', async () => {
    await hermesWorkflowApi.listRuns({ search: '通勤', source: 'manual', page: 2 });
    expect(api.get).toHaveBeenCalledWith('/hermes-workflows/runs', { params: { limit: 8, search: '通勤', source: 'manual', page: 2 }, timeout: 20000 });
  });
  it('keeps workflow scope on both owner and administrator history requests', async () => {
    const query = { workflow_mode: 'single' as const, status: 'review_pending', page: 2 };
    await hermesWorkflowApi.listRuns(query);
    expect(api.get).toHaveBeenCalledWith('/hermes-workflows/runs', { params: { limit: 8, ...query }, timeout: 20000 });
    await hermesWorkflowApi.adminListRuns({ workflow_mode: 'batch' });
    expect(api.get).toHaveBeenCalledWith('/admin/hermes-workflows/runs', { params: { limit: 8, workflow_mode: 'batch' }, timeout: 20000 });
  });
  it('sends review version to prevent stale approval', async () => {
    await hermesWorkflowApi.reviewPost(9, 'approve', undefined, 'version-a');
    expect(api.post).toHaveBeenCalledWith('/hermes-workflows/posts/9/review', { action: 'approve', comment: undefined, expected_version: 'version-a' });
  });
  it('explicitly opts into single-post regeneration for both owner and admin review', async () => {
    await hermesWorkflowApi.reviewPost(9, 'reject', '图中配置不符', 'v2', true);
    expect(api.post).toHaveBeenCalledWith('/hermes-workflows/posts/9/review', { action: 'reject', comment: '图中配置不符', expected_version: 'v2', regenerate: true });
    await hermesWorkflowApi.adminReviewPost(9, 'reject', '需修正', 'v2', true);
    expect(api.post).toHaveBeenCalledWith('/admin/hermes-workflows/posts/9/review', { action: 'reject', comment: '需修正', expected_version: 'v2', regenerate: true });
  });
  it('uses distinct admin publish endpoint for cross-owner content', async () => {
    const items = [{ post_id: 9, environment_id: 2, scheduled_at: '2030-01-01T09:00:00+08:00', expected_version: 'v' }];
    await hermesWorkflowApi.adminSavePublishPlan(items);
    expect(api.post).toHaveBeenCalledWith('/admin/hermes-workflows/publish-plan', { items });
  });
  it('preserves full title, emoji and final topics on edit', async () => {
    const payload = { title: '试驾记录🚗', content: '完整正文\n\n#零跑A05[话题]#', comment: '调整话术', expected_version: 'v' };
    await hermesWorkflowApi.editPost(12, payload);
    expect(api.patch).toHaveBeenCalledWith('/hermes-workflows/posts/12', payload);
  });
  it('recovers a transient read failure with a bounded retry', async () => {
    vi.useFakeTimers();
    vi.mocked(api.get).mockClear().mockRejectedValueOnce(new Error('Network Error'));
    try {
      const pending = hermesWorkflowApi.getRun(9);
      await vi.runAllTimersAsync();
      await pending;
      expect(api.get).toHaveBeenCalledTimes(2);
    } finally { vi.useRealTimers(); }
  });
  it('does not retry permission errors or writes', async () => {
    vi.mocked(api.get).mockClear().mockRejectedValueOnce(Object.assign(new Error('Forbidden'), { status: 403 }));
    await expect(hermesWorkflowApi.getRun(9)).rejects.toThrow('Forbidden');
    expect(api.get).toHaveBeenCalledTimes(1);
    vi.mocked(api.post).mockClear().mockRejectedValueOnce(new Error('Network Error'));
    await expect(hermesWorkflowApi.createRun({ account_id: 1, vehicle_model: '零跑A05', post_count: 1 })).rejects.toThrow('Network Error');
    expect(api.post).toHaveBeenCalledTimes(1);
  });
});
