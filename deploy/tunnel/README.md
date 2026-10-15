# 方案 A：Cloudflare Tunnel（零注册，5 分钟上线）

教师机跑 serve.py + cloudflared 隧道，直接获得公网 HTTPS 地址。
**无需注册任何云平台、无需信用卡、无需备案、不限流量。**

## 代价（先说清楚）

| 项 | 说明 |
|---|---|
| 教师机必须常开 | 服务就在你机器上，关机 = 站点下线 |
| 流量经过 Cloudflare 边缘节点转发 | TLS 端到端加密，CF 不存储内容；但严格说与「不上传任何云端」的字面承诺有差异，**付费学生的服务建议在隐私说明里提一句** |
| 国内速度中等 | API 小包（几百字节）完全可用；静态资源晚高峰一般——正好配合日后的 data 懒加载改造 |

数据库仍然在教师机本地，"数据本地留存"的设计哲学不变。

## 快速开始（测试模式，1 分钟）

```bash
brew install cloudflared          # 或 https://github.com/cloudflare/cloudflared/releases
./deploy/tunnel/start.sh
```

脚本会起 serve.py 并打印一个 `https://xxx-yyy-zzz.trycloudflare.com` 地址，
发给学生就能用。**Quick Tunnel 的域名每次重启都会变**，只适合测试。

## 生产模式（固定域名，一条龙 5 分钟）

需要两样东西。**域名可以免费**（见下方路 B），CF 账号免费计划即可：

1. **Cloudflare 账号**（免费计划，无需信用卡）：
   https://dash.cloudflare.com/sign-up
2. **域名**，两条路任选：

### 路 A：花钱买（$9.77/年，最省心）

CF 面板 → Registrar → Register Domain → `.com` 约 **$9.77/年**（成本价，
比 Namesilo/GoDaddy 便宜，且 DNS、隧道、证书全在一个面板）。
域名自动托管在 CF，脚本全自动配好，零手动。

### 路 B：免费域名（0 元，手动加一条 CNAME）

Named Tunnel 只要求「能加 CNAME 到 `<隧道ID>.cfargotunnel.com`」，
**不要求域名在 Cloudflare**。免费选项按靠谱程度：

| 服务 | 地址形态 | 拿法 | CNAME | 评价 |
|---|---|---|---|---|
| **afraid.org FreeDNS** | `xxx.干净域段` | 邮箱注册即得 | ✅ 面板直接加 | **首选**，老牌记录全，避开被滥用的域段 |
| **is-a.dev** | `xxx.is-a.dev` | GitHub 提 PR 加 CNAME 文件，审核数小时 | ✅（PR 即 CNAME） | 开发者圈正规，有 GitHub 就合适 |
| **eu.org** | `xxx.eu.org` | 官网申请，人工审核几天~几周 | ✅ | 经典但太慢，应急不选 |
| DuckDNS | `xxx.duckdns.org` | 即时 | ❌ **只有动态 A 记录** | **配不了隧道**，常被误荐 |

脚本对免费域名自动降级：`route dns` 失败时打印精确的手动 CNAME 步骤
（含你的隧道 ID），照着加完回车，后面全自动。

然后跑一条龙脚本：

```bash
./deploy/tunnel/named-setup.sh
# 交互问一句完整域名（如 math.example.com），然后自动完成：
#   浏览器授权 → 建隧道 → 写 config.yml → 配 DNS CNAME →
#   装 launchd（开机自启+崩溃自拉）→ 验证 + 打印固定地址
```

配好后：

- 地址永久不变：`https://math.你的域名.com`
- 教师机重启自动恢复，不用再手动跑任何东西
- 停服：`launchctl unload ~/Library/LaunchAgents/com.mathbank.tunnel.plist`
- 日志：`deploy/tunnel/tunnel.log`

### 手动模式（脚本失败时的手工步骤）

## 验收

- [ ] `https://你的域名/api/me` 返回 `{"role":null}`
- [ ] 教师机重启后服务自动恢复（launchd）
- [ ] 学生答一题，教师机 bank.sqlite 里能看到

## 数据安全

数据本来就在教师机，隧道不改变这一点。但仍建议保留每日备份习惯
（`deploy/oracle/backup.sh` 里的 sqlite .backup 逻辑在任何机器上都适用，
把路径改成本地即可）。
