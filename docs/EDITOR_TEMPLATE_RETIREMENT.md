# 独立模板库与编辑器下线

## 范围

- 删除模板库、画布编辑器及旧模板页：/library、/editor、/templates。
- 删除后台设计项目管理 /admin/projects，用户统计不再查询或展示项目数。
- 删除画布组件、状态、Fabric 转换工具、专属 API、静态模板、字体预览页、编辑器演示页与 gaoding-clone 参考工程。
- 移除 fabric 和 @types/fabric 依赖及仅供编辑器使用的字体加载。
- 登录后的默认入口改为 /ai。历史设计稿只展示缩略图，不再提供打开编辑入口。
- 移除 /api/v1/templates、/api/v1/projects、/api/v1/admin/resources/projects 和 POST /api/v1/materials/design。
- 共享图库 API 独立为 materialApi，保留 AI 保存、草稿、参考图选择、素材标签和文件夹管理。

## 数据边界

没有清空本地或线上数据库，没有删除用户上传文件、AI 生图结果、任务记录。
历史 projects、templates 表与 materials.design_json 字段及历史迁移保留，
只用于数据库兼容和数据留存，不再提供画布编辑接口。
素材详情和列表不再下发 design_json，更新素材也不会覆盖此字段。

图库的 AI 模版属于 materials / ai-template，与本次删除的独立模板库不同。
提示词库、文案库、车型图库、工作流、运营和投流看板保留。
种子脚本只初始化管理员和角色，不再生成编辑器预置素材；--reset 拒绝执行，避免清空历史资产。

## 验证与部署注意

本次只在本地修改和验证，未部署。

1. 前端执行 npm run type-check、npm test；确认 AI 与图库正常、旧路由为 404。
2. 后端执行 test_editor_retirement、素材权限/保存、后台统计、种子脚本等相关回归测试。
3. 新数据库发布冒烟使用独立临时 SQLite，不使用本地业务库或线上库。
4. 后续发布必须用干净暂存目录构建新镜像，禁止仅覆盖解压旧源码后直接构建，避免已删除页面残留。
5. 若同步 Windows 源码工作目录，应按版本删除清单处理旧模块文件，不能删除 uploads、.env、数据库目录或卷。
6. 不需要删表迁移，不需要重置数据库，不需要清空任务队列；按已有发布规程保护进行中的生图任务。
7. 回滚使用上一版本完整镜像和发布源码，不靠只覆盖部分文件恢复页面。

旧设计/发布文档中提及编辑器的内容视为历史记录，当前模块范围以此文档及实际路由为准。

## 本地验证记录

- 前端 TypeScript 检查通过，74 项前端测试通过。
- 后端相关回归 58 项通过，独立临时数据库的迁移及跨模块发布冒烟 1 项通过。
- 本地 HTTP 检查：/editor、/library、/templates、/admin/projects 返回 404；
  /ai、/gallery、/workflows、/prompts 返回 200。
- 未执行生产部署，也未清空本地业务数据库或调用付费生图上游。
