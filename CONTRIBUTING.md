# 贡献指南

感谢你愿意为这个项目出力。动手前请先读这篇 —— 尤其是**版权红线**。

---

## 🚫 版权红线（会被直接拒绝的 PR）

本仓库是 **public**。以下内容**不要提交**：

| 禁止 | 原因 |
|---|---|
| 原卷图片 / Mark Scheme 扫描件 / PDF | 属 CAIE、Pearson Edexcel、UKMT 等考试局版权 |
| 完整真题 PDF | 同上 |
| 从付费渠道获取的题库 | 授权问题 |

**为什么**：真题与 Mark Scheme 的著作权归考试局所有。仓库只公开**代码**与
**结构化元数据**（题干文本、知识点、难度、分值、出处年份）。

> 原卷图片（31,532 张 / 2.9 GB）保存在本地独立版本库 `site/data/img/`，
> 已被 `.gitignore` 排除。**请勿尝试把它加进来。**

**可以做**：提交从**已获授权的样卷（Specimen Paper）**或**自己原创**的题目。

---

## 开发环境

```bash
git clone https://github.com/WEIWEI0614/math-bank.git
cd math-bank

python3 site/serve.py          # → http://127.0.0.1:8770
```

后端零第三方依赖（只用标准库），**不需要 venv**。
`requirements.txt` 里的 `PyMuPDF` / `Pillow` / `numpy` 只给构建脚本用。

---

## 数据自检

改动题库数据后**必须**跑一遍：

```bash
python3 scripts/check_data.py
```

它会检查：

- 每个单元能否正确解析
- 题目是否都是定长 11 字段
- `topic_id` 是否悬空引用
- 答案长度分布是否有定长截断尖峰
- `qid` 是否重复

CI 也会跑这个脚本，**不通过无法合并**。

---

## 代码风格

| 位置 | 约定 |
|---|---|
| `site/serve.py` | Python 标准库，4 空格缩进，中英文注释混排可以 |
| `site/index.html` | 原生 JS，`"use strict"`，2 空格缩进，无构建步骤 |
| 注释 | **写"为什么"，不写"做了什么"** —— 见下面 |

### 注释规范（重要）

这个项目刻意维护了大量"踩坑注释"—— 记录**为什么**这么写，而不是复述代码。

```python
# ✅ 好：解释了动机，后人不会改回去
# 只读身份判定用独立的 req_name / export_all 两个变量：
# 早前这里复用了后面 export 分支还要再读一次的 name，
# 导致学生不带 name 的请求被重置成 ""，落进「教师全员导出」分支。
# 两者必须分开，不可复用。

# ❌ 差：复述代码
# 设置请求名字
```

**改代码时如果绕过了一个坑，请把这个坑写进注释** —— 否则下一个人会踩回去。

---

## 不要破坏的两条原则

1. **零 LLM 调用** —— 运行时不调任何 AI 接口。
   想加 AI 能力？**离线预生成物料**，不要运行时调 API。
2. **数据不出本机** —— 本机模式只监听 `127.0.0.1`。
   不要为了"方便局域网访问"放宽这个限制。

---

## 提交新单元

1. 按 [docs/DATA-FORMAT.md](docs/DATA-FORMAT.md) 生成 `site/data/<UNIT>.js`
2. 在 `site/data/index.js` 注册（`code` / `name` / `file` / `n` / `nt` / `kb`）
3. 跑 `python3 scripts/check_data.py`
4. 确认题目**有明确授权**（样卷或原创）

---

## PR 流程

1. Fork 并建分支（`feat/xxx` / `fix/xxx` / `docs/xxx`）
2. 改动后跑 `scripts/check_data.py`
3. 如果改了行为，**同步更新 `docs/` 里对应的文档**
4. 写清楚 PR 描述：改了什么、为什么、怎么验证

### Commit message

沿用现有风格，中文或英文均可，但要说清**动机**：

```
fix: 修复学生 token 越权导出全班数据

身份判定与下游读取复用了同一个变量，导致不带 name 的学生请求
落进「教师全员导出」分支。改用独立的 req_name / export_all。
```

---

## 报告问题

- **Bug** → 开 issue，附上：运行模式（本机 / 云）、Python 版本、复现步骤
- **数据错误** → 开 issue，附上 `qid` 与错在哪
- **安全问题** → **不要开公开 issue**，直接联系仓库所有者

已知的数据缺陷请先查 [docs/KNOWN-ISSUES.md](docs/KNOWN-ISSUES.md)，
答案截断、OCR 残损这类问题**已经记录在案**，重复报告不会加速修复。
