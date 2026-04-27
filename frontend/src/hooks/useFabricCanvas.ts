/**
 * Fabric.js Canvas Hook - Replaces DOM-based element rendering
 *
 * Architecture (aligned with vue-fabric-editor):
 * - Fabric canvas is the SINGLE source of truth for elements/layers
 * - No separate elements[] or layers[] React state needed
 * - Selection is driven by Fabric events (selection:created, selection:updated, selection:cleared)
 * - Templates load directly via loadFromJSON (no parsing layer needed)
 * - History is managed via snapshot diffs on object:modified
 */

import { useEffect, useLayoutEffect, useRef, useState, useCallback, type RefObject } from 'react';
import { fabric } from 'fabric';
import { afterTemplateLoad, getLayerTree } from '@/utils/fabricTemplateObjects';

const DSET = { backstoreOnly: true } as { backstoreOnly: boolean };

export interface UseFabricCanvasOptions {
  /** Width of the canvas in px */
  width: number;
  /** Height of the canvas in px */
  height: number;
  /** Background color/gradient string */
  background?: string;
  /** Called when the active selection changes */
  onSelectionChange?: (objects: fabric.Object[]) => void;
  /**
   * 外层容器 ref；用于把 canvas 用 CSS 缩放到该容器内。
   * 当提供此 ref 时，hook 以该容器的尺寸为基准计算缩放。
   */
  containerRef?: RefObject<HTMLDivElement | null>;
  /**
   * 可选：画板 wrapper ref（直接包裹 <canvas> 的 div）。
   * 如果提供，优先用此 wrapper 的尺寸来计算 CSS 缩放，确保缩放比例与外层 div 一致。
   */
  wrapperRef?: RefObject<HTMLDivElement | null>;
}

export function useFabricCanvas(options: UseFabricCanvasOptions) {
  const canvasEl = useRef<HTMLCanvasElement>(null);
  const wrapperEl = useRef<HTMLDivElement>(null);
  const fabricCanvas = useRef<fabric.Canvas | null>(null);
  const isInitialized = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  // React state for UI sync
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedObject, setSelectedObject] = useState<fabric.Object | null>(null);
  const [, forceUpdate] = useState(0); // bump to trigger re-renders from Fabric events

  // History stack for undo/redo
  const historyRef = useRef<{ stack: string[]; idx: number }>({ stack: [], idx: -1 });
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const [isReady, setIsReady] = useState(false);
  /** true = CSS 1:1 与 buffer 同像素，不套「适应视口」系数 */
  const pixel1to1Ref = useRef(false);
  /** Buffer dimensions — NEVER changed by cssWidth/cssHeight */
  const bufferWRef = useRef(0);
  const bufferHRef = useRef(0);
  /** 左下角/工具栏缩放 25%–200%，相对「适应视口」的倍率，100% = 刚好在容器内不溢出的等比 */
  const [zoomPercent, setZoomPercent] = useState(100);
  const zoomPercentRef = useRef(100);
  zoomPercentRef.current = zoomPercent;

  // ---- Initialization ----
  useLayoutEffect(() => {
    // Check if element is in DOM
    if (!canvasEl.current) {
      console.warn('[useFabricCanvas] canvasEl.current is null, will retry...');
      return;
    }
    // React 18 StrictMode double-mounts: check if we already have a valid canvas
    if (fabricCanvas.current && isInitialized.current) {
      return;
    }

    const opt = optionsRef.current;
    console.log('[useFabricCanvas] Initializing canvas:', opt.width, 'x', opt.height);

    // If there's a disposed canvas on this element, clean it up
    if ((canvasEl.current as any).__fabricCanvas) {
      delete (canvasEl.current as any).__fabricCanvas;
    }

    try {
      const canvas = new fabric.Canvas(canvasEl.current, {
        width: opt.width,
        height: opt.height,
        backgroundColor: opt.background || '#e8edf5',
        preserveObjectStacking: true,
        fireRightClick: true,
        stopContextMenu: true,
        controlsAboveOverlay: true,
      });
      console.log('[useFabricCanvas] Fabric canvas created:', opt.width, 'x', opt.height);

      // Save buffer dimensions — these NEVER change via cssWidth/cssHeight
      bufferWRef.current = opt.width;
      bufferHRef.current = opt.height;

      // Track on DOM element for StrictMode safety
      (canvasEl.current as any).__fabricCanvas = true;

      // Selection events
      canvas.on('selection:created', () => {
        const objs = canvas.getActiveObjects();
        setSelectedIds(objs.map(o => (o as any).id || ''));
        setSelectedObject(objs.length === 1 ? objs[0] : null);
        optionsRef.current.onSelectionChange?.(objs);
        forceUpdate(n => n + 1);
      });
      canvas.on('selection:updated', () => {
        const objs = canvas.getActiveObjects();
        setSelectedIds(objs.map(o => (o as any).id || ''));
        setSelectedObject(objs.length === 1 ? objs[0] : null);
        optionsRef.current.onSelectionChange?.(objs);
        forceUpdate(n => n + 1);
      });
      canvas.on('selection:cleared', () => {
        setSelectedIds([]);
        setSelectedObject(null);
        optionsRef.current.onSelectionChange?.([]);
        forceUpdate(n => n + 1);
      });

      // History tracking
      const pushHistory = () => {
        try {
          const json = JSON.stringify(canvas.toJSON(['id', 'name', 'canvasId']));
          const stack = historyRef.current.stack.slice(0, historyRef.current.idx + 1);
          stack.push(json);
          if (stack.length > 50) stack.shift();
          historyRef.current.stack = stack;
          historyRef.current.idx = stack.length - 1;
          setCanUndo(historyRef.current.idx > 0);
          setCanRedo(false);
        } catch (e) {
          console.warn('pushHistory error:', e);
        }
      };

      canvas.on('object:added', (e) => {
        if (!((e.target as any)?._isHistoryLoading)) {
          pushHistory();
        }
      });
      canvas.on('object:modified', pushHistory);
      canvas.on('object:removed', (e) => {
        if (!((e.target as any)?._isHistoryLoading)) {
          pushHistory();
        }
      });

      fabricCanvas.current = canvas;
      isInitialized.current = true;

      // Apply viewport CSS synchronously before first paint
      applyCanvasViewportCss();
      console.log('[init]', {
        width: canvas.width, height: canvas.height,
        bufferW: bufferWRef.current, bufferH: bufferHRef.current,
        objs: canvas.getObjects().length,
        viewport: canvas.viewportTransform,
        zoom: canvas.getZoom(),
        cssW: canvas.getElement()?.style.width, cssH: canvas.getElement()?.style.height,
      });

      requestAnimationFrame(() => {
        pushHistory();
        setIsReady(true);
      });
    } catch (e) {
      console.error('[useFabricCanvas] Failed to initialize fabric canvas:', e);
    }

    return () => {
      if (fabricCanvas.current) {
        fabricCanvas.current.dispose();
        fabricCanvas.current = null;
      }
      isInitialized.current = false;
      // CRITICAL: remove StrictMode safety marker on cleanup so re-mount can reinitialize
      if (canvasEl.current) {
        delete (canvasEl.current as any).__fabricCanvas;
      }
    };
  }, []);

  // 仅改离屏/逻辑像素，不直接改展示尺寸（展示由 applyCanvasViewportCss 用 cssOnly 算）
  // NOTE: When loading JSON templates, the buffer dimensions come from the JSON itself.
  // We only sync background here, and let applyCanvasViewportCss handle CSS scaling.
  useEffect(() => {
    if (!fabricCanvas.current) return;
    const c = fabricCanvas.current;
    // Don't override buffer dimensions here — loadFromJSON sets them from the JSON data.
    // Only sync background.
    if (options.background) {
      if (options.background.includes('gradient') || options.background.includes('linear-gradient') || options.background.includes('radial-gradient')) {
        c.setBackgroundColor('', c.renderAll.bind(c));
        if (wrapperEl.current) {
          (wrapperEl.current as any).style.background = options.background;
        }
      } else {
        c.setBackgroundColor(options.background, c.renderAll.bind(c));
        if (wrapperEl.current) {
          (wrapperEl.current as any).style.background = '';
        }
      }
    }
  }, [options.background]);

  /** 画板等比缩放到容器时的基础倍率（相对容器满铺的百分比） */
  const VIEWPORT_FIT_RATIO = 0.85;

  /** Shrink canvas CSS dimensions to fit container.
   *  Directly sets canvas element CSS size — no setDimensions, no transform.
   *  Buffer stays at full resolution. */
  const applyCanvasViewportCss = useCallback(() => {
    const c = fabricCanvas.current;
    if (!c) return;
    c.setZoom(1);
    c.setViewportTransform([1, 0, 0, 1, 0, 0]);
    const w = bufferWRef.current || 1;
    const h = bufferHRef.current || 1;
    if (pixel1to1Ref.current) {
      setZoomPercent(100);
      return;
    }

    const containerEl = optionsRef.current.containerRef?.current;
    if (!containerEl) {
      console.warn('[viewport-v2] No container ref found');
      return;
    }

    const cw = Math.max(1, containerEl.clientWidth);
    const ch = Math.max(1, containerEl.clientHeight);
    const baseFit = Math.min(cw / w, ch / h, 1) * VIEWPORT_FIT_RATIO;
    const zp = zoomPercentRef.current;
    const scale = (zp / 100) * baseFit;

    // Set canvas element CSS size directly — buffer untouched
    const cssW = Math.ceil(w * scale);
    const cssH = Math.ceil(h * scale);
    const el = c.getElement();
    console.log('[viewport]', { cw, ch, bufferW: w, bufferH: h, baseFit, zp, scale, cssW, cssH, elW: el?.style.width, elH: el?.style.height });
    if (el) { el.style.width = `${cssW}px`; el.style.height = `${cssH}px`; }
    if ((c as any).upperCanvasEl) {
      (c as any).upperCanvasEl.style.width = `${cssW}px`;
      (c as any).upperCanvasEl.style.height = `${cssH}px`;
    }
    if ((c as any).lowerCanvasEl) {
      (c as any).lowerCanvasEl.style.width = `${cssW}px`;
      (c as any).lowerCanvasEl.style.height = `${cssH}px`;
    }

    // Wrapper wraps canvas naturally
    const reactWrapperEl = optionsRef.current.wrapperRef?.current;
    if (reactWrapperEl) {
      reactWrapperEl.style.width = `${cssW}px`;
      reactWrapperEl.style.height = `${cssH}px`;
      reactWrapperEl.style.transform = 'none';
    }

    c.calcOffset();
    c.requestRenderAll();
  }, []);

  useEffect(() => {
    if (!isReady || !fabricCanvas.current) return;
    applyCanvasViewportCss();
  }, [isReady, applyCanvasViewportCss, options.width, options.height]);

  useEffect(() => {
    if (!isReady) return;
    // Only observe the OUTER container (viewport) — its size changes when side panels resize.
    // DO NOT observe the wrapper because we control its size programmatically.
    const containerEl = optionsRef.current.containerRef?.current;
    if (!containerEl) return;

    const ro = new ResizeObserver(() => {
      requestAnimationFrame(() => applyCanvasViewportCss());
    });
    ro.observe(containerEl);
    return () => ro.disconnect();
  }, [isReady, applyCanvasViewportCss]);

  // ---- Element Creation ----
  const addRect = useCallback((attrs?: Partial<fabric.IRectOptions>) => {
    const c = fabricCanvas.current;
    if (!c) return;
    const rect = new fabric.Rect({
      left: 100, top: 100, width: 100, height: 100,
      fill: '#6366f1', rx: 0, ry: 0,
      name: '矩形',
      ...attrs,
    });
    c.add(rect);
    rect.setCoords();
    c.setActiveObject(rect);
    c.renderAll();
    console.log('[addRect]', { objs: c.getObjects().length, left: rect.left, top: rect.top, w: rect.width, fill: rect.fill, visible: rect.visible, cssW: c.getElement()?.style.width, cssH: c.getElement()?.style.height });
    return rect;
  }, []);

  const addCircle = useCallback((attrs?: Partial<fabric.ICircleOptions>) => {
    const c = fabricCanvas.current;
    if (!c) return;
    const circle = new fabric.Circle({
      left: 150, top: 100, radius: 50,
      fill: '#8b5cf6',
      name: '圆形',
      ...attrs,
    });
    c.add(circle);
    circle.setCoords();
    c.setActiveObject(circle);
    c.renderAll();
    console.log('[addCircle]', { objs: c.getObjects().length, left: circle.left, top: circle.top, r: circle.radius, cssW: c.getElement()?.style.width });
    return circle;
  }, []);

  const addTriangle = useCallback((attrs?: Partial<fabric.ITriangleOptions>) => {
    const c = fabricCanvas.current;
    if (!c) return;
    const tri = new fabric.Triangle({
      left: 150, top: 100, width: 100, height: 100,
      fill: '#ec4899',
      name: '三角形',
      ...attrs,
    });
    c.add(tri);
    tri.setCoords();
    c.setActiveObject(tri);
    c.renderAll();
    console.log('[addTriangle]', { objs: c.getObjects().length, left: tri.left, top: tri.top, cssW: c.getElement()?.style.width });
    return tri;
  }, []);

  const addText = useCallback((text?: string, attrs?: Partial<fabric.ITextOptions>) => {
    const c = fabricCanvas.current;
    if (!c) return;
    const t = new fabric.IText(text || '双击编辑文字', {
      left: 100, top: 100, fontSize: 24, fill: '#0f172a',
      fontFamily: 'PingFang SC',
      name: '文字',
      ...attrs,
    });
    c.add(t);
    t.setCoords();
    c.setActiveObject(t);
    c.renderAll();
    console.log('[addText]', { objs: c.getObjects().length, left: t.left, top: t.top, fill: t.fill, cssW: c.getElement()?.style.width });
    return t;
  }, []);

  const addImage = useCallback((src: string, attrs?: Partial<fabric.IImageOptions>) => {
    const c = fabricCanvas.current;
    if (!c) return;
    fabric.Image.fromURL(src, (img) => {
      if (!img) return;
      img.set({
        left: attrs?.left ?? 100,
        top: attrs?.top ?? 100,
        name: attrs?.name || '图片',
        ...attrs,
      });
      // Scale if too large
      const maxDim = Math.min(options.width, options.height) * 0.5;
      const w = img.width || 100;
      const h = img.height || 100;
      if (w > maxDim || h > maxDim) {
        const scale = maxDim / Math.max(w, h);
        img.scale(scale);
      }
      c.add(img);
      img.setCoords();
      c.setActiveObject(img);
      c.renderAll();
      console.log('[addImage]', { objs: c.getObjects().length, cssW: c.getElement()?.style.width });
    });
  }, [options.width, options.height]);

  const addLine = useCallback((attrs?: Partial<fabric.ILineOptions>) => {
    const c = fabricCanvas.current;
    if (!c) return;
    const line = new fabric.Line([50, 50, 200, 200], {
      stroke: '#6366f1',
      strokeWidth: 2,
      name: '线条',
      ...attrs,
    });
    c.add(line);
    line.setCoords();
    c.setActiveObject(line);
    c.renderAll();
    return line;
  }, []);

  const addTextbox = useCallback((text?: string, attrs?: Partial<fabric.ITextboxOptions>) => {
    const c = fabricCanvas.current;
    if (!c) return;
    const tb = new fabric.Textbox(text || '多行文本框', {
      left: 100, top: 100, width: 300, fontSize: 18, fill: '#0f172a',
      fontFamily: 'PingFang SC',
      name: '文本框',
      ...attrs,
    });
    c.add(tb);
    tb.setCoords();
    c.setActiveObject(tb);
    c.renderAll();
    return tb;
  }, []);

  // ---- Load Fabric JSON (for templates) ----
  const loadFromJSON = useCallback((jsonStr: string, bgImageUrl?: string) => {
    const c = fabricCanvas.current;
    if (!c) {
      console.warn('[loadFromJSON] canvas not initialized yet');
      return;
    }

    // Handle double-encoded JSON: if input is a quoted string (starts with "), unwrap it
    let inputStr = jsonStr;
    if (typeof inputStr === 'string' && inputStr.startsWith('"') && inputStr.endsWith('"')) {
      try {
        inputStr = JSON.parse(inputStr);
        console.log('[loadFromJSON] Detected and unwrapped double-encoded JSON');
      } catch { /* not a double-encoded string */ }
    }
    // Handle object input (should be stringified first)
    if (typeof inputStr !== 'string') {
      try {
        inputStr = JSON.stringify(inputStr);
        console.log('[loadFromJSON] Converted object input to JSON string');
      } catch (e) {
        console.error('[loadFromJSON] Failed to stringify input:', e);
        return;
      }
    }

    console.log('[loadFromJSON] Input length:', inputStr.length, 'first 100 chars:', inputStr.slice(0, 100));

    const doFitViewport = () => {
      pixel1to1Ref.current = false;
      const w = bufferWRef.current || 1;
      const h = bufferHRef.current || 1;

      const containerEl = optionsRef.current.containerRef?.current;
      if (!containerEl) {
        console.warn('[loadFromJSON-fit] No container ref, keeping 1:1');
        return;
      }
      const cw = Math.max(1, containerEl.clientWidth);
      const ch = Math.max(1, containerEl.clientHeight);
      const scale = Math.min(cw / w, ch / h, 1) * VIEWPORT_FIT_RATIO;

      const cssW = Math.ceil(w * scale);
      const cssH = Math.ceil(h * scale);

      // Set canvas CSS directly
      const el = c.getElement();
      if (el) { el.style.width = `${cssW}px`; el.style.height = `${cssH}px`; }
      if ((c as any).upperCanvasEl) {
        (c as any).upperCanvasEl.style.width = `${cssW}px`;
        (c as any).upperCanvasEl.style.height = `${cssH}px`;
      }
      if ((c as any).lowerCanvasEl) {
        (c as any).lowerCanvasEl.style.width = `${cssW}px`;
        (c as any).lowerCanvasEl.style.height = `${cssH}px`;
      }

      const reactWrapperEl = optionsRef.current.wrapperRef?.current;
      if (reactWrapperEl) {
        reactWrapperEl.style.width = `${cssW}px`;
        reactWrapperEl.style.height = `${cssH}px`;
        reactWrapperEl.style.transform = 'none';
      }

      // Reset child transforms
      if (el) el.style.transform = '';
      c.setZoom(1);
      c.setViewportTransform([1, 0, 0, 1, 0, 0]);
      c.calcOffset();
      c.requestRenderAll();
    };

    const runAfterEnliven = () => {
      // Apply CSS fit only once now — React state change will trigger a second fit via useEffect
      requestAnimationFrame(() => {
        doFitViewport();
        // One more time after images decode
        setTimeout(() => doFitViewport(), 200);
      });
    };

    try {
      c.clear();
      const parsed = JSON.parse(inputStr);

      // Use declared canvas dimensions from JSON only
      const correctW = typeof parsed.width === 'number' ? parsed.width : c.width;
      const correctH = typeof parsed.height === 'number' ? parsed.height : c.height;

      // Save buffer dimensions immediately
      bufferWRef.current = correctW;
      bufferHRef.current = correctH;

      // Resize canvas buffer FIRST, before loading JSON
      c.setDimensions({ width: correctW, height: correctH }, DSET);

      if (parsed.objects) {
        parsed.objects.forEach((obj: any) => {
          obj._isHistoryLoading = true;
        });
      }

      // Load JSON — canvas is already the correct size
      c.loadFromJSON(inputStr, () => {
        c.setZoom(1);
        c.setViewportTransform([1, 0, 0, 1, 0, 0]);
        // Ensure buffer dimensions are correct after loadFromJSON
        c.setDimensions({ width: correctW, height: correctH }, DSET);
        // Update saved buffer dimensions
        bufferWRef.current = correctW;
        bufferHRef.current = correctH;

        const finishLoad = () => {
          // Apply layout background image if provided (grid patterns, full-canvas backgrounds)
          if (bgImageUrl) {
            fabric.Image.fromURL(bgImageUrl, (fabricImg) => {
              if (fabricImg) {
                fabricImg.set({
                  originX: 'left',
                  originY: 'top',
                  left: 0,
                  top: 0,
                  selectable: false,
                  evented: false,
                });
                const imgW = fabricImg.width || 1;
                const imgH = fabricImg.height || 1;
                fabricImg.scaleX = correctW / imgW;
                fabricImg.scaleY = correctH / imgH;

                c.setBackgroundImage(fabricImg, () => {
                  afterTemplateLoad(c);
                  c.requestRenderAll();
                  runAfterEnliven();
                });
              } else {
                // Image failed to load, proceed anyway
                afterTemplateLoad(c);
                c.requestRenderAll();
                runAfterEnliven();
              }
            }, { crossOrigin: 'anonymous' });
          } else {
            if (typeof parsed.background === 'string') {
              c.setBackgroundColor(parsed.background, () => {
                afterTemplateLoad(c);
                c.requestRenderAll();
                runAfterEnliven();
              });
            } else {
              afterTemplateLoad(c);
              c.requestRenderAll();
              runAfterEnliven();
            }
          }
        };

        if (typeof parsed.background === 'string') {
          c.setBackgroundColor(parsed.background, () => {
            finishLoad();
          });
        } else {
          finishLoad();
        }
        setTimeout(() => {
          try {
            const snap = JSON.stringify(c.toJSON(['id', 'name', 'canvasId']));
            historyRef.current = { stack: [snap], idx: 0 };
            setCanUndo(false);
            setCanRedo(false);
          } catch (e) {
            console.warn('loadFromJSON history error:', e);
            historyRef.current = { stack: [], idx: 0 };
          }
        }, 50);
      });
    } catch (e) {
      console.error('loadFromJSON failed:', e);
    }
  }, []);

  // ---- Undo / Redo ----
  const undo = useCallback(() => {
    const c = fabricCanvas.current;
    const h = historyRef.current;
    if (!c || h.idx <= 0) return;
    h.idx--;
    try {
      c.clear();
      c.loadFromJSON(h.stack[h.idx], () => {
        c.setZoom(1);
        c.setViewportTransform([1, 0, 0, 1, 0, 0]);
        c.renderAll();
        setCanUndo(h.idx > 0);
        setCanRedo(true);
        requestAnimationFrame(() => applyCanvasViewportCss());
      });
    } catch (e) {
      console.warn('undo error:', e);
    }
  }, [applyCanvasViewportCss]);

  const redo = useCallback(() => {
    const c = fabricCanvas.current;
    const h = historyRef.current;
    if (!c || h.idx >= h.stack.length - 1) return;
    h.idx++;
    try {
      c.clear();
      c.loadFromJSON(h.stack[h.idx], () => {
        c.setZoom(1);
        c.setViewportTransform([1, 0, 0, 1, 0, 0]);
        c.renderAll();
        setCanUndo(true);
        setCanRedo(h.idx < h.stack.length - 1);
        requestAnimationFrame(() => applyCanvasViewportCss());
      });
    } catch (e) {
      console.warn('redo error:', e);
    }
  }, [applyCanvasViewportCss]);

  // ---- Save / Export ----
  const toJSON = useCallback(() => {
    const c = fabricCanvas.current;
    if (!c) return null;
    return JSON.stringify(c.toJSON(['id', 'name', 'canvasId']));
  }, []);

  const toDataURL = useCallback((format: string = 'png', quality: number = 1) => {
    const c = fabricCanvas.current;
    if (!c) return '';
    return c.toDataURL({ format, quality, multiplier: 2 });
  }, []);

  // ---- Selection helpers ----
  const deselectAll = useCallback(() => {
    fabricCanvas.current?.discardActiveObject();
    fabricCanvas.current?.renderAll();
  }, []);

  const selectObject = useCallback((obj: fabric.Object) => {
    fabricCanvas.current?.setActiveObject(obj);
    fabricCanvas.current?.renderAll();
  }, []);

  const deleteSelected = useCallback(() => {
    const c = fabricCanvas.current;
    if (!c) return;
    c.getActiveObjects().forEach(obj => c.remove(obj));
    c.discardActiveObject();
    c.renderAll();
  }, []);

  const cloneSelected = useCallback(() => {
    const c = fabricCanvas.current;
    if (!c) return;
    c.getActiveObjects().forEach(obj => {
      obj.clone((cloned: fabric.Object) => {
        cloned.set({ left: (obj.left || 0) + 20, top: (obj.top || 0) + 20 });
        c.add(cloned);
        c.setActiveObject(cloned);
      });
    });
    c.renderAll();
  }, []);

  // ---- Layer helpers ----
  const bringForward = useCallback(() => {
    const c = fabricCanvas.current;
    const obj = c?.getActiveObject();
    if (obj && c) { c.bringForward(obj); c.renderAll(); }
  }, []);

  const sendBackward = useCallback(() => {
    const c = fabricCanvas.current;
    const obj = c?.getActiveObject();
    if (obj && c) { c.sendBackwards(obj); c.renderAll(); }
  }, []);

  const bringToFront = useCallback(() => {
    const c = fabricCanvas.current;
    const obj = c?.getActiveObject();
    if (obj && c) { c.bringToFront(obj); c.renderAll(); }
  }, []);

  const sendToBack = useCallback(() => {
    const c = fabricCanvas.current;
    const obj = c?.getActiveObject();
    if (obj && c) { c.sendToBack(obj); c.renderAll(); }
  }, []);

  const getLayerList = useCallback(() => {
    const c = fabricCanvas.current;
    if (!c) return [];
    return [...c.getObjects()]
      .filter(o => (o as any).id !== 'workspace')
      .reverse()
      .map(o => ({
        id: (o as any).id || o.type,
        name: (o as any).name || (o as any).text?.toString()?.slice(0, 20) || o.type,
        type: o.type || 'unknown',
        visible: o.visible !== false,
        locked: !o.selectable,
        _object: o,
      }));
  }, []);

  // ---- Zoom：只改 CSS 展示倍率（相对「适应容器」），不改 buffer，保证命中与导出一致 ----
  const setZoom = useCallback((value: number | ((prev: number) => number)) => {
    pixel1to1Ref.current = false;
    setZoomPercent((prev) => {
      const next = typeof value === 'function' ? (value as (p: number) => number)(prev) : value;
      // Immediately apply CSS scaling with the new zoom value using ref to avoid stale closure
      requestAnimationFrame(() => applyCanvasViewportCss());
      return next;
    });
  }, [applyCanvasViewportCss]);

  /** 在容器内等比缩到全图可见（与左下角 100% 一致） */
  const fitViewportToContainer = useCallback(() => {
    pixel1to1Ref.current = false;
    setZoomPercent(100);
    const c = fabricCanvas.current;
    if (!c) { console.error('[viewport-fit] canvas not found'); return; }

    const containerEl = optionsRef.current.containerRef?.current;
    if (!containerEl) { console.error('[viewport-fit] container ref not found'); return; }
    const w = bufferWRef.current || 1;
    const h = bufferHRef.current || 1;
    const cw = Math.max(1, containerEl.clientWidth);
    const ch = Math.max(1, containerEl.clientHeight);
    if (cw === 0 || ch === 0) { console.error('[viewport-fit] container is 0x0'); return; }
    const scale = Math.min(cw / w, ch / h, 1) * VIEWPORT_FIT_RATIO;

    const cssW = Math.ceil(w * scale);
    const cssH = Math.ceil(h * scale);

    // Set canvas CSS directly
    const el = c.getElement();
    if (el) { el.style.width = `${cssW}px`; el.style.height = `${cssH}px`; }
    if ((c as any).upperCanvasEl) {
      (c as any).upperCanvasEl.style.width = `${cssW}px`;
      (c as any).upperCanvasEl.style.height = `${cssH}px`;
    }
    if ((c as any).lowerCanvasEl) {
      (c as any).lowerCanvasEl.style.width = `${cssW}px`;
      (c as any).lowerCanvasEl.style.height = `${cssH}px`;
    }

    const reactWrapperEl = optionsRef.current.wrapperRef?.current;
    if (reactWrapperEl) {
      reactWrapperEl.style.width = `${cssW}px`;
      reactWrapperEl.style.height = `${cssH}px`;
      reactWrapperEl.style.transform = 'none';
    }

    // Reset child transforms
    if (el) el.style.transform = '';
    c.setZoom(1);
    c.setViewportTransform([1, 0, 0, 1, 0, 0]);
    c.calcOffset();
    c.requestRenderAll();
  }, []);

  /** 1:1 物理像素展示（可能需滚动） */
  const setViewportPixelPerfect = useCallback(() => {
    pixel1to1Ref.current = true;
    setZoomPercent(100);
    const c = fabricCanvas.current;
    if (!c) return;
    const w = bufferWRef.current || 1;
    const h = bufferHRef.current || 1;
    // Restore wrapper to actual buffer size, no scaling
    const reactWrapperEl = optionsRef.current.wrapperRef?.current;
    if (reactWrapperEl) {
      reactWrapperEl.style.width = `${w}px`;
      reactWrapperEl.style.height = `${h}px`;
      reactWrapperEl.style.transform = 'none';
    }
    const el = c.getElement();
    if (el) el.style.transform = '';
    if ((c as any).upperCanvasEl) (c as any).upperCanvasEl.style.transform = '';
    c.calcOffset();
    c.requestRenderAll();
  }, []);

  return {
    // Refs for rendering
    canvasEl,
    wrapperEl,
    fabricCanvas,
    isReady,

    // Selection state
    selectedIds,
    selectedObject,
    canUndo,
    canRedo,

    // Element creation
    addRect,
    addCircle,
    addTriangle,
    addText,
    addTextbox,
    addImage,
    addLine,

    // Template / Save
    loadFromJSON,
    toJSON,
    toDataURL,

    // Actions
    undo,
    redo,
    deselectAll,
    selectObject,
    deleteSelected,
    cloneSelected,

    // Layer
    bringForward,
    sendBackward,
    bringToFront,
    sendToBack,
    getLayerList,
    getLayerTree: () => {
      const c = fabricCanvas.current;
      if (!c) return [];
      return getLayerTree(c);
    },

    // Zoom
    zoomPercent,
    setZoom,
    fitViewportToContainer,
    setViewportPixelPerfect,
  };
}
