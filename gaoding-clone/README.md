# 稿定设计编辑器 - 界面克隆

通过 Puppeteer 从 https://www.gaoding.com/editor/design?id=36281412433466481 真实渲染提取的完整编辑器界面。

## 文件说明

- `index.html` (1.2MB) - 完整的静态 HTML，包含所有 CSS 样式和内联 DOM 结构
- `screenshot.png` - 编辑器界面截图
- `rendered.html` - Puppeteer 提取的原始渲染 HTML

## 使用方式

直接用浏览器打开 `index.html` 即可查看完整的编辑器界面。

## 说明

- 所有样式已通过 CSS rules 提取并内联到 HTML 中
- 不需要 JavaScript 运行，纯静态页面
- 图片等资源仍然引用 CDN（dancf.com）
- 界面包含完整的工具栏、侧边栏、画布、属性面板等所有 UI 元素
