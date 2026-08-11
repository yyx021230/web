import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  generateImage: vi.fn(),
  getTaskStatus: vi.fn(),
  cancelTask: vi.fn(),
  getHistory: vi.fn(),
}));

vi.mock('@/services/aiApi', () => ({
  aiApi: apiMocks,
}));

import { useAIStore } from './aiStore';

describe('useAIStore', () => {
  beforeEach(() => {
    vi.useRealTimers();
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
    useAIStore.setState({
      generations: [],
      currentModel: 'gptimage2',
      isGenerating: false,
    });
  });

  it('stores immediately completed generations', async () => {
    apiMocks.generateImage.mockResolvedValue({
      data: { task_id: 'task-1', status: 'completed', image_urls: ['/uploads/a.png'] },
    });
    const id = await useAIStore.getState().generateImage('portrait', { width: 768, height: 1024 });
    expect(id).toBe('task-1');
    expect(apiMocks.generateImage).toHaveBeenCalledWith(expect.objectContaining({
      prompt: 'portrait',
      model: 'gptimage2',
      width: 768,
      height: 1024,
    }));
    expect(useAIStore.getState().generations[0]).toMatchObject({
      id: 'task-1',
      status: 'completed',
      imageUrl: '/uploads/a.png',
    });
    expect(useAIStore.getState().isGenerating).toBe(false);
  });

  it('polls asynchronous tasks through completion', async () => {
    vi.useFakeTimers();
    apiMocks.generateImage.mockResolvedValue({
      data: { task_id: 'task-2', status: 'processing', image_urls: [] },
    });
    apiMocks.getTaskStatus.mockResolvedValue({
      data: { task_id: 'task-2', status: 'completed', image_urls: ['/uploads/b.png'] },
    });
    await useAIStore.getState().generateImage('async');
    expect(useAIStore.getState().generations[0].status).toBe('generating');
    await vi.advanceTimersByTimeAsync(2000);
    expect(useAIStore.getState().generations[0]).toMatchObject({
      status: 'completed',
      imageUrl: '/uploads/b.png',
    });
    expect(useAIStore.getState().isGenerating).toBe(false);
  });

  it('records failed polling, submit failures and cancellation', async () => {
    vi.useFakeTimers();
    apiMocks.generateImage.mockResolvedValueOnce({
      data: { task_id: 'task-3', status: 'processing', image_urls: [] },
    });
    apiMocks.getTaskStatus.mockResolvedValue({
      data: { task_id: 'task-3', status: 'failed', image_urls: [], error: 'quota' },
    });
    await useAIStore.getState().generateImage('will fail');
    await vi.advanceTimersByTimeAsync(2000);
    expect(useAIStore.getState().generations[0]).toMatchObject({ status: 'failed', error: 'quota' });

    apiMocks.generateImage.mockRejectedValueOnce(new Error('network'));
    await expect(useAIStore.getState().generateImage('submit fails')).resolves.toBeUndefined();
    expect(useAIStore.getState().isGenerating).toBe(false);

    apiMocks.cancelTask.mockResolvedValue({});
    useAIStore.getState().cancelGeneration('task-3');
    expect(apiMocks.cancelTask).toHaveBeenCalledWith('task-3', 'gptimage2');
    expect(useAIStore.getState().generations[0].error).toBe('已取消');
  });

  it('maps history records and preserves previous data on fetch errors', async () => {
    apiMocks.getHistory.mockResolvedValue({
      data: {
        items: [{
          id: 9,
          prompt: 'history',
          model_name: 'seedream',
          status: 'completed',
          result_urls: ['/uploads/history.png'],
          created_at: '2026-08-11T10:00:00Z',
        }],
      },
    });
    await useAIStore.getState().fetchHistory(2, 10);
    expect(apiMocks.getHistory).toHaveBeenCalledWith(2, 10);
    expect(useAIStore.getState().generations[0]).toMatchObject({
      id: '9',
      model: 'seedream',
      imageUrl: '/uploads/history.png',
    });

    apiMocks.getHistory.mockRejectedValue(new Error('offline'));
    await useAIStore.getState().fetchHistory();
    expect(useAIStore.getState().generations).toHaveLength(1);
  });
});
