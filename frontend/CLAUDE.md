# Frontend AI Coding Rules

## 项目信息
- 项目: AI Creative Studio (AI创意工作台)
- 技术栈: Next.js 14 (App Router) + TypeScript + Tailwind CSS + shadcn/ui + Zustand + Fabric.js
- 目录: /Users/yyx/ztqc/web/frontend

## 核心规则

### 1. 严格遵循的约定
- **必须使用 TypeScript**，禁止使用 `any` 类型，使用 `unknown` 或具体类型替代
- **必须使用函数式组件**，禁止 class 组件
- **样式必须使用 Tailwind CSS**，禁止写行内 style（除动态计算值外）
- **组件命名**: PascalCase (如 `ImageGenerator.tsx`)
- **文件命名**: 
  - 组件: PascalCase.tsx
  - hooks: useXxx.ts
  - 工具函数: kebab-case.ts
  - 类型定义: kebab-case.ts
- **API 服务层**: 所有 API 调用必须通过 `services/` 目录封装，禁止在组件中直接调用 fetch/axios

### 2. UI 设计规范 (Design Tokens)

#### 色彩（只能使用以下预设值）
```
Primary:    #6366f1 (indigo-500) — 主按钮、活跃状态
Primary-Hover: #4f46e5 (indigo-600)
Success:    #22c55e (green-500) — 成功提示
Warning:    #f59e0b (amber-500) — 警告提示
Danger:     #ef4444 (red-500)   — 删除、错误
Background: #ffffff / #0f172a  — 背景色
Surface:    #f8fafc            — 卡片背景
Border:     #e2e8f0            — 边框
Text-Primary:   #0f172a        — 主文本
Text-Secondary: #64748b        — 次要文本
Text-Muted:     #94a3b8        — 弱化文本
```

#### 间距（4px 倍数）
```
xs:  4px   |  sm:  8px   |  md:  16px
lg:  24px  |  xl:  32px  |  2xl: 48px
```

#### 圆角
```
sm: 4px  |  md: 8px  |  lg: 12px  |  xl: 16px  |  full: 9999px
```

#### 字体
```
标题: h1(32px/700) h2(24px/600) h3(20px/600)
正文: body(14px/400) | small(12px/400)
字体族: system-ui, -apple-system, sans-serif
```

#### 阴影
```
sm: 0 1px 2px rgba(0,0,0,0.05)
md: 0 4px 6px -1px rgba(0,0,0,0.1)
lg: 0 10px 15px -3px rgba(0,0,0,0.1)
```

### 3. 组件规范

#### 必须使用 shadcn/ui 组件
- 按钮: `@/components/ui/button`
- 对话框: `@/components/ui/dialog`
- 下拉菜单: `@/components/ui/dropdown-menu`
- 输入框: `@/components/ui/input`
- 表单: `@/components/ui/form`
- 标签页: `@/components/ui/tabs`
- 通知: `@/components/ui/toast`
- 选择器: `@/components/ui/select`
- 开关: `@/components/ui/switch`
- 滑块: `@/components/ui/slider`

#### 组件结构模板
```tsx
'use client';

import { useState } from 'react';

interface ComponentNameProps {
  // props 定义
}

export function ComponentName({ prop1, prop2 }: ComponentNameProps) {
  // hooks 必须在顶部
  const [state, setState] = useState(defaultValue);

  // 事件处理函数
  const handleClick = () => {
    // ...
  };

  return (
    <div className="flex items-center gap-4 p-4">
      {/* 内容 */}
    </div>
  );
}
```

### 4. 状态管理规范
- 全局状态使用 **Zustand**
- 每个 store 单独文件，放在 `stores/` 目录
- Store 命名: `useXxxStore`
- 必须使用 TypeScript 定义 store 类型
- 避免在 store 中存储可计算状态，使用 selector 计算

### 5. API 调用规范
- 使用 `services/api.ts` 创建的 axios 实例
- 所有 API 函数必须有类型定义
- 错误处理统一在 axios 拦截器中处理
- 禁止在组件中直接使用 `fetch()` 或 `axios()`

### 6. Fabric.js 集成规范
- Canvas 操作封装在 `lib/fabric/` 目录
- 禁止在组件中直接操作 canvas，必须通过 manager
- 所有 fabric 对象创建通过 `object-factory.ts`
- 历史记录通过 `history.ts` 管理

### 7. Dify 工作流集成规范
- Dify 调用封装在 `lib/dify/` 和 `services/difyApi.ts`
- SSE 流式响应统一通过 `dify/sse-handler.ts` 处理
- 工作流状态通过 `stores/workflowStore.ts` 管理

### 8. AI 生图模块规范
- 模型适配器实现 `lib/ai/model-adapter.ts` 接口
- 新模型注册到 `lib/ai/registry.ts`
- 禁止硬编码 API 密钥，使用环境变量

### 9. 禁止事项
- 禁止使用行内 style（除动态计算值）
- 禁止使用 `any` 类型
- 禁止在组件中直接调用 fetch/axios
- 禁止使用硬编码颜色值（使用 design token）
- 禁止跳过错误处理
- 禁止在 useEffect 中做不必要的数据请求
- 禁止使用 class 组件
- 禁止直接操作 DOM（除非必要）
