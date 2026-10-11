# Frontend 开发约定

本项目使用 Next.js 15 App Router、React 18、TypeScript、Tailwind CSS 和 CSS Modules。以当前代码、`../docs/ARCHITECTURE.md`、`../docs/DESIGN_SYSTEM.md` 为准，不按旧版模板库/编辑器方案新增功能。

## 代码组织

- 页面放在 `src/app/`，业务 API 封装在 `src/services/`，复用组件放在 `src/components/`。页面、服务和类型改动应一起检查。
- 全局 UI 状态按实际作用域选择 React state/context；不要为已删除的 Zustand store 重新引入依赖。
- 生图是服务端异步任务。前端提交后保留任务标识，通过现有任务查询与恢复接口展示排队、生成、失败和结果；不要让页面等待长连接直到上游返回图片。
- Dify 与 Hermes 是不同的工作流入口，分别使用现有 API 服务，不共用旧的前端 SSE helper。
- 模型适配器及密钥管理在后端，不在浏览器增加模型调用或密钥。

## 界面与交互

- 优先复用 `src/components/` 中现有组件；样式可用 Tailwind 和 CSS Modules。全局 token 在 `src/styles/globals.css`，工作区结构在 `src/components/navigation/workspace-shell.module.css`。
- 保持侧栏和右侧路由容器分离；检查窄屏、低高度、滚动容器及 `prefers-reduced-motion`。
- 图标操作提供可访问名称；表单错误、任务失败和重试要有可见反馈。避免图片加载和列表追加时页面位置跳动。
- 不恢复独立模板库或画布编辑器；图库共享操作通过现有素材 API。

## 验证

改动后在 `frontend/` 运行 `npm run type-check`、`npm test` 和 `npm run build`。覆盖率范围由 `vitest.config.ts` 定义；不要把已删除文件加入覆盖率配置。
