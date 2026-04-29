# AI Creative Studio — 项目分析与完善计划

## 一、项目现状分析

### 1. 项目定位
AI Creative Studio 是一个集在线图形编辑、AI 生图、工作流编排于一体的创意工作台。目标用户是需要快速生成营销素材的设计师/运营人员。

### 2. 已完成的功能

| 模块 | 状态 | 说明 |
|------|------|------|
| 认证系统 | 完成 | JWT + 注册/登录，dev模式自动登录 |
| 编辑器 | 完成 | Fabric.js 编辑器，保存/导出/撤销/缩放 |
| AI 生图 | 部分完成 | Seedream 可用，Midjourney/SD 为空壳 |
| Dify 工作流 | 完成 | 配置/运行/日志/任务管理/SSE 流式 |
| 图库管理 | 完成 | 素材上传/搜索/分类/文件夹/车型库 |
| 模板库 | 完成 | AI 生图结果存为模板 |
| 文案库 | 完成 | 创建/编辑/搜索/标签提取 |
| 后台管理 | 完成 | Dashboard/用户管理/图库管理/API使用统计 |
| 车型库 | 完成 | 品牌/车型/图片关联 |

### 3. 关键问题与不足

#### A. 功能缺失（优先级高）
1. **登录页面功能不完整**
   - Google/GitHub 登录是 `alert()` 模拟，无实际实现
   - "忘记密码"是 `alert()` 模拟
   - "记住我"复选框无功能
   - 登录成功后跳转到 `/editor`，未登录后无法查看其他页面

2. **无权限控制**
   - AuthGuard 组件为空（始终放行）
   - 非 admin 用户可以访问 `/admin` 所有页面
   - 无路由级别的权限守卫

3. **AI 模型仅 Seedream 可用**
   - Midjourney adapter 全是 `NotImplementedError`
   - Stable Diffusion adapter 全是 `NotImplementedError`
   - GPT Image 2 适配器存在但配置为空

4. **工作流管理后台空白**
   - `/admin/workflows` 只有一个占位提示
   - 后台无法管理工作流配置

5. **无操作反馈**
   - 全局无 toast/notification 系统（虽然有 `@radix-ui/react-toast` 依赖）
   - API 错误只显示 console.error，用户看不到提示

6. **编辑器功能有限**
   - CanvasManager 全是 TODO 注释
   - ObjectFactory 全是 TODO 注释
   - 缺少文字编辑、形状绘制、图层管理等核心编辑功能

#### B. 代码质量问题
1. **前端类型安全不足**
   - 多处 `any` 类型（dashboard 页面中 `(m: any)` 等）
   - editorApi 返回类型定义不全
   - workflowStore 的 TODO 说明 API 调用未接入

2. **后端异常处理粗糙**
   - 多处 `raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")` 暴露内部实现
   - stop_task 接口有 TODO：未校验任务所有权

3. **安全漏洞**
   - JWT secret 为默认值 `change-me-in-production`
   - CORS 允许所有方法/头
   - 文件上传无大小/类型限制
   - 无 rate limiting
   - 密码强度无要求（仅6字符）

4. **数据库配置不一致**
   - config.py 默认 PostgreSQL，实际运行用 SQLite
   - Redis URL 配置了但未使用

5. **无测试覆盖**
   - 后端有测试框架但测试用例很少
   - 前端无任何自动化测试

#### C. 用户体验问题
1. 无加载骨架屏（loading skeleton），API 请求时白屏
2. 无错误边界（error boundary）
3. 无全局搜索
4. 无用户偏好设置（主题、语言等）
5. 无数据导出功能

---

## 二、完善计划

### Phase 1: 权限与安全加固（最关键）
- **1.1** 路由权限守卫 — 非 admin 访问 `/admin` 时拦截并重定向
- **1.2** 修复 AuthGuard — 验证 token 有效性，过期自动跳转登录
- **1.3** 全局 Toast 通知 — 接入 `@radix-ui/react-toast`，API 错误/成功统一提示
- **1.4** 完善登录页 — 移除 Google/GitHub 模拟按钮或标注"即将上线"

### Phase 2: 功能补齐
- **2.1** 工作流管理后台 — 在 `/admin/workflows` 展示和管理所有 Dify 工作流配置
- **2.2** 加载骨架屏 — 所有列表页/详情页添加 loading skeleton
- **2.3** 编辑器增强 — 完善 CanvasManager 和 ObjectFactory，至少实现文字编辑和形状绘制
- **2.4** 全局搜索 — 顶部搜索框，支持搜索项目/素材/模板/工作流

### Phase 3: 代码质量提升
- **3.1** 消除 `any` 类型 — Dashboard 和所有页面的显式类型
- **3.2** 后端异常脱敏 — 生产环境不暴露内部错误详情
- **3.3** 文件上传限制 — 大小/类型校验
- **3.4** 统一 API 响应格式 — 确保所有接口返回一致的 `{ code, message, data }`

### Phase 4: 扩展性（可选）
- **4.1** Midjourney / Stable Diffusion 适配器实现
- **4.2** Redis 缓存接入（模板列表/素材列表）
- **4.3** S3/MinIO 存储适配器
- **4.4** 用户设置页面（头像/密码修改）

---

## 三、实施建议

**推荐从 Phase 1 开始**，因为权限和安全是基础，影响到后续所有功能。

关键风险点：
- 权限守卫需要确保 dev 模式下不阻断现有流程
- Toast 系统需要全局 Provider，需修改 root layout
- 工作流管理后台已有前端实现（`/workflows`），后台版本主要是复用 + 管理视角

请告诉我你想从哪个 Phase 开始，或者对上述分析有不同意见我们可以调整。
