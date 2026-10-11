#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_site.py —— 把 bank.sqlite 导出为浏览器可直接加载的数据文件（前端用）

零 LLM 调用。为什么不用 fetch JSON：
  file:// 协议下 fetch 会被 CORS 拦掉，而这份站点要能直接双击打开、
  也要能由本地 server 托管，所以导出成 .js（挂全局变量），两种方式都能跑。

输出：
  site/data/index.js       各单元清单（单元名 / 题量 / 知识点数 / 对应数据文件）
  site/data/<unit>.js      单个单元的完整数据（知识点树 + 题目）

用法:
    python3 scripts/build_site.py
    python3 scripts/build_site.py --db /path/bank.sqlite --data /path/site/data
    python3 scripts/build_site.py --max-kb 3000

说明：默认路径取「仓库根目录」下的 bank.sqlite 与 site/data。图片只有真正
存在时才写进 figs 字段，所以在**有原卷图的机器**上构建才能带上截图。

== 两个已修复的构建期缺陷（改这里前先读）==

1) 答案曾被 `substr(ms_md, 1, 1200)` 硬截断 —— 导致 3,093 题（25.7%）的答案
   恰好卡在 1200 字符，句子断在中间。现已去掉截断，有多少导多少。
   注意：数据库里另有 2,888 题的答案**在上游导入时就已被截断**，
   这个脚本救不回来，只能靠前端标注（见 index.html 的 TRUNC_LEN）。

2) 跨单元知识点曾被整批丢弃 —— 旧代码先只收 `CH-<unit>-` 前缀的章，
   再把 parent 不在这些章里的知识点从 topics[] 剔除。结果题目还在、
   知识点没了：1,331 题（11.1%）永远选不中（CIE9709P2 高达 69%）。
   现已改为「按章名合并 + 维护 old_id→canonical_id 重映射」，
   跨单元知识点被并入本单元并指向合并后的章，不再丢弃。
"""
import sqlite3
import os
import json
import argparse
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UNIT_CN = {
    "CIE9709P1": "CIE 9709 P1 纯数1", "CIE9709P2": "CIE 9709 P2 纯数2",
    "CIE9709P3": "CIE 9709 P3 纯数3",
    "CIE9709M1": "CIE 9709 M1 力学", "CIE9709S1": "CIE 9709 S1 统计1",
    "EDXIALP1": "Edexcel IAL P1", "EDXIALP2": "Edexcel IAL P2",
    "EDXIALP3": "Edexcel IAL P3", "EDXIALP4": "Edexcel IAL P4",
    "EDXIALFP1": "Edexcel IAL FP1 进阶1", "EDXIALFP2": "Edexcel IAL FP2 进阶2",
    "EDXIALFP3": "Edexcel IAL FP3 进阶3",
    "EDXIALM1": "Edexcel IAL M1 力学1", "EDXIALM2": "Edexcel IAL M2 力学2",
    "EDXIALM3": "Edexcel IAL M3 力学3",
    "EDXIALS1": "Edexcel IAL S1 统计1", "EDXIALS2": "Edexcel IAL S2 统计2",
    "EDXIALS3": "Edexcel IAL S3 统计3", "EDXIALD1": "Edexcel IAL D1 决策1",
    "CIE9231FP1": "CIE 9231 FP1 进阶纯数1", "CIE9231FP2": "CIE 9231 FP2 进阶纯数2",
    "CIE9231FM": "CIE 9231 FM 进阶力学", "CIE9231FS": "CIE 9231 FS 进阶统计",
    "SMC": "UKMT SMC 竞赛",
    "TMUA": "TMUA 入学考数学",
    "ESAT": "ESAT 入学考（ENGAA/NSAA）",
    "BMO": "BMO Round 1 竞赛",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "bank.sqlite"))
    ap.add_argument("--data", default=os.path.join(ROOT, "site", "data"))
    ap.add_argument("--max-kb", type=int, default=3000, help="单文件上限告警阈值")
    a = ap.parse_args()

    DATA = os.path.abspath(a.data)
    os.makedirs(DATA, exist_ok=True)
    con = sqlite3.connect(a.db)
    c = con.cursor()
    # ms_figs 列由 backfill_ms_md.py 建；若回填未跑过，这里兜底建空列保证可构建
    if not any(r[1] == "ms_figs" for r in c.execute("PRAGMA table_info(question)")):
        c.execute("ALTER TABLE question ADD COLUMN ms_figs TEXT")
        con.commit()

    # 知识点树。注意 topic_id 形如 CH-CIE9709P3-4，切单元名要 instr(...)-1，
    # 否则会把 "-4" 也切进去，导致章列表为空。
    l1 = {t: n for t, n in c.execute("SELECT topic_id, name_cn FROM topic WHERE level='L1'")}
    l2 = {}
    for t, n, p, pq, nq in c.execute(
            "SELECT topic_id, name_cn, parent_id, prereq_ids, n_questions FROM topic WHERE level='L2'"):
        l2[t] = {"n": n, "p": p, "pre": json.loads(pq) if pq else [], "nq": nq}

    # 单元 -> 知识点（必须走 topic_unit_map，跨单元知识点靠它）
    unit_topics = defaultdict(set)
    # topic_unit_map contains only L2 topic links; L1 chapter links are kept in a
    # separate table so the browser receives a clean chapter/topic tree.
    for t, u in c.execute("SELECT topic_id, unit FROM topic_unit_l1"):
        unit_topics[u].add(t)
    for t, u in c.execute("SELECT topic_id, unit FROM topic_unit_map"):
        unit_topics[u].add(t)
    for u, t in c.execute(
            "SELECT DISTINCT unit, topic_id FROM question "
            "WHERE topic_id IS NOT NULL AND length(trim(stem_md)) > 15"):
        unit_topics[u].add(t)
    # 章直接从 L2 的 parent_id 聚合，不再反解单元名
    unit_chapters = defaultdict(set)
    for u, ts in unit_topics.items():
        for t in ts:
            p = l2.get(t, {}).get("p") or ""
            # 只收本单元的章：跨单元知识点的 parent 可能指向别的单元，
            # 直接聚合会让单元章表混入 "trig / integration" 这类同名的外单元章
            if p.startswith("CH-" + u + "-"):
                unit_chapters[u].add(p)

    # 题目
    qs = defaultdict(list)
    # raw_chapter/chapter_name：未细分类单元（topic 只有占位）的章节兜底来源
    rawmap = {}          # (unit, qid) -> (raw_chapter, chapter_name)
    for qid, unit, tid, marks, dp, dt, stem, ms, opts, figs, msfigs, rc, rn, \
            year, session, session_cn, paper, qno in c.execute("""
            SELECT qid, unit, topic_id, marks, difficulty_p, difficulty_raw, stem_md,
                   COALESCE(ms_md,''), options, figs, ms_figs,
                   raw_chapter, chapter_name, year, session, session_cn, paper, qno
            FROM question WHERE topic_id IS NOT NULL AND length(trim(stem_md)) > 15
            ORDER BY unit, year, qno"""):
        o = json.loads(opts) if opts else None
        if o:
            # 丢弃 options 的两种情形（构建期判定，前端零逻辑）：
            # 1) 题干已含全部/绝大多数选项文本（SMC 部分年份拼接把选项拼进题干）
            # 2) 题干自带 >=3 个 "(A)".."(E)" 选项标记 —— 此时 options 列很可能
            #    与题干选项错位（SMC 早期 OCR 切分问题），展示错位选项比不展示更糟
            hit = sum(1 for v in o.values() if len(v.strip()) > 1 and v.strip() in stem)
            markers = sum(1 for L in "ABCDE" if "({})".format(L) in stem)
            if hit >= max(1, len(o) - 1) or markers >= 3:
                o = None
        # 图（q[8]）：figs 条目 file 为站点相对 site/data/ 的路径，存在才导出
        imgs = []
        if figs:
            try:
                for e in json.loads(figs):
                    f = e.get("file") if isinstance(e, dict) else None
                    if f and os.path.exists(os.path.join(DATA, f)):
                        imgs.append(f)
            except Exception:
                pass
        # 答案截图（q[9]）：ms_figs 条目，存在才导出
        mimgs = []
        if msfigs:
            try:
                for e in json.loads(msfigs):
                    f = e.get("file") if isinstance(e, dict) else None
                    if f and os.path.exists(os.path.join(DATA, f)):
                        mimgs.append(f)
            except Exception:
                pass
        qs[unit].append([qid, tid, marks or 0, round(dp or 0.5, 3), dt or "", stem,
                         ms or "", o, imgs, mimgs, {
                             "year": year, "session": session,
                             "session_cn": session_cn, "paper": paper,
                             "qno": qno
                         }])
        if rc:
            rawmap[(unit, qid)] = (rc, rn or rc)

    idx, total = [], 0
    # 占位单元（topic 只有 CH-<unit>-X 一个综合、真章为空）：
    # 用 classify_gaps 写入的 raw_chapter 合成「章 + 知识点」两级，
    # 题目 topic_id 临时改指向合成知识点 —— 前端零改动即可出章节 chips。
    raw_name = {}      # raw_chapter -> chapter_name（多数票）
    raw_cnt = defaultdict(Counter)
    for (u2, _q), (rc, rn) in rawmap.items():
        raw_cnt[u2][rc] += 1
        raw_name.setdefault(rc, rn)
    synth_units = set()
    for u in raw_cnt:
        if u == "BMO":
            continue
        real = [c_ for c_ in unit_chapters.get(u, set()) if not c_.endswith("-X")]
        if not real:
            synth_units.add(u)

    for u in sorted(qs, key=lambda x: -len(qs[x])):
        topics = sorted(t for t in unit_topics.get(u, set()) if t in l2)

        # ---- 章：本单元的章 + 跨单元知识点带来的外单元章 ----
        # 旧实现只收 CH-<unit>- 前缀的章，然后把 parent 不在集合里的知识点
        # 整个丢掉 —— 那道题从此永远选不中（全库 1,331 题，CIE9709P2 占 69%）。
        # 现在改为「按章名合并 + old_id→canonical_id 重映射」：外单元章并入
        # 本单元（chips 显示的是章名而非原始章号），知识点一律保留。
        chapter_ids = set(unit_chapters.get(u, set()))
        for t in topics:
            p = (l2.get(t, {}).get("p") or "").strip()
            if p:
                chapter_ids.add(p)
        # 兜底章：万一有知识点没有 parent，挂到本单元的「综合题」章，
        # 绝不让知识点无家可归（无 parent 的知识点前端会显示成裸 topic id）
        fallback_id = "CH-" + u + "-X"
        name_to_id, rename = {}, {}
        for cid in sorted(chapter_ids):
            name = l1.get(cid) or cid
            canonical = name_to_id.setdefault(name, cid)
            rename[cid] = canonical
        chapters = [{"id": cid, "name": name}
                    for name, cid in sorted(name_to_id.items())]
        chapter_ids_out = {c2["id"] for c2 in chapters}

        if u == "BMO":
            # BMO 的原始 L1 只有占位章，但 question.chapter_name 已有
            # 17 个稳定主题；按主题建章，不再把每个知识点单独列成章。
            grouped_bmo = defaultdict(lambda: {"count": 0, "id": None})
            for item in qs[u]:
                qid, topic_id = item[0], item[1]
                row = c.execute("SELECT chapter_name FROM question WHERE qid=?", (qid,)).fetchone()
                # question.chapter_name 已是 BMO 的主题章（知识题库中的
                # raw_subtopic 是细粒度标签，不应在 BMO 页面重复展开）。
                name = ((row[0] if row else "") or topic_id).strip() or "BMO1 综合"
                grouped_bmo[name]["count"] += 1
            chapter_order = sorted(grouped_bmo, key=lambda k: (-grouped_bmo[k]["count"], k))
            chapter_id_by_name = {name: "CH-BMO-" + str(i + 1)
                                  for i, name in enumerate(chapter_order)}
            chapters = [{"id": chapter_id_by_name[name], "name": name}
                        for name in chapter_order]
            tlist = [
                {"id": "T:" + name, "name": name,
                 "parent": chapter_id_by_name[name],
                 "pre": [], "nq": grouped_bmo[name]["count"]}
                for name in chapter_order
            ]
            # q[1] 已改为 T:<章名>，确保前端按章筛选和知识点筛选一致。
            for item in qs[u]:
                row = c.execute(
                    "SELECT chapter_name FROM question WHERE qid=?", (item[0],)
                ).fetchone()
                name = ((row[0] if row else "") or item[1]).strip() or "BMO1 综合"
                if name in grouped_bmo:
                    item[1] = "T:" + name
        else:
            tlist = []
            for t in topics:
                raw_parent = (l2[t]["p"] or "").strip()
                parent = rename.get(raw_parent, raw_parent)
                if parent not in chapter_ids_out:
                    # 兜底：parent 被合并掉了或原本就没有 → 挂到综合章
                    if fallback_id not in chapter_ids_out:
                        chapter_ids_out.add(fallback_id)
                        chapters.append({"id": fallback_id,
                                         "name": l1.get(fallback_id, "综合题")})
                    parent = fallback_id
                tlist.append({"id": t, "name": l2[t]["n"], "parent": parent,
                              "pre": l2[t]["pre"],
                              "nq": sum(1 for q in qs[u] if q[1] == t)})

        if u in synth_units:
            # 按 raw_chapter 重排：章 id=raw_chapter，知识点 id=T:<raw_chapter>
            # 注意：必须**先把 q[1] 改指合成知识点**，再算 nq ——
            # 旧顺序反过来，nq 恒为 0 → pick() 过滤 nq>0 → 章节选不出题。
            for q in qs[u]:
                ent = rawmap.get((u, q[0]))
                if ent:
                    q[1] = "T:" + ent[0]
            rc_sorted = sorted(raw_cnt[u], key=lambda x: (x[-2:], raw_name.get(x, x)))
            chapters = [{"id": rc, "name": raw_name.get(rc, rc)} for rc in rc_sorted]
            tlist = [{"id": "T:" + rc, "name": raw_name.get(rc, rc),
                      "parent": rc, "pre": [],
                      "nq": sum(1 for q in qs[u] if q[1] == "T:" + rc)}
                     for rc in rc_sorted]

        payload = {
            "unit": u, "name": UNIT_CN.get(u, u),
            "chapters": chapters,
            "topics": tlist,
            "questions": qs[u],
        }
        txt = "window.UNIT_DATA=window.UNIT_DATA||{};window.UNIT_DATA[" + \
              json.dumps(u, ensure_ascii=False) + "]=" + \
              json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"
        fn = "{}.js".format(u)
        open(os.path.join(DATA, fn), "w", encoding="utf-8").write(txt)
        kb = len(txt.encode()) / 1024
        total += kb
        idx.append({"code": u, "name": UNIT_CN.get(u, u), "file": fn,
                    "n": len(qs[u]), "nt": len(payload["topics"]), "kb": round(kb)})
        flag = "  <== 超过上限，建议注入时按章加载" if kb > a.max_kb else ""
        print("  {:12s} 题 {:5d}  知识点 {:3d}  章 {:3d}  {:7.0f} KB{}".format(
            u, len(qs[u]), len(payload["topics"]), len(chapters), kb, flag))

    js = "window.UNIT_INDEX=" + json.dumps(idx, ensure_ascii=False, separators=(",", ":")) + ";"
    open(os.path.join(DATA, "index.js"), "w", encoding="utf-8").write(js)
    print("\n[完成] {} 个单元，合计 {:.0f} KB -> {}".format(len(idx), total, DATA))
    print("       index.js {:.1f} KB".format(len(js.encode()) / 1024))
    print("[提示] 直接双击 site/index.html 可用（file:// 也能加载 .js）；")
    print("       若要保存学生作答进 bank.sqlite，请跑 python3 site/serve.py")


if __name__ == "__main__":
    main()
