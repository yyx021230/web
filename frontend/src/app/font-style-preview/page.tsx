'use client';

import { useEffect, useState } from 'react';

/* ============================================================
   字体与文字特效预览 V4
   设计思路：
   艺术字 = 描边 + 投影 + 纹理 + 渐变 + 发光 + 3D + 背景框/装饰
   每种样式是这些基础效果的组合
============================================================ */

// ========== 字体列表 ==========
const FONT_LIST = [
  { name: '系统黑体', family: 'system-ui, -apple-system, sans-serif', category: '基础' },
  { name: '思源黑体', family: '"Noto Sans SC", sans-serif', category: '基础' },
  { name: '思源宋体', family: '"Noto Serif SC", serif', category: '宋体' },
  { name: '系统宋体', family: '"Songti SC", serif', category: '宋体' },
  { name: '马善政毛笔', family: '"Ma Shan Zheng", cursive', category: '书法' },
  { name: '龙藏草书', family: '"Long Cang", cursive', category: '书法' },
  { name: '志莽行书', family: '"Zhi Mang Xing", cursive', category: '书法' },
  { name: '站酷快乐体', family: '"ZCOOL KuaiLe", cursive', category: '可爱' },
  { name: '站酷小薇体', family: '"ZCOOL XiaoWei", serif', category: '可爱' },
  { name: 'Pacifico 手写', family: '"Pacifico", cursive', category: '英文手写' },
  { name: 'Dancing 花体', family: '"Dancing Script", cursive', category: '英文手写' },
  { name: 'Lobster', family: '"Lobster", cursive', category: '英文装饰' },
  { name: 'Fredoka 圆润', family: '"Fredoka One", cursive', category: '英文装饰' },
  { name: 'Bebas Neue', family: '"Bebas Neue", cursive', category: '英文海报' },
  { name: 'Orbitron 科幻', family: '"Orbitron", sans-serif', category: '英文科技' },
  { name: 'Press Start 像素', family: '"Press Start 2P", cursive', category: '像素' },
];

// ========== 基础效果拆解（用于编辑器特效面板） ==========
const BASE_EFFECT_TYPES = [
  { id: 'gradient', label: '渐变', icon: '🎨', desc: '单色→双色→多色渐变填充' },
  { id: 'stroke', label: '描边', icon: '✏️', desc: '内描边/外描边/纯色描边/渐变描边' },
  { id: 'shadow', label: '投影', icon: '👤', desc: '柔和阴影/长阴影/彩色投影' },
  { id: 'glow', label: '发光', icon: '✨', desc: '单色发光/多色发光/霓虹管' },
  { id: 'texture', label: '纹理', icon: '🖼️', desc: '金属/大理石/水彩/火焰/冰霜' },
  { id: '3d', label: '3D', icon: '💎', desc: '3D立体/3D翻转/3D斜角' },
  { id: 'background', label: '背景', icon: '📦', desc: '色块背景/渐变背景/形状背景/装饰框' },
];

// ========== 艺术字组合样式 ==========
// 每个样式 = 填充(纯色/渐变) + 描边 + 投影/3D + 发光 + 背景框

interface ArtTextStyle {
  id: string;
  name: string;
  category: string; // 节日/商务/可爱/酷炫/复古/电商/游戏
  /** 预览文字 */
  sample: string;
  /** 默认字体 */
  fontFamily?: string;
  /** 字体大小 */
  fontSize: number;
  /** 字重 */
  fontWeight: number;
  /** 背景容器样式 */
  bgStyle?: React.CSSProperties;
  /** 文字主体样式 */
  textStyle: React.CSSProperties;
  /** 底层文字样式（用于投影/3D叠加） */
  bottomStyle?: React.CSSProperties;
  /** 组合效果标签 */
  effects: string[];
}

const ART_TEXT_STYLES: ArtTextStyle[] = [
  // ==================== 电商/营销 ====================
  {
    id: 'ecom-gold-red',
    name: '金红大促',
    category: '电商',
    sample: '限时抢购',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 42,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(135deg, #c0392b 0%, #e74c3c 50%, #c0392b 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      background: 'linear-gradient(180deg, #f7d774 0%, #e8b84f 30%, #c8952e 60%, #f7d774 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      filter: 'drop-shadow(0 2px 3px rgba(0,0,0,0.4))',
    },
    effects: ['渐变', '描边', '投影', '背景'],
  },
  {
    id: 'ecom-flash-sale',
    name: '闪电促销',
    category: '电商',
    sample: '全场5折',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 42,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(135deg, #f39c12 0%, #e74c3c 100%)',
      borderRadius: '8px',
      padding: '12px 24px',
    },
    textStyle: {
      color: '#fff',
      WebkitTextStroke: '2.5px rgba(0,0,0,0.3)',
      textShadow: '0 3px 6px rgba(0,0,0,0.3)',
    },
    effects: ['描边', '投影', '背景'],
  },
  {
    id: 'ecom-neon-sale',
    name: '霓虹促销',
    category: '电商',
    sample: '爆款热卖',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 42,
    fontWeight: 900,
    bgStyle: {
      background: '#1a1a2e',
      borderRadius: '12px',
      padding: '12px 24px',
      border: '2px solid #f0c27f',
    },
    textStyle: {
      background: 'linear-gradient(90deg, #f7d774, #f0c27f, #e8b84f)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      textShadow: '0 0 20px rgba(240,194,127,0.5)',
    },
    effects: ['渐变', '发光', '背景'],
  },

  // ==================== 节日 ====================
  {
    id: 'fest-chinese-new-year',
    name: '春节喜庆',
    category: '节日',
    sample: '新年快乐',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 44,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(135deg, #c0392b 0%, #a93226 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      background: 'linear-gradient(180deg, #ffd700 0%, #ff8c00 40%, #ffd700 70%, #ffcc00 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.5))',
    },
    effects: ['渐变', '投影', '背景'],
  },
  {
    id: 'fest-couplets',
    name: '对联春联',
    category: '节日',
    sample: '万事如意',
    fontFamily: '"Ma Shan Zheng", cursive',
    fontSize: 50,
    fontWeight: 400,
    bgStyle: {
      background: 'linear-gradient(180deg, #c0392b 0%, #922b21 100%)',
      borderRadius: '4px',
      padding: '14px 28px',
      border: '3px solid #f7d774',
    },
    textStyle: {
      background: 'linear-gradient(180deg, #f7d774 0%, #e8b84f 50%, #c8952e 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
    },
    effects: ['渐变', '描边', '背景'],
  },
  {
    id: 'fest-christmas',
    name: '圣诞铃铛',
    category: '节日',
    sample: '圣诞快乐',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 42,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(135deg, #1a5e1a 0%, #2d8e2d 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
      border: '2px solid #c0392b',
    },
    textStyle: {
      color: '#fff',
      textShadow: '0 0 10px rgba(255,255,255,0.5), 0 2px 4px rgba(0,0,0,0.3)',
    },
    effects: ['发光', '投影', '背景'],
  },

  // ==================== 酷炫/科技 ====================
  {
    id: 'cool-cyber-neon',
    name: '赛博霓虹',
    category: '酷炫',
    sample: 'NEON',
    fontFamily: '"Orbitron", sans-serif',
    fontSize: 44,
    fontWeight: 700,
    bgStyle: {
      background: '#0a0a0a',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      color: '#fff',
      textShadow: '0 0 7px #fff, 0 0 10px #fff, 0 0 21px #fff, 0 0 42px #0fa, 0 0 82px #0fa',
    },
    effects: ['发光', '霓虹'],
  },
  {
    id: 'cool-pink-neon',
    name: '粉色霓虹',
    category: '酷炫',
    sample: 'PINK',
    fontFamily: '"Orbitron", sans-serif',
    fontSize: 44,
    fontWeight: 700,
    bgStyle: {
      background: '#0a0a0a',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      color: '#fff',
      textShadow: '0 0 7px #fff, 0 0 10px #fff, 0 0 21px #fff, 0 0 42px #ff00de, 0 0 82px #ff00de',
    },
    effects: ['发光', '霓虹'],
  },
  {
    id: 'cool-blue-tech',
    name: '蓝色科技',
    category: '酷炫',
    sample: 'FUTURE',
    fontFamily: '"Orbitron", sans-serif',
    fontSize: 40,
    fontWeight: 700,
    bgStyle: {
      background: 'linear-gradient(135deg, #0a0a1a 0%, #0d1b2a 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
      border: '1px solid #00d4ff33',
    },
    textStyle: {
      background: 'linear-gradient(180deg, #00d4ff 0%, #0099cc 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      textShadow: '0 0 30px rgba(0,212,255,0.4)',
    },
    effects: ['渐变', '发光', '背景'],
  },
  {
    id: 'cool-fire-text',
    name: '火焰文字',
    category: '酷炫',
    sample: '燃烧',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(180deg, #0a0a0a 0%, #1a0505 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      background: 'linear-gradient(180deg, #ffffff 0%, #fff700 15%, #ff8800 40%, #ff0000 70%, #8b0000 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      filter: 'drop-shadow(0 0 8px rgba(255,136,0,0.6))',
    },
    effects: ['渐变', '发光', '投影'],
  },
  {
    id: 'cool-ice-text',
    name: '冰霜文字',
    category: '酷炫',
    sample: '冰霜',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(180deg, #0a1628 0%, #0d2137 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      background: 'linear-gradient(180deg, #ffffff 0%, #b3e5fc 20%, #4fc3f7 50%, #0288d1 80%, #01579b 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      textShadow: '0 0 20px rgba(79,195,247,0.5), 0 0 40px rgba(2,136,209,0.3)',
    },
    effects: ['渐变', '发光'],
  },

  // ==================== 金属质感 ====================
  {
    id: 'metal-gold',
    name: '黄金质感',
    category: '金属',
    sample: '黄金',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    textStyle: {
      background: 'linear-gradient(180deg, #f7d774 0%, #c8952e 10%, #f7d774 20%, #e8b84f 35%, #f7d774 50%, #c8952e 65%, #f7d774 80%, #a87b22 90%, #f7d774 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.5))',
    },
    effects: ['渐变', '投影'],
  },
  {
    id: 'metal-rose-gold',
    name: '玫瑰金',
    category: '金属',
    sample: '玫瑰金',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    textStyle: {
      background: 'linear-gradient(180deg, #f5c6a0 0%, #c8816a 15%, #f5c6a0 30%, #e8a87c 45%, #f5c6a0 60%, #b87355 75%, #f5c6a0 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.5))',
    },
    effects: ['渐变', '投影'],
  },
  {
    id: 'metal-silver',
    name: '银色金属',
    category: '金属',
    sample: '银色',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    textStyle: {
      background: 'linear-gradient(180deg, #e8e8e8 0%, #a0a0a0 15%, #e8e8e8 30%, #c0c0c0 45%, #e8e8e8 60%, #909090 75%, #e8e8e8 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.5))',
    },
    effects: ['渐变', '投影'],
  },

  // ==================== 3D立体 ====================
  {
    id: '3d-layered-red',
    name: '红色3D',
    category: '3D',
    sample: '3D立体',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      color: '#e74c3c',
      textShadow: '1px 1px 0 #c0392b, 2px 2px 0 #c0392b, 3px 3px 0 #a93226, 4px 4px 0 #a93226, 5px 5px 0 #922b21, 6px 6px 6px rgba(0,0,0,0.2)',
    },
    effects: ['3D', '投影', '背景'],
  },
  {
    id: '3d-layered-blue',
    name: '蓝色3D',
    category: '3D',
    sample: '蓝色3D',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(135deg, #d4fc79 0%, #96e6a1 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      color: '#2980b9',
      textShadow: '1px 1px 0 #2471a3, 2px 2px 0 #2471a3, 3px 3px 0 #1f618d, 4px 4px 0 #1f618d, 5px 5px 0 #1a5276, 6px 6px 6px rgba(0,0,0,0.15)',
    },
    effects: ['3D', '投影', '背景'],
  },
  {
    id: '3d-candy',
    name: '糖果3D',
    category: '3D',
    sample: '糖果3D',
    fontFamily: '"Fredoka One", cursive',
    fontSize: 48,
    fontWeight: 400,
    bgStyle: {
      background: 'linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)',
      borderRadius: '16px',
      padding: '12px 24px',
    },
    textStyle: {
      color: '#ff6b9d',
      textShadow: '0 4px 0 #e84393, 0 8px 0 rgba(232,67,147,0.3)',
    },
    effects: ['3D', '投影', '背景'],
  },
  {
    id: '3d-heavymetal',
    name: '重金属3D',
    category: '3D',
    sample: '重金属',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    textStyle: {
      background: 'linear-gradient(180deg, #e8e8e8 0%, #a0a0a0 30%, #c0c0c0 60%, #909090 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      textShadow: '1px 1px 0 #777, 2px 2px 0 #777, 3px 3px 0 #666, 4px 4px 0 #666, 5px 5px 0 #555, 6px 6px 0 #555, 7px 7px 8px rgba(0,0,0,0.3)',
    },
    effects: ['渐变', '3D', '投影'],
  },

  // ==================== 描边 ====================
  {
    id: 'stroke-white-black',
    name: '白字黑描边',
    category: '描边',
    sample: '经典描边',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      color: '#ffffff',
      WebkitTextStroke: '2.5px rgba(0,0,0,0.6)',
      filter: 'drop-shadow(0 3px 6px rgba(0,0,0,0.3))',
    },
    effects: ['描边', '投影', '背景'],
  },
  {
    id: 'stroke-gradient',
    name: '渐变描边',
    category: '描边',
    sample: '渐变描边',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      background: 'linear-gradient(90deg, #f77062, #fe5196, #c471ed)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      WebkitTextStroke: '2px #1a1a1a',
    },
    effects: ['渐变', '描边', '背景'],
  },
  {
    id: 'stroke-hollow',
    name: '空心镂空',
    category: '描边',
    sample: '空心文字',
    fontFamily: '"Noto Sans SC", sans-serif',
    fontSize: 48,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)',
      borderRadius: '12px',
      padding: '12px 24px',
    },
    textStyle: {
      color: 'transparent',
      WebkitTextStroke: '2px #f0c27f',
    },
    effects: ['描边', '背景'],
  },

  // ==================== 可爱/卡通 ====================
  {
    id: 'cute-kawaii',
    name: '卡哇伊',
    category: '可爱',
    sample: '可爱文字',
    fontFamily: '"ZCOOL KuaiLe", cursive',
    fontSize: 48,
    fontWeight: 400,
    bgStyle: {
      background: 'linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)',
      borderRadius: '20px',
      padding: '12px 24px',
    },
    textStyle: {
      color: '#ff6b9d',
      WebkitTextStroke: '2px #fff',
      filter: 'drop-shadow(0 2px 4px rgba(255,107,157,0.3))',
    },
    effects: ['描边', '投影', '背景'],
  },
  {
    id: 'cute-bubble',
    name: '泡泡字',
    category: '可爱',
    sample: '泡泡',
    fontFamily: '"Fredoka One", cursive',
    fontSize: 48,
    fontWeight: 400,
    bgStyle: {
      background: 'linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)',
      borderRadius: '20px',
      padding: '12px 24px',
    },
    textStyle: {
      color: '#fff',
      textShadow: '0 0 10px rgba(255,255,255,0.8), 0 2px 4px rgba(0,0,0,0.2), inset 0 0 0 2px rgba(255,255,255,0.5)',
      WebkitTextStroke: '1px rgba(161,140,209,0.5)',
    },
    effects: ['发光', '描边', '背景'],
  },

  // ==================== 复古 ====================
  {
    id: 'retro-vintage',
    name: '复古印刷',
    category: '复古',
    sample: '复古风格',
    fontFamily: '"Noto Serif SC", serif',
    fontSize: 48,
    fontWeight: 900,
    bgStyle: {
      background: 'linear-gradient(135deg, #f5e6d3 0%, #d4a574 100%)',
      borderRadius: '4px',
      padding: '12px 24px',
    },
    textStyle: {
      color: '#2d1810',
      textShadow: '2px 2px 0 #8b6914, -1px -1px 0 #8b6914, 1px -1px 0 #8b6914, -1px 1px 0 #8b6914',
    },
    effects: ['投影', '背景'],
  },
  {
    id: 'retro-poster',
    name: '复古海报',
    category: '复古',
    sample: 'POSTER',
    fontFamily: '"Bebas Neue", cursive',
    fontSize: 56,
    fontWeight: 400,
    bgStyle: {
      background: 'linear-gradient(180deg, #2c1810 0%, #1a0f0a 100%)',
      borderRadius: '4px',
      padding: '12px 24px',
      border: '3px solid #c8952e',
    },
    textStyle: {
      background: 'linear-gradient(180deg, #f7d774 0%, #c8952e 50%, #a87b22 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      textShadow: '0 2px 4px rgba(0,0,0,0.5)',
    },
    effects: ['渐变', '投影', '背景'],
  },

  // ==================== 像素/游戏 ====================
  {
    id: 'game-pixel',
    name: '像素风',
    category: '游戏',
    sample: 'PIXEL',
    fontFamily: '"Press Start 2P", cursive',
    fontSize: 28,
    fontWeight: 400,
    bgStyle: {
      background: 'linear-gradient(135deg, #2d1b69 0%, #11998e 100%)',
      borderRadius: '8px',
      padding: '14px 24px',
    },
    textStyle: {
      color: '#fff',
      textShadow: '2px 2px 0 #ff0044, 4px 4px 0 rgba(255,0,68,0.3)',
    },
    effects: ['投影', '背景'],
  },
  {
    id: 'game-arcade',
    name: '街机风',
    category: '游戏',
    sample: 'ARCADE',
    fontFamily: '"Press Start 2P", cursive',
    fontSize: 28,
    fontWeight: 400,
    bgStyle: {
      background: '#1a1a1a',
      borderRadius: '8px',
      padding: '14px 24px',
      border: '3px solid #ff0044',
    },
    textStyle: {
      color: '#ffff00',
      textShadow: '0 0 10px #ffff00, 0 0 20px #ff8800, 2px 2px 0 #ff0044',
    },
    effects: ['发光', '投影', '背景'],
  },
];

// ========== SVG 滤镜 ==========
const SVG_FILTERS = `
<svg style="position:absolute;width:0;height:0;overflow:hidden">
  <defs>
    <filter id="fire" x="-20%" y="-20%" width="140%" height="140%">
      <feTurbulence type="fractalNoise" baseFrequency="0.02" numOctaves="3" result="noise"/>
      <feDisplacementMap in="SourceGraphic" in2="noise" scale="6" xChannelSelector="R" yChannelSelector="G"/>
      <feColorMatrix type="matrix" values="
        1.5 0 0 0 0
        0.5 0.8 0 0 0
        0 0.3 0.2 0 0
        0 0 0 1 0"/>
    </filter>
    <filter id="ice" x="-20%" y="-20%" width="140%" height="140%">
      <feTurbulence type="fractalNoise" baseFrequency="0.025" numOctaves="3" result="noise"/>
      <feDisplacementMap in="SourceGraphic" in2="noise" scale="4" xChannelSelector="R" yChannelSelector="G"/>
      <feColorMatrix type="matrix" values="
        0.5 0 0 0 0.3
        0 0.6 0 0 0.4
        0 0 1 0 0.2
        0 0 0 0.9 0"/>
    </filter>
    <filter id="marble" x="-20%" y="-20%" width="140%" height="140%">
      <feTurbulence type="fractalNoise" baseFrequency="0.015" numOctaves="3" result="noise"/>
      <feColorMatrix type="matrix" values="
        0.7 0 0 0 0.1
        0 0.5 0 0 0.05
        0 0 0.3 0 0
        0 0 0 0.15 0" in="noise" result="coloredNoise"/>
      <feComposite operator="in" in="coloredNoise" in2="SourceGraphic" result="texture"/>
      <feBlend mode="multiply" in="texture" in2="SourceGraphic"/>
    </filter>
  </defs>
</svg>
`;

// =================== 页面组件 ===================
export default function FontStylePreviewPage() {
  const [fontsLoaded, setFontsLoaded] = useState(false);
  const [selectedFontCat, setSelectedFontCat] = useState('全部');
  const [selectedEffectCat, setSelectedEffectCat] = useState('全部');

  useEffect(() => {
    if (typeof document !== 'undefined' && document.fonts) {
      document.fonts.ready.then(() => setFontsLoaded(true));
    } else {
      setFontsLoaded(true);
    }
  }, []);

  const fontCats = ['全部', ...Array.from(new Set(FONT_LIST.map(f => f.category)))];
  const filteredFonts = selectedFontCat === '全部' ? FONT_LIST : FONT_LIST.filter(f => f.category === selectedFontCat);

  const effectCats = ['全部', ...Array.from(new Set(ART_TEXT_STYLES.map(s => s.category)))];
  const filteredStyles = selectedEffectCat === '全部' ? ART_TEXT_STYLES : ART_TEXT_STYLES.filter(s => s.category === selectedEffectCat);

  return (
    <div className="min-h-screen bg-gray-50">
      <div dangerouslySetInnerHTML={{ __html: SVG_FILTERS }} />

      {/* Header */}
      <div className="sticky top-0 z-50 bg-white/90 backdrop-blur border-b border-gray-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-[#19315d]">字体与艺术字预览 V4</h1>
            <p className="text-xs text-gray-400">
              描边 + 投影 + 纹理 + 渐变 + 发光 + 3D + 背景框 | {fontsLoaded ? '✅ 就绪' : '⏳ 加载中'}
            </p>
          </div>
          <a href="/editor" className="text-sm text-[#2254f4] hover:underline font-medium">← 返回编辑器</a>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6 space-y-10">

        {/* ===== 一、基础效果类型说明 ===== */}
        <section>
          <h2 className="text-lg font-bold text-[#19315d] mb-1">一、艺术字 = 基础效果组合</h2>
          <p className="text-xs text-gray-400 mb-4">每种艺术字样式由以下基础效果组合而成</p>
          <div className="grid grid-cols-4 sm:grid-cols-7 gap-3">
            {BASE_EFFECT_TYPES.map(e => (
              <div key={e.id} className="bg-white rounded-xl border border-gray-200 p-3 text-center hover:shadow-md transition-shadow">
                <div className="text-2xl mb-1">{e.icon}</div>
                <div className="text-sm font-semibold text-[#19315d]">{e.label}</div>
                <div className="text-[10px] text-gray-300 mt-1">{e.desc}</div>
              </div>
            ))}
          </div>
        </section>

        {/* ===== 二、字体选择器 ===== */}
        <section>
          <div className="flex items-baseline gap-3 mb-1">
            <h2 className="text-lg font-bold text-[#19315d]">二、字体选择器</h2>
            <span className="text-xs text-gray-400">{FONT_LIST.length} 款</span>
          </div>
          <div className="flex gap-1.5 mb-4 flex-wrap">
            {fontCats.map(cat => (
              <button key={cat} onClick={() => setSelectedFontCat(cat)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${selectedFontCat === cat ? 'bg-[#f0f6ff] text-[#2254f4]' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}>
                {cat}
              </button>
            ))}
          </div>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            {filteredFonts.map((font, i) => (
              <div key={i} className="flex items-center gap-4 px-5 py-3 border-b border-gray-100 last:border-0 hover:bg-gray-50">
                <div className="w-28 shrink-0">
                  <div className="text-sm font-medium text-[#19315d]">{font.name}</div>
                  <div className="text-[10px] text-gray-300">{font.category}</div>
                </div>
                <div className="flex-1 flex items-baseline gap-6">
                  <span style={{ fontFamily: font.family, fontSize: 22, color: '#19315d' }} className="truncate">设计预览文字效果</span>
                  <span style={{ fontFamily: font.family, fontSize: 14, color: '#94a3b8' }} className="hidden md:inline">The quick brown fox</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ===== 三、艺术字样式库 ===== */}
        <section>
          <div className="flex items-baseline gap-3 mb-1">
            <h2 className="text-lg font-bold text-[#19315d]">三、艺术字样式库</h2>
            <span className="text-xs text-gray-400">{ART_TEXT_STYLES.length} 种组合样式</span>
          </div>
          <div className="flex gap-1.5 mb-4 flex-wrap">
            {effectCats.map(cat => (
              <button key={cat} onClick={() => setSelectedEffectCat(cat)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${selectedEffectCat === cat ? 'bg-[#f0f6ff] text-[#2254f4]' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}>
                {cat}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {filteredStyles.map((style) => (
              <div key={style.id} className="rounded-xl border border-gray-200 overflow-hidden hover:shadow-lg hover:scale-[1.02] transition-all duration-200">
                {/* 展示区 */}
                <div className="py-8 px-4 flex items-center justify-center min-h-[110px]"
                  style={style.bgStyle || { background: '#f8f9fa' }}>
                  <span style={{
                    fontFamily: style.fontFamily || '"Noto Sans SC", sans-serif',
                    fontSize: style.fontSize,
                    fontWeight: style.fontWeight,
                    ...style.textStyle,
                  }}>
                    {style.sample}
                  </span>
                </div>
                {/* 底部信息 */}
                <div className="px-3.5 py-2.5 bg-white border-t border-gray-100">
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-xs font-semibold text-[#19315d]">{style.name}</div>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-400">{style.category}</span>
                  </div>
                  <div className="flex gap-1 flex-wrap">
                    {style.effects.map(e => (
                      <span key={e} className="text-[9px] px-1.5 py-0.5 rounded bg-[#f0f6ff] text-[#2254f4]">{e}</span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ===== 四、效果组合矩阵 ===== */}
        <section>
          <h2 className="text-lg font-bold text-[#19315d] mb-4">四、效果组合拆解示例</h2>
          <div className="space-y-6">
            {/* 金红大促拆解 */}
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-[#19315d] mb-4">「金红大促」效果拆解</h3>
              <div className="space-y-3">
                {[
                  { label: '① 背景框', desc: '红色渐变圆角矩形', style: { background: 'linear-gradient(135deg, #c0392b, #e74c3c)', borderRadius: '8px', padding: '10px 20px' } },
                  { label: '② + 渐变填充', desc: '黄金多色渐变', style: { background: 'linear-gradient(180deg, #f7d774, #c8952e, #f7d774, #a87b22)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' } },
                  { label: '③ + 投影', desc: '叠加 drop-shadow', style: { background: 'linear-gradient(180deg, #f7d774, #c8952e, #f7d774, #a87b22)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', filter: 'drop-shadow(0 2px 3px rgba(0,0,0,0.4))' } },
                  { label: '④ + 描边(可选)', desc: '再加描边更立体', style: { background: 'linear-gradient(180deg, #f7d774, #c8952e, #f7d774, #a87b22)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', filter: 'drop-shadow(0 2px 3px rgba(0,0,0,0.4))', WebkitTextStroke: '1px rgba(0,0,0,0.2)' } },
                ].map((step, i) => (
                  <div key={i} className="flex items-center gap-4">
                    <div className="w-20 shrink-0">
                      <div className="text-xs font-medium text-[#19315d]">{step.label}</div>
                      <div className="text-[10px] text-gray-300">{step.desc}</div>
                    </div>
                    <div className="rounded-lg px-4 py-2" style={{ background: "#f0f0f0" }}>
                      <span style={{
                        fontFamily: '"Noto Sans SC", sans-serif',
                        fontSize: 32, fontWeight: 900,
                        ...(step.style as React.CSSProperties),
                      }}>限时抢购</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* 3D红色拆解 */}
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-[#19315d] mb-4">「红色3D」效果拆解</h3>
              <div className="space-y-3">
                {[
                  { label: '① 基础文字', desc: '纯红色填充', style: { color: '#e74c3c' } },
                  { label: '② + 1层投影', desc: '1px 偏移深红', style: { color: '#e74c3c', textShadow: '1px 1px 0 #c0392b' } },
                  { label: '③ + 多层投影', desc: '叠加多层形成立体', style: { color: '#e74c3c', textShadow: '1px 1px 0 #c0392b, 2px 2px 0 #c0392b, 3px 3px 0 #a93226, 4px 4px 0 #a93226, 5px 5px 0 #922b21, 6px 6px 6px rgba(0,0,0,0.2)' } },
                  { label: '④ + 背景框', desc: '加渐变背景完成', style: { color: '#e74c3c', textShadow: '1px 1px 0 #c0392b, 2px 2px 0 #c0392b, 3px 3px 0 #a93226, 4px 4px 0 #a93226, 5px 5px 0 #922b21, 6px 6px 6px rgba(0,0,0,0.2)' }, bgStyle: { background: 'linear-gradient(135deg, #ffecd2, #fcb69f)', borderRadius: '8px', padding: '10px 20px' } },
                ].map((step, i) => (
                  <div key={i} className="flex items-center gap-4">
                    <div className="w-20 shrink-0">
                      <div className="text-xs font-medium text-[#19315d]">{step.label}</div>
                      <div className="text-[10px] text-gray-300">{step.desc}</div>
                    </div>
                    <div className="rounded-lg px-4 py-2" style={{ background: "#f0f0f0" }}>
                      <span style={{
                        fontFamily: '"Noto Sans SC", sans-serif',
                        fontSize: 36, fontWeight: 900,
                        ...(step.style as React.CSSProperties),
                      }}>3D立体</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* ===== 五、Fabric.js 实现方案 ===== */}
        <section>
          <h2 className="text-lg font-bold text-[#19315d] mb-4">五、Fabric.js 实现方案</h2>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">效果</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Fabric 支持</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">实现方案</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">难度</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { name: '渐变填充', support: '✅ 原生', method: 'fill = new fabric.Gradient({ type, coords, colorStops })', difficulty: '⭐⭐' },
                  { name: '描边', support: '✅ 原生', method: 'stroke + strokeWidth', difficulty: '⭐' },
                  { name: '投影', support: '✅ 原生', method: 'shadow = new fabric.Shadow({ color, blur, offsetX, offsetY })', difficulty: '⭐' },
                  { name: '3D立体', support: '✅ 原生', method: '多层 text 对象叠加，逐层偏移', difficulty: '⭐⭐⭐' },
                  { name: '发光', support: '⚠️ 变通', method: '底层模糊 text 叠加 或 多重 shadow', difficulty: '⭐⭐⭐' },
                  { name: '文字背景框', support: '✅ 原生', method: 'Rect + Text 组合 Group', difficulty: '⭐⭐' },
                  { name: '金属渐变', support: '✅ 原生', method: '多色 Gradient 循环渐变', difficulty: '⭐⭐' },
                  { name: 'SVG 滤镜纹理', support: '⚠️ 变通', method: '离屏 Canvas 渲染 → Pattern', difficulty: '⭐⭐⭐⭐' },
                  { name: '霓虹管效果', support: '⚠️ 变通', method: '多层 shadow 叠加模拟', difficulty: '⭐⭐⭐⭐' },
                  { name: '火焰/冰霜', support: '⚠️ 变通', method: 'SVG filter 离屏渲染 → 贴图', difficulty: '⭐⭐⭐⭐⭐' },
                ].map((row, i) => (
                  <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-2.5 font-medium text-[#19315d]">{row.name}</td>
                    <td className="px-4 py-2.5">{row.support}</td>
                    <td className="px-4 py-2.5 text-gray-500 text-xs font-mono">{row.method}</td>
                    <td className="px-4 py-2.5 text-amber-600">{row.difficulty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
