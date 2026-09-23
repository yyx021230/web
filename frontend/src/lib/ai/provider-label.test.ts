import { describe, expect, it } from 'vitest';
import { getAiProviderLabel } from './provider-label';

describe('AI task provider labels', () => {
  it.each(['queued', 'pending', 'processing'])('does not invent a direct route for %s tasks', (status) => {
    for (const model_name of ['gptimage2', 'gptimage25']) {
      expect(getAiProviderLabel({ model_name, status })).toBe('入口待确认');
    }
  });

  it.each(['completed', 'failed', 'cancelled', 'postprocessing'])('does not invent a route for %s tasks', (status) => {
    expect(getAiProviderLabel({ model_name: 'gptimage2', status })).toBe('未记录入口');
  });

  it('keeps actual provider names and explicitly recorded direct routes', () => {
    expect(getAiProviderLabel({ provider_name: 'team', status: 'processing' })).toBe('team');
    expect(getAiProviderLabel({ provider_kind: 'adapter_direct' })).toBe('直连适配器');
    expect(getAiProviderLabel({ provider_kind: 'mentalout_batch' })).toBe('mentalout_batch');
    expect(getAiProviderLabel({ model_name: 'seedream' })).toBe('-');
  });
});
