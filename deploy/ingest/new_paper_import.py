#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新下载 PDF → MinerU 解析 → 切题 → 建 question 行（新题，不是更新旧题）。

与 _mineru_ingest.py 的分工：
  ingest  = 更新**已存在**题的 stem_mineru 列（铁律不碰 stem_md）
  本脚本  = **创建新题**（库里没有的场次/单元），幂等 INSERT OR IGNORE

支持三种来源的文件名：
  9709_s25_qp_51.pdf   → CIE9709S1, 2025, summer, variant 51
  9231_w25_qp_31.pdf   → CIE9231FM,  2025, winter, variant 31
  25_10_QP_P1.pdf      → EDXIALP1,   2025, winter(10月), paper 01
  （MS / gt / 水印版小程序文件自动跳过）

用法：
  python new_paper_import.py <目录或PDF>            # dry-run，只报告
  python new_paper_import.py <目录> --apply        # 写库
  python new_paper_import.py <目录> --tier pipeline  # 换解析档（默认 basic）
"""
import os, re, sys, json, sqlite3, subprocess, time
from pathlib import Path
from collections import Counter

ROOT = Path("/Users/davidwei/Desktop/数学题库系统")
DB = ROOT / "bank.sqlite"
OUTDIR = ROOT / "output" / "new_papers_md"
MINERU = "/Users/davidwei/.workbuddy/binaries/python/envs/default/bin/mineru"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "site"))   # serve.py 在 site/ 下
from _mineru_slice import build, candidates, drop_page_numbers, slice_paper
import serve  # 复用 clean_paper_text（版权/水印/乱码清洗）

# ---------- 文件名 → 单元映射 ----------
# CIE 9709：组件号首位 = 单元（1x=P1 2x=P2 3x=P3 4x=M1 5x=S1 6x=S2）
C9709 = {"1": "CIE9709P1", "2": "CIE9709P2", "3": "CIE9709P3",
         "4": "CIE9709M1", "5": "CIE9709S1", "6": "CIE9709S2"}
# CIE 9231：按库内 paper 字段实际分布（FP1=1x FP2=2x FM=3x FS=4x）
C9231 = {"1": "CIE9231FP1", "2": "CIE9231FP2", "3": "CIE9231FM", "4": "CIE9231FS"}
# 爱得思 edemat 文件名 → 单元（FS1/FM1/FS2/FM2 库内无对应单元，跳过）
EDX = {"P1": "EDXIALP1", "P2": "EDXIALP2", "P3": "EDXIALP3", "P4": "EDXIALP4",
       "S1": "EDXIALS1", "S2": "EDXIALS2", "S3": "EDXIALS3",
       "M1": "EDXIALM1", "M2": "EDXIALM2", "M3": "EDXIALM3", "D1": "EDXIALD1",
       "FP1": "EDXIALFP1", "FP2": "EDXIALFP2"}
EDX_SESSION = {"10": "w", "01": "m", "06": "s"}   # 10月=winter 1月=march 6月=summer

RX_CIE = re.compile(r"^(9709|9231)_([swm])(\d{2})_(qp|ms)_(\d{2})\.pdf$")
RX_EDX = re.compile(r"^(\d{2})_(\d{2})_(QP|MS)_([A-Z]+\d?)\.pdf$")


def parse_name(fn: str):
    """→ dict(unit, year, session, paper, board, kind) 或 None（跳过）"""
    m = RX_CIE.match(fn)
    if m:
        syl, s, yy, kind, comp = m.groups()
        tbl = C9709 if syl == "9709" else C9231
        unit = tbl.get(comp[0])
        if not unit:
            return None
        return {"unit": unit, "year": 2000 + int(yy), "session": s,
                "paper": comp, "board": "CIE", "kind": kind}
    m = RX_EDX.match(fn)
    if m:
        yy, mm, kind, paper = m.groups()
        unit = EDX.get(paper)
        if not unit:
            return {"skip": f"edemat {paper} 库内无对应单元"}
        sess = EDX_SESSION.get(mm)
        if not sess:
            return {"skip": f"未知月份 {mm}"}
        return {"unit": unit, "year": 2000 + int(yy), "session": sess,
                "paper": "01", "board": "EDX", "kind": kind.lower()}
    return {"skip": "文件名不匹配（水印版/gt/杂项）"}


# ---------- marks 提取 ----------
RX_TOTAL_CIE = re.compile(r"\(Total for Question\s+\d+\s+is\s+(\d+)\s+marks?\)", re.I)
RX_TOTAL_EDX = re.compile(r"\(Total for Question\s+\d+\s+is\s+(\d+)\s+marks\)", re.I)
RX_BRACKET = re.compile(r"\[(\d{1,2})\]")
RX_PAREN = re.compile(r"\((\d{1,2})\)")


def extract_marks(seg: str, board: str) -> float:
    for rx in (RX_TOTAL_CIE, RX_TOTAL_EDX):
        m = rx.search(seg)
        if m:
            return float(m.group(1))
    # 兜底：括号数字求和（part 分值），取合理区间
    nums = [int(x) for x in (RX_BRACKET if board == "CIE" else RX_PAREN).findall(seg)]
    nums = [n for n in nums if 1 <= n <= 20]
    if nums:
        return float(sum(nums))
    return 0.0


# ---------- 题号序列（新题没有 expected，从候选提取） ----------
RX_TOTAL_Q = re.compile(r"\(Total for Question\s+(\d+)\s+is\s+\d+\s+marks?\)", re.I)


def edx_total_anchors(lines, page_of, cands):
    """爱得思专用：用 "(Total for Question N is M marks)" 合成缺失题号的锚点。

    爱得思版式：题号常是裸 `N.` 行（已由 F 形态覆盖），但个别题的题号行会被
    OCR 整行丢掉（实测 24_10_QP_P1 的 Q7）。而 Total 行极稳（全卷每道题都有），
    第 N 题的起点 ≈ 第 N-1 题 Total 行的下一行。
    返回补全后的 cands（已按行号排序）。
    """
    ends = {}
    for i, l in enumerate(lines):
        m = RX_TOTAL_Q.search(l)
        if m:
            n = int(m.group(1))
            if n not in ends:
                ends[n] = i
    if not ends:
        return cands
    maxq = max(ends)
    have = {q for (_, _, q, _) in cands}
    added = 0
    for n in range(2, maxq + 1):
        if n not in have and (n - 1) in ends:
            li = ends[n - 1] + 1
            if li < len(lines):
                cands.append((li, page_of.get(li, 1), n, "F"))
                added += 1
    if added:
        cands.sort(key=lambda c: c[0])
        print(f"    [EDX锚点] Total 行合成 {added} 个缺失题号: "
              f"{sorted(set(range(2, maxq + 1)) - have)}", flush=True)
    return cands


def cie_promote_anchors(cands):
    """CIE 专用：独立数字行（kind A）里分离页码与题号。

    CIE 版式实证（9709_m25_qp_12）：每页有纸码行 `\\* 000080000000N \\*`（N=页号），
    页码以独立数字行紧跟着出现；**题号也印成独立数字行**（在题干旁白，OCR 丢失数字
    与正文的粘连时只剩孤行）。drop_page_numbers 的位置判据对 CIE 失效（页码在页顶
    不在页尾，且常隔着图片块），实测把 Q4/Q10 的题号行当噪声、把页码当候选留下。
    判据：值 == 页号 → 页码（弃）；不等 → 题号（保留并提升为强候选）。
    风险：题号恰好等于所在页号时会被误弃（保守，可接受——那种题的正文行通常还在）。
    """
    return [c for c in cands if not (c[3] == "A" and c[2] == c[1])]


def derive_qnos(cands, use_a=False):
    """从候选提取期望题号序列。

    ⚠️ 关键：kind A（独立数字行）在真题卷里**几乎总是页码/公式里的孤立数字**，
    题号必然带正文（"1 The curve..."→E、"1. Find..."→C）或独占一行带点
    （爱得思的 "2." →F）。若把 A 类混进来，页码 13 排在题号 7 前面时会污染
    LIS，把 7 挤掉（实测 9231_s23_qp_12）。
    所以：默认只用强形态候选（E/C/B/D/F），强候选不足 3 个题号才回退全量。
    use_a=True（CIE 专用，调用方已用 cie_promote_anchors 剥掉页码）时把 A 纳入强集。
    """
    strong_kinds = ("E", "C", "B", "D", "F", "A") if use_a else ("E", "C", "B", "D", "F")
    strong = [c for c in cands if c[3] in strong_kinds]
    if len({q for (_, _, q, _) in strong}) >= 3:
        use = strong
    else:
        use = cands
    seen = []
    for (_, _, q, _) in use:
        if q >= 1 and q not in seen:
            seen.append(q)
    if not seen:
        return []
    # 动态规划求最长严格递增子序列
    best = [1] * len(seen)
    prev = [-1] * len(seen)
    for i in range(len(seen)):
        for j in range(i):
            if seen[j] < seen[i] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i = best.index(max(best))
    seq = []
    while i >= 0:
        seq.append(seen[i]); i = prev[i]
    seq = list(reversed(seq))
    # 若存在从 1 起头的子序列，截到那里（可能有从中间起头的更长序列——真题卷以 1 起头）
    if seq and seq[0] != 1 and 1 in seq:
        head, started = [], False
        for q in seq:
            if q == 1:
                started = True
            if started:
                head.append(q)
        if len(head) >= 3:
            seq = head
    # gap 截断：真题卷题号连续（OCR 丢题号行时允许连缺 2 题），>3 的跳变是噪声混入
    out = []
    for q in seq:
        if out and q - out[-1] > 3:
            break
        out.append(q)
    return out


# ---------- MinerU 解析 ----------
def run_mineru(pdf: Path, tier: str) -> Path | None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    dst = OUTDIR / (pdf.stem.replace(" ", "_")[:80] + ".md")
    if dst.exists() and dst.stat().st_size > 200:
        return dst
    env = dict(os.environ)
    r = subprocess.run(
        [MINERU, "parse", str(pdf), "--tier", tier, "--pages", "all",
         "-o", str(dst), "--json", "--wait", "2400"],
        capture_output=True, text=True, timeout=3600, env=env, cwd="/tmp")
    if dst.exists() and dst.stat().st_size > 200:
        return dst
    print(f"    MinerU 失败: {(r.stderr or r.stdout or '')[-200:]}", flush=True)
    return None


# ---------- 主流程 ----------
def process(pdf: Path, tier: str, apply: bool, con) -> Counter:
    st = Counter()
    info = parse_name(pdf.name)
    if info is None:
        return st
    if "skip" in info:
        st["skip"] += 1
        return st
    unit, year, session, paper = info["unit"], info["year"], info["session"], info["paper"]
    if info["kind"] != "qp":
        st["ms_skip"] += 1
        return st
    # 预检：库内已有同场次题 → 跳过（不必再花 CPU 解析）。
    # 粒度分考试局：
    #   CIE —— 一场多 variant（11/12/13/15），按 unit×year×session×variant 判，
    #          同一场可能缺某个 variant（如 2025s P1 缺 v3）。
    #   EDX —— 一场只有一个 QP，且旧 JSON 入库的 paper 值是「2023Jan」格式而非
    #          「01」，按 variant 判会漏匹配造成重复导入，必须按场次判。
    # 幂等保护只防重复写，预检防的是「用户早有数据的卷白解析一遍/重复入库」。
    if con is not None:
        if info["board"] == "EDX":
            have = con.execute(
                "SELECT count(*) FROM question WHERE unit=? AND year=? AND session=?",
                (unit, year, session)).fetchone()[0]
        else:
            have = con.execute(
                "SELECT count(*) FROM question WHERE unit=? AND year=? AND session=? AND paper=?",
                (unit, year, session, paper)).fetchone()[0]
        if have > 0:
            st["have"] += 1
            return st
    prefix = "CIE_" if info["board"] == "CIE" else "EDX_"
    md = run_mineru(pdf, tier)
    if not md:
        st["parse_fail"] += 1
        return st
    text = md.read_text(encoding="utf-8", errors="replace")
    lines, page_of, pages = build(text)
    cands = candidates(lines, page_of)
    cands, _ = drop_page_numbers(lines, page_of, pages, cands)
    if info["board"] == "EDX":
        # 爱得思页码就是裸数字行（页脚），且 drop_page_numbers 的「值==页号」判据
        # 只能杀掉一部分（页码不在页尾时漏网，实测第6页页码6存活并劫持了 Q6 锚点）。
        # 爱得思题号必带点（F）或带正文（C/E），裸数字行可全弃，丢失的由 Total 锚点补。
        cands = [c for c in cands if c[3] != "A"]
        cands = edx_total_anchors(lines, page_of, cands)
        qnos = derive_qnos(cands)
    else:
        # CIE：题号常是独立数字行（题干旁白），按「值==页号→页码」分离后提升为强候选
        cands = cie_promote_anchors(cands)
        qnos = derive_qnos(cands, use_a=True)
    if not qnos:
        st["no_qno"] += 1
        return st
    # pages_of 优先取强形态候选（E/C/B/D/F）所在页：A 类若排在前面会把
    # 题号的「期望页」带到错误页面，find_starts 就锁定到错页（实测 Q6 被带到第6页）。
    pages_of = {}
    for (li, p, q, k) in cands:
        if k in ("E", "C", "B", "D", "F"):
            pages_of.setdefault(q, p)
    for (li, p, q, k) in cands:
        pages_of.setdefault(q, p)
    segs = slice_paper(lines, pages, cands, qnos, pages_of)
    if not segs:
        st["no_slice"] += 1
        return st
    made = 0
    for q in sorted(segs):
        s, e, _how = segs[q]
        seg = "\n".join(lines[s:e])
        seg = serve.clean_paper_text(seg)
        # 质量门禁：有效字符不足或噪声过多 → 弃（宁可少，不错）
        eff = re.sub(r"\s", "", seg)
        noise = sum(1 for l in seg.split("\n")
                    if re.match(r"^\s*(<!--\s*page|\*?\s*BLANK|DO NOT)", l))
        if len(eff) < 40 or noise > max(3, len(seg.split("\n")) * 0.3):
            st["low_q"] += 1
            continue
        marks = extract_marks(seg, info["board"])
        qid = f"{prefix}{unit}_{year}{session}_{paper}_Q{q}"
        topic = f"RAWGAP-{unit}"
        if apply:
            con.execute("""INSERT OR IGNORE INTO question
                (qid,parent_qid,board,unit,year,session,paper,qno,marks,qtype,
                 stem_md,topic_id,qp_path,src_file,verified,src_status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,'new_paper',datetime('now'))""",
                        (qid, None, info["board"], unit, year, session, paper, q,
                         marks, "written", seg, topic, str(pdf), str(pdf)))
        made += 1
    st["q"] += made
    st["papers"] += 1
    print(f"  {pdf.name}: {unit} {year}{session} v{paper} → {made} 题"
          f"（题号 {qnos[0]}-{qnos[-1]}）", flush=True)
    return st


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    tier = "basic"
    for a in args:
        if a.startswith("--tier="):
            tier = a.split("=", 1)[1]
    paths = [a for a in args if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return
    pdfs = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            pdfs += sorted(p.rglob("*.pdf"))
        elif p.suffix.lower() == ".pdf":
            pdfs.append(p)
    # QP only
    pdfs = [p for p in pdfs if re.search(r"_(qp)_\d{2}\.pdf$", p.name, re.I)
            or re.search(r"_\d{2}_QP_", p.name)]
    print(f"待处理 QP: {len(pdfs)} 个 | tier={tier} | {'写库' if apply else 'dry-run'}")
    con = sqlite3.connect(DB) if apply else None
    tot = Counter()
    for i, pdf in enumerate(pdfs, 1):
        print(f"[{i}/{len(pdfs)}] {pdf.name}", flush=True)
        tot += process(pdf, tier, apply, con)
        if apply and i % 10 == 0:
            con.commit()
    if apply:
        con.commit(); con.close()
    print(f"\n汇总: 卷 {tot['papers']} / 题 {tot['q']} / 预检跳过(已有) {tot['have']} / "
          f"跳MS {tot['ms_skip']} / 跳过(无单元等) {tot['skip']} / "
          f"解析失败 {tot['parse_fail']} / 无题号 {tot['no_qno']} / "
          f"切分失败 {tot['no_slice']} / 低质量题 {tot['low_q']}")


if __name__ == "__main__":
    main()
