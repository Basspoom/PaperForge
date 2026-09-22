# Codex 接入（OpenAI Codex CLI / Codex App）

把 `paperforge` 接入 Codex。本文全部结论都在**本机真实安装的 Codex 26.908.9136.0**
（`~/.codex/`，配置文件 `~/.codex/config.toml`）上逐项核对过，核对方法见第 1 节。

---

## 1. 核实状态（哪些是核对过的、哪些没有）

### 1.1 已在本机核对（可直接照抄）

| 事实 | 核对到的内容 |
|---|---|
| **技能根** | **`~/.codex/skills/<name>/SKILL.md`**。本机 `~/.codex/skills\` 下实际存在 16 个技能目录（`nature-academic-search`、`nature-citation`、`nature-downloader`、`nature-literature-pipeline` …），每个目录根下就是 `SKILL.md` + `scripts/` 等资源，frontmatter 为 `name` + `description`。**这与本仓库布局完全同构** |
| **插件清单** | **`.codex-plugin/plugin.json`**（插件目录根下）。本机 `~/.codex/plugins/cache/**/.codex-plugin/plugin.json` 共 15 个真实插件在用 |
| **`plugin.json` 的 `skills` 键** | 是**字符串路径**，不是数组。真实值：`"skills": "./skills/"` |
| **`plugin.json` 的 `mcpServers` 键** | 是**字符串路径**，不是内联对象。真实值：`"mcpServers": "./.mcp.json"`（在 `codex-app-tools`、`unified-computer-use` 两个官方插件里都如此） |
| **`plugin.json` 的 `interface` 块** | 含 `displayName` / `shortDescription` / `longDescription` / `developerName` / `category` / `capabilities` / `defaultPrompt` / `brandColor` 等；`capabilities` 取值含 `"Interactive"` / `"Read"` / `"Write"` |
| **`plugin.json` 顶层键** | 实测出现过：`name`、`version`、`description`、`author`、`license`、`keywords`、`homepage`、`repository`、`skills`、`mcpServers`、`interface`、`hooks` |
| **`.mcp.json` 结构** | 顶层 `mcpServers` → `{ "<server>": { command, args, cwd, env, ... } }`。**`env` 是对象（键值对），可用**；另实测存在 `cwd`、`enabled`、`env_vars`、`startup_timeout_sec`、`tool_timeout_sec`、`default_tools_approval_mode`、`tools`、`omit_tools_from` 等可选字段 |
| **用户级 MCP 配置** | `~/.codex/config.toml` 的 **`[mcp_servers.<name>]`** 段，字段为 `command` / `args` / `startup_timeout_sec`，嵌套 `[mcp_servers.<name>.env]` 写环境变量。本机 `node_repl` 即按此注册 |
| **插件注册方式** | `~/.codex/config.toml` 的 **`[marketplaces.<名字>]`**（`source_type = "local"` + `source = '<路径>'`）+ **`[plugins."<插件名>@<marketplace 名>"]`** + **`enabled = true`** |
| **插件目录位置** | 本机注册的插件实际都在 `~/.codex/plugins/cache/<marketplace>/<plugin>/<version>/` |

### 1.2 未核实（**需按你所用版本核实**）

| 事项 | 状态 |
|---|---|
| `mcpServers` 是否**也**接受内联对象（而非只有 `"./.mcp.json"` 路径） | **未核实**。15 个真实插件里只见到字符串路径形态。本文给出的清单因此照抄字符串路径形态 |
| **符号链接 / 目录联接**是否被技能发现跟随 | **未核实**。本机 `~/.codex/skills/` 下 16 个都是真实目录（`LinkType` 为空），没有可参照的链接样本。[openai/codex PR #8801「Support symlink for skills discovery」](https://github.com/openai/codex/pull/8801) 的标题暗示这是被补上的能力，但本环境无法打开网页正文，**未逐字核对**。因此本文把「复制」列为不依赖该能力的稳妥做法 |
| `codex plugin add <name>@<marketplace>` 子命令在你版本上的确切行为 | **未核实**（本机 `codex` 未在 `PATH` 上，无法实测）。上游 `scansci-pdf` 的安装脚本用它，说明至少在某些版本可用 |
| `interface` 各键是否**必填** | **未核实**，只知道官方插件都写了。本仓库的 `.codex-plugin/plugin.json` 保留了最小合理集合 |

> **一句话结论**：`~/.codex/skills/`（用户级技能根）与 `~/.codex/config.toml` 的
> `[marketplaces]` / `[plugins]` / `[mcp_servers]` 三处，是本机核对过的真实约定；
> 「链接是否被跟随」是唯一影响做法的未知项，已用「复制」兜底。

---

## 2. 本仓库已经准备好的配置

| 文件 | 作用 | 是否入库 |
|---|---|---|
| `.codex-plugin/plugin.json` | 插件清单；`"mcpServers": "./.mcp.json"`（相对路径，可入库） | ✅ 入库 |
| `.mcp.json.template` | MCP 配置模板，用 `{{REPO}}` 占位 | ✅ 入库 |
| `.mcp.json` | MCP server 定义（由 `bootstrap.py apply` 按当前路径生成） | ❌ **不入库**（含本机绝对路径，已 gitignore） |

> **关于 `skills` 字段**：真实 Codex 插件的 `plugin.json` 里写的是
> `"skills": "./skills/"`（字符串路径）。但**本仓库没有 `skills/` 目录**——
> 本仓库的 `SKILL.md` 直接位于仓库根，与 DSH / Claude Code 的
> `<技能根>/<name>/SKILL.md` 一层布局同构。
> 因此 `.codex-plugin/plugin.json` **刻意省略了 `skills` 键**，
> 让插件只管 MCP；技能发现走下面的 B 方案（`~/.codex/skills/`）。
> 若你确实想要 A 方案一次带齐，请自行建 `skills/` 目录并把技能放进去。

生成 `.mcp.json`：

```bash
python 0路由/scripts/bootstrap.py apply --skip-install --skip-smoke
```

它会写出（去掉注释后的）下面这份内容：

```json
{
  "mcpServers": {
    "scansci-pdf": {
      "command": "<仓库>\\workspace\\.venv\\Scripts\\python.exe",
      "args": ["-m", "scansci_pdf", "run"],
      "cwd": "<仓库>",
      "env": {
        "SCANSCI_PDF_DATA_DIR": "<仓库>\\workspace\\scansci-pdf",
        "TMP": "<仓库>\\workspace\\.tmp",
        "TEMP": "<仓库>\\workspace\\.tmp",
        "PLAYWRIGHT_BROWSERS_PATH": "<仓库>\\workspace\\.browsers",
        "UV_CACHE_DIR": "<仓库>\\workspace\\.uv-cache",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      },
      "startup_timeout_sec": 120,
      "tool_timeout_sec": 1800
    }
  }
}
```

`tool_timeout_sec` 设成 1800 秒是必须的——默认超时对下载任务远远不够。

macOS / Linux 上把 `command`、`cwd` 与各路径换成 POSIX 形态（其余不变）：

```json
{
  "mcpServers": {
    "scansci-pdf": {
      "command": "/绝对路径/智能体/workspace/.venv/bin/python",
      "args": ["-m", "scansci_pdf", "run"],
      "cwd": "/绝对路径/智能体",
      "env": {
        "SCANSCI_PDF_DATA_DIR": "/绝对路径/智能体/workspace/scansci-pdf",
        "TMPDIR": "/绝对路径/智能体/workspace/.tmp",
        "PLAYWRIGHT_BROWSERS_PATH": "/绝对路径/智能体/workspace/.browsers",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### 为什么这么写

| 决定 | 原因 |
|---|---|
| 用 **venv 里的 python + `-m scansci_pdf run`**，而不是裸 `scansci-pdf` | 上游自带的 `.mcp.json` 用 `"command": "scansci-pdf"`，那要求 console script 在 `PATH` 上。本仓库刻意不依赖 `PATH` 与 venv 激活状态（见 `0路由/scripts/_common.py` 的 `scansci_pdf()` 注释）。`python -m scansci_pdf run` 默认 `--mode stdio`，直接起 MCP stdio server——已实测确认该子命令存在 |
| 写满 `env` | 本仓库默认把 `TMP`/`TEMP`/`SCANSCI_PDF_DATA_DIR`/`PLAYWRIGHT_BROWSERS_PATH` 全部收进 `workspace/`，保证可清理、不污染用户目录。**手写 MCP 配置时必须照抄**，否则浏览器内核与缓存会跑到 `%LOCALAPPDATA%` 去 |
| 加 `startup_timeout_sec: 120` | MCP server 首次 import 上游依赖较慢；官方插件用 10–3600 不等，这里取宽松值 |

---

## 3. 接入步骤

### 第 0 步（必须）：先过部署关

没有 venv，MCP server 起来也会失败；技能文本能读到也没用。

```bash
cd "<仓库绝对路径>"
python 0路由/scripts/bootstrap.py check     # 只体检，不改动
python 0路由/scripts/bootstrap.py plan      # 打印计划，等确认
python 0路由/scripts/bootstrap.py apply     # 执行
```

要求：`workspace\.venv\Scripts\python.exe` 存在，且 `workspace/state/deploy.json` 里 `ready` 为 `true`。

### A 方案（推荐）：注册为本地插件 → 一次带齐 skills + MCP

1. 在 `~/.codex/config.toml` 末尾追加（把路径换成你的实际路径）：

   ```toml
   [marketplaces.paperforge-local]
   source_type = "local"
   source = '<仓库绝对路径>'

   [plugins."paperforge@paperforge-local"]
   enabled = true
   ```

   > 这两段的字段形态来自本机 `config.toml` 里 `openai-bundled` / `ponytail` /
   > `openai-primary-runtime` 三个 marketplace 与若干 `[plugins."x@y"]` 条目的实际写法。

2. 重启 Codex（或新开会话）。
3. 若你的版本带插件管理页，刷新一下"个人 / 本地 marketplace"，应能看到 `paperforge`。

### B 方案（最直接）：只挂技能到 `~/.codex/skills/`

不碰插件系统，只让 Codex 发现技能：

```powershell
$repo = "<仓库绝对路径>"
New-Item -ItemType Directory -Force -Path "$HOME\.codex\skills" | Out-Null

# 首选：目录联接
New-Item -ItemType Junction -Path "$HOME\.codex\skills\paperforge" -Target $repo
```

**若链接不被跟随**（第 1.2 节标注的未核实项），改用复制：

```powershell
Copy-Item -Recurse -Force $repo "$HOME\.codex\skills\paperforge"
# 或者用 robocopy 排除产物目录，避免把 workspace 也拷进去：
robocopy $repo "$HOME\.codex\skills\paperforge" /E /XD workspace .git .tmp 2>$null
```

```bash
# macOS / Linux
ln -s "/path/to/智能体" "$HOME/.codex/skills/paperforge"
```

> 本仓库的 `0路由/scripts/install.ps1` / `install.sh` 会把 `~/.codex/skills` 一并列入候选技能根
> 自动处理，**一般不用手敲**；链接失败时它会打印上面这些复制命令。

### C 方案（兜底）：纯 CLI，框架无关

只要 Codex 能执行 shell，就能用，不依赖任何目录约定：

```bash
python 0路由/scripts/pipeline.py run --input "2020 年以来高被引的钙钛矿稳定性研究，要 20 篇"
python 0路由/scripts/pipeline.py run --input dois.txt
python 0路由/scripts/pipeline.py run --input refs.bib --no-search
```

### MCP 的另一种注册方式（不用插件）

直接把 server 写进 `~/.codex/config.toml`（字段形态照抄本机 `[mcp_servers.node_repl]`）：

```toml
[mcp_servers.scansci-pdf]
command = '<仓库绝对路径>\workspace\.venv\Scripts\python.exe'
args = ["-m", "scansci_pdf", "run"]
startup_timeout_sec = 120

[mcp_servers.scansci-pdf.env]
SCANSCI_PDF_DATA_DIR = '<仓库绝对路径>\workspace\scansci-pdf'
PLAYWRIGHT_BROWSERS_PATH = '<仓库绝对路径>\workspace\.browsers'
```

> 这条**绕开插件系统**，很适合 A 方案里某个约定和你版本对不上时使用。
> `[mcp_servers.*]` 的字段是本机核对过的：`node_repl` 真实使用了
> `command` / `args` / `startup_timeout_sec` / `[mcp_servers.node_repl.env]`。

---

## 4. 环境要求（务必照做）

| 约束 | 说明 |
|---|---|
| Python ≥ 3.11 | `scansci-pdf` 的硬要求；`bootstrap.py` 会用 `uv` 把 3.12 装进 `workspace/.uv-python` |
| 用**普通终端**，别用受限沙箱 | WebVPN / CARSI / EZProxy 登录、过 Cloudflare、sci-hub 竞速的浏览器通道需要**可见浏览器**；链路是 patchright → Edge/Chrome，Playwright 走 **Windows 命名管道**，受限权限下报 `WinError 5 拒绝访问` |
| pip 需要能写临时目录 | 受限环境下放宽文件权限 |
| 机构通道可选 | Elsevier API Key（最快、**无需浏览器**）> 高校 WebVPN > CARSI > EZProxy |

---

## 5. 验证方法

> **新开一个 Codex 会话，问它：「你能看到 `paperforge` 技能吗？」**

按顺序确认：

1. **技能可见**：它能复述用途（文献搜索与获取），并指出首次使用必须先跑
   `python 0路由/scripts/bootstrap.py check / plan / apply`。
   答不上来 → 回第 3 节 B 方案，检查 `~/.codex/skills/paperforge/SKILL.md` 是否成立。
2. **环境就绪**：

   ```bash
   python 0路由/scripts/doctor.py        # 环境体检（含代理自动探测）
   ```

3. **MCP 连通**（若配了）：让它列出可用工具，应出现 `scansci_pdf_*` 系列
   （上游 `scansci-pdf` 1.17.0 为 17 个工具）。
   列不出来 → 检查 `command` 绝对路径是否存在（`Test-Path` 一下），以及是否重启过。
4. **端到端**（可选，会真的下载）：

   ```bash
   python 0路由/scripts/pipeline.py run --input "10.48550/arXiv.1706.03762"
   ```

   成功时 `workspace/pdfs/10.48550_arXiv.1706.03762.pdf` 出现。
