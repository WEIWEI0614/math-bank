# HTTP API

> `site/serve.py` 提供的 7 个接口。全部为 JSON（`GET /api/quiz` 例外，返回 HTML）。

**Base URL**：`http://127.0.0.1:8770`（本机模式）

---

## 鉴权

除 `POST /api/login` 外，所有接口都需要 Bearer token。

```http
Authorization: Bearer <token>
```

GET 接口也接受 `?token=xxx`（方便导出链接场景）。

| 参数 | 值 |
|---|---|
| token 生成 | `secrets.token_urlsafe(24)` |
| TTL | 7 天 |
| 存储 | 服务端内存（重启即失效）；客户端存 `localStorage` |

**角色**：`teacher` / `student`。权限由**服务端强制**，不依赖前端。

---

## 接口一览

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/login` | — | 登录，换 token |
| POST | `/api/logout` | token | 注销 |
| GET | `/api/me` | token | 当前身份（恢复登录态） |
| POST | `/api/attempt` | **学生** | 记录作答 |
| GET | `/api/students` | **教师** | 学生清单与统计 |
| GET | `/api/export` | token | 导出（学生仅自己） |
| GET | `/api/quiz` | **教师** | 生成专项练习 HTML |
| GET | `/api/sync` | **教师** | 增量作答（镜像用） |

---

## POST /api/login

```jsonc
// 教师
{"role":"teacher","pass":"<TEACHER_KEY>"}

// 学生
{"role":"student","name":"张三","pass":"<STUDENT_CODE>"}
```

**200**

```json
{"token":"eyJ...","role":"student","name":"张三"}
```

**错误**

| 码 | `err` | 场景 |
|---|---|---|
| 400 | `role 必须是 teacher/student` | role 非法 |
| 400 | `缺少姓名` | 学生没填名字 |
| 401 | `口令不对` | 教师口令错误 |
| 401 | `班级码不对` | 班级码错误 |

> 学生首次登录**自动建号**（`INSERT INTO student`），无需预先导入花名册。

---

## POST /api/logout

无请求体。注销当前 token。

```json
{"ok":true}
```

---

## GET /api/me

```jsonc
{"role":"teacher","name":"教师"}   // 已登录
{"role":null}                      // 未登录或已过期
```

---

## POST /api/attempt

记录一次作答。**需要学生 token**；身份以 token 为准，不信 body 里的 name。

```json
{
  "qid":   "CIE_CIE9709P1_2008s_1_Q1",
  "topic": "TP-0252",
  "score": 1,          // 必须是 0 / 0.5 / 1
  "secs":  87,
  "why":   "漏讨论了 x=0",
  "err":   "concept",  // 见下方错因表
  "marks": 3,
  "aid":   "a3f1c2e4b5d60718"   // 幂等键，16-32 位十六进制
}
```

| 字段 | 校验 |
|---|---|
| `qid` | `^[A-Za-z0-9_\-]{1,64}$` |
| `topic` | `^[A-Za-z0-9_\-]{1,64}$`（不合规则置空） |
| `score` | **必须**是 `0` / `0.5` / `1` |
| `secs` | 钳到 `0..7200` |
| `marks` | 钳到 `0..500` |
| `why` | 截断到 500 字符 |
| `err` | 必须在错因白名单内，否则置 `null` |
| `aid` | `[0-9a-f]{16,32}`；不合规则服务端生成 |

**错因白名单**

```
concept   concept     概念不清
procedure procedure   步骤方法错
setup     setup       建模列式错
algebra   algebra     代数运算失误
calc      calc        计算抄写失误
time      time        没做完
misread   misread     看错题
```

**200**

```json
{
  "ok": true,
  "attempts": 42,
  "topic": {"topic":"TP-0252","name":"三角函数","chapter":"三角学",
            "elo":1043,"n":7,"reliable":false}
}
```

**幂等**：`aid` 作为主键，`INSERT OR IGNORE`。网络重试不会产生重复记录。

**错误**：`401 未登录` / `403 教师账号不能作答` / `400 qid 非法` / `400 score 必须是 0/0.5/1`

---

## GET /api/students

**需要教师 token**。

```json
[
  {"name":"张三","n":42,"acc":71,"created":"2026-09-01 10:00:00",
   "last":"2026-10-09 21:33:12",
   "weak":[{"name":"隐函数求导","elo":812,"n":6}, ...]}   // 最弱 3 项
]
```

| 字段 | 说明 |
|---|---|
| `n` | 累计作答题数 |
| `acc` | 平均正确率（百分比整数） |
| `last` | 最近作答时间（可为 `null`） |
| `weak` | 按能力分升序的前 3 个知识点 |

排序：`最近活跃 DESC, 姓名`。

**错误**：`401 需要教师登录`

---

## GET /api/export

需要 token。**学生永远只能导出自己**（即便显式传 `name=别人` 也会被忽略，以 token 身份为准）。

| 参数 | 说明 |
|---|---|
| `name` | 教师可选，指定学生；省略 = 全员 |
| `light=1` | 只回能力分（热力图用，省流量） |

**学生 / 指定单人**

```json
{
  "name":"张三","attempts":42,
  "ability":[{"topic":"TP-0252","name":"三角函数","chapter":"三角学",
              "elo":1043,"n":7,"reliable":false}],
  "log":[{"aid":"...","qid":"...","ts":"...","score":1,"secs":87,
          "err":"concept","why":"...","topic":"TP-0252"}]
}
```

**教师全员**（`{"all": {...}}`）

```json
{"all":{"张三":{"attempts":42,"ability":[...],"log":[...]}, "李四":{...}}}
```

**错误**：`401 需要登录` / `404 学生不存在`

---

## GET /api/quiz

**需要教师 token**。按学生薄弱知识点生成专项练习，**返回 HTML**（不是 JSON）。

| 参数 | 默认 | 说明 |
|---|---|---|
| `name` | — | **必填**，学生姓名 |
| `unit` | 空 | 可选，按单元筛选 |
| `n` | 10 | 题数，钳到 `1..50` |

生成的 HTML 包含：

- 卷头：`姓名 · 薄弱点专项练习（N 题）` + 生成时间
- **实际覆盖的知识点与各题数**（不会静默降级成单单元随机卷）
- 若指定了 `unit`，会提示"薄弱知识点命中 N 个"
- 每题：原卷题图 + 题干（KaTeX 渲染）+ 参考答案；无简答时附**判分细则**（Mark Scheme 原文，已裁版权与水印）

**错误**：`401 需要教师登录` / `400 缺少 name` / `404 学生不存在，请从花名册选择`

> ⚠️ 姓名是从花名册下拉选择的，**拼错会 404 且不会建号**（只读查找）。

---

## GET /api/sync

**需要教师 token**。镜像守护用的增量拉取。

| 参数 | 说明 |
|---|---|
| `since` | ISO8601 时间戳；为空 = 全量 |

```json
{
  "since":"2026-10-09 00:00:00",
  "students":["张三","李四"],
  "attempts":[{"aid":"...","name":"张三","qid":"...","ts":"...",
               "score":1,"secs":87,"err":"concept","why":"...","self":"..."}]
}
```

**错误**：`401 需要教师登录`

---

## 通用错误码

| 码 | `err` | 触发 |
|---|---|---|
| 400 | `bad json: ...` | 请求体不是合法 JSON |
| 403 | `forbidden host` | Host 不在白名单（本机模式） |
| 403 | `forbidden` | 命中静态文件黑名单（`.py` / `.sqlite` / `.env` / 含 `..`） |
| 403 | `cross-origin denied` | POST 的 Origin/Referer 非同源 |
| 404 | `not found` | 未知 POST 路径 |
| 413 | `bad content-length` | 请求体 > 64 KB |
| 429 | `too many requests` | 超过限流 |

---

## 请求限制

| 项 | 本机模式 | 云模式 |
|---|---:|---:|
| 请求体上限 | 64 KB | 64 KB |
| 限流 | 120 次/分钟/IP | 600 次/分钟/IP |

安全设计详见 [SECURITY.md](SECURITY.md)。
