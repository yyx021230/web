'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Search, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { editorApi, type Template as BackendTemplate } from '@/services/editorApi';

const categoryMap: Record<string, string> = {
  poster: '海报',
  social: '社交媒体',
  card: '卡片',
  banner: '电商',
  presentation: '演示',
};

const getCategoryLabel = (cat: string) => categoryMap[cat] || cat;

function getDimensions(fabricJson: string): { width: number; height: number } {
  try {
    const parsed = JSON.parse(fabricJson);
    return { width: parsed.width || 1242, height: parsed.height || 1656 };
  } catch {
    return { width: 1242, height: 1656 };
  }
}

const categoryColors: Record<string, string> = {
  poster: '#f59e0b',
  social: '#6366f1',
  card: '#8b5cf6',
  banner: '#ec4899',
  presentation: '#14b8a6',
};

export default function TemplatesPage() {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('全部');
  const [templates, setTemplates] = useState<BackendTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    editorApi.getTemplates()
      .then(res => setTemplates(res.data.items))
      .catch(() => setTemplates([]))
      .finally(() => setLoading(false));
  }, []);

  const categories = ['全部', ...Array.from(new Set(templates.map(t => getCategoryLabel(t.category))))];

  const filtered = templates.filter(t => {
    const catLabel = getCategoryLabel(t.category);
    const matchCat = activeCategory === '全部' || catLabel === activeCategory;
    const matchSearch = t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.category.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (t.description || '').toLowerCase().includes(searchQuery.toLowerCase());
    return matchCat && matchSearch;
  });

  const useTemplate = (t: BackendTemplate) => {
    const { width, height } = getDimensions(t.fabric_json || '{}');
    sessionStorage.setItem('selectedTemplate', JSON.stringify({
      id: t.id,
      name: t.name,
      category: getCategoryLabel(t.category),
      width,
      height,
      fabric_json: t.fabric_json,
    }));
    router.push('/editor');
  };

  return (
    <div className="cloud-page h-full overflow-auto p-6">
      <div className="cloud-panel mx-auto max-w-7xl rounded-[32px] p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="mb-2 inline-flex rounded-full bg-indigo-50 px-2.5 py-1 text-[11px] font-semibold text-indigo-600">Cloud Studio</div>
          <h1 className="text-2xl font-semibold text-slate-950">模板库</h1>
          <p className="text-sm text-slate-500 mt-1">选择模板快速开始设计</p>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索模板..."
            className="cloud-pill w-64 rounded-2xl py-2.5 pl-10 pr-4 text-sm focus:outline-none focus:ring-4 focus:ring-indigo-100"
          />
        </div>
      </div>

      <div className="flex gap-2 mb-6">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={cn('cloud-pill px-4 py-2 text-sm rounded-full transition-colors hover:border-indigo-200 hover:bg-indigo-50',
              activeCategory === cat ? 'border-indigo-400 bg-indigo-50 text-indigo-600 font-medium' : 'text-slate-600')}
          >
            {cat}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <span className="ml-3 text-sm text-muted-foreground">加载模板中...</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-muted-foreground">未找到匹配的模板</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {filtered.map((template) => {
            const { width, height } = getDimensions(template.fabric_json || '{}');
            const color = categoryColors[template.category] || '#6366f1';
            return (
              <div
                key={template.id}
                onClick={() => useTemplate(template)}
                className="cloud-card cloud-card-hover group cursor-pointer overflow-hidden rounded-3xl"
              >
                <div className="aspect-[4/3] flex items-center justify-center relative" style={{ backgroundColor: color }}>
                  <span className="text-white text-sm font-medium">{template.name}</span>
                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors flex items-center justify-center">
                    <span className="text-white text-xs font-medium opacity-0 group-hover:opacity-100 transition-opacity bg-primary/80 px-3 py-1 rounded-full">
                      使用模板
                    </span>
                  </div>
                </div>
                <div className="p-3">
                  <p className="text-sm font-medium truncate text-slate-900">{template.name}</p>
                  <p className="text-xs text-slate-400 mt-1">{getCategoryLabel(template.category)} · {width}×{height}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}
      </div>
    </div>
  );
}
