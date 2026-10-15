#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补库验收：重复检查 → session_cn 回填 → 覆盖矩阵 → 质量抽验。
用法: python3 verify_gap_fill.py [--fix]
  --fix: 执行 session_cn 回填（否则只报告）
"""
import sqlite3, sys
from collections import Counter, defaultdict

DB = "/Users/davidwei/Desktop/数学题库系统/bank.sqlite"
con = sqlite3.connect(DB)
fix = "--fix" in sys.argv

print("=" * 62)
print("① 总量与新增")
tot = con.execute("SELECT count(*) FROM question").fetchone()[0]
new = con.execute("SELECT count(*) FROM question WHERE src_status='new_paper'").fetchone()[0]
print(f"   总题数: {tot}   本次新增(new_paper): {new}")
print(f"   新增按考试局: {con.execute('SELECT board, count(*) FROM question WHERE src_status=\"new_paper\" GROUP BY board').fetchall()}")

print("\n② 重复检查（同 unit+year+session+paper+qno 只允许 1 行）")
dups = con.execute("""
    SELECT unit, year, session, paper, qno, count(*) c, group_concat(qid)
    FROM question GROUP BY unit, year, session, paper, qno HAVING c > 1
""").fetchall()
print(f"   重复组: {len(dups)}")
for d in dups[:10]:
    print(f"     {d[0]} {d[1]}{d[2]} v{d[3]} Q{d[4]}: {d[5]}行 {d[6][:80]}")

print("\n③ 新增题的场次覆盖（应有题且题量合理）")
rows = con.execute("""
    SELECT unit, year, session, count(*) n, min(qno), max(qno)
    FROM question WHERE src_status='new_paper'
    GROUP BY unit, year, session ORDER BY unit, year, session
""").fetchall()
for u, y, s, n, qmin, qmax in rows:
    flag = "⚠️题量偏少" if n < 5 else ""
    print(f"   {u:14s} {y}{s}  {n:3d}题 (Q{qmin}-{qmax}) {flag}")

print("\n④ session_cn 回填")
miss = con.execute("SELECT count(*) FROM question WHERE src_status='new_paper' AND (session_cn IS NULL OR session_cn='')").fetchone()[0]
print(f"   待回填: {miss} 行")
if fix and miss:
    MAP = {"m": "春季(1月)", "s": "夏季(5-6月)", "w": "冬季(10-11月)", "sp": "样卷/其他"}
    n = 0
    for code, cn in MAP.items():
        c = con.execute("UPDATE question SET session_cn=? WHERE session=? AND (session_cn IS NULL OR session_cn='')", (cn, code))
        n += c.rowcount
    con.commit()
    print(f"   已回填 {n} 行（全库范围）")

print("\n⑤ 关键场次抽查（用户点名的）")
for u, y, s, label in [
    ("EDXIALP1", 2025, "w", "爱得思P1 2025年10月"),
    ("EDXIALP2", 2025, "w", "爱得思P2 2025年10月"),
    ("EDXIALM1", 2025, "w", "爱得思M1 2025年10月"),
    ("EDXIALS1", 2025, "w", "爱得思S1 2025年10月"),
    ("EDXIALP1", 2024, "w", "爱得思P1 2024年10月"),
    ("CIE9709P1", 2025, "w", "CIE P1 2025年10-11月"),
    ("CIE9709S1", 2025, "w", "CIE S1 2025年10-11月"),
    ("CIE9709M1", 2025, "w", "CIE M1 2025年10-11月"),
    ("CIE9231FP1", 2025, "w", "CIE FP1 2025年10-11月"),
    ("CIE9231FM", 2025, "s", "CIE FM 2025年5-6月"),
]:
    n = con.execute("SELECT count(*) FROM question WHERE unit=? AND year=? AND session=?", (u, y, s)).fetchone()[0]
    print(f"   {label:24s} {n:3d} 题 {'✅' if n >= 5 else '❌ 缺失'}")

print("\n⑥ 质量抽验（新增题前3条的题干首行）")
for qid, stem in con.execute(
        "SELECT qid, stem_md FROM question WHERE src_status='new_paper' ORDER BY created_at LIMIT 3"):
    first = next((l for l in stem.split("\n") if l.strip()), "")
    print(f"   {qid}: {first[:70]}")

con.close()
print("\n验收完成")
