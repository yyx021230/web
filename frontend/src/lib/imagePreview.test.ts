import { describe, expect, it } from 'vitest';

import { getImagePreviewUrl } from './imagePreview';

describe('getImagePreviewUrl', () => {
  it('routes internal uploads through the thumbnail endpoint', () => {
    expect(getImagePreviewUrl('/uploads/prompts/中文 图.png', 640, 70)).toBe(
      '/_next/image?url=%2Fuploads%2Fprompts%2F%E4%B8%AD%E6%96%87%20%E5%9B%BE.png&w=640&q=70',
    );
  });

  it('leaves remote and data URLs untouched', () => {
    expect(getImagePreviewUrl('https://cdn.example.com/a.png')).toBe('https://cdn.example.com/a.png');
    expect(getImagePreviewUrl('data:image/png;base64,abc')).toBe('data:image/png;base64,abc');
  });
});
