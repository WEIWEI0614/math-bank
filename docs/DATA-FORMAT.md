# 题库数据格式规范

> 想导入自己的题库？按这个格式生成 `site/data/<UNIT>.js` 并在 `index.js` 注册即可，无需改动代码。

---

## 1. 文件组织

```
site/data/
├── index.js        单元索引（浏览器先加载它）
├── CIE9709P1.js    每个单元一个文件
├── CIE9709P3.js
└── ...             共 29 个
```

**为什么是 `.js` 而不是 `.json`**：`file://` 协议下 `fetch()` 会被 CORS 拦掉。
挂全局变量的 `.js` 在"双击打开"和"起服务"两种方式下都能加载。

---

## 2. 单元索引 `index.js`

```js
window.UNIT_INDEX=[
  {"code":"CIE9709P1","name":"CIE 9709 P1 纯数1","file":"CIE9709P1.js","n":1225,"nt":40,"kb":1550},
  ...
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | string | 单元代码，也是文件名（不含 `.js`）与 `UNIT_DATA` 的 key |
| `name` | string | 显示名 |
| `file` | string | 文件名 |
| `n` | int | 题目数 |
| `nt` | int | 知识点数 |
| `kb` | int | 文件体积（KB） |

---

## 3. 单元文件 `<UNIT>.js`

```js
window.UNIT_DATA=window.UNIT_DATA||{};
window.UNIT_DATA["TMUA"]={
  "unit":"TMUA",
  "name":"TMUA 入学考数学",
  "chapters":[ {"id":"CH-TMUA-3","name":"一次与二次函数"}, ... ],
  "topics":[
    {"id":"TP-TMUA-10_1","name":"Straight Line Equations (直线方程)",
     "parent":"CH-TMUA-10","pre":[],"nq":0}, ...
  ],
  "questions":[ [ ...11 个字段... ], ... ]
};
```

### 3.1 `chapters` —— 章（L1）

```json
{"id":"CH-TMUA-3","name":"一次与二次函数"}
```

### 3.2 `topics` —— 知识点（L2）

```json
{"id":"TP-TMUA-10_1","name":"Straight Line Equations (直线方程)",
 "parent":"CH-TMUA-10","pre":[],"nq":0}
```

| 字段 | 说明 |
|---|---|
| `id` | 知识点 ID，全局唯一 |
| `name` | 显示名（中英混排常见） |
| `parent` | 所属章 ID → `chapters[].id` |
| `pre` | 前置知识点 ID 数组 |
| `nq` | 题目数（**可能为 0，前端会按 `questions` 重新统计**） |

> ⚠️ **`pre` 字段只有 2.6% 非空**（1,009 个知识点里仅 26 个）。
> **想做学习路径必须自己建依赖图**，不要指望这个字段。

---

## 4. 题目：定长 11 元素数组

题目用**数组**而不是对象，纯粹为了省体积（12,030 题 × 11 字段，对象会多出 ~60% 的 key 开销）。

```js
["TMUA_SPEC_Paper1_Q1",          // [0] qid
 "TP-TMUA-8X6",                  // [1] topic_id
 1,                              // [2] marks
 0.55,                           // [3] difficulty_p
 "medium",                       // [4] difficulty_label
 "The sum of the two values...", // [5] stem_md
 "官方答案 D",                     // [6] ms_md / answer
 {"A":"$8.5$","B":"$7.5$"},      // [7] options
 [],                             // [8] figs（题面图）
 [],                             // [9] figs_ms（答案图）
 {"year":2014,"session":"2014",  // [10] source
  "session_cn":"2014","paper":"Paper1","qno":1}]
```

| 索引 | 字段 | 类型 | 说明 |
|---:|---|---|---|
| `[0]` | `qid` | string | **全局唯一**。命名如 `CIE_CIE9709P1_2008s_1_Q1`、`EDX_EDXIALP1_2016s_2016Jun_Q8` |
| `[1]` | `topic_id` | string | 外键 → `topics[].id` |
| `[2]` | `marks` | int | 分值 |
| `[3]` | `difficulty_p` | float 0–1 | 难度值。**越大越难**（引擎里 `D = 800 + 800×(1-p)`，p 越大 D 越小 = 越简单） |
| `[4]` | `difficulty_label` | string | `易` / `中` / `难` / `easy` / `medium` / `hard` |
| `[5]` | `stem_md` | string | 题面文本，**Markdown + LaTeX（`$...$` / `$$...$$`）** |
| `[6]` | `ms_md` | string | Mark Scheme 文本；客观题可能是 `"官方答案 D"` |
| `[7]` | `options` | object \| null | 客观题选项 `{"A":"...","B":"..."}`；主观题为 `null` |
| `[8]` | `figs` | string[] | 题面图文件名列表 |
| `[9]` | `figs_ms` | string[] | 答案图文件名列表 |
| `[10]` | `source` | object | `{year, session, session_cn, paper, qno}` |

### 字段细节

**`difficulty_p` 的方向容易搞反**：它是"容易度"，不是"难度"。
`p=0.933` 是**很简单的题**，`p=0.55` 是中档。

**`stem_md` 有 OCR 残损**（上标丢失、顺序错乱），**可靠的是原卷图**。
这也是前端把"截图主显、文字版折叠"作为默认呈现的原因。

**`ms_md` 有系统性截断**：3,093 题（25.7%）的长度**恰好等于 1200**，
是构建期"从合并文档切固定窗口"造成的。详见 [KNOWN-ISSUES.md](KNOWN-ISSUES.md)。

---

## 5. 图片

图片位于 `site/data/img/`，**因版权与体积不随仓库分发**（见 README 的版权声明）。
字段 `[8]` / `[9]` 只存**文件名**，路径前缀 `img/` 由前端拼接。

### 命名约定

| 模式 | 含义 |
|---|---|
| `<QID>__full.png` | 整页原图 |
| `<QID>__stem.png` | 题面切割图 |
| `<QID>__ms.png` | 答案（Mark Scheme）图 |
| `<QID>__ms_pN.png` | 答案图第 N 页 |
| `<QID>_stem_pN.png` | 题面分页碎片 |

> ⚠️ 532 题存在**分页碎片爆炸**（单题最多 26 页），页范围判定会失效。

---

## 6. 校验脚本

加完新单元后跑一遍自检，能提前发现大部分问题：

```python
# scripts/check_data.py —— 检查字段完整性、答案长度分布、引用完整性
import json, glob, collections

for f in glob.glob('site/data/*.js'):
    s = open(f, encoding='utf-8').read()
    if ';window.UNIT_DATA[' not in s:
        continue
    j = s.index(';window.UNIT_DATA[')
    k = s.index('=', j)
    d = json.JSONDecoder().raw_decode(s[k+1:])[0]

    tids = {t['id'] for t in d['topics']}
    cids = {c['id'] for c in d['chapters']}
    lens = collections.Counter()
    bad = 0

    for q in d['questions']:
        assert len(q) == 11, f"{q[0]} 字段数不是 11"
        if q[1] not in tids:
            bad += 1                      # topic_id 悬空引用
        lens[len(str(q[6] or ''))] += 1

    print(f"{d['unit']:12} q={len(d['questions']):5} "
          f"悬空topic={bad:4} 答案长度TOP3={lens.most_common(3)}")
```

**看什么**：

- `悬空topic` > 0 → 知识点 ID 对不上，前端会漏题
- 答案长度 TOP1 是某个**整数**（如 1200）→ 有定长截断
- 字段数不是 11 → 数据生成脚本有 bug

---

## 7. 当前规模

| 体系 | 单元 | 题量 | 知识点 | 章 |
|---|---:|---:|---:|---:|
| CIE 9709 A-Level 数学 | 7 | 5,832 | 125 | 54 |
| Edexcel IAL | 14 | 3,443 | 345 | 97 |
| 竞赛 / 入学考（BMO/SMC/ESAT/TMUA） | 4 | 1,539 | 509 | 49 |
| CIE 9231 进阶数学 | 4 | 1,216 | 30 | 30 |
| **合计** | **29** | **12,030** | **1,009** | **230** |

其他：客观题 1,178 道（9.8%）· 带图题 11,487 道（95.5%）· 年份跨度 1993–2026。
