/**
 * Template Loader — load gaoding templates from static files.
 *
 * Templates are served from public/templates/ → accessible at /templates/
 */

import {
  gaodingToFabric,
  type FabricCanvasJSON,
  rewriteGaodingAssetUrl,
} from '@/utils/gaodingToFabric';

/**
 * Recursively process trusted template SVG elements.
 * P0 security: keep SVGs as local/template URLs and never convert user-controlled
 * SVG text into data:image/svg+xml payloads.
 */
async function preprocessSvgElements(el: Record<string, unknown>, folder: string, svgCache?: Record<string, string>): Promise<void> {
  if (!svgCache) svgCache = {};
  const type = el.type as string;
  // Handle top-level SVG elements
  if (type === 'svg' && typeof el.url === 'string') {
    const originalUrl = el.url as string;
    const colors = (el.colors as string[]) || [];
    if (colors.length > 0) {
      if (svgCache[originalUrl]) {
        el.url = svgCache[originalUrl];
      } else {
        try {
          const localUrl = rewriteGaodingAssetUrl(originalUrl, folder);
          const res = await fetch(localUrl, { cache: 'no-store' });
          if (res.ok) {
            el.url = localUrl;
            svgCache[originalUrl] = localUrl;
          }
        } catch { /* ignore */ }
      }
    }
  }
  // Handle text element background SVGs (e.g., colored banners behind text)
  const bg = el.background as Record<string, unknown> | undefined;
  if (bg && bg.enable === true) {
    const svg = bg.svg as Record<string, unknown> | undefined;
    if (svg && typeof svg.url === 'string') {
      try {
        const localUrl = rewriteGaodingAssetUrl(svg.url, folder);
        const res = await fetch(localUrl, { cache: 'no-store' });
        if (res.ok) {
          // P0 security: do not convert SVG text to data URLs. Keep trusted local assets only.
          svg._processedDataUrl = localUrl;
        }
      } catch { /* ignore */ }
    }
  }
  // Recurse into children
  if (Array.isArray(el.elements)) {
    for (const child of el.elements) {
      await preprocessSvgElements(child as Record<string, unknown>, folder, svgCache);
    }
  }
  // Recurse into layouts and pages
  if (Array.isArray(el.layouts)) {
    for (const item of el.layouts) {
      await preprocessSvgElements(item as Record<string, unknown>, folder, svgCache);
    }
  }
  if (Array.isArray(el.pages)) {
    for (const item of el.pages) {
      await preprocessSvgElements(item as Record<string, unknown>, folder, svgCache);
    }
  }
}

export interface TemplateMeta {
  id: string;
  title: string;
  type: string;
  width: number;
  height: number;
  payment: string | number;
  image_count: number;
  preview: string;
  folder: string;
  /** Pre-converted fabric.json path, e.g. "folder/fabric.json" */
  fabric_json_file?: string;
}

export interface LoadedTemplate {
  id: string;
  title: string;
  width: number;
  height: number;
  fabricJson: string;
  bgImageUrl?: string;
  bgImageOpacity?: number;
  previewUrl: string;
  meta: TemplateMeta;
}

const BASE_PATH = '/templates';

/**
 * Extract layout background image URL from design.json.
 * Handles both `layouts[0].background.image.url` and `layouts[0].backgroundImage`.
 * This is needed because pre-generated fabric.json never includes the layout background image,
 * so we must extract it from design.json separately.
 */
function extractBgImageUrlFromDesign(design: Record<string, unknown> | null, folder?: string): string | undefined {
  if (!design) return undefined;
  const layouts = design.layouts as Record<string, unknown>[] | undefined;
  if (layouts && layouts.length > 0) {
    const L0 = layouts[0];
    const bg = L0?.background as Record<string, unknown> | undefined;
    const img = bg?.image as Record<string, unknown> | undefined;
    if (img?.url) {
      let url = img.url as string;
      if (folder) url = rewriteGaodingAssetUrl(url, folder);
      return url;
    }
    if (L0?.backgroundImage) {
      let url = L0.backgroundImage as string;
      if (folder) url = rewriteGaodingAssetUrl(url, folder);
      return url;
    }
  }
  // Also check pages format
  const pages = design.pages as Record<string, unknown>[] | undefined;
  if (pages && pages.length > 0) {
    const el0 = (pages[0].elements as Record<string, unknown>[])?.[0];
    if (el0?.type === 'layout') {
      const bg = el0.background as Record<string, unknown> | undefined;
      const img = bg?.image as Record<string, unknown> | undefined;
      if (img?.url) {
        let url = img.url as string;
        if (folder) url = rewriteGaodingAssetUrl(url, folder);
        return url;
      }
    }
  }
  return undefined;
}

/**
 * Walk Fabric JSON; {@link rewriteGaodingAssetUrl} only maps non-absolute names to
 * /templates/.../images/ — https CDN URLs are kept for reliable loading.
 */
function rewriteFabricJsonAssetUrls(node: unknown, folder: string): void {
  if (node == null || typeof node !== 'object') return;
  const o = node as Record<string, unknown>;
  if (typeof o.src === 'string') {
    o.src = rewriteGaodingAssetUrl(o.src, folder);
    // 稿定 CDN 若未对 anonymous CORS 放行，Fabric 会整图失败 → 透明。去掉 crossOrigin 能正常出图；canvas 可能被污染不便于导出。
    if (o.type === 'Image' && typeof o.src === 'string' && /^https?:/i.test(o.src)) {
      delete o.crossOrigin;
    }
  }
  if (o.backgroundImage && typeof o.backgroundImage === 'object') {
    const bi = o.backgroundImage as { src?: string };
    if (typeof bi.src === 'string') bi.src = rewriteGaodingAssetUrl(bi.src, folder);
  }
  if (o.overlayImage && typeof o.overlayImage === 'object') {
    const oi = o.overlayImage as { src?: string };
    if (typeof oi.src === 'string') oi.src = rewriteGaodingAssetUrl(oi.src, folder);
  }
  if (Array.isArray(o.objects)) {
    for (const child of o.objects) rewriteFabricJsonAssetUrls(child, folder);
  }
}

/**
 * Load template as Fabric canvas JSON: prefer pre-generated fabric.json (pixel match with 稿定),
 * fall back to design.json + gaodingToFabric.
 *
 * CRITICAL FIX: When a template has multiple layouts (different size variants), the pre-generated
 * fabric.json merges ALL layouts into one canvas, causing duplicate elements and wrong dimensions.
 * For these templates, use runtime conversion which only uses the first layout.
 */
export async function loadTemplateAsFabric(meta: TemplateMeta): Promise<{
  fabricJson: FabricCanvasJSON;
  bgImageUrl?: string;
  bgImageOpacity?: number;
}> {
  // First, check design.json to determine layout count.
  // We'll reuse this data if we need runtime conversion.
  const designUrl = `${BASE_PATH}/${meta.folder}/design.json`;
  let designJson: unknown = null;
  try {
    const dres = await fetch(designUrl, { cache: 'no-store' });
    if (dres.ok) {
      designJson = await dres.json();
    }
  } catch { /* ignore — proceed with fabric.json fallback */ }

  // Detect multi-layout: if design has multiple layouts, fabric.json likely merged them all
  let isMultiLayout = false;
  let layoutCount = 0;
  if (designJson) {
    const dj = designJson as Record<string, unknown>;
    layoutCount = Array.isArray(dj.layouts) ? dj.layouts.length : 0;
    const pageCount = Array.isArray(dj.pages) ? dj.pages.length : 0;
    isMultiLayout = layoutCount > 1 || pageCount > 1;
  }

  if (isMultiLayout && designJson) {
    // Use runtime conversion — only first layout will be processed
    console.log(`[templateLoader] ${meta.folder}: ${layoutCount ?? 0} layouts detected, using runtime conversion`);
    // CRITICAL: Preprocess SVG elements to replace {{colors[N]}} with actual values
    await preprocessSvgElements(designJson as Record<string, unknown>, meta.folder);
    return gaodingToFabric(designJson as any, meta.folder);
  }

  // Single-layout: prefer pre-generated fabric.json
  const tryUrls: string[] = [];
  if (meta.fabric_json_file) tryUrls.push(`${BASE_PATH}/${meta.fabric_json_file}`);
  const defaultFabric = `${BASE_PATH}/${meta.folder}/fabric.json`;
  if (!tryUrls.includes(defaultFabric)) tryUrls.push(defaultFabric);

  for (const url of tryUrls) {
    const res = await fetch(url, { cache: 'no-store' });
    if (res.ok) {
      const fabricJson = (await res.json()) as FabricCanvasJSON;
      rewriteFabricJsonAssetUrls(fabricJson, meta.folder);
      // FIX: Even when using pre-generated fabric.json, extract bgImageUrl from design.json
      // since fabric.json never includes the layout background image.
      const bgImageUrl = extractBgImageUrlFromDesign(designJson as Record<string, unknown> | null, meta.folder);
      return { fabricJson, bgImageUrl, bgImageOpacity: 1 };
    }
  }

  // Fallback: runtime conversion
  if (designJson) {
    // CRITICAL: Preprocess SVG elements to replace {{colors[N]}} with actual values
    await preprocessSvgElements(designJson as Record<string, unknown>, meta.folder);
    return gaodingToFabric(designJson as any, meta.folder);
  }
  throw new Error(`No fabric.json and no design.json for ${meta.folder}`);
}

/**
 * Fetch the template index (list of all templates).
 */
export async function getTemplateList(): Promise<TemplateMeta[]> {
  const res = await fetch(`${BASE_PATH}/index.json`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Failed to load template index: ${res.status}`);
  return res.json();
}

/**
 * Resolve `TemplateMeta` for a folder (from index) or a minimal default so we can open fabric.json.
 */
export async function getTemplateMetaForFolder(folder: string): Promise<TemplateMeta> {
  const list = await getTemplateList();
  const found = list.find(t => t.folder === folder);
  if (found) return found;
  return {
    id: folder,
    title: folder,
    type: 'poster',
    width: 1242,
    height: 1656,
    payment: 'FREE',
    image_count: 0,
    preview: '',
    folder,
  };
}

/**
 * Load a single template: prefer fabric.json, else design.json + runtime conversion.
 */
export async function loadTemplate(meta: TemplateMeta): Promise<LoadedTemplate> {
  const { fabricJson, bgImageUrl, bgImageOpacity } = await loadTemplateAsFabric(meta);

  return {
    id: meta.id,
    title: meta.title,
    width: fabricJson.width ?? meta.width,
    height: fabricJson.height ?? meta.height,
    fabricJson: JSON.stringify(fabricJson),
    bgImageUrl,
    bgImageOpacity,
    previewUrl: `${BASE_PATH}/${meta.folder}/preview.png`,
    meta,
  };
}

/**
 * Load a template by ID — first find the meta in index, then load.
 */
export async function loadTemplateById(templateId: string): Promise<LoadedTemplate> {
  const list = await getTemplateList();
  const meta = list.find(t => t.id === templateId);
  if (!meta) throw new Error(`Template ${templateId} not found in index`);
  return loadTemplate(meta);
}
