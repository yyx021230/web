"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { fabric } from "fabric";
import { cn } from "@/lib/utils";
import {
  LayoutGrid, Square, Type, ImageIcon, Layers, Wand2,
  Eye, EyeOff, Lock, Unlock, Search, Plus,
  Copy, Trash2, ArrowUp, ArrowDown,
  AlignCenter, AlignLeft, AlignRight, Bold, Italic, Underline,
  Circle, Triangle,
  MinusIcon, Star, Hexagon, ArrowRight, Sparkles,
  Image, Crop,
  ZoomIn, ZoomOut, Palette, Maximize2,
  FlipHorizontal, FlipVertical,
  Loader2, Undo2, Redo2, Save, Download,
  ChevronDown,
} from "lucide-react";
import { useEditorContext } from "@/contexts/EditorContext";
import { editorApi, type Template as BackendTemplate, type Material as BackendMaterial } from "@/services/editorApi";
import { getTemplateList, getTemplateMetaForFolder, type TemplateMeta } from "@/services/templateLoader";
import { gaodingToFabric } from "@/utils/gaodingToFabric";
import { useFabricCanvas } from "@/hooks/useFabricCanvas";

/* ============ Types ============ */

interface CanvasAttr {
  id: string;
  name: string;
  w: number;
  h: number;
  bgColor: string;
  bg?: string;
  bgImage?: string;
  /** Fabric JSON content for this canvas — enables thumbnail previews when inactive */
  contentJson?: string;
}

/* ============ Constants ============ */

const mockBackgrounds = [
  { id: "bg1", name: "纯白", type: "color", value: "#ffffff" },
  { id: "bg2", name: "浅灰", type: "color", value: "#f8fafc" },
  { id: "bg3", name: "深蓝", type: "color", value: "#0f172a" },
  { id: "bg8", name: "暗夜", type: "color", value: "#1a1a2e" },
  { id: "bg9", name: "薄荷绿", type: "color", value: "#d1fae5" },
  { id: "bg10", name: "薰衣草", type: "color", value: "#ede9fe" },
  { id: "bg20", name: "奶油白", type: "color", value: "#fefce8" },
  { id: "bg21", name: "天蓝", type: "color", value: "#e0f2fe" },
  { id: "bg22", name: "玫瑰粉", type: "color", value: "#fce7f3" },
  { id: "bg23", name: "纯黑", type: "color", value: "#000000" },
  { id: "bg24", name: "深绿", type: "color", value: "#052e16" },
  { id: "bg25", name: "暖沙", type: "color", value: "#fef3c7" },
  { id: "bg4", name: "渐变蓝紫", type: "gradient", value: "linear-gradient(135deg, #6366f1, #a855f7)" },
  { id: "bg5", name: "渐变粉橙", type: "gradient", value: "linear-gradient(135deg, #ec4899, #f59e0b)" },
  { id: "bg6", name: "渐变青蓝", type: "gradient", value: "linear-gradient(135deg, #10b981, #3b82f6)" },
  { id: "bg7", name: "暖色渐变", type: "gradient", value: "linear-gradient(135deg, #ef4444, #f59e0b)" },
  { id: "bg30", name: "紫罗兰", type: "gradient", value: "linear-gradient(135deg, #667eea, #764ba2)" },
  { id: "bg31", name: "日落余晖", type: "gradient", value: "linear-gradient(135deg, #f093fb, #f5576c)" },
  { id: "bg32", name: "极光绿", type: "gradient", value: "linear-gradient(135deg, #43e97b, #38f9d7)" },
  { id: "bg33", name: "深海蓝", type: "gradient", value: "linear-gradient(135deg, #0c3483, #a2b6df, #6b8dd6)" },
  { id: "bg34", name: "暮光之城", type: "gradient", value: "linear-gradient(135deg, #4a00e0, #8e2de2)" },
  { id: "bg35", name: "薄荷清新", type: "gradient", value: "linear-gradient(135deg, #96fbc4, #f9f586)" },
  { id: "bg36", name: "暗夜渐变", type: "gradient", value: "linear-gradient(135deg, #232526, #66737a)" },
  { id: "bg37", name: "珊瑚海", type: "gradient", value: "linear-gradient(135deg, #ff9a9e, #fad0c4, #ffd1ff)" },
  { id: "bg38", name: "金属银", type: "gradient", value: "linear-gradient(135deg, #e0e0e0, #bdbdbd, #e0e0e0)" },
  { id: "bg39", name: "赛博朋克", type: "gradient", value: "linear-gradient(135deg, #fc466b, #3f5efb)" },
  { id: "bg11", name: "几何图案", type: "gradient", value: "linear-gradient(135deg, #667eea 25%, #764ba2 25%, #764ba2 50%, #667eea 50%, #667eea 75%, #764ba2 75%)" },
  { id: "bg12", name: "条纹", type: "gradient", value: "repeating-linear-gradient(45deg, #6366f1, #6366f1 10px, #818cf8 10px, #818cf8 20px)" },
  { id: "bg40", name: "点阵网格", type: "gradient", value: "radial-gradient(circle, #d1d5db 1px, transparent 1px)" },
  { id: "bg41", name: "方格纸", type: "gradient", value: "linear-gradient(#e5e7eb 1px, transparent 1px), linear-gradient(90deg, #e5e7eb 1px, transparent 1px)" },
  { id: "bg42", name: "斜纹", type: "gradient", value: "repeating-linear-gradient(-45deg, #f0f0f0, #f0f0f0 5px, #ffffff 5px, #ffffff 10px)" },
  { id: "bg43", name: "同心圆", type: "gradient", value: "radial-gradient(circle at center, #6366f1 2px, transparent 2px)" },
  { id: "bg44", name: "棋盘格", type: "gradient", value: "linear-gradient(45deg, #e5e7eb 25%, transparent 25%), linear-gradient(-45deg, #e5e7eb 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #e5e7eb 75%), linear-gradient(-45deg, transparent 75%, #e5e7eb 75%)" },
];

const elementShapes = [
  { id: "rect", icon: Square, label: "矩形" },
  { id: "circle", icon: Circle, label: "圆形" },
  { id: "triangle", icon: Triangle, label: "三角形" },
  { id: "star", icon: Star, label: "星形" },
  { id: "hexagon", icon: Hexagon, label: "六边形" },
  { id: "line", icon: MinusIcon, label: "线条" },
  { id: "arrow", icon: ArrowRight, label: "箭头" },
  { id: "diamond", icon: LayoutGrid, label: "菱形" },
];

const layerTypeConfig: Record<string, { icon: string; color: string }> = {
  rect: { icon: "▬", color: "bg-blue-100 text-blue-600" },
  circle: { icon: "●", color: "bg-purple-100 text-purple-600" },
  triangle: { icon: "▲", color: "bg-green-100 text-green-600" },
  star: { icon: "★", color: "bg-yellow-100 text-yellow-600" },
  hexagon: { icon: "⬡", color: "bg-teal-100 text-teal-600" },
  line: { icon: "╱", color: "bg-gray-100 text-gray-600" },
  arrow: { icon: "→", color: "bg-orange-100 text-orange-600" },
  diamond: { icon: "◆", color: "bg-indigo-100 text-indigo-600" },
  text: { icon: "T", color: "bg-amber-100 text-amber-600" },
  image: { icon: "🖼", color: "bg-pink-100 text-pink-600" },
  group: { icon: "▤", color: "bg-cyan-100 text-cyan-600" },
};

/* ============ 艺术字样式定义 ============ */
/**
 * 设计思路：艺术字 = 描边 + 投影 + 纹理 + 渐变 + 发光 + 3D + 背景框
 * 每种样式是这些基础效果的组合
 *
 * fabricProps 使用纯 JSON 定义（不使用 fabric.* 对象），
 * 在 onClick 中动态创建 fabric.Gradient / fabric.Shadow
 */

interface GradientDef {
  type: 'linear' | 'radial';
  coords: { x1: number; y1: number; x2: number; y2: number };
  colorStops: { offset: number; color: string }[];
}

interface ShadowDef {
  color: string;
  blur: number;
  offsetX: number;
  offsetY: number;
}

interface ArtTextStyleDef {
  id: string;
  name: string;
  sample: string;
  /** 卡片背景 */
  cardBg?: React.CSSProperties;
  /** 预览文字大小 */
  fontSize?: number;
  /** 字重 */
  fontWeight?: string;
  /** Fabric 属性（纯 JSON，运行时转换为 fabric.Gradient/fabric.Shadow） */
  fabricProps: {
    fill?: string | GradientDef;
    fontWeight?: string;
    fontSize?: number;
    shadow?: ShadowDef;
    stroke?: string;
    strokeWidth?: number;
  };
  /** 效果标签 */
  effects: string[];
}

/** 将 JSON 定义的 fabricProps 转换为 Fabric.js 对象 */
function convertFabricProps(props: ArtTextStyleDef['fabricProps']): Partial<fabric.ITextOptions> {
  const result: Partial<fabric.ITextOptions> = {};
  if (props.fill) {
    if (typeof props.fill === 'object' && 'type' in props.fill) {
      result.fill = new fabric.Gradient({
        type: props.fill.type,
        coords: props.fill.coords,
        colorStops: props.fill.colorStops,
      });
    } else {
      result.fill = props.fill;
    }
  }
  if (props.fontWeight) result.fontWeight = props.fontWeight;
  if (props.fontSize) result.fontSize = props.fontSize;
  if (props.stroke) result.stroke = props.stroke;
  if (props.strokeWidth) result.strokeWidth = props.strokeWidth;
  if (props.shadow) {
    result.shadow = new fabric.Shadow({
      color: props.shadow.color,
      blur: props.shadow.blur,
      offsetX: props.shadow.offsetX,
      offsetY: props.shadow.offsetY,
    });
  }
  return result;
}

const artTextStyles: ArtTextStyleDef[] = [
  // ===== 电商类 =====
  {
    id: 'ecom-gold-red', name: '金红大促', sample: '限时抢购',
    cardBg: { background: 'linear-gradient(135deg, #c0392b 0%, #e74c3c 100%)' },
    fontSize: 28, fontWeight: 'bold',
    fabricProps: {
      fill: { type: 'linear' as const, coords: { x1: 0, y1: 0, x2: 0, y2: 40 },
        colorStops: [
          { offset: 0, color: '#f7d774' },
          { offset: 0.3, color: '#e8b84f' },
          { offset: 0.6, color: '#c8952e' },
          { offset: 1, color: '#f7d774' },
        ],
      },
      fontWeight: 'bold', fontSize: 48,
      shadow: { color: 'rgba(0,0,0,0.5)', blur: 4, offsetX: 0, offsetY: 2 },
    },
    effects: ['渐变', '投影', '背景'],
  },
  {
    id: 'ecom-flash-sale', name: '闪电促销', sample: '全场5折',
    cardBg: { background: 'linear-gradient(135deg, #f39c12 0%, #e74c3c 100%)' },
    fontSize: 28, fontWeight: 'bold',
    fabricProps: {
      fill: '#ffffff', fontWeight: 'bold', fontSize: 48,
      shadow: { color: 'rgba(0,0,0,0.3)', blur: 4, offsetX: 0, offsetY: 3 },
    },
    effects: ['投影', '背景'],
  },
  {
    id: 'ecom-neon-sale', name: '霓虹促销', sample: '爆款热卖',
    cardBg: { background: '#1a1a2e' },
    fontSize: 28, fontWeight: 'bold',
    fabricProps: {
      fill: { type: 'linear' as const, coords: { x1: 0, y1: 0, x2: 200, y2: 0 },
        colorStops: [
          { offset: 0, color: '#f7d774' },
          { offset: 0.5, color: '#f0c27f' },
          { offset: 1, color: '#e8b84f' },
        ],
      },
      fontWeight: 'bold', fontSize: 48,
      shadow: { color: 'rgba(240,194,127,0.5)', blur: 12, offsetX: 0, offsetY: 0 },
    },
    effects: ['渐变', '发光'],
  },

  // ===== 节日类 =====
  {
    id: 'fest-new-year', name: '春节喜庆', sample: '新年快乐',
    cardBg: { background: 'linear-gradient(135deg, #c0392b 0%, #a93226 100%)' },
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: { type: 'linear' as const, coords: { x1: 0, y1: 0, x2: 0, y2: 40 },
        colorStops: [
          { offset: 0, color: '#ffd700' },
          { offset: 0.4, color: '#ff8c00' },
          { offset: 0.7, color: '#ffd700' },
          { offset: 1, color: '#ffcc00' },
        ],
      },
      fontWeight: 'bold', fontSize: 48,
      shadow: { color: 'rgba(0,0,0,0.5)', blur: 4, offsetX: 0, offsetY: 2 },
    },
    effects: ['渐变', '投影'],
  },
  {
    id: 'fest-christmas', name: '圣诞铃铛', sample: '圣诞快乐',
    cardBg: { background: 'linear-gradient(135deg, #1a5e1a 0%, #2d8e2d 100%)' },
    fontSize: 28, fontWeight: 'bold',
    fabricProps: {
      fill: '#ffffff', fontWeight: 'bold', fontSize: 48,
      shadow: { color: 'rgba(255,255,255,0.5)', blur: 8, offsetX: 0, offsetY: 0 },
    },
    effects: ['发光', '投影'],
  },

  // ===== 酷炫类 =====
  {
    id: 'cool-cyber-neon', name: '赛博霓虹', sample: '赛博朋克',
    cardBg: { background: '#0a0a0a' },
    fontSize: 28, fontWeight: 'bold',
    fabricProps: {
      fill: '#ffffff', fontWeight: 'bold', fontSize: 48,
      shadow: { color: '#0fa', blur: 8, offsetX: 0, offsetY: 0 },
    },
    effects: ['发光', '霓虹'],
  },
  {
    id: 'cool-pink-neon', name: '粉色霓虹', sample: '粉色霓虹',
    cardBg: { background: '#0a0a0a' },
    fontSize: 28, fontWeight: 'normal',
    fabricProps: {
      fill: '#ffffff', fontWeight: 'normal', fontSize: 48,
      shadow: { color: '#ff00de', blur: 10, offsetX: 0, offsetY: 0 },
    },
    effects: ['发光', '霓虹'],
  },
  {
    id: 'cool-blue-tech', name: '蓝色科技', sample: '未来科技',
    cardBg: { background: 'linear-gradient(135deg, #0a0a1a 0%, #0d1b2a 100%)' },
    fontSize: 28, fontWeight: 'bold',
    fabricProps: {
      fill: '#00d4ff', fontWeight: 'bold', fontSize: 48,
      shadow: { color: 'rgba(0,212,255,0.6)', blur: 15, offsetX: 0, offsetY: 0 },
    },
    effects: ['发光'],
  },
  {
    id: 'cool-fire-text', name: '火焰文字', sample: '燃烧',
    cardBg: { background: 'linear-gradient(180deg, #0a0a0a 0%, #1a0505 100%)' },
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: { type: 'linear' as const, coords: { x1: 0, y1: 0, x2: 0, y2: 50 },
        colorStops: [
          { offset: 0, color: '#ffffff' },
          { offset: 0.15, color: '#fff700' },
          { offset: 0.4, color: '#ff8800' },
          { offset: 0.7, color: '#ff0000' },
          { offset: 1, color: '#8b0000' },
        ],
      },
      fontWeight: 'bold', fontSize: 52,
      shadow: { color: 'rgba(255,136,0,0.6)', blur: 8, offsetX: 0, offsetY: 0 },
    },
    effects: ['渐变', '发光'],
  },
  {
    id: 'cool-ice-text', name: '冰霜文字', sample: '冰霜',
    cardBg: { background: 'linear-gradient(180deg, #0a1628 0%, #0d2137 100%)' },
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: { type: 'linear' as const, coords: { x1: 0, y1: 0, x2: 0, y2: 50 },
        colorStops: [
          { offset: 0, color: '#ffffff' },
          { offset: 0.2, color: '#b3e5fc' },
          { offset: 0.5, color: '#4fc3f7' },
          { offset: 0.8, color: '#0288d1' },
          { offset: 1, color: '#01579b' },
        ],
      },
      fontWeight: 'bold', fontSize: 52,
      shadow: { color: 'rgba(79,195,247,0.5)', blur: 12, offsetX: 0, offsetY: 0 },
    },
    effects: ['渐变', '发光'],
  },

  // ===== 金属类 =====
  {
    id: 'metal-gold', name: '黄金质感', sample: '黄金',
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: { type: 'linear' as const, coords: { x1: 0, y1: 0, x2: 0, y2: 50 },
        colorStops: [
          { offset: 0, color: '#f7d774' },
          { offset: 0.1, color: '#c8952e' },
          { offset: 0.2, color: '#f7d774' },
          { offset: 0.35, color: '#e8b84f' },
          { offset: 0.5, color: '#f7d774' },
          { offset: 0.65, color: '#c8952e' },
          { offset: 0.8, color: '#f7d774' },
          { offset: 0.9, color: '#a87b22' },
          { offset: 1, color: '#f7d774' },
        ],
      },
      fontWeight: 'bold', fontSize: 52,
      shadow: { color: 'rgba(0,0,0,0.5)', blur: 4, offsetX: 0, offsetY: 2 },
    },
    effects: ['渐变', '投影'],
  },
  {
    id: 'metal-rose-gold', name: '玫瑰金', sample: '玫瑰金',
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: { type: 'linear' as const, coords: { x1: 0, y1: 0, x2: 0, y2: 50 },
        colorStops: [
          { offset: 0, color: '#f5c6a0' },
          { offset: 0.15, color: '#c8816a' },
          { offset: 0.3, color: '#f5c6a0' },
          { offset: 0.45, color: '#e8a87c' },
          { offset: 0.6, color: '#f5c6a0' },
          { offset: 0.75, color: '#b87355' },
          { offset: 1, color: '#f5c6a0' },
        ],
      },
      fontWeight: 'bold', fontSize: 52,
      shadow: { color: 'rgba(0,0,0,0.5)', blur: 4, offsetX: 0, offsetY: 2 },
    },
    effects: ['渐变', '投影'],
  },
  {
    id: 'metal-silver', name: '银色金属', sample: '银色',
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: { type: 'linear' as const, coords: { x1: 0, y1: 0, x2: 0, y2: 50 },
        colorStops: [
          { offset: 0, color: '#e8e8e8' },
          { offset: 0.15, color: '#a0a0a0' },
          { offset: 0.3, color: '#e8e8e8' },
          { offset: 0.45, color: '#c0c0c0' },
          { offset: 0.6, color: '#e8e8e8' },
          { offset: 0.75, color: '#909090' },
          { offset: 1, color: '#e8e8e8' },
        ],
      },
      fontWeight: 'bold', fontSize: 52,
      shadow: { color: 'rgba(0,0,0,0.5)', blur: 4, offsetX: 0, offsetY: 2 },
    },
    effects: ['渐变', '投影'],
  },

  // ===== 3D立体 =====
  {
    id: '3d-red', name: '红色3D', sample: '3D立体',
    cardBg: { background: 'linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)' },
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: '#e74c3c', fontWeight: 'bold', fontSize: 52,
      shadow: { color: '#922b21', blur: 0, offsetX: 5, offsetY: 5 },
    },
    effects: ['3D', '投影'],
  },
  {
    id: '3d-blue', name: '蓝色3D', sample: '蓝色3D',
    cardBg: { background: 'linear-gradient(135deg, #d4fc79 0%, #96e6a1 100%)' },
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: '#2980b9', fontWeight: 'bold', fontSize: 52,
      shadow: { color: '#1a5276', blur: 0, offsetX: 5, offsetY: 5 },
    },
    effects: ['3D', '投影'],
  },
  {
    id: '3d-candy', name: '糖果3D', sample: '糖果3D',
    cardBg: { background: 'linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)' },
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: '#ff6b9d', fontWeight: 'bold', fontSize: 52,
      shadow: { color: '#e84393', blur: 0, offsetX: 0, offsetY: 6 },
    },
    effects: ['3D', '投影'],
  },
  {
    id: '3d-heavymetal', name: '重金属3D', sample: '重金属',
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: { type: 'linear' as const, coords: { x1: 0, y1: 0, x2: 0, y2: 50 },
        colorStops: [
          { offset: 0, color: '#e8e8e8' },
          { offset: 0.3, color: '#a0a0a0' },
          { offset: 0.6, color: '#c0c0c0' },
          { offset: 1, color: '#909090' },
        ],
      },
      fontWeight: 'bold', fontSize: 52,
      shadow: { color: '#555', blur: 0, offsetX: 5, offsetY: 5 },
    },
    effects: ['渐变', '3D', '投影'],
  },

  // ===== 描边类（用 Fabric shadow 模拟外轮廓描边，不用 stroke） =====
  {
    id: 'stroke-white-black', name: '白字黑描边', sample: '经典描边',
    cardBg: { background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' },
    fontSize: 28, fontWeight: 'bold',
    fabricProps: {
      fill: '#ffffff', fontWeight: 'bold', fontSize: 52,
      shadow: { color: 'rgba(0,0,0,0.8)', blur: 6, offsetX: 0, offsetY: 0 },
    },
    effects: ['投影', '描边'],
  },
  {
    id: 'stroke-hollow', name: '空心镂空', sample: '空心文字',
    cardBg: { background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)' },
    fontSize: 28, fontWeight: 'bold',
    fabricProps: {
      fill: 'transparent', fontWeight: 'bold', fontSize: 52,
      stroke: '#f0c27f', strokeWidth: 2,
    },
    effects: ['描边'],
  },

  // ===== 可爱类 =====
  {
    id: 'cute-kawaii', name: '卡哇伊', sample: '可爱文字',
    cardBg: { background: 'linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)' },
    fontSize: 30, fontWeight: 'normal',
    fabricProps: {
      fill: '#ff6b9d', fontWeight: 'normal', fontSize: 52,
      shadow: { color: 'rgba(255,107,157,0.4)', blur: 4, offsetX: 0, offsetY: 2 },
    },
    effects: ['投影'],
  },
  {
    id: 'cute-bubble', name: '泡泡字', sample: '泡泡',
    cardBg: { background: 'linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)' },
    fontSize: 30, fontWeight: 'normal',
    fabricProps: {
      fill: '#ffffff', fontWeight: 'normal', fontSize: 52,
      shadow: { color: 'rgba(161,140,209,0.5)', blur: 6, offsetX: 0, offsetY: 3 },
    },
    effects: ['投影', '发光'],
  },

  // ===== 复古类 =====
  {
    id: 'retro-poster', name: '复古海报', sample: '复古风格',
    cardBg: { background: 'linear-gradient(180deg, #2c1810 0%, #1a0f0a 100%)' },
    fontSize: 30, fontWeight: 'bold',
    fabricProps: {
      fill: { type: 'linear' as const, coords: { x1: 0, y1: 0, x2: 0, y2: 50 },
        colorStops: [
          { offset: 0, color: '#f7d774' },
          { offset: 0.5, color: '#c8952e' },
          { offset: 1, color: '#a87b22' },
        ],
      },
      fontWeight: 'bold', fontSize: 52,
      shadow: { color: 'rgba(0,0,0,0.5)', blur: 4, offsetX: 0, offsetY: 2 },
    },
    effects: ['渐变', '投影'],
  },

  // ===== 游戏/像素 =====
  {
    id: 'game-pixel', name: '像素风', sample: 'PIXEL',
    cardBg: { background: 'linear-gradient(135deg, #2d1b69 0%, #11998e 100%)' },
    fontSize: 22, fontWeight: 'normal',
    fabricProps: {
      fill: '#ffffff', fontWeight: 'normal', fontSize: 32,
      shadow: { color: '#ff0044', blur: 0, offsetX: 3, offsetY: 3 },
    },
    effects: ['投影'],
  },
  {
    id: 'game-arcade', name: '街机风', sample: 'ARCADE',
    cardBg: { background: '#1a1a1a' },
    fontSize: 22, fontWeight: 'normal',
    fabricProps: {
      fill: '#ffff00', fontWeight: 'normal', fontSize: 32,
      shadow: { color: '#ff8800', blur: 8, offsetX: 0, offsetY: 0 },
    },
    effects: ['发光', '投影'],
  },
];

const textColors = ["#0f172a", "#64748b", "#94a3b8", "#ffffff", "#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#8b5cf6", "#ec4899", "#06b6d4"];
const shapeDefaultColors = ["#6366f1", "#8b5cf6", "#ec4899", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#06b6d4"];

/** 字体选择器数据 — 每种字体用实际字体显示预览 */
const allFonts = [
  { value: 'system-ui, -apple-system, sans-serif', label: '系统黑体', preview: '预览 Preview' },
  { value: '"Noto Sans SC", sans-serif', label: '思源黑体', preview: '预览 Preview' },
  { value: '"Noto Serif SC", serif', label: '思源宋体', preview: '预览 Preview' },
  { value: '"Songti SC", serif', label: '系统宋体', preview: '预览 Preview' },
  { value: '"Ma Shan Zheng", cursive', label: '马善政毛笔', preview: '预览 Preview' },
  { value: '"Long Cang", cursive', label: '龙藏草书', preview: '预览 Preview' },
  { value: '"Zhi Mang Xing", cursive', label: '志莽行书', preview: '预览 Preview' },
  { value: '"ZCOOL KuaiLe", cursive', label: '站酷快乐体', preview: '预览 Preview' },
  { value: '"ZCOOL XiaoWei", serif', label: '站酷小薇体', preview: '预览 Preview' },
  { value: '"Pacifico", cursive', label: 'Pacifico', preview: 'Preview' },
  { value: '"Dancing Script", cursive', label: 'Dancing', preview: 'Preview' },
  { value: '"Lobster", cursive', label: 'Lobster', preview: 'Preview' },
  { value: '"Fredoka One", cursive', label: 'Fredoka', preview: 'Preview' },
  { value: '"Bebas Neue", cursive', label: 'Bebas', preview: 'PREVIEW' },
  { value: '"Playfair Display", serif', label: 'Playfair', preview: 'Preview' },
  { value: '"Orbitron", sans-serif', label: 'Orbitron', preview: 'PREVIEW' },
  { value: '"Black Ops One", cursive', label: 'Black Ops', preview: 'PREVIEW' },
  { value: '"Press Start 2P", cursive', label: 'Pixel', preview: 'PREVIEW' },
  { value: 'Arial', label: 'Arial', preview: 'Preview' },
  { value: 'Georgia', label: 'Georgia', preview: 'Preview' },
  { value: 'Verdana', label: 'Verdana', preview: 'Preview' },
];
/** 与稿定 layouts 常见画板一致，全编辑器默认画板 */
const DEFAULT_CANVAS_W = 1242;
const DEFAULT_CANVAS_H = 1656;

const presetSizes = [
  { name: "手机海报", w: 1080, h: 1920, ratio: "9:16", cat: "海报" },
  { name: "横版海报", w: 1920, h: 1080, ratio: "16:9", cat: "海报" },
  { name: "小红书配图", w: 1242, h: 1656, ratio: "3:4", cat: "社交媒体" },
  { name: "公众号首图", w: 900, h: 383, ratio: "2.35:1", cat: "社交媒体" },
  { name: "公众号次图", w: 500, h: 500, ratio: "1:1", cat: "社交媒体" },
  { name: "文章长图", w: 1080, h: 3000, ratio: "9:25", cat: "社交媒体" },
  { name: "PPT 演示", w: 1920, h: 1080, ratio: "16:9", cat: "演示" },
  { name: "PPT 标准", w: 1920, h: 1440, ratio: "4:3", cat: "演示" },
  { name: "抖音封面", w: 1080, h: 1440, ratio: "3:4", cat: "视频" },
  { name: "B站封面", w: 1920, h: 1080, ratio: "16:9", cat: "视频" },
  { name: "名片", w: 900, h: 540, ratio: "5:3", cat: "印刷" },
  { name: "A4 文档", w: 794, h: 1123, ratio: "A4", cat: "印刷" },
];

/* ============ 文字特效选择器 ============ */

/** 预设文字特效模板 */
const TEXT_EFFECT_PRESETS = [
  { id: 'none', name: '无特效', icon: '✕' },
  { id: 'shadow-basic', name: '基础投影', shadow: { color: 'rgba(0,0,0,0.3)', blur: 4, offsetX: 2, offsetY: 2 } },
  { id: 'shadow-heavy', name: '重投影', shadow: { color: 'rgba(0,0,0,0.5)', blur: 8, offsetX: 3, offsetY: 3 } },
  { id: 'glow-blue', name: '蓝色发光', shadow: { color: 'rgba(59,130,246,0.6)', blur: 12, offsetX: 0, offsetY: 0 } },
  { id: 'glow-red', name: '红色发光', shadow: { color: 'rgba(239,68,68,0.5)', blur: 10, offsetX: 0, offsetY: 0 } },
  { id: 'glow-green', name: '绿色发光', shadow: { color: 'rgba(34,197,94,0.5)', blur: 10, offsetX: 0, offsetY: 0 } },
  { id: 'glow-purple', name: '紫色发光', shadow: { color: 'rgba(168,85,247,0.5)', blur: 12, offsetX: 0, offsetY: 0 } },
  { id: 'neon-cyan', name: '霓虹青', shadow: { color: '#0fa', blur: 8, offsetX: 0, offsetY: 0 } },
  { id: 'neon-pink', name: '霓虹粉', shadow: { color: '#ff00de', blur: 10, offsetX: 0, offsetY: 0 } },
  { id: '3d-red', name: '红色3D', shadow: { color: '#922b21', blur: 0, offsetX: 5, offsetY: 5 } },
  { id: '3d-blue', name: '蓝色3D', shadow: { color: '#1a5276', blur: 0, offsetX: 5, offsetY: 5 } },
  { id: '3d-dark', name: '深色3D', shadow: { color: '#333', blur: 0, offsetX: 4, offsetY: 4 } },
  { id: 'stroke-black', name: '白字黑描边', stroke: '#000000', strokeWidth: 3 },
  { id: 'stroke-red', name: '红描边', stroke: '#ef4444', strokeWidth: 2 },
  { id: 'stroke-gold', name: '金描边', stroke: '#f59e0b', strokeWidth: 2 },
  { id: 'stroke-white', name: '黑字白描边', stroke: '#ffffff', strokeWidth: 3 },
  { id: 'combo-shadow-stroke', name: '投影+描边', shadow: { color: 'rgba(0,0,0,0.4)', blur: 4, offsetX: 2, offsetY: 2 }, stroke: '#ffffff', strokeWidth: 2 },
  { id: 'combo-glow-stroke', name: '发光+描边', shadow: { color: 'rgba(59,130,246,0.5)', blur: 8, offsetX: 0, offsetY: 0 }, stroke: '#ffffff', strokeWidth: 2 },
];

interface TextEffectPickerProps {
  selectedEl: Record<string, any>;
  updateProp: (key: string, value: any) => void;
}

function TextEffectPicker({ selectedEl, updateProp }: TextEffectPickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const applyEffect = (preset: typeof TEXT_EFFECT_PRESETS[number]) => {
    if (preset.id === 'none') {
      updateProp('shadow', undefined);
      updateProp('stroke', undefined);
      updateProp('strokeWidth', 0);
      setOpen(false);
      return;
    }
    if (preset.shadow) {
      updateProp('shadow', new fabric.Shadow({
        color: preset.shadow.color,
        blur: preset.shadow.blur,
        offsetX: preset.shadow.offsetX,
        offsetY: preset.shadow.offsetY,
      }));
    } else {
      updateProp('shadow', undefined);
    }
    if (preset.stroke) {
      updateProp('stroke', preset.stroke);
      updateProp('strokeWidth', preset.strokeWidth || 1);
    } else if (preset.id !== 'none') {
      // Only reset stroke if this preset doesn't define one
      updateProp('stroke', undefined);
      updateProp('strokeWidth', 0);
    }
    setOpen(false);
  };

  const hasShadow = !!selectedEl._fabricObject?.shadow;
  const hasStroke = selectedEl.stroke && selectedEl.strokeWidth > 0;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between rounded-lg border bg-background px-3 py-2 text-sm hover:border-primary/50 transition-colors"
      >
        <span className="text-xs">
          {!hasShadow && !hasStroke && '无特效'}
          {hasShadow && !hasStroke && '投影'}
          {!hasShadow && hasStroke && '描边'}
          {hasShadow && hasStroke && '投影 + 描边'}
        </span>
        <ChevronDown className="h-4 w-4 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute top-full left-0 right-0 z-50 mt-1 bg-white rounded-lg border shadow-lg max-h-72 overflow-y-auto">
          <div className="grid grid-cols-2 gap-1 p-2">
            {TEXT_EFFECT_PRESETS.map(preset => {
              const isActive = (preset.id === 'none' && !hasShadow && !hasStroke) ||
                (preset.id.startsWith('shadow') && hasShadow && !hasStroke) ||
                (preset.id.startsWith('glow') && hasShadow && !hasStroke) ||
                (preset.id.startsWith('neon') && hasShadow && !hasStroke) ||
                (preset.id.startsWith('3d') && hasShadow && !hasStroke) ||
                (preset.id.startsWith('stroke') && hasStroke && !hasShadow) ||
                (preset.id.startsWith('combo') && hasShadow && hasStroke);
              return (
                <button
                  key={preset.id}
                  onClick={() => applyEffect(preset)}
                  className={`rounded-md px-2 py-1.5 text-xs text-left transition-colors ${
                    isActive ? 'bg-primary/10 text-primary font-medium border border-primary/20' : 'hover:bg-accent border border-transparent'
                  }`}
                >
                  {preset.name}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ============ Component ============ */

export default function EditorPage() {
  const ctx = useEditorContext();

  /* ===== Sidebar state ===== */
  const [activeLeftTab, setActiveLeftTab] = useState("templates");
  const [activeRightTab, setActiveRightTab] = useState("attr");
  const [selectedShape, setSelectedShape] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [templateCat, setTemplateCat] = useState("全部");
  const [materialCat, setMaterialCat] = useState("全部");
  const [bgCat, setBgCat] = useState("全部");
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiSize, setAiSize] = useState("1:1");
  const [aiStyle, setAiStyle] = useState("写实");

  /* Backend data */
  const [backendTemplates, setBackendTemplates] = useState<BackendTemplate[]>([]);
  const [backendMaterials, setBackendMaterials] = useState<BackendMaterial[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [loadingMaterials, setLoadingMaterials] = useState(true);

  /* Gaoding templates */
  const [gaodingTemplates, setGaodingTemplates] = useState<TemplateMeta[]>([]);
  const [loadingGaoding, setLoadingGaoding] = useState(true);
  const [loadingTemplate, setLoadingTemplate] = useState(false);

  /* Canvas state (multi-canvas) */
  const [canvases, setCanvases] = useState<CanvasAttr[]>([
    { id: "c1", name: "画板 1", w: DEFAULT_CANVAS_W, h: DEFAULT_CANVAS_H, bgColor: "#e8edf5" },
  ]);
  const [activeCanvasId, setActiveCanvasId] = useState("c1");
  const activeCanvas = canvases.find(c => c.id === activeCanvasId) ?? canvases[0];
  const canvasW = activeCanvas?.w || DEFAULT_CANVAS_W;
  const canvasH = activeCanvas?.h || DEFAULT_CANVAS_H;

  // Refs for save function — ensures we always read latest values regardless of closure timing
  const canvasesRef = useRef(canvases);
  canvasesRef.current = canvases;
  const activeCanvasIdRef = useRef(activeCanvasId);
  activeCanvasIdRef.current = activeCanvasId;

  /* Size modal */
  const [showSizeTemplateModal, setShowSizeTemplateModal] = useState(false);

  /** 当前正在编辑的设计稿 ID（从草稿箱打开时记录，保存时用于覆盖而不是新建） */
  const [editingMaterialId, setEditingMaterialId] = useState<number | null>(null);
  const editingMaterialIdRef = useRef<number | null>(null);
  editingMaterialIdRef.current = editingMaterialId;

  /* ===== Fabric Canvas Hook ===== */
  const viewportRef = useRef<HTMLDivElement>(null);
  const canvasWrapperRef = useRef<HTMLDivElement>(null);
  /** Increments on every template load to force re-fit even when dimensions don't change */
  const [templateLoadKey, setTemplateLoadKey] = useState(0);

  // CRITICAL: Force dimensions if somehow they became 0
  const safeW = canvasW > 0 ? canvasW : DEFAULT_CANVAS_W;
  const safeH = canvasH > 0 ? canvasH : DEFAULT_CANVAS_H;

  const canvasKey = useRef(`canvas-${Date.now()}`).current;

  const fabricHook = useFabricCanvas({
    width: safeW,
    height: safeH,
    background: activeCanvas.bg ?? activeCanvas.bgColor,
    containerRef: viewportRef,
    wrapperRef: canvasWrapperRef,
    onSelectionChange: () => {
      // Auto-switch right panel based on selection
    },
  });

  /* ===== 全局键盘快捷键 ===== */
  useEffect(() => {
    let clipboardData: string | null = null;

    function handleKeyDown(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      const cmdOrCtrl = isMac ? e.metaKey : e.ctrlKey;

      // 撤销: Cmd/Ctrl + Z
      if (cmdOrCtrl && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        fabricHook.undo();
        return;
      }
      // 重做: Cmd/Ctrl + Shift + Z  或  Cmd/Ctrl + Y
      if ((cmdOrCtrl && e.key === 'z' && e.shiftKey) || (cmdOrCtrl && e.key === 'y')) {
        e.preventDefault();
        fabricHook.redo();
        return;
      }
      // 复制: Cmd/Ctrl + C
      if (cmdOrCtrl && e.key === 'c') {
        const active = fabricHook.fabricCanvas.current?.getActiveObject();
        if (active) {
          e.preventDefault();
          try { clipboardData = JSON.stringify(active.toJSON()); } catch { /* ignore */ }
        }
        return;
      }
      // 粘贴: Cmd/Ctrl + V
      if (cmdOrCtrl && e.key === 'v') {
        if (clipboardData) {
          e.preventDefault();
          try {
            const canvas = fabricHook.fabricCanvas.current;
            if (!canvas) return;
            const tmpObj = JSON.parse(clipboardData);
            tmpObj.left = (tmpObj.left || 0) + 20;
            tmpObj.top = (tmpObj.top || 0) + 20;
            canvas.loadFromJSON(JSON.stringify({ version: '5.3.0', objects: [tmpObj] }), () => {
              canvas.renderAll();
            });
          } catch { /* ignore */ }
        }
        return;
      }
      // 快速复制副本: Cmd/Ctrl + D
      if (cmdOrCtrl && e.key === 'd') {
        e.preventDefault();
        fabricHook.cloneSelected();
        return;
      }
      // 全选: Cmd/Ctrl + A
      if (cmdOrCtrl && e.key === 'a') {
        e.preventDefault();
        const canvas = fabricHook.fabricCanvas.current;
        if (canvas) {
          canvas.discardActiveObject();
          const all = canvas.getObjects().filter(o => o.selectable !== false);
          if (all.length > 0) {
            const activeSel = new fabric.ActiveSelection(all, { canvas });
            canvas.setActiveObject(activeSel);
            canvas.renderAll();
          }
        }
        return;
      }
      // 删除: Delete 或 Backspace
      if (e.key === 'Delete' || e.key === 'Backspace') {
        const active = fabricHook.fabricCanvas.current?.getActiveObject();
        if (active) {
          e.preventDefault();
          fabricHook.deleteSelected();
          return;
        }
      }
      // 保存: Cmd/Ctrl + S
      if (cmdOrCtrl && e.key === 's') {
        e.preventDefault();
        ctx.triggerSave();
        return;
      }
    }

    // 拦截浏览器默认的粘贴事件（支持外部图片粘贴、文本粘贴）
    function handlePaste(e: ClipboardEvent) {
      const canvas = fabricHook.fabricCanvas.current;
      if (!canvas) return;
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      const items = e.clipboardData?.items;
      if (items) {
        for (let i = 0; i < items.length; i++) {
          if (items[i].type.indexOf('image') !== -1) {
            e.preventDefault();
            const blob = items[i].getAsFile();
            if (blob) {
              const reader = new FileReader();
              reader.onload = () => {
                fabricHook.addImage(reader.result as string, {
                  left: (canvas.width || 1242) / 2 - 50,
                  top: (canvas.height || 1656) / 2 - 50,
                });
              };
              reader.readAsDataURL(blob);
            }
            return;
          }
        }
      }

      const text = e.clipboardData?.getData('text');
      if (text && !(canvas.getActiveObject() as any)?.isEditing) {
        e.preventDefault();
        fabricHook.addText(text, {
          left: (canvas.width || 1242) / 2 - 50,
          top: (canvas.height || 1656) / 2 - 15,
        });
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('paste', handlePaste);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('paste', handlePaste);
    };
  }, [fabricHook, ctx]);

  /* ===== Fetch backend data ===== */
  useEffect(() => {
    setLoadingTemplates(true);
    editorApi.getTemplates()
      .then(res => setBackendTemplates(res.data?.items ?? []))
      .catch(() => setBackendTemplates([]))
      .finally(() => setLoadingTemplates(false));

    setLoadingMaterials(true);
    editorApi.getMaterials(undefined, 1, 100, true)
      .then(res => setBackendMaterials(res.data?.items ?? []))
      .catch(() => setBackendMaterials([]))
      .finally(() => setLoadingMaterials(false));
  }, []);

  /* ===== Fetch gaoding templates ===== */
  useEffect(() => {
    setLoadingGaoding(true);
    getTemplateList()
      .then(list => {
        console.log('[Editor] Loaded gaoding templates:', list.length);
        // Sort by object_count descending for richer templates first
        list.sort((a, b) => ((a as any).object_count || 0) - ((b as any).object_count || 0)).reverse();
        setGaodingTemplates(list);
      })
      .catch(e => {
        console.error("[Editor] Failed to load gaoding templates:", e);
        setGaodingTemplates([]);
      })
      .finally(() => setLoadingGaoding(false));
  }, []);

  /* ===== Load a gaoding template — ALWAYS use runtime design.json conversion ===== */
  const handleLoadGaodingTemplate = useCallback(async (meta: TemplateMeta) => {
    if (!confirm(`使用模板 "${meta.title}"？当前编辑内容将被覆盖。`)) return;

    setLoadingTemplate(true);
    try {
      // Step 1: Fetch design.json
      const designUrl = `/templates/${meta.folder}/design.json`;
      const dres = await fetch(designUrl, { cache: 'no-store' });
      if (!dres.ok) throw new Error(`Failed to load design.json: ${dres.status}`);
      const designJson = await dres.json();

      // Step 2: Preprocess SVGs (replace {{colors[N]}} placeholders) — shared URL cache
      const svgCache: Record<string, string> = {};
      async function preprocessSvg(el: Record<string, unknown>): Promise<void> {
        const type = el.type as string;
        if (type === 'svg' && typeof el.url === 'string') {
          const originalUrl = el.url as string;
          const colors = (el.colors as string[]) || [];
          if (colors.length > 0) {
            if (svgCache[originalUrl]) {
              el.url = svgCache[originalUrl];
            } else {
              const filename = originalUrl.split('/').pop()?.split('?')[0];
              const localUrl = filename ? `/templates/${meta.folder}/images/${filename}` : originalUrl;
              try {
                const res = await fetch(localUrl, { cache: 'no-store' });
                if (res.ok) {
                  el.url = localUrl;
                  svgCache[originalUrl] = localUrl;
                }
              } catch { /* ignore */ }
            }
          }
        }
        if (Array.isArray(el.elements)) {
          for (const child of el.elements) await preprocessSvg(child as Record<string, unknown>);
        }
        if (Array.isArray(el.layouts)) {
          for (const item of el.layouts) await preprocessSvg(item as Record<string, unknown>);
        }
        if (Array.isArray(el.pages)) {
          for (const item of el.pages) await preprocessSvg(item as Record<string, unknown>);
        }
      }
      await preprocessSvg(designJson as Record<string, unknown>);

      // Step 3: Runtime conversion — design.json → Fabric JSON
      const { fabricJson, bgImageUrl } = gaodingToFabric(designJson as any, meta.folder);

      console.log(`[handleLoadGaodingTemplate] ${meta.folder}: ${fabricJson.objects.length} objects, canvas ${fabricJson.width}x${fabricJson.height}, bg: ${fabricJson.background}`);

      const cw = fabricJson.width || DEFAULT_CANVAS_W;
      const ch = fabricJson.height || DEFAULT_CANVAS_H;

      // Load content with background image
      fabricHook.loadFromJSON(JSON.stringify(fabricJson), bgImageUrl);

      // Use the fabric JSON background color if available
      const bgColor = typeof fabricJson.background === 'string' ? fabricJson.background : "#ffffff";

      // Update React state so wrapper div + status bar show correct dimensions
      setCanvases(prev => prev.map(c => c.id === "c1" ? { ...c, w: cw, h: ch, bgColor } : c));

      // Bump template load key to force re-fit via useEffect (even if dimensions didn't change)
      setTemplateLoadKey(k => k + 1);
    } catch (e) {
      console.error("Failed to load template:", e);
      alert("模板加载失败: " + (e as Error).message);
    } finally {
      setLoadingTemplate(false);
    }
  }, [fabricHook, ctx]);

  /* ===== Load template from sessionStorage (after canvas is ready) ===== */
  const templateLoadedRef = useRef(false);

  useEffect(() => {
    if (!fabricHook.isReady || templateLoadedRef.current) return;

    const tpl = sessionStorage.getItem("selectedTemplate");
    if (tpl) {
      templateLoadedRef.current = true;
      try {
        const data = JSON.parse(tpl);
        if (data.name) ctx.setProjectName(data.name);

        if (data.folder) {
          (async () => {
            const meta = await getTemplateMetaForFolder(data.folder);
            // Runtime conversion — design.json → Fabric JSON
            const designUrl = `/templates/${meta.folder}/design.json`;
            const dres = await fetch(designUrl, { cache: 'no-store' });
            if (!dres.ok) throw new Error(`Failed to load design.json: ${dres.status}`);
            const designJson = await dres.json();
            const svgCache: Record<string, string> = {};
            async function preprocessSvg(el: Record<string, unknown>): Promise<void> {
              const type = el.type as string;
              if (type === 'svg' && typeof el.url === 'string') {
                const originalUrl = el.url as string;
                const colors = (el.colors as string[]) || [];
                if (colors.length > 0) {
                  if (svgCache[originalUrl]) {
                    el.url = svgCache[originalUrl];
                  } else {
                    const filename = originalUrl.split('/').pop()?.split('?')[0];
                    const localUrl = filename ? `/templates/${meta.folder}/images/${filename}` : originalUrl;
                    try {
                      const res = await fetch(localUrl, { cache: 'no-store' });
                      if (res.ok) {
                        el.url = localUrl;
                        svgCache[originalUrl] = localUrl;
                      }
                    } catch { /* ignore */ }
                  }
                }
              }
              if (Array.isArray(el.elements)) for (const c of el.elements) await preprocessSvg(c as Record<string, unknown>);
              if (Array.isArray(el.layouts)) for (const c of el.layouts) await preprocessSvg(c as Record<string, unknown>);
              if (Array.isArray(el.pages)) for (const c of el.pages) await preprocessSvg(c as Record<string, unknown>);
            }
            await preprocessSvg(designJson as Record<string, unknown>);
            const { fabricJson, bgImageUrl } = gaodingToFabric(designJson as any, meta.folder);
            fabricHook.loadFromJSON(JSON.stringify(fabricJson), bgImageUrl);
            const bgColor = typeof fabricJson.background === 'string' ? fabricJson.background : "#ffffff";
            setCanvases(prev => prev.map(c => c.id === "c1" ? { ...c, w: fabricJson.width, h: fabricJson.height, bgColor } : c));
            setTemplateLoadKey(k => k + 1);
          })().catch(e => {
            console.error("Failed to load template:", e);
          });
        } else if (data.fabric_json) {
          // Legacy path: load content first, then resize
          fabricHook.loadFromJSON(data.fabric_json);
          if (data.width && data.height) {
            setCanvases(prev => prev.map(c => c.id === "c1" ? { ...c, w: data.width, h: data.height } : c));
          }
        }
      } catch (e) {
        console.error("Failed to load template:", e);
      } finally {
        sessionStorage.removeItem("selectedTemplate");
      }
    } else {
      // 检查 URL 参数中是否有 designId（从草稿箱打开设计稿）
      const urlParams = new URLSearchParams(window.location.search);
      const designId = urlParams.get('designId');
      if (designId) {
        const matId = Number(designId);
        setEditingMaterialId(matId);
        editorApi.getMaterial(matId)
          .then(res => {
            const m = res.data;
            if (m && m.design_json) {
              const design = m.design_json as any;
              ctx.setProjectName(design.projectName || m.name);
              // 加载画布信息
              if (design.canvases && design.canvases.length > 0) {
                // 恢复多画布状态
                const restoredCanvases = design.canvases.map((c: any) => ({
                  id: c.id,
                  name: c.name,
                  w: c.width,
                  h: c.height,
                  bgColor: c.bgColor || '#ffffff',
                  contentJson: c.contentJson,
                }));
                setCanvases(restoredCanvases);
                // 恢复激活画布
                if (design.activeCanvasId) {
                  setActiveCanvasId(design.activeCanvasId);
                }
                // 加载激活画布的 Fabric JSON
                const activeCanvas = restoredCanvases.find((c: any) => c.id === (design.activeCanvasId || restoredCanvases[0].id));
                if (activeCanvas?.contentJson) {
                  // contentJson 已经是 JSON 字符串（fabricHook.toJSON() 返回），不要再次 stringify
                  const jsonStr = typeof activeCanvas.contentJson === 'string'
                    ? activeCanvas.contentJson
                    : JSON.stringify(activeCanvas.contentJson);
                  console.log('[Editor] 加载画布内容，contentJson 类型:', typeof activeCanvas.contentJson, '长度:', activeCanvas.contentJson.length);
                  fabricHook.loadFromJSON(jsonStr);
                }
                setTemplateLoadKey(k => k + 1);
              }
              console.log('[Editor] 设计稿已从草稿箱加载:', m.name);
            }
          })
          .catch(e => {
            console.error('Failed to load design from drafts:', e);
          });
      } else {
      // Try loading saved project — but don't block if backend is unavailable
      editorApi.getProjects(1, 1)
        .then(res => {
          if (res.data?.items?.length > 0) {
            const project = res.data.items[0];
            ctx.setProjectName(project.name);
            ctx.setProjectId(project.id);
            return editorApi.getProject(project.id);
          }
          return null;
        })
        .then(detailRes => {
          if (!detailRes?.data?.fabric_json) return;
          // Only load JSON, don't touch canvas dimensions
          fabricHook.loadFromJSON(detailRes.data.fabric_json);
        })
        .catch(() => {
          // Backend might not be running — this is OK
          console.log("[Editor] Backend not available, using blank canvas");
        });
      }
    }
  }, [fabricHook.isReady]);

  /* ===== Sync canvas content to state after Fabric hook is ready and content loaded ===== */
  useEffect(() => {
    if (!fabricHook.isReady) return;

    const timer = setTimeout(() => {
      try {
        const json = fabricHook.toJSON();
        if (json) {
          setCanvases(prev => prev.map(c =>
            c.id === activeCanvasId ? { ...c, contentJson: json } : c
          ));
        }
      } catch (e) {
        console.warn('Failed to sync canvas content to state:', e);
      }
    }, 1500); // wait for async template loading to complete

    return () => clearTimeout(timer);
  }, [fabricHook.isReady, activeCanvasId]); // CRITICAL: don't include fabricHook object in deps — it changes every render

  /* ===== Sync undo/redo to context ===== */
  useEffect(() => {
    ctx._setCanUndo(fabricHook.canUndo);
    ctx._setCanRedo(fabricHook.canRedo);
  }, [fabricHook.canUndo, fabricHook.canRedo]);

  /* ===== Trigger viewport CSS when canvas dimensions change (e.g., after template load) ===== */
  useEffect(() => {
    if (!fabricHook.isReady) return;
    // Delay to allow React to re-render the wrapper div with new dimensions
    const timer = setTimeout(() => {
      fabricHook.fitViewportToContainer();
    }, 100);
    return () => clearTimeout(timer);
  }, [canvasW, canvasH, templateLoadKey]); // Re-fit when dimensions change OR template is loaded

  /* ===== Register undo/redo/save in context ===== */
  useEffect(() => {
    ctx._setUndoFn(fabricHook.undo);
    ctx._setRedoFn(fabricHook.redo);
    ctx._setSaveFn(async () => {
      const currentCanvases = canvasesRef.current;
      const currentActiveCanvasId = activeCanvasIdRef.current;
      const currentEditingMaterialId = editingMaterialIdRef.current;

      ctx.setHasUnsavedChanges(false);
      ctx.setIsSaving(true);
      try {
        // 先保存当前激活画布的内容到 canvases 状态
        const activeJson = fabricHook.toJSON();
        console.log('[Save] activeJson 长度:', activeJson?.length ?? 'null/undefined');

        const updatedCanvases = currentCanvases.map(c =>
          c.id === currentActiveCanvasId ? { ...c, contentJson: activeJson || c.contentJson } : c
        );

        // 构建完整的设计稿 JSON（包含所有画布及其内容）
        const designJson = {
          version: "1.0",
          saveTime: new Date().toISOString(),
          projectName: ctx.projectName,
          activeCanvasId: currentActiveCanvasId,
          canvases: updatedCanvases.map(c => ({
            id: c.id,
            name: c.name,
            width: c.w,
            height: c.h,
            bgColor: c.bgColor,
            contentJson: c.contentJson,  // 每个画布的完整 Fabric JSON
          })),
        };

        console.log('[Save] designJson canvases:', designJson.canvases.length, '个画布, materialId:', currentEditingMaterialId);

        // 生成缩略图（当前激活画布）
        const thumbnail = fabricHook.toDataURL("jpeg", 0.3);
        const activeCanvasData = updatedCanvases.find(c => c.id === currentActiveCanvasId);

        // 保存逻辑：有 editingMaterialId 时覆盖，否则新建
        if (currentEditingMaterialId) {
          await editorApi.updateMaterial(currentEditingMaterialId, {
            name: ctx.projectName,
            design_json: designJson,
            thumbnail,
            width: activeCanvasData?.w,
            height: activeCanvasData?.h,
          });
          console.log('[Save] 设计稿已覆盖更新, materialId:', currentEditingMaterialId);
          alert('✅ 已保存');
        } else {
          const res = await editorApi.saveDesign({
            name: ctx.projectName,
            design_json: designJson,
            thumbnail,
            width: activeCanvasData?.w,
            height: activeCanvasData?.h,
          });
          // 新建后记录 ID，后续保存将覆盖同一条
          if (res?.data?.id) {
            setEditingMaterialId(res.data.id);
            console.log('[Save] 设计稿已新建到草稿箱, ID:', res.data.id);
          } else {
            console.warn('[Save] 新建成功但返回数据中无 id, res.data:', res?.data);
          }
          alert('✅ 已保存到草稿箱');
        }
      } catch (e) {
        const errorMsg = (e as Error)?.message || '保存失败';
        console.error("Save failed:", e);
        alert('保存失败: ' + errorMsg + '\n已保存到浏览器本地缓存');
        // 保存失败时降级到 localStorage
        try {
          const activeJson = fabricHook.toJSON();
          const curCanvases = canvasesRef.current;
          const curActiveId = activeCanvasIdRef.current;
          localStorage.setItem("editor_draft", JSON.stringify({
            canvases: curCanvases.map(c =>
              c.id === curActiveId ? { ...c, contentJson: activeJson } : c
            ),
            activeCanvasId: curActiveId,
            projectName: ctx.projectName,
          }));
        } catch { /* ignore */ }
      } finally {
        ctx.setIsSaving(false);
      }
    });
  }, [fabricHook]); // Refs used internally — only need fabricHook to register undo/redo/save

  /* ===== Selection for property panel ===== */
  const [selectedEl, setSelectedEl] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    const obj = fabricHook.selectedObject;
    if (!obj) {
      setSelectedEl(null);
      return;
    }
    setSelectedEl({
      type: obj.type,
      name: (obj as any).name || obj.type,
      left: Math.round(obj.left || 0),
      top: Math.round(obj.top || 0),
      width: Math.round((obj.width || 0) * (obj.scaleX || 1)),
      height: Math.round((obj.height || 0) * (obj.scaleY || 1)),
      angle: Math.round(obj.angle || 0),
      opacity: Math.round((obj.opacity ?? 1) * 100),
      fill: obj.fill as string | undefined,
      stroke: obj.stroke as string | undefined,
      strokeWidth: obj.strokeWidth || 0,
      text: obj.type?.includes("text") ? (obj as any).text : undefined,
      fontSize: (obj as any).fontSize,
      fontFamily: (obj as any).fontFamily,
      fontWeight: (obj as any).fontWeight,
      fontStyle: (obj as any).fontStyle,
      underline: (obj as any).underline,
      strikethrough: (obj as any).strikethrough,
      textAlign: (obj as any).textAlign,
      flipX: obj.flipX || false,
      flipY: obj.flipY || false,
      _fabricObject: obj,
    });
  }, [fabricHook.selectedObject, fabricHook.selectedIds.length]);

  /* ===== Element creation ===== */
  const makeShape = useCallback((shapeId: string) => {
    const cx = canvasW / 2 - 50;
    const cy = canvasH / 2 - 50;
    switch (shapeId) {
      case "rect": return fabricHook.addRect({ left: cx, top: cy });
      case "circle": return fabricHook.addCircle({ left: cx, top: cy });
      case "triangle": return fabricHook.addTriangle({ left: cx, top: cy });
      case "line": return fabricHook.addLine({ left: cx, top: cy });
      case "diamond":
        return fabricHook.addRect({ left: cx, top: cy, width: 100, height: 100, angle: 45, fill: "#6366f1", name: "菱形" });
      case "star":
      case "hexagon":
        return fabricHook.addRect({ left: cx, top: cy, fill: "#f59e0b", name: shapeId });
      case "arrow":
        return fabricHook.addRect({ left: cx, top: cy, width: 120, height: 30, fill: "#3b82f6", name: "箭头", rx: 4, ry: 4 });
      default: return fabricHook.addRect({ left: cx, top: cy });
    }
  }, [canvasW, canvasH, fabricHook]);

  /* ===== Update element property ===== */
  const updateProp = useCallback((key: string, value: any) => {
    const obj = fabricHook.selectedObject;
    if (!obj) return;
    (obj as any).set(key, value);
    fabricHook.fabricCanvas.current?.renderAll();
    setSelectedEl(prev => prev ? { ...prev, [key]: value } : null);
  }, [fabricHook]);

  /* ===== Layer list ===== */
  const layerList = fabricHook.getLayerList();
  const totalLayerCount = layerList.length;

  /* ===== Multi-canvas ===== */
  const switchToCanvas = useCallback((id: string) => {
    const c = canvases.find(x => x.id === id);
    if (!c) return;

    // Save current active canvas content before switching
    if (fabricHook.fabricCanvas.current && activeCanvasId !== id) {
      try {
        const json = fabricHook.toJSON();
        if (json) {
          setCanvases(prev => prev.map(x =>
            x.id === activeCanvasId ? { ...x, contentJson: json } : x
          ));
        }
      } catch (e) {
        console.warn('Failed to save canvas content before switch:', e);
      }
    }

    setActiveCanvasId(id);

    // Load target canvas content
    if (c.contentJson && fabricHook.isReady) {
      fabricHook.loadFromJSON(c.contentJson);
    }
  }, [canvases, activeCanvasId, fabricHook, fabricHook.isReady]);

  const addCanvas = useCallback(() => {
    const newId = `c${Date.now()}`;
    const colors = ["#e8edf5", "#fff3cd", "#d1fae5", "#ede9fe", "#fce7f3"];
    const newBg = colors[canvases.length % colors.length];
    setCanvases(prev => [...prev, { id: newId, name: `画板 ${prev.length + 1}`, w: DEFAULT_CANVAS_W, h: DEFAULT_CANVAS_H, bgColor: newBg }]);
    setActiveCanvasId(newId);
  }, [canvases.length]);

  const duplicateCanvas = useCallback((id: string) => {
    const src = canvases.find(c => c.id === id);
    if (!src) return;
    const newId = `c${Date.now()}`;
    setCanvases(prev => [...prev, { ...src, id: newId, name: src.name + " 副本", contentJson: id === activeCanvasId ? (fabricHook.toJSON() || src.contentJson) : src.contentJson }]);
    setActiveCanvasId(newId);
  }, [canvases, activeCanvasId, fabricHook]);

  const deleteCanvasFn = useCallback((id: string) => {
    if (canvases.length <= 1) return;
    const next = canvases.filter(c => c.id !== id);
    setCanvases(next);
    if (activeCanvasId === id) {
      setActiveCanvasId(next[0].id);
    }
  }, [canvases, activeCanvasId]);

  const resizeCanvas = useCallback((w: number, h: number) => {
    setCanvases(prev => prev.map(c => c.id === activeCanvasId ? { ...c, w, h } : c));
  }, [activeCanvasId]);

  /* ===== Export ===== */
  const handleExport = useCallback(() => {
    const dataUrl = fabricHook.toDataURL("png", 1);
    const link = document.createElement("a");
    link.download = `${ctx.projectName || "design"}.png`;
    link.href = dataUrl;
    link.click();
  }, [fabricHook, ctx.projectName]);

  /* ===== Filter backend data ===== */
  const templateCategoryMap: Record<string, string> = {
    poster: "海报", social: "社交媒体", card: "卡片", banner: "电商", presentation: "演示",
  };
  const materialCategoryMap: Record<string, string> = {
    decoration: "装饰", arrow: "箭头", shape: "形状", interface: "界面",
  };

  const filteredTemplates = backendTemplates.filter(t => {
    const catLabel = templateCategoryMap[t.category] || t.category;
    const matchCat = templateCat === "全部" || catLabel === templateCat;
    const matchSearch = t.name.toLowerCase().includes(searchQuery.toLowerCase());
    return matchCat && matchSearch;
  });

  const filteredMaterials = backendMaterials.filter(m => {
    const catLabel = materialCategoryMap[m.category ?? ""] || m.category || "";
    const matchCat = materialCat === "全部" || catLabel === materialCat;
    const matchSearch = m.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (m.tags || []).some(tag => tag.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchCat && matchSearch;
  });

  /* ===== Render ===== */
  return (
    <div className="flex flex-col h-screen bg-background">
      {/* ===== TOP BAR ===== */}
      <div className="flex items-center justify-between border-b bg-card px-4" style={{ height: 48 }}>
        <div className="flex items-center gap-3">
          <Sparkles className="h-5 w-5 text-primary" />
          <span className="text-sm font-medium">{ctx.projectName}</span>
          {ctx.hasUnsavedChanges && <span className="text-[10px] text-muted-foreground">· 未保存</span>}
          {ctx.isSaving && <span className="text-[10px] text-primary">保存中...</span>}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={fabricHook.undo} disabled={!fabricHook.canUndo} className="p-1.5 rounded hover:bg-accent disabled:opacity-30" title="撤销">
            <Undo2 className="h-4 w-4" />
          </button>
          <button onClick={fabricHook.redo} disabled={!fabricHook.canRedo} className="p-1.5 rounded hover:bg-accent disabled:opacity-30" title="重做">
            <Redo2 className="h-4 w-4" />
          </button>
          <div className="h-4 w-px bg-border mx-1" />
          <button onClick={() => ctx.triggerSave()} className="p-1.5 rounded hover:bg-accent" title="保存">
            <Save className="h-4 w-4" />
          </button>
          <button onClick={handleExport} className="p-1.5 rounded hover:bg-accent" title="导出">
            <Download className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* ===== MAIN 3-PANEL AREA ===== */}
      <div className="flex flex-1 min-h-0">

        {/* ===== LEFT PANEL (280px) ===== */}
        <div className="flex w-72 shrink-0 flex-col border-r bg-card">
          {/* Horizontal tabs at TOP (like original) */}
          <div className="flex border-b bg-card shrink-0">
            {[
              { id: "templates", icon: LayoutGrid, label: "模板" },
              { id: "elements", icon: Square, label: "元素" },
              { id: "text", icon: Type, label: "文字" },
              { id: "materials", icon: ImageIcon, label: "素材" },
              { id: "backgrounds", icon: Palette, label: "背景" },
              { id: "layers", icon: Layers, label: "图层" },
              { id: "ai", icon: Wand2, label: "AI" },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => { setActiveLeftTab(tab.id); setSearchQuery(""); }}
                className={cn(
                  "flex-1 flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium transition-colors border-b-2",
                  activeLeftTab === tab.id ? "text-primary border-primary" : "text-muted-foreground border-transparent hover:text-foreground"
                )}
              >
                <tab.icon className="h-4 w-4" />
                {tab.label}
              </button>
            ))}
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-auto">

            {/* === Templates === */}
            {activeLeftTab === "templates" && (
              <div className="p-3">
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input type="text" placeholder="搜索模板..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} className="w-full rounded-lg border bg-background py-2 pl-9 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
                </div>

                {/* Tabs: gaoding / backend */}
                <div className="flex gap-1.5 mb-3 flex-wrap">
                  <button
                    onClick={() => setTemplateCat("全部")}
                    className={cn("rounded-full px-2.5 py-1 text-xs transition-colors", templateCat === "全部" ? "bg-primary/10 text-primary font-medium" : "bg-muted hover:bg-primary/10 hover:text-primary")}
                  >
                    稿定模板 ({gaodingTemplates.length})
                  </button>
                  <button
                    onClick={() => setTemplateCat("后端")}
                    className={cn("rounded-full px-2.5 py-1 text-xs transition-colors", templateCat === "后端" ? "bg-primary/10 text-primary font-medium" : "bg-muted hover:bg-primary/10 hover:text-primary")}
                  >
                    后端模板 ({backendTemplates.length})
                  </button>
                </div>

                {/* Loading overlay */}
                {loadingTemplate && (
                  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
                    <div className="flex items-center gap-3 bg-white rounded-xl px-6 py-4 shadow-lg">
                      <Loader2 className="h-6 w-6 animate-spin text-primary" />
                      <span className="text-sm font-medium">加载模板中...</span>
                    </div>
                  </div>
                )}

                {/* Gaoding templates */}
                {templateCat !== "后端" && (
                  loadingGaoding ? (
                    <div className="flex items-center justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>
                  ) : (
                    <div className="grid grid-cols-2 gap-2.5">
                      {gaodingTemplates
                        .filter(t => t.title.toLowerCase().includes(searchQuery.toLowerCase()))
                        .map(t => {
                          return (
                            <button
                              key={t.id}
                              onClick={() => handleLoadGaodingTemplate(t)}
                              className="group flex flex-col overflow-hidden rounded-lg border bg-card shadow-sm transition-all hover:shadow-md hover:border-primary/30"
                            >
                              {/* Fixed-height preview, image fills with object-cover */}
                              <div className="relative overflow-hidden bg-gray-100" style={{ height: 120 }}>
                                <img
                                  src={t.preview.startsWith('/') ? t.preview : `/templates/${t.folder}/preview.png`}
                                  alt={t.title}
                                  className="w-full h-full object-cover"
                                  loading="lazy"
                                />
                                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors" />
                                <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                  <Plus className="h-4 w-4 text-white drop-shadow" />
                                </div>
                                <div className="absolute bottom-1 left-1 bg-black/50 text-white text-[9px] px-1 rounded">
                                  {t.width}×{t.height}
                                </div>
                              </div>
                              <div className="p-1.5">
                                <p className="truncate text-[10px] font-medium leading-tight">{t.title}</p>
                                <p className="text-[9px] text-muted-foreground mt-0.5">{t.image_count} 素材</p>
                              </div>
                            </button>
                          );
                        })}
                    </div>
                  )
                )}

                {/* Backend templates (when selected) */}
                {templateCat === "后端" && (
                  loadingTemplates ? (
                    <div className="flex items-center justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>
                  ) : filteredTemplates.length === 0 ? (
                    <div className="text-center py-8 text-sm text-muted-foreground">暂无模板</div>
                  ) : (
                    <div className="grid grid-cols-2 gap-2.5">
                      {filteredTemplates.map(t => {
                        let fabricW = DEFAULT_CANVAS_W, fabricH = DEFAULT_CANVAS_H;
                        try { const f = JSON.parse(t.fabric_json || "{}"); fabricW = f.width || DEFAULT_CANVAS_W; fabricH = f.height || DEFAULT_CANVAS_H; } catch {}
                        const bgColors: Record<string, string> = { poster: "#f59e0b", social: "#6366f1", card: "#8b5cf6", banner: "#ec4899", presentation: "#14b8a6" };
                        const color = bgColors[t.category] || "#6366f1";
                        return (
                          <button key={t.id} onClick={() => {
                            if (!confirm(`使用模板 "${t.name}"？当前编辑内容将被覆盖。`)) return;
                            ctx.setProjectName(t.name);
                            setCanvases(prev => prev.map(c2 => c2.id === "c1" ? { ...c2, w: fabricW, h: fabricH } : c2));
                            fabricHook.loadFromJSON(t.fabric_json || "{}");
                            setTemplateLoadKey(k => k + 1);
                          }} className="group flex flex-col overflow-hidden rounded-lg border bg-card shadow-sm transition-all hover:shadow-md hover:border-primary/30">
                            <div className="aspect-[4/3] flex items-center justify-center text-xs font-medium text-white relative" style={{ background: `linear-gradient(135deg, ${color}, ${color}88)` }}>
                              <div className="w-8 h-8 rounded bg-white/20" />
                              <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity"><Plus className="h-4 w-4 text-white" /></div>
                            </div>
                            <div className="p-2">
                              <p className="truncate text-xs font-medium">{t.name}</p>
                              <div className="mt-0.5 flex items-center justify-between">
                                <span className="text-[10px] text-muted-foreground">{templateCategoryMap[t.category] || t.category}</span>
                                <span className="text-[10px] text-muted-foreground">{fabricW}×{fabricH}</span>
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  )
                )}
              </div>
            )}

            {/* === Elements === */}
            {activeLeftTab === "elements" && (
              <div className="p-3 space-y-4">
                <h4 className="text-sm font-medium">基本形状</h4>
                <div className="grid grid-cols-4 gap-2">
                  {elementShapes.map(el => (
                    <button key={el.id} onClick={() => { setSelectedShape(el.id); makeShape(el.id); }} className={cn("flex flex-col items-center gap-1.5 rounded-lg border py-3 transition-colors", selectedShape === el.id ? "border-primary bg-primary/5 text-primary" : "hover:bg-accent")}>
                      <el.icon className="h-5 w-5" /><span className="text-[10px]">{el.label}</span>
                    </button>
                  ))}
                </div>
                <h4 className="text-sm font-medium">媒体</h4>
                <div className="grid grid-cols-2 gap-2">
                  <button onClick={() => {
                    const input = document.createElement("input");
                    input.type = "file";
                    input.accept = "image/*";
                    input.onchange = (e) => {
                      const file = (e.target as HTMLInputElement).files?.[0];
                      if (!file) return;
                      const reader = new FileReader();
                      reader.onload = () => {
                        fabricHook.addImage(reader.result as string, { left: canvasW / 2 - 50, top: canvasH / 2 - 50 });
                      };
                      reader.readAsDataURL(file);
                    };
                    input.click();
                  }} className="flex flex-col items-center gap-1.5 rounded-lg border bg-card py-4 hover:bg-accent transition-colors">
                    <Image className="h-5 w-5 text-muted-foreground" /><span className="text-[10px]">上传图片</span>
                  </button>
                </div>
                <h4 className="text-sm font-medium">装饰元素</h4>
                {loadingMaterials ? (
                  <div className="flex items-center justify-center py-4"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
                ) : backendMaterials.length === 0 ? (
                  <div className="text-center py-4 text-xs text-muted-foreground">暂无素材</div>
                ) : (
                  <div className="grid grid-cols-4 gap-2">
                    {backendMaterials.slice(0, 8).map(m => (
                      <button key={m.id} onClick={() => {
                        if (m.url) fabricHook.addImage(m.url, { left: canvasW / 2 - (m.width || 50) / 2, top: canvasH / 2 - (m.height || 50) / 2, name: m.name });
                      }} className="flex flex-col items-center gap-1 rounded-lg border bg-card p-2 hover:bg-accent hover:shadow-sm transition-all">
                        {m.url ? (
                          <img src={m.url} alt={m.name} className="h-6 w-6 object-contain" />
                        ) : (
                          <Image className="h-6 w-6 text-muted-foreground" />
                        )}
                        <span className="text-[9px] truncate w-full text-center text-muted-foreground">{m.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* === Text === */}
            {activeLeftTab === "text" && (
              <div className="p-3 space-y-3">
                <button onClick={() => fabricHook.addText("双击编辑文字", { left: canvasW / 2 - 100, top: canvasH / 2 - 15 })} className="w-full rounded-lg border-2 border-dashed border-muted-foreground/40 py-5 text-center transition-colors hover:border-primary hover:bg-primary/5 group">
                  <Plus className="mx-auto mb-2 h-6 w-6 text-muted-foreground group-hover:text-primary" />
                  <span className="text-sm text-muted-foreground group-hover:text-primary">添加文本框</span>
                </button>
                <div>
                  <h4 className="mb-2 text-sm font-medium">预设文字样式</h4>
                  <div className="space-y-2">
                    {[
                      { nm: "主标题", sz: 36, fw: "bold", t: "主标题文字" },
                      { nm: "副标题", sz: 22, fw: "semibold", t: "副标题文字" },
                      { nm: "正文", sz: 14, fw: "normal", t: "正文内容，支持多行文本" },
                    ].map(p => (
                      <button key={p.nm} onClick={() => {
                        fabricHook.addText(p.t, { left: 60, top: 80, fontSize: p.sz, fontWeight: p.fw, name: p.nm });
                      }} className="w-full rounded-lg border bg-card p-4 text-left hover:bg-accent transition-colors">
                        <span style={{ fontSize: p.sz, fontWeight: p.fw as any }}>{p.nm}</span>
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <h4 className="mb-2 text-sm font-medium">艺术字</h4>
                  <div className="space-y-2">
                    {artTextStyles.map(style => {
                      const fp = style.fabricProps;
                      // Build CSS gradient for preview
                      let cssFill: string | undefined;
                      if (typeof fp.fill === 'string') {
                        cssFill = fp.fill;
                      } else if (fp.fill && typeof fp.fill === 'object') {
                        const stops = fp.fill.colorStops.map(s => `${s.color} ${(s.offset * 100).toFixed(0)}%`).join(', ');
                        cssFill = `linear-gradient(90deg, ${stops})`;
                      }
                      // Build CSS shadow for preview
                      let cssShadow: string | undefined;
                      if (fp.shadow) {
                        const s = fp.shadow;
                        cssShadow = `${s.offsetX}px ${s.offsetY}px ${s.blur}px ${s.color}`;
                      }
                      // Build CSS stroke for preview
                      let cssStroke: string | undefined;
                      let cssStrokeWidth: number | undefined;
                      if (fp.stroke) {
                        cssStroke = fp.stroke;
                        cssStrokeWidth = fp.strokeWidth || 1;
                      }

                      return (
                      <button key={style.id} onClick={() => {
                        fabricHook.addText(style.sample, {
                          left: canvasW / 2 - 100,
                          top: canvasH / 2 - 25,
                          textAlign: 'center',
                          ...convertFabricProps(style.fabricProps),
                        } as Partial<fabric.ITextOptions>);
                      }} className="w-full rounded-xl border border-[#e8eaec] overflow-hidden hover:shadow-md transition-all text-left group">
                        {/* 效果展示区 */}
                        <div className="flex items-center justify-center py-4 px-3 min-h-[56px]" style={style.cardBg || { background: '#f8f9fa' }}>
                          <span style={{
                            fontFamily: '"Noto Sans SC", sans-serif',
                            fontSize: style.fontSize || 24,
                            fontWeight: style.fontWeight || 700,
                            color: cssFill === 'transparent' ? 'transparent' : cssFill || undefined,
                            WebkitTextStrokeColor: cssStroke,
                            WebkitTextStrokeWidth: cssStrokeWidth ? `${cssStrokeWidth}px` : undefined,
                            textShadow: cssShadow,
                            background: cssFill && !cssFill.startsWith('#') && !cssFill.startsWith('rgba') ? cssFill : undefined,
                            WebkitBackgroundClip: cssFill && !cssFill.startsWith('#') && !cssFill.startsWith('rgba') ? 'text' : undefined,
                            WebkitTextFillColor: cssFill && !cssFill.startsWith('#') && !cssFill.startsWith('rgba') ? 'transparent' : undefined,
                          }}>
                            {style.sample}
                          </span>
                        </div>
                        {/* 底部标签 */}
                        <div className="px-2.5 py-1.5 bg-[#fafbfc] border-t border-[#e8eaec] flex items-center justify-between">
                          <span className="text-[11px] font-medium text-[#4c535c]">{style.name}</span>
                          <div className="flex gap-0.5">
                            {style.effects.map(e => (
                              <span key={e} className="text-[9px] px-1 py-px rounded bg-[#f0f6ff] text-[#2254f4]">{e}</span>
                            ))}
                          </div>
                        </div>
                      </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* === Materials === */}
            {activeLeftTab === "materials" && (
              <div className="p-3">
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input type="text" placeholder="搜索素材..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} className="w-full rounded-lg border bg-background py-2 pl-9 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
                </div>
                <div className="flex gap-1.5 mb-3 flex-wrap">
                  {["全部", ...Array.from(new Set(filteredMaterials.map(m => materialCategoryMap[m.category ?? ""] || m.category || "")))].map(c => (
                    <button key={c} onClick={() => setMaterialCat(c)} className={cn("rounded-full px-2.5 py-1 text-xs transition-colors", materialCat === c ? "bg-primary/10 text-primary font-medium" : "bg-muted hover:bg-primary/10 hover:text-primary")}>{c}</button>
                  ))}
                </div>
                {loadingMaterials ? (
                  <div className="flex items-center justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>
                ) : filteredMaterials.length === 0 ? (
                  <div className="text-center py-8 text-sm text-muted-foreground">暂无素材</div>
                ) : (
                  <div className="grid grid-cols-3 gap-2">
                    {filteredMaterials.map(m => (
                      <button key={m.id} onClick={() => {
                        if (m.url) fabricHook.addImage(m.url, { left: canvasW / 2 - (m.width || 50) / 2, top: canvasH / 2 - (m.height || 50) / 2, name: m.name });
                      }} className="flex flex-col items-center gap-1.5 rounded-lg border bg-card p-3 hover:bg-accent hover:shadow-sm transition-all">
                        {m.url ? (
                          <img src={m.url} alt={m.name} className="w-10 h-10 object-contain" />
                        ) : (
                          <Image className="h-10 w-10 text-muted-foreground" />
                        )}
                        <span className="text-[10px] truncate w-full text-center">{m.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* === Backgrounds === */}
            {activeLeftTab === "backgrounds" && (
              <div className="p-3">
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input type="text" placeholder="搜索背景..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} className="w-full rounded-lg border bg-background py-2 pl-9 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
                </div>
                <div className="flex gap-1.5 mb-3 flex-wrap">
                  {["全部", "纯色", "渐变", "图案"].map(c => (
                    <button key={c} onClick={() => setBgCat(c)} className={cn("rounded-full px-2.5 py-1 text-xs transition-colors", bgCat === c ? "bg-primary/10 text-primary font-medium" : "bg-muted hover:bg-primary/10 hover:text-primary")}>{c}</button>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {mockBackgrounds.filter(bg => {
                    if (bgCat === "全部") return true;
                    if (bgCat === "纯色") return bg.type === "color";
                    if (bgCat === "渐变") return bg.type === "gradient";
                    if (bgCat === "图案") return bg.type === "gradient" && bg.value.includes("repeating");
                    return true;
                  }).map(bg => (
                    <button
                      key={bg.id}
                      onClick={() => {
                        setCanvases(prev => prev.map(c2 => c2.id === activeCanvasId ? { ...c2, bgColor: bg.value, bg: bg.value } : c2));
                      }}
                      className={cn("flex flex-col overflow-hidden rounded-lg border transition-all hover:shadow-md",
                        (activeCanvas.bg ?? activeCanvas.bgColor) === bg.value ? "border-primary ring-1 ring-primary/20" : "hover:border-primary/30")}
                    >
                      <div className="aspect-[4/3]" style={{ background: bg.value }} />
                      <div className="px-2 py-1.5 bg-card">
                        <p className="truncate text-[10px] font-medium">{bg.name}</p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* === Layers === */}
            {activeLeftTab === "layers" && (
              <div>
                <div className="flex items-center justify-between px-3 py-2.5 border-b shrink-0">
                  <span className="text-sm font-medium">图层 ({totalLayerCount})</span>
                  <div className="flex items-center gap-0.5">
                    <button onClick={fabricHook.bringForward} className="p-1.5 rounded hover:bg-accent text-muted-foreground"><ArrowUp className="h-3.5 w-3.5" /></button>
                    <button onClick={fabricHook.sendBackward} className="p-1.5 rounded hover:bg-accent text-muted-foreground"><ArrowDown className="h-3.5 w-3.5" /></button>
                    <button onClick={fabricHook.cloneSelected} className="p-1.5 rounded hover:bg-accent text-muted-foreground"><Copy className="h-3.5 w-3.5" /></button>
                    <button onClick={fabricHook.deleteSelected} className="p-1.5 rounded hover:bg-red-50 text-destructive"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>
                <div className="overflow-auto" style={{ maxHeight: "calc(100vh - 200px)" }}>
                  {layerList.map((layer: any) => {
                    const cfg = layerTypeConfig[layer.type] || { icon: "?", color: "bg-gray-100 text-gray-600" };
                    const isSelected = fabricHook.selectedIds.includes(layer.id);
                    return (
                      <div
                        key={layer.id}
                        onClick={() => fabricHook.selectObject(layer._object)}
                        className={cn("flex items-center gap-2 px-3 py-2 text-xs cursor-pointer transition-colors", isSelected ? "bg-primary/5 text-primary" : "hover:bg-accent")}
                      >
                        <span className={cn("w-5 h-5 rounded flex items-center justify-center text-[10px]", cfg.color)}>{cfg.icon}</span>
                        <span className="flex-1 truncate">{layer.name}</span>
                        <button onClick={(e) => { e.stopPropagation(); layer._object.set("visible", !layer.visible); fabricHook.fabricCanvas.current?.renderAll(); }} className={cn("p-0.5 rounded", layer.visible ? "text-muted-foreground" : "text-muted-foreground/30")}>
                          {layer.visible ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); layer._object.set("selectable", !layer._object.selectable); fabricHook.fabricCanvas.current?.renderAll(); }} className={cn("p-0.5 rounded", layer.locked ? "text-amber-500" : "text-muted-foreground/30")}>
                          {layer.locked ? <Lock className="h-3 w-3" /> : <Unlock className="h-3 w-3" />}
                        </button>
                      </div>
                    );
                  })}
                  {layerList.length === 0 && (
                    <div className="text-center py-8 text-xs text-muted-foreground">暂无图层</div>
                  )}
                </div>
              </div>
            )}

            {/* === AI === */}
            {activeLeftTab === "ai" && (
              <div className="p-3 space-y-3">
                <h4 className="text-sm font-medium">AI 生成图片</h4>
                <textarea value={aiPrompt} onChange={e => setAiPrompt(e.target.value)} placeholder="描述你想要的图片..." className="w-full rounded-lg border bg-background p-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none h-20" />
                <div>
                  <label className="text-sm font-medium mb-1.5 block">图片尺寸</label>
                  <div className="grid grid-cols-3 gap-1.5">
                    {["1:1", "16:9", "9:16", "4:3", "3:4", "3:2"].map(r => (
                      <button key={r} onClick={() => setAiSize(r)} className={cn("rounded-md border py-1.5 text-xs font-medium hover:bg-accent transition-colors", aiSize === r ? "border-primary bg-primary/5 text-primary" : "")}>{r}</button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">风格</label>
                  <div className="grid grid-cols-4 gap-1.5">
                    {["写实", "插画", "3D", "动漫", "水彩", "像素", "油画", "极简"].map(s => (
                      <button key={s} onClick={() => setAiStyle(s)} className={cn("rounded-md border py-1.5 text-xs hover:bg-accent transition-colors", aiStyle === s ? "border-primary bg-primary/5 text-primary" : "")}>{s}</button>
                    ))}
                  </div>
                </div>
                <button className="w-full rounded-lg bg-primary py-2.5 text-sm font-medium text-white shadow-sm flex items-center justify-center gap-2"><Sparkles className="h-4 w-4" />生成图片</button>
              </div>
            )}
          </div>
        </div>

        {/* ===== CENTER CANVAS ===== */}
        <div className="flex flex-1 flex-col min-w-0 bg-gray-100/60">
          <div
            ref={viewportRef}
            className="flex-1 overflow-auto flex items-center justify-center p-6"
            onClick={e => { if (e.target === e.currentTarget) fabricHook.deselectAll(); }}
          >
            {/* Canvas + labels */}
            <div className="flex flex-col items-center gap-6">
              {canvases.map(c => {
                const isActive = c.id === activeCanvasId;

                return (
                  <div key={c.id} className="flex flex-col items-center gap-2">
                    <div className="flex items-center gap-2">
                      <span className={cn("text-xs font-medium px-2 py-0.5 rounded", isActive ? "bg-primary/10 text-primary" : "text-muted-foreground")}>{c.name}</span>
                      <span className="text-[10px] text-muted-foreground font-mono">{c.w} × {c.h}</span>
                    </div>
                    <div
                      ref={isActive ? canvasWrapperRef : undefined}
                      className={cn("relative rounded-sm transition-all bg-white overflow-hidden", isActive ? "ring-2 ring-primary ring-offset-2" : "opacity-90 hover:opacity-100 cursor-pointer border shadow-md")}
                      style={isActive ? {} : { width: Math.min(c.w * 0.15, 120), height: Math.min(c.h * 0.15, 100) }}
                      onClick={e => { e.stopPropagation(); if (!isActive) switchToCanvas(c.id); }}
                    >
                      {/* Active canvas: Fabric.js controls CSS dimensions via applyCanvasViewportCss */}
                      {isActive ? (
                        <canvas key={canvasKey} ref={fabricHook.canvasEl}
                          style={{ display: 'block', background: activeCanvas.bg ?? activeCanvas.bgColor, boxShadow: '0 8px 32px rgba(99,102,241,0.15), 0 2px 8px rgba(0,0,0,0.08)' }} />
                      ) : (
                        /* Inactive canvas: simple preview with background color */
                        <div style={{ width: '100%', height: '100%', background: c.bg ?? c.bgColor }} className="flex items-center justify-center">
                          <span className="text-xs text-muted-foreground">点击切换</span>
                        </div>
                      )}
                      {/* Overlay for inactive: click hint */}
                      {!isActive && (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/0 hover:bg-black/10 transition-colors rounded-sm">
                          <span className="text-xs font-medium text-white drop-shadow-md bg-black/30 px-2 py-1 rounded opacity-0 hover:opacity-100 transition-opacity">点击切换</span>
                        </div>
                      )}
                    </div>
                    {isActive && (
                      <div className="flex items-center gap-0.5">
                        <button onClick={(e) => { e.stopPropagation(); duplicateCanvas(c.id); }} className="p-0.5 rounded hover:bg-accent text-muted-foreground" title="复制"><Copy className="h-2.5 w-2.5" /></button>
                        <button onClick={(e) => { e.stopPropagation(); deleteCanvasFn(c.id); }} className="p-0.5 rounded hover:bg-red-50 text-destructive" title="删除" disabled={canvases.length <= 1}><Trash2 className="h-2.5 w-2.5" /></button>
                      </div>
                    )}
                  </div>
                );
              })}
              {/* Add canvas button */}
              <button onClick={addCanvas} className="flex items-center gap-2 rounded-lg border-2 border-dashed border-muted-foreground/40 px-6 py-3 text-sm text-muted-foreground hover:border-primary hover:text-primary transition-colors">
                <Plus className="h-4 w-4" />添加画板
              </button>
            </div>
          </div>

          {/* Status bar：缩放 + 适应视口/1:1 必须可见，窄屏时换行 */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1.5 border-t bg-card px-3 py-2 shrink-0 min-h-9 text-xs text-muted-foreground">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 min-w-0">
              <span className="tabular-nums">{safeW} × {safeH}px</span>
              {fabricHook.selectedIds.length > 0 && <span>已选 {fabricHook.selectedIds.length} 个</span>}
              <span>图层 {totalLayerCount}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => fabricHook.setZoom(z => Math.max(25, z - 10))} className="hover:text-foreground p-0.5 rounded" aria-label="缩小"><ZoomOut className="h-4 w-4" /></button>
                <input type="range" min={25} max={200} value={fabricHook.zoomPercent} onChange={e => fabricHook.setZoom(Number(e.target.value))} className="w-24 sm:w-28 accent-primary" />
                <button type="button" onClick={() => fabricHook.setZoom(z => Math.min(200, z + 10))} className="hover:text-foreground p-0.5 rounded" aria-label="放大"><ZoomIn className="h-4 w-4" /></button>
                <span className="w-9 text-right font-mono text-foreground">{fabricHook.zoomPercent}%</span>
              </div>
              <div className="h-4 w-px bg-border hidden sm:block" />
              <button
                type="button"
                onClick={() => fabricHook.fitViewportToContainer()}
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-foreground hover:bg-accent"
                title="整图画布缩放到当前可见区域，一眼看全"
              >
                <Maximize2 className="h-3.5 w-3.5 shrink-0" />
                <span>适应</span>
              </button>
              <button
                type="button"
                onClick={() => fabricHook.setViewportPixelPerfect()}
                className="rounded border border-border px-2 py-1 text-foreground hover:bg-accent"
                title="按 1:1 像素显示（图很大时可滚动）"
              >
                1:1
              </button>
            </div>
          </div>
        </div>

        {/* ===== RIGHT PANEL (280px) ===== */}
        <div className="flex w-72 shrink-0 flex-col border-l bg-card overflow-y-auto">

          {/* === 画板 section (always visible) === */}
          <div className="border-b px-3 py-2.5 shrink-0 flex items-center justify-between">
            <h3 className="text-sm font-medium">画板</h3>
            <button onClick={addCanvas} className="flex items-center gap-1 rounded-md bg-primary/10 text-primary px-2 py-1 text-xs font-medium hover:bg-primary/20 transition-colors">
              <Plus className="h-3 w-3" />添加画板
            </button>
          </div>

          {/* Canvas list */}
          <div className="px-3 py-2 border-b shrink-0">
            <div className="flex gap-2 overflow-x-auto pb-1">
              {canvases.map(c => {
                const isActive = c.id === activeCanvasId;
                return (
                  <div key={c.id} className={cn("flex flex-col items-center gap-1 rounded-lg border p-1.5 cursor-pointer transition-all min-w-[72px]", isActive ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "hover:border-border")}>
                    <div onClick={() => switchToCanvas(c.id)} className="w-12 h-8 rounded-sm shadow-sm flex items-center justify-center" style={{ background: c.bg ?? c.bgColor }}>
                      <span className="text-[8px] text-muted-foreground">{c.w > 0 ? Math.round((c.w / c.h) * 10) / 10 : ""}</span>
                    </div>
                    <span className="text-[10px] truncate w-full text-center">{c.name}</span>
                    {isActive && (
                      <div className="flex items-center gap-0.5">
                        <button onClick={(e) => { e.stopPropagation(); duplicateCanvas(c.id); }} className="p-0.5 rounded hover:bg-accent text-muted-foreground" title="复制"><Copy className="h-2.5 w-2.5" /></button>
                        <button onClick={(e) => { e.stopPropagation(); deleteCanvasFn(c.id); }} className="p-0.5 rounded hover:bg-red-50 text-destructive" title="删除" disabled={canvases.length <= 1}><Trash2 className="h-2.5 w-2.5" /></button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* === Canvas properties — when NO element selected === */}
          {!selectedEl && (
            <>
              <div className="px-3 py-3 border-b shrink-0">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold">画板属性</span>
                  <span className="text-[10px] text-muted-foreground font-mono">{activeCanvas.w} × {activeCanvas.h} px</span>
                </div>
                {/* Canvas preview */}
                <div className="flex items-center justify-center rounded-lg border bg-muted/30 p-3 mb-3">
                  <div className="rounded-sm shadow-sm border" style={{ width: Math.min(120, (activeCanvas.w / activeCanvas.h) * 75), height: Math.min(75, (activeCanvas.h / activeCanvas.w) * 120), background: activeCanvas.bg ?? activeCanvas.bgColor }} />
                </div>
                {/* Size buttons */}
                <div className="grid grid-cols-2 gap-1.5 mb-3">
                  <button onClick={() => {
                    const w = prompt("宽度 (px)", String(activeCanvas.w));
                    const h = prompt("高度 (px)", String(activeCanvas.h));
                    if (w && h) resizeCanvas(parseInt(w), parseInt(h));
                  }} className="flex items-center justify-center gap-1 rounded-md border bg-background py-1.5 text-xs hover:bg-accent transition-colors">
                    <Crop className="h-3.5 w-3.5" />调整尺寸
                  </button>
                  <button onClick={() => setShowSizeTemplateModal(!showSizeTemplateModal)} className="flex items-center justify-center gap-1 rounded-md border bg-background py-1.5 text-xs hover:bg-accent transition-colors">
                    <LayoutGrid className="h-3.5 w-3.5" />尺寸模板
                  </button>
                </div>
                {/* Size templates popup */}
                {showSizeTemplateModal && (
                  <div className="mb-3 rounded-lg border bg-background p-2 max-h-40 overflow-auto">
                    {presetSizes.map(ps => (
                      <button key={ps.name} onClick={() => { resizeCanvas(ps.w, ps.h); setShowSizeTemplateModal(false); }} className="w-full flex items-center justify-between px-2 py-1.5 text-xs hover:bg-accent rounded transition-colors">
                        <span>{ps.name}</span>
                        <span className="text-muted-foreground">{ps.w}×{ps.h} ({ps.ratio})</span>
                      </button>
                    ))}
                  </div>
                )}
                {/* Background color */}
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-muted-foreground shrink-0">背景色</span>
                  <input type="color" value={activeCanvas.bgColor.startsWith("#") ? activeCanvas.bgColor : "#ffffff"} onChange={e => { const v = e.target.value; setCanvases(prev => prev.map(c2 => c2.id === activeCanvasId ? { ...c2, bgColor: v, bg: v } : c2)); }} className="h-6 w-6 rounded cursor-pointer border-0 shrink-0" />
                  <div className="flex items-center gap-1 flex-1">
                    {["#ffffff", "#f8fafc", "#0f172a", "#6366f1", "#ec4899", "#10b981"].map(c => (
                      <button key={c} onClick={() => setCanvases(prev => prev.map(c2 => c2.id === activeCanvasId ? { ...c2, bgColor: c, bg: c } : c2))} className={cn("h-5 w-5 rounded-sm border transition-all", (activeCanvas.bg ?? activeCanvas.bgColor) === c ? "ring-2 ring-primary ring-offset-1 scale-110" : "hover:scale-110")} style={{ backgroundColor: c }} />
                    ))}
                  </div>
                </div>
                {/* Background image upload */}
                <div className="mt-2 flex gap-2">
                  <button onClick={() => {
                    const input = document.createElement("input");
                    input.type = "file";
                    input.accept = "image/*";
                    input.onchange = (e) => {
                      const file = (e.target as HTMLInputElement).files?.[0];
                      if (!file) return;
                      const reader = new FileReader();
                      reader.onload = () => {
                        setCanvases(prev => prev.map(c2 => c2.id === activeCanvasId ? { ...c2, bgImage: reader.result as string } : c2));
                      };
                      reader.readAsDataURL(file);
                    };
                    input.click();
                  }} className="flex-1 flex items-center justify-center gap-1 rounded-md border bg-background py-1.5 text-xs hover:bg-accent transition-colors">
                    <Image className="h-3.5 w-3.5" />上传图片
                  </button>
                  <button onClick={() => setActiveLeftTab("backgrounds")} className="flex-1 flex items-center justify-center gap-1 rounded-md border bg-background py-1.5 text-xs hover:bg-accent transition-colors">
                    <Palette className="h-3.5 w-3.5" />背景模板
                  </button>
                </div>
              </div>
              <div className="px-3 py-3">
                <p className="text-xs text-muted-foreground">点击画布中的元素即可编辑属性</p>
              </div>
            </>
          )}

          {/* === Element properties (when element selected) === */}
          {selectedEl && (
            <>
              <div className="border-b px-3 py-2.5 flex items-center justify-between shrink-0">
                <div className="flex items-center gap-2">
                  <span className={cn("flex h-6 w-6 items-center justify-center rounded text-xs font-bold", layerTypeConfig[selectedEl.type]?.color)}>
                    {layerTypeConfig[selectedEl.type]?.icon}
                  </span>
                  <input type="text" value={selectedEl.name} onChange={e => updateProp("name", e.target.value)} className="text-sm font-semibold bg-transparent border-b border-transparent focus:border-primary/50 focus:outline-none rounded px-0.5 w-28" />
                </div>
                <div className="flex items-center gap-0.5">
                  <button onClick={fabricHook.cloneSelected} className="p-1.5 rounded hover:bg-accent text-muted-foreground" title="复制"><Copy className="h-3.5 w-3.5" /></button>
                  <button onClick={() => updateProp("selectable", !(selectedEl._fabricObject as any)?.selectable)} className={cn("p-1.5 rounded hover:bg-accent", !selectedEl._fabricObject?.selectable ? "text-amber-500" : "text-muted-foreground")} title="锁定">
                    {!selectedEl._fabricObject?.selectable ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}
                  </button>
                  <button onClick={fabricHook.deleteSelected} className="p-1.5 rounded hover:bg-red-50 text-destructive" title="删除"><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              </div>

              {/* Right panel tabs */}
              <div className="flex border-b shrink-0">
                <button onClick={() => setActiveRightTab("attr")} className={cn("flex-1 py-1.5 text-xs font-medium border-b-2 transition-colors", activeRightTab === "attr" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}>属性</button>
                <button onClick={() => setActiveRightTab("style")} className={cn("flex-1 py-1.5 text-xs font-medium border-b-2 transition-colors", activeRightTab === "style" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}>样式</button>
              </div>

              {activeRightTab === "attr" && (
                <div className="p-3 space-y-4">
                  {/* Position */}
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-2">位置</h4>
                    <div className="grid grid-cols-2 gap-2">
                      <div><label className="text-[10px] text-muted-foreground">X</label><input type="number" value={selectedEl.left} onChange={e => updateProp("left", Number(e.target.value))} className="w-full rounded border bg-background px-2 py-1 text-xs" /></div>
                      <div><label className="text-[10px] text-muted-foreground">Y</label><input type="number" value={selectedEl.top} onChange={e => updateProp("top", Number(e.target.value))} className="w-full rounded border bg-background px-2 py-1 text-xs" /></div>
                    </div>
                  </div>
                  {/* Size */}
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-2">尺寸</h4>
                    <div className="grid grid-cols-2 gap-2">
                      <div><label className="text-[10px] text-muted-foreground">宽</label><input type="number" value={selectedEl.width} onChange={e => { const obj = selectedEl._fabricObject; if (!obj) return; const scaleX = Number(e.target.value) / (obj.width || 1); obj.scale(scaleX); fabricHook.fabricCanvas.current?.renderAll(); }} className="w-full rounded border bg-background px-2 py-1 text-xs" /></div>
                      <div><label className="text-[10px] text-muted-foreground">高</label><input type="number" value={selectedEl.height} onChange={e => { const obj = selectedEl._fabricObject; if (!obj) return; const scaleY = Number(e.target.value) / (obj.height || 1); obj.scale(scaleY); fabricHook.fabricCanvas.current?.renderAll(); }} className="w-full rounded border bg-background px-2 py-1 text-xs" /></div>
                    </div>
                  </div>
                  {/* Angle */}
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-2">旋转</h4>
                    <div className="flex items-center gap-2">
                      <input type="range" min={0} max={360} value={selectedEl.angle} onChange={e => updateProp("angle", Number(e.target.value))} className="flex-1 accent-primary" />
                      <span className="text-xs w-8 text-right">{selectedEl.angle}°</span>
                    </div>
                  </div>
                  {/* Opacity */}
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-2">透明度</h4>
                    <div className="flex items-center gap-2">
                      <input type="range" min={0} max={100} value={selectedEl.opacity} onChange={e => updateProp("opacity", Number(e.target.value) / 100)} className="flex-1 accent-primary" />
                      <span className="text-xs w-8 text-right">{selectedEl.opacity}%</span>
                    </div>
                  </div>
                  {/* Quick actions */}
                  <div className="flex gap-2 pt-2 border-t">
                    <button onClick={fabricHook.cloneSelected} className="flex-1 p-2 rounded border text-xs hover:bg-accent transition-colors flex items-center justify-center gap-1"><Copy className="h-3 w-3" />复制</button>
                    <button onClick={fabricHook.bringToFront} className="flex-1 p-2 rounded border text-xs hover:bg-accent transition-colors flex items-center justify-center gap-1"><ArrowUp className="h-3 w-3" />置顶</button>
                    <button onClick={fabricHook.sendToBack} className="flex-1 p-2 rounded border text-xs hover:bg-accent transition-colors flex items-center justify-center gap-1"><ArrowDown className="h-3 w-3" />置底</button>
                  </div>
                </div>
              )}

              {activeRightTab === "style" && (
                <div className="p-3 space-y-4">
                  {/* Text-specific */}
                  {selectedEl.type?.includes("text") && (
                    <>
                      {/* 字体选择器 — 简单下拉列表 */}
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">字体</h4>
                        <select
                          value={selectedEl.fontFamily || ''}
                          onChange={e => updateProp("fontFamily", e.target.value)}
                          className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                        >
                          <option value="">系统默认</option>
                          {allFonts.map(font => (
                            <option key={font.value} value={font.value} style={{ fontFamily: font.value }}>
                              {font.label} — {font.preview}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">字号</h4>
                        <input type="number" value={selectedEl.fontSize || 24} onChange={e => updateProp("fontSize", Number(e.target.value))} className="w-full rounded border bg-background px-2 py-1 text-xs" />
                      </div>
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">文字颜色</h4>
                        <div className="flex flex-wrap gap-1.5">
                          {textColors.map(c => (
                            <button key={c} onClick={() => updateProp("fill", c)} className={cn("h-6 w-6 rounded-sm border transition-all", selectedEl.fill === c ? "ring-2 ring-primary scale-110" : "hover:scale-110")} style={{ backgroundColor: c }} />
                          ))}
                          <input type="color" value={typeof selectedEl.fill === 'string' && selectedEl.fill.startsWith('#') ? selectedEl.fill : '#000000'} onChange={e => updateProp("fill", e.target.value)} className="h-6 w-8 rounded cursor-pointer border-0" />
                        </div>
                      </div>
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">对齐</h4>
                        <div className="flex gap-1">
                          {[{ v: "left", i: AlignLeft }, { v: "center", i: AlignCenter }, { v: "right", i: AlignRight }].map(a => (
                            <button key={a.v} onClick={() => updateProp("textAlign", a.v)} className={cn("flex-1 p-1.5 rounded border transition-colors", selectedEl.textAlign === a.v ? "bg-primary/10 border-primary text-primary" : "hover:bg-accent")}><a.i className="h-4 w-4" /></button>
                          ))}
                        </div>
                      </div>
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">样式</h4>
                        <div className="flex gap-1">
                          <button onClick={() => updateProp("fontWeight", selectedEl.fontWeight === "bold" ? "normal" : "bold")} className={cn("flex-1 p-1.5 rounded border transition-colors", selectedEl.fontWeight === "bold" && "bg-primary/10 border-primary text-primary")}><Bold className="h-4 w-4" /></button>
                          <button onClick={() => updateProp("fontStyle", selectedEl.fontStyle === "italic" ? "normal" : "italic")} className={cn("flex-1 p-1.5 rounded border transition-colors", selectedEl.fontStyle === "italic" && "bg-primary/10 border-primary text-primary")}><Italic className="h-4 w-4" /></button>
                          <button onClick={() => updateProp("underline", !selectedEl.underline)} className={cn("flex-1 p-1.5 rounded border transition-colors", selectedEl.underline && "bg-primary/10 border-primary text-primary")}><Underline className="h-4 w-4" /></button>
                        </div>
                      </div>
                      {/* 特效下拉 */}
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">特效</h4>
                        <TextEffectPicker
                          selectedEl={selectedEl}
                          updateProp={updateProp}
                        />
                      </div>
                    </>
                  )}
                  {/* Shape-specific: Fill + Stroke (only for non-text) */}
                  {!selectedEl.type?.includes("text") && (
                    <>
                      {/* Fill Color */}
                      {selectedEl.fill && typeof selectedEl.fill === "string" && selectedEl.fill.startsWith("#") && (
                        <div>
                          <h4 className="text-xs font-medium text-muted-foreground mb-2">填充颜色</h4>
                          <div className="flex flex-wrap gap-1.5">
                            {shapeDefaultColors.map(c => (
                              <button key={c} onClick={() => updateProp("fill", c)} className={cn("h-6 w-6 rounded-sm border transition-all", selectedEl.fill === c ? "ring-2 ring-primary scale-110" : "hover:scale-110")} style={{ backgroundColor: c }} />
                            ))}
                            <input type="color" value={selectedEl.fill} onChange={e => updateProp("fill", e.target.value)} className="h-6 w-8 rounded cursor-pointer border-0" />
                          </div>
                        </div>
                      )}
                      {/* Stroke */}
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">描边</h4>
                        <div className="flex items-center gap-2">
                          <input type="color" value={selectedEl.stroke && typeof selectedEl.stroke === "string" ? selectedEl.stroke : "#000000"} onChange={e => updateProp("stroke", e.target.value)} className="h-6 w-8 rounded cursor-pointer border" />
                          <input type="number" min={0} max={20} value={selectedEl.strokeWidth || 0} onChange={e => updateProp("strokeWidth", Number(e.target.value))} className="w-16 rounded border bg-background px-2 py-1 text-xs" />
                          <span className="text-[10px] text-muted-foreground">px</span>
                        </div>
                      </div>
                    </>
                  )}
                  {/* Image-specific */}
                  {selectedEl.type === "image" && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-2">翻转</h4>
                      <div className="flex gap-2">
                        <button onClick={() => updateProp("flipX", !selectedEl.flipX)} className={cn("flex-1 p-2 rounded border text-xs transition-colors", selectedEl.flipX && "bg-primary/10 border-primary text-primary")}><FlipHorizontal className="h-4 w-4 inline mr-1" />水平</button>
                        <button onClick={() => updateProp("flipY", !selectedEl.flipY)} className={cn("flex-1 p-2 rounded border text-xs transition-colors", selectedEl.flipY && "bg-primary/10 border-primary text-primary")}><FlipVertical className="h-4 w-4 inline mr-1" />垂直</button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
