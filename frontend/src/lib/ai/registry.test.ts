import { describe, expect, it, vi } from 'vitest';

import { modelRegistry } from './registry';
import type { AIModelAdapter } from './model-adapter';

function adapter(name: string): AIModelAdapter {
  return {
    name,
    description: `${name} adapter`,
    generateImage: vi.fn(),
    cancelTask: vi.fn(),
    getTaskStatus: vi.fn(),
  };
}

describe('modelRegistry', () => {
  it('registers, lists and switches the default model', () => {
    const first = adapter('registry-first');
    const second = adapter('registry-second');
    modelRegistry.register(first);
    modelRegistry.register(second);
    expect(modelRegistry.get('registry-first')).toBe(first);
    expect(modelRegistry.list()).toEqual(expect.arrayContaining([first, second]));
    modelRegistry.setDefault('registry-second');
    expect(modelRegistry.getDefault()).toBe(second);
    modelRegistry.setDefault('missing');
    expect(modelRegistry.getDefault()).toBe(second);
  });
});
