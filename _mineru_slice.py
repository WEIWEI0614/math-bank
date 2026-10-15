#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MinerU md → 逐题切分（v2：页定位优先）。

两条路：
  ① 有 stem_page  → 页定位：取该页内容，页内从「题号 qno」起切到下一个题号/页尾
  ② 无 stem_page  → 题号切分：全文候选题号 + 与库内 qno 序列做 LCS 对齐（允许跳号）

题号形态（实测五种）：
  A 独立数字行       ^\s*(\d{1,2})\s*$
  B 加粗数字带点     ^\s*\*\*\s*(\d{1,2})\s*[\.\)]\s*\*\*
  C 数字点+文本      ^\s*(\d{1,2})\s*[\.\)]\s+\S
  D markdown 标题    ^#{1,6}\s*(\d{1,2})\b
  F 裸数字加点行     ^\s*(\d{1,2})\s*[\.\)]\s*$   ← 爱得思题型号（`2.` 独占一行，
                        题文本在下一页）；CIE 卷此形态罕见
⚠️ 页码与题号同形态 —— 页码判据：值 == 所在页号 且 位于该页最后 20% 行。
"""
import re
from pathlib import Path

RA = re.compile(r"^\s*(\d{1,2})\s*$")
RB = re.compile(r"^\s*\*\*\s*(\d{1,2})\s*[\.\)]")
RC = re.compile(r"^\s*(\d{1,2})\s*[\.\)]\s+\S")
RD = re.compile(r"^#{1,6}\s*(\d{1,2})(?:\s|$)")
RF = re.compile(r"^\s*(\d{1,2})\s*[\.\)]\s*$")
# E：数字 + 空格 + 大写字母/括号开头 —— CIE 卷的典型题号（`1 A bullet of mass m kg ...`）
#    前四条判据都要求「整行只有数字」或「数字带点号」，把 CIE 全漏了（实测 CIE9231FM
#    整卷只检出页码，题目首行一个都没认出来）。
RE5 = re.compile(r"^\s*(\d{1,2})\s+(?=[A-Z(])")
RPAGE = re.compile(r"<!--\s*page\s+(\d+)\s+of\s+(\d+)\s*-->")
MAXQ = 30


def build(text):
    """返回 (lines, page_of, pages)  pages=[(pno, s, e)]"""
    lines = text.split("\n")
    page_of = {}
    pno = 1
    for i, l in enumerate(lines):
        m = RPAGE.search(l)
        if m:
            pno = int(m.group(1))
        page_of[i] = pno
    pages = []
    if not lines:
        return lines, page_of, pages
    start, last = 0, page_of[0]
    for i in range(1, len(lines)):
        if page_of[i] != last:
            pages.append((last, start, i))
            start, last = i, page_of[i]
    pages.append((last, start, len(lines)))
    return lines, page_of, pages


def candidates(lines, page_of):
    """[(line_idx, page, qno, kind)]

    ⚠️ 判据顺序有讲究：A/B/D 是强判据（形态独特），C/E 弱（会匹配正文）。
       E 必须排在 C 之后 —— 否则 `1. Find ...` 会被 E 抢先，丢掉「带点号」这个信号。
    """
    out = []
    for i, l in enumerate(lines):
        m = None
        kind = None
        for rx, k in ((RA, "A"), (RD, "D"), (RB, "B"), (RC, "C"), (RF, "F"), (RE5, "E")):
            mm = rx.match(l)
            if mm:
                m, kind = mm, k
                break
        if m is None:
            continue
        q = int(m.group(1))
        if q > MAXQ:
            continue
        out.append((i, page_of[i], q, kind))
    return out


def drop_page_numbers(lines, page_of, pages, cands):
    """排除页码候选。

    实测两种版面（**页码位置完全不同**，第一版只按「页尾」判 → CIE 全错）：
      · CIE  : 页码**紧跟页标记**（`<!-- page 2 of 24 -->` 下一两行就是 `2`）
      · TMUA : 页码在页尾，且因「一页一题」其值恰好 == 页号

    判据（**只作用于 kind=='A' 的孤立数字行**，E/C 这类「数字+正文」一律当题号）：
      ① 值 == 页号 且 距页标记 ≤3 行   → 页码
      ② 值 == 页号 且 位于该页后半     → 页码
    """
    mark_line = {}
    for i, l in enumerate(lines):
        m = RPAGE.search(l)
        if m:
            mark_line.setdefault(int(m.group(1)), i)
    span = {p: (s, e) for p, s, e in pages}
    keep, drop = [], 0
    for (li, p, q, k) in cands:
        s, e = span.get(p, (0, len(lines)))
        ml = mark_line.get(p, -99)
        mid = s + (e - s) * 0.5
        if k == "A" and q == p:
            if (li - ml) <= 3 or li >= mid:
                drop += 1
                continue
        keep.append((li, p, q, k))
    keep.sort(key=lambda c: c[0])
    return keep, drop


def lcs_align(cands, expected):
    """候选与期望 qno 序列的最长公共子序列（按顺序）。
    返回 {qno: cand_index} 与命中数。"""
    vals = [c[2] for c in cands]
    n, m = len(vals), len(expected)
    if not n or not m:
        return {}, 0
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if vals[i] == expected[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    hit = {}
    i = j = 0
    while i < n and j < m:
        if vals[i] == expected[j]:
            hit.setdefault(expected[j], []).append(i)
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return hit, dp[0][0]


def find_starts(cands, qno, page, page_tol=0):
    """返回题号 qno 的**所有**候选行号（已按 kind 优先级筛过，升序）。

    为什么要返回全部：页码和公式里的孤立数字也会形成候选（kind A）。
    只要第一个候选是噪声，单值返回就会把起点定错（实测 Q2 的候选排在 Q1 之前）。

    ⚠️ `page_tol` 试过放宽到 2，**结果是变差**（ok 8172→8055，no_content 356→563）：
       库内 stem_page 与 MinerU 页号的偏差**不是系统性的**，
       放宽只会把别页的错误候选引进来。所以固定为**精确匹配**。
    """
    def scan(kinds, pgs):
        for p in pgs:
            cs = sorted(li for (li, pp, q, k) in cands
                        if q == qno and k in kinds and (p is None or pp == p))
            if cs:
                return cs
        return []

    if page:
        near = [page] + [page + d for d in range(1, page_tol + 1)] \
                      + [page - d for d in range(1, page_tol + 1)]
        near = [p for p in near if p >= 1]
    else:
        near = [None]
    for kinds in (("E", "C", "B", "D", "F"), ("A",)):
        r = scan(kinds, near)
        if r:
            return r
    # 兜底：忽略页限制，全文档找
    for kinds in (("E", "C", "B", "D", "F"), ("A",)):
        cs = sorted(li for (li, pp, q, k) in cands if q == qno and k in kinds)
        if cs:
            return cs
    return []


def slice_paper(lines, pages, cands, qnos, pages_of, score_fn=None):
    """**整卷一次性切分** —— 一页多题时必须这样做。

    ⚠️ 演进过程（多次踩坑，都记在这里）：
      v1 逐题独立切 → 一页多题时两题切出同一段
         （实测 9709_s10_qp_23：Q1 起点 54、Q2 起点 52，Q2 比 Q1 还早）
      v2 强制单调、找不到就跳过 → **no_anchor 从 151 暴涨到 2007**
      v3 候选列表 + 挑第一个满足单调的 + 兜底整页 → 稳住了

    v4（现在）新增 `score_fn`：**同一题有多个候选起点时，让调用方打分选最优**。
      为什么必须加：题干里的说明页/封面也会形成候选（SMC 的
      `1. Do not open this booklet`、EDXIAL 的 `Candidate surname`），
      单一「取第一个」会把整道题切到封面上去。实测这类「切错」有数百题，
      在过去被统一记成 `scrambled`（名字起错了 —— 那根本不是拆散）。

      score_fn(start, end) -> float，越大越好；返回 None 表示无法判断。
    """
    span = {p: (s, e) for p, s, e in pages}
    seen, oq = set(), []
    for q in qnos:
        if q is None or q in seen:
            continue
        seen.add(q)
        oq.append(q)
    # 每题的全部候选起点（供选优）
    all_cands = {q: find_starts(cands, q, pages_of.get(q)) for q in oq}
    starts, last = {}, -1
    for i, q in enumerate(oq):
        cs = all_cands.get(q) or []
        if not cs:
            continue
        pool = [c for c in cs if c > last] or [min(cs)]
        nq = oq[i + 1] if i + 1 < len(oq) else None
        ends = sorted(all_cands.get(nq) or []) if nq else []
        pick = pool[0]
        if score_fn and len(pool) > 1:
            best_sc = None
            for c in pool:
                e = next((x for x in ends if x > c), None)
                if e is None:
                    pg = pages_of.get(q) or 1
                    e = span.get(pg, (0, len(lines)))[1]
                    if e <= c:
                        e = min(len(lines), c + 40)
                try:
                    sc = score_fn(q, c, e)
                except Exception:
                    sc = None
                if sc is None:
                    continue
                if best_sc is None or sc > best_sc:
                    best_sc, pick = sc, c
        if pick <= last:
            pick = last + 1
        starts[q] = pick
        last = pick
    if not starts:
        return {}
    items = sorted(starts.items(), key=lambda kv: kv[1])
    out = {}
    for i, (q, s) in enumerate(items):
        if i + 1 < len(items):
            e = items[i + 1][1]
        else:
            pg = pages_of.get(q) or 1
            e = span.get(pg, (0, len(lines)))[1]
            if e <= s:
                e = min(len(lines), s + 6)
        out[q] = (s, e, "paper")
    return out


def slice_by_page(lines, pages, cands, qno, page, expected=None):
    """单题切分（保留作为「没有整卷 qno 序列」时的兜底）。

    优先用 slice_paper。这套单独切分的逻辑有两个弱点，所以只在拿不到
    整卷题号序列时才用：
      1. 起点若优先取 kind A（孤立数字行），会和公式里的数字、页码混淆 ——
         实测 9709_S08_qp_1 的 page2 有 5 个乱序 A 类候选（3,5,2,4,6）；
      2. 终点若用「下一个任意候选」，中间的噪声数字会把区间截断。
    """
    inpage = [(li, p, q, k) for (li, p, q, k) in cands if p == page]
    span = {p: (s, e) for p, s, e in pages}

    start = None
    for kind in ("E", "C", "B", "D", "A"):
        cand = [c for c in inpage if c[2] == qno and c[3] == kind]
        if cand:
            start = cand[0][0]
            break
    if start is None:
        for (li, p, q, k) in inpage:
            if q == qno:
                start = li
                break
    if start is None:
        s, e = span.get(page, (0, len(lines)))
        return (s, e), "page_only"

    # 终点①：expected 里的下一个题号
    nxt = None
    if expected:
        nq = next((x for x in sorted(set(expected)) if x is not None and x > qno), None)
        if nq is not None:
            pos = sorted(li for (li, p, q, k) in cands if li > start and q == nq)
            if pos:
                nxt = pos[0]
    # 终点②：退化为「下一个任意候选」
    if nxt is None:
        later = sorted(li for (li, p, q, k) in cands if li > start and p >= page and q != qno)
        if later:
            nxt = later[0]
    s0, e0 = span.get(page, (0, len(lines)))
    end = nxt if nxt is not None else e0
    return (start, end), ("by_expected" if nxt is not None else "to_page_end")
