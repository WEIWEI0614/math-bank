# 自适应引擎

> 能力评估与选题策略的设计依据、A/B 实测数据与文献出处。

---

## 1. 为什么用 Elo 而不是 IRT

| | IRT（2PL/3PL） | Elo |
|---|---|---|
| 参数估计所需样本 | 标准 2PL 需 **N > 500**；分层贝叶斯可降到 N ≈ 100 | **冷启动即可用** |
| 题目难度 | 需先标定 | 可与学生能力**同时在线校准** |
| 本系统适配度 | ❌ 单学生冷启动时样本量远远不够 | ✅ |

依据：König, Spoden & Frey (2020), *An Optimized Bayesian Hierarchical 2PL Model for
Small-Sample Item Calibration*, Applied Psychological Measurement 44(4):311–326 ——
即便用分层贝叶斯把 2PL 的标定样本量降到 N=100，仍远高于我们冷启动时的样本量。

---

## 2. 能力评估

### 2.1 常量

```js
const INIT   = 1000;   // 初始能力分
const K_HI   = 32;     // 早期 K 值（样本少，快速收敛）
const K_LO   = 12;     // 稳定期 K 值
const MIN_T  = 3;      // 最小样本数（低于此向章均值收缩）
const SHOW_AT = 15;    // 展示阈值（低于此 UI 不显示分数）
const SHRINK = 0.5;    // 向同章兄弟节点收缩的权重
```

服务端同名常量（必须与前端一致）：

```python
SECS_SLOW, CREDIT_SLOW = 120, 0.7
INIT, K_HI, K_LO = 1000.0, 32.0, 12.0
MIN_T, SHOW_AT = 3, 15
```

### 2.2 更新公式

```js
function upd(t, D, s, secs) {
  let sc = s;
  if (s === 1 && secs > 120) sc = 0.7;          // 超时降权
  const a = rating(t);
  const k = Math.max(K_LO, K_HI - (STU.n[t]||0) * 2);   // K 随样本衰减
  STU.elo[t] = a + k * (sc - E(a, D));
  STU.n[t] = (STU.n[t]||0) + 1;
}
```

其中：

- **题目难度** `D = 800 + 800 × (1 - difficulty_p)`
- **期望得分** `E(a,D) = 1 / (1 + 10^((D-a)/400))`
- **实际得分** `s ∈ {0, 0.5, 1}`

**K 值衰减**：`k = max(12, 32 - 2n)` —— 前 10 题快速收敛，之后趋于稳定，避免单题波动过大。

**超时降权**：超过 120 秒才做对，只给 0.7 学分。速度是能力的独立维度（见 §4 文献）。

### 2.3 章节收缩

样本不足 3 题时，向**同章兄弟知识点**的加权平均收缩：

```js
function ability(t) {
  const n = STU.n[t] || 0;
  if (n >= MIN_T) return rating(t);
  const ch = chOf[t];
  const sibs = Object.keys(chOf).filter(x => chOf[x] === ch);
  const pool = sibs.filter(x => (STU.n[x]||0) >= MIN_T).map(x => [rating(x), STU.n[x]]);
  if (!pool.length) return rating(t);
  const w = pool.reduce((s,p) => s + p[1], 0);
  const m = pool.reduce((s,p) => s + p[0]*p[1], 0) / w;
  return n ? SHRINK*rating(t) + (1-SHRINK)*m : m;   // 一次都没做过 → 直接用章均值
}
```

目的：避免"某知识点只做过 1 题"就给出极端分数。

### 2.4 样本提示

```js
function marks(t) {
  const n = STU.n[t] || 0;
  return n >= SHOW_AT ? "" : (n >= MIN_T ? "样本偏少" : "样本不足");
}
```

**< 15 次不显示能力分**（只显示"—"），这是产品约束，由 A/B 验证推得。

---

## 3. 选题策略

每轮 **10 题**：

| 类型 | 占比 | 逻辑 |
|---|---:|---|
| **补短板** | 60% | 取能力分最低的 3 个知识点，最多 6 题 |
| **间隔重复** | 25% | 本轮未用过的知识点，最多 3 题 |
| **拔高** | 15% | 能力分 > 1150 的知识点，最多 2 题 |
| 补齐 | — | 不足 10 题时用剩余知识点填满 |

```js
take(weak, 6, "补短板");
take(tp.filter(t => !used.has(t.id)), 3, "间隔重复");
take(tp.filter(t => !used.has(t.id) && ability(t.id) > 1150), 2, "拔高");
take(tp.filter(t => !used.has(t.id)), 9, "补齐");
```

每道题在界面上会标出**为什么选它**（补短板 / 间隔重复 / 拔高 / 补齐）。

**轮次级去重**：每轮独占一组 qid，并与上一轮比对，避免连续两轮做同一批题。

---

## 4. A/B 实验

指标双轨：

- **AUC** —— 预测下一题是否答对（知识追踪文献的标准指标）
- **r** —— 估计能力与真实能力的相关系数（对应"找薄弱点"这一核心任务）
- **练到不同知识点/人** —— **防混淆指标**：若某变体 r 上升但该值下降，
  说明它是靠"少练几个知识点"换来的假提升

| 变体 | AUC | r | 练到不同知识点/人 | 采用 |
|---|---:|---:|---:|:---:|
| 基线 | 0.7075 | 0.672 | 24.4 | |
| **用时加权（速度维度）** | **0.7141** | **0.703** | **24.9** | ✅ |
| 双链并行（Bolsinova 2025） | 0.6964 | 0.702 | 24.0 | ❌ AUC 反而降 |
| 滞后快照 | 0.6957 | 0.746 | 13.5 | ❌ 覆盖骤降，是混淆 |
| 多维（知识点+章节融合） | 0.6872 | 0.644 | 21.6 | ❌ 双指标变差 |

> **"滞后快照"是个陷阱**：r 虚高到 0.746，但覆盖的知识点数从 24.4 掉到 13.5。
> 它只是少练了知识点，不是估得更准。

---

## 5. 文献依据

### 已采用

- **Park, Cornillie, van der Maas & Van den Noortgate (2019)**,
  *A Multidimensional IRT Approach for Dynamically Monitoring Ability Growth in
  Computerized Practice Environments*, Frontiers in Psychology 10:620 ——
  同时使用**速度与正确率**优于只用正确率。→ 对应本系统的超时降权。

### 已排除（实测无效）

- **Bolsinova, Gergely & Brinkhuis (2025)**, *Keeping Elo alive*,
  British Journal of Mathematical and Statistical Psychology 79(1):95–110 ——
  指出"自适应选题 + 题目难度在线更新"会让评分方差膨胀、不收敛，提出双链方案。
  **实测双链 r 升但 AUC 降，未采用。**

- **Abdi et al. (2019)**, *A Multivariate Elo-based Learner Model*, arXiv:1910.12581 ——
  题目挂多概念时同时更新多维度。**实测把章节维度混进来反而伤区分度。**

### 不用 IRT 的依据

- **König, Spoden & Frey (2020)**, *An Optimized Bayesian Hierarchical 2PL Model for
  Small-Sample Item Calibration*, Applied Psychological Measurement 44(4):311–326。

---

## 6. 反复出现的规律（重要）

> **任何把估计向均值 / 章节收缩的操作，都会「校准变好、区分度被毁」。**

层次先验（r 0.662 → 0.604）、多维融合（r 0.672 → 0.644）都是同一个失败模式。

**原因**：本系统的核心任务是**排序**（找出哪个知识点最弱），不是**校准**（预测绝对正确率）。
在诊断 / 推荐场景里，牺牲区分度的正则化是净损失。

**推论**：§2.3 的章节收缩只在**样本 < 3** 时启用，一旦有足够样本立即停止收缩 ——
正是为了把"冷启动兜底"和"长期估计"分开。

---

## 7. 七类错因

```js
const ERRS = [
  ["concept",   "概念不清"],
  ["procedure", "步骤方法错"],
  ["setup",     "建模列式错"],
  ["algebra",   "代数运算失误"],
  ["calc",      "计算抄写失误"],
  ["time",      "没做完"],
  ["misread",   "看错题"]
];
```

错因**必填**，并驱动薄弱点页的处方建议：

| 错因集中 | 处方 |
|---|---|
| `algebra` / `calc` | 限时计算训练，**不是**重学概念 |
| `concept` | 回讲义重学，**不是**刷题 |
| `setup` | 专练"把文字转成方程" |

> `err_type` 是未来接 AI 引导式答疑最自然的触发器 —— 按错因匹配预生成的引导脚本。

---

## 8. 已知局限

- 能力分是**相对值**，用于排序，不要当正确率解读
- 只在**同一学生的不同知识点之间**可比，跨学生比较意义有限
- 主观题依赖**学生自评**，会有系统性偏差（学生倾向于高估自己）
- 手写过程分（M 分）无法判定 —— 只判客观题与自评
