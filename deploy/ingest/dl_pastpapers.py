#!/usr/bin/env python3
"""papacambridge 批量下载器：多重试 + 大小校验 + 断点跳过。

papacambridge 的直链模式（已实测）：
  https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/<官方文件名>.pdf
官方文件名：9709_w25_qp_51.pdf / 9709_w25_ms_51.pdf / 9231_w25_qp_11.pdf 等。
该站对沙箱代理时通时断（502/000），每个文件多重试即可。
"""
import sys, os, time, subprocess, json
from pathlib import Path

BASE = "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"
MIN_BYTES = 20000          # PDF 小于 20KB 视为错误页/占位
TRIES = 6
GAP = 2.5

def dl(url: str, dest: Path) -> str:
    """下载单个文件。返回 done/skip/fail/missing。
    missing = 服务端 404（确定不存在，不重试）；fail = 网络类失败（已重试）。"""
    if dest.exists() and dest.stat().st_size >= MIN_BYTES:
        return "skip"
    tmp = Path("/tmp/.dl_current_part")  # 单一固定临时文件：反复覆盖，不删除不累积
    for i in range(1, TRIES + 1):
        code = "000"
        try:
            r = subprocess.run(
                ["curl", "-sSL", "--max-time", "90", "-w", "%{http_code}",
                 "-o", str(tmp), url],
                capture_output=True, text=True, timeout=100)
            code = (r.stdout or "").strip()[-3:]
        except Exception:
            code = "000"
        if code == "404":
            break                      # 确定不存在，别浪费时间重试
        if tmp.exists() and tmp.stat().st_size >= MIN_BYTES:
            with open(tmp, "rb") as f:
                head = f.read(5)
            if head.startswith(b"%PDF"):
                tmp.rename(dest)
                return "done"
        if code in ("200", "404"):
            break                      # 200 但内容不合格（错误页），不重试
        time.sleep(GAP)
    return "missing" if code == "404" else "fail"

def main():
    # 用法: dl_pastpapers.py <清单json> <目标根目录>
    # 清单 json: {"9709_w25_qp_51.pdf": {"url": "https://...", "dir": "CIE A-Level 数学/.../2025"}, ...}
    # 值也可以是纯字符串（dir），此时 URL 按 papacambridge 默认模式拼。
    manifest_path, root = sys.argv[1], Path(sys.argv[2])
    items = json.load(open(manifest_path))
    ok = skip = miss = fail = 0
    fails = []
    for fname, v in items.items():
        if isinstance(v, dict):
            url, reldir = v["url"], v["dir"]
        else:
            url, reldir = f"{BASE}/{fname}", v
        d = root / reldir
        d.mkdir(parents=True, exist_ok=True)
        st = dl(url, d / fname)
        if st == "done":
            ok += 1
            print(f"  ✓ {fname}  ({(d/fname).stat().st_size//1024}KB)", flush=True)
        elif st == "skip":
            skip += 1
        elif st == "missing":
            miss += 1
        else:
            fail += 1
            fails.append(fname)
            print(f"  ✗ {fname}  {TRIES} 次重试均失败", flush=True)
    print(f"\n完成: 下载 {ok} / 已存在 {skip} / 不存在 {miss} / 网络失败 {fail}", flush=True)
    if fails:
        print("失败清单（可重跑）:", ", ".join(fails[:30]), flush=True)

if __name__ == "__main__":
    main()
