'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ImageIcon,
  Loader2,
  Pencil,
  Plus,
  Power,
  Play,
  RefreshCw,
  Trash2,
  Upload,
  X,
  XCircle,
} from 'lucide-react';
import { adminApi } from '@/services/adminApi';
import { cn } from '@/lib/utils';
import { toast } from '@/lib/toast';

type Provider = {
  id: number;
  name: string;
  model_name: string;
  provider_kind: string;
  provider_model: string;
  endpoint_url: string;
  api_key_prefix: string;
  is_enabled: boolean;
  is_default: boolean;
  priority: number;
  weight: number;
  supports_text_input: boolean;
  supports_image_input: boolean;
  config: Record<string, unknown>;
  last_health_status: string;
  last_health_error: string | null;
  last_checked_at: string | null;
  last_used_at: string | null;
  success_count: number;
  failure_count: number;
  avg_latency_ms: number | null;
  current_running: number;
  max_concurrent: number;
};

type ProviderForm = {
  name: string;
  model_name: string;
  provider_kind: string;
  provider_model: string;
  endpoint_url: string;
  api_key: string;
  is_enabled: boolean;
  is_default: boolean;
  priority: number;
  weight: number;
  supports_text_input: boolean;
  supports_image_input: boolean;
  configText: string;
};

type ProviderTestResult = {
  id: number;
  task_id: string;
  status: string;
  image_urls: string[];
  error: string | null;
  elapsed_seconds: number | null;
  provider: {
    id: number;
    name: string;
    provider_kind: string;
    provider_model: string;
  };
};

const emptyForm: ProviderForm = {
  name: '',
  model_name: 'gptimage2',
  provider_kind: 'openai_images',
  provider_model: 'gpt-image-2',
  endpoint_url: 'https://api.duckcoding.ai/v1',
  api_key: '',
  is_enabled: true,
  is_default: false,
  priority: 100,
  weight: 1,
  supports_text_input: true,
  supports_image_input: false,
  configText: JSON.stringify({ send_size: true, send_n: false, timeout: 180, max_concurrent: 3 }, null, 2),
};

const statusMeta: Record<string, { label: string; icon: typeof CheckCircle2; cls: string; dot: string }> = {
  healthy: { label: '正常', icon: CheckCircle2, cls: 'text-emerald-700 bg-emerald-50 border-emerald-200', dot: 'bg-emerald-500' },
  degraded: { label: '降级', icon: AlertTriangle, cls: 'text-amber-700 bg-amber-50 border-amber-200', dot: 'bg-amber-500' },
  unhealthy: { label: '异常', icon: XCircle, cls: 'text-red-700 bg-red-50 border-red-200', dot: 'bg-red-500' },
  unknown: { label: '未知', icon: AlertTriangle, cls: 'text-slate-600 bg-slate-50 border-slate-200', dot: 'bg-slate-400' },
};

function validateEndpointUrl(providerKind: string, endpointUrl: string): string | null {
  const value = endpointUrl.trim();
  if (!value) return '请填写接口地址';
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return '接口地址不是合法 URL';
  }

  if (providerKind === 'openai_images') {
    const path = parsed.pathname.replace(/\/+$/, '');
    if (!path) {
      return 'OpenAI Images 兼容入口不能填站点首页；请填写 API base，例如 http://192.168.10.51:48731/v1';
    }
  }

  return null;
}

function fmtTime(v: string | null) {
  if (!v) return '-';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return '-';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function ProviderModal({
  open,
  editing,
  onClose,
  onSaved,
}: {
  open: boolean;
  editing: Provider | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<ProviderForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const endpointHelp = form.provider_kind === 'openai_images'
    ? '填写 OpenAI Images API base，例如 http://192.168.10.51:48731/v1 或完整生图路径 http://192.168.10.51:48731/v1/images/generations；不要填站点首页 /'
    : '填写 MentalOut Batch 服务地址，例如 https://image.mentalout.top';

  useEffect(() => {
    if (!open) return;
    if (!editing) {
      setForm(emptyForm);
      return;
    }
    setForm({
      name: editing.name,
      model_name: editing.model_name,
      provider_kind: editing.provider_kind,
      provider_model: editing.provider_model,
      endpoint_url: editing.endpoint_url,
      api_key: '',
      is_enabled: editing.is_enabled,
      is_default: editing.is_default,
      priority: editing.priority,
      weight: editing.weight,
      supports_text_input: editing.supports_text_input,
      supports_image_input: editing.supports_image_input,
      configText: JSON.stringify(editing.config || {}, null, 2),
    });
  }, [editing, open]);

  if (!open) return null;

  const update = <K extends keyof ProviderForm>(key: K, value: ProviderForm[K]) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const save = async () => {
    if (!form.name.trim()) {
      toast.error('请填写入口名称');
      return;
    }
    if (!editing && !form.api_key.trim()) {
      toast.error('请填写 API Key');
      return;
    }
    const endpointError = validateEndpointUrl(form.provider_kind, form.endpoint_url);
    if (endpointError) {
      toast.error(endpointError);
      return;
    }
    let config: Record<string, unknown>;
    try {
      config = form.configText.trim() ? JSON.parse(form.configText) : {};
    } catch {
      toast.error('高级配置不是合法 JSON');
      return;
    }

    const payload = {
      name: form.name.trim(),
      model_name: form.model_name.trim(),
      provider_kind: form.provider_kind,
      provider_model: form.provider_model.trim(),
      endpoint_url: form.endpoint_url.trim(),
      ...(form.api_key.trim() ? { api_key: form.api_key.trim() } : {}),
      is_enabled: form.is_enabled,
      is_default: form.is_default,
      priority: Number(form.priority),
      weight: Number(form.weight),
      supports_text_input: form.supports_text_input,
      supports_image_input: form.supports_image_input,
      config,
    };

    setSaving(true);
    try {
      if (editing) {
        await adminApi.updateAiImageProvider(editing.id, payload);
        toast.success('入口已更新');
      } else {
        await adminApi.createAiImageProvider(payload as typeof payload & { api_key: string });
        toast.success('入口已创建');
      }
      onSaved();
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-3xl rounded-lg bg-white shadow-xl">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <div>
            <h2 className="text-base font-semibold">{editing ? '编辑生图入口' : '新增生图入口'}</h2>
            <p className="mt-1 text-xs text-gray-500">同一模型可启用多个入口，系统会按任务类型、并发容量和权重派发；失败只记录，不自动切换入口。</p>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid max-h-[72vh] grid-cols-1 gap-4 overflow-auto p-5 md:grid-cols-2">
          <label className="space-y-1">
            <span className="text-xs font-medium text-gray-600">入口名称</span>
            <input value={form.name} onChange={e => update('name', e.target.value)} className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100" placeholder="DuckCoding GPT Image 2" />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-gray-600">内部模型</span>
            <input value={form.model_name} onChange={e => update('model_name', e.target.value)} className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100" />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-gray-600">入口类型</span>
            <select value={form.provider_kind} onChange={e => update('provider_kind', e.target.value)} className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100">
              <option value="openai_images">OpenAI Images 兼容</option>
              <option value="mentalout_batch">MentalOut Batch</option>
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-gray-600">上游模型名</span>
            <input value={form.provider_model} onChange={e => update('provider_model', e.target.value)} className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100" placeholder="gpt-image-2" />
          </label>
          <label className="space-y-1 md:col-span-2">
            <span className="text-xs font-medium text-gray-600">接口地址</span>
            <input value={form.endpoint_url} onChange={e => update('endpoint_url', e.target.value)} className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100" placeholder="https://api.duckcoding.ai/v1" />
            <span className="text-[11px] text-gray-400">{endpointHelp}</span>
          </label>
          <label className="space-y-1 md:col-span-2">
            <span className="text-xs font-medium text-gray-600">API Key {editing ? '（留空保持不变）' : ''}</span>
            <input value={form.api_key} onChange={e => update('api_key', e.target.value)} type="password" className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100" placeholder={editing ? editing.api_key_prefix : 'sk-...'} />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-gray-600">优先级</span>
            <input value={form.priority} onChange={e => update('priority', Number(e.target.value))} type="number" className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100" />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-gray-600">权重</span>
            <input value={form.weight} onChange={e => update('weight', Number(e.target.value))} type="number" min={1} className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100" />
          </label>
          <div className="flex flex-wrap items-center gap-4 md:col-span-2">
            <label className="inline-flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={form.is_enabled} onChange={e => update('is_enabled', e.target.checked)} />
              启用
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={form.is_default} onChange={e => update('is_default', e.target.checked)} />
              设为主入口
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={form.supports_text_input} onChange={e => update('supports_text_input', e.target.checked)} />
              支持文生图
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={form.supports_image_input} onChange={e => update('supports_image_input', e.target.checked)} />
              支持参考图任务
            </label>
          </div>
          <label className="space-y-1 md:col-span-2">
            <span className="text-xs font-medium text-gray-600">高级配置 JSON</span>
            <textarea value={form.configText} onChange={e => update('configText', e.target.value)} className="h-28 w-full rounded-md border px-3 py-2 font-mono text-xs outline-none focus:ring-2 focus:ring-indigo-100" />
            <span className="text-[11px] text-gray-400">可配置 max_concurrent 控制单入口并发；DuckCoding 建议 send_size=true，send_n=false。</span>
          </label>
        </div>

        <div className="flex justify-end gap-2 border-t px-5 py-4">
          <button onClick={onClose} className="rounded-md border px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">取消</button>
          <button onClick={save} disabled={saving} className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60">
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

function ProviderTestModal({
  open,
  provider,
  onClose,
  onFinished,
}: {
  open: boolean;
  provider: Provider | null;
  onClose: () => void;
  onFinished: () => void;
}) {
  const [prompt, setPrompt] = useState('生成一张干净的汽车展厅海报，真实摄影风格，画面包含一辆新能源 SUV，柔和自然光，高级商业质感。');
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [quality, setQuality] = useState('low');
  const [count, setCount] = useState(1);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ProviderTestResult | null>(null);
  const [taskId, setTaskId] = useState('');
  const [referenceImageData, setReferenceImageData] = useState('');
  const [referenceImageName, setReferenceImageName] = useState('');

  useEffect(() => {
    if (!open) return;
    setResult(null);
    setTaskId('');
    setReferenceImageData('');
    setReferenceImageName('');
  }, [open, provider?.id]);

  const handleReferenceImage = (file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      toast.error('请选择图片文件');
      return;
    }
    if (file.size > 12 * 1024 * 1024) {
      toast.error('参考图不能超过 12MB');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const value = typeof reader.result === 'string' ? reader.result : '';
      if (!value.startsWith('data:image/')) {
        toast.error('参考图读取失败');
        return;
      }
      setReferenceImageData(value);
      setReferenceImageName(file.name);
    };
    reader.onerror = () => toast.error('参考图读取失败');
    reader.readAsDataURL(file);
  };

  const runTest = async () => {
    if (!provider) return;
    if (!prompt.trim()) {
      toast.error('请输入测试提示词');
      return;
    }
    setTesting(true);
    setResult(null);
    setTaskId('');
    try {
      const res = await adminApi.testAiImageProvider(provider.id, {
        prompt: prompt.trim(),
        width,
        height,
        quality: quality || undefined,
        count,
        image_data: referenceImageData || undefined,
      });
      setResult(res.data);
      setTaskId(res.data.task_id || '');
    } catch (e) {
      const message = e instanceof Error ? e.message : '测试失败';
      setResult({
        id: provider.id,
        task_id: '',
        status: 'failed',
        image_urls: [],
        error: message,
        elapsed_seconds: 0,
        provider: {
          id: provider.id,
          name: provider.name,
          provider_kind: provider.provider_kind,
          provider_model: provider.provider_model,
        },
      });
      toast.error(message);
      setTesting(false);
    }
  };

  useEffect(() => {
    if (!open || !taskId || !testing || !provider) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const res = await adminApi.getAiImageProviderTestTask(taskId);
        if (cancelled) return;
        const data = res.data;
        setResult(data);
        if (data.status === 'completed' && data.image_urls.length > 0) {
          setTesting(false);
          toast.success('测试生图完成');
          onFinished();
          return;
        }
        if (data.status === 'failed') {
          setTesting(false);
          toast.error(data.error || '测试未返回图片');
          onFinished();
          return;
        }
        timer = setTimeout(poll, 2000);
      } catch (e) {
        if (cancelled) return;
        setTesting(false);
        const message = e instanceof Error ? e.message : '测试状态查询失败';
        setResult(prev => ({
          id: provider.id,
          task_id: taskId,
          status: 'failed',
          image_urls: [],
          error: message,
          elapsed_seconds: prev?.elapsed_seconds ?? null,
          provider: prev?.provider || {
            id: provider.id,
            name: provider.name,
            provider_kind: provider.provider_kind,
            provider_model: provider.provider_model,
          },
        }));
        toast.error(message);
      }
    };

    timer = setTimeout(poll, 800);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [open, taskId, testing, onFinished, provider]);

  const closeModal = () => {
    if (testing && !confirm('测试任务仍在后台执行，确定关闭窗口？')) return;
    onClose();
  };

  const resultStatusLabel = result?.status === 'queued'
    ? '已提交，等待执行'
    : result?.status === 'processing'
      ? '正在请求上游'
      : '正在等待上游返回图片';

  if (!open || !provider) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4">
      <div className="relative grid max-h-[88vh] w-full max-w-5xl overflow-hidden rounded-xl bg-white shadow-2xl md:grid-cols-[380px_minmax(0,1fr)]">
        <button
          onClick={closeModal}
          aria-label="关闭测试窗口"
          className="absolute right-4 top-4 z-20 grid h-9 w-9 place-items-center rounded-full border border-gray-200 bg-white text-gray-500 shadow-sm transition hover:bg-gray-50 hover:text-gray-900"
        >
          <X className="h-4 w-4" />
        </button>
        <div className="overflow-y-auto border-b p-5 md:border-b-0 md:border-r">
          <div className="flex items-start justify-between gap-4 pr-10">
            <div>
              <h2 className="text-base font-semibold text-gray-950">Provider 接口诊断</h2>
              <p className="mt-1 text-xs leading-5 text-gray-500">{provider.name} · {provider.provider_kind}</p>
            </div>
          </div>

          <div className="mt-5 space-y-4">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-gray-600">测试提示词</span>
              <textarea
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                className="h-36 w-full resize-none rounded-md border px-3 py-2 text-sm leading-6 outline-none focus:ring-2 focus:ring-indigo-100"
                placeholder="输入要真实发送到上游的提示词"
              />
            </label>

            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-gray-600">参考图（可选）</span>
                <span className={cn(
                  'rounded-full px-2 py-1 text-[10px] font-medium',
                  referenceImageData ? 'bg-amber-50 text-amber-700' : 'bg-sky-50 text-sky-700',
                )}>
                  {referenceImageData ? '图片编辑 /images/edits' : '文字直出 /images/generations'}
                </span>
              </div>
              {referenceImageData ? (
                <div className="flex items-center gap-3 rounded-lg border bg-gray-50 p-2">
                  <img src={referenceImageData} alt="测试参考图" className="h-14 w-14 rounded-md object-cover" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium text-gray-700">{referenceImageName}</div>
                    <div className="mt-1 text-[11px] text-gray-400">将真实测试用户带参考图时使用的接口</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => { setReferenceImageData(''); setReferenceImageName(''); }}
                    className="rounded-md border bg-white px-2 py-1 text-xs text-gray-500 hover:text-gray-900"
                  >
                    移除
                  </button>
                </div>
              ) : (
                <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed bg-gray-50 px-3 py-4 text-xs text-gray-500 transition hover:border-gray-400 hover:bg-gray-100">
                  <Upload className="h-4 w-4" />
                  上传参考图，验证用户实际链路
                  <input type="file" accept="image/*" className="hidden" onChange={event => handleReferenceImage(event.target.files?.[0])} />
                </label>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <label className="space-y-1">
                <span className="text-xs font-medium text-gray-600">宽度</span>
                <input value={width} onChange={e => setWidth(Number(e.target.value) || 1024)} type="number" min={256} max={4096} className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100" />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-gray-600">高度</span>
                <input value={height} onChange={e => setHeight(Number(e.target.value) || 1024)} type="number" min={256} max={4096} className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100" />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-gray-600">质量</span>
                <select value={quality} onChange={e => setQuality(e.target.value)} className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100">
                  <option value="">不传</option>
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-gray-600">张数</span>
                <input value={count} onChange={e => setCount(Math.max(1, Math.min(4, Number(e.target.value) || 1)))} type="number" min={1} max={4} className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-100" />
              </label>
            </div>

            <button
              onClick={runTest}
              disabled={testing}
              className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-slate-950 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
            >
              {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {testing ? '测试任务执行中...' : `测试${referenceImageData ? '图片编辑' : '文字直出'}接口`}
            </button>
            <p className="text-[11px] leading-5 text-gray-400">会真实消耗上游额度。本功能诊断指定 Provider 接口，不代表用户队列、文件存储和去水印链路均已完成。</p>
          </div>
        </div>

        <div className="min-h-[560px] overflow-auto bg-gray-50 p-5 pt-14">
          {!result && !testing ? (
            <div className="grid h-full min-h-[480px] place-items-center rounded-lg border border-dashed bg-white text-center">
              <div>
                <ImageIcon className="mx-auto h-10 w-10 text-gray-300" />
                <div className="mt-3 text-sm font-medium text-gray-700">等待测试结果</div>
                <div className="mt-1 text-xs text-gray-400">输入提示词后会在这里显示上游返回图片</div>
              </div>
            </div>
          ) : testing ? (
            <div className="grid h-full min-h-[480px] place-items-center rounded-lg border bg-white text-center">
              <div>
                <Loader2 className="mx-auto h-8 w-8 animate-spin text-slate-900" />
                <div className="mt-3 text-sm font-medium text-gray-800">{resultStatusLabel}</div>
                <div className="mt-1 text-xs text-gray-400">{taskId ? `测试任务 #${taskId}` : '窗口可以保持打开，完成后会自动展示结果'}</div>
              </div>
            </div>
          ) : result?.status === 'completed' && result.image_urls.length > 0 ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold text-gray-900">测试成功</div>
                  <div className="mt-1 text-xs text-gray-500">耗时 {result.elapsed_seconds ?? '-'}s · {result.provider.provider_model}</div>
                </div>
                <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">completed</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {result.image_urls.map((url, index) => (
                  <a key={`${url}-${index}`} href={url} target="_blank" rel="noreferrer" className="group overflow-hidden rounded-lg border bg-white">
                    <img src={url} alt={`测试结果 ${index + 1}`} className="aspect-square w-full object-contain bg-white transition group-hover:scale-[1.01]" />
                    <div className="truncate border-t px-3 py-2 text-xs text-gray-500">{url}</div>
                  </a>
                ))}
              </div>
              <button onClick={closeModal} className="rounded-md border bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">关闭</button>
            </div>
          ) : (
            <div className="rounded-lg border border-red-100 bg-white p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-red-700">
                <XCircle className="h-4 w-4" />
                测试失败
              </div>
              <div className="mt-3 whitespace-pre-wrap rounded-md bg-red-50 p-3 text-xs leading-6 text-red-700">
                {result?.error || '上游没有返回图片'}
              </div>
              {result?.elapsed_seconds ? <div className="mt-2 text-xs text-gray-400">耗时 {result.elapsed_seconds}s</div> : null}
              <button onClick={closeModal} className="mt-4 rounded-md border bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">关闭</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default function AdminAIImageProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [checkingId, setCheckingId] = useState<'all' | null>(null);
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [defaultingId, setDefaultingId] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [testingProvider, setTestingProvider] = useState<Provider | null>(null);

  const load = async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const res = await adminApi.getAiImageProviders('gptimage2');
      setProviders(res.data);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '加载失败');
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const summary = useMemo(() => {
    const enabled = providers.filter(p => p.is_enabled).length;
    const healthy = providers.filter(p => p.last_health_status === 'healthy').length;
    const failed = providers.filter(p => p.last_health_status === 'unhealthy').length;
    return { enabled, healthy, failed };
  }, [providers]);

  const checkAll = async () => {
    setCheckingId('all');
    try {
      await adminApi.checkAllAiImageProviders('gptimage2');
      await load();
      toast.success('全部检测完成');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '检测失败');
    } finally {
      setCheckingId(null);
    }
  };

  const toggle = async (provider: Provider) => {
    if (togglingId !== null) return;
    const nextEnabled = !provider.is_enabled;
    setTogglingId(provider.id);
    setProviders(prev => prev.map(item =>
      item.id === provider.id ? { ...item, is_enabled: nextEnabled } : item
    ));
    try {
      await adminApi.toggleAiImageProvider(provider.id, nextEnabled);
      toast.success(`${provider.name} 已${nextEnabled ? '启用' : '停用'}`);
      await load(false);
    } catch (e) {
      setProviders(prev => prev.map(item =>
        item.id === provider.id ? { ...item, is_enabled: provider.is_enabled } : item
      ));
      toast.error(e instanceof Error ? e.message : '切换失败');
    } finally {
      setTogglingId(null);
    }
  };

  const setDefault = async (provider: Provider) => {
    if (defaultingId !== null || provider.is_default) return;
    setDefaultingId(provider.id);
    setProviders(prev => prev.map(item => ({ ...item, is_default: item.id === provider.id })));
    try {
      await adminApi.setDefaultAiImageProvider(provider.id);
      toast.success(`${provider.name} 已设为主入口`);
      await load(false);
    } catch (e) {
      setProviders(prev => prev.map(item => ({ ...item, is_default: item.id === provider.id ? provider.is_default : item.is_default })));
      toast.error(e instanceof Error ? e.message : '设置主入口失败');
    } finally {
      setDefaultingId(null);
    }
  };

  const remove = async (provider: Provider) => {
    if (!confirm(`确定删除生图入口「${provider.name}」？`)) return;
    try {
      await adminApi.deleteAiImageProvider(provider.id);
      await load();
      toast.success('已删除');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '删除失败');
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-xl font-semibold">生图入口</h1>
          <p className="mt-1 text-xs text-gray-500">管理 GPT Image 2 上游入口。启用多个入口时，生成任务会按健康状态、任务类型、优先级和权重自动路由并失败切换。</p>
        </div>
        <div className="flex gap-2">
          <button onClick={checkAll} disabled={checkingId === 'all'} className="inline-flex items-center gap-2 rounded-md border bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60">
            {checkingId === 'all' ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            全部检测
          </button>
          <button onClick={() => load()} className="inline-flex items-center gap-2 rounded-md border bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50">
            <RefreshCw className="h-4 w-4" />
            刷新
          </button>
          <button onClick={() => { setEditing(null); setModalOpen(true); }} className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700">
            <Plus className="h-4 w-4" />
            新增入口
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <div className="rounded-lg border bg-white p-4">
          <div className="text-xs text-gray-500">入口总数</div>
          <div className="mt-2 text-2xl font-bold">{providers.length}</div>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <div className="text-xs text-gray-500">启用中</div>
          <div className="mt-2 text-2xl font-bold text-indigo-600">{summary.enabled}</div>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <div className="text-xs text-gray-500">健康</div>
          <div className="mt-2 text-2xl font-bold text-emerald-600">{summary.healthy}</div>
        </div>
        <div className="rounded-lg border bg-white p-4">
          <div className="text-xs text-gray-500">异常</div>
          <div className="mt-2 text-2xl font-bold text-red-600">{summary.failed}</div>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="border-b bg-gray-50 text-xs text-gray-500">
              <tr>
                <th className="px-4 py-3 text-left font-medium">入口</th>
                <th className="px-4 py-3 text-left font-medium">接口</th>
                <th className="px-4 py-3 text-left font-medium">状态</th>
                <th className="px-4 py-3 text-left font-medium">路由</th>
                <th className="px-4 py-3 text-right font-medium">统计</th>
                <th className="px-4 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {loading ? (
                <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-500"><Loader2 className="mx-auto h-5 w-5 animate-spin" /></td></tr>
              ) : providers.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-500">暂无入口，请新增 DuckCoding 或其他 OpenAI Images 兼容地址。</td></tr>
              ) : providers.map(provider => {
                const meta = statusMeta[provider.last_health_status] || statusMeta.unknown;
                const StatusIcon = meta.icon;
                return (
                  <tr key={provider.id} className={cn(!provider.is_enabled && 'bg-gray-50 text-gray-400')}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-900">{provider.name}</div>
                      <div className="mt-1 text-xs text-gray-500">{provider.model_name} / {provider.provider_model}</div>
                      <div className="mt-1 text-xs text-gray-400">Key: {provider.api_key_prefix || '-'}</div>
                    </td>
                    <td className="max-w-[360px] px-4 py-3">
                      <div className="inline-flex rounded-full border bg-gray-50 px-2 py-0.5 text-[11px] text-gray-600">{provider.provider_kind}</div>
                      <div className="mt-2 truncate font-mono text-xs text-gray-500" title={provider.endpoint_url}>{provider.endpoint_url}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-medium', meta.cls)}>
                        <StatusIcon className="h-3.5 w-3.5" />
                        {meta.label}
                      </span>
                      {provider.is_default && (
                        <span className="ml-2 inline-flex items-center rounded-full border border-indigo-200 bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700">
                          主入口
                        </span>
                      )}
                      <span className={cn(
                        'ml-2 inline-flex items-center rounded-full border px-2 py-1 text-xs font-medium',
                        provider.is_enabled
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          : 'border-gray-200 bg-gray-100 text-gray-500'
                      )}>
                        {provider.is_enabled ? '已启用' : '已停用'}
                      </span>
                      <div className="mt-1 text-xs text-gray-400">检测: {fmtTime(provider.last_checked_at)}</div>
                      {provider.last_health_error && <div className="mt-1 max-w-[260px] truncate text-xs text-red-500" title={provider.last_health_error}>{provider.last_health_error}</div>}
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-xs text-gray-600">权重 {provider.weight} / 并发 {provider.current_running}/{provider.max_concurrent}</div>
                      <div className="mt-1 text-xs text-gray-400">优先级 {provider.priority}</div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {provider.supports_text_input && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-700">文生图</span>}
                        {provider.supports_image_input && <span className="rounded bg-purple-50 px-1.5 py-0.5 text-[11px] text-purple-700">参考图</span>}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="text-xs text-gray-600">成功 {provider.success_count} / 失败 {provider.failure_count}</div>
                      <div className="mt-1 text-xs text-gray-400">延迟 {provider.avg_latency_ms ? Math.round(provider.avg_latency_ms) + 'ms' : '-'}</div>
                      <div className="mt-1 text-xs text-gray-400">使用: {fmtTime(provider.last_used_at)}</div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1.5">
                        <button onClick={() => setTestingProvider(provider)} title="真实测试" className="inline-flex min-w-[72px] items-center justify-center gap-1.5 rounded-md border px-2.5 py-2 text-xs text-slate-700 hover:bg-gray-50">
                          <Play className="h-4 w-4" />
                          测试
                        </button>
                        <button
                          onClick={() => toggle(provider)}
                          disabled={togglingId === provider.id}
                          title={provider.is_enabled ? '停用' : '启用'}
                          aria-label={`${provider.is_enabled ? '停用' : '启用'} ${provider.name}`}
                          className={cn(
                            'inline-flex min-w-[72px] items-center justify-center gap-1.5 rounded-md border px-2.5 py-2 text-xs hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60',
                            provider.is_enabled ? 'text-emerald-600' : 'text-gray-400'
                          )}
                        >
                          {togglingId === provider.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}
                          {provider.is_enabled ? '停用' : '启用'}
                        </button>
                        <button
                          onClick={() => setDefault(provider)}
                          disabled={defaultingId === provider.id || provider.is_default}
                          title={provider.is_default ? '当前主入口' : '设为主入口'}
                          className="inline-flex min-w-[72px] items-center justify-center gap-1.5 rounded-md border px-2.5 py-2 text-xs text-indigo-600 hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {defaultingId === provider.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                          {provider.is_default ? '主入口' : '设主'}
                        </button>
                        <button onClick={() => { setEditing(provider); setModalOpen(true); }} title="编辑" className="rounded-md border p-2 text-gray-600 hover:bg-gray-50">
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button onClick={() => remove(provider)} title="删除" className="rounded-md border p-2 text-red-600 hover:bg-red-50">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-lg border bg-gray-50 px-4 py-3 text-xs leading-6 text-gray-600">
        推荐新增 DuckCoding：类型选 OpenAI Images 兼容，接口地址填 <span className="font-mono">https://api.duckcoding.ai/v1</span>，上游模型填 <span className="font-mono">gpt-image-2</span>，高级配置保持 <span className="font-mono">{'{ "send_size": true, "send_n": false, "max_concurrent": 3 }'}</span>。像 <span className="font-mono">http://192.168.10.51:48731/</span> 这种站点首页地址不要直接填，应该填 API base <span className="font-mono">http://192.168.10.51:48731/v1</span> 或完整路径 <span className="font-mono">http://192.168.10.51:48731/v1/images/generations</span>。
      </div>

      <ProviderModal
        open={modalOpen}
        editing={editing}
        onClose={() => setModalOpen(false)}
        onSaved={load}
      />
      <ProviderTestModal
        open={Boolean(testingProvider)}
        provider={testingProvider}
        onClose={() => setTestingProvider(null)}
        onFinished={() => load(false)}
      />
    </div>
  );
}
