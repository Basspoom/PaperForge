# 契约：输入、队列、输出

本文件是**唯一的事实来源**。`0路由/scripts/` 下的代码、`SKILL.md`、`README.md`
都按这里写的字段与取值行事；改动契约必须同步改代码。

---

## 1. 输入契约

### 1.1 两种输入形态

| 形态 | 说明 | 归一化后的去向 |
|---|---|---|
| **检索需求** | 自然语言描述的主题/关键词/作者/时间范围 | 走 P1 学术查询 |
| **待下载文献清单** | 已能逐条确定标识符 | 跳过检索，直接进 P3 |

清单可以是下面任意一种（也可以混排）：

| 形式 | 例子 | 解析方式 |
|---|---|---|
| DOI 清单 | `10.1038/nature12373` | 逐行 / 全文扫描 |
| DOI URL | `https://doi.org/10.1038/nature12373` | 剥前缀 |
| arXiv 号 | `1706.03762`、`arXiv:1706.03762`、`https://arxiv.org/abs/1706.03762` | 归一化 |
| arXiv DOI | `10.48550/arXiv.1706.03762` | 归一化为同一个 arXiv 身份 |
| BibTeX | `@article{...}` | 字段解析 |
| RIS | `TY  - JOUR` … `ER  -` | 标签解析 |
| EndNote / MEDLINE | `PMID- `、`DO  - ` | 标签解析 |
| CSV / XLSX | 含 DOI 或标题列 | 表头识别（中英文表头都认） |
| APA / 自由文本 / 聊天记录粘贴 | 任意含 DOI 的文字 | 全文扫描 |
| 已知标题但无 DOI | — | 走 Crossref 标题检索补 DOI（相似度阈值 0.75，不够就判 `bad_identifier`） |

### 1.2 标识符归一化规则

这是**必须统一**的地方——同一篇文献的多种写法绝不能在队列里存活成两条：

| 输入 | 归一的身份 | 规范文件名主干 |
|---|---|---|
| `10.48550/arXiv.1706.03762` | `arxiv:1706.03762` | `10.48550_arXiv.1706.03762` |
| `1706.03762` | `arxiv:1706.03762` | `10.48550_arXiv.1706.03762` |
| `arXiv:1706.03762` | `arxiv:1706.03762` | `10.48550_arXiv.1706.03762` |
| `https://doi.org/10.1038/nature12373` | `doi:10.1038/nature12373` | `10.1038_nature12373` |

去重键由 `_common.dedup_key()` 产出，P0 归一化、P1 检索合并、P3 队列构建
三个阶段**共用同一个函数**——这是防止重复条目的结构性保证。

---

## 2. 队列契约

队列是流程的中枢文件，默认位于 `workspace/state/queue.json`。

```jsonc
{
  "schema_version": 1,
  "skill_version": "0.1.0",
  "created_at": "2026-09-21T10:51:43Z",
  "updated_at": "2026-09-21T10:51:43Z",

  // 阶段机：needs_search → awaiting_selection → ready_for_download
  "stage": "ready_for_download",

  "input": {
    "kind": "query | id-list | bibtex | ris | medline | csv | xlsx | unknown",
    "query": "原始检索需求（kind=query 时）",
    "year_from": 2020, "year_to": null,
    "sort": "relevance_score | cited_by_count | publication_date",
    "sources": ["openalex", "crossref"],
    "notes": ["各通道的返回条数与被限速情况"]
  },

  "selection": { "selected": 3, "ready": 3, "at": "..." },

  "items": [ /* 见下 */ ]
}
```

### 2.1 条目字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | str | 规范化标识符（DOI 或 arXiv 号） |
| `kind` | str | `doi` / `arxiv` / `unknown` |
| `title` | str | 标题（P3 会补全） |
| `authors` | str[] | 作者列表 |
| `year` | str | 年份 |
| `journal` | str | 期刊/来源 |
| `abstract` | str | 摘要（≤500 字） |
| `cited_by_count` | int | 被引数 |
| `is_oa` | bool | 是否开放获取 |
| `source` | str | 元信息来自哪里（`crossref` / `openalex` / `crossref+arxiv-meta` …） |
| `origin` | str | `direct`（用户直接给）/ `search`（检索得到）/ `manual`（人工补）/ `recovered`（磁盘上捡到的） |
| `selected` | bool | ★门① 的用户选择 |
| `status` | str | `pending` / `success` / `failed` / `skipped` |
| `file` | str | PDF 绝对路径（成功时） |
| `reason` | str | 失败原因分类（见 §4），成功时为空 |
| `detail` | str | 原始错误信息 / 文件大小等可读说明 |
| `channel` | str | 实际下载通道（上游回报，如 `PLOSDirect` / `arXiv` / `Sci-Hub(https://sci-hub.vg)`） |

**不变量**

- `status == "success"` ⟺ `file` 非空且该文件通过 PDF 校验（`%PDF` 头 + ≥10 KB）。
- `status == "failed"` ⟹ `reason` ∈ §4 的取值集合。
- `status == "skipped"` 目前只用于 `reason == "duplicate"`。

---

## 3. 输出契约

默认全部落在 `workspace/`（路径可在 `bootstrap.py` 中改）：

```
workspace/
├── pdfs/                       # ★ 交付物：所有 PDF，DOI 命名，单一目录
│   └── 10.1038_nature12373.pdf
├── pdf_alternates/             # 同一 DOI 的多余副本（上游各车道的中间文件）
├── metadata.csv                # 元信息表（UTF-8 BOM，Excel 直接打开不乱码）
├── metadata.xlsx               # 同上，带列宽与冻结首行
├── metadata.md                 # 同上，人读版
├── doi_index.json              # DOI → 文件 / 通道 / 标题 / 年份 / 时间戳
├── failures.md                 # 只列失败项 + 归因分布 + 重试建议
├── logs/
│   ├── download-<ts>.jsonl     # 逐条结构化日志
│   ├── download-<ts>.md        # 逐条人读日志
│   ├── finalize-<ts>.jsonl
│   └── finalize-<ts>.md
├── state/
│   ├── queue.json              # 队列（中枢）
│   ├── deploy.json             # 部署状态
│   ├── doctor.json             # 最近一次体检报告
│   ├── config.json             # 本 skill 自己的状态（策略档位等）
│   └── download_queue.txt      # 传给上游的标识符清单
└── scansci-pdf/                # 上游自己的数据目录（config.json / cache / cookies）
```

### 3.1 默认布局

默认产物落在 skill 自己的 `workspace/` 下：

### 3.2 自定义交付目录（`--out-dir`）

默认产物落在 skill 自己的 `workspace/` 下。指定 `--out-dir <DIR>` 后，
**交付物**整体搬过去，**任务状态**仍留在 `workspace/`（状态是技能的运行记忆，
不是交付物）：

```
<DIR>/
├── *.pdf                     ★ 交付物：所有 PDF，DOI 命名，单一目录
├── metadata.csv|.xlsx|.md    ★ 元信息表
├── failures.md               ★ 失败清单与重试建议（反映最近一次运行）
├── failures-<时间戳>.md       ★ 有失败项时额外留的审计快照（不会被后续轮次覆盖）
├── doi_index.json            ★ 本技能的索引：DOI → 文件/通道/标题/年份
├── pdf_alternates/           同一 DOI 的多余副本
├── logs/                     ★ 运行日志（.jsonl + .md）
└── ── 以下由上游 scansci-pdf 写入，不是本技能的契约产物 ──
    ├── .doi_index.json       上游自己的下载缓存索引（**注意开头有个点**）
    ├── batch_results.json    上游逐车道尝试明细
    ├── download_results.json 上游规范化结果（带 error_type / reason）
    ├── retry.txt             上游建议重试的标识符
    ├── .browser_runs/        上游浏览器通道的运行记录
    └── .publisher_runs/      上游按出版商分桶的执行记录
```

⚠️ **两个 `doi_index` 只差一个点、内容形态完全不同**，别混用：

| 文件 | 结构 | 用途 |
|---|---|---|
| `doi_index.json` | `{schema_version, generated_at, pdf_dir, count, entries:{doi:{file,path,channel,title,year,ts}}}` | 本技能产出，供你程序化读取 |
| `.doi_index.json` | `{doi: {...}}` 顶层直接就是 DOI | 上游缓存索引，**删除它会导致已下载的文献被重下** |

上面标 "非契约产物" 的几个文件**可以安全删除**（除了 `.doi_index.json`，
删它会让上游丢掉下载缓存、重复下载），删掉不影响本技能的产出。

### 3.3 多轮运行的语义

**每次 `run --input ...` 都会整体替换队列**（队列 = 本次任务，不是累计成果）。
由此产生两条必须知道的规则：

| 规则 | 说明 |
|---|---|
| 元信息表只含**本次队列中被选中**的条目 | 门① 没选中的候选、以及磁盘上属于上一轮的 PDF，都**不进**元信息表；后者只进 `doi_index.json`，并在 `metadata.md` 页脚注明数量 |
| `failures.md` 只反映**最近一次**运行 | 有失败项的轮次会额外留一份 `failures-<时间戳>.md` |

要一份覆盖多轮成果的自洽交付物，用**并集清单**再跑一轮：

```bash
python 0路由/scripts/pipeline.py run --input union_ids.txt --select-file union_ids.txt --out-dir <DIR>
```

`--select-file` 的语义是**以该文件为准**：先清空原有选择，再只保留文件里列出的；
**文件里出现、而队列里没有的标识符会被追加**为手工条目（`origin=manual`）并自动补全元信息。

### 3.4 元信息表列

列顺序固定（`finalize.py` 的 `COLUMNS`）：

| 列 | 表头 | 说明 |
|---|---|---|
| 1 | 序号 | 1-based |
| 2 | DOI/标识符 | 规范化后的标识符 |
| 3 | 标题 | |
| 4 | 作者 | `; ` 分隔 |
| 5 | 年份 | |
| 6 | 期刊 | |
| 7 | 被引 | 无数据留空 |
| 8 | 状态 | `success` / `failed` / `skipped` |
| 9 | 下载通道 | 上游回报的来源 |
| 10 | 文件 | **文件名**，不是全路径 |
| 11 | 失败原因 | 中文描述（见 §4），成功时留空 |
| 12 | 详情 | 原始错误 / 文件大小，≤300 字 |

### 3.5 PDF 命名规则（硬约束）

1. **PDF 一律用 DOI 命名**：`/` 与非法字符替换为 `_`。
   `10.1038/nature12373` → `10.1038_nature12373.pdf`
2. **arXiv 号单独进队时补上 DataCite DOI 前缀**：
   `1706.03762` → `10.48550_arXiv.1706.03762.pdf`
3. **所有 PDF 放在同一个目录**，不按期刊/年份分子目录。
4. 上游会用来源前缀/后缀命名（`unpaywall_…`、`…_Sci-Hub_scihub_sci-hub_vg`）
   或把 arXiv DOI 改写成裸号落盘；这些都会在 P6 被**反推还原并改名到规范名**。
5. 同一 DOI 存在多个副本时，**保留最完整的一份**（先看是否为有效 PDF，再比大小）
   作为规范文件，其余移入 `pdf_alternates/`。

---

## 4. 失败原因分类

`reason` 取值封闭集合（`_common.REASONS`）。归因规则在 `download.py::REASON_RULES`，
**顺序即优先级**（越具体的越靠前）。

| `reason` | 中文 | 典型触发 |
|---|---|---|
| `ip_blocked` | 出版商封禁出口 IP | `IP Address Blocked`、持续 403/429 |
| `cf_challenge` | 被 Cloudflare/CAPTCHA 拦截 | `cloudflare`、`turnstile`、`just a moment` |
| `bad_identifier` | DOI/arXiv 号无效或无法解析 | `invalid doi`、标题补 DOI 相似度不足 |
| `paywalled_no_access` | 有付费墙且当前无可用机构通道 | `NOT_ENTITLED`、`requires institutional` |
| `network` | 网络层失败 | 超时、DNS、TLS、代理 |
| `not_found` | 各源都没有可下载副本 | `all sources failed`、`no pdf`、404 |
| `file_missing` | 声称成功但磁盘上无有效 PDF | 文件缺失 / 过小 / 不是 PDF |
| `duplicate` | 与队列中已有条目重复 | 去重命中 |
| `unsupported` | 输入类型或来源当前不支持 | — |
| `unknown` | 未归类 | 保留原始错误在 `detail` |

每条建议见 `failures.md`（由 `finalize.RETRY_HINT` 生成）。

---

## 5. 日志契约

### 5.1 JSONL（机读）

每行一个 JSON 对象：

```json
{"ts": "2026-09-21T10:51:43Z", "stage": "download", "event": "item",
 "id": "10.1038/nature12373", "status": "success", "reason": "",
 "detail": "922 KB", "channel": "CrossrefPage", "file": "…/10.1038_nature12373.pdf"}
```

`event` 取值：`start`（一次运行开始）、`item`（单条结果）。

### 5.2 Markdown（人读）

同一批记录渲染成表格，列：时间 / 事件 / 标识符 / 状态 / 原因 / 详情。

---

## 6. 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功（`pipeline.py run` 在检索/队列/下载/产出全部成功时） |
| 1 | 有失败项，或体检未通过，或部署关未过 |

`download.py` / `finalize.py` 单独跑时，只要**成功数 > 0** 就返回 0；
`finalize.py` 在**存在失败项**时返回 1，便于脚本判断。
