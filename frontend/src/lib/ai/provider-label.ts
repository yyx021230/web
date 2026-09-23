type ProviderTask = {
  provider_name?: string | null;
  provider_kind?: string | null;
  model_name?: string;
  status?: string;
};

export function getAiProviderLabel(item: ProviderTask): string {
  if (item.provider_name) return item.provider_name;
  if (item.provider_kind === 'adapter_direct') return '直连适配器';
  if (item.provider_kind) return item.provider_kind;
  if (!['gptimage2', 'gptimage25'].includes(item.model_name || '')) return '-';
  // Missing provider metadata is not evidence that a task used the direct adapter.
  return ['queued', 'pending', 'processing'].includes(item.status || '')
    ? '入口待确认'
    : '未记录入口';
}
