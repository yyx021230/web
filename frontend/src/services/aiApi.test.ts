import { afterEach, describe, expect, it, vi } from 'vitest';

import { aiApi } from './aiApi';

describe('aiApi.generateImage', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('adds the bearer token and unwraps a successful envelope', async () => {
    localStorage.setItem('token', 'token-1');
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({
        code: 0,
        data: { task_id: 'task-1', status: 'completed', image_urls: ['/uploads/a.png'] },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await aiApi.generateImage({ prompt: 'test', model: 'gptimage2' });
    expect(result.data.task_id).toBe('task-1');
    expect(fetchMock).toHaveBeenCalledWith('/api/ai-image/generate', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ Authorization: 'Bearer token-1' }),
    }));
  });

  it('preserves HTTP status and server messages for auth and upstream failures', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        status: 401,
        json: async () => ({ detail: '登录已失效' }),
      })
      .mockResolvedValueOnce({
        status: 524,
        json: async () => ({ message: '上游生成超时' }),
      });
    vi.stubGlobal('fetch', fetchMock);

    await expect(aiApi.generateImage({ prompt: 'one', model: 'gptimage2' })).rejects.toMatchObject({
      message: '登录已失效',
      status: 401,
    });
    await expect(aiApi.generateImage({ prompt: 'two', model: 'gptimage2' })).rejects.toMatchObject({
      message: '上游生成超时',
      status: 524,
    });
  });
});
