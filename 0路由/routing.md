# 路由：怎么判断「直接下载」还是「先检索」

这是本智能体**唯一需要判断**的地方。判错了要么白搜一遍，要么拿着一堆标题下不了。

---

## 先明确一件事：检索要走 skill，不要走脚本

**P1 检索阶段的正确做法是加载 `1学术查询/` 这个 skill 并执行它的 workflow：**

```
读 1学术查询/SKILL.md
  → 它的 routing protocol 让你：读 manifest.yaml + 两个 always_load 核心文件
  → 检出 workflow = multi-source-search
  → 只读那一个 workflow 文件（references/workflows/wf1-multi-source-search.md）
  → 按它走：分析主题 → 按 domain→tier 选源 → 并发检索 → 去重 → 排序 → 呈现
  → 需要时再取用 search-strategy.md / source-tiers.md / dedup-engine.md
```

它注册了 **16 个 MCP 工具**（`mcp__academic-search__*`），其中 `search_papers`
就是 wf1 要的「CrossRef + PubMed + arXiv 并发检索」。

**为什么必须这样**：这个 skill 的价值在于**判断**——概念拆解、同义词扩展、
按领域选源（医学→PubMed、CS/物理→arXiv、跨学科→CrossRef）、T1→T2→T3 分级降级、
去重偏好、组合打分。这些是模型该做的事。把它改写成一句关键词查询
（=`search.py` 的做法）就把核心价值丢掉了，实测后果是候选里混进大量跑题文献。

`0路由/scripts/search.py` 是**兜底**：没有 MCP 可用、或完全无人值守且不需要判断时
才用它。它不是主路径。

### 落地点

检索的产物是**一份 DOI 清单**，交给下载流水线：

```bash
python 0路由/scripts/pipeline.py run --input picked.txt --select-file picked.txt --out-dir <目录>
```

`--select-file` 以清单为准，队列里没有的标识符会**自动追加**并补全元信息。
这就是「模型判断」与「流水线执行」之间的接缝。

---

## 判定树

```
拿到输入
  │
  ├─ 是文件路径？
  │    ├─ .xlsx ────────────────────────→ 表格解析 → 逐行取 DOI/标题
  │    ├─ .csv  ────────────────────────→ 表头识别 → 逐行取 DOI/标题
  │    └─ 其他文本 → 读内容后按下面「文本」分支走
  │
  └─ 文本
       │
       ├─ ① 匹配 `^@\w+\s*\{` ？ ──是→ BibTeX 解析
       ├─ ② 匹配 `^TY\s{1,2}-\s`？ ─是→ RIS 解析
       ├─ ③ 匹配 `^PMID-\s`？ ────是→ MEDLINE/EndNote 解析
       ├─ ④ 多行且首行含逗号？ ───是→ 尝试 CSV 解析
       │
       ├─ 上面解析出条目？ ──是→ 【直接下载】origin=direct
       │
       ├─ ⑤ 全文扫描 DOI 与 arXiv 号
       │     └─ 扫到？ ──是→ 【直接下载】origin=direct
       │
       └─ ⑥ 什么都没扫到 → 【先检索】kind=query
```

**顺序不可颠倒。** 早期版本先判断"像不像自然语言"再做格式识别，结果一段
BibTeX 会被误判成检索需求。正确顺序是：**结构化格式 → 标识符扫描 → 才当需求**。

---

## 混合输入怎么办

一份清单里常常一部分有 DOI、一部分只有标题。处理方式：

| 条目状态 | 去向 |
|---|---|
| 有 DOI / arXiv | `origin=direct`，直接进队列 |
| 只有标题 | 走 Crossref 标题检索补 DOI（阈值 0.75） |
| 补不到 DOI | 标 `status=failed` / `reason=bad_identifier`，**保留在表里让用户看见**，不静默丢弃 |

补到的 DOI 会写回条目（`source` 追加 `+crossref-title`），后续与直连条目**走同一条下载路径**。

---

## 检索需求怎么变成可下载的清单

这是 P1 的活儿，细节见 [../1学术查询/SKILL.md](../1学术查询/SKILL.md)。
本 skill 侧的关键决策：

### 通道选择

| 通道 | 默认 | 说明 |
|---|---|---|
| `openalex` | ✅ 开 | 复用本地化的 `1学术查询/scripts/academic_search.py`（纯标准库、无需 key） |
| `crossref` | ✅ 开 | 直连 REST API |
| `scansci` | ⬜ 关 | 上游自带的检索，输出是 Markdown 文本，解析稳定性一般；需要时 `--sources openalex,crossref,scansci` |

### 排序的一个真实陷阱

Crossref 的 `sort=is-referenced-by-count` 是**全局排序**，`query` 只做过滤——
于是「perovskite solar cell stability」会返回 SARS-CoV-2 这类全局高被引论文，
主题完全跑偏。

**本 skill 的做法**：永远先按相关性取一个更宽的候选池（`POOL_FACTOR = 5`），
再在本地按目标字段重排后截断。OpenAlex 通道沿用其脚本自带的
"先相关性池再重排"逻辑。

### 相关性排序的第二个陷阱：Crossref 把 query 当词袋

上面那条对策（宽池 + 本地重排）**解决不了这个问题**，因为本地重排用的还是同一个
relevance 信号。

Crossref 的相关性排序不理解查询意图，只做词袋匹配。查询
`phage-host interaction prediction machine learning` 里的
`prediction` / `interaction` / `machine learning` 都是高频词，
于是**药物靶点预测、船舶阻力预测、航班延误预测、人机交互认知负荷预测**
都会被拉到前排。实测确认过这一点。

**结论：单一 `--query` 的相关性排序不足以直接支撑"取前 N 条下载"。**

### 推荐做法：多角度查询并集 + 清单落地

这是 P1 的**推荐工作流**（不是可选技巧）：

```bash
# 1) 从多个角度各取一批，快照落盘（不污染主队列）
python 0路由/scripts/search.py --query "phage-host interaction prediction machine learning" --limit 40 --year-from 2019 --out pool1.json
python 0路由/scripts/search.py --query "bacteriophage host range prediction computational"     --limit 40 --year-from 2019 --out pool2.json
python 0路由/scripts/search.py --query "deep learning phage bacteria interaction"             --limit 40 --year-from 2019 --out pool3.json
#    ……同义/近义/子问题角度各来一条，通常 4~6 条就够

# 2) 从并集里挑出真正想要的，写成一份清单（一行一个 DOI）
#    —— 这一步是人工（或规则）判断，不要指望排序替你决定

# 3) 用清单落地。队列里没有的条目会被自动追加，并补全元信息
python 0路由/scripts/pipeline.py run --input picked.txt --select-file picked.txt --out-dir "<目录>"
```

为什么必须绕这一圈：**"要哪几篇"是用户的判断，不是排序的产物**。
把选择权交给 `--limit-select N` 就等于让词袋匹配替你决定。

代价是这一步无法完全自动化。无人值守场景的折中见 [hitl.md](hitl.md) 的
「无人值守模式」。

### 限速

- OpenAlex 对匿名调用限速很严（常见 429）。给 `bootstrap.py` 传 `--email`
  就进礼貌池。429 时脚本会退避重试 2 次，仍失败则**降级为只有 Crossref 单源**，
  并在 `input.notes` 里写明。
- 排序键 `relevance_score`（默认）/ `cited_by_count` / `publication_date`。

---

## 什么时候**不要**检索

- 用户已经给了明确清单 → 直接下，不要"顺手帮你搜一下"
- 用户给的是 DOI 但想扩展（"这篇的参考文献也下"）→ 那是另一个动作，
  先确认再做，不要自动扩大范围
- 检索得到的候选**没有过 ★门①** → 不要下载

---

## 相关代码

| 阶段 | 文件 |
|---|---|
| 输入判定与解析 | `0路由/scripts/normalize.py` |
| 检索 | `0路由/scripts/search.py` |
| 标题补 DOI / 元信息补全 | `0路由/scripts/build_queue.py` |
| 编排 | `0路由/scripts/pipeline.py` |
