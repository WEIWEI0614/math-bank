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

## 生产模式（固定域名，5 分钟）

1. 注册 Cloudflare 账号（免费，邮箱即可，**这就是唯一的"注册"**）
2. 把域名 NS 交给 Cloudflare（或只加一个 CNAME 记录用 partial 接入）
3. `cloudflared tunnel login` → 按提示选域名
4. 编辑 `config.yml`，把 `math.example.com` 换成你的域名：
   ```yaml
   tunnel: <TunnelID>
   credentials-file: <登录后生成的.json路径>
   ingress:
     - hostname: math.example.com
       service: http://127.0.0.1:8770
     - service: http_status:404
   ```
5. `cloudflared tunnel route dns <Tunnel名> math.example.com`
6. `cloudflared tunnel run <Tunnel名>` 跑起来；要开机自启就装 plist：
   ```bash
   cp deploy/tunnel/com.mathbank.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.mathbank.plist
   ```

## 验收

- [ ] `https://你的域名/api/me` 返回 `{"role":null}`
- [ ] 教师机重启后服务自动恢复（launchd）
- [ ] 学生答一题，教师机 bank.sqlite 里能看到

## 数据安全

数据本来就在教师机，隧道不改变这一点。但仍建议保留每日备份习惯
（`deploy/oracle/backup.sh` 里的 sqlite .backup 逻辑在任何机器上都适用，
把路径改成本地即可）。
