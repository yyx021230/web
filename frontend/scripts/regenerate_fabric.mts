/**
 * Regenerate all fabric.json files from design.json using the fixed converter.
 * Run: cd /Users/yyx/ztqc/web/frontend && npx tsx scripts/regenerate_fabric.mts
 */
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'fs';
import { join } from 'path';

const TEMPLATES_DIR = '/Users/yyx/ztqc/web/frontend/public/templates';

function normalizeColor(hex: string): string {
  if (!hex) return '#000000';
  if (hex.length === 9 && hex.startsWith('#')) {
    const a = parseInt(hex.slice(7, 9), 16) / 255;
    if (a >= 0.99) return '#' + hex.slice(1, 7);
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${a.toFixed(2)})`;
  }
  return hex;
}

function getScale(t: any): { scaleX: number; scaleY: number } {
  if (!t) return { scaleX: 1, scaleY: 1 };
  const sx = Math.sqrt(t.a * t.a + t.b * t.b);
  const sy = Math.sqrt(t.c * t.c + t.d * t.d);
  return { scaleX: isFinite(sx) && sx > 0 ? sx : 1, scaleY: isFinite(sy) && sy > 0 ? sy : 1 };
}

function convertText(el: any, absLeft: number, absTop: number): any {
  if (el.hidden) return null;
  const { scaleX, scaleY } = getScale(el.transform);
  let text = el.content || '';
  if (el.contents?.length > 0) text = el.contents.map((c: any) => c.content).join('');
  return {
    type: 'Textbox', text, left: absLeft, top: absTop,
    width: el.width * scaleX, height: el.height * scaleY,
    fill: normalizeColor(el.color || '#000000'),
    fontSize: el.fontSize * 0.75, fontFamily: el.fontFamily || 'PingFang SC',
    fontWeight: (el.fontWeight || 400) >= 500 ? 'bold' : 'normal',
    fontStyle: el.fontStyle === 'italic' ? 'italic' : 'normal',
    lineHeight: el.lineHeight || 1.2, charSpacing: (el.letterSpacing || 0) * 10,
    textAlign: el.textAlign === 'justify' ? 'justify' : (el.textAlign || 'left'),
    angle: 0, opacity: el.opacity, originX: 'left', originY: 'top',
    selectable: !el.lock, id: el.uuid, name: el.title || text.slice(0, 20) || '文字',
    shadow: null, underline: false, linethrough: false, overline: false,
  };
}

function convertImage(src: string, el: any, absLeft: number, absTop: number, name: string): any {
  if (el.hidden || !src) return null;
  const { scaleX, scaleY } = getScale(el.transform);
  const nw = el.naturalWidth || el.width || 100;
  const nh = el.naturalHeight || el.height || 100;
  return {
    type: 'Image', src, left: absLeft, top: absTop,
    width: nw, height: nh,
    scaleX: (el.width * scaleX) / nw, scaleY: (el.height * scaleY) / nh,
    angle: 0, opacity: el.opacity, originX: 'left', originY: 'top',
    selectable: !el.lock, id: el.uuid, name, shadow: null,
  };
}

function convertAny(el: any, gox = 0, goy = 0, visited = new Set<string>()): any {
  const uuid = el.uuid || '';
  if (visited.has(uuid)) return null;
  visited.add(uuid);
  const { scaleX, scaleY } = getScale(el.transform);
  const absLeft = isFinite(gox + el.left * scaleX) ? gox + el.left * scaleX : (el.left || 0);
  const absTop = isFinite(goy + el.top * scaleY) ? goy + el.top * scaleY : (el.top || 0);

  switch (el.type) {
    case 'text': return convertText(el, absLeft, absTop);
    case 'image': return convertImage(el.url, el, absLeft, absTop, '图片');
    case 'svg': return convertImage(el.url, el, absLeft, absTop, '图形');
    case 'path': return el.imageUrl ? convertImage(el.imageUrl, el, absLeft, absTop, el.title || '图形') : null;
    case 'mask': {
      const mi = el.maskInfo;
      if (mi?.showSelf === false) return null;
      if (mi?.enable === false && !el.imageUrl) return null;
      return convertImage(el.imageUrl, el, absLeft, absTop, '遮罩');
    }
    case 'effectText': return convertImage(el.imageUrl, el, absLeft, absTop, '特效文字');
    case 'ninePatch':
      if (el.imageUrl) return convertImage(el.imageUrl, el, absLeft, absTop, el.title || '九宫格');
      if (el.backgroundColor) return { type:'Rect',left:absLeft,top:absTop,width:el.width*scaleX,height:el.height*scaleY,fill:normalizeColor(el.backgroundColor),angle:0,opacity:el.opacity,originX:'left',originY:'top',selectable:!el.lock,id:el.uuid,name:el.title||'九宫格',shadow:null,rx:el.borderRadius||0,ry:el.borderRadius||0 };
      return null;
    case 'group': {
      if (el.hidden) return null;
      const children: any[] = [];
      for (const c of el.elements || []) {
        const conv = convertAny(c, 0, 0, visited);
        if (conv) children.push(conv);
      }
      if (children.length === 0) return null;
      return { type:'Group',left:absLeft,top:absTop,width:el.width,height:el.height,scaleX,scaleY,angle:0,opacity:el.opacity,originX:'left',originY:'top',selectable:!el.lock,id:el.uuid,name:el.title||'组合',objects:children,shadow:null };
    }
    case 'table': case 'tableRow': case 'tableCell': {
      if (el.hidden || !el.elements?.length) return null;
      const children: any[] = [];
      for (const c of el.elements) {
        const cla = el.type === 'table' ? (el.left + c.left) : 0;
        const cta = el.type === 'table' ? (el.top + c.top) : 0;
        const conv = convertAny(c, cla, cta, visited);
        if (conv) children.push(conv);
      }
      if (children.length === 1) return children[0];
      if (children.length > 0) return { type:'Group',left:absLeft,top:absTop,width:el.width*scaleX,height:el.height*scaleY,scaleX:1,scaleY:1,angle:0,opacity:el.opacity,originX:'left',originY:'top',selectable:!el.lock,id:el.uuid||'',name:el.title||'表格',objects:children,shadow:null };
      return null;
    }
    case 'layout': return null;
    default: return el.elements ? convertAny(el, gox, goy, visited) : null;
  }
}

function gaodingToFabric(design: any, folder: string): any {
  const layout = design.global.layout;
  const objects: any[] = [];
  const visited = new Set<string>();

  function rewriteUrl(url: string): string {
    if (!url || !folder || url.startsWith('/templates/') || url.startsWith('data:') || url.startsWith('blob:') || url.startsWith('http://') || url.startsWith('https://')) return url;
    const fn = url.split('?')[0].split('/').pop();
    return fn ? `/templates/${folder}/images/${fn}` : url;
  }
  function rewriteUrls(el: any): void {
    if (el.url && (el.type === 'image' || el.type === 'svg')) el.url = rewriteUrl(el.url);
    if (el.imageUrl && ['path','mask','effectText','ninePatch'].includes(el.type)) el.imageUrl = rewriteUrl(el.imageUrl);
    el.elements?.forEach(rewriteUrls);
  }

  function processLayout(lyt: any): void {
    if (lyt.elements) {
      for (const c of lyt.elements) rewriteUrls(c);
      for (const c of lyt.elements) {
        const conv = convertAny(c, 0, 0, visited);
        if (conv) objects.push(conv);
      }
    }
  }

  if (design.pages?.length) {
    for (const page of design.pages) {
      for (const el of page.elements) {
        if (el.type === 'layout') processLayout(el);
        else { const c = convertAny(el, 0, 0, visited); if (c) objects.push(c); }
      }
    }
  } else if (design.layouts?.length) {
    for (const el of design.layouts) processLayout(el);
  }

  let bg = layout.backgroundColor || '#ffffff';
  if (bg.length === 9) bg = normalizeColor(bg);

  let cw = 1242, ch = 1656;
  if (design.pages?.length) {
    for (const page of design.pages) {
      for (const el of page.elements) {
        if (el.type === 'layout' && el.width > 0 && el.height > 0) { cw = el.width; ch = el.height; break; }
      }
    }
  }

  return { version: '5.3.0', objects, background: bg, width: cw, height: ch };
}

// Main
const folders = readdirSync(TEMPLATES_DIR).filter(f => f.startsWith('gaoding_'));
console.log(`Found ${folders.length} template folders\n`);

let processed = 0, errors = 0;
for (const folder of folders) {
  const designPath = join(TEMPLATES_DIR, folder, 'design.json');
  const fabricPath = join(TEMPLATES_DIR, folder, 'fabric.json');
  if (!existsSync(designPath)) continue;
  try {
    const design = JSON.parse(readFileSync(designPath, 'utf-8'));
    const fabricJson = gaodingToFabric(design, folder);
    writeFileSync(fabricPath, JSON.stringify(fabricJson, null, 2));
    processed++;
    const types: Record<string, number> = {};
    for (const obj of fabricJson.objects) {
      types[obj.type] = (types[obj.type] || 0) + 1;
      for (const sub of obj.objects || []) types[sub.type] = (types[sub.type] || 0) + 1;
    }
    const ts = Object.entries(types).map(([k,v]) => `${k}:${v}`).join(', ');
    console.log(`✓ ${folder} (${fabricJson.objects.length} top, ${ts})`);
  } catch (e: any) { errors++; console.error(`✗ ${folder}: ${e.message}`); }
}
console.log(`\nDone! Processed: ${processed}, Errors: ${errors}`);
