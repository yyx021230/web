/**
 * Convert gaoding.com design.json -> Fabric.js canvas JSON
 *
 * Architecture:
 * - All gaoding elements use absolute canvas coordinates
 * - When converting to Fabric Groups, children must use relative coords
 * - path/mask/effectText/ninePatch types have pre-rasterized imageUrl -> treat as Image
 * - layout background image is extracted and placed as canvas background
 */

interface GaodingTransform {
  a: number;
  b: number;
  c: number;
  d: number;
  tx: number;
  ty: number;
}

interface GaodingBaseElement {
  uuid: string;
  type: string;
  title: string;
  left: number;
  top: number;
  width: number;
  height: number;
  opacity: number;
  hidden?: boolean;
  lock?: boolean;
  borderRadius?: number;
  transform: GaodingTransform;
  elements?: GaodingElement[];
  filter?: {
    contrast?: number;
    sharpness?: number;
    hueRotate?: number;
    saturate?: number;
    brightness?: number;
    gaussianBlur?: number;
  };
}

interface GaodingTextElement extends GaodingBaseElement {
  type: 'text';
  content: string;
  color: string;
  fontFamily: string;
  fontSize: number;
  fontWeight: number;
  fontStyle: string;
  lineHeight: number;
  letterSpacing: number;
  textAlign: string;
  textDecoration: string;
  contents?: Array<{
    color?: string;
    fontFamily?: string;
    fontSize?: number;
    fontWeight?: number;
    fontStyle?: string;
    content: string;
  }>;
}

interface GaodingImageElement extends GaodingBaseElement {
  type: 'image';
  url: string;
  naturalWidth?: number;
  naturalHeight?: number;
}

interface GaodingSvgElement extends GaodingBaseElement {
  type: 'svg';
  url: string;
  colors?: string[];
  naturalWidth?: number;
  naturalHeight?: number;
  content?: string;
}

interface GaodingPathElement extends GaodingBaseElement {
  type: 'path';
  imageUrl: string;
  naturalWidth?: number;
  naturalHeight?: number;
}

interface GaodingMaskElement extends GaodingBaseElement {
  type: 'mask';
  imageUrl: string;
  naturalWidth?: number;
  naturalHeight?: number;
}

interface GaodingEffectTextElement extends GaodingBaseElement {
  type: 'effectText';
  imageUrl: string;
  naturalWidth?: number;
  naturalHeight?: number;
}

interface GaodingNinePatchElement extends GaodingBaseElement {
  type: 'ninePatch';
  imageUrl?: string;
  backgroundColor?: string;
}

interface GaodingLayoutElement extends GaodingBaseElement {
  type: 'layout';
  backgroundColor?: string;
  background?: {
    color?: string;
    image?: {
      url: string;
      opacity: number;
      width: number;
      height: number;
      left: number;
      top: number;
      transform?: GaodingTransform;
    };
  };
  backgroundImage?: string;
}

interface GaodingGroupElement extends GaodingBaseElement {
  type: 'group';
}

type GaodingElement =
  | GaodingTextElement
  | GaodingImageElement
  | GaodingSvgElement
  | GaodingPathElement
  | GaodingMaskElement
  | GaodingEffectTextElement
  | GaodingNinePatchElement
  | GaodingLayoutElement
  | GaodingGroupElement
  | GaodingBaseElement;

interface GaodingDesign {
  version: string;
  type: string;
  global: {
    layout: {
      width: number | null;
      height: number | null;
      backgroundColor: string;
      backgroundImage: string | null;
    };
  };
  /** Newer format: pages[].elements[] */
  pages?: Array<{
    uuid: string;
    elements: GaodingElement[];
  }>;
  /** Older format: layouts[] (flat array of layout elements) */
  layouts?: GaodingElement[];
}

interface FabricObject {
  type: string;
  originX?: string;
  originY?: string;
  left: number;
  top: number;
  width: number;
  height: number;
  scaleX?: number;
  scaleY?: number;
  fill?: string | null;
  stroke?: string | null;
  strokeWidth?: number;
  angle: number;
  opacity: number;
  flipX?: boolean;
  flipY?: boolean;
  visible?: boolean;
  backgroundColor?: string;
  id?: string;
  name?: string;
  selectable?: boolean;
  hasControls?: boolean;
  evented?: boolean;
  text?: string;
  fontSize?: number;
  fontFamily?: string;
  fontWeight?: string | number;
  fontStyle?: string;
  lineHeight?: number;
  charSpacing?: number;
  textAlign?: string;
  underline?: boolean;
  linethrough?: boolean;
  overline?: boolean;
  src?: string;
  crossOrigin?: string;
  objects?: FabricObject[];
  shadow?: { color: string; blur: number; offsetX: number; offsetY: number } | null;
  rx?: number;
  ry?: number;
  [key: string]: any;
}

interface FabricCanvasJSON {
  version: string;
  objects: FabricObject[];
  background: string;
  backgroundImage?: {
    src: string;
    scaleX: number;
    scaleY: number;
    opacity: number;
  };
  width: number;
  height: number;
}

/* ============ Helpers ============ */

function normalizeColor(hex: string): string {
  if (!hex) return '#000000';
  if (hex.length === 9 && hex.startsWith('#')) {
    const a = parseInt(hex.slice(7, 9), 16) / 255;
    if (a >= 0.99) return `#${hex.slice(1, 7)}`;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${a.toFixed(2)})`;
  }
  if (hex.length === 7 && hex.startsWith('#')) return hex;
  return hex;
}

function getAngle(transform?: GaodingTransform): number {
  if (!transform) return 0;
  const { a, b } = transform;
  if (a === 1 && b === 0) return 0;
  return (Math.atan2(b, a) * 180) / Math.PI;
}

function getScale(transform?: GaodingTransform): { scaleX: number; scaleY: number } {
  if (!transform) return { scaleX: 1, scaleY: 1 };
  const sx = Math.sqrt(transform.a * transform.a + transform.b * transform.b);
  const sy = Math.sqrt(transform.c * transform.c + transform.d * transform.d);
  // FIX: Guard against NaN/Infinity
  return {
    scaleX: isFinite(sx) && sx > 0 ? sx : 1,
    scaleY: isFinite(sy) && sy > 0 ? sy : 1,
  };
}

function getTextDecor(decoration: string): { underline: boolean; linethrough: boolean; overline: boolean } {
  return {
    underline: decoration === 'underline',
    linethrough: decoration === 'line-through',
    overline: decoration === 'overline',
  };
}

/**
 * Build a Fabric Image object from any element that has an imageUrl/url.
 * Used for: image, svg, path, mask, effectText
 */
function makeFabricImage(
  src: string,
  absLeft: number,
  absTop: number,
  displayW: number,
  displayH: number,
  naturalW: number,
  naturalH: number,
  scaleX: number,
  scaleY: number,
  angle: number,
  opacity: number,
  uuid: string,
  name: string,
  lock: boolean | undefined,
): FabricObject {
  // FIX: Guard against zero/undefined natural dimensions to prevent NaN/Infinity
  const safeNaturalW = naturalW > 0 ? naturalW : displayW;
  const safeNaturalH = naturalH > 0 ? naturalH : displayH;

  return {
    type: 'Image',
    src,
    left: absLeft,
    top: absTop,
    width: safeNaturalW,
    height: safeNaturalH,
    scaleX: (displayW * scaleX) / safeNaturalW,
    scaleY: (displayH * scaleY) / safeNaturalH,
    angle,
    opacity,
    originX: 'left',
    originY: 'top',
    selectable: !lock,
    id: uuid,
    name,
    // 仅同源 /templates/ 用 anonymous；远程素材用 CORS 失败时整图不显示
    ...(src.startsWith('/templates/')
      ? { crossOrigin: 'anonymous' as const }
      : {}),
    shadow: null,
  };
}

/* ============ Element converters ============ */

function convertText(
  el: GaodingTextElement,
  absLeft: number,
  absTop: number,
  extraObjects: FabricObject[],
  _folder?: string,
): FabricObject | null {
  if (el.hidden) return null;
  const { scaleX } = getScale(el.transform);
  const decor = getTextDecor(el.textDecoration || 'none');

  let text = el.content || '';
  if (el.contents && el.contents.length > 0) {
    text = el.contents.map(c => c.content).join('');
  }

  // FIX: Handle text elements with background SVG (colored banners behind text).
  // Background is pushed as a SEPARATE independent object into extraObjects — not grouped with text.
  // This keeps text editable and background independently selectable in the layer list.
  const bgObj = convertTextBackground(el, absLeft, absTop);
  if (bgObj) {
    extraObjects.push(bgObj);
  }

  // FIX: Do NOT set height on Textbox. Fabric.js uses height as a clipping constraint —
  // when declared height < content height (due to font differences, wrapping), text gets cut off.
  // We omit height so Fabric auto-calculates from content, preventing clipping.
  const textBox = {
    type: 'Textbox',
    text,
    left: absLeft,
    top: absTop,
    width: el.width * scaleX,
    fill: normalizeColor(el.color || '#000000'),
    fontSize: el.fontSize * 0.75,
    fontFamily: el.fontFamily || 'PingFang SC',
    fontWeight: (el.fontWeight || 400) >= 500 ? 'bold' : 'normal',
    fontStyle: el.fontStyle === 'italic' ? 'italic' : 'normal',
    lineHeight: el.lineHeight || 1.2,
    charSpacing: (el.letterSpacing || 0) * 10,
    textAlign: el.textAlign === 'justify' ? 'justify' : (el.textAlign || 'left'),
    angle: getAngle(el.transform),
    opacity: el.opacity,
    originX: 'left',
    originY: 'top',
    selectable: !el.lock,
    id: el.uuid,
    name: el.title || text.slice(0, 20) || '文字',
    shadow: null,
    ...decor,
  } as FabricObject;

  return textBox;
}

/**
 * Generic image-like converter.
 * Handles: image, svg, path, mask, effectText — all render as Image in Fabric.
 */
function convertImageLike(
  src: string,
  el: GaodingBaseElement,
  absLeft: number,
  absTop: number,
  defaultName: string,
): FabricObject | null {
  if (el.hidden) return null;
  if (!src) return null;
  const { scaleX, scaleY } = getScale(el.transform);
  // FIX: Better fallback chain for natural dimensions
  const elAny = el as any;
  const nw = elAny.naturalWidth || el.width || 100;
  const nh = elAny.naturalHeight || el.height || 100;
  return makeFabricImage(
    src, absLeft, absTop,
    el.width, el.height,
    nw, nh,
    scaleX, scaleY,
    getAngle(el.transform),
    el.opacity,
    el.uuid,
    (el as any).title || defaultName,
    el.lock,
  );
}

/**
 * Create a background Fabric object for text elements that have `background.enable: true`.
 * Gaoding uses SVG backgrounds behind text for colored banners/decorative effects.
 * Returns null if no background, or a Rect/Image that should be placed BEFORE the text
 * in the objects array (so it renders behind).
 */
function convertTextBackground(
  el: GaodingTextElement,
  absLeft: number,
  absTop: number,
  _folder?: string,
): FabricObject | null {
  const bg = (el as any).background;
  if (!bg || !bg.enable) return null;
  const svg = bg.svg;
  if (!svg || !svg.url) return null;

  // Try to get preprocessed SVG data URL (set by preprocessSvgElements)
  const processedUrl = svg._processedDataUrl as string | undefined;
  const color = (svg.colors && svg.colors[0]) || '#000000';
  const svgNaturalW = svg.naturalWidth || 100;
  const svgNaturalH = svg.naturalHeight || 100;
  const scaleX = el.width / svgNaturalW;
  const scaleY = el.height / svgNaturalH;

  // If we have a preprocessed SVG data URL, render it as an Image behind the text
  if (processedUrl) {
    return {
      type: 'Image',
      src: processedUrl,
      left: absLeft,
      top: absTop,
      width: svgNaturalW,
      height: svgNaturalH,
      scaleX,
      scaleY,
      angle: getAngle(el.transform),
      opacity: svg.opacity ?? el.opacity,
      originX: 'left',
      originY: 'top',
      selectable: !el.lock,
      evented: true,
      id: (el.uuid || '') + '-bg',
      name: (el.title || '文字') + '背景',
      ...(processedUrl.startsWith('/templates/') ? { crossOrigin: 'anonymous' as const } : {}),
      shadow: null,
    };
  }

  // No preprocessed SVG — fall back to solid color Rect
  return {
    type: 'Rect',
    left: absLeft,
    top: absTop,
    width: el.width * getScale(el.transform).scaleX,
    height: el.height * getScale(el.transform).scaleY,
    fill: normalizeColor(color),
    angle: getAngle(el.transform),
    opacity: svg.opacity ?? el.opacity,
    originX: 'left',
    originY: 'top',
    selectable: !el.lock,
    evented: true,
    id: (el.uuid || '') + '-bg',
    name: (el.title || '文字') + '背景',
    shadow: null,
    rx: 0,
    ry: 0,
  };
}

/**
 * Convert any element recursively.
 * groupOffsetX/groupOffsetY = cumulative parent group position (for coord conversion).
 * visited = cycle detection.
 */
function convertAny(
  el: GaodingElement,
  groupOffsetX: number = 0,
  groupOffsetY: number = 0,
  visited?: Set<string>,
  folder?: string,
  extraObjects: FabricObject[] = [],
): FabricObject | null {
  if (!visited) visited = new Set();

  const uuid = el.uuid || '';
  if (visited.has(uuid)) return null;
  visited.add(uuid);

  const { scaleX, scaleY } = getScale(el.transform);
  // FIX: Ensure absLeft/absTop are finite numbers
  const absLeft = isFinite(groupOffsetX + el.left * scaleX) ? groupOffsetX + el.left * scaleX : (el.left || 0);
  const absTop = isFinite(groupOffsetY + el.top * scaleY) ? groupOffsetY + el.top * scaleY : (el.top || 0);

  switch (el.type) {
    // --- Text ---
    case 'text':
      return convertText(el as GaodingTextElement, absLeft, absTop, extraObjects, folder);

    // --- Image (bitmap) ---
    case 'image': {
      const ie = el as GaodingImageElement;
      return convertImageLike(ie.url, ie, absLeft, absTop, '图片');
    }

    // --- SVG (vector, served as URL) ---
    case 'svg': {
      const se = el as GaodingSvgElement;
      return convertImageLike(se.url, se, absLeft, absTop, '图形');
    }

    // --- Path (shape with pre-rasterized PNG) ---
    case 'path': {
      // FIX: path elements in gaoding have imageUrl pointing to a pre-rasterized PNG.
      // Previously these were skipped entirely, causing missing background/decorative images.
      const pe = el as any;
      if (pe.imageUrl) {
        return convertImageLike(pe.imageUrl, pe, absLeft, absTop, pe.title || '图形');
      }
      return null;
    }

    // --- Mask (masked/composited image) ---
    case 'mask': {
      const me = el as GaodingMaskElement;
      const maskInfo = (me as any).maskInfo;
      // FIX: When mask is disabled (enable=false) and the image URL exists, the imageUrl
      // contains the pre-composited result with masking baked in — render it as a normal image.
      // showSelf=false means "don't show mask layer separately in editor", not "don't render".
      // Only skip when mask is actively enabled (it's a masking layer for another element).
      if (maskInfo?.enable === true) {
        // Active mask: only show if explicitly requested
        if (maskInfo?.showSelf === false) return null;
        if (!me.imageUrl) return null;
      }
      // Disabled or neutral mask: try imageUrl first (composited result), then url
      const src = me.imageUrl || (me as any).url;
      if (!src) return null;
      return convertImageLike(src, me, absLeft, absTop, '遮罩');
    }

    // --- Effect Text (styled text rendered as PNG) ---
    case 'effectText': {
      const et = el as GaodingEffectTextElement;
      return convertImageLike(et.imageUrl, et, absLeft, absTop, '特效文字');
    }

    // --- Nine-Patch (stretchable UI element) ---
    case 'ninePatch': {
      const ne = el as GaodingNinePatchElement;
      const neAny = ne as any;
      // FIX: ninePatch may have URL in `url` field instead of `imageUrl`.
      // Try imageUrl first, then url, then backgroundColor fallback.
      const src = ne.imageUrl || neAny.url;
      if (src) {
        return convertImageLike(src, ne, absLeft, absTop, ne.title || '九宫格');
      }
      // Fallback: render as colored rect
      if (ne.backgroundColor) {
        return {
          type: 'Rect',
          left: absLeft,
          top: absTop,
          width: ne.width * scaleX,
          height: ne.height * scaleY,
          fill: normalizeColor(ne.backgroundColor),
          angle: getAngle(ne.transform),
          opacity: ne.opacity,
          originX: 'left',
          originY: 'top',
          selectable: !ne.lock,
          id: ne.uuid,
          name: ne.title || '九宫格',
          shadow: null,
          rx: ne.borderRadius || 0,
          ry: ne.borderRadius || 0,
        };
      }
      return null;
    }

    // --- Puzzle (photo collage/grid) — render the composited image ---
    case 'puzzle': {
      if (el.hidden) return null;
      const pe = el as any;
      const src = pe.imageUrl || pe.url;
      if (!src) return null;
      return convertImageLike(src, el, absLeft, absTop, pe.title || '拼图');
    }

    // --- Group (container) — flatten: each child becomes independent top-level object ---
    case 'group': {
      const groupEl = el as GaodingGroupElement;
      if (groupEl.hidden) return null;

      // Flatten: push each child as an independent top-level object.
      // Child coords are relative to group origin, so pass group's absolute position.
      if (groupEl.elements) {
        for (const child of groupEl.elements) {
          const converted = convertAny(child, absLeft, absTop, visited, folder, extraObjects);
          if (converted) {
            extraObjects.push(converted);
          }
        }
      }
      return null; // Never create a Fabric Group
    }

    // --- Layout (canvas container) ---
    case 'layout':
      // Layout is handled at the top level, not as an object
      return null;

    // --- Table types — flatten, recurse into children ---
    case 'table':
    case 'tableRow':
    case 'tableCell': {
      const te = el as any;
      if (te.hidden) return null;
      if (!te.elements || te.elements.length === 0) return null;

      // Flatten: push each child as independent object
      for (const child of te.elements) {
        const converted = convertAny(child, absLeft, absTop, visited, folder, extraObjects);
        if (converted) extraObjects.push(converted);
      }
      return null; // Never create a Fabric Group
    }

    // --- Unknown with children (treat as group, flatten) ---
    default:
      if ((el as GaodingBaseElement).elements) {
        for (const child of (el as GaodingBaseElement).elements!) {
          const converted = convertAny(child, absLeft, absTop, visited, folder, extraObjects);
          if (converted) extraObjects.push(converted);
        }
        return null;
      }
      return null;
  }
}

/* ============ Main converter ============ */

/**
 * Process layout elements — extract background image and convert children.
 * This is shared by both `pages` and `layouts` formats.
 */
function processLayoutElement(layoutEl: GaodingLayoutElement, objects: FabricObject[], visited: Set<string>, folder?: string) {
  if (folder) {
    // IMPORTANT: Do NOT rewrite background image URL. Keep original CDN URL for reliable loading.
    // Rewrite all children image URLs
    if (layoutEl.elements) {
      for (const child of layoutEl.elements) {
        rewriteElementUrls(child, folder);
      }
    }
  }

  // Extract background image — use original URL (not rewritten)
  let bgResult: { bgImageUrl: string; bgImageOpacity: number; bgWidth: number; bgHeight: number } | null = null;
  const bg = layoutEl.background;
  if (bg?.image?.url) {
    bgResult = {
      bgImageUrl: bg.image.url,
      bgImageOpacity: bg.image.opacity ?? 1,
      bgWidth: bg.image.width || layoutEl.width,
      bgHeight: bg.image.height || layoutEl.height,
    };
  } else if (layoutEl.backgroundImage) {
    bgResult = { bgImageUrl: layoutEl.backgroundImage, bgImageOpacity: 1, bgWidth: layoutEl.width, bgHeight: layoutEl.height };
  }

  // FIX: Always convert layout children, regardless of whether there's a background image.
  // Previously this was inside an else branch after the background check, causing children
  // to be skipped when a background image existed (Objects count: 0 bug).
  if (layoutEl.elements) {
    for (const child of layoutEl.elements) {
      const converted = convertAny(child, 0, 0, visited, folder, objects);
      if (converted) objects.push(converted);
    }
  }

  return bgResult;
}

/**
 * Recursively rewrite all image/SVG/etc URLs in an element tree.
 */
function rewriteElementUrls(el: GaodingElement, folder: string): void {
  const t = el.type;
  if (t === 'image' && (el as GaodingImageElement).url) {
    (el as GaodingImageElement).url = rewriteUrl((el as GaodingImageElement).url, folder);
  } else if (t === 'svg' && (el as GaodingSvgElement).url) {
    (el as GaodingSvgElement).url = rewriteUrl((el as GaodingSvgElement).url, folder);
  } else if (t === 'path' && (el as GaodingPathElement).imageUrl) {
    (el as GaodingPathElement).imageUrl = rewriteUrl((el as GaodingPathElement).imageUrl, folder);
  } else if (t === 'mask' && (el as GaodingMaskElement).imageUrl) {
    (el as GaodingMaskElement).imageUrl = rewriteUrl((el as GaodingMaskElement).imageUrl, folder);
  } else if (t === 'effectText' && (el as GaodingEffectTextElement).imageUrl) {
    (el as GaodingEffectTextElement).imageUrl = rewriteUrl((el as GaodingEffectTextElement).imageUrl, folder);
  } else if (t === 'ninePatch') {
    const ne = el as GaodingNinePatchElement;
    const neAny = ne as any;
    if (ne.imageUrl) ne.imageUrl = rewriteUrl(ne.imageUrl, folder);
    if (neAny.url) neAny.url = rewriteUrl(neAny.url, folder);
  }
  // Recurse into children
  if (el.elements) {
    for (const child of el.elements) {
      rewriteElementUrls(child, folder);
    }
  }
}

export interface ConvertResult {
  fabricJson: FabricCanvasJSON;
  /** Background image URL from layout, if any */
  bgImageUrl?: string;
  /** Background image opacity */
  bgImageOpacity?: number;
}

/**
 * Resolve asset URL for the editor. Absolute http(s) URLs (稿定 CDN) are left unchanged:
 * the repo’s `public/templates/.../images/` mirror is often partial only; mapping CDN → local
 * for every filename 404s missing PNGs and Fabric draws nothing (looks “transparent”).
 */
export function rewriteGaodingAssetUrl(url: string, folder?: string): string {
  if (!url || !folder) return url;
  if (url.startsWith('/templates/')) return url;
  if (url.startsWith('data:') || url.startsWith('blob:')) return url;
  if (url.startsWith('http://') || url.startsWith('https://')) {
    return url;
  }
  const filename = url.split('?')[0].split('/').pop();
  if (!filename) return url;
  return `/templates/${folder}/images/${filename}`;
}

function rewriteUrl(url: string, folder?: string): string {
  return rewriteGaodingAssetUrl(url, folder);
}

/**
 * 稿定画板尺寸：以「带 elements 的页/画板」为准（layouts[0] 或 pages 里第一个 layout），
 * 与 layer 的 left/top/width 同坐标系。global.layout 常有 width=640、height=0 等与内容不一致的情况，不能优先信。
 */
export function resolveGaodingArtboardSize(design: GaodingDesign): { width: number; height: number } {
  if (design.layouts && design.layouts.length > 0) {
    const L = design.layouts[0] as { width?: number; height?: number };
    if (L.width != null && L.width > 0 && L.height != null && L.height > 0) {
      return { width: L.width, height: L.height };
    }
  }
  if (design.pages && design.pages.length > 0) {
    for (const page of design.pages) {
      for (const el of page.elements) {
        if (el.type === 'layout') {
          const L = el as { width?: number; height?: number };
          if (L.width != null && L.width > 0 && L.height != null && L.height > 0) {
            return { width: L.width, height: L.height };
          }
        }
      }
    }
  }
  const g = design.global?.layout;
  if (g) {
    const gw = g.width != null && g.width > 0 ? g.width : 0;
    const gh = g.height != null && g.height > 0 ? g.height : 0;
    if (gw > 0 && gh > 0) {
      return { width: gw, height: gh };
    }
    if (gw > 0) {
      return { width: gw, height: 1656 };
    }
  }
  return { width: 1242, height: 1656 };
}

export function gaodingToFabric(design: GaodingDesign, folder?: string): ConvertResult {
  const layout = design.global.layout;
  const objects: FabricObject[] = [];
  const visited = new Set<string>();

  let bgImageUrl: string | undefined;
  let bgImageOpacity = 1;

  // Handle both `pages` and `layouts` formats
  if (design.pages && design.pages.length > 0) {
    // Newer format: pages[].elements[]
    for (const page of design.pages) {
      for (const el of page.elements) {
        if (el.type === 'layout') {
          const result = processLayoutElement(el as GaodingLayoutElement, objects, visited, folder);
          if (result) {
            bgImageUrl = result.bgImageUrl;
            bgImageOpacity = result.bgImageOpacity;
          }
        } else {
          if (folder) rewriteElementUrls(el, folder);
          const converted = convertAny(el, 0, 0, visited, folder, objects);
          if (converted) objects.push(converted);
        }
      }
    }
  } else if (design.layouts && design.layouts.length > 0) {
    // Older format: layouts[] (flat array of layout elements)
    // FIX: When there are multiple layouts (different size variants), only process the first one.
    // Later layouts are alternate sizes (e.g., square version) that shouldn't be merged into the same canvas.
    const firstLayout = design.layouts[0];
    const result = processLayoutElement(firstLayout as GaodingLayoutElement, objects, visited, folder);
    if (result) {
      bgImageUrl = result.bgImageUrl;
      bgImageOpacity = result.bgImageOpacity;
    }
  }

  const { width: canvasWidth, height: canvasHeight } = resolveGaodingArtboardSize(design);

  let background = layout.backgroundColor || '#ffffff';
  if (background.length === 9) background = normalizeColor(background);

  const result: FabricCanvasJSON = {
    version: '5.3.0',
    objects,
    background,
    width: canvasWidth,
    height: canvasHeight,
  };

  // FIX: Do NOT set backgroundImage. The pre-generated fabric.json never includes backgroundImage
  // even when layout has a background image. The background effect is handled by the elements
  // within groups. Setting backgroundImage causes an extra layer that doesn't match the original.
  // bgImageUrl and bgImageOpacity are still returned for callers that need them.

  return { fabricJson: result, bgImageUrl, bgImageOpacity };
}

export type { GaodingDesign, FabricCanvasJSON, FabricObject };
