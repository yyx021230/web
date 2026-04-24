import { fabric } from 'fabric';

/**
 * 遍历画布上的所有对象（含 Group 子节点）。
 */
export function walkAllObjects(
  root: fabric.Object,
  visit: (o: fabric.Object) => void,
): void {
  visit(root);
  if (root instanceof fabric.Group) {
    root.getObjects().forEach((c) => walkAllObjects(c, visit));
  }
}

/** Layer tree node for hierarchical display */
export interface LayerNode {
  id: string;
  name: string;
  type: string;
  visible: boolean;
  locked: boolean;
  isGroup: boolean;
  children: LayerNode[];
  _object: fabric.Object;
  _depth: number;
}

/**
 * Build a hierarchical layer tree from the canvas objects.
 * Groups become parent nodes with children.
 */
export function getLayerTree(canvas: fabric.Canvas): LayerNode[] {
  const result: LayerNode[] = [];

  // Canvas objects are in bottom-to-top order; reverse for top-to-bottom display
  const objects = [...canvas.getObjects()].filter(o => (o as any).id !== 'workspace').reverse();

  function buildNode(o: fabric.Object, depth: number): LayerNode {
    const typeLabel = (o.type || 'unknown').toLowerCase();
    const name = (o as any).name || (o as any).text?.toString()?.slice(0, 20) || o.type || '';
    const children: LayerNode[] = [];

    if (o instanceof fabric.Group) {
      // Group children: maintain their stacking order
      const groupObjs = [...o.getObjects()].reverse();
      for (const child of groupObjs) {
        children.push(buildNode(child, depth + 1));
      }
    }

    return {
      id: (o as any).id || `${o.type}_${Math.random().toString(36).slice(2, 8)}`,
      name,
      type: typeLabel,
      visible: o.visible !== false,
      locked: !o.selectable,
      isGroup: o instanceof fabric.Group,
      children,
      _object: o,
      _depth: depth,
    };
  }

  for (const o of objects) {
    result.push(buildNode(o, 0));
  }

  return result;
}

/**
 * 将 fabric.Image 统一为「以整幅源图 intrinsic 为 base 尺寸 + scaleX/Y 到稿定外框」。
 * 否则 JSON 里 width/height 小于 natural 时 Fabric 会当裁切，只从左上角取图。
 * 不只在 natural>width 时重算；natural 晚解码、或 w>n 等也一并纠正。
 */
function rebaseOneFabricImage(img: fabric.Image): void {
  const el = img.getElement?.() as HTMLImageElement | undefined;
  if (!el) return;
  let nw: number;
  let nh: number;
  if (typeof img.getOriginalSize === 'function') {
    const s = img.getOriginalSize();
    nw = s.width;
    nh = s.height;
  } else {
    nw = el.naturalWidth || el.width || 0;
    nh = el.naturalHeight || el.height || 0;
  }
  if (!nw || !nh) return;
  const w = img.width ?? 0;
  const h = img.height ?? 0;
  const sx = img.scaleX || 1;
  const sy = img.scaleY || 1;
  if (w <= 0 || h <= 0) return;
  const targetW = w * sx;
  const targetH = h * sy;
  const newSX = targetW / nw;
  const newSY = targetH / nh;
  if (
    Math.abs(nw - w) < 0.01 &&
    Math.abs(nh - h) < 0.01 &&
    Math.abs(sx - newSX) < 1e-3 &&
    Math.abs(sy - newSY) < 1e-3 &&
    !((img as { cropX?: number }).cropX || (img as { cropY?: number }).cropY)
  ) {
    return;
  }
  (img as fabric.Object & { cropX?: number; cropY?: number; dirty?: boolean }).set({
    width: nw,
    height: nh,
    scaleX: newSX,
    scaleY: newSY,
    cropX: 0,
    cropY: 0,
  } as object);
  img.setCoords();
  (img as { dirty?: boolean }).dirty = true;
}

/**
 * 遍历并修正所有 image（含子对象）。
 */
export function normalizeLoadedFabricImages(canvas: fabric.Canvas): void {
  const visit = (o: fabric.Object) => {
    const t = o.type;
    if (t === 'image' || t === 'Image') rebaseOneFabricImage(o as fabric.Image);
  };
  canvas.getObjects().forEach((o) => walkAllObjects(o, visit));
}

/**
 * 模版图里大量文字在 Group 里；默认不开启 subTargetCheck 时只能选到整组，双击打不开字块编辑。
 * 为所有 Group 开启子目标选择；文字保持可选、可事件。
 */
export function enableTemplateGroupAndTextInteractivity(canvas: fabric.Canvas): void {
  const visit = (o: fabric.Object) => {
    if (o.type === 'group' || o.type === 'Group' || o instanceof fabric.Group) {
      o.set({ subTargetCheck: true } as object);
    }
    const t = (o.type || '').toLowerCase();
    if (t === 'textbox' || t === 'i-text' || t === 'text') {
      (o as fabric.Object & { editable?: boolean }).set({
        selectable: true,
        evented: true,
        editable: true,
      } as object);
    }
  };
  canvas.getObjects().forEach((o) => walkAllObjects(o, visit));
}

export function afterTemplateLoad(canvas: fabric.Canvas): void {
  const run = () => {
    normalizeLoadedFabricImages(canvas);
    enableTemplateGroupAndTextInteractivity(canvas);
    canvas.requestRenderAll();
  };
  run();
  // 部分远程图 decode 后才有 natural，晚一帧再收一遍
  requestAnimationFrame(() => {
    run();
  });
  setTimeout(() => {
    run();
  }, 120);
}
