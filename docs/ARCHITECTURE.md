# 架构说明

> 面向开发者。使用说明请看 [PRODUCT.md](PRODUCT.md)。
> 本文档基于对 `serve.py`（702 行）与 `index.html`（1,923 行）的实际阅读，不是推测。

---

## 1. 一句话概括

一个**单页前端 + 标准库后端 + SQLite** 的本地应用。没有框架、没有构建步骤、没有运行时第三方依赖。

```
浏览器 ──HTTP──> site/serve.py ──> bank.sqlite
   ↑
   └── 直接加载 site/data/*.js（不经后端）
```

---

## 2. 目录结构

```
.
├── site/
│   ├── index.html              单页应用（1,923 行，含引擎、渲染、路由）
│   ├── serve.py                后端服务（702 行，标准库 http.server）
│   ├── vendor/katex/           KaTeX 0.16.9 本地副本 + 20 个 woff2 字体
│   └── data/
│       ├── index.js            单元索引（29 条元信息）
│       └── <UNIT>.js           29 个单元题库文件（共 17 MB）
├── docs/                       文档
├── requirements.txt            仅构建脚本需要（PyMuPDF / Pillow / numpy）
├── Procfile                    云部署启动命令
├── render.yaml                 Render 部署蓝图
└── bank.sqlite                 运行期数据库（仓库根目录，不进发布包）
```

**为什么 `bank.sqlite` 在 `site/` 外面**：云发布只拷 `site/`，
数据库与密钥文件（`.teacher_key` / `.student_code`）落在上级目录，天然不会被打包。

---

## 3. 数据流

### 3.1 题目数据（只读，构建期生成）

```
bank.sqlite (question/topic 表)
        │  build_site.py（构建期，本机）
        ▼
site/data/<UNIT>.js              ← 浏览器直接 <script> 加载
```

**不用 JSON 而用 `.js`**：`file://` 协议下 `fetch()` 会被 CORS 拦掉。
挂全局变量的 `.js` 在 `file://` 与 `http://` 两种方式下都能跑。

### 3.2 作答数据（读写，运行期）

```
学生作答
   │
   ├─① 写 localStorage（立即，永不丢）
   │
   ├─② 入同步队列 → POST /api/attempt → bank.sqlite
   │
   └─③ 服务端重算能力分 → 返回 → 更新 localStorage
```

**队列是幂等的**：每条作答带客户端生成的 `aid`（16–32 位十六进制），
服务端 `INSERT OR IGNORE`，网络重试不会产生重复记录。
失败 3 次后移入 `queue:dead` 死信队列，不阻塞后续作答。

### 3.3 能力分：客户端与服务端各自算

| 位置 | 作用 |
|---|---|
| 前端 `ability()` | 即时反馈，驱动 UI |
| 后端 `ability()` | **权威值**，写入与导出以它为准 |

两端用**同一套常量**（`INIT=1000, K_HI=32, K_LO=12, MIN_T=3, SHOW_AT=15`），
前端只是缓存，服务端才是真相。

---

## 4. 前端

单文件，无框架，无构建。核心模块：

| 模块 | 关键函数 | 职责 |
|---|---|---|
| 会话 | `api()` / `doLogin()` / `enterRole()` | Bearer token、角色切换 |
| 同步队列 | `enqueue()` / `flushQueue()` | 断网重试、幂等 |
| 引擎 | `rating()` / `ability()` / `upd()` / `pick()` | Elo 与选题 |
| 渲染 | `renderQ()` / `renderWeak()` / `renderHeat()` | 六个页面 |
| 公式 | `renderMathIn()` | KaTeX 自动渲染 |
| 图片 | `figBlock()` / `markTallFigs()` / `openLb()` | 原卷图、超长图、灯箱 |
| 轮次 | `saveRound()` / `loadRound()` | 断点续做（2 小时有效） |

### 两套页面

```js
const STUDENT_PAGES = [["prac","练习"],["weak","薄弱点"],["me","我的数据"]];
const TEACHER_PAGES = [["roster","学生一览"],["heat","掌握热力"],["recent","最近作答"]];
```

隔离不只是 UI —— 教师端与学生端的**数据接口和 DOM 入口也是分开的**。

### 两种运行模式

```js
const API = { mode: "local" | "server", ... }
```

- `local`（`file://` 直开）：只用 localStorage，不请求后端
- `server`：走 `/api/*`，队列同步

---

## 5. 数据库

```sql
CREATE TABLE student (
  sid TEXT PRIMARY KEY, name TEXT, cohort TEXT,
  target_units TEXT, goal TEXT, created_at TEXT);

CREATE TABLE attempt (
  aid TEXT PRIMARY KEY,      -- 作答唯一 id（客户端生成，幂等键）
  sid TEXT NOT NULL,         -- → student.sid
  qid TEXT NOT NULL,         -- → question.qid
  ts  TEXT NOT NULL,
  resp_raw      TEXT,        -- 原始作答
  self_report   TEXT,        -- 学生自评
  score         REAL,        -- 0 / 0.5 / 1
  score_max     REAL,        -- 该题分值
  rubric_hits   TEXT,        -- 命中的评分细则（预留）
  grader        TEXT,        -- 'self'
  err_type      TEXT,        -- ⭐ 错因，见 ADAPTIVE-ENGINE.md
  secs          INTEGER,
  is_retry      INTEGER DEFAULT 0);

CREATE INDEX idx_a_sid ON attempt(sid, ts);
```

另外两个表由构建脚本从 `site/data/*.js` 灌入，供服务端能力评估使用：

```sql
question(qid, unit, topic_id, stem_md, ms_md, answer_key, marks, difficulty_p, figs)
topic(topic_id, name_cn, parent_id, level)      -- level: 'L1'=章, 'L2'=知识点
```

> **`err_type` 是未来扩展最自然的接口**：学生错在哪一类，就推哪一条引导脚本。
> 想接入 AI 讲解，正确做法是**离线预生成物料**并按 `err_type` 匹配，
> 而不是在运行时调 API（会破坏"零 LLM"原则）。

---

## 6. 后端

`serve.py`，标准库 `ThreadingHTTPServer` + `SimpleHTTPRequestHandler`。

启动流程：

1. 载入密钥（环境变量 > 密钥文件 > 默认值）
2. 检查 `bank.sqlite` 是否存在
3. 绑定 `127.0.0.1`（云模式绑 `0.0.0.0`）

请求处理顺序（`do_GET` / `do_POST`）：

```
Host 校验 → 静态文件黑名单 → 路由分发 → 鉴权 → 限流 → 输入校验 → 业务
```

### 云模式

```python
CLOUD = bool(os.environ.get("PORT"))
```

平台注入 `PORT` 即切换云模式：

| 行为 | 本机模式 | 云模式 |
|---|---|---|
| 绑定 | `127.0.0.1` | `0.0.0.0` |
| Host 校验 | 仅 `127.0.0.1` / `localhost` / `::1` | 放行（平台反代控制） |
| 同源校验 | 必须来自本机 | 必须等于请求 Host |
| 限流 | 120/min | 600/min（反代后 IP 共享） |

---

## 7. 版权与水印清理

出卷时（`GET /api/quiz`）会对题干与 Mark Scheme 做清洗，
因为原始 OCR 常带进考试局版权声明与第三方试卷站水印：

```python
def clean_paper_text(t): ...
```

处理四类噪声：

1. **开头版权行**（`© UCLES 2022` / `Page 6 of 20`）—— 逐行剥离，遇正文即停
2. **尾部版权段**（`Permission to reproduce` / `Photocopiable`）—— 从特征短语处截断到文末
3. **第三方水印**（`www.OnlineExamHelp.com` 等）—— 正则 + 迭代删除，处理"域名与孤立页码交错"的形态
4. **OCR Latin-1 乱码**（`ĬÍĊ®Ġ´−ÈõÏĪ°ĊÝúµĂ×`）—— 成串丢弃

> ⚠️ 尾部版权大多**与正文同行**（实测 321 道含 `Permission to reproduce` 的题里 320 道同行），
> 所以不能要求"版权特征独占一行" —— 那样规则对 99.7% 的真实情况失效。

---

## 8. 技术选型的取舍

| 决策 | 取 | 舍 | 理由 |
|---|---|---|---|
| 数据格式 | 定长数组 | 对象 | 省体积（12,030 题 × 11 字段） |
| 前端 | 单文件原生 JS | React / Vue | 无构建步骤，十年后还能跑 |
| 后端 | 标准库 `http.server` | Flask / FastAPI | 零依赖，不需要 venv |
| 判分 | 确定性代码 | LLM 判分 | 可复现、可解释、零成本、数据不出本机 |
| 公式 | 本地 KaTeX | CDN | 离线可用 |
| 部署 | 只拷 `site/` | 全目录 | 数据库与密钥不进发布包 |
| 文件放权 | 只监听 127.0.0.1 | 局域网访问 | 学生数据不出本机 |

---

## 9. 从零重建

1. **准备题库数据** —— 按 [DATA-FORMAT.md](DATA-FORMAT.md) 生成 `site/data/<UNIT>.js`
2. **灌数据库** —— 建 `question` / `topic` 表（构建脚本）
3. **前端** —— `index.html` 需要实现：三级导航、KaTeX、原卷图、客观题判分、错因自评、六页 UI
4. **后端** —— `serve.py`：建表、会话鉴权、路由、七层安全（见 [SECURITY.md](SECURITY.md)）、能力评估

验证清单：

- [ ] 教师登录 → 能看到学生一览
- [ ] 学生登录 → 做一题并提交，数据落库
- [ ] `sqlite3 bank.sqlite "SELECT count(*) FROM attempt"` 有记录
- [ ] 访问 `/serve.py`、`/../bank.sqlite` → 被拒绝
- [ ] 断网状态下公式与图片仍正常渲染

---

## 10. 扩展点

| 想加什么 | 怎么做 | 注意 |
|---|---|---|
| 新单元题库 | 加一个 `site/data/<UNIT>.js` + 在 `index.js` 注册 | 见 DATA-FORMAT.md |
| AI 讲解 | 离线预生成 HTML，按 `err_type` 匹配 | 不要运行时调 API |
| 学习路径 | 自建知识点依赖图 | `topics[].pre` 只有 2.6% 非空，不能用 |
| 局域网多人 | 改监听地址 | 会绕过安全设计，见 SECURITY.md |
