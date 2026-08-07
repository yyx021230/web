'use client';

import { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Search, Loader2, X, Eye } from 'lucide-react';
import { cn } from '@/lib/utils';

interface LibraryTemplate {
  id: string;
  title: string;
  type: string;
  width: number;
  height: number;
  payment: string;
  preview: string;
  fabric_json_file: string;
  object_count: number;
  folder: string;
}

export default function LibraryPage() {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('全部');
  const [templates, setTemplates] = useState<LibraryTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [previewTemplate, setPreviewTemplate] = useState<LibraryTemplate | null>(null);

  useEffect(() => {
    fetch('/templates/index.json')
      .then(res => res.json())
      .then(data => {
        const withPreviews = data.map((t: LibraryTemplate) => {
          let previewPath = t.preview;
          if (!previewPath) {
            previewPath = `/templates/${t.folder}/preview.jpg`;
          }
          return { ...t, preview: previewPath };
        });
        setTemplates(withPreviews);
      })
      .catch(() => setTemplates([]))
      .finally(() => setLoading(false));
  }, []);

  const categories = useMemo(() => {
    const cats = new Set<string>();
    for (const t of templates) {
      cats.add(getCategory(t));
    }
    return ['全部', ...Array.from(cats).sort()];
  }, [templates]);

  function getCategory(t: LibraryTemplate): string {
    const rules: Array<[string, string[]]> = [
      ['招聘', ['招聘', '春招', '秋招', '求职', '大厂']],
      ['教育', ['教育', '考研', '考公', '教资', '期末', '单词']],
      ['知识科普', ['科普', '知识', '法律', '母婴', '宠物', '金融', '保险', '物业', '职场']],
      ['节日节气', ['圣诞', '元宵', '情人', '五一', '劳动', '妇女', '教师', '儿童', '节庆', '立春']],
      ['美食', ['美食', '餐饮', '代餐']],
      ['美妆', ['美妆', '美容']],
      ['旅游', ['旅游', '攻略']],
      ['电商', ['电商', '促销', '产品']],
      ['AI工具', ['AI', 'deepseek', '工具', 'aigc', 'AIGC']],
    ];
    for (const [cat, keywords] of rules) {
      if (keywords.some(kw => t.title.toLowerCase().includes(kw.toLowerCase()))) return cat;
    }
    return '其他';
  }

  const filtered = useMemo(() => {
    return templates.filter(t => {
      const cat = getCategory(t);
      const matchCat = activeCategory === '全部' || cat === activeCategory;
      const matchSearch = !searchQuery || t.title.toLowerCase().includes(searchQuery.toLowerCase());
      return matchCat && matchSearch;
    });
  }, [templates, activeCategory, searchQuery]);

  const useTemplate = (t: LibraryTemplate) => {
    // Just store the template meta — editor will load design.json and convert at runtime
    sessionStorage.setItem('selectedTemplate', JSON.stringify({
      id: t.id,
      name: t.title,
      category: getCategory(t),
      width: t.width,
      height: t.height,
      folder: t.folder,
    }));
    router.push('/editor');
  };

  return (
    <div className="cloud-page min-h-screen">
      {/* Header */}
      <div className="cloud-toolbar sticky top-0 z-30">
        <div className="max-w-[1600px] mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="mb-1 inline-flex rounded-full bg-indigo-50 px-2.5 py-1 text-[11px] font-semibold text-indigo-600">Cloud Studio</div>
              <h1 className="text-xl font-bold text-slate-950">模板库</h1>
              <p className="text-sm text-slate-500 mt-0.5">{templates.length} 个模板</p>
            </div>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="搜索模板..."
                className="cloud-pill w-72 rounded-2xl py-2.5 pl-10 pr-4 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-4 focus:ring-indigo-100"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Category tabs */}
      <div className="cloud-toolbar">
        <div className="max-w-[1600px] mx-auto px-6">
          <div className="flex gap-2 py-3 overflow-x-auto">
            {categories.map(cat => {
              const count = cat === '全部'
                ? templates.length
                : templates.filter(t => getCategory(t) === cat).length;
              return (
                <button
                  key={cat}
                  onClick={() => setActiveCategory(cat)}
                  className={cn(
                    'cloud-pill flex-shrink-0 px-4 py-1.5 text-sm rounded-full transition-all',
                    activeCategory === cat
                      ? 'border-indigo-400 bg-indigo-50 text-indigo-600 font-medium'
                      : 'text-slate-600 hover:border-indigo-200 hover:bg-indigo-50'
                  )}
                >
                  {cat}
                  <span className={cn('ml-1 text-xs', activeCategory === cat ? 'text-gray-300' : 'text-gray-400')}>
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Template grid - masonry layout like gaoding.com */}
      <div className="max-w-[1600px] mx-auto px-6 py-6">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="ml-3 text-sm text-gray-500">加载模板中...</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-20">
            <p className="text-gray-500">未找到匹配的模板</p>
          </div>
        ) : (
          <div className="columns-2 md:columns-3 lg:columns-4 xl:columns-5 gap-4 space-y-4">
            {filtered.map(t => {
              const aspectRatio = t.height / t.width;
              const cardHeight = Math.max(140, Math.min(300, 220 * aspectRatio));
              return (
                <div
                  key={t.id}
                  className="cloud-card cloud-card-hover break-inside-avoid group cursor-pointer overflow-hidden rounded-3xl"
                >
                  <div className="relative overflow-hidden" style={{ height: cardHeight }}>
                    <img
                      src={t.preview}
                      alt={t.title}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                      loading="lazy"
                      onError={e => {
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                    {/* Hover overlay */}
                    <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors duration-300 flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100">
                      <button
                        onClick={e => { e.stopPropagation(); setPreviewTemplate(t); }}
                        className="p-2.5 bg-white/90 rounded-full hover:bg-white transition-colors"
                        title="预览"
                      >
                        <Eye className="h-4 w-4 text-gray-700" />
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); useTemplate(t); }}
                        className="px-4 py-2.5 bg-primary text-white text-sm font-medium rounded-full hover:bg-primary/90 transition-colors"
                      >
                        使用模板
                      </button>
                    </div>
                    <div className="absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <span className="text-[10px] bg-black/50 text-white px-1.5 py-0.5 rounded">
                        {t.width}×{t.height}
                      </span>
                    </div>
                  </div>
                  <div className="p-3">
                    <p className="text-sm font-medium text-slate-900 truncate">{t.title}</p>
                    <div className="flex items-center justify-between mt-1.5">
                      <span className="text-xs text-slate-400">{getCategory(t)}</span>
                      <span className="text-[10px] text-slate-400">{t.width}×{t.height}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Preview modal */}
      {previewTemplate && (
        <div
          className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
          onClick={() => setPreviewTemplate(null)}
        >
          <div
            className="bg-white rounded-2xl overflow-hidden max-w-3xl max-h-[90vh] flex shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex-1 bg-gray-100 flex items-center justify-center p-8">
              <img
                src={previewTemplate.preview}
                alt={previewTemplate.title}
                className="max-h-[70vh] max-w-full object-contain rounded-lg shadow-lg"
              />
            </div>
            <div className="w-72 p-6 flex flex-col">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-bold text-gray-900">模板详情</h3>
                <button onClick={() => setPreviewTemplate(null)} className="p-1 hover:bg-gray-100 rounded">
                  <X className="h-5 w-5 text-gray-400" />
                </button>
              </div>
              <p className="text-sm text-gray-600 mb-4">{previewTemplate.title}</p>
              <div className="space-y-3 mb-6">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">尺寸</span>
                  <span className="text-gray-900 font-medium">{previewTemplate.width} × {previewTemplate.height}px</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">分类</span>
                  <span className="text-gray-900 font-medium">{getCategory(previewTemplate)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">元素数</span>
                  <span className="text-gray-900 font-medium">{previewTemplate.object_count || '-'}</span>
                </div>
              </div>
              <div className="mt-auto space-y-2">
                <button
                  onClick={() => useTemplate(previewTemplate)}
                  className="w-full py-2.5 bg-primary text-white font-medium rounded-xl hover:bg-primary/90 transition-colors"
                >
                  使用此模板
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
