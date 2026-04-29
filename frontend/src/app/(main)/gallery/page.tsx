'use client';

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { cn } from '@/lib/utils';
import {
  Search, Upload, LayoutGrid, Grid3X3, Download, Trash2, Heart,
  Eye, ChevronLeft, ChevronRight, Loader2, CloudDownload,
  Car, FileImage, Palette, X, Check, ImagePlus,
  Sparkles, Edit3, Tag,
} from 'lucide-react';
import { carModelsApi } from '@/services/carModelsApi';
import { editorApi } from '@/services/editorApi';

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
  /** AI 生图元数据（模版库专用） */
  aiMeta?: {
    prompt?: string;
    ref_images?: string[];
    model?: string;
    size?: string;
    style?: string;
    count?: number;
    quality?: string;
  } | null;
  // Car model specific fields
  brand?: string;
  model?: string;
  angle?: string;
  // Draft specific
  liked?: boolean;
  createdAt?: string;
  format?: string;
  /** 模版标签（大字报 / 汽车报价单图 / 汽车产品主图） */
  tags?: string[] | null;
}

type FolderKey = 'drafts' | 'templates' | 'car-models';
type TemplateSubKey = string; // 用户可自定义文件夹名称

function getUserScopedStorageKey(base: string): string {
  try {
    const raw = localStorage.getItem('app_current_user');
    if (raw) {
      const u = JSON.parse(raw) as { id?: number; username?: string };
      if (u?.id != null) return `${base}:uid:${u.id}`;
      if (u?.username) return `${base}:user:${u.username}`;
    }
  } catch {
    // ignore
  }
  return `${base}:guest`;
}

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
  const [templateSubFolder, setTemplateSubFolder] = useState<TemplateSubKey>('');
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

  // Pagination for drafts/templates (load more on demand)
  const [draftPage, setDraftPage] = useState(1);
  const [draftHasMore, setDraftHasMore] = useState(false);
  const [loadingMoreDrafts, setLoadingMoreDrafts] = useState(false);
  const [templatePage, setTemplatePage] = useState(1);
  const [templateHasMore, setTemplateHasMore] = useState(false);
  const [loadingMoreTemplates, setLoadingMoreTemplates] = useState(false);

  // Storage usage
  const [storageUsedMB, setStorageUsedMB] = useState(0);
  const [storagePercent, setStoragePercent] = useState(0);
  const [storageLoading, setStorageLoading] = useState(true);

  // Fetch all data on mount (first page only, load more on demand)
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        // Drafts: exclude template category
        const res = await editorApi.getMaterials(undefined, 1, 50, true, 'ai-template');
        const drafts: GalleryImage[] = (res.data.items || []).map(m => ({
          id: m.id,
          name: m.name,
          url: m.url || '',
          width: m.width || 1200,
          height: m.height || 800,
          folder: 'drafts' as const,
          isDesign: m.type === 'design',
          designJson: m.design_json,
          aiMeta: m.ai_meta,
          liked: false,
          createdAt: m.created_at,
          format: m.type,
        }));
        setDraftImages(drafts);
        setDraftHasMore(res.data.items.length === 50);
        setDraftPage(1);

        // Templates: first page of user's templates
        const tRes = await editorApi.getMaterials('ai-template', 1, 50, true);
        const tItems = (tRes.data.items || []).filter(m => m.type === 'template' || m.type === 'image' || m.type === 'design');
        const templates: GalleryImage[] = tItems.map(m => ({
          id: m.id,
          name: m.name,
          url: m.url || '',
          width: m.width || 2048,
          height: m.height || 2048,
          folder: 'templates' as const,
          aiMeta: m.ai_meta,
          createdAt: m.created_at,
          tags: m.tags || [],
        }));
        setTemplateImages(templates);
        setTemplateHasMore(tItems.length === 50);
        setTemplatePage(1);

        // Car models: fetch brands and initialize
        const brandsRes = await carModelsApi.getBrands();
        const brands = brandsRes.data.sort();
        setCarBrands(brands);
        if (brands.length > 0) {
          setSelectedBrand(brands[0]);
          const modelsRes = await carModelsApi.getModels(brands[0]);
          setCarModels(modelsRes.data);
          setSelectedModel('all');
          await fetchCarImages(brands[0]);
        }
      } catch (e) {
        console.error('Failed to fetch gallery data:', e);
      } finally {
        setLoading(false);
      }

      // Storage usage (independent of gallery data)
      try {
        const usage = await editorApi.getStorageUsage();
        setStorageUsedMB(usage.data.used_mb);
        setStoragePercent(usage.data.percent);
      } catch (e) {
        console.error('Failed to fetch storage usage:', e);
      } finally {
        setStorageLoading(false);
      }
    };
    fetchData();
  }, []);

  /* Load more drafts */
  const loadMoreDrafts = async () => {
    setLoadingMoreDrafts(true);
    try {
      const nextPage = draftPage + 1;
      const res = await editorApi.getMaterials(undefined, nextPage, 50, true, 'ai-template');
      const newDrafts: GalleryImage[] = (res.data.items || []).map(m => ({
        id: m.id, name: m.name, url: m.url || '',
        width: m.width || 1200, height: m.height || 800,
        folder: 'drafts' as const, isDesign: m.type === 'design',
        designJson: m.design_json, aiMeta: m.ai_meta,
        liked: false, createdAt: m.created_at, format: m.type,
      }));
      setDraftImages(prev => [...prev, ...newDrafts]);
      setDraftHasMore(res.data.items.length === 50);
      setDraftPage(nextPage);
    } catch (e) { console.error('Failed to load more drafts:', e); }
    finally { setLoadingMoreDrafts(false); }
  };

  /* Load more templates */
  const loadMoreTemplates = async () => {
    setLoadingMoreTemplates(true);
    try {
      const nextPage = templatePage + 1;
      const res = await editorApi.getMaterials('ai-template', nextPage, 50, true);
      const tItems = (res.data.items || []).filter(m => m.type === 'template' || m.type === 'image' || m.type === 'design');
      const newTemplates: GalleryImage[] = tItems.map(m => ({
        id: m.id, name: m.name, url: m.url || '',
        width: m.width || 2048, height: m.height || 2048,
        folder: 'templates' as const, aiMeta: m.ai_meta,
        createdAt: m.created_at, tags: m.tags || [],
      }));
      setTemplateImages(prev => [...prev, ...newTemplates]);
      setTemplateHasMore(tItems.length === 50);
      setTemplatePage(nextPage);
    } catch (e) { console.error('Failed to load more templates:', e); }
    finally { setLoadingMoreTemplates(false); }
  };

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
      // Filter by sub-folder tag
      if (templateSubFolder) {
        images = images.filter(img => img.tags && img.tags.includes(templateSubFolder));
      }
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
  }, [activeFolder, templateSubFolder, draftImages, templateImages, carImages, searchQuery]);

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

  const getTemplateSubCount = useCallback((tag: TemplateSubKey) => {
    if (!tag) return templateImages.length;
    return templateImages.filter(img => img.tags && img.tags.includes(tag)).length;
  }, [templateImages]);

  // 动态计算模版子分类（从 tags 中提取所有非空标签）
  // 用户手动创建的文件夹也合并进来
  // 用户手动创建的文件夹持久化到 localStorage
  const userFoldersStorageKey = getUserScopedStorageKey('user_created_folders');
  const [userCreatedFolders, setUserCreatedFolders] = useState<string[]>(() => {
    try {
      const stored = localStorage.getItem(userFoldersStorageKey);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });
  const [showNewFolderInput, setShowNewFolderInput] = useState(false);
  const [newFolderInput, setNewFolderInput] = useState('');

  const templateFolders = useMemo(() => {
    const folderSet = new Set<string>();
    // 先加入用户手动创建的文件夹
    for (const f of userCreatedFolders) {
      folderSet.add(f);
    }
    // 再从已有图片的 tags 中提取
    for (const img of templateImages) {
      for (const tag of (img.tags || [])) {
        if (tag) folderSet.add(tag);
      }
    }
    return Array.from(folderSet).sort();
  }, [templateImages, userCreatedFolders]);

  const handleCreateFolder = (name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    if (!templateFolders.includes(trimmed)) {
      setUserCreatedFolders(prev => {
        const next = [...prev, trimmed];
        localStorage.setItem(userFoldersStorageKey, JSON.stringify(next));
        return next;
      });
    }
    setTemplateSubFolder(trimmed);
  };

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

  const deleteDraft = async (id: number) => {
    if (!confirm('确定要删除这个素材吗？')) return;
    if (previewImg && String(previewImg.id) === String(id)) setPreviewImg(null);
    try {
      await editorApi.deleteMaterial(id);
      setDraftImages(prev => prev.filter(img => img.id !== id));
      setSelectedImages(prev => { const n = new Set(prev); n.delete(String(id)); return n; });
    } catch (err) {
      alert('删除失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
  };

  /** 删除模版 */
  const deleteTemplate = async (id: number) => {
    if (!confirm('确定要删除这个模版吗？')) return;
    if (previewImg && String(previewImg.id) === String(id)) setPreviewImg(null);
    try {
      await editorApi.deleteMaterial(id);
      setTemplateImages(prev => prev.filter(img => img.id !== id));
      setSelectedImages(prev => { const n = new Set(prev); n.delete(String(id)); return n; });
    } catch (err) {
      alert('删除失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
  };

  /** 打开设计稿到编辑器 */
  const openDesignInEditor = async (img: GalleryImage) => {
    if (!img.isDesign || !img.designJson) return;
    // 跳转到编辑器页面并携带设计数据
    const params = new URLSearchParams();
    params.set('designId', String(img.id));
    window.location.href = `/editor?${params.toString()}`;
  };

  /** 从模版库删除 */
  const handleDeleteTemplate = (img: GalleryImage) => {
    const tid = Number(img.id);
    if (!isNaN(tid)) deleteTemplate(tid);
  };

  /** 重新下载远程图片（用于修复过期链接） */
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const handleReDownload = async (img: GalleryImage) => {
    const tid = Number(img.id);
    if (isNaN(tid)) return;
    setDownloadingId(tid);
    try {
      const res = await editorApi.downloadRemoteImage(tid, img.url);
      if (res.data?.url) {
        // 更新本地状态为新的 URL
        setTemplateImages(prev => prev.map(t =>
          t.id === tid ? { ...t, url: res.data.url } : t
        ));
        // 同时更新预览中的图片
        setPreviewImg(prev =>
          prev && String(prev.id) === String(tid) ? { ...prev, url: res.data.url } : prev
        );
        alert('✅ 图片已下载到本地');
      }
    } catch (e) {
      const msg = (e as Error)?.message || '下载失败';
      alert('❌ ' + msg);
    } finally {
      setDownloadingId(null);
    }
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

  // Upload handler for templates
  const templateFileInputRef = useRef<HTMLInputElement>(null);
  const [pendingUploadId, setPendingUploadId] = useState<number | null>(null);

  const handleTemplateUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const res = await editorApi.uploadMaterial(file, 'templates');
      const m = res.data;
      // Show category selection modal
      setPendingUploadId(m.id);
      setPendingUploadName(m.name);
      setShowNewFolderInput(false);
      setNewFolderInput('');
      const newImg: GalleryImage = {
        id: m.id,
        name: m.name,
        url: m.url,
        width: m.width,
        height: m.height,
        folder: 'templates',
        createdAt: m.created_at,
        tags: [],
      };
      setTemplateImages(prev => [newImg, ...prev]);
    } catch (err) {
      alert('上传失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
    e.target.value = '';
  };

  const handleAssignTag = async (tag: TemplateSubKey) => {
    if (pendingUploadId === null) return;
    try {
      const tags = tag ? [tag] : [];
      await editorApi.updateMaterial(pendingUploadId, { tags });
      setTemplateImages(prev => prev.map(t =>
        t.id === pendingUploadId ? { ...t, tags } : t
      ));
    } catch (err) {
      // Silently fail — image is still uploaded
    }
    setPendingUploadId(null);
    setNewFolderInput('');
    setShowNewFolderInput(false);
  };

  /** 编辑模版信息 */
  const [editingTemplate, setEditingTemplate] = useState<GalleryImage | null>(null);
  const [editName, setEditName] = useState('');
  const [editTag, setEditTag] = useState<TemplateSubKey>('');
  const [savingEdit, setSavingEdit] = useState(false);
  const [showEditNewFolderInput, setShowEditNewFolderInput] = useState(false);
  const [editNewFolderInput, setEditNewFolderInput] = useState('');

  /** 上传后选择分类 */
  const [pendingUploadName, setPendingUploadName] = useState('');

  /** 文件夹管理（重命名/删除） */
  const [folderAction, setFolderAction] = useState<{
    type: 'rename' | 'delete';
    name: string;
    newName: string;
    imageCount: number;
  } | null>(null);

  const handleRenameFolder = async () => {
    if (!folderAction || !folderAction.newName.trim()) return;
    try {
      await editorApi.renameFolder(folderAction.name, folderAction.newName.trim());
      // Update local state + persist
      setUserCreatedFolders(prev => {
        const next = prev.map(f => f === folderAction.name ? folderAction.newName.trim() : f);
        localStorage.setItem(userFoldersStorageKey, JSON.stringify(next));
        return next;
      });
      if (templateSubFolder === folderAction.name) {
        setTemplateSubFolder(folderAction.newName.trim());
      }
      setFolderAction(null);
      alert('✅ 文件夹已重命名');
    } catch (err) {
      alert('重命名失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
  };

  const handleDeleteFolder = async () => {
    if (!folderAction) return;
    try {
      await editorApi.deleteFolder(folderAction.name);
      // Update local state + persist
      setUserCreatedFolders(prev => {
        const next = prev.filter(f => f !== folderAction.name);
        localStorage.setItem(userFoldersStorageKey, JSON.stringify(next));
        return next;
      });
      if (templateSubFolder === folderAction.name) {
        setTemplateSubFolder('');
      }
      setFolderAction(null);
      alert('✅ 文件夹已删除，图片已移至未分类');
    } catch (err) {
      alert('删除失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
  };

  const openEditTemplate = (img: GalleryImage) => {
    setEditingTemplate(img);
    setEditName(img.name);
    const currentTag = img.tags?.find(t => ['大字报', '汽车报价单图', '汽车产品主图'].includes(t)) as TemplateSubKey || '';
    setEditTag(currentTag);
  };

  const handleSaveTemplateEdit = async () => {
    if (!editingTemplate) return;
    setSavingEdit(true);
    try {
      // Build new tags list: keep non-template tags, add current template tag
      const otherTags = (editingTemplate.tags || []).filter(t => !['大字报', '汽车报价单图', '汽车产品主图'].includes(t));
      const newTags = editTag ? [...otherTags, editTag] : otherTags;
      await editorApi.updateMaterial(Number(editingTemplate.id), {
        name: editName,
        tags: newTags,
      });
      // Update local state
      setTemplateImages(prev => prev.map(t =>
        t.id === editingTemplate.id ? { ...t, name: editName, tags: newTags } : t
      ));
      setPreviewImg(prev =>
        prev && String(prev.id) === String(editingTemplate.id) ? { ...prev, name: editName, tags: newTags } : prev
      );
      setEditingTemplate(null);
      alert('✅ 已更新');
    } catch (err) {
      alert('保存失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
    setSavingEdit(false);
  };

  return (
    <div className="flex h-full">
      {/* Hidden file input for upload */}
      <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleUpload} />
      {/* Hidden file input for template upload */}
      <input ref={templateFileInputRef} type="file" accept="image/*" className="hidden" onChange={handleTemplateUpload} />

      {/* ===== 左侧文件夹 ===== */}
      <div className="flex w-52 shrink-0 flex-col border-r bg-card">
        <div className="border-b px-4 py-4">
          <h2 className="text-sm font-semibold">我的图库</h2>
          <p className="text-xs text-muted-foreground mt-0.5">管理您的图片素材</p>
        </div>

        <nav className="flex-1 overflow-auto py-2">
          {FOLDERS.map(f => {
            const isActive = activeFolder === f.key;
            return (
              <div key={f.key}>
                <button
                  onClick={() => { setActiveFolder(f.key); setSelectedImages(new Set()); }}
                  className={cn(
                    'flex w-full items-center justify-between px-4 py-2.5 text-sm transition-colors',
                    isActive
                      ? 'bg-primary/10 text-primary font-medium'
                      : 'text-foreground hover:bg-accent'
                  )}
                >
                  <div className="flex items-center gap-2.5">
                    <span className={cn(isActive ? 'text-primary' : 'text-muted-foreground')}>
                      {f.icon}
                    </span>
                    <span className="truncate">{f.label}</span>
                  </div>
                  <span className={cn('text-xs', isActive ? 'text-primary/70' : 'text-muted-foreground')}>
                    {getFolderCount(f.key)}
                  </span>
                </button>
                {/* 模版库子分类 */}
                {f.key === 'templates' && isActive && (
                  <div className="ml-4 border-l-2 border-border pl-3 space-y-0.5 mt-0.5">
                    <button
                      onClick={() => setTemplateSubFolder('')}
                      className={cn(
                        'flex w-full items-center justify-between px-3 py-2 text-xs transition-colors rounded-r',
                        !templateSubFolder
                          ? 'text-primary font-medium'
                          : 'text-muted-foreground hover:text-foreground'
                      )}
                    >
                      <span>全部</span>
                      <span className={cn(!templateSubFolder ? 'text-primary/70' : 'text-muted-foreground/60')}>
                        {getTemplateSubCount('')}
                      </span>
                    </button>
                    {templateFolders.map(sub => (
                      <div key={sub} className="group/folder relative">
                        <button
                          onClick={() => setTemplateSubFolder(sub)}
                          className={cn(
                            'flex w-full items-center justify-between px-3 py-2 text-xs transition-colors rounded-r',
                            templateSubFolder === sub
                              ? 'text-primary font-medium'
                              : 'text-muted-foreground hover:text-foreground'
                          )}
                        >
                          <span className="truncate">{sub}</span>
                          <span className={cn(templateSubFolder === sub ? 'text-primary/70' : 'text-muted-foreground/60')}>
                            {getTemplateSubCount(sub)}
                          </span>
                        </button>
                        {/* Hover actions */}
                        <div className="absolute right-1 top-1/2 -translate-y-1/2 hidden group-hover/folder:flex items-center gap-0.5">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setFolderAction({
                                type: 'rename',
                                name: sub,
                                newName: sub,
                                imageCount: getTemplateSubCount(sub),
                              });
                            }}
                            className="h-5 w-5 flex items-center justify-center rounded text-muted-foreground hover:text-primary hover:bg-accent"
                            title="重命名"
                          >
                            <Edit3 className="h-3 w-3" />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setFolderAction({
                                type: 'delete',
                                name: sub,
                                newName: '',
                                imageCount: getTemplateSubCount(sub),
                              });
                            }}
                            className="h-5 w-5 flex items-center justify-center rounded text-muted-foreground hover:text-red-500 hover:bg-accent"
                            title="删除文件夹"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                      </div>
                    ))}
                    {/* 新建文件夹输入框 */}
                    {showNewFolderInput ? (
                      <div className="flex items-center gap-1 px-2 py-1">
                        <input
                          autoFocus
                          value={newFolderInput}
                          onChange={(e) => setNewFolderInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && newFolderInput.trim()) {
                              handleCreateFolder(newFolderInput.trim());
                              setNewFolderInput('');
                              setShowNewFolderInput(false);
                            }
                            if (e.key === 'Escape') {
                              setNewFolderInput('');
                              setShowNewFolderInput(false);
                            }
                          }}
                          placeholder="文件夹名称"
                          className="flex-1 h-7 rounded-md border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary/30"
                        />
                        <button
                          onClick={() => {
                            if (newFolderInput.trim()) {
                              handleCreateFolder(newFolderInput.trim());
                              setNewFolderInput('');
                            }
                            setShowNewFolderInput(false);
                          }}
                          className="h-7 w-7 flex items-center justify-center rounded-md bg-primary text-white hover:bg-primary/90"
                        >
                          <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                        </button>
                        <button
                          onClick={() => { setNewFolderInput(''); setShowNewFolderInput(false); }}
                          className="h-7 w-7 flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setShowNewFolderInput(true)}
                        className="flex w-full items-center gap-1.5 px-3 py-2 text-xs text-muted-foreground hover:text-primary transition-colors rounded-r"
                      >
                        <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
                        新建文件夹
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {/* Storage info */}
        <div className="border-t p-4">
          <div className="text-xs text-muted-foreground mb-2">存储空间</div>
          {storageLoading ? (
            <div className="h-1.5 rounded-full bg-muted animate-pulse" />
          ) : (
            <>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded-full transition-all',
                    storagePercent > 90 ? 'bg-red-500' :
                    storagePercent > 70 ? 'bg-amber-500' :
                    'bg-primary'
                  )}
                  style={{ width: `${Math.min(storagePercent, 100)}%` }}
                />
              </div>
              <div className="mt-1.5 text-xs text-muted-foreground">
                {storageUsedMB >= 1024
                  ? `${(storageUsedMB / 1024).toFixed(1)} GB`
                  : `${storageUsedMB} MB`}
                {' '}
                / 5 GB
                {storagePercent > 0 && (
                  <span className="ml-1 text-primary/70">({storagePercent}%)</span>
                )}
              </div>
            </>
          )}
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
            {activeFolder === 'templates' && (
              <button
                onClick={() => templateFileInputRef.current?.click()}
                className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-primary/90"
              >
                <Upload className="h-3.5 w-3.5" />导入图片
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
                {activeFolder === 'drafts' ? '上传或生成第一张图片' : activeFolder === 'templates' ? '从 AI 生图保存或手动导入图片' : '暂无数据'}
              </p>
              {activeFolder === 'drafts' && (
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-white hover:bg-primary/90 transition-colors"
                >
                  <Upload className="h-3.5 w-3.5" />上传图片
                </button>
              )}
              {activeFolder === 'templates' && (
                <button
                  onClick={() => templateFileInputRef.current?.click()}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-white hover:bg-primary/90 transition-colors"
                >
                  <Upload className="h-3.5 w-3.5" />导入图片
                </button>
              )}
            </div>
          ) : viewMode === 'grid' ? (
            <>
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
                  {/* AI 模版标识 */}
                  {activeFolder === 'templates' && img.aiMeta && (
                    <div className="absolute top-2 right-2 flex items-center gap-1 px-1.5 py-0.5 rounded bg-purple-600/90 text-white text-[9px] font-medium">
                      <Sparkles className="h-2.5 w-2.5" />
                      <span>AI 模版</span>
                    </div>
                  )}
                  {/* 普通模版标识（手动导入） */}
                  {activeFolder === 'templates' && !img.aiMeta && (
                    <div className="absolute top-2 right-2 flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-600/90 text-white text-[9px] font-medium">
                      <ImagePlus className="h-2.5 w-2.5" />
                      <span>导入</span>
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
                    {activeFolder === 'templates' && img.tags && img.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {img.tags.filter(t => ['大字报', '汽车报价单图', '汽车产品主图'].includes(t)).map(tag => (
                          <span key={tag} className="text-[9px] bg-white/20 text-white px-1 py-0.5 rounded">{tag}</span>
                        ))}
                      </div>
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
                  {/* 模版快速操作按钮 */}
                  {activeFolder === 'templates' && (
                    <div className="absolute bottom-8 left-0 right-0 flex justify-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          openEditTemplate(img);
                        }}
                        className="flex items-center gap-1 rounded-md bg-blue-500 px-2 py-1 text-[10px] text-white font-medium shadow-sm hover:bg-blue-600"
                      >
                        <Edit3 className="h-2.5 w-2.5" />编辑
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteTemplate(img);
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
              {/* Load more button */}
              {activeFolder === 'drafts' && draftHasMore && (
                <div className="flex justify-center pt-4">
                  <button
                    onClick={loadMoreDrafts}
                    disabled={loadingMoreDrafts}
                    className="flex items-center gap-2 rounded-lg border px-4 py-2 text-xs font-medium hover:bg-accent disabled:opacity-50"
                  >
                    {loadingMoreDrafts ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                    加载更多
                  </button>
                </div>
              )}
              {activeFolder === 'templates' && templateHasMore && (
                <div className="flex justify-center pt-4">
                  <button
                    onClick={loadMoreTemplates}
                    disabled={loadingMoreTemplates}
                    className="flex items-center gap-2 rounded-lg border px-4 py-2 text-xs font-medium hover:bg-accent disabled:opacity-50"
                  >
                    {loadingMoreTemplates ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                    加载更多
                  </button>
                </div>
              )}
            </>
          ) : (
            <>
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
              {/* Load more button */}
              {activeFolder === 'drafts' && draftHasMore && (
                <div className="flex justify-center pt-4">
                  <button
                    onClick={loadMoreDrafts}
                    disabled={loadingMoreDrafts}
                    className="flex items-center gap-2 rounded-lg border px-4 py-2 text-xs font-medium hover:bg-accent disabled:opacity-50"
                  >
                    {loadingMoreDrafts ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                    加载更多
                  </button>
                </div>
              )}
              {activeFolder === 'templates' && templateHasMore && (
                <div className="flex justify-center pt-4">
                  <button
                    onClick={loadMoreTemplates}
                    disabled={loadingMoreTemplates}
                    className="flex items-center gap-2 rounded-lg border px-4 py-2 text-xs font-medium hover:bg-accent disabled:opacity-50"
                  >
                    {loadingMoreTemplates ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                    加载更多
                  </button>
                </div>
              )}
            </>
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
                {activeFolder === 'templates' && typeof previewImg.id === 'number' && (() => {
                  const tid = previewImg.id;
                  const isRemote = previewImg.url.startsWith('http://') || previewImg.url.startsWith('https://');
                  const isDownloading = downloadingId === tid;
                  return (
                    <>
                      <button onClick={() => openEditTemplate(previewImg)}
                        className="flex items-center justify-center gap-1.5 rounded-lg border py-2 px-3 text-xs font-medium text-blue-600 hover:bg-blue-50 transition-colors">
                        <Edit3 className="h-3.5 w-3.5" />编辑
                      </button>
                      {isRemote && (
                        <button onClick={() => handleReDownload(previewImg)} disabled={isDownloading}
                          className="flex items-center justify-center gap-1.5 rounded-lg border py-2 px-3 text-xs font-medium text-amber-600 hover:bg-amber-50 transition-colors disabled:opacity-50">
                          {isDownloading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CloudDownload className="h-3.5 w-3.5" />}
                          重新下载
                        </button>
                      )}
                      <button onClick={() => deleteTemplate(tid)} className="flex items-center justify-center gap-1.5 rounded-lg border py-2 px-3 text-xs font-medium text-red-600 hover:bg-red-50 transition-colors">
                        <Trash2 className="h-3.5 w-3.5" />删除
                      </button>
                    </>
                  );
                })()}
              </div>
              {/* AI 模版元数据展示 */}
              {activeFolder === 'templates' && previewImg.aiMeta && (
                <div className="mt-3 pt-3 border-t space-y-2.5">
                  {/* 提示词 */}
                  <div>
                    <div className="text-[10px] font-medium text-muted-foreground mb-1">提示词</div>
                    <div className="text-xs bg-muted/50 rounded-lg px-3 py-2 leading-relaxed break-words">
                      {previewImg.aiMeta.prompt || '无'}
                    </div>
                  </div>
                  {/* 参考图 */}
                  {previewImg.aiMeta.ref_images && previewImg.aiMeta.ref_images.length > 0 && (
                    <div>
                      <div className="text-[10px] font-medium text-muted-foreground mb-1">参考图</div>
                      <div className="flex gap-2">
                        {previewImg.aiMeta.ref_images.slice(0, 4).map((refUrl, idx) => (
                          <div key={idx} className="w-12 h-12 rounded-md overflow-hidden border bg-muted flex-shrink-0">
                            <img src={refUrl} alt={`参考图${idx + 1}`} className="w-full h-full object-cover" />
                          </div>
                        ))}
                        {previewImg.aiMeta.ref_images.length > 4 && (
                          <div className="w-12 h-12 rounded-md border bg-muted flex items-center justify-center flex-shrink-0">
                            <span className="text-[10px] text-muted-foreground">+{previewImg.aiMeta.ref_images.length - 4}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  {/* 参数标签 */}
                  <div className="flex flex-wrap gap-1.5">
                    {previewImg.aiMeta.model && (
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">{previewImg.aiMeta.model}</span>
                    )}
                    {previewImg.aiMeta.size && (
                      <span className="rounded-full bg-purple-50 px-2 py-0.5 text-[10px] font-medium text-purple-600">{previewImg.aiMeta.size}</span>
                    )}
                    {previewImg.aiMeta.style && (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-600">{previewImg.aiMeta.style}</span>
                    )}
                    {previewImg.aiMeta.quality && (
                      <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium',
                        previewImg.aiMeta.quality === 'high' ? 'bg-red-50 text-red-600' :
                        previewImg.aiMeta.quality === 'medium' ? 'bg-orange-50 text-orange-600' :
                        'bg-green-50 text-green-600'
                      )}>{previewImg.aiMeta.quality === 'high' ? '高质量' : previewImg.aiMeta.quality === 'medium' ? '中质量' : '低质量'}</span>
                    )}
                  </div>
                </div>
              )}
              <div className="flex items-center gap-4 mt-3 pt-3 border-t text-[10px] text-muted-foreground">
                <span><kbd className="font-mono bg-muted px-1 rounded">←</kbd> <kbd className="font-mono bg-muted px-1 rounded">→</kbd> 切换</span>
                <span><kbd className="font-mono bg-muted px-1 rounded">Esc</kbd> 关闭</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ===== 编辑模版信息弹窗 ===== */}
      {editingTemplate && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm" onClick={() => setEditingTemplate(null)}>
          <div onClick={(e) => e.stopPropagation()} className="flex flex-col max-w-md w-full mx-4">
            <div className="bg-card rounded-2xl border p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold">编辑模版信息</h3>
                <button onClick={() => setEditingTemplate(null)} className="flex h-7 w-7 items-center justify-center rounded-full text-muted-foreground hover:bg-accent transition-colors">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="space-y-4">
                {/* 名称 */}
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">名称</label>
                  <input value={editName} onChange={(e) => setEditName(e.target.value)}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
                </div>
                {/* 分类标签 */}
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">分类</label>
                  <div className="flex flex-wrap gap-2">
                    {templateFolders.map(tag => (
                      <button key={tag}
                        onClick={() => setEditTag(tag)}
                        className={cn(
                          'flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs transition-colors',
                          editTag === tag
                            ? 'border-primary bg-primary/5 text-primary font-medium'
                            : 'hover:border-foreground/20'
                        )}>
                        <Tag className="h-3.5 w-3.5" />
                        {tag}
                      </button>
                    ))}
                    {showEditNewFolderInput ? (
                      <div className="flex items-center gap-1">
                        <input
                          autoFocus
                          value={editNewFolderInput}
                          onChange={(e) => setEditNewFolderInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && editNewFolderInput.trim()) {
                              handleCreateFolder(editNewFolderInput.trim());
                              setEditTag(editNewFolderInput.trim());
                              setShowEditNewFolderInput(false);
                              setEditNewFolderInput('');
                            }
                            if (e.key === 'Escape') {
                              setShowEditNewFolderInput(false);
                              setEditNewFolderInput('');
                            }
                          }}
                          placeholder="名称"
                          className="w-20 h-8 rounded-lg border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary/30"
                        />
                        <button
                          onClick={() => {
                            if (editNewFolderInput.trim()) {
                              handleCreateFolder(editNewFolderInput.trim());
                              setEditTag(editNewFolderInput.trim());
                            }
                            setShowEditNewFolderInput(false);
                            setEditNewFolderInput('');
                          }}
                          className="h-8 px-2 rounded-lg bg-primary text-white text-xs hover:bg-primary/90"
                        >
                          确定
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setShowEditNewFolderInput(true)}
                        className="flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs text-muted-foreground hover:text-primary transition-colors"
                      >
                        <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
                        新建
                      </button>
                    )}
                  </div>
                </div>
                {/* 操作按钮 */}
                <div className="flex gap-2 justify-end pt-2">
                  <button onClick={() => setEditingTemplate(null)}
                    className="rounded-lg border px-4 py-2 text-xs font-medium text-muted-foreground hover:bg-accent transition-colors">
                    取消
                  </button>
                  <button onClick={handleSaveTemplateEdit} disabled={savingEdit}
                    className="rounded-lg bg-primary px-4 py-2 text-xs font-medium text-white hover:bg-primary/90 transition-colors disabled:opacity-50">
                    {savingEdit ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : '保存'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ===== 上传后选择分类弹窗 ===== */}
      {pendingUploadId !== null && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-[2px]" onClick={() => setPendingUploadId(null)}>
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-72 rounded-xl border bg-card shadow-2xl overflow-hidden"
          >
            {/* 头部 */}
            <div className="flex items-center justify-between px-4 py-3 border-b">
              <h3 className="text-sm font-semibold">归类到文件夹</h3>
              <button onClick={() => setPendingUploadId(null)} className="p-1 rounded hover:bg-accent transition-colors">
                <X className="h-4 w-4 text-muted-foreground" />
              </button>
            </div>
            <p className="text-xs text-muted-foreground px-4 pt-2.5 truncate">
              {pendingUploadName}
            </p>

            {/* 文件夹列表 */}
            <div className="max-h-60 overflow-auto px-2 py-2">
              {templateFolders.map(tag => (
                <button key={tag}
                  onClick={() => handleAssignTag(tag)}
                  className="w-full flex items-center justify-between rounded-lg px-3 py-2 text-sm transition-colors hover:bg-primary/5"
                >
                  <div className="flex items-center gap-2">
                    <Tag className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>{tag}</span>
                  </div>
                  <span className="text-xs text-muted-foreground/60">
                    {getTemplateSubCount(tag)}
                  </span>
                </button>
              ))}
            </div>

            {/* 底部：新建文件夹 */}
            <div className="border-t px-3 py-2">
              {showNewFolderInput ? (
                <div className="flex items-center gap-1">
                  <input
                    autoFocus
                    value={newFolderInput}
                    onChange={(e) => setNewFolderInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && newFolderInput.trim()) {
                        handleCreateFolder(newFolderInput.trim());
                        setPendingUploadId(null);
                      }
                      if (e.key === 'Escape') {
                        setNewFolderInput('');
                        setShowNewFolderInput(false);
                      }
                    }}
                    placeholder="输入名称..."
                    className="flex-1 h-7 rounded-md border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary/30"
                  />
                  <button
                    onClick={() => {
                      if (newFolderInput.trim()) {
                        handleCreateFolder(newFolderInput.trim());
                        setPendingUploadId(null);
                      }
                    }}
                    className="h-7 px-2 rounded-md bg-primary text-white text-xs hover:bg-primary/90"
                  >
                    确定
                  </button>
                  <button
                    onClick={() => { setNewFolderInput(''); setShowNewFolderInput(false); }}
                    className="h-7 w-7 flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setShowNewFolderInput(true)}
                  className="w-full flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs text-muted-foreground hover:text-primary transition-colors"
                >
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
                  新建文件夹
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ===== 文件夹操作弹窗（重命名/删除） ===== */}
      {folderAction && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-[2px]"
          onClick={() => setFolderAction(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className={cn(
              'rounded-xl border bg-card shadow-2xl overflow-hidden',
              folderAction.type === 'rename' ? 'w-72' : 'w-80'
            )}
          >
            {/* 头部 */}
            <div className="flex items-center justify-between px-4 py-3 border-b">
              <h3 className="text-sm font-semibold">
                {folderAction.type === 'rename' ? '重命名文件夹' : '删除文件夹'}
              </h3>
              <button
                onClick={() => setFolderAction(null)}
                className="p-1 rounded hover:bg-accent transition-colors"
              >
                <X className="h-4 w-4 text-muted-foreground" />
              </button>
            </div>

            {/* 内容 */}
            {folderAction.type === 'rename' ? (
              /* 重命名 */
              <div className="p-4 space-y-4">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">当前名称</label>
                  <div className="text-sm font-medium">{folderAction.name}</div>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">新名称</label>
                  <input
                    autoFocus
                    value={folderAction.newName}
                    onChange={(e) => setFolderAction(prev => prev ? { ...prev, newName: e.target.value } : null)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRenameFolder();
                      if (e.key === 'Escape') setFolderAction(null);
                    }}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                </div>
                <div className="flex gap-2 justify-end pt-1">
                  <button
                    onClick={() => setFolderAction(null)}
                    className="rounded-lg border px-4 py-2 text-xs font-medium text-muted-foreground hover:bg-accent"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleRenameFolder}
                    disabled={!folderAction.newName.trim() || folderAction.newName === folderAction.name}
                    className="rounded-lg bg-primary px-4 py-2 text-xs font-medium text-white hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    确认
                  </button>
                </div>
              </div>
            ) : (
              /* 删除 */
              <div className="p-4 space-y-3">
                <div className="flex items-center gap-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                  <svg className="h-5 w-5 text-amber-500 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                    <line x1="12" y1="9" x2="12" y2="13"/>
                    <line x1="12" y1="17" x2="12.01" y2="17"/>
                  </svg>
                  <div className="text-xs text-amber-700 dark:text-amber-400">
                    <div className="font-medium">文件夹「{folderAction.name}」</div>
                    <div>包含 {folderAction.imageCount} 个素材，删除后图片将移至未分类</div>
                  </div>
                </div>
                <div className="flex gap-2 justify-end pt-1">
                  <button
                    onClick={() => setFolderAction(null)}
                    className="rounded-lg border px-4 py-2 text-xs font-medium text-muted-foreground hover:bg-accent"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleDeleteFolder}
                    className="rounded-lg bg-red-500 px-4 py-2 text-xs font-medium text-white hover:bg-red-600"
                  >
                    删除
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
