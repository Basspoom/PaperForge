# LOCALIZATION — `1学术查询/`

本目录是 [Yuan1z0825/nature-skills](https://github.com/Yuan1z0825/nature-skills) 仓库中
`skills/nature-academic-search` 子树的**本地化（vendored）副本**：逐字复制、零源码改动，
作为 `paperforge` 技能的学术检索子能力随仓库一起分发。

因此本目录**不依赖运行时访问原仓库**，也不随之漂移——内容锚定在下面记录的 pinned commit 上。

## 1. 来源

| 项 | 值 |
|---|---|
| 上游仓库 | `https://github.com/Yuan1z0825/nature-skills` |
| 子树路径 | `skills/nature-academic-search` |
| 许可 | Apache License 2.0（上游仓库根 `LICENSE`） |
| pinned commit | `9cecfef6ac683fa59d7d15d2e22f98fa71dacaf5` |
| commit 日期 | `2026-09-19T02:39:36Z` |
| 本地化目标目录 | `1学术查询/` |
| 上游组件版本 | `name: nature-academic-search` / `version: 2.0.0`（见 `manifest.yaml`） |
| 归属记录 | 仓库根 `NOTICE`、`PROVENANCE.json` |

## 2. 本地化方式

| 约定 | 说明 |
|---|---|
| 复制粒度 | 子树级：`skills/nature-academic-search` 下的**全部内容**直接放进本目录 |
| 源码改动 | **零**。未修改任何上游文件的内容，包括路径、导入、默认配置 |
| 新增文件 | 仅 `LICENSE`（从上游仓库根复制而来）与本文档 `LOCALIZATION.md` |
| 内部相对链接 | **仍然有效**，因为子树根 = 本目录根，目录层级没有被压平 |

关于相对链接为何有效：上游内部的交叉引用是按子树内的相对层级写的，
例如 `static/core/routing-and-ops.md` 引用 `../../references/source-tiers.md`、
`static/core/tools.md` 引用 `../../references/dedup-engine.md` 与 `../../scripts/format-converter.py`。
本目录保持 `<本目录>/static/core/` 与 `<本目录>/references/`、`<本目录>/scripts/` 的原有相对位置，
所以 `../../references/...` 这类链接无需重写即可解析。

> 结论：读取本目录内容时按**上游原文**理解即可，不存在"本地化后语义已变"的地方。

## 3. 目录清单

| 路径 | 作用 |
|---|---|
| `SKILL.md` | 上游技能入口：动态/静态分层说明与加载策略 |
| `manifest.yaml` | 声明式清单：`always_load` 常驻模块、`workflow` 轴（6 条 workflow 映射）、`references.on_demand` 按需模块 |
| `agents/openai.yaml` | OpenAI 侧 agent 配置片段 |
| `config/mcp-snippet.json` | MCP 客户端配置片段 |
| `config/settings-snippet.json` | 设置片段 |
| `config/triggers-academic-search.toml` | 触发词配置 |
| `install.sh` | 上游安装脚本（本仓库不使用，保留原文） |
| `LICENSE` | Apache-2.0 许可原文（新增） |
| `README.md` / `README_EN.md` | 上游双语说明 |
| `mcp-server/` | MCP 服务器实现：`academic_search_server.py`、`sources/`（crossref / pubmed / arxiv / scopus / sciencedirect / elsevier_common）、`utils/`、`tests/`、`config.toml`、`requirements.txt`、本目录 `README.md` |
| `references/` | 共享模块：`dedup-engine.md`（去重）、`citation-parser.md`（引文解析）、`search-strategy.md`（查询构造与排序）、`ris-bibtex-format.md`（格式字段映射）、`source-tiers.md`（T1/T2/T3 源分级与回退），以及示例记录 `pubmed-28344011.bib` / `.ris` / `.nbib` |
| `references/workflows/` | 6 条 workflow：`wf1-multi-source-search.md`、`wf2-citation-verification.md`、`wf3-mesh-strategy.md`、`wf4-citation-file-mgmt.md`、`wf5-reference-mgmt.md`、`wf6-strict-other-citation-impact-audit.md` |
| `scripts/` | 无 MCP 兜底脚本：`academic_search.py`（OpenAlex 检索）、`format-converter.py`（CrossRef + PubMed + arXiv 导出）、`converters.py`、`preflight.py`（端点连通性预检） |
| `static/core/` | 常驻核心模块：`tools.md`（MCP 工具表与共享模块索引）、`routing-and-ops.md`（源路由、环境准备、错误处理、限制） |

### 能力概览

- **6 条 workflow**：`multi-source-search`、`citation-verification`、`mesh-strategy`、
  `citation-file-mgmt`、`reference-mgmt`、`strict-other-citation-impact-audit`。
  可按需组合（例如先检索再导出）。
- **MCP 工具**：核心检索（`search_papers`、`get_paper_by_id`、`get_citation`、`lookup_mesh`）、
  Scopus / ScienceDirect 系列、扩展检索与 PubMed 工具。完整表见 `static/core/tools.md`。
- **可选 API key**：`SEMANTIC_SCHOLAR_API_KEY`、`NCBI_API_KEY`；Elsevier 走本地
  pybliometrics 配置（通常 `~/.config/pybliometrics.cfg`）。三者都不是必需。

## 4. 没有 MCP 时怎么用

MCP 服务器未挂载（纯 CLI、技能自动发现、CI 场景）时，检索链路仍可用：
两个**纯标准库**脚本直接打公开 HTTP API，不引入额外依赖。

| 脚本 | 覆盖 | 源 |
|---|---|---|
| `scripts/academic_search.py` | 发现（关键词/作者检索，相关性重排、作者消歧） | OpenAlex（免费、无需 key） |
| `scripts/format-converter.py` | 导出 `.ris` / `.bib` / `.enw` / `.nbib` | CrossRef + PubMed + arXiv |

命令示例（取自 `static/core/routing-and-ops.md`）：

```bash
# 发现，然后导出选中的条目
python scripts/academic_search.py "graph neural network potentials" --limit 10 --sort cited_by_count --mailto you@example.com
python scripts/format-converter.py --doi 10.1103/physrevlett.120.143001 --format ris
```

几点运行时约定：

- OpenAlex 是共享资源池，请传 `--mailto` 或设置 `OPENALEX_MAILTO` / `CROSSREF_MAILTO` 表明身份。
- 两个脚本按源独立上报失败（HTTP 429 / 超时 / 网络）到 stderr 并以非零码退出，
  调用方应把每个源当作独立单元处理并继续尝试其它工具。
- 封顶能力差异：兜底的**发现**覆盖同样走 OpenAlex 的 T1→T2→T3 源；
  有 MCP 时仍优先走 MCP（可逐源选工具，且有 Semantic Scholar / Scopus provider）。
- 批量网络操作前可先跑预检：

```bash
python scripts/preflight.py
```

## 5. 上游更新流程

1. 取上游新 commit：

   ```bash
   git clone https://github.com/Yuan1z0825/nature-skills.git /tmp/nature-skills
   git -C /tmp/nature-skills checkout <new-commit>
   ```

2. 记录新 commit 的 hash 与日期（`git -C /tmp/nature-skills show -s --format=%cI <new-commit>`）。

3. **覆盖**本目录内容（保留本目录新增的 `LICENSE` 与 `LOCALIZATION.md`）：

   ```bash
   rsync -a --delete /tmp/nature-skills/skills/nature-academic-search/ 1学术查询/
   ```

   若上游子树新增了生成物或缓存目录，照旧排除（`__pycache__/`、`*.pyc`）。

4. 复核相对链接：全文搜一遍 `../../`，确认 `references/` 与 `scripts/` 的相对位置未被上游改动。

5. 同步元数据（三处必须一致）：
   - `PROVENANCE.json` → `sources[0].pinned_commit` 与 `commit_date`
   - `NOTICE` → 若归属表述或改动说明有变化
   - 本文档 → 第 1 节来源表与第 3 节目录清单

6. 跑一次兜底脚本冒烟（上一节两条命令），确认检索与导出链路未被上游变更破坏。

## 6. 已知限制

以下限制引自上游文档（`static/core/routing-and-ops.md`），本地化未做任何缓解：

- **Google Scholar 与 Semantic Scholar 是抓取而非 API** —— 结果可能波动，稳定性不由本仓库保证。
- **中文文献不被 CrossRef 或 PubMed 索引** —— CNKI / 万方 属 T3，需人工检索（见 `source-tiers.md` 的路由表）。
- **引用计数有延迟** —— CrossRef 按月更新，引用敏感场景应优先 Semantic Scholar。
- **MCP 工具不可用**时按上游约定降级：报告具体失败并继续用剩余工具；
  整个 MCP 服务器缺失时切到本文第 4 节的兜底脚本。
- **脚本连续失败 2 次**时，退回"从 MCP 已取回元数据手工生成"。
