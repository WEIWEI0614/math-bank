# Koyeb 部署镜像（GitHub 集成云端构建）。
#
# 设计约束（免费层：512MB RAM / 2GB SSD / 无持久卷）：
#   1. bank.sqlite 56MB 不进 git（仓库已 942MB，且 git 不适合放大文件）——
#      改为启动时从 GitHub Release 下载，题库更新 = 换 release，不用重新构建镜像
#   2. 原卷图 5.5GB 同样不进镜像，云模式走 jsDelivr（见 index.html 的 IMG_BASE）
#   3. attempt 数据写在容器内，重部署即丢——教师机每日 /api/sync 拉回兜底
FROM python:3.12-slim

WORKDIR /app

# 站点本体：index.html + serve.py + vendor/katex + data/*.js（题库数据 ~17MB）
COPY site/ /app/site/
COPY deploy/koyeb/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# 云模式：PORT 存在即触发 serve.py 的云逻辑（同源校验 + 600/min 限流）
ENV PORT=8000
ENV BIND_HOST=0.0.0.0

# 题库下载地址（GitHub Release asset，tag: bank-latest，.gz 压缩版 ~15MB）
# 首次部署前需先跑 deploy/koyeb/fetch-bank-release.sh 上传题库
ENV BANK_URL=https://github.com/WEIWEI0614/math-bank/releases/download/bank-latest/bank.sqlite.gz

# 云模式图片 CDN：quiz 接口生成的练习卷里原卷图也走 jsDelivr
# （jsDelivr 国内有节点；本地部署时留空即用 data/ 相对路径）
ENV IMG_CDN_BASE=https://cdn.jsdelivr.net/gh/WEIWEI0614/math-bank-img@main/

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
