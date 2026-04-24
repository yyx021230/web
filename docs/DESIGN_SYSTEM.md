# AI Creative Studio — Design System

## 版本: 1.0.0
## 最后更新: 2025-04-21

---

## 1. 色彩系统

### 品牌色
| Token | 值 | 用途 |
|-------|-----|------|
| `--primary` | `#6366f1` | 主按钮、链接、活跃状态 |
| `--primary-hover` | `#4f46e5` | 主按钮悬停 |
| `--primary-light` | `#e0e7ff` | 主色背景 |
| `--primary-text` | `#4338ca` | 主色文本 |

### 功能色
| Token | 值 | 用途 |
|-------|-----|------|
| `--success` | `#22c55e` | 成功状态、通过 |
| `--success-bg` | `#f0fdf4` | 成功背景 |
| `--warning` | `#f59e0b` | 警告提示 |
| `--warning-bg` | `#fffbeb` | 警告背景 |
| `--danger` | `#ef4444` | 错误、删除、危险操作 |
| `--danger-bg` | `#fef2f2` | 危险背景 |
| `--info` | `#3b82f6` | 信息提示 |
| `--info-bg` | `#eff6ff` | 信息背景 |

### 中性色
| Token | 值 | 用途 |
|-------|-----|------|
| `--background` | `#ffffff` | 页面背景 |
| `--background-dark` | `#0f172a` | 深色背景 |
| `--surface` | `#f8fafc` | 卡片、面板背景 |
| `--surface-hover` | `#f1f5f9` | 悬停背景 |
| `--border` | `#e2e8f0` | 边框 |
| `--border-light` | `#f1f5f9` | 浅色边框 |
| `--text-primary` | `#0f172a` | 主要文本 |
| `--text-secondary` | `#64748b` | 次要文本 |
| `--text-muted` | `#94a3b8` | 弱化文本 |
| `--text-inverse` | `#ffffff` | 深色背景上的文本 |

### Canvas 工作区
| Token | 值 | 用途 |
|-------|-----|------|
| `--canvas-bg` | `#f1f5f9` | 画布背景 |
| `--canvas-border` | `#cbd5e1` | 画布边框 |
| `--canvas-grid` | `#e2e8f0` | 网格线 |
| `--canvas-guide` | `#3b82f6` | 辅助线 |

---

## 2. 间距系统

### 基础间距（4px 网格）
| Token | Tailwind | 值 | 用途 |
|-------|----------|-----|------|
| `space-xs` | `p-1` | 4px | 紧凑间距 |
| `space-sm` | `p-2` | 8px | 小组件间距 |
| `space-md` | `p-4` | 16px | 标准间距 |
| `space-lg` | `p-6` | 24px | 模块间距 |
| `space-xl` | `p-8` | 32px | 大模块间距 |
| `space-2xl` | `p-12` | 48px | 区域间距 |

### 使用规则
- 所有间距必须是 4 的倍数
- 优先使用 Tailwind 内置间距类
- 面板内边距统一 `p-4`
- 卡片间距统一 `gap-4`

---

## 3. 排版系统

### 字体族
```css
--font-sans: 'Inter', system-ui, -apple-system, sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', monospace;
```

### 字号 Scale
| Token | 值 | 行高 | 字重 | 用途 |
|-------|-----|------|------|------|
| `text-xs` | 12px | 16px | 400 | 标签、提示 |
| `text-sm` | 13px | 20px | 400 | 次要文本、表单 |
| `text-base` | 14px | 20px | 400 | 正文 |
| `text-lg` | 16px | 24px | 500 | 小标题 |
| `text-xl` | 20px | 28px | 600 | 面板标题 |
| `text-2xl` | 24px | 32px | 600 | 页面标题 |
| `text-3xl` | 30px | 36px | 700 | 大标题 |

---

## 4. 圆角系统

| Token | Tailwind | 值 | 用途 |
|-------|----------|-----|------|
| `rounded-sm` | `rounded-sm` | 2px | 小标签 |
| `rounded-md` | `rounded-md` | 6px | 按钮、输入框 |
| `rounded-lg` | `rounded-lg` | 8px | 卡片、面板 |
| `rounded-xl` | `rounded-xl` | 12px | 对话框、弹窗 |
| `rounded-full` | `rounded-full` | 9999px | 头像、标签 |

---

## 5. 阴影系统

| Token | 值 | 用途 |
|-------|-----|------|
| `shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | 按钮、小卡片 |
| `shadow-md` | `0 4px 6px -1px rgba(0,0,0,0.1)` | 下拉菜单、工具提示 |
| `shadow-lg` | `0 10px 15px -3px rgba(0,0,0,0.1)` | 对话框、弹窗 |
| `shadow-xl` | `0 20px 25px -5px rgba(0,0,0,0.1)` | 重要弹窗 |

---

## 6. 布局规范

### 编辑器布局
```
┌────────────────────────────────────────────────────┐
│  Header (48px) — Logo + 工具栏 + 用户              │
├────────┬──────────────────────────┬────────────────┤
│ Sidebar│                          │   Properties   │
│ (280px)│     Canvas Area          │   Panel        │
│        │     (flex-1)             │   (320px)      │
│        │                          │                │
│ - 工具 │                          │ - 属性编辑      │
│ - 图层 │                          │ - 样式设置      │
│ - 模板 │                          │ - AI 操作       │
│ - AI   │                          │                │
└────────┴──────────────────────────┴────────────────┘
```

### 响应式断点
| Token | 值 | 用途 |
|-------|-----|------|
| `sm` | 640px | 移动端 |
| `md` | 768px | 平板 |
| `lg` | 1024px | 桌面 |
| `xl` | 1280px | 大屏 |
| `2xl` | 1536px | 超大屏 |

> 编辑器功能仅在 `lg` (1024px) 以上可用

---

## 7. 组件使用规则

### 按钮
- 主操作: `<Button>` (默认 primary)
- 次要操作: `<Button variant="outline">`
- 危险操作: `<Button variant="destructive">`
- 文字链接: `<Button variant="link">`
- 图标按钮: `<Button size="icon">`

### 表单
- 所有表单使用 `react-hook-form` + `zod` 验证
- 标签放在输入框上方
- 必填项标记 `*`
- 错误信息在输入框下方红色显示

### 对话框
- 确认操作: 必须有确认对话框
- 危险操作: 使用 destructive 主题
- 表单弹窗: 使用大尺寸对话框

### 通知
- 成功: toast (green)
- 错误: toast (red)
- 警告: toast (yellow)
- 信息: toast (blue)
