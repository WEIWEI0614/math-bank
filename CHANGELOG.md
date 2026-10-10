# 更新日志

本项目采用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 📌 说明：仓库存在两条独立的提交历史（本地开发线与早期部署线，无共同祖先）。
> 本文件按**时间顺序**合并记录，不区分是哪条线引入的。

---

## [未发布]

### 新增

- **完整文档体系** —— `README.md` + `docs/` 七篇文档：
  [产品手册](docs/PRODUCT.md)、[架构说明](docs/ARCHITECTURE.md)、
  [自适应引擎](docs/ADAPTIVE-ENGINE.md)、[数据格式](docs/DATA-FORMAT.md)、
  [HTTP API](docs/API.md)、[部署指南](docs/DEPLOY.md)、[安全设计](docs/SECURITY.md)、
  [已知缺陷](docs/KNOWN-ISSUES.md)
- **`scripts/check_data.py`** —— 题库数据自检脚本（标准库实现，无需 `bank.sqlite`），
  检查字段完整性、知识点悬空引用、答案截断尖峰、`qid` 重复、索引一致性
- `LICENSE`（MIT + 数据版权声明）、`CONTRIBUTING.md`、`CHANGELOG.md`
- GitHub Actions 工作流，在 PR 上自动跑数据自检与 Python 语法检查

### 文档化的既有缺陷（本次新发现）

- 🔴 **1,331 题（11.1%）因 `topic_id` 悬空引用，永远不会被自适应出题选中**
  —— CIE 9709 P2 最严重：725 题里只有 223 题（31%）可练。见 [KNOWN-ISSUES §1](docs/KNOWN-ISSUES.md#1-知识点悬空引用111-题目无法被选中-)

---

## [0.1.0] — 2026-10-08

### 修复

- **题面泄漏 JS 注释** —— 一段 `/* */` 注释写在 `renderQ()` 的 innerHTML 模板字符串**内部**，
  被浏览器当成普通 HTML 渲染，用户直接看到开发注释。已移到模板字符串外
- **身份切换** —— 修复教师端 ⇄ 学生端切换；对答案时同时显示原题
- **自评口径** —— 从"主观打分"改为"你实际做到哪一步"，并支持答后订正
- **题干呈现** —— 改为**原卷截图主显、文字版折叠**（应对 OCR 残损）

## [0.0.x] — 2026-10-07

### 修复

- **公式渲染失效** —— KaTeX 从 cdnjs 加载，CDN 不可达时 `window.katex` 为 `undefined`，
  所有公式显示为原始源码。改为**本地内置 KaTeX**（含 20 个 woff2 字体），离线可用
- **越权导出** —— 学生 token 曾可导出全班数据（身份判定与下游读取复用了同一变量）。
  改为独立的 `req_name` / `export_all`，学生导出强制以 token 身份为准
- **错因统计失效** —— 修复错因分布不更新
- **题干缺失** —— 修复部分题目题干为空

## 早期部署线 — 2026-09-26 ~ 2026-09-27

- Render 免费部署蓝图（`render.yaml` / `Procfile`）
- 修复登录框抢占焦点；每轮题数上限改为 10
- 修复章节题数统计与章节轮次重启的兜底逻辑
- 重新部署以重置线上数据库并清理探针测试数据

---

## 版本说明

| 版本 | 含义 |
|---|---|
| 0.0.x | 内部开发 |
| 0.1.0 | 学生端 + 教师端功能完整，可日常教学使用 |
| 1.0.0 | 待 [KNOWN-ISSUES](docs/KNOWN-ISSUES.md) 中的 🔴 级缺陷修复后发布 |
