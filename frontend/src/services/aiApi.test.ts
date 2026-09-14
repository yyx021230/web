import { afterEach, describe, expect, it, vi } from 'vitest';

import { aiApi } from './aiApi';

describe('aiApi.generateImage', () => {
  afterEach(() => vi.unstubAllGlobals());

  const success = { status: 200, json: async () => ({ code: 0, data: { task_id: 'task-1' } }) };

  it('converts legacy car images to inline data without changing retry settings', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, blob: async () => new Blob(['reference'], { type: 'image/webp' }) })
      .mockResolvedValueOnce(success);
    vi.stubGlobal('fetch', fetchMock);
    const params = { prompt: 'test', model: 'gptimage25', generation_mode: 'precision' as const,
      width: 1024, height: 1536, count: 1, image_url: '/car-models/零跑/C16/斜前.webp' };
    await aiApi.generateImage(params);
    const sent = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(sent).toMatchObject({ prompt: 'test', model: 'gptimage25', generation_mode: 'precision', width: 1024, height: 1536, count: 1 });
    expect(sent.image_data).toMatch(/^data:image\/webp;base64,/);
    expect(sent.image_url).toBeUndefined();
    expect(params.image_url).toBe('/car-models/零跑/C16/斜前.webp');
  });

  it('keeps mixed references in order and normalizes same-origin uploads', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, blob: async () => new Blob(['ref'], { type: 'image/png' }) })
      .mockResolvedValueOnce(success);
    vi.stubGlobal('fetch', fetchMock);
    await aiApi.generateImage({ prompt: 'test', model: 'gptimage2', images_data: [
      '/car-models/car.png', 'http://localhost:3000/uploads/ref.png', 'https://trusted.example/ref.png',
    ] });
    const sent = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(sent.images_data[0]).toMatch(/^data:image\/png;base64,/);
    expect(sent.images_data.slice(1)).toEqual(['/uploads/ref.png', 'https://trusted.example/ref.png']);
  });

  it('does not fetch arbitrary remote references or bypass backend allowlists', async () => {
    const fetchMock = vi.fn().mockResolvedValue(success);
    vi.stubGlobal('fetch', fetchMock);
    await aiApi.generateImage({ prompt: 'test', model: 'gptimage2', image_url: 'https://other.example/car-models/a.png' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).image_url).toBe('https://other.example/car-models/a.png');
  });

  it.each([
    { ok: false, status: 404 },
    { ok: true, blob: async () => new Blob(['html'], { type: 'text/html' }) },
    { ok: true, blob: async () => ({ type: 'image/png', size: 11 * 1024 * 1024 }) },
  ])('does not submit generation when a legacy reference cannot be loaded', async response => {
    const fetchMock = vi.fn().mockResolvedValue(response);
    vi.stubGlobal('fetch', fetchMock);
    await expect(aiApi.generateImage({ prompt: 'test', model: 'gptimage2', image_url: '/car-models/a.png' }))
      .rejects.toMatchObject({ status: 400, message: expect.stringContaining('车型参考图读取失败') });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('shows field validation details instead of a generic validation failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 422, json: async () => ({
      code: 422, message: '参数验证失败', data: [{ field: 'body.image_url', message: 'Value error, 参考图片仅支持内部图库' }],
    }) }));
    await expect(aiApi.generateImage({ prompt: 'test', model: 'gptimage2' }))
      .rejects.toMatchObject({ status: 422, message: '参考图地址：参考图片仅支持内部图库' });
  });

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
