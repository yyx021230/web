'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { cn } from '@/lib/utils';
import {
  Search, Upload, LayoutGrid, Grid3X3, Download, Trash2, Heart,
  Eye, ChevronLeft, ChevronRight, Loader2,
  Car, FileImage, Palette, X, Check, ImagePlus,
} from 'lucide-react';
import { carModelsApi } from '@/services/carModelsApi';
import { editorApi, type Material as BackendMaterial } from '@/services/editorApi';

// ===== Types =====
interface GalleryImage {
  id: number | string;
  name: string;
  url: string;
  width: number;
  height: number;
  folder: 'drafts' | 'templates' | 'car-models';
  /** 是否为编辑器设计稿 */
  isDesign?: boolean;
  /** 设计稿的完整 JSON（用于跳转编辑器时还原） */
  designJson?: Record<string, unknown> | null;
  // Car model specific fields
  brand?: string;
  model?: string;
  angle?: string;
  // Draft specific
  liked?: boolean;
  createdAt?: string;
  format?: string;
}

type FolderKey = 'drafts' | 'templates' | 'car-models';

const FOLDERS: { key: FolderKey; label: string; icon: React.ReactNode }[] = [
  { key: 'drafts', label: '草稿箱', icon: <FileImage className="h-4 w-4" /> },
  { key: 'templates', label: '模版库', icon: <Palette className="h-4 w-4" /> },
  { key: 'car-models', label: '车型库', icon: <Car className="h-4 w-4" /> },
];

// ===== Searchable Select Component =====
interface SearchableSelectProps {
  options: string[];
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
  emptyText?: string;
  className?: string;
}

function SearchableSelect({ options, value, onChange, placeholder = '请选择...', emptyText = '无匹配结果', className }: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Smart match: contains match for Chinese/English
  const filtered = options.filter(opt => {
    if (!query) return true;
    const q = query.toLowerCase();
    return opt.toLowerCase().includes(q);
  });

  // Limit displayed items
  const displayItems = filtered.slice(0, 20);
  const hasMore = filtered.length > 20;

  const displayValue = value || '';

  return (
    <div ref={wrapperRef} className={cn('relative', className)}>
      <div
        onClick={() => { setOpen(!open); setQuery(''); }}
        className={cn(
          'flex h-8 items-center justify-between rounded-lg border bg-background px-3 text-sm cursor-pointer transition-colors',
          open ? 'ring-2 ring-primary/30 border-primary' : 'hover:border-foreground/20'
        )}
      >
        <span className={cn('truncate', !value && 'text-muted-foreground')}>
          {displayValue || placeholder}
        </span>
        <svg className={cn('h-4 w-4 shrink-0 ml-2 transition-transform', open && 'rotate-180')} viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </div>

      {open && (
        <div className="absolute top-full mt-1 z-50 w-56 rounded-lg border bg-card shadow-lg overflow-hidden">
          {/* Search input */}
          <div className="p-2 border-b">
            <input
              autoFocus
              type="text"
              placeholder="搜索..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              className="w-full rounded-md border bg-background px-2.5 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>
          {/* Options list */}
          <div className="max-h-52 overflow-auto py-1">
            {displayItems.length === 0 ? (
              <div className="px-3 py-2 text-xs text-muted-foreground">{emptyText}</div>
            ) : (
              displayItems.map(opt => (
                <div
                  key={opt}
                  onClick={() => { onChange(opt); setOpen(false); setQuery(''); }}
                  className={cn(
                    'px-3 py-1.5 text-sm cursor-pointer transition-colors',
                    opt === value
                      ? 'bg-primary/10 text-primary font-medium'
                      : 'hover:bg-accent'
                  )}
                >
                  {opt}
                </div>
              ))
            )}
            {hasMore && (
              <div className="px-3 py-1 text-[10px] text-muted-foreground text-center border-t">
                还有 {filtered.length - 20} 项，请输入关键词搜索
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ===== Main Component =====
export default function GalleryPage() {
  const [activeFolder, setActiveFolder] = useState<FolderKey>('drafts');
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [selectedImages, setSelectedImages] = useState<Set<string>>(new Set());
  const [previewImg, setPreviewImg] = useState<GalleryImage | null>(null);

  // Data
  const [draftImages, setDraftImages] = useState<GalleryImage[]>([]);
  const [templateImages, setTemplateImages] = useState<GalleryImage[]>([]);
  const [carBrands, setCarBrands] = useState<string[]>([]);
  const [selectedBrand, setSelectedBrand] = useState<string>('');
  const [carModels, setCarModels] = useState<Record<string, string[]>>({});
  const [selectedModel, setSelectedModel] = useState<string>('all');
  const [carImages, setCarImages] = useState<GalleryImage[]>([]);
  const [carData, setCarData] = useState<Record<string, Record<string, { label: string; url: string }[]>> | null>(null);

  const [loading, setLoading] = useState(true);

  // Fetch all data on mount
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        // Drafts: fetch from editor API
        const allMaterials: BackendMaterial[] = [];
        let page = 1;
        let hasMore = true;
        while (hasMore) {
          const res = await editorApi.getMaterials(undefined, page, 50);
          allMaterials.push(...res.data.items);
          hasMore = res.data.items.length === 50;
          page++;
        }
        const drafts: GalleryImage[] = allMaterials.map(m => ({
          id: m.id,
          name: m.name,
          url: m.url || '',
          width: m.width || 1200,
          height: m.height || 800,
          folder: 'drafts' as const,
          isDesign: m.type === 'design',
          designJson: m.design_json,
          liked: false,
          createdAt: m.created_at,
          format: m.type,
        }));
        setDraftImages(drafts);

        // Templates: placeholder for now (can be extended later)
        setTemplateImages([]);

        // Car models: fetch brands and initialize
        const brandsRes = await carModelsApi.getBrands();
        const brands = brandsRes.data.sort();
        setCarBrands(brands);
        if (brands.length > 0) {
          setSelectedBrand(brands[0]);
          const modelsRes = await carModelsApi.getModels(brands[0]);
          setCarModels(modelsRes.data);
          // 默认选择"全部"车型
          setSelectedModel('all');
          await fetchCarImages(brands[0]);
        }
      } catch (e) {
        console.error('Failed to fetch gallery data:', e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  // Fetch car images when brand/model changes
  const fetchCarImages = async (brand: string, model?: string) => {
    try {
      const res = await carModelsApi.getCarImages(brand, model);
      const data = res.data;
      const images: GalleryImage[] = (data.images || []).map((img, idx) => ({
        id: `${data.brand}-${img.model || data.model}-${idx}`,
        name: `${data.brand} ${img.model || data.model} - ${img.label}`,
        url: img.url,
        width: 1920,
        height: 1080,
        folder: 'car-models' as const,
        brand: data.brand,
        model: img.model || data.model,
        angle: img.label,
      }));
      setCarImages(images);
    } catch (e) {
      console.error('Failed to fetch car images:', e);
      setCarImages([]);
    }
  };

  // Brand selection change
  const handleBrandChange = async (brand: string) => {
    setSelectedBrand(brand);
    setSelectedModel('all');
    setCarImages([]);
    try {
      const modelsRes = await carModelsApi.getModels(brand);
      setCarModels(modelsRes.data);
      await fetchCarImages(brand);
    } catch (e) {
      console.error('Failed to fetch models:', e);
    }
  };

  // Model selection change
  const handleModelChange = (model: string) => {
    setSelectedModel(model);
    if (selectedBrand && model) {
      // model 为 'all' 时不传，获取该品牌下所有车型
      fetchCarImages(selectedBrand, model === 'all' ? undefined : model);
    }
  };

  // Filtered images based on active folder and search
  const filteredImages = useCallback(() => {
    let images: GalleryImage[] = [];
    if (activeFolder === 'drafts') {
      images = draftImages;
    } else if (activeFolder === 'templates') {
      images = templateImages;
    } else {
      images = carImages;
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      images = images.filter(img =>
        img.name.toLowerCase().includes(q) ||
        img.brand?.toLowerCase().includes(q) ||
        img.model?.toLowerCase().includes(q) ||
        img.angle?.toLowerCase().includes(q)
      );
    }
    return images;
  }, [activeFolder, draftImages, templateImages, carImages, searchQuery]);

  const currentImages = filteredImages();

  // Selection
  const toggleSelect = (id: string, e?: React.MouseEvent) => {
    if (e && (e.ctrlKey || e.metaKey)) {
      const next = new Set(selectedImages);
      next.has(id) ? next.delete(id) : next.add(id);
      setSelectedImages(next);
    } else {
      setSelectedImages(prev => {
        const next = new Set(prev);
        next.has(id) ? next.delete(id) : next.add(id);
        return next;
      });
    }
  };

  const getFolderCount = useCallback((folder: FolderKey) => {
    if (folder === 'drafts') return draftImages.length;
    if (folder === 'templates') return templateImages.length;
    // For car models, show total across all brands
    if (carData) {
      let total = 0;
      for (const brands of Object.values(carData)) {
        for (const imgs of Object.values(brands)) {
          total += imgs.length;
        }
      }
      return total;
    }
    return carImages.length;
  }, [draftImages, templateImages, carImages, carData]);

  // Car models data for total count
  useEffect(() => {
    const loadCarData = async () => {
      try {
        const res = await carModelsApi.getAllData();
        setCarData(res.data);
      } catch (e) {
        // ignore
      }
    };
    loadCarData();
  }, []);

  // Keyboard shortcuts for preview
  useEffect(() => {
    if (!previewImg) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPreviewImg(null);
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const idx = currentImages.findIndex(img => String(img.id) === String(previewImg.id));
        if (e.key === 'ArrowLeft' && idx > 0) setPreviewImg(currentImages[idx - 1]);
        if (e.key === 'ArrowRight' && idx < currentImages.length - 1) setPreviewImg(currentImages[idx + 1]);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [previewImg, currentImages]);

  // Draft actions
  const toggleLike = (id: number) => {
    setDraftImages(prev => prev.map(img =>
      img.id === id ? { ...img, liked: !img.liked } : img
    ));
  };

  const deleteDraft = (id: number) => {
    if (!confirm('确定要删除这个素材吗？')) return;
    if (previewImg && String(previewImg.id) === String(id)) setPreviewImg(null);
    // 设计稿和普通图片删除逻辑一样
    editorApi.deleteMaterial(id).catch(() => {});
    setDraftImages(prev => prev.filter(img => img.id !== id));
    setSelectedImages(prev => { const n = new Set(prev); n.delete(String(id)); return n; });
  };

  /** 打开设计稿到编辑器 */
  const openDesignInEditor = async (img: GalleryImage) => {
    if (!img.isDesign || !img.designJson) return;
    // 跳转到编辑器页面并携带设计数据
    const params = new URLSearchParams();
    params.set('designId', String(img.id));
    window.location.href = `/editor?${params.toString()}`;
  };

  const deleteSelected = () => {
    if (activeFolder !== 'drafts') return;
    if (!confirm(`确定要删除选中的 ${selectedImages.size} 个素材吗？`)) return;
    selectedImages.forEach(idStr => {
      const id = Number(idStr);
      editorApi.deleteMaterial(id).catch(() => {});
    });
    setDraftImages(prev => prev.filter(img => !selectedImages.has(String(img.id))));
    setSelectedImages(new Set());
  };

  // Preview navigation
  const previewIdx = previewImg ? currentImages.findIndex(img => String(img.id) === String(previewImg.id)) : -1;
  const goPrev = () => { if (previewIdx > 0) setPreviewImg(currentImages[previewIdx - 1]); };
  const goNext = () => { if (previewIdx < currentImages.length - 1) setPreviewImg(currentImages[previewIdx + 1]); };

  // Upload handler for drafts
  const fileInputRef = useRef<HTMLInputElement>(null);
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const res = await editorApi.uploadMaterial(file);
      const m = res.data;
      const newImg: GalleryImage = {
        id: m.id,
        name: m.name,
        url: m.url,
        width: m.width,
        height: m.height,
        folder: 'drafts',
        liked: false,
        createdAt: m.created_at,
        format: m.type,
      };
      setDraftImages(prev => [newImg, ...prev]);
    } catch (err) {
      alert('上传失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
    e.target.value = '';
  };

  return (
    <div className="flex h-full">
      {/* Hidden file input for upload */}
      <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleUpload} />

      {/* ===== 左侧文件夹 ===== */}
      <div className="flex w-52 shrink-0 flex-col border-r bg-card">
        <div className="border-b px-4 py-4">
          <h2 className="text-sm font-semibold">我的图库</h2>
          <p className="text-xs text-muted-foreground mt-0.5">管理您的图片素材</p>
        </div>

        <nav className="flex-1 overflow-auto py-2">
          {FOLDERS.map(f => (
            <button
              key={f.key}
              onClick={() => { setActiveFolder(f.key); setSelectedImages(new Set()); }}
              className={cn(
                'flex w-full items-center justify-between px-4 py-2.5 text-sm transition-colors',
                activeFolder === f.key
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-foreground hover:bg-accent'
              )}
            >
              <div className="flex items-center gap-2.5">
                <span className={cn(activeFolder === f.key ? 'text-primary' : 'text-muted-foreground')}>
                  {f.icon}
                </span>
                <span className="truncate">{f.label}</span>
              </div>
              <span className={cn('text-xs', activeFolder === f.key ? 'text-primary/70' : 'text-muted-foreground')}>
                {getFolderCount(f.key)}
              </span>
            </button>
          ))}
        </nav>

        {/* Storage info */}
        <div className="border-t p-4">
          <div className="text-xs text-muted-foreground mb-2">存储空间</div>
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div className="h-full w-[35%] rounded-full bg-primary" />
          </div>
          <div className="mt-1.5 text-xs text-muted-foreground">3.2 GB / 10 GB</div>
        </div>
      </div>

      {/* ===== 主内容 ===== */}
      <div className="flex flex-1 flex-col">
        {/* 顶部工具栏 */}
        <div className="flex items-center justify-between border-b bg-card px-4 py-2.5">
          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                placeholder="搜索图片..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="rounded-lg border bg-background py-1.5 pl-9 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 w-64"
              />
            </div>
            {selectedImages.size > 0 && activeFolder === 'drafts' && (
              <div className="flex items-center gap-2 rounded-lg bg-primary/10 px-3 py-1.5">
                <Check className="h-4 w-4 text-primary" />
                <span className="text-xs font-medium text-primary">已选 {selectedImages.size} 张</span>
                <button onClick={deleteSelected} className="flex items-center gap-1 text-xs text-red-600 hover:underline ml-1">
                  <Trash2 className="h-3 w-3" />删除
                </button>
                <button onClick={() => setSelectedImages(new Set())} className="text-xs text-primary hover:underline ml-1">
                  取消
                </button>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {activeFolder === 'drafts' && (
              <button
                onClick={() => fileInputRef.current?.click()}
                className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-primary/90"
              >
                <Upload className="h-3.5 w-3.5" />上传
              </button>
            )}
            <div className="h-5 w-px bg-border" />
            <div className="flex items-center rounded-lg border p-0.5">
              <button
                onClick={() => setViewMode('grid')}
                className={cn('flex h-7 w-7 items-center justify-center rounded-md transition-colors', viewMode === 'grid' ? 'bg-accent' : '')}
              >
                <LayoutGrid className="h-4 w-4" />
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={cn('flex h-7 w-7 items-center justify-center rounded-md transition-colors', viewMode === 'list' ? 'bg-accent' : '')}
              >
                <Grid3X3 className="h-4 w-4 rotate-90" />
              </button>
            </div>
          </div>
        </div>

        {/* ===== 车型库筛选栏 ===== */}
        {activeFolder === 'car-models' && (
          <div className="flex items-center gap-3 border-b bg-card px-4 py-2.5">
            <span className="text-xs text-muted-foreground whitespace-nowrap">品牌:</span>
            <SearchableSelect
              options={carBrands}
              value={selectedBrand}
              onChange={handleBrandChange}
              placeholder="选择品牌..."
              emptyText="无匹配品牌"
            />
            <span className="text-xs text-muted-foreground whitespace-nowrap">车型:</span>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => handleModelChange('all')}
                className={cn(
                  'px-2.5 py-1 text-xs rounded-lg border transition-colors',
                  selectedModel === 'all'
                    ? 'bg-primary text-primary-foreground border-primary font-medium'
                    : 'hover:border-primary/50 text-muted-foreground'
                )}
              >
                全部
              </button>
              <span className="text-xs text-muted-foreground">|</span>
              <SearchableSelect
                options={carModels[selectedBrand] || []}
                value={selectedModel === 'all' ? '' : selectedModel}
                onChange={(v) => handleModelChange(v)}
                placeholder="选择车型..."
                emptyText="无匹配车型"
                className="min-w-[140px]"
              />
            </div>
            <span className="text-xs text-muted-foreground ml-2">
              {carImages.length} 张图片{selectedModel === 'all' ? '（全部车型）' : '（5角度）'}
            </span>
          </div>
        )}

        {/* ===== 图片列表区域 ===== */}
        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <Loader2 className="h-10 w-10 animate-spin text-primary mb-3" />
              <p className="text-sm text-muted-foreground">加载素材中...</p>
            </div>
          ) : currentImages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <ImagePlus className="h-12 w-12 text-muted-foreground/30 mb-4" />
              <h3 className="text-sm font-medium mb-1">
                {activeFolder === 'drafts' ? '暂无草稿' : activeFolder === 'templates' ? '暂无模版' : '暂无数据'}
              </h3>
              <p className="text-xs text-muted-foreground mb-4">
                {activeFolder === 'drafts' ? '上传或生成第一张图片' : '内容即将上线'}
              </p>
              {activeFolder === 'drafts' && (
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-white hover:bg-primary/90 transition-colors"
                >
                  <Upload className="h-3.5 w-3.5" />上传图片
                </button>
              )}
            </div>
          ) : viewMode === 'grid' ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
              {currentImages.map(img => (
                <div
                  key={String(img.id)}
                  className={cn(
                    'group relative aspect-square cursor-pointer rounded-xl overflow-hidden border transition-all',
                    selectedImages.has(String(img.id))
                      ? 'ring-2 ring-primary ring-offset-2'
                      : 'hover:shadow-md'
                  )}
                >
                  {/* 点击：设计稿跳转到编辑器，普通图片打开预览 */}
                  <div
                    onClick={() => {
                      if (img.isDesign) {
                        openDesignInEditor(img);
                      } else {
                        setPreviewImg(img);
                      }
                    }}
                    className="w-full h-full flex items-center justify-center bg-muted"
                  >
                    {img.isDesign && img.url ? (
                      <img src={img.url} alt={img.name} className="w-full h-full object-contain p-2" />
                    ) : img.isDesign ? (
                      <div className="flex flex-col items-center justify-center text-muted-foreground">
                        <Palette className="h-8 w-8 mb-1 opacity-30" />
                        <span className="text-[10px] opacity-50">{img.name}</span>
                      </div>
                    ) : (
                      <img src={img.url} alt={img.name} className="w-full h-full object-contain p-2" />
                    )}
                  </div>
                  {/* 设计稿标识 */}
                  {img.isDesign && (
                    <div className="absolute top-2 right-2 flex items-center gap-1 px-1.5 py-0.5 rounded bg-primary/90 text-white text-[9px] font-medium">
                      <Palette className="h-2.5 w-2.5" />
                      <span>设计稿</span>
                    </div>
                  )}
                  {/* Checkbox (only for drafts, not designs) */}
                  {activeFolder === 'drafts' && !img.isDesign && (
                    <label
                      onClick={(e) => { e.stopPropagation(); toggleSelect(String(img.id), e); }}
                      className="absolute top-2 left-2 z-10"
                    >
                      <div className={cn(
                        'flex h-5 w-5 items-center justify-center rounded border transition-all cursor-pointer',
                        selectedImages.has(String(img.id))
                          ? 'bg-primary border-primary shadow-sm'
                          : 'bg-white/70 border-white/50 opacity-0 group-hover:opacity-100'
                      )}>
                        {selectedImages.has(String(img.id)) && <Check className="h-3 w-3 text-white" />}
                      </div>
                    </label>
                  )}
                  {/* Bottom info */}
                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-2 pt-6">
                    <p className="text-xs text-white truncate">{img.name}</p>
                    {img.angle && (
                      <p className="text-[10px] text-white/70">{img.angle}</p>
                    )}
                    {img.isDesign && (
                      <p className="text-[10px] text-primary/80">点击打开编辑</p>
                    )}
                  </div>
                  {/* 设计稿快速操作按钮 */}
                  {img.isDesign && (
                    <div className="absolute bottom-8 left-0 right-0 flex justify-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={(e) => { e.stopPropagation(); openDesignInEditor(img); }}
                        className="flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-[10px] text-white font-medium shadow-sm hover:bg-primary/90"
                      >
                        <Palette className="h-2.5 w-2.5" />打开编辑
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          const draftId = Number(img.id);
                          deleteDraft(draftId);
                        }}
                        className="flex items-center gap-1 rounded-md bg-red-500 px-2 py-1 text-[10px] text-white font-medium shadow-sm hover:bg-red-600"
                      >
                        <Trash2 className="h-2.5 w-2.5" />删除
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-1">
              {currentImages.map(img => (
                <div
                  key={String(img.id)}
                  className="flex items-center gap-3 rounded-lg border bg-card px-3 py-2 hover:bg-accent/50 transition-colors"
                >
                  {/* Checkbox (only for drafts) */}
                  {activeFolder === 'drafts' && (
                    <label onClick={(e) => e.stopPropagation()} className="shrink-0 cursor-pointer">
                      <div className={cn(
                        'flex h-5 w-5 items-center justify-center rounded border transition-all',
                        selectedImages.has(String(img.id)) ? 'bg-primary border-primary' : 'border-muted-foreground/30'
                      )}>
                        {selectedImages.has(String(img.id)) && <Check className="h-3 w-3 text-white" />}
                      </div>
                      <input type="checkbox" className="sr-only" checked={selectedImages.has(String(img.id))} onChange={() => toggleSelect(String(img.id))} />
                    </label>
                  )}
                  <div
                    onClick={() => setPreviewImg(img)}
                    className="h-12 w-12 rounded-md shrink-0 cursor-pointer hover:opacity-80 transition-opacity flex items-center justify-center bg-muted"
                  >
                    <img src={img.url} alt={img.name} className="w-8 h-8 object-contain" />
                  </div>
                  <div className="flex-1 min-w-0 cursor-pointer" onClick={() => setPreviewImg(img)}>
                    <p className="text-sm font-medium truncate">{img.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {img.brand && `${img.brand} · `}{img.width}×{img.height}
                      {img.angle && ` · ${img.angle}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    <button onClick={() => setPreviewImg(img)} className="p-1.5 rounded hover:bg-background/50 text-muted-foreground" title="预览">
                      <Eye className="h-3.5 w-3.5" />
                    </button>
                    <button onClick={() => {
                      const a = document.createElement('a');
                      a.href = img.url;
                      a.download = img.name + '.jpg';
                      a.click();
                    }} className="p-1.5 rounded hover:bg-background/50 text-muted-foreground" title="下载">
                      <Download className="h-3.5 w-3.5" />
                    </button>
                    {activeFolder === 'drafts' && typeof img.id === 'number' && (() => {
                        const draftId = img.id;
                        return (
                          <>
                            <button onClick={() => toggleLike(draftId)} className={cn('p-1.5 rounded hover:bg-background/50', img.liked ? 'text-red-500' : 'text-muted-foreground')} title="收藏">
                              <Heart className={cn('h-3.5 w-3.5', img.liked && 'fill-current')} />
                            </button>
                            <button onClick={() => deleteDraft(draftId)} className="p-1.5 rounded hover:bg-red-50 text-muted-foreground hover:text-red-600" title="删除">
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </>
                        );
                      })()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ===== 图片预览弹窗 ===== */}
      {previewImg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm" onClick={() => setPreviewImg(null)}>
          <button onClick={() => setPreviewImg(null)} className="absolute top-4 right-4 z-10 flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors">
            <X className="h-5 w-5" />
          </button>
          {previewIdx > 0 && (
            <button onClick={(e) => { e.stopPropagation(); goPrev(); }} className="absolute left-4 z-10 flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors">
              <ChevronLeft className="h-5 w-5" />
            </button>
          )}
          {previewIdx < currentImages.length - 1 && (
            <button onClick={(e) => { e.stopPropagation(); goNext(); }} className="absolute right-4 z-10 flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 transition-colors">
              <ChevronRight className="h-5 w-5" />
            </button>
          )}
          <div onClick={(e) => e.stopPropagation()} className="flex flex-col max-w-4xl max-h-[90vh] w-full mx-4">
            <div className="flex-1 flex items-center justify-center rounded-t-2xl overflow-hidden bg-muted" style={{ minHeight: 300 }}>
              <img src={previewImg.url} alt={previewImg.name} className="max-w-full max-h-[60vh] object-contain" />
            </div>
            <div className="bg-card rounded-b-2xl border border-t-0 p-4">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="text-sm font-semibold">{previewImg.name}</h3>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {previewImg.brand && `${previewImg.brand} · `}
                    {previewImg.angle && `${previewImg.angle} · `}
                    {previewImg.width}×{previewImg.height}
                  </p>
                </div>
                {activeFolder === 'drafts' && typeof previewImg.id === 'number' && (() => {
                  const draftId = previewImg.id;
                  const liked = previewImg.liked;
                  return (
                    <button onClick={() => toggleLike(draftId)} className={cn('flex h-8 w-8 items-center justify-center rounded-full transition-colors', liked ? 'bg-red-50 text-red-500' : 'bg-muted text-muted-foreground hover:bg-red-50 hover:text-red-500')}>
                      <Heart className={cn('h-4 w-4', liked && 'fill-current')} />
                    </button>
                  );
                })()}
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => {
                  const a = document.createElement('a');
                  a.href = previewImg.url;
                  a.download = previewImg.name + '.jpg';
                  a.click();
                }} className="flex-1 flex items-center justify-center gap-1.5 rounded-lg bg-primary py-2 text-xs font-medium text-white hover:bg-primary/90 transition-colors">
                  <Download className="h-3.5 w-3.5" />下载原图
                </button>
                {activeFolder === 'drafts' && typeof previewImg.id === 'number' && (() => {
                  const draftId = previewImg.id;
                  return (
                    <button onClick={() => deleteDraft(draftId)} className="flex items-center justify-center gap-1.5 rounded-lg border py-2 px-3 text-xs font-medium text-red-600 hover:bg-red-50 transition-colors">
                      <Trash2 className="h-3.5 w-3.5" />删除
                    </button>
                  );
                })()}
              </div>
              <div className="flex items-center gap-4 mt-3 pt-3 border-t text-[10px] text-muted-foreground">
                <span><kbd className="font-mono bg-muted px-1 rounded">←</kbd> <kbd className="font-mono bg-muted px-1 rounded">→</kbd> 切换</span>
                <span><kbd className="font-mono bg-muted px-1 rounded">Esc</kbd> 关闭</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
