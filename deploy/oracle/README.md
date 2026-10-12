# Oracle Cloud 部署 · 操作手册

把练习站从 Render 免费版搬到 **Oracle Cloud Always Free ARM VM**。

为什么搬：Render 免费版会在每次休眠/重启/重新部署时**清空本地 SQLite**（官方文档明示），
且带宽已从 100GB 砍到 5GB/月（2026-04 新规）。Oracle 永久免费层有持久磁盘、不休眠、
10TB/月流量，serve.py 一行逻辑不用改。

全程约一个下午。域名**不需要备案**（备案只在国内节点/CDN 才需要；服务器在境外不用）。

---

## 第 0 步：准备域名（强烈建议，为了 HTTPS）

没有域名也能跑，但登录口令和学生成绩会走**明文 HTTP**，不可接受。
域名 ~55 元/年（Namesilo / Cloudflare / 阿里云国际站均可），
DNS 解析到境外服务器**不需要备案**，买了就能用。

假设域名是 `example.com`，下面统一用 `math.example.com` 作为练习站地址。

## 第 1 步：注册 OCI + 建 ARM 实例

1. 打开 https://www.oracle.com/cloud/free/ 注册（要信用卡验证，只做身份验证不扣费；
   不接受虚拟卡/预付卡，国内双币卡一般能过）
2. **home region 一旦选定不可改**。国内访问优先选 **South Korea: Seoul (ap-seoul-1)**
   或 **Japan: Tokyo (ap-tokyo-1)**。若创建实例时提示 `Out of capacity`，
   换 **US Midwest (Chicago)** / **Canada Southeast (Montreal)** 再试
3. Compute → Instances → Create instance：
   - Image: **Canonical Ubuntu 24.04**（ARM 原生支持，无需额外配置）
   - Shape: **VM.Standard.A1.Flex**，选 **2 OCPU / 8 GB RAM**
     （免费额度是 4 OCPU/24GB；留一半余量防止超额度，8GB 跑这个应用绰绰有余）
   - SSH key：上传你的公钥（`~/.ssh/id_rsa.pub`，没有就 `ssh-keygen` 生成一个）
4. 创建后记下**公网 IP**

## 第 2 步：网络配置（两个地方都要开，这是 OCI 最经典的坑）

OCI 实例即使 OS 内防火墙放行，**云控制台的安全列表不放行照样不通**。

**① 云控制台**：Networking → Virtual Cloud Networks → 你的 VCN → Subnet →
Security List → Add Ingress Rules：

| 源 CIDR | 协议 | 目标端口 | 用途 |
|---|---|---|---|
| 0.0.0.0/0 | TCP | 80 | Caddy HTTP→HTTPS 跳转 + 签证书 |
| 0.0.0.0/0 | TCP | 443 | HTTPS 流量 |
| 你的IP/32 | TCP | 22 | SSH 管理（别对全网开） |

**② OS 内防火墙**：Oracle 的 Ubuntu 镜像自带 iptables 默认 DROP 规则，
登录 VM 后跑本仓库的 `setup.sh` 会自动处理（见第 4 步）。

## 第 3 步：DNS

域名管理处加一条 A 记录：

```
math.example.com   A   <第1步记下的公网IP>
```

## 第 4 步：VM 初始化（在 VM 上执行一次）

```bash
# 把 deploy/oracle 目录传上去（任选一种）
scp -r deploy/oracle ubuntu@<公网IP>:/tmp/
# 或走 git：VM 上 git clone 你的题库仓库

cd /tmp/oracle
sudo bash setup.sh
```

`setup.sh` 做四件事：装 Caddy/sqlite3、开本机防火墙 80/443、
建 `/opt/mathbank` 目录、装 systemd unit。

## 第 5 步：配置站点密钥

```bash
sudo tee /etc/mathbank.env <<'EOF'
TEACHER_KEY=改成你的教师口令
STUDENT_CODE=改成你的班级码
EOF
sudo chmod 600 /etc/mathbank.env
```

> ⚠️ 立即改掉 render.yaml 里那对默认值（`shuxue2026` / `banji2026`）。
> 这两个值曾明文存在于一个公开仓库的部署配置里。

## 第 6 步：配置 Caddy（HTTPS 反代）

```bash
sudo cp /tmp/oracle/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/math.example.com/你的真实域名/' /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy 会自动向 Let's Encrypt 申请证书并续期，无需手工干预。
`/api/*` 和小文件由 Caddy 反向代理到 `127.0.0.1:8770`。

## 第 7 步：上传代码和题库（在你的 Mac 上执行）

```bash
cd 数学题库系统
./deploy/oracle/deploy.sh ubuntu@<公网IP>
```

脚本会做三件事：
1. 用 `sqlite3 .backup` 对 bank.sqlite 做**在线一致性备份**（直接 cp 一个 WAL 模式的库可能丢数据，这是必须的）
2. rsync `site/` + 题库到 `/opt/mathbank/`（自动排除开发机上的几百个临时脚本和 30GB 备份文件）
3. 重启服务并跑健康检查

## 第 8 步：启用每日备份

```bash
sudo cp /tmp/oracle/backup.sh /opt/mathbank/
sudo chmod +x /opt/mathbank/backup.sh
(crontab -l 2>/dev/null; echo "0 3 * * * /opt/mathbank/backup.sh >> /opt/mathbank/backups/backup.log 2>&1") | crontab -
```

每天凌晨 3 点做 SQLite 在线备份，本地保留 7 天。
**强烈建议再配一层异地**（VM 硬盘本身不是备份）：

```bash
# 方案 A：rclone 同步到 OCI Object Storage（免费 10GB，VM 内操作）
sudo apt install rclone
rclone config          # 选 S3 兼容，endpoint 填 OCI Object Storage 的
# 然后把 backup.sh 最后一行 rclone sync 取消注释

# 方案 B：备份 scp 回教师机（需要教师机常开 SSH）
```

## 验收清单

部署完成后逐条对：

- [ ] `https://math.example.com` 能打开，地址栏有小锁
- [ ] 学生登录 → 答一题 → 断网重连后数据还在（证明写进了 VM 上的 SQLite）
- [ ] 教师登录 → 学生一览能看到刚才那条作答
- [ ] `sudo systemctl status mathbank` 显示 active (running)
- [ ] VM 重启一次（`sudo reboot`），数据完好、服务自动起来
- [ ] 8770 端口从外网直接访问**不通**（应该只有 443 可达）

## 常见坑

| 症状 | 原因 |
|---|---|
| 网站完全打不开，SSH 也进不去 | 多半是 OS 内 iptables 没放行（跑 setup.sh），或安全列表没配 |
| SSH 能进、网站打不开 | 只配了一处防火墙。OCI 要**云控制台安全列表 + OS iptables 双开放** |
| Caddy 签证书失败 | DNS 没生效（等 10 分钟）、80 端口没开、或 IP 填错 |
| 建实例报 Out of capacity | ARM 免费资源紧张，换 region 或多试几次（首尔/东京热门） |
| 数据突然没了 | 你还在 Render 上。Render 免费版休眠即清库，这也是搬迁的原因 |
| 端口 8770 外网可达 | 危险。BIND_HOST=127.0.0.1 就是防这个，检查 service 文件 |

## 以后若静态层搬 EdgeOne Pages（备案后）

前端加一个开关即可，serve.py 不用动：

```js
// site/index.html 里
const API_BASE = location.hostname.endsWith('edgeone.app')
  ? 'https://api.math.example.com' : '';
```

EdgeOne 只放静态（不限流量、国内秒开），API 继续留在 Oracle。
届时需在 serve.py 补 CORS 头（静态和 API 不同域），这是后话，现在不用管。
