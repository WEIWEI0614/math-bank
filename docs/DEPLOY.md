# 部署指南

> 三种部署方式：本机（推荐）、局域网、云（Render）。

---

## 1. 本机部署（推荐）

面向**一位老师 + 自己的学生**的典型场景：服务跑在老师电脑上，学生在本机或远程桌面使用。

```bash
git clone https://github.com/WEIWEI0614/math-bank.git
cd math-bank

python3 site/serve.py                 # → http://127.0.0.1:8770
python3 site/serve.py --port 9000     # 换端口
```

要求：**Python 3.11+**，无第三方依赖（后端只用标准库）。

启动后控制台打印：

```
练习站: http://127.0.0.1:8770/   （仅本机可访问，数据写入 /path/to/bank.sqlite）
教师口令: shuxue2026   学生班级码: banji2026
Ctrl+C 停止
```

### 改默认口令（**生产环境务必做**）

```bash
# 方式 A：环境变量（优先级最高）
TEACHER_KEY="改成你的口令" STUDENT_CODE="改成你的班级码" python3 site/serve.py

# 方式 B：密钥文件
echo "改成你的口令"   > .teacher_key
echo "改成你的班级码" > .student_code
chmod 600 .teacher_key .student_code
```

优先级：**环境变量 > 密钥文件 > 内置默认值**。密钥文件已被 git 忽略。

### 开机自启（macOS）

`~/Library/LaunchAgents/com.mathbank.serve.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.mathbank.serve</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/absolute/path/to/math-bank/site/serve.py</string>
  </array>
  <key>WorkingDirectory</key><string>/absolute/path/to/math-bank</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TEACHER_KEY</key><string>你的口令</string>
    <key>STUDENT_CODE</key><string>你的班级码</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.mathbank.serve.plist
```

---

## 2. 无后端部署（静态托管）

不需要 Python，不需要数据库。适合**单机自用 / 演示**。

```bash
open site/index.html
```

或把 `site/` 丢到任何静态托管（GitHub Pages / Nginx / OSS）。

**限制**：

- 数据存浏览器 `localStorage`，**换设备即丢失**
- **教师端不可用**（没有服务端就没有全班数据）
- 无法导出全班数据

---

## 3. 云部署（Render）

仓库已自带 `render.yaml` 与 `Procfile`。

```yaml
services:
  - type: web
    name: math-bank
    runtime: python
    plan: free
    rootDir: .
    buildCommand: pip install -r requirements.txt
    startCommand: python site/serve.py --port ${PORT}
    healthCheckPath: /
    envVars:
      - key: TEACHER_KEY
        value: shuxue2026
      - key: STUDENT_CODE
        value: banji2026
```

部署步骤：

1. 在 Render 新建 **Blueprint**，指向本仓库
2. 修改 `TEACHER_KEY` / `STUDENT_CODE` 环境变量
3. 部署

### 云模式的差异

平台注入 `PORT` 环境变量即自动切云模式（`CLOUD = bool(os.environ.get("PORT"))`）：

| 行为 | 本机 | 云 |
|---|---|---|
| 绑定地址 | `127.0.0.1` | `0.0.0.0` |
| Host 校验 | 仅本机 | 放行（平台反代控制） |
| 同源校验 | 必须来自本机 | 必须等于请求 Host |
| 限流 | 120/min | 600/min |

### ⚠️ 云部署的三个坑

**1. 免费实例会休眠，数据会丢**

Render Free 计划的磁盘是**临时的**，实例休眠后 `bank.sqlite` 会被重置。
学生作答记录会在重启后消失。

> 长期使用请改用付费计划并挂载持久磁盘，或者干脆用**本机部署**。

**2. 数据仍在服务端，不是"云端同步"**

云模式下作答仍然写在服务端的 `bank.sqlite`。
"数据不出本机"这条原则在云模式下**不成立** —— 你需要自行评估是否接受。

**3. `requirements.txt` 里的包运行时并不需要**

`PyMuPDF` / `Pillow` / `numpy` 只给**构建脚本**用（PDF 解析与图片裁剪）。
运行时零依赖，如果在意构建时间可以精简。

---

## 4. 发布包内容

云发布只拷 `site/`：

```
site/
├── index.html
├── serve.py
├── vendor/katex/
└── data/*.js
```

**不会**被打进包：

- `bank.sqlite`（数据库，在上级目录）
- `.teacher_key` / `.student_code`（密钥，在上级目录）
- `docs/`

---

## 5. 数据备份

`bank.sqlite` 就是全部原始数据，备份它即可。

```bash
# 备份
cp bank.sqlite bank.sqlite.bak.$(date +%Y%m%d)

# 或者用教师端"导出全部数据"下载 JSON（人类可读，适合归档）
```

> ⚠️ SQLite 的 `-wal` / `-shm` 是伴随文件，备份时确保服务已停止，或用 `VACUUM INTO`。

```bash
sqlite3 bank.sqlite "VACUUM INTO 'bank.backup.sqlite'"
```

**原卷图片**（`site/data/img/`，2.9 GB）是独立版本库，备份策略另见 README 的版权说明。

---

## 6. 验证清单

部署后逐项确认：

- [ ] 教师登录 → 能看到学生一览
- [ ] 学生登录 → 做一题并提交，`sqlite3 bank.sqlite "SELECT count(*) FROM attempt"` 有记录
- [ ] 访问 `/serve.py` → 被拒绝（403）
- [ ] 访问 `/../bank.sqlite` → 被拒绝
- [ ] 断网状态下公式与图片仍正常渲染（KaTeX 已本地化）
- [ ] 默认口令已改
- [ ] 本机模式下从局域网另一台设备访问 → **应当失败**（安全设计）
