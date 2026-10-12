# 方案 B：Koyeb 部署（GitHub 集成，无需本地 Docker）

免费层：**1 个常驻服务、不休眠、512MB / 0.1 vCPU / 2GB SSD / 100GB 月流量**，
地区仅 Frankfurt / Washington。GitHub OAuth 登录，多数用户免信用卡。

本地没有 Docker 也能部署——Koyeb 连你的 GitHub 仓库**云端构建**。

## 架构：三个部件各就各位

这个项目有三块“重资产”，免费层 2GB 磁盘装不下，所以分开安置：

| 资产 | 大小 | 安置 | 更新方式 |
|---|---|---|---|
| 站点代码 + 题库文本（data/*.js） | ~17MB | **打进镜像**（COPY site/） | git push → 重新部署 |
| 题库数据库 bank.sqlite | 56MB | **GitHub Release**，容器启动时下载解压 | 跑 fetch-bank-release.sh → 重新部署 |
| 原卷图片 | ~3GB | **独立 public 仓库 + jsDelivr CDN** | 跑 push-img-repo.sh |
| 学生作答 attempt | 增长中 | **容器内 SQLite**（重部署即丢） | 教师机每日 sync-back.sh 拉回 |

本地权威数据永远在教师机；云端只是服务 + 可牺牲的缓存。

## 第 1 步（一次性）：建图片仓库

```bash
brew install gh && gh auth login
./deploy/koyeb/push-img-repo.sh        # 推 ~3GB，15-40 分钟，可中断重跑
```

推完几分钟后验证 jsDelivr 已索引：

```bash
curl -sI "https://cdn.jsdelivr.net/gh/WEIWEI0614/math-bank-img@main/BMO1_1993_Q1__ms.png" | head -1
# 应返回 HTTP/2 200（刚推完可能 404，等几分钟）
```

> ⚠️ GitHub 账号不是 `WEIWEI0614` 的话，改两处默认值：
> `site/index.html` 的 `IMG_BASE` 和 `deploy/koyeb/Dockerfile` 的 `IMG_CDN_BASE`。

## 第 2 步（一次性）：上传题库 Release

```bash
./deploy/koyeb/fetch-bank-release.sh
```

脚本会做 SQLite 在线备份（WAL 一致性）→ gzip → 建成 tag 为 `bank-latest` 的
GitHub Release。容器启动时自动下载。

> ⚠️ 题库是 12064 道真题，release asset 公开可下载。不愿公开就改用
> Cloudflare R2 私有桶，entrypoint 里带 token 下载。

## 第 3 步：Koyeb 部署（网页操作，5 分钟）

1. https://app.koyeb.com 用 GitHub 登录
2. **Create Service → GitHub → 选 `WEIWEI0614/math-bank`**
3. 构建配置：
   - **Dockerfile 路径：`deploy/koyeb/Dockerfile`**（关键！仓库根没有 Dockerfile）
   - Instance type: **Free**
   - Region: **Frankfurt** 或 **Washington**（免费层只有这两个）
4. Port: **8000**，Protocol: HTTP
5. 环境变量：

   | Key | Value |
   |---|---|
   | `TEACHER_KEY` | 你的教师口令（**别用 shuxue2026**） |
   | `STUDENT_CODE` | 你的班级码（别用 banji2026） |

   `PORT` / `BIND_HOST` / `BANK_URL` / `IMG_CDN_BASE` Dockerfile 里已有默认值，不用填
6. Deploy。首次构建要 clone 942MB 仓库，约 5-10 分钟；成功后分配
   `https://mathbank-<org>.koyeb.app`

> 想用 CLI 也行（本地需先装 Docker）：`brew install koyeb/tap/koyeb`，
> 参数以 `koyeb deploy --help` 为准。

## 第 4 步：每日拉回（必须做）

Koyeb 免费层**没有持久卷，重新部署会清掉容器内所有 attempt 数据**。
教师机每晚拉回，本地才是最终权威：

```bash
# 1. 拿教师 token
curl -s -X POST https://mathbank-<org>.koyeb.app/api/login \
  -H 'Content-Type: application/json' \
  -d '{"role":"teacher","pass":"你的教师口令"}'

# 2. 写进 ~/.mathbank_env（chmod 600）
echo 'TEACHER_TOKEN=上一步拿到的token' > ~/.mathbank_env
echo 'KOYEB_URL=https://mathbank-<org>.koyeb.app' >> ~/.mathbank_env
chmod 600 ~/.mathbank_env

# 3. cron，每天 03:00
crontab -e
# 加一行：
0 3 * * * /Users/davidwei/Desktop/数学题库系统/deploy/koyeb/sync-back.sh >> ~/mathbank-sync/sync.log 2>&1
```

拉回的数据存 `~/mathbank-sync/sync-YYYYMMDD-HHMM.json`，增量拉取（`?since=`），
本地保留 30 天。最坏情况（某次重部署丢了当天数据）从这个归档里能找回。

## 第 5 步：以后的题库更新流程

```bash
# 本地改完 bank.sqlite 后：
./deploy/koyeb/fetch-bank-release.sh     # 换成新 release
# Koyeb 控制台点 Redeploy（或改任何配置触发）—— 容器重启时自动下载新题库
```

不用重新构建镜像，不用推 56MB 进 git。

## 验收清单

- [ ] `https://mathbank-<org>.koyeb.app` 打开正常，KaTeX 公式渲染
- [ ] 学生登录 → 答题 → **刷新页面数据还在**（证明写进了容器 SQLite）
- [ ] 点开一道题的“原卷图”折叠区，**图片能显示**（jsDelivr 生效；CSP 已放行）
- [ ] 教师端 → 专项练习卷 → 卷子里图片也显示
- [ ] 教师机跑 sync-back.sh 能拉到刚才的作答
- [ ] Koyeb 控制台 Redeploy 一次 → 站点恢复 → 当晚 sync-back 的归档完好

## 已知限制（免费层硬约束，非 bug）

1. **重新部署丢 attempt** —— 靠每日拉回兜底；想彻底解决只有换有持久卷的平台
2. **2GB 磁盘** —— 题库 56MB + 年增 attempt（~30MB/年）够用，但别在容器里放别的
3. **地区只有欧美** —— 国内访问一般；API 小包可用，静态资源晚峰偏慢
4. **仓库 942MB 首次构建慢** —— 想根治得清 git 历史（`git filter-repo` 删早期大文件），非阻塞
5. **镜像里 index.html 是构建时的版本** —— 前端改动要 git push + 重新部署才生效

## 什么时候该换掉 Koyeb

- 学生量上来、或不能忍受“重部署丢数据”→ 换 Oracle ARM VM（`../oracle/`，200GB 持久盘，注册门槛已解决的话）
- 师生都在国内要速度 → 备案 + EdgeOne Pages 放静态层，API 留这里
- 教师机常开 → 其实 `../tunnel/`（cloudflared）数据全在本地，更适合这个项目
