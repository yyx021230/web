'use client';

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { adminApi } from '@/services/adminApi';
import { toast } from '@/lib/toast';
import { Trash2, Search, Eye, CheckSquare, Square, Filter, Save, Upload, Download, FolderUp } from 'lucide-react';
import { cn } from '@/lib/utils';

interface GalleryItem {
  id: number;
  name: string;
  url: string | null;
  width: number;
  height: number;
  type?: string;
  category?: string | null;
  tags?: string[];
  ai_meta?: Record<string, unknown> | null;
  created_by?: number | null;
  created_by_name?: string | null;
  created_at: string;
}

interface CarImageItem {
  label: string;
  url: string;
}

type CarModelsData = Record<string, Record<string, CarImageItem[]>>;
type ImportMethod = 'ocr' | 'gptimage2';
type ImportBrandMode = 'existing' | 'new';
type ImportResult = {
  brand: string;
  model: string;
  already_cleaned: boolean;
  clean_method: string | null;
  overwrite: boolean;
  imported_angles: string[];
  missing_angles: string[];
  warnings: string[];
  images: CarImageItem[];
  backup_file: string;
};
type DirectoryPickerWindow = Window & {
  showDirectoryPicker?: () => Promise<FileSystemDirectoryHandle>;
};

type FileSystemDirectoryHandle = {
  values: () => AsyncIterable<FileSystemHandle>;
};

type FileSystemFileHandle = {
  kind: 'file';
  name: string;
  getFile: () => Promise<File>;
};

type FileSystemDirectoryEntryHandle = {
  kind: 'directory';
  name: string;
  values: () => AsyncIterable<FileSystemHandle>;
};

type FileSystemHandle = FileSystemDirectoryEntryHandle | FileSystemFileHandle;

export default function GalleryAdminPage() {
  const searchParams = useSearchParams();
  const initUsername = searchParams?.get('username') ?? undefined;

  const [activeTab, setActiveTab] = useState<'materials' | 'templates' | 'car-models'>('materials');
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [carModelsData, setCarModelsData] = useState<CarModelsData>({});
  const [selectedBrand, setSelectedBrand] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [editingImages, setEditingImages] = useState<CarImageItem[]>([]);
  const [savingCarModel, setSavingCarModel] = useState(false);
  const [replacingCarModels, setReplacingCarModels] = useState(false);
  const [importingCarModel, setImportingCarModel] = useState(false);
  const [deletingCarModel, setDeletingCarModel] = useState(false);
  const [deletingCarImageKey, setDeletingCarImageKey] = useState<string | null>(null);
  const [importBrandMode, setImportBrandMode] = useState<ImportBrandMode>('existing');
  const [importBrand, setImportBrand] = useState('');
  const [importNewBrand, setImportNewBrand] = useState('');
  const [importModel, setImportModel] = useState('');
  const [importAlreadyCleaned, setImportAlreadyCleaned] = useState(true);
  const [importMethod, setImportMethod] = useState<ImportMethod>('ocr');
  const [importOverwrite, setImportOverwrite] = useState(false);
  const [importFiles, setImportFiles] = useState<File[]>([]);
  const [importWarnings, setImportWarnings] = useState<string[]>([]);
  const [importError, setImportError] = useState('');
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [usernameFilter, setUsernameFilter] = useState<string | undefined>(initUsername);
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [onlyAi, setOnlyAi] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [userOptions, setUserOptions] = useState<string[]>([]);
  const replaceCarModelsInputRef = useRef<HTMLInputElement | null>(null);
  const importFolderInputRef = useRef<HTMLInputElement | null>(null);

  const fetchData = useCallback(() => {
    setLoading(true);
    if (activeTab === 'car-models') {
      adminApi.getCarModelsAll().then(res => {
        const data = res.data || {};
        setCarModelsData(data);
        const modelCount = Object.values(data).reduce((sum, models) => sum + Object.keys(models || {}).length, 0);
        setTotal(modelCount);
        setItems([]);
        setSelectedIds(new Set());
      }).catch(console.error).finally(() => setLoading(false));
      return;
    }

    const apiCall = activeTab === 'templates'
      ? adminApi.getTemplates(page)
      : adminApi.getMaterials({ page, limit: 20, username: usernameFilter, type: typeFilter || undefined });

    apiCall.then(res => {
      setItems(res.data.items);
      setTotal(res.data.total);
      setSelectedIds(new Set());
    }).catch(console.error).finally(() => setLoading(false));
  }, [activeTab, page, usernameFilter, typeFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    adminApi.getUsers(1, 100)
      .then((res) => {
        const names = (res.data.items || []).map(u => u.username).filter(Boolean);
        setUserOptions(names);
      })
      .catch(() => setUserOptions([]));
  }, []);

  const carBrands = useMemo(
    () => Object.keys(carModelsData || {}).sort((a, b) => a.localeCompare(b, 'zh-CN')),
    [carModelsData],
  );

  const carModelOptions = useMemo(
    () => (selectedBrand && carModelsData[selectedBrand] ? Object.keys(carModelsData[selectedBrand]).sort((a, b) => a.localeCompare(b, 'zh-CN')) : []),
    [carModelsData, selectedBrand],
  );
  const carBrandCount = carBrands.length;
  const currentModelImageCount = editingImages.length;
  const carImageTotal = useMemo(
    () => Object.values(carModelsData).reduce(
      (sum, models) => sum + Object.values(models || {}).reduce((modelSum, images) => modelSum + (images?.length || 0), 0),
      0,
    ),
    [carModelsData],
  );

  useEffect(() => {
    if (activeTab !== 'car-models') return;
    if (!carBrands.length) {
      setSelectedBrand('');
      setSelectedModel('');
      setEditingImages([]);
      return;
    }

    const nextBrand = selectedBrand && carModelsData[selectedBrand] ? selectedBrand : carBrands[0];
    if (nextBrand !== selectedBrand) {
      setSelectedBrand(nextBrand);
      return;
    }

    const models = Object.keys(carModelsData[nextBrand] || {});
    if (!models.length) {
      setSelectedModel('');
      setEditingImages([]);
      return;
    }
    const nextModel = selectedModel && carModelsData[nextBrand][selectedModel] ? selectedModel : models[0];
    if (nextModel !== selectedModel) {
      setSelectedModel(nextModel);
      return;
    }

    const source = carModelsData[nextBrand]?.[nextModel] || [];
    setEditingImages(source.map(img => ({ label: img.label || '', url: img.url || '' })));
  }, [activeTab, carBrands, carModelsData, selectedBrand, selectedModel]);

  useEffect(() => {
    if (importBrandMode === 'existing' && !importBrand && carBrands.length > 0) {
      setImportBrand(carBrands[0]);
    }
  }, [carBrands, importBrand, importBrandMode]);

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这个素材吗？')) return;
    setDeletingId(id);
    try {
      await adminApi.deleteMaterial(id);
      toast.success('已删除');
      fetchData();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  const filtered = useMemo(() => {
    let list = items;
    if (searchQuery) {
      const kw = searchQuery.toLowerCase();
      list = list.filter(i => i.name.toLowerCase().includes(kw));
    }
    if (onlyAi) {
      list = list.filter(i => Boolean(i.ai_meta));
    }
    return list;
  }, [items, searchQuery, onlyAi]);

  const allSelected = filtered.length > 0 && filtered.every(i => selectedIds.has(i.id));

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(new Set());
      return;
    }
    setSelectedIds(new Set(filtered.map(i => i.id)));
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) {
      toast.error('请先选择要删除的素材');
      return;
    }
    if (!confirm(`确认批量删除 ${selectedIds.size} 个素材吗？`)) return;
    setBatchDeleting(true);
    try {
      const ids = Array.from(selectedIds);
      let ok = 0;
      for (const id of ids) {
        try {
          await adminApi.deleteMaterial(id);
          ok += 1;
        } catch {
          // keep going
        }
      }
      toast.success(`批量删除完成：成功 ${ok} / ${ids.length}`);
      fetchData();
    } finally {
      setBatchDeleting(false);
    }
  };

  const updateCarImageField = (index: number, field: 'label' | 'url', value: string) => {
    setEditingImages(prev => prev.map((img, i) => (i === index ? { ...img, [field]: value } : img)));
  };

  const handleSaveCarModel = async () => {
    if (!selectedBrand || !selectedModel) {
      toast.error('请先选择品牌和车型');
      return;
    }
    const clean = editingImages
      .map(img => ({ label: img.label.trim(), url: img.url.trim() }))
      .filter(img => img.label && img.url);
    if (clean.length === 0) {
      toast.error('至少保留一条有效图片记录');
      return;
    }

    setSavingCarModel(true);
    try {
      await adminApi.updateCarModelImages({
        brand: selectedBrand,
        model: selectedModel,
        images: clean,
      });
      setCarModelsData(prev => ({
        ...prev,
        [selectedBrand]: {
          ...(prev[selectedBrand] || {}),
          [selectedModel]: clean,
        },
      }));
      toast.success('车型图片已更新');
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '更新失败');
    } finally {
      setSavingCarModel(false);
    }
  };

  const handleReplaceCarModelsFile = async (file: File | null) => {
    if (!file) return;
    setReplacingCarModels(true);
    try {
      const res = await adminApi.replaceCarModelsJson(file);
      toast.success(`车型库已更新：${res.data.brands} 个品牌，${res.data.models} 个车型`);
      fetchData();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '车型库更新失败');
    } finally {
      setReplacingCarModels(false);
      if (replaceCarModelsInputRef.current) {
        replaceCarModelsInputRef.current.value = '';
      }
    }
  };

  const handleExportCarModels = async () => {
    try {
      const res = await adminApi.exportCarModelsJson();
      const blob = new Blob([res.data], { type: 'application/json;charset=utf-8' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `car_models_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success('车型库 JSON 已导出');
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '导出车型库失败');
    }
  };

  const handleDeleteCarModel = async () => {
    if (!selectedBrand || !selectedModel) {
      toast.error('请先选择品牌和车型');
      return;
    }
    if (!confirm(`确定删除车型“${selectedBrand} / ${selectedModel}”吗？`)) return;

    setDeletingCarModel(true);
    try {
      await adminApi.deleteCarModel({ brand: selectedBrand, model: selectedModel });
      toast.success('车型已删除');
      setImportResult(null);
      fetchData();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除车型失败');
    } finally {
      setDeletingCarModel(false);
    }
  };

  const handleDeleteCarImage = async (img: CarImageItem) => {
    if (!selectedBrand || !selectedModel) {
      toast.error('请先选择品牌和车型');
      return;
    }
    if (!confirm(`确定删除图片“${img.label}”吗？`)) return;

    const key = `${img.label}-${img.url}`;
    setDeletingCarImageKey(key);
    try {
      const res = await adminApi.deleteCarModelImage({
        brand: selectedBrand,
        model: selectedModel,
        label: img.label,
        url: img.url,
      });
      const remaining = res.data.images || [];
      setEditingImages(remaining.map((item: CarImageItem) => ({ label: item.label, url: item.url })));
      setCarModelsData(prev => ({
        ...prev,
        [selectedBrand]: {
          ...(prev[selectedBrand] || {}),
          [selectedModel]: remaining,
        },
      }));
      toast.success('车型图片已删除');
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '删除车型图片失败');
    } finally {
      setDeletingCarImageKey(null);
    }
  };

  const handleImportFolderSelect = (selected: FileList | null) => {
    const files = Array.from(selected || []).filter((file) => file.type.startsWith('image/') || /\.(jpe?g|png|webp|bmp)$/i.test(file.name));
    setImportFiles(files);
    setImportWarnings([]);
    setImportError(files.length === 0 ? '这个文件夹里没有识别到图片文件，请确认图片格式是 jpg、jpeg、png、webp 或 bmp。' : '');
    setImportResult(null);
  };

  const collectFilesFromDirectoryHandle = useCallback(async (dirHandle: FileSystemDirectoryHandle) => {
    const collected: File[] = [];
    const walk = async (handle: FileSystemDirectoryHandle | FileSystemDirectoryEntryHandle, prefix = ''): Promise<void> => {
      for await (const entry of handle.values()) {
        const nextPrefix = prefix ? `${prefix}/${entry.name}` : entry.name;
        if (entry.kind === 'directory') {
          await walk(entry, nextPrefix);
          continue;
        }
        const file = await entry.getFile();
        const relativePath = nextPrefix;
        try {
          Object.defineProperty(file, 'webkitRelativePath', {
            configurable: true,
            value: relativePath,
          });
        } catch {
          // ignore readonly override failures
        }
        collected.push(file);
      }
    };

    await walk(dirHandle);
    return collected.filter((file) => file.type.startsWith('image/') || /\.(jpe?g|png|webp|bmp)$/i.test(file.name));
  }, []);

  const handleChooseImportFolder = useCallback(async () => {
    const pickerWindow = window as DirectoryPickerWindow;
    if (pickerWindow.showDirectoryPicker) {
      try {
        const dirHandle = await pickerWindow.showDirectoryPicker();
        const files = await collectFilesFromDirectoryHandle(dirHandle);
        setImportFiles(files);
        setImportWarnings([]);
        setImportError(files.length === 0 ? '这个文件夹里没有识别到图片文件，请确认图片格式是 jpg、jpeg、png、webp 或 bmp。' : '');
        setImportResult(null);
        return;
      } catch (error) {
        if ((error as Error)?.name !== 'AbortError') {
          toast.error('文件夹读取失败');
        }
        return;
      }
    }
    importFolderInputRef.current?.click();
  }, [collectFilesFromDirectoryHandle]);

  const handleImportCarModelFolder = async () => {
    const targetBrand = (importBrandMode === 'new' ? importNewBrand : importBrand).trim();
    if (!targetBrand) {
      toast.error('请选择品牌');
      setImportError('请选择品牌，或切换到“新建品牌”后输入品牌名。');
      return;
    }
    if (!importModel.trim()) {
      toast.error('请输入车型名称');
      setImportError('请输入车型名称。');
      return;
    }
    if (importFiles.length === 0) {
      toast.error('请先选择车型图片文件夹');
      setImportError('请先选择车型图片文件夹，且文件夹内需要包含 jpg、jpeg、png、webp 或 bmp 图片。');
      return;
    }

    setImportingCarModel(true);
    setImportWarnings([]);
    setImportError('');
    setImportResult(null);
    try {
      const res = await adminApi.importCarModelFolder({
        brand: targetBrand,
        model: importModel.trim(),
        already_cleaned: importAlreadyCleaned,
        clean_method: importMethod,
        overwrite: importOverwrite,
        files: importFiles,
      });
      const payload = res.data;
      setImportWarnings(payload.warnings || []);
      setImportError('');
      setImportResult(payload);
      setSelectedBrand(payload.brand);
      setSelectedModel(payload.model);
      setImportBrandMode('existing');
      setImportBrand(payload.brand);
      setImportNewBrand('');
      setImportModel('');
      setImportFiles([]);
      if (importFolderInputRef.current) {
        importFolderInputRef.current.value = '';
      }
      toast.success(`导入完成：${payload.imported_angles.length} 个角度${payload.missing_angles.length ? `，缺少 ${payload.missing_angles.join('、')}` : ''}`);
      fetchData();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : '车型文件夹导入失败';
      setImportError(message);
      toast.error(message);
    } finally {
      setImportingCarModel(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">资产中心</h2>
        <span className="text-sm text-gray-500">共 {total} 个</span>
      </div>

      <div className="flex gap-2 border-b">
        {([['materials', '素材资产'], ['templates', '模板资产'], ['car-models', '车型库']] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => { setActiveTab(key); setPage(1); setSearchQuery(''); }}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === key ? 'border-indigo-500 text-indigo-700' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab !== 'car-models' && (
      <div className="flex flex-wrap gap-2 items-center">
        <div className="relative max-w-xs">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="搜索素材名..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border bg-white py-1.5 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
          />
        </div>

        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-gray-400" />
          <select value={typeFilter} onChange={e => { setTypeFilter(e.target.value); setPage(1); }}
            className="px-2 py-1.5 rounded-lg border text-xs">
            <option value="">全部类型</option>
            <option value="image">图片</option>
            <option value="video">视频</option>
            <option value="audio">音频</option>
            <option value="template">模板</option>
          </select>
          <label className="inline-flex items-center gap-1 text-xs text-gray-600">
            <input type="checkbox" checked={onlyAi} onChange={e => setOnlyAi(e.target.checked)} className="rounded" />
            仅 AI 元数据
          </label>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-500">用户:</label>
          <select
            className="w-36 px-3 py-1.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
            value={usernameFilter ?? ''}
            onChange={e => { setUsernameFilter(e.target.value || undefined); setPage(1); }}
          >
            <option value="">全部用户</option>
            {userOptions.map(name => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>

        <button onClick={toggleSelectAll} className="ml-auto text-xs px-3 py-1.5 rounded-lg border hover:bg-gray-50 inline-flex items-center gap-1">
          {allSelected ? <CheckSquare className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
          {allSelected ? '取消全选' : '全选当前页'}
        </button>
        <button
          onClick={handleBatchDelete}
          disabled={batchDeleting || selectedIds.size === 0}
          className={cn(
            'text-xs px-3 py-1.5 rounded-lg border inline-flex items-center gap-1',
            selectedIds.size > 0 ? 'text-red-600 border-red-200 hover:bg-red-50' : 'text-gray-400 border-gray-200 cursor-not-allowed',
          )}
        >
          <Trash2 className="h-3.5 w-3.5" />
          {batchDeleting ? '删除中...' : `批量删除(${selectedIds.size})`}
        </button>
      </div>
      )}

      {activeTab === 'car-models' && (
        <div className="space-y-4">
          <input
            ref={replaceCarModelsInputRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => void handleReplaceCarModelsFile(e.target.files?.[0] || null)}
          />
          <input
            ref={importFolderInputRef}
            type="file"
            multiple
            {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
            className="hidden"
            onChange={(e) => handleImportFolderSelect(e.target.files)}
          />
          <div className="rounded-2xl border border-stone-200 bg-[linear-gradient(180deg,#fffdf8_0%,#ffffff_100%)] p-5 shadow-sm">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <div className="text-[11px] font-medium uppercase tracking-[0.22em] text-stone-500">Car Model Library</div>
                <h3 className="mt-2 text-xl font-semibold tracking-tight text-slate-900">车型库管理</h3>
                <p className="mt-1 text-sm text-slate-500">导入、编辑、删除和导出放在一个工作区里，减少来回切换。</p>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                <div className="rounded-xl border border-stone-200 bg-white px-4 py-3">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-stone-400">品牌</div>
                  <div className="mt-1 text-lg font-semibold text-slate-900">{carBrandCount}</div>
                </div>
                <div className="rounded-xl border border-stone-200 bg-white px-4 py-3">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-stone-400">车型</div>
                  <div className="mt-1 text-lg font-semibold text-slate-900">{total}</div>
                </div>
                <div className="rounded-xl border border-stone-200 bg-white px-4 py-3">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-stone-400">图片</div>
                  <div className="mt-1 text-lg font-semibold text-slate-900">{carImageTotal}</div>
                </div>
                <button
                  onClick={handleExportCarModels}
                  className="inline-flex items-center justify-center gap-1 rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 hover:bg-stone-50"
                >
                  <Download className="h-3.5 w-3.5" />
                  导出 JSON
                </button>
                <button
                  onClick={() => replaceCarModelsInputRef.current?.click()}
                  disabled={replacingCarModels}
                  className={cn(
                    'inline-flex items-center justify-center gap-1 rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm font-medium',
                    replacingCarModels ? 'cursor-not-allowed text-slate-400' : 'text-slate-700 hover:bg-stone-50',
                  )}
                >
                  <Upload className="h-3.5 w-3.5" />
                  {replacingCarModels ? '更新中...' : '整库替换'}
                </button>
              </div>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-[400px_minmax(0,1fr)]">
            <div className="space-y-4 xl:sticky xl:top-4 xl:self-start">
            <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[11px] font-medium uppercase tracking-[0.22em] text-stone-500">Import</div>
                  <h3 className="mt-2 text-lg font-semibold text-slate-900">导入车型文件夹</h3>
                  <p className="mt-1 text-sm text-slate-500">浏览器直接选文件夹，按角度命名规则处理并上传到阿里云 OSS。</p>
                </div>
                <button
                  onClick={() => void handleChooseImportFolder()}
                  className="inline-flex items-center gap-1 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-slate-700 hover:bg-stone-100"
                >
                  <FolderUp className="h-4 w-4" />
                  选择文件夹
                </button>
              </div>

              <div className="grid gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-600">品牌</label>
                  <div className="space-y-2">
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setImportBrandMode('existing')}
                        className={cn(
                          'rounded-xl border px-3 py-2 text-xs font-medium',
                          importBrandMode === 'existing' ? 'border-slate-900 bg-slate-900 text-white' : 'border-stone-200 bg-white text-slate-600 hover:bg-stone-50',
                        )}
                      >
                        选择已有品牌
                      </button>
                      <button
                        type="button"
                        onClick={() => setImportBrandMode('new')}
                        className={cn(
                          'rounded-xl border px-3 py-2 text-xs font-medium',
                          importBrandMode === 'new' ? 'border-slate-900 bg-slate-900 text-white' : 'border-stone-200 bg-white text-slate-600 hover:bg-stone-50',
                        )}
                      >
                        新建品牌
                      </button>
                    </div>
                    {importBrandMode === 'existing' ? (
                      <select
                        value={importBrand}
                        onChange={(e) => setImportBrand(e.target.value)}
                        className="w-full rounded-xl border border-stone-200 bg-stone-50 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-stone-300"
                      >
                        {carBrands.map((brand) => <option key={brand} value={brand}>{brand}</option>)}
                      </select>
                    ) : (
                      <input
                        value={importNewBrand}
                        onChange={(e) => setImportNewBrand(e.target.value)}
                        placeholder="输入新品牌，例如：本田"
                        className="w-full rounded-xl border border-stone-200 bg-stone-50 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-stone-300"
                      />
                    )}
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-600">车型名称</label>
                  <input
                    value={importModel}
                    onChange={(e) => setImportModel(e.target.value)}
                    placeholder="例如：星越 L"
                    className="w-full rounded-xl border border-stone-200 bg-stone-50 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-stone-300"
                  />
                </div>
              </div>

              <div className="grid gap-3">
                <label className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-3 text-sm">
                  <div className="text-xs font-medium text-slate-600">是否已去水印</div>
                  <select
                    value={String(importAlreadyCleaned)}
                    onChange={(e) => setImportAlreadyCleaned(e.target.value === 'true')}
                    className="mt-1 w-full bg-transparent text-slate-900 focus:outline-none"
                  >
                    <option value="true">已去水印</option>
                    <option value="false">未去水印</option>
                  </select>
                </label>
                <label className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-3 text-sm">
                  <div className="text-xs font-medium text-slate-600">去水印方式</div>
                  <select
                    value={importMethod}
                    onChange={(e) => setImportMethod(e.target.value as ImportMethod)}
                    disabled={importAlreadyCleaned}
                    className="mt-1 w-full bg-transparent text-slate-900 focus:outline-none disabled:text-slate-400"
                  >
                    <option value="ocr">OCR</option>
                    <option value="gptimage2">GPT Image 2</option>
                  </select>
                </label>
                <label className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-3 text-sm">
                  <div className="text-xs font-medium text-slate-600">已存在车型</div>
                  <select
                    value={String(importOverwrite)}
                    onChange={(e) => setImportOverwrite(e.target.value === 'true')}
                    className="mt-1 w-full bg-transparent text-slate-900 focus:outline-none"
                  >
                    <option value="false">不覆盖</option>
                    <option value="true">覆盖</option>
                  </select>
                </label>
              </div>

              <div className="rounded-xl border border-dashed border-stone-300 bg-stone-50 px-3 py-3 text-xs text-slate-600">
                <div className="font-medium text-slate-700">已选文件：{importFiles.length} 张</div>
                {importFiles.length > 0 && (
                  <div className="mt-2 max-h-24 space-y-1 overflow-auto text-slate-500">
                    {importFiles.slice(0, 8).map((file) => (
                      <div key={file.name}>{file.webkitRelativePath || file.name}</div>
                    ))}
                    {importFiles.length > 8 && <div>… 另有 {importFiles.length - 8} 张</div>}
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-stone-200 bg-[#fcfaf5] px-3 py-3 text-xs text-slate-600 space-y-2">
                <div className="font-medium text-slate-700">文件夹格式说明</div>
                <div>1. 直接选择一个车型文件夹，里面放图片文件即可，不需要再传压缩包。</div>
                <div>2. 推荐文件名按这 5 个角度命名：</div>
                <div className="rounded-lg bg-white px-3 py-2 font-mono text-[11px] text-slate-800">正前.jpg / 斜前.jpg / 侧面.jpg / 斜后.jpg / 正后.jpg</div>
                <div>3. 兼容别名：正前方、斜前方、斜后方、正后方、前45、45前、后45、45后、车头、车尾、front、rear、side。</div>
                <div>4. 当前不识别示例：`正面.jpg.webp`。</div>
                <div>5. 支持格式：jpg、jpeg、png、webp、bmp。</div>
                <div>6. 同一角度只能有 1 张图；重复角度会直接报错。</div>
                <div>7. 缺少角度允许导入，但结果里会提示缺失项。</div>
              </div>

              {importWarnings.length > 0 && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  {importWarnings.map((warning) => <div key={warning}>{warning}</div>)}
                </div>
              )}

              {importError && (
                <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-900">
                  导入失败：{importError}
                </div>
              )}

              <div className="grid gap-2">
                <button
                  onClick={handleImportCarModelFolder}
                  disabled={importingCarModel}
                  className={cn(
                    'rounded-xl px-3 py-3 text-sm font-medium',
                    importingCarModel ? 'cursor-not-allowed bg-slate-200 text-slate-500' : 'bg-slate-900 text-white hover:bg-slate-800',
                  )}
                >
                  {importingCarModel ? '导入处理中...' : '开始导入车型文件夹'}
                </button>
              </div>

              {importingCarModel && (
                <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900">
                  正在处理文件夹。当前流程是同步执行：上传文件、去水印、上传阿里云 OSS、更新车型库。
                </div>
              )}

              {importResult && (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-xs text-emerald-950 space-y-2">
                  <div className="font-medium">最近一次导入结果</div>
                  <div>品牌：{importResult.brand}</div>
                  <div>车型：{importResult.model}</div>
                  <div>已导入角度：{importResult.imported_angles.join('、') || '无'}</div>
                  <div>缺少角度：{importResult.missing_angles.join('、') || '无'}</div>
                  <div>备份文件：{importResult.backup_file}</div>
                </div>
              )}
            </div>
            </div>

            <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-4">
              <div className="flex flex-col gap-3 border-b border-slate-100 pb-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                  <div className="text-[11px] font-medium uppercase tracking-[0.22em] text-stone-500">Editor</div>
                  <h3 className="mt-2 text-lg font-semibold text-slate-900">车型库编辑器</h3>
                  <p className="mt-1 text-sm text-slate-500">按品牌和车型定位后，维护当前车型的图片链接和角度。</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={handleSaveCarModel}
                    disabled={savingCarModel || editingImages.length === 0}
                    className={cn(
                      'inline-flex items-center gap-1 rounded-xl border border-stone-200 px-3 py-2 text-sm',
                      savingCarModel ? 'cursor-not-allowed text-slate-400 border-slate-200' : 'text-slate-700 hover:bg-stone-50',
                    )}
                  >
                    <Save className="h-4 w-4" />
                    {savingCarModel ? '保存中...' : '保存更新'}
                  </button>
                  <button
                    onClick={handleDeleteCarModel}
                    disabled={deletingCarModel || !selectedBrand || !selectedModel}
                    className={cn(
                      'inline-flex items-center gap-1 rounded-xl border px-3 py-2 text-sm',
                      deletingCarModel ? 'cursor-not-allowed text-slate-400 border-slate-200' : 'text-red-700 border-red-200 hover:bg-red-50',
                    )}
                  >
                    <Trash2 className="h-4 w-4" />
                    {deletingCarModel ? '删除中...' : '删除车型'}
                  </button>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-[220px_280px_1fr]">
                <div className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-3">
                  <label className="text-xs font-medium text-slate-600">品牌</label>
                  <select
                    value={selectedBrand}
                    onChange={(e) => setSelectedBrand(e.target.value)}
                    className="mt-2 w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-stone-300"
                  >
                    {carBrands.map(brand => <option key={brand} value={brand}>{brand}</option>)}
                  </select>
                </div>
                <div className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-3">
                  <label className="text-xs font-medium text-slate-600">车型</label>
                  <select
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    className="mt-2 w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-stone-300"
                  >
                    {carModelOptions.map(model => <option key={model} value={model}>{model}</option>)}
                  </select>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-3">
                    <div className="text-xs text-slate-500">当前图片数</div>
                    <div className="mt-1 text-xl font-semibold text-slate-900">{currentModelImageCount}</div>
                  </div>
                  <div className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-3">
                    <div className="text-xs text-slate-500">当前品牌车型数</div>
                    <div className="mt-1 text-xl font-semibold text-slate-900">{carModelOptions.length}</div>
                  </div>
                  <div className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-3">
                    <div className="text-xs text-slate-500">当前品牌</div>
                    <div className="mt-1 truncate text-xl font-semibold text-slate-900">{selectedBrand || '-'}</div>
                  </div>
                </div>
              </div>

              {editingImages.length === 0 ? (
                <div className="rounded-xl border border-dashed border-stone-300 bg-stone-50 py-16 text-center text-sm text-slate-500">当前车型暂无图片</div>
              ) : (
                <div className="grid gap-4 md:grid-cols-2">
                  {editingImages.map((img, idx) => (
                    <div key={`${idx}-${img.label}`} className="overflow-hidden rounded-2xl border border-stone-200 bg-white">
                      <div className="border-b border-stone-100 bg-stone-50 px-4 py-3">
                        <img src={img.url} alt={img.label} className="h-44 w-full object-contain bg-white" />
                      </div>
                      <div className="grid grid-cols-12 gap-2 p-3">
                        <input
                          value={img.label}
                          onChange={e => updateCarImageField(idx, 'label', e.target.value)}
                          className="col-span-4 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-stone-300"
                          placeholder="角度标签"
                        />
                        <input
                          value={img.url}
                          onChange={e => updateCarImageField(idx, 'url', e.target.value)}
                          className="col-span-6 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-stone-300"
                          placeholder="图片 URL"
                        />
                        <button
                          onClick={() => void handleDeleteCarImage(img)}
                          disabled={deletingCarImageKey === `${img.label}-${img.url}`}
                          className={cn(
                            'col-span-2 rounded-xl border px-3 py-2 text-sm',
                            deletingCarImageKey === `${img.label}-${img.url}` ? 'cursor-not-allowed text-slate-400 border-slate-200 bg-white' : 'text-red-700 border-red-200 bg-white hover:bg-red-50',
                          )}
                          title="删除该图片"
                        >
                          <Trash2 className="mx-auto h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {activeTab !== 'car-models' && (loading ? (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="aspect-square bg-gray-100 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20 text-sm text-gray-500">暂无数据</div>
      ) : (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3">
          {filtered.map(img => (
            <div key={img.id} className="group relative bg-white rounded-xl border shadow-sm overflow-hidden">
              <button
                onClick={() => toggleSelect(img.id)}
                className="absolute top-1.5 left-1.5 z-10 flex h-5 w-5 items-center justify-center rounded bg-white/90 border"
              >
                {selectedIds.has(img.id) ? <CheckSquare className="h-3.5 w-3.5 text-indigo-600" /> : <Square className="h-3.5 w-3.5 text-gray-500" />}
              </button>

              <div className="aspect-square flex items-center justify-center bg-gray-50 p-1">
                {img.url ? (
                  <img src={img.url} alt={img.name} className="w-full h-full object-contain cursor-pointer" onClick={() => setPreviewUrl(img.url)} />
                ) : (
                  <span className="text-xs text-gray-400">无预览</span>
                )}
              </div>

              <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/50 to-transparent p-1.5 pt-4">
                <p className="text-[10px] text-white truncate">{img.name}</p>
              </div>

              <div className="absolute top-1.5 right-1.5 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                {img.url && (
                  <button onClick={() => setPreviewUrl(img.url)} className="flex h-6 w-6 items-center justify-center rounded-full bg-white/90 shadow-sm hover:bg-white">
                    <Eye className="h-3 w-3" />
                  </button>
                )}
                <button onClick={() => handleDelete(img.id)} disabled={deletingId === img.id}
                  className="flex h-6 w-6 items-center justify-center rounded-full bg-red-500/90 shadow-sm hover:bg-red-600 text-white disabled:opacity-50">
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          ))}
        </div>
      ))}

      {activeTab !== 'car-models' && total > 20 && (
        <div className="flex items-center justify-between border-t bg-white rounded-lg px-4 py-3">
          <span className="text-xs text-gray-500">第 {page} 页 / 共 {Math.ceil(total / 20)} 页</span>
          <div className="flex gap-2">
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
              className="px-3 py-1 text-xs rounded-md border disabled:opacity-40 hover:bg-gray-50">上一页</button>
            <button disabled={page * 20 >= total} onClick={() => setPage(p => p + 1)}
              className="px-3 py-1 text-xs rounded-md border disabled:opacity-40 hover:bg-gray-50">下一页</button>
          </div>
        </div>
      )}

      {previewUrl && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={() => setPreviewUrl(null)}>
          <img src={previewUrl} alt="preview" className="max-w-[90vw] max-h-[90vh] object-contain" />
          <button onClick={() => setPreviewUrl(null)} className="absolute top-4 right-4 text-white text-sm hover:underline">关闭</button>
        </div>
      )}
    </div>
  );
}
