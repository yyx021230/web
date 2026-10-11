export type PromptSourceFilter = 'all' | 'external' | 'internal' | 'performance';

export type PromptLibraryFilter = {
  source: PromptSourceFilter;
  category: string;
};

export const PROMPT_LIBRARY_FILTER_EVENT = 'prompt-library-filter-change';

const validSources = new Set<PromptSourceFilter>(['all', 'external', 'internal', 'performance']);

export function readPromptLibraryFilter(search = ''): PromptLibraryFilter {
  const params = new URLSearchParams(search);
  const rawSource = params.get('source') as PromptSourceFilter | null;
  return {
    source: rawSource && validSources.has(rawSource) ? rawSource : 'all',
    category: (params.get('category') || '').trim(),
  };
}

export function setPromptLibraryFilter(filter: PromptLibraryFilter, mode: 'push' | 'replace' = 'push') {
  const params = new URLSearchParams();
  if (filter.source !== 'all') params.set('source', filter.source);
  if (filter.category) params.set('category', filter.category);
  const href = `/prompts${params.size ? `?${params.toString()}` : ''}`;

  if (mode === 'replace') window.history.replaceState(null, '', href);
  else window.history.pushState(null, '', href);
  window.dispatchEvent(new CustomEvent<PromptLibraryFilter>(PROMPT_LIBRARY_FILTER_EVENT, { detail: filter }));
}
