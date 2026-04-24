/**
 * Parse Fabric.js JSON into our editor's ElementAttr[] and LayerItem[]
 */
export interface FabricObject {
  type: string;
  left?: number;
  top?: number;
  width?: number;
  height?: number;
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
  opacity?: number;
  angle?: number;
  text?: string;
  fontSize?: number;
  fontFamily?: string;
  fontWeight?: string | number;
  fontStyle?: string;
  underline?: boolean;
  strikethrough?: boolean;
  textAlign?: string;
  lineHeight?: number;
  selectable?: boolean;
  x1?: number;
  y1?: number;
  x2?: number;
  y2?: number;
  rx?: number;
  ry?: number;
  flipX?: boolean;
  flipY?: boolean;
  scaleX?: number;
  scaleY?: number;
}

export function parseFabricJson(
  fabricJson: string,
  canvasId: string = 'c1'
): { elements: any[]; layers: any[] } {
  const fabric = JSON.parse(fabricJson);
  const elements: any[] = [];
  const layers: any[] = [];
  let counter = 0;

  for (const obj of (fabric.objects || []) as FabricObject[]) {
    counter++;
    const id = `fabric-${counter}`;
    const typeName = obj.type || 'rect';
    const w = obj.width || 100;
    const h = obj.height || 100;

    if (typeName === 'rect') {
      elements.push({
        id, name: '矩形', type: 'rect', canvasId,
        x: obj.left || 0, y: obj.top || 0, w, h,
        angle: obj.angle || 0, opacity: obj.opacity != null ? Math.round(obj.opacity * 100) : 100,
        fill: obj.fill || '#6366f1', strokeWidth: obj.strokeWidth || 0,
        stroke: obj.stroke, borderRadius: (obj.rx || 0),
        shadow: { enabled: false, color: '#000', blur: 0, x: 0, y: 0 },
      });
      layers.push({ id, name: '矩形', type: 'rect', visible: true, locked: !obj.selectable });
    } else if (typeName === 'circle' || typeName === 'ellipse') {
      elements.push({
        id, name: '圆形', type: 'circle', canvasId,
        x: obj.left || 0, y: obj.top || 0, w, h,
        angle: obj.angle || 0, opacity: obj.opacity != null ? Math.round(obj.opacity * 100) : 100,
        fill: obj.fill || '#6366f1', strokeWidth: obj.strokeWidth || 0,
        stroke: obj.stroke,
        shadow: { enabled: false, color: '#000', blur: 0, x: 0, y: 0 },
      });
      layers.push({ id, name: '圆形', type: 'circle', visible: true, locked: !obj.selectable });
    } else if (typeName === 'i-text' || typeName === 'text' || typeName === 'textbox') {
      const textContent = obj.text || '文字';
      elements.push({
        id, name: '文字', type: 'text', canvasId,
        x: obj.left || 0, y: obj.top || 0, w: w || 200, h: h || 30,
        angle: obj.angle || 0, opacity: obj.opacity != null ? Math.round(obj.opacity * 100) : 100,
        fill: obj.fill || '#0f172a', fontFamily: obj.fontFamily || 'PingFang SC',
        fontSize: obj.fontSize || 14, fontWeight: String(obj.fontWeight || 'normal'),
        fontStyle: obj.fontStyle || 'normal',
        underline: obj.underline || false, strikethrough: obj.strikethrough || false,
        textAlign: obj.textAlign || 'left', lineHeight: obj.lineHeight || 1.2,
        text: textContent,
      });
      layers.push({ id, name: textContent.slice(0, 20), type: 'text', visible: true, locked: !obj.selectable });
    } else if (typeName === 'line') {
      const x1 = obj.x1 || 0;
      const y1 = obj.y1 || 0;
      const x2 = obj.x2 || 100;
      const y2 = obj.y2 || 100;
      elements.push({
        id, name: '线条', type: 'line', canvasId,
        x: Math.min(x1, x2), y: Math.min(y1, y2),
        w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
        angle: obj.angle || 0, opacity: obj.opacity != null ? Math.round(obj.opacity * 100) : 100,
        stroke: obj.stroke || '#6366f1', strokeWidth: obj.strokeWidth || 2,
      });
      layers.push({ id, name: '线条', type: 'line', visible: true, locked: !obj.selectable });
    } else if (typeName.toLowerCase() === 'image') {
      elements.push({
        id, name: '图片', type: 'image', canvasId,
        x: obj.left || 0, y: obj.top || 0,
        w: (obj.width || 0) * (obj.scaleX || 1),
        h: (obj.height || 0) * (obj.scaleY || 1),
        angle: obj.angle || 0, opacity: obj.opacity != null ? Math.round(obj.opacity * 100) : 100,
        flipX: obj.flipX || false, flipY: obj.flipY || false,
      });
      layers.push({ id, name: '图片', type: 'image', visible: true, locked: !obj.selectable });
    } else {
      elements.push({
        id, name: typeName, type: 'rect', canvasId,
        x: obj.left || 0, y: obj.top || 0, w, h,
        angle: obj.angle || 0, opacity: obj.opacity != null ? Math.round(obj.opacity * 100) : 100,
        fill: obj.fill || '#6366f1', strokeWidth: obj.strokeWidth || 0,
        stroke: obj.stroke,
        shadow: { enabled: false, color: '#000', blur: 0, x: 0, y: 0 },
      });
      layers.push({ id, name: typeName, type: 'rect', visible: true, locked: !obj.selectable });
    }
  }

  return { elements, layers };
}
