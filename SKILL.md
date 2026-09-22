---
name: paperforge
description: "Agent-native literature discovery and authorized PDF acquisition: route natural-language requests or citation lists through multi-source search, citation verification, human approval, and traceable PDF/metadata output."
whenToUse: "用户要检索文献、批量下载论文、获取全文 PDF、拉补充材料、把文献清单变成实际文件、或需要带元信息和成功失败日志的文献获取任务时使用。不用于论文写作、翻译、图表绘制或引文格式转换。"
---

# PaperForge · 文献搜索与获取智能体

一句话能力：**给检索需求或文献清单，产出 DOI 命名的 PDF + 元信息表 + 成功失败日志。**
V2 的结构性变化在**下载层**：保留双引擎，但默认只启用开放获取、出版社和机构授权来源。

## 与第一代的差异（先读这一节）

| | 第一代 | 第二代 |
|---|---|---|
| 下载层 | 单引擎：scansci-pdf 工程化 | **双引擎**：授权工程化默认；实验性直连需显式开启 |
| 补充材料 | 支持（工程化引擎的 `--si`） | 支持，并明确"只有工程化引擎能做" |
| 全文速度 | 20–200 秒/篇 | 直连命中 3–10 秒/篇；未命中回退后与一代同量级 |
| 反爬处理 | 无（全靠上游） | 镜像轮换 + 退避重试 + **连续失败熔断** |
| 镜像列表 | 上游默认（多为已失效域名） | 实测可用的 `.box/.su/.ru/.red` |

**为什么不是"直连替代工程化"**：实测（30 篇对照，见 [docs/COMPARISON.md](docs/COMPARISON.md)）
实验性直连在连续批量请求下可能被来源站点拦截，也可能不符合用户的授权范围。
所以它默认关闭；PaperForge 的默认路径是**先走授权来源，失败就记录原因并给出下一步建议**。

## 工作链路

```
输入
 ├─ ① 自然语言检索需求 ─┐
 └─ ② 待下载文献清单 ───┤
                        ▼
  P0 归一化 ── 能否直接确定 DOI / arXiv？ ──是──┐
        │否                                      │
        ▼                                        │
  P1 学术检索（1学术查询）                        │
        ▼                                        │
  P2 ★门① 用户确认文献列表                        │
        ▼                                        │
  P3 队列构建（verify / resolve OA / 分桶）  ◄────┘
        ▼
  P4 ★门② 下载策略确认（含"要不要补充材料"）
        ▼
  P5 下载（双引擎，见下）
        ▼
  P6 后处理（DOI 命名 / 校验 / 去重）
        ▼
  P7 产出（元信息表 / DOI→文件映射 / 成功失败日志）
```

唯一入口：

```
python 0路由/scripts/pipeline.py run --input <需求或清单文件>
```

## 两个子能力：一个是「skill」，一个是「流水线」

| 目录 | 角色 | 怎么用 |
|---|---|---|
| [1学术查询/](1学术查询/SKILL.md) | **模型面向的 skill**（nature-academic-search） | **加载它、按它的 workflow 执行。** 它给的是检索方法论与 MCP 工具。**由模型按它的指导去检索**，而不是把这套逻辑改写成我们自己的脚本。 |
| [2工程化下载/](2工程化下载/SKILL.md) | **确定性流水线**（scansci-pdf） | 给一份标识符清单，机械地取 PDF、命名、归因、产出表。这层不需要判断，所以脚本化是对的。 |

**判断归模型，执行归流水线。** 接缝就是 `--select-file`。

## P5 下载层：双引擎怎么分工

```
                    ┌─────────────────────────────────────────┐
   每条 DOI ──────► │ P5a 授权来源工程化下载（默认）           │
                    │  · 镜像轮换 .box/.su/.ru/.red            │
                    │  · 遇 altcha 反爬 → 换镜像 + 退避重试     │
                    │  · 连续 3 篇全被拦 → 熔断，本次不再试      │
                    └───────────────┬─────────────────────────┘
                          成功 ◄────┤├────► 失败 / 熔断
                            │                   │
                       该条结束                 ▼
                    ┌─────────────────────────────────────────┐
                    │ P5b scansci-pdf 工程化引擎               │  20–200 秒
                    │  · OA 直链 / 预印本 / 出版商 / 灰色源竞速 │
                    │  · 机构通道（需登录）                     │
                    │  · 单篇 get 兜底（竞速"迟到的成功"）      │
                    └───────────────┬─────────────────────────┘
                                    ▼
                    ┌─────────────────────────────────────────┐
                    │ P5c 补充材料（可选，--supplement）        │  只有这里能做
                    └─────────────────────────────────────────┘
```

**补充材料的分支规则**——这是第二代最需要用户参与的一个判断：

| 用户需求 | 全文 | 补充材料 |
|---|---|---|
| 只要全文 PDF | 先直连，失败回退工程化 | 不做 |
| 要补充材料 | 先直连（快），失败回退工程化 | **只能**由工程化引擎做（`--si`） |

补充材料默认只走授权的工程化引擎；实验性直连不参与补充材料路由。
打开 `--supplement` 会明显变慢——这不是缺陷，是能力边界。

策略全部由 [0路由/downloads.json](0路由/downloads.json) 控制，改配置不用改代码。

## 两个必须停下来问用户的门

| 门 | 位置 | 问什么 |
|---|---|---|
| ★门① | P2，检索之后、构建队列之前 | 呈现候选文献表，让用户勾选/裁剪/补 DOI。**没有用户确认就不要批量下载。** |
| ★门② | P4，下载之前 | 确认下载顺序（直连优先 / 纯工程化）、**要不要补充材料**、灰色源是否放行、并发与延迟 |

## 输入契约

| 输入形式 | 例子 | 处理 |
|---|---|---|
| 自然语言检索需求 | "2020 年以来高被引的钙钛矿稳定性研究，要 20 篇" | P0 → P1 检索 |
| DOI 清单（每行一个 / txt / csv） | `10.1038/nature12373` | P0 直达 |
| arXiv ID 清单 | `2401.12345`、`arXiv:2401.12345` | P0 直达 |
| 引文清单 | BibTeX / RIS / APA / EndNote `.nbib` | P0 解析出 DOI → 直达；缺 DOI 的走 P1 补全 |
| 表格 | `.csv` / `.xlsx`（含 DOI 或标题列） | 同上 |

## 输出契约

```
workspace/
├── pdfs/                     # 所有 PDF，DOI 命名：10.1038_nature12373.pdf
├── metadata.csv              # 元信息表（含 status / file / source / reason）
├── metadata.xlsx
├── metadata.md
├── doi_index.json            # DOI → 文件名 / 来源 / 策略 / 时间戳
├── logs/run-<ts>.jsonl       # 逐条日志
├── logs/run-<ts>.md
└── failures.md               # 只列失败项 + 归因 + 重试建议
```

`channel` 字段写明这篇走的链路：`scihub:https://sci-hub.box` 或平台名
（`Sci-Hub(...)` / `oa_url` / `CORE` / …），所以"快路径命中率"可统计。

## 硬性约束

- **PDF 一律用 DOI 命名**：`/` 和非法字符替换为 `_`。
- **所有 PDF 放在同一个目录**（`workspace/pdfs/`），不按期刊/年份分子目录。
- **落盘前校验 `%PDF` 文件头**：直连拿到的可能是 HTML 错误页，不能当成功。
- **每条结果都必须有归因**：成功写来源（含链路），失败写原因分类 + 原始错误。
- **密钥不入库**：API key、cookie 只写本地配置与 `workspace/state/`。
- **批量下载前必须过门①**；用户在同一轮已明确给出清单时视为已确认。

## 常用命令

```bash
# 端到端（停在门①）
python 0路由/scripts/pipeline.py run --input "钙钛矿稳定性 高被引 20 篇"

# 只有清单：确认全部并一路跑完
python 0路由/scripts/pipeline.py run --input dois.txt --all

# 要补充材料（走工程化引擎，明显变慢）
python 0路由/scripts/pipeline.py resume --all --supplement

# 只走直连、不回退（对照测速用）
python 0路由/scripts/download.py --scihub-only

# 跳过直连，纯工程化
python 0路由/scripts/download.py --no-scihub
```

## 排障：四个已经踩过的坑

1. **"venv 解释器不可执行"** — 本机沙箱/ACL 会拒绝执行 `workspace/.venv` 里的
   `python.exe`。V2 按设计**不建 venv**：用系统解释器 + `.pylib` 挂载依赖，并让
   `_common.venv_python()` 做可执行性探测 + 自动回退。看到
   `[WARN] venv 解释器不可执行` 是正常的，不是故障。
2. **直连批量时后段全失败** — 那是 altcha 反爬整段封禁，不是脚本坏了。熔断生效后
   会自动回退工程化；封禁是临时的，隔一段时间再跑直连又会恢复
   （实测：连续批量后 0/6，约一小时后重新探测恢复为命中）。
3. **工程化引擎报 `patchright not installed`** — 浏览器后端缺失时，Nature/Cell 等
   需要浏览器的通道会失败（`FAIL NatureBrowser: unknown` /
   `No module named 'greenlet._greenlet'`，因为 greenlet 的 C 扩展与 Python 3.10 不匹配）。
   纯 HTTP 通道（OA/Unpaywall/CORE/OpenAlexOA/CrossrefPage/Sci-Hub/SemanticScholar）
   不受影响。补装见 [2工程化下载/SKILL.md](2工程化下载/SKILL.md)。
4. **别"顺手优化"工程化引擎的参数** — 实测关掉 Tor、改成 `--scihub` racing 会把
   成功率从 73% 拉到 53%、每篇耗时从 16.5s 拉到 29.4s（原因见
   [docs/COMPARISON.md](docs/COMPARISON.md)）。V2 相对第一代只改了镜像列表。

## 合规与使用边界

下载通路中包含 Sci-Hub / LibGen 类灰色源，其可用性取决于**所在司法辖区、
机构订阅与出版商条款**。本 skill 默认策略是能力最大化，仅用于本地能力验证与
授权范围内的使用。用户必须自己有权限获取所下载的内容；本工具不授予任何访问权。
详见 [0路由/policy.md](0路由/policy.md)。
