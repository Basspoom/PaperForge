# 跨 Agent 框架接入说明

本目录说明如何把 `paperforge`（本仓库）接入不同的 Agent 框架。

**一句话总纲：主干是 CLI，任何能执行 shell 的 Agent 都能用；MCP 只是可选增强层。**

也就是说：即使某个框架的"技能目录"或"MCP 配置"约定你没对上，只要有办法让它执行
`python 0路由/scripts/pipeline.py run --input <需求或清单>`，本技能就是可用的。

---

## 1. 框架对照表

| 框架 | 接入方式 | 是否需要 MCP | 是否需要重启 | 说明 |
|---|---|---|---|---|
| **DSH**（DeepSeek Harness） | 技能根挂载：`<技能根>/paperforge/SKILL.md` | 不必需 | 通常需要新开会话 | **实测可用**：`~/.dsh/skills/paperforge` 建成目录联接后，技能立刻出现在本会话的技能列表中 |
| **Codex**（Codex CLI / Codex App） | 用户级技能根 `~/.codex/skills/<name>/SKILL.md`；或插件 `.codex-plugin/plugin.json` + `skills/` + `.mcp.json` | 可选（配了多 17 个 MCP 工具） | 需要（注册插件 / 改 MCP 后） | 技能根与插件清单、`config.toml` 的 `[marketplaces]` / `[plugins]` / `[mcp_servers]` 均在实机 Codex 上核对过；**唯一未核实项**是"链接是否被跟随"。见 [codex.md](codex.md) |
| **Claude Code** | 项目级 `.claude/skills/<name>/SKILL.md`（推荐）；MCP 用 `claude mcp add` 或 `.mcp.json` | 可选 | 需要（改 MCP 后） | `.claude/skills/` 约定来自上游 `scansci-pdf` 的明确表述；`claude mcp add` 参数形态**未核实**。见 [claude-code.md](claude-code.md) |
| **opencode** | 技能目录 + `opencode.json` 的 `mcp` 段 | 可选 | 需要（改配置后） | 官方确有 skills / mcp-servers / config 文档，但**本环境读不到正文**，故目录名与字段格式均标注未核实。见 [opencode.md](opencode.md) |
| **WorkBuddy** | 未核实 | 未核实 | 未核实 | **未找到可信的接入规范正文**。已给纯 CLI / 上传技能包 / Claude-Code 兼容布局三条兜底路线。见 [workbuddy.md](workbuddy.md) |

> 表中标"可选"的 MCP，指的是把上游 `scansci-pdf` 的 MCP server 一并注册。
> 不注册也完全可用——本仓库的胶水代码本来就是通过
> `python -m scansci_pdf <子命令>` 调上游的（见 `0路由/scripts/_common.py` 的 `scansci_pdf()`）。

> **文档里的路径占位符**：`<仓库绝对路径>` 指本仓库被克隆到的绝对路径
> （即含 `SKILL.md`、`0路由/`、`1学术查询/`、`2工程化下载/` 的那个目录）。
> 各 adapter 文档里的 MCP 配置示例都用它做占位；实际配置**不要手抄**——
> 跑 `python 0路由/scripts/bootstrap.py apply` 会按当前路径自动生成
> 仓库根的 `.mcp.json`（该文件含绝对路径，已 gitignore，不入库）。

## 2. 所有框架共用的前置步骤

无论接哪个框架，**技能文本能被 Agent 看到**只是第一步，**环境必须真的能跑**是第二步。
后者由部署关负责，且与框架无关：

```bash
# 1) 注册到技能根（本目录各 adapter 文档里的具体做法）
# 2) 过部署关（与框架无关，所有框架都跑这一段）
python 0路由/scripts/bootstrap.py check     # 只体检，不改动任何东西
python 0路由/scripts/bootstrap.py plan      # 打印计划，等确认
python 0路由/scripts/bootstrap.py apply     # 执行
```

部署关覆盖：Python 3.11+ 运行环境 → `scansci-pdf` → 目录与策略 → API key →
机构通道（Elsevier API / 高校 WebVPN）→ 网络与代理 → **抄通性验收（真下 1 篇 OA）**。

通过后 `workspace/state/deploy.json` 里 `ready` 为 `true`，技能才允许开始检索/下载。

## 3. 技能发现要求：目录名必须是 `paperforge`

技能发现要求布局是 **`<技能根>/<name>/SKILL.md`**，其中 `<name>` 必须等于
`SKILL.md` frontmatter 里的 `name`（本仓库是 `paperforge`）。

而本仓库目录名是中文 **`智能体`**，直接挂上去**发现不了**。所以接入时通常需要在技能根下
建一个名为 `paperforge` 的链接指向本目录：

```powershell
# Windows：目录联接
New-Item -ItemType Junction -Path "$HOME\.claude\skills\paperforge" `
         -Target "<仓库绝对路径>"
```

```bash
# macOS / Linux：软链接
ln -s "/path/to/智能体" "$HOME/.claude/skills/paperforge"
```

这一步已由 [`../scripts/install.ps1`](../scripts/install.ps1) 与
[`../scripts/install.sh`](../scripts/install.sh) 自动完成，**一般不需要手敲上面的命令**。

两个脚本按顺序尝试这些技能根（**只处理已经存在的**）：
`~/.codex/skills`、`<项目根>/.dsh/skills`、`<项目根>/.agents/skills`、
`$DSH_HOME/skills`（或 `~/.dsh/skills`）、`~/.agents/skills`、`~/.claude/skills`、`~/plugins`；
也可用 `-TargetDir` / `--target-dir` 显式指定。
链接失败（权限不足）时脚本会降级成**复制目录的准确命令提示**，不中断其它目标。

> **实测记录**：在 `~/.dsh/skills/paperforge` 建成目录联接（Junction）指向本仓库后，
> 本技能立即出现在会话的技能列表中，`<技能根>/paperforge/SKILL.md` 校验通过。
> 链接创建失败时脚本的表现也已实测：打印 `robocopy` 降级命令、跳过该项、继续处理其它技能根，
> 且不在失败目标处留下任何垃圾。
>
> **注意（Windows）**：脚本文件 `install.ps1` 带 UTF-8 BOM。Windows PowerShell 5.1 会按
> ANSI/cp936 解析无 BOM 的文件，导致其中的中文注释乱码并触发语法错误 —— 加 BOM 是为了让
> `powershell -File` 与 `pwsh -File` 两种调用方式都能正常工作。

## 4. 环境约束（**所有框架都适用，这是真实踩过的坑**）

| # | 约束 | 现象 | 处理 |
|---|---|---|---|
| 1 | `scansci-pdf` 要求 **Python ≥ 3.11** | 低版本上直接装不上 | `bootstrap.py apply` 会用 `uv` 把 Python 3.12 装进 `<仓库>/workspace/.uv-python`，不污染系统 Python |
| 2 | **浏览器相关功能需要可见浏览器**（WebVPN / CARSI / EZProxy 登录、过 Cloudflare、sci-hub 竞速的浏览器通道） | 链路是 patchright → Edge / Chrome | 需要机构通道时就别用无头/受限环境 |
| 3 | Playwright 用 **Windows 命名管道**与浏览器驱动通信 | 受限沙箱/受限权限下报 **`WinError 5 拒绝访问`** | **用普通终端运行，或放宽文件权限**。这是权限问题，不是依赖问题 |
| 4 | pip 安装需要能写系统临时目录 | 受限环境下 `pip` / `ensurepip` 失败 | 放宽权限；或让 `bootstrap.py` 走它的降级路径（复制 pip 进 venv） |
| 5 | 本仓库默认把 `TMP` / `TEMP` / `SCANSCI_PDF_DATA_DIR` / `PLAYWRIGHT_BROWSERS_PATH` 等全部重定向进 `workspace/` | 保证可清理、不污染用户目录 | 见 `0路由/scripts/_common.py` 的 `child_env()`。**你手写 MCP 配置时也要照抄这些变量**，否则浏览器内核和缓存会跑到用户目录去 |
| 6 | 机构通道是**可选**的 | 没有就下不了付费墙论文，OA 仍然能下 | 按性价比：Elsevier API Key（最快，**无需浏览器**）> 高校 WebVPN > CARSI > EZProxy |

## 5. 验证方法

任何框架接入后，都用同一种方式确认：

> **新开一个会话，问它：「你能看到 `paperforge` 技能吗？」**

Agent 应当能复述出该技能的名称与用途（"文献搜索与获取"），并且能说出首次使用要先跑
`bootstrap.py`。若答不上来 → 回到本文第 3 节检查链接是否落到该框架**真正**读取的技能根。

再用一条 CLI 确认环境：

```bash
python 0路由/scripts/doctor.py        # 环境体检（含代理自动探测）
```

体检 `ok` 且 `workspace/state/deploy.json` 的 `ready` 为 `true`，接入即完成。
