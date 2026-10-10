# 安全设计

> 七层防护、威胁模型、以及"为什么这么设计"。

---

## 1. 威胁模型

**保护什么**：学生姓名 + 作答记录 + 能力评估（属于个人教育数据）。

**防谁**：

| 威胁 | 场景 |
|---|---|
| 同网段的其他人 | 学生数据被局域网内其他设备读到 |
| 恶意网页 | 学生浏览器被诱导访问本机服务（DNS-rebinding） |
| 跨站脚本 | 恶意站点伪造作答、偷数据 |
| 误操作 | 源码 / 数据库被当作静态文件下载 |
| 指纹识别 | 通过 `Server` 头探测后端版本 |

**不防**（明确超出范围）：

- 已获得本机登录权限的攻击者（能直接读 `bank.sqlite`）
- 云模式下的平台侧风险（见 [DEPLOY.md](DEPLOY.md)）
- 学生自己篡改前端（能力分由服务端权威重算，改前端没用）

---

## 2. 七层防护

| # | 措施 | 实现 | 防什么 |
|---:|---|---|---|
| 1 | **Host 白名单** | 本机模式只接受 `127.0.0.1` / `localhost` / `::1` | DNS-rebinding |
| 2 | **静态文件黑名单** | 拒绝 `.py` / `.pyc` / `.sqlite` / `.sqlite3` / `.db` / `.env` / `.bak`，以及任何含 `..` 的路径 | 源码与数据库外泄 |
| 3 | **安全响应头** | `nosniff` / `X-Frame-Options` / `Referrer-Policy` / CSP | XSS · 点击劫持 |
| 4 | **同源写入校验** | POST 带 `Origin`/`Referer` 时必须来自本机（云模式：等于请求 Host） | 跨站伪造作答 |
| 5 | **限流** | 每 IP 120 次/分钟（云模式 600），内存令牌窗 | 滥用 |
| 6 | **输入校验** | body ≤ 64 KB；`qid`/`topic` 正则白名单；`score` 枚举；`secs`/`marks`/`n` 范围钳制 | 注入 · 越界 |
| 7 | **版本隐匿** | `Server: mathbank`（不暴露 Python 版本） | 指纹识别 |

### 细节

**第 1 层（Host 白名单）** 防的是 DNS-rebinding：攻击者让学生访问 `evil.com`，
该域名先解析到真实 IP 通过校验，随后重绑定到 `127.0.0.1` 打到本机服务。
校验 `Host` 头可拦住。

**第 2 层** 是纵深防御 —— `http.server` 本身已归一化路径，这一层是为了防住归一化失效的情况。

**第 6 层** 全部白名单化，不做黑名单过滤：

```python
QID_RE   = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
TOPIC_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
ERR_SET  = {"concept","procedure","setup","algebra","calc","time","misread"}
```

SQL 全部走参数化查询（`?` 占位符），无字符串拼接。

---

## 3. 鉴权与角色隔离

### 会话

| 项 | 值 |
|---|---|
| token 生成 | `secrets.token_urlsafe(24)` |
| TTL | 7 天 |
| 传递 | `Authorization: Bearer <token>`；GET 也接受 `?token=` |
| 存储 | 服务端内存（重启失效）；客户端 `localStorage` |

### 角色隔离是服务端强制的

| 接口 | 学生 | 教师 |
|---|:---:|:---:|
| `POST /api/attempt` | ✅ | ❌ `403 教师账号不能作答` |
| `GET /api/students` | ❌ 401 | ✅ |
| `GET /api/export` | ✅ **仅自己** | ✅ 全员 |
| `GET /api/quiz` | ❌ 401 | ✅ |
| `GET /api/sync` | ❌ 401 | ✅ |

**学生导出越权防护**（曾经踩过的坑）：

```python
# 学生永远只能导出自己：即便显式传了 name=别人 也忽略，
# 直接以 token 里的身份为准
if s["role"] == "student":
    req_name = s["name"]
```

> 早前的 bug：身份判定与下游读取**复用了同一个变量**，
> 导致学生不带 `name` 的请求被重置成 `""`，落进"教师全员导出"分支。
> 现在用独立的 `req_name` / `export_all` 两个变量，不可复用。

### 口令来源优先级

```
环境变量 TEACHER_KEY / STUDENT_CODE
        ↓
密钥文件 .teacher_key / .student_code（0600，已被 git 忽略）
        ↓
内置默认值 shuxue2026 / banji2026
```

比对用 `secrets.compare_digest()`（恒定时间，防时序侧信道）。

---

## 4. 内容安全策略（CSP）

```
default-src 'self';
script-src  'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net;
style-src   'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net;
img-src     'self' data:;
font-src    'self' data: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net;
connect-src 'self';
object-src  'none';
base-uri    'self';
frame-ancestors 'self'
```

**两点需要注意**：

1. `connect-src 'self'` —— **页面内不能直连任何外部 API**。
   这正好与"零 LLM 调用"原则一致：运行时本来就不该有外部请求。
2. `img-src 'self' data:` —— 图片只能来自本站或 data URI。
   内联的 KaTeX（data URI 字体）是允许的。

> 接 AI 物料时注意：`img-src` 不放行外链；需要展示外部图片时用 data URI 或本地化。

---

## 5. 数据处理原则

| 原则 | 落实 |
|---|---|
| **数据不出本机** | 本机模式只绑 `127.0.0.1`；零外部请求 |
| **零 LLM 调用** | 运行时不调任何 AI 接口，判分全是确定性代码 |
| **不采集多余信息** | 学生只需一个姓名，不要手机号 / 邮箱 |
| **密钥不进版本库** | `.teacher_key` / `.student_code` 已被 git 忽略 |

---

## 6. 已知取舍

| 取舍 | 说明 |
|---|---|
| token 存内存 | 重启服务即全部登出。对单机应用可接受，省去了持久化会话的复杂度 |
| 无 HTTPS | 本机模式（`127.0.0.1`）不需要；云模式由平台反代提供 |
| 无审计日志 | 单机教学场景，暂不需要 |
| 限流按 IP | 云模式反代后 IP 共享，故放宽到 600/min |

---

## 7. 报告安全问题

如果发现问题，请**不要**开公开 issue。直接联系仓库所有者。

复现时请附上：运行模式（本机 / 云）、Python 版本、请求与响应原文。
