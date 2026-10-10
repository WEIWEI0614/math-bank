#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_data.py —— 题库数据自检（只用标准库，无需 bank.sqlite）

检查项：
  1. 每个单元文件能否正确解析
  2. 题目是否都是定长 11 字段
  3. topic_id 是否悬空引用（指向不存在的知识点）
  4. 答案长度分布是否有「定长截断尖峰」（如恰好 1200）
  5. qid 是否全局重复
  6. 与 data/index.js 登记的题量是否一致

用法:
    python3 scripts/check_data.py            # 默认：结构性问题才失败
    python3 scripts/check_data.py --strict   # 已知数据缺陷也算失败

退出码:
    0  没有结构性问题（默认模式下，已知数据缺陷只警告）
    1  存在必须修复的问题（--strict 时含已知数据缺陷）
"""
import json
import os
import sys
import glob
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "site", "data")

# 已知的系统性缺陷阈值：答案长度恰好等于该值的题目占比超过此比例即报警
TRUNC_SUSPECT_RATIO = 0.02


def load_units():
    """解析 site/data/*.js，返回 {code: unit_dict}。"""
    units = {}
    for path in sorted(glob.glob(os.path.join(DATA, "*.js"))):
        code = os.path.basename(path)[:-3]
        if code == "index":
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        marker = ";window.UNIT_DATA["
        if marker not in src:
            print("  ✗ %-12s 不是合法的单元文件（缺 %r）" % (code, marker))
            continue
        j = src.index(marker)
        k = src.index("=", j)
        try:
            units[code] = json.JSONDecoder().raw_decode(src[k + 1:])[0]
        except ValueError as e:
            print("  ✗ %-12s JSON 解析失败：%s" % (code, e))
    return units


def load_index():
    path = os.path.join(DATA, "index.js")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        src = f.read()
    start = src.index("[")
    end = src.rindex("]") + 1
    return json.loads(src[start:end])


def main():
    strict = "--strict" in sys.argv

    # errors   —— 结构性问题：会直接让系统出错，必须修复
    # warnings —— 已知数据缺陷：已记录在 docs/KNOWN-ISSUES.md，默认只提示
    errors = []
    warnings = []

    units = load_units()
    if not units:
        errors.append("没有解析到任何单元文件")

    index = {r["code"]: r for r in load_index()}

    total_q = 0
    all_qids = collections.Counter()
    ans_lens = collections.Counter()

    print("=" * 74)
    print("%-12s %6s %6s %6s  %s" % ("单元", "题量", "知识点", "章", "检查"))
    print("=" * 74)

    for code, d in sorted(units.items()):
        topics = d.get("topics", [])
        chapters = d.get("chapters", [])
        questions = d.get("questions", [])
        total_q += len(questions)

        tids = {t["id"] for t in topics}
        cids = {c["id"] for c in chapters}

        notes = []

        bad_len = [q[0] for q in questions if len(q) != 11]
        if bad_len:
            errors.append("%s: %d 题字段数不是 11（例：%s）"
                          % (code, len(bad_len), bad_len[0]))
            notes.append("字段数×%d" % len(bad_len))

        # 悬空 topic_id 是已记录的系统性缺陷（见 docs/KNOWN-ISSUES.md §1）：
        # 这类题目永远不会被自适应出题选中，但不会让系统崩溃。
        # 因此归为 warning 而非 error —— 否则 CI 会因为存量数据一直红。
        dangling = [q[0] for q in questions
                    if len(q) == 11 and q[1] not in tids]
        if dangling:
            warnings.append("%s: %d 题 topic_id 悬空引用（例：%s）—— "
                            "这些题不会被出题选中，见 docs/KNOWN-ISSUES.md §1"
                            % (code, len(dangling), dangling[0]))
            notes.append("悬空topic×%d" % len(dangling))

        bad_parent = [t["id"] for t in topics if t.get("parent") not in cids]
        if bad_parent:
            warnings.append("%s: %d 个知识点 parent 悬空（例：%s）"
                            % (code, len(bad_parent), bad_parent[0]))
            notes.append("悬空parent×%d" % len(bad_parent))

        for q in questions:
            if len(q) != 11:
                continue
            all_qids[q[0]] += 1
            ans_lens[len(q[6] or "")] += 1

        registered = index.get(code)
        if registered and registered.get("n") != len(questions):
            warnings.append("%s: index.js 登记 %d 题，实际 %d 题"
                            % (code, registered.get("n"), len(questions)))
            notes.append("索引不符")

        if not notes:
            notes.append("OK")

        print("%-12s %6d %6d %6d  %s" %
              (code, len(questions), len(topics), len(chapters), " ".join(notes)))

    # --- qid 全局唯一 ---
    dup = [(q, c) for q, c in all_qids.items() if c > 1]
    if dup:
        errors.append("qid 重复 %d 个（例：%s 出现 %d 次）"
                      % (len(dup), dup[0][0], dup[0][1]))

    # --- 答案长度分布：检测定长截断 ---
    if ans_lens:
        top_len, top_cnt = ans_lens.most_common(1)[0]
        ratio = top_cnt / max(1, sum(ans_lens.values()))
        if top_len > 0 and ratio > TRUNC_SUSPECT_RATIO:
            msg = ("答案长度尖峰：%d 题（%.1f%%）长度恰好 = %d，疑似定长截断"
                   % (top_cnt, ratio * 100, top_len))
            warnings.append(msg)
        empty = ans_lens.get(0, 0)
        if empty:
            warnings.append("答案文本为空：%d 题（%.1f%%）"
                            % (empty, 100.0 * empty / max(1, sum(ans_lens.values()))))

    print("=" * 74)
    print("单元 %d 个 · 题目 %d 道 · 知识点 %d 个"
          % (len(units), total_q,
             sum(len(d.get("topics", [])) for d in units.values())))
    if ans_lens:
        print("答案长度 TOP3：%s"
              % ", ".join("%d字符×%d" % (l, c) for l, c in ans_lens.most_common(3)))
    print("=" * 74)

    if warnings:
        print("\n⚠️  已知数据缺陷（见 docs/KNOWN-ISSUES.md）：")
        for w in warnings:
            print("   · %s" % w)

    if errors:
        print("\n🔴 必须修复（结构性问题）：")
        for e in errors:
            print("   · %s" % e)
        print("\n检查未通过。")
        return 1

    if warnings and strict:
        print("\n--strict：已知数据缺陷视为失败。")
        return 1

    print("\n✅ 检查通过（%d 项已知缺陷已记录，不阻塞）。" % len(warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
