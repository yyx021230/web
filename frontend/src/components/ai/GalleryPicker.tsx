'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { cn } from '@/lib/utils';
import {
  X, Search, Loader2, ImagePlus, Check,
  FileImage, Car, ChevronDown, Layers,
} from 'lucide-react';
import { editorApi, type Material } from '@/services/editorApi';
import { carModelsApi } from '@/services/carModelsApi';

export interface GalleryPickerImage {
  id: string;
  name: string;
  url: string;
  width: number;
  height: number;
  source: 'drafts' | 'car-models' | 'templates';
  brand?: string;
  model?: string;
  angle?: string;
}

interface GalleryPickerProps {
  open: boolean;
  onClose: () => void;
  onSelect: (image: GalleryPickerImage) => void;
  /** 是否允许多选（最多 10 张） */
  multiSelect?: boolean;
  /** 多选确认回调 */
  onMultiSelect?: (images: GalleryPickerImage[]) => void;
  /** 已选中的图片标识列表（可传图片 ID 或 URL，用于标记已添加） */
  existingIds?: string[];
}

type TabKey = 'drafts' | 'car-models' | 'templates';

const TABS: { key: TabKey; label: string; icon: React.ReactNode }[] = [
  { key: 'drafts', label: '草稿箱', icon: <FileImage className="h-3.5 w-3.5" /> },
  { key: 'templates', label: '模版库', icon: <Layers className="h-3.5 w-3.5" /> },
  { key: 'car-models', label: '车型库', icon: <Car className="h-3.5 w-3.5" /> },
];

/** 简易的可搜索下拉选择 */
function SearchableSelect({
  options, value, onChange, placeholder = '请选择...', emptyText = '无匹配结果', className,
}: {
  options: string[];
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
  emptyText?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const filtered = query ? options.filter(o => o.toLowerCase().includes(query.toLowerCase())) : options;
  const displayItems = filtered;

  return (
    <div ref={wrapperRef} className={cn('relative', open && 'z-[90]', className)}>
      <div
        onClick={() => { setOpen(!open); setQuery(''); }}
        className={cn(
          'flex h-8 items-center justify-between rounded-lg border bg-background px-3 text-sm cursor-pointer transition-colors',
          open ? 'ring-2 ring-primary/30 border-primary' : 'hover:border-foreground/20'
        )}
      >
        <span className={cn('truncate', !value && 'text-muted-foreground')}>
          {value || placeholder}
        </span>
        <ChevronDown className={cn('h-4 w-4 ml-2 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </div>
      {open && (
        <div className="absolute top-full mt-1 z-[100] w-52 rounded-lg border bg-card shadow-lg overflow-hidden">
          <div className="p-2 border-b">
            <input autoFocus type="text" placeholder="搜索..." value={query}
              onChange={(e) => setQuery(e.target.value)} onClick={(e) => e.stopPropagation()}
              className="w-full rounded-md border bg-background px-2.5 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-primary/30" />
          </div>
          <div className="max-h-48 overflow-auto py-1">
            {displayItems.length === 0 ? (
              <div className="px-3 py-2 text-xs text-muted-foreground">{emptyText}</div>
            ) : (
              displayItems.map(opt => (
                <div key={opt} onClick={() => { onChange(opt); setOpen(false); setQuery(''); }}
                  className={cn('px-3 py-1.5 text-sm cursor-pointer transition-colors',
                    opt === value ? 'bg-primary/10 text-primary font-medium' : 'hover:bg-accent')}>
                  {opt}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function GalleryPicker({ open, onClose, onSelect, multiSelect, onMultiSelect, existingIds = [] }: GalleryPickerProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('drafts');
  const [searchQuery, setSearchQuery] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [multiSelected, setMultiSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);

  // Drafts
  const [draftImages, setDraftImages] = useState<GalleryPickerImage[]>([]);
  // Templates
  const [templateImages, setTemplateImages] = useState<GalleryPickerImage[]>([]);
  // Car models
  const [carBrands, setCarBrands] = useState<string[]>([]);
  const [selectedBrand, setSelectedBrand] = useState('');
  const [carModels, setCarModels] = useState<Record<string, string[]>>({});
  const [selectedModel, setSelectedModel] = useState('all');
  const [carImages, setCarImages] = useState<GalleryPickerImage[]>([]);

  const fetchDrafts = useCallback(async () => {
    setLoading(true);
    try {
      const all: Material[] = [];
      let page = 1;
      let hasMore = true;
      while (hasMore) {
        const res = await editorApi.getMaterials(undefined, page, 50, true, 'ai-template');
        all.push(...res.data.items);
        hasMore = res.data.items.length === 50;
        page++;
      }
      setDraftImages(all.map(m => ({
        id: `drafts:${m.id}`,
        name: m.name,
        url: m.url || '',
        width: m.width,
        height: m.height,
        source: 'drafts' as const,
      })));
    } catch (e) {
      console.error('Failed to fetch drafts:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const all: Material[] = [];
      let page = 1;
      let hasMore = true;
      while (hasMore) {
        const res = await editorApi.getMaterials('ai-template', page, 50, true);
        const items = res.data.items;
        all.push(...items);
        hasMore = items.length === 50;
        page++;
      }
      setTemplateImages(all.map(m => ({
        id: `templates:${m.id}`,
        name: m.name,
        url: m.url || '',
        width: m.width || 2048,
        height: m.height || 2048,
        source: 'templates' as const,
      })));
    } catch (e) {
      console.error('Failed to fetch templates:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchCarImages = useCallback(async (brand: string, model?: string) => {
    try {
      const res = await carModelsApi.getCarImages(brand, model);
      const data = res.data;
      // model check
      setCarImages((data.images || []).map((img: any, idx: number) => ({
        id: `car-models:${data.brand}-${img.model || data.model}-${idx}`,
        name: `${data.brand} ${img.model || data.model} - ${img.label}`,
        url: img.url,
        width: 1920,
        height: 1080,
        source: 'car-models' as const,
        brand: data.brand,
        model: img.model || data.model,
        angle: img.label,
      })));
    } catch (e) {
      console.error('Failed to fetch car images:', e);
      setCarImages([]);
    }
  }, []);

  // Load data on open
  useEffect(() => {
    if (!open) return;
    setSelected(null);
    setMultiSelected(new Set());
    setSearchQuery('');

    if (activeTab === 'drafts') {
      fetchDrafts();
    } else if (activeTab === 'templates') {
      fetchTemplates();
    } else {
      setLoading(true);
      setCarImages([]);

      // 先加载品牌和车型列表
      Promise.all([
        carModelsApi.getBrands(),
        carModelsApi.getModels(),
      ]).then(([brandsRes, modelsRes]) => {
        const brands = [...brandsRes.data].sort((a, b) => a.localeCompare(b, 'zh-CN'));
        setCarBrands(brands);
        setCarModels(modelsRes.data);
        // 默认选中第一个品牌，加载全部车型
        if (brands.length > 0) {
          setSelectedBrand(brands[0]);
          setSelectedModel('all');
          return fetchCarImages(brands[0], undefined);
        }
        return Promise.resolve();
      })
        .catch(() => { /* ignore */ })
        .finally(() => { setLoading(false); });
    }
  }, [open, activeTab, fetchDrafts, fetchTemplates, fetchCarImages]);

  // Brand change
  const handleBrandChange = async (brand: string) => {
    setSelectedBrand(brand);
    setSelectedModel('all');
    setCarImages([]);
    setLoading(true);
    try {
      const modelsRes = await carModelsApi.getModels(brand);
      setCarModels(modelsRes.data);
      await fetchCarImages(brand, undefined);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  };

  // Model change
  const handleModelChange = (model: string) => {
    setSelectedModel(model);
    if (selectedBrand) {
      // model 为 'all' 时不传，获取该品牌下所有车型
      fetchCarImages(selectedBrand, model === 'all' ? undefined : model);
    }
  };

  // Filter
  const currentImages = (() => {
    const images = activeTab === 'drafts' ? draftImages : activeTab === 'templates' ? templateImages : carImages;
    if (!searchQuery) return images;
    const q = searchQuery.toLowerCase();
    return images.filter(img =>
      img.name.toLowerCase().includes(q) ||
      img.brand?.toLowerCase().includes(q) ||
      img.model?.toLowerCase().includes(q) ||
      img.angle?.toLowerCase().includes(q)
    );
  })();

  // Confirm
  const handleConfirm = () => {
    if (multiSelect && onMultiSelect) {
      if (multiSelected.size === 0) return;
      const selectedImages = currentImages.filter(img => multiSelected.has(img.id));
      if (selectedImages.length > 0) {
        onMultiSelect(selectedImages);
      }
    } else {
      if (!selected) return;
      const img = currentImages.find(i => i.id === selected);
      if (img) onSelect(img);
    }
  };

  // Toggle multi selection
  const toggleMulti = (id: string) => {
    setMultiSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < 10) {
        next.add(id);
      }
      return next;
    });
  };

  // Check if image is already added to the main UI
  const isAlreadyAdded = (img: GalleryPickerImage) => existingIds.includes(img.id) || existingIds.includes(img.url);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="flex flex-col bg-card rounded-2xl shadow-2xl border w-[720px] max-h-[85vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-5 py-4">
          <h3 className="text-sm font-semibold">
            从图库选择参考图
            {multiSelect && <span className="ml-2 text-xs font-normal text-muted-foreground">（可多选，最多 10 张）</span>}
          </h3>
          <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full hover:bg-accent transition-colors">
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b px-5">
          {TABS.map(tab => (
            <button key={tab.key} onClick={() => { setActiveTab(tab.key); setSelected(null); setMultiSelected(new Set()); setSearchQuery(''); }}
              className={cn(
                'flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors',
                activeTab === tab.key
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              )}>
              {tab.icon}{tab.label}
            </button>
          ))}
        </div>

        {/* Toolbar */}
        <div className="flex items-center gap-3 border-b px-5 py-3">
          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input type="text" placeholder="搜索图片..." value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-lg border bg-background py-1.5 pl-8 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
          </div>
          {activeTab === 'car-models' && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground whitespace-nowrap">品牌</span>
              <SearchableSelect options={carBrands} value={selectedBrand} onChange={handleBrandChange}
                placeholder="选择品牌..." emptyText="无匹配品牌" />
              <span className="text-xs text-muted-foreground whitespace-nowrap">车型</span>
              <div className="flex items-center gap-1">
                <button onClick={() => handleModelChange('all')}
                  className={cn('px-2 py-1 text-xs rounded-lg border transition-colors',
                    selectedModel === 'all' ? 'bg-primary text-primary-foreground border-primary font-medium' : 'hover:border-primary/50 text-muted-foreground')}>
                  全部
                </button>
                <span className="text-xs text-muted-foreground">|</span>
                <SearchableSelect options={carModels[selectedBrand] || []} value={selectedModel}
                  onChange={handleModelChange} placeholder="选择车型..." emptyText="无匹配车型" className="min-w-[120px]" />
              </div>
            </div>
          )}
          <span className="ml-auto text-xs text-muted-foreground">{currentImages.length} 张</span>
        </div>

        {/* Image Grid */}
        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Loader2 className="h-8 w-8 animate-spin text-primary mb-3" />
              <p className="text-sm text-muted-foreground">加载中...</p>
            </div>
          ) : currentImages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <ImagePlus className="h-10 w-10 text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">
                {activeTab === 'drafts' ? '暂无草稿图片' : activeTab === 'templates' ? '暂无模版图片' : '暂无车型图片'}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2.5">
              {currentImages.map(img => {
                const isSelected = multiSelect ? multiSelected.has(img.id) : selected === img.id;
                const alreadyAdded = isAlreadyAdded(img);
                return (
                  <div key={img.id}
                    onClick={() => {
                      if (alreadyAdded) return;
                      multiSelect ? toggleMulti(img.id) : setSelected(img.id === selected ? null : img.id);
                    }}
                    className={cn(
                      'group relative aspect-square cursor-pointer rounded-xl overflow-hidden border transition-all',
                      alreadyAdded ? 'opacity-40 cursor-not-allowed' : '',
                      !multiSelect && !alreadyAdded && (isSelected
                        ? 'ring-2 ring-primary ring-offset-2'
                        : 'hover:shadow-md hover:border-foreground/20')
                    )}>
                    <div className="w-full h-full flex items-center justify-center bg-muted">
                      <img src={img.url} alt={img.name} className="w-full h-full object-contain p-1.5" />
                    </div>
                    {/* Selected checkmark */}
                    {isSelected && !alreadyAdded && (
                      <div className="absolute top-1.5 right-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-primary shadow-sm">
                        <Check className="h-3 w-3 text-white" />
                      </div>
                    )}
                    {/* Already added badge */}
                    {alreadyAdded && (
                      <div className="absolute inset-0 flex items-center justify-center bg-black/30">
                        <span className="text-xs text-white font-medium bg-black/50 px-2 py-1 rounded">已添加</span>
                      </div>
                    )}
                    {/* Multi-select order number */}
                    {multiSelect && isSelected && !alreadyAdded && (
                      <div className="absolute top-1.5 left-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-primary/90 text-[10px] text-white font-medium">
                        {[...multiSelected].indexOf(img.id) + 1}
                      </div>
                    )}
                    {/* Bottom info */}
                    <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-1.5 pt-6">
                      <p className="text-[10px] text-white truncate">{img.name}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t px-5 py-3">
          {multiSelect && multiSelected.size > 0 && (
            <span className="mr-auto text-xs text-primary font-medium">已选 {multiSelected.size} 张</span>
          )}
          <button onClick={onClose}
            className="rounded-lg border bg-background px-4 py-2 text-sm font-medium hover:bg-accent transition-colors">
            取消
          </button>
          {multiSelect ? (
            <button onClick={handleConfirm} disabled={multiSelected.size === 0}
              className={cn(
                'rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                multiSelected.size > 0
                  ? 'bg-primary text-white hover:bg-primary/90 shadow-sm'
                  : 'bg-muted text-muted-foreground cursor-not-allowed'
              )}>
              确认选择 ({multiSelected.size})
            </button>
          ) : (
            <button onClick={handleConfirm} disabled={!selected}
              className={cn(
                'rounded-lg px-4 py-2 text-sm font-medium transition-colors',
                selected
                  ? 'bg-primary text-white hover:bg-primary/90 shadow-sm'
                  : 'bg-muted text-muted-foreground cursor-not-allowed'
              )}>
              确认选择
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
