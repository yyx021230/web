'use client';

import { useEffect, useRef, useState } from 'react';

// 这些字体通过 globals.css 中的 @font-face 加载
// Noto Sans SC = Google 版的思源黑体
const FONT_REGULAR = 'SourceHanSansSC-Regular';
const FONT_MEDIUM = 'SourceHanSansSC-Medium';
const FONT_BOLD = 'SourceHanSansSC-Bold';
// AlimamaShuHeiTi not loaded

const gaodingTextStyles = [
  {
    name: '数字大字',
    text: 'NO.1',
    font: FONT_BOLD,
    fontSize: 83.1,
    fontWeight: 700,
    color: '#19315d',
    lineHeight: 1.2,
    letterSpacing: 4.98,
    textAlign: 'left' as const,
  },
  {
    name: '产品名称',
    text: '产品名称',
    font: FONT_BOLD,
    fontSize: 72.6,
    fontWeight: 700,
    color: '#ffffff',
    bgColor: '#19315d',
    lineHeight: 1.2,
    letterSpacing: 11.62,
    textAlign: 'center' as const,
  },
  {
    name: '小标题',
    text: '小标题',
    font: FONT_BOLD,
    fontSize: 68.9,
    fontWeight: 700,
    color: '#ec5b46',
    lineHeight: 1.2,
    letterSpacing: 0,
    textAlign: 'center' as const,
  },
  {
    name: '标签',
    text: '标签',
    font: FONT_BOLD,
    fontSize: 60.5,
    fontWeight: 700,
    color: '#19315d',
    lineHeight: 1.2,
    letterSpacing: 0,
    textAlign: 'center' as const,
  },
  {
    name: '正文',
    text: '作为零食届的大明星，优惠信息满满，千万别错过啦！',
    font: FONT_REGULAR,
    fontSize: 45.9,
    fontWeight: 400,
    color: '#19315d',
    lineHeight: 1.58,
    letterSpacing: 0.46,
    textAlign: 'justify' as const,
  },
];

const richTextSegments = [
  { text: '半价', color: '#19315d' },
  { text: '、', color: '#19315d' },
  { text: '1元买', color: '#ec5b46' },
  { text: '满', color: '#19315d' },
  { text: '199', color: '#ec5b46' },
  { text: '减', color: '#19315d' },
  { text: '50', color: '#ec5b46' },
  { text: '券', color: '#19315d' },
];

export default function FontTestPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [fabricReady, setFabricReady] = useState(false);
  const [fontsLoaded, setFontsLoaded] = useState(false);

  // Wait for fonts to load
  useEffect(() => {
    if (typeof document !== 'undefined' && document.fonts) {
      document.fonts.ready.then(() => {
        setFontsLoaded(true);
      });
    } else {
      setFontsLoaded(true);
    }
  }, []);

  // Fabric.js Canvas
  useEffect(() => {
    if (!fontsLoaded) return;
    let active = true;
    let disposeCanvas: (() => void) | undefined;

    void import('fabric').then(({ fabric }) => {
      if (!active || !canvasRef.current) return;
      const canvas = new fabric.Canvas(canvasRef.current, {
      width: 1242,
      height: 2800,
      backgroundColor: '#f5f5f5',
    });

    let yOffset = 30;
    const scale = 0.33;

    for (const style of gaodingTextStyles) {
      const label = new fabric.Text(`【${style.name}】 ${style.fontSize}px / ${style.font}`, {
        left: 30,
        top: yOffset,
        fontSize: 16,
        fill: '#666',
        fontFamily: FONT_REGULAR,
      });
      canvas.add(label);
      yOffset += 28;

      if (style.bgColor) {
        const bg = new fabric.Rect({
          left: 30,
          top: yOffset,
          width: 400,
          height: style.fontSize * 1.4 * scale,
          fill: style.bgColor,
          rx: 8,
          ry: 8,
        });
        canvas.add(bg);
      }

      const text = new fabric.Text(style.text, {
        left: style.bgColor ? 50 : 30,
        top: yOffset + 5,
        fontSize: Math.round(style.fontSize * scale),
        fontWeight: style.fontWeight === 700 ? 'bold' : 'normal',
        fill: style.color,
        fontFamily: style.font,
        lineHeight: style.lineHeight,
        charSpacing: style.letterSpacing * 10,
        textAlign: style.textAlign,
      });
      canvas.add(text);

      yOffset += Math.round(style.fontSize * scale * style.lineHeight) + 30;

      const divider = new fabric.Line([30, yOffset, (canvas.width || 1242) - 30, yOffset], {
        stroke: '#ddd',
        strokeWidth: 1,
      });
      canvas.add(divider);
      yOffset += 20;
    }

    // Rich text
    const label = new fabric.Text('【富文本 混合颜色】', {
      left: 30,
      top: yOffset,
      fontSize: 16,
      fill: '#666',
      fontFamily: FONT_REGULAR,
    });
    canvas.add(label);
    yOffset += 28;

    const richTextFull = richTextSegments.map(s => s.text).join('');
    const fontSize = Math.round(52 * 0.33);
    const richText = new fabric.IText(richTextFull, {
      left: 30,
      top: yOffset,
      fontSize,
      fontWeight: 'bold',
      fill: '#19315d',
      fontFamily: FONT_BOLD,
      styles: (() => {
        const styleObj: Record<number, Record<string, any>> = {};
        let charIndex = 0;
        for (const seg of richTextSegments) {
          for (let i = 0; i < seg.text.length; i++) {
            styleObj[charIndex] = { fill: seg.color, fontSize, fontWeight: 'bold', fontFamily: FONT_BOLD };
            charIndex++;
          }
        }
        return styleObj;
      })(),
    });
    canvas.add(richText);

      setFabricReady(true);
      canvas.renderAll();
      disposeCanvas = () => canvas.dispose();
    }).catch((error) => {
      if (active) {
        console.error('Failed to load Fabric.js for font preview', error);
        setFabricReady(false);
      }
    });

    return () => {
      active = false;
      disposeCanvas?.();
    };
  }, [fontsLoaded]);

  const scale = (v: number) => Math.round(v / 3);

  return (
    <div className="min-h-screen bg-white p-8">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold mb-2">稿定设计字体样式测试</h1>
        <p className="text-gray-500 mb-2">
          原始字体: AlibabaPuHuiTi-Bold, SourceHanSansSC-Medium, SourceHanSansSC-Regular
        </p>
        <p className="text-gray-500 mb-2">
          已加载: SourceHanSansSC-Regular (Noto Sans SC Regular), SourceHanSansSC-Medium, SourceHanSansSC-Bold
        </p>
        <p className="text-amber-600 mb-8">
          注意: AlimamaShuHeiTi 字体文件未加载，暂用 SourceHanSansSC-Bold 替代
        </p>
        <p className="text-sm text-gray-400 mb-8">
          字体状态: {fontsLoaded ? '✅ 字体已加载' : '⏳ 加载中...'} | Canvas: {fabricReady ? '✅ 已渲染' : '⏳ 等待中'}
        </p>

        {/* 1. CSS 内联 */}
        <section className="mb-10">
          <h2 className="text-xl font-bold mb-4 text-[#19315d]">一、CSS 渲染 (使用 @font-face 字体)</h2>
          <div className="border rounded-xl p-6 space-y-6 bg-gray-50">
            {gaodingTextStyles.map((s, i) => (
              <div key={i}>
                <div className="text-xs text-gray-400 font-mono mb-2">
                  {s.name} | {s.fontSize}px / {s.font} / {s.color} / ls:{s.letterSpacing}px
                </div>
                <div style={{
                  fontFamily: s.font,
                  fontSize: scale(s.fontSize),
                  fontWeight: s.fontWeight,
                  color: s.color,
                  lineHeight: s.lineHeight,
                  letterSpacing: `${scale(s.letterSpacing)}px`,
                  textAlign: s.textAlign,
                  padding: s.bgColor ? '8px 16px' : 0,
                  backgroundColor: s.bgColor || undefined,
                  borderRadius: s.bgColor ? '8px' : undefined,
                  display: s.textAlign === 'center' || s.textAlign === 'justify' ? 'block' : 'inline-block',
                  width: s.textAlign === 'justify' ? '100%' : undefined,
                }}>
                  {s.text}
                </div>
              </div>
            ))}
            <div className="border-t pt-6">
              <div className="text-xs text-gray-400 font-mono mb-2">富文本</div>
              <div className="flex flex-wrap">
                {richTextSegments.map((seg, i) => (
                  <span key={i} style={{
                    fontFamily: FONT_BOLD,
                    fontSize: scale(52),
                    fontWeight: 700,
                    color: seg.color,
                  }}>{seg.text}</span>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* 2. CSS Class */}
        <section className="mb-10">
          <h2 className="text-xl font-bold mb-4 text-[#19315d]">二、CSS Class (gd-text-*)</h2>
          <div className="border rounded-xl p-6 space-y-5 bg-gray-50">
            {[
              { cls: 'gd-text-number', label: '.gd-text-number', text: 'NO.1', override: { fontSize: scale(83.1) } },
              { cls: 'gd-text-product', label: '.gd-text-product', text: '产品名称', override: { fontSize: scale(72.6), background: '#19315d', padding: '8px 16px', borderRadius: '8px', display: 'inline-block' as const } },
              { cls: 'gd-text-subtitle', label: '.gd-text-subtitle', text: '小标题', override: { fontSize: scale(68.9) } },
              { cls: 'gd-text-label', label: '.gd-text-label', text: '标签', override: { fontSize: scale(60.5) } },
              { cls: 'gd-text-body', label: '.gd-text-body', text: '作为零食届的大明星，优惠信息满满，千万别错过啦！', override: { fontSize: scale(45.9) } },
            ].map((item, i) => (
              <div key={i}>
                <div className="text-xs text-gray-400 font-mono mb-1">{item.label}</div>
                <div className={item.cls} style={item.override}>{item.text}</div>
              </div>
            ))}
          </div>
        </section>

        {/* 3. 字体对比 - Regular vs Medium vs Bold */}
        <section className="mb-10">
          <h2 className="text-xl font-bold mb-4 text-[#19315d]">三、字重对比 (Regular / Medium / Bold)</h2>
          <div className="border rounded-xl p-6 space-y-4 bg-gray-50">
            {[
              { label: 'SourceHanSansSC-Regular (正文)', family: FONT_REGULAR, weight: 400 },
              { label: 'SourceHanSansSC-Medium (中等)', family: FONT_MEDIUM, weight: 500 },
              { label: 'SourceHanSansSC-Bold (标题)', family: FONT_BOLD, weight: 700 },
              { label: 'SourceHanSansSC-Bold + fontWeight:bold', family: FONT_BOLD, weight: 700 },
            ].map((item, i) => (
              <div key={i} className="flex items-baseline gap-4 border-b pb-3">
                <span className="text-xs text-gray-400 font-mono w-64 shrink-0">{item.label}</span>
                <span style={{ fontFamily: item.family, fontSize: 28, fontWeight: item.weight, color: '#19315d' }}>
                  作为零食届的大明星 NO.1 产品名称
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* 4. Fabric Canvas */}
        <section className="mb-10">
          <h2 className="text-xl font-bold mb-4 text-[#19315d]">四、Fabric.js Canvas {fabricReady ? '✅' : '⏳'}</h2>
          <div className="border rounded-xl overflow-auto max-h-[800px] bg-gray-50">
            <canvas ref={canvasRef} className="block" />
          </div>
        </section>

        {/* 5. 配色 */}
        <section className="mb-10">
          <h2 className="text-xl font-bold mb-4 text-[#19315d]">五、配色</h2>
          <div className="border rounded-xl p-6 flex gap-6 bg-gray-50">
            {[
              { name: '深蓝', hex: '#19315d' },
              { name: '暖橙', hex: '#ec5b46' },
              { name: '白', hex: '#ffffff' },
              { name: '粉背景', hex: '#e7d6d6' },
            ].map((c, i) => (
              <div key={i} className="text-center">
                <div className="w-20 h-20 rounded-lg shadow border" style={{ backgroundColor: c.hex }} />
                <div className="text-xs font-mono mt-1">{c.hex}</div>
                <div className="text-xs text-gray-500">{c.name}</div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
