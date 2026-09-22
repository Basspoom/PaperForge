# Claude Code 接入

把 `paperforge` 接入 Claude Code。Claude Code 有两条独立的路：
**技能（Skills）** 和 **MCP**。两条都推荐做，但只有技能是必需的。

---

## 1. 核实状态

### 1.1 已核实

| 事实 | 内容 | 来源 |
|---|---|---|
| Claude Code 用 `.claude/skills/` 承载技能 | 上游 `scansci-pdf` 明确写「Claude Code = `.claude/skills/` + 标准 MCP 配置」 | [`Rimagination/scansci-pdf` README.md](https://github.com/Rimagination/scansci-pdf)「插件入口」段；本地可读 `2工程化下载/vendor/scansci-pdf/README.md:71`。同仓库 `zcode-plugin/README.md:38` 再述一次 |
| 上游仓库实际在 `.claude/` 下放了技能 | `2工程化下载/vendor/scansci-pdf/.claude/skills/scansci-pdf.md` **文件真实存在** | 本地文件系统 |
| 技能是 `<name>/SKILL.md` + `name`/`description` frontmatter | 上游 `skills/scansci-pdf/SKILL.md` 即该形态；本仓库 `SKILL.md` 同构（`name: paperforge`） | 本地文件 |
| Claude 系 MCP 配置用顶层 `mcpServers` 键 | 上游 README 给出的「标准 MCP 配置（Claude Desktop / Cursor / Windsurf / Cline / Cherry Studio…）」即 `{"mcpServers": {...}}` | 上游 README.md；本地 `2工程化下载/vendor/scansci-pdf/.mcp.json` |
| `~/.claude/` 是用户级配置目录 | 本机存在 `~/.claude\`（含 `backups/`、`ide/`、`projects/`、`sessions/`）与 `~/.claude.json` | 本地文件系统实测 |

### 1.2 未核实（**需按你所用版本核实**）

| 事项 | 状态 |
|---|---|
| `claude mcp add` 的确切参数形态（`--scope user/project`、`-e KEY=VALUE`、`--` 分隔是否都支持） | **未核实**。本机没有 `claude` 可执行文件（`PATH` 上没有，`%LOCALAPPDATA%\Programs\` 与 npm 全局目录里也没有），**无法实测**。请用 `claude mcp add --help` 自行确认 |
| `.mcp.json` 中 `env` 键是否被接受 | **未核实**（结构上是通用 MCP 客户端约定；本机 Codex 的 `.mcp.json` 实测支持 `env`，Claude Code 未实测）。若不接受，把变量设成系统环境变量即可，效果相同 |
| 用户级技能根 `~/.claude/skills/` | **较可信但未亲眼见到**：本机 `~/.claude\` 下**没有** `skills\` 子目录（Claude Code 大概率是「第一次用到才创建」）。`~/.claude/` 是用户级配置目录这点已实测 |

> **不确定时的安全选择**：用**项目级**配置——`<项目根>/.claude/skills/` + `<项目根>/.mcp.json`。
> 它随项目走、不依赖用户级目录约定，歧义最小；`<项目根>/.claude/skills/` 也正是上游
> `scansci-pdf` 实际采用的位置。

---

## 2. 技能目录

技能发现要求 **`<技能根>/<name>/SKILL.md`**，其中 `<name>` 必须等于 frontmatter 的 `name`。

| 层级 | 技能根 | 可放置位置 |
|---|---|---|
| 项目级（推荐） | `<项目根>/.claude/skills/paperforge/` | 在哪个项目里用，就放到哪个项目的 `.claude/skills/` |
| 用户级 | `~/.claude/skills/paperforge/` | 全机器可用（该目录本机尚未存在，需新建） |

本仓库目录名是中文 **`智能体`**，而 `name` 是 `paperforge`，所以**必须**建一个名为
`paperforge` 的链接/副本指向本目录，否则发现不了：

```powershell
# Windows：目录联接
$repo = "<仓库绝对路径>"
New-Item -ItemType Directory -Force -Path "$HOME\.claude\skills" | Out-Null
New-Item -ItemType Junction -Path "$HOME\.claude\skills\paperforge" -Target $repo
```

```bash
# macOS / Linux：软链接
mkdir -p "$HOME/.claude/skills"
ln -s "/path/to/智能体" "$HOME/.claude/skills/paperforge"
```

```powershell
# 或直接用本仓库的幂等脚本（推荐，自动处理已存在 / 重复执行 / 权限失败）
powershell -NoProfile -ExecutionPolicy Bypass -File 0路由\scripts\install.ps1
# macOS / Linux:
bash 0路由/scripts/install.sh
```

验证布局成立：

```powershell
Test-Path "$HOME\.claude\skills\paperforge\SKILL.md"   # 应为 True
```

## 3. MCP 配置（可选增强层）

本仓库主干是 CLI；MCP 是把上游 `scansci-pdf` 的 17 个工具也暴露给 Claude Code，属增强。

**要点**：命令用 **venv 里的 python + `-m scansci_pdf run`**，并把 `_common.py`
`child_env()` 那套环境变量写进去（否则浏览器内核与缓存会跑到用户目录）。

### 3.1 方式一：`.mcp.json`（可直接粘贴）

本仓库根目录**已经放好** `<仓库>\.mcp.json`，直接可用。项目级用法是在项目根再放一份，
或把下面内容整段粘进去：

```json
{
  "mcpServers": {
    "scansci-pdf": {
      "command": "<仓库绝对路径>\\workspace\\.venv\\Scripts\\python.exe",
      "args": ["-m", "scansci_pdf", "run"],
      "cwd": "<仓库绝对路径>",
      "env": {
        "SCANSCI_PDF_DATA_DIR": "<仓库绝对路径>\\workspace\\scansci-pdf",
        "TMP": "<仓库绝对路径>\\workspace\\.tmp",
        "TEMP": "<仓库绝对路径>\\workspace\\.tmp",
        "PLAYWRIGHT_BROWSERS_PATH": "<仓库绝对路径>\\workspace\\.browsers",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

macOS / Linux 版：

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

> **为什么不用裸 `scansci-pdf`**：上游自带的 `.mcp.json` 用 `"command": "scansci-pdf"`，
> 那要求 console script 在 `PATH` 上。本仓库刻意不依赖 `PATH` 与 venv 激活状态，
> 统一走 `python -m scansci_pdf`（见 `0路由/scripts/_common.py` 的 `scansci_pdf()` 注释）。
> `python -m scansci_pdf run` 默认 `--mode stdio`，直接起 MCP stdio server——已实测。

### 3.2 方式二：`claude mcp add`

```bash
claude mcp add scansci-pdf \
  "<仓库绝对路径>\workspace\.venv\Scripts\python.exe" \
  -- -m scansci_pdf run
```

若你的版本支持 `-e`：

```bash
claude mcp add scansci-pdf \
  -e SCANSCI_PDF_DATA_DIR="<仓库绝对路径>\workspace\scansci-pdf" \
  -e PLAYWRIGHT_BROWSERS_PATH="<仓库绝对路径>\workspace\.browsers" \
  "<仓库绝对路径>\workspace\.venv\Scripts\python.exe" \
  -- -m scansci_pdf run
```

> 参数形态**未经逐字核实**（本机无 `claude` 可执行文件，见第 1.2 节）。
> 先跑 `claude mcp add --help`，再按你的版本调整。加完用 `claude mcp list` 确认。

## 4. 接入步骤

1. **过部署关**（必须；没有 venv，MCP server 起来也会失败）：

   ```bash
   cd "<仓库绝对路径>"
   python 0路由/scripts/bootstrap.py check
   python 0路由/scripts/bootstrap.py plan
   python 0路由/scripts/bootstrap.py apply
   ```

   要求 `workspace\.venv\Scripts\python.exe` 存在、`workspace/state/deploy.json` 的 `ready` 为 `true`。

2. **建技能目录**（第 2 节；或直接跑 `install.ps1` / `install.sh`）。
3. **（可选）配 MCP**（第 3 节任一方式）。
4. **重启 Claude Code / 新开会话**（技能与 MCP 变更都需重新加载）。
5. 用法：直接在对话里说需求，或让它跑 CLI：

   ```bash
   python 0路由/scripts/pipeline.py run --input "2020 年以来高被引的钙钛矿稳定性研究，要 20 篇"
   python 0路由/scripts/pipeline.py run --input dois.txt
   python 0路由/scripts/pipeline.py run --input refs.bib --no-search
   ```

## 5. 环境要求（务必照做）

| 约束 | 说明 |
|---|---|
| Python ≥ 3.11 | `scansci-pdf` 硬要求；`bootstrap.py` 会用 `uv` 在 `workspace/.uv-python` 装 3.12 |
| 用**普通终端**，别用受限沙箱 | WebVPN / CARSI / EZProxy 登录、过 Cloudflare、sci-hub 竞速的浏览器通道需要**可见浏览器**；链路是 patchright → Edge/Chrome，Playwright 走 **Windows 命名管道**，受限权限下报 `WinError 5 拒绝访问` |
| pip 需要能写临时目录 | 受限环境下放宽文件权限 |
| 机构通道可选 | Elsevier API Key（最快、**无需浏览器**）> 高校 WebVPN > CARSI > EZProxy |

## 6. 验证方法

> **新开一个 Claude Code 会话，问它：「你能看到 `paperforge` 技能吗？」**

1. **技能可见**：它能复述用途（文献搜索与获取），并指出首次使用必须先过部署关。
   答不上来 → 检查 `<技能根>/paperforge/SKILL.md` 是否成立（第 2 节末的 `Test-Path`）。
2. **环境就绪**：

   ```bash
   python 0路由/scripts/doctor.py
   ```

3. **MCP 连通**（若配了）：`claude mcp list` 应列出 `scansci-pdf`；新会话里让它列工具，
   应出现 `scansci_pdf_*` 系列（上游 1.17.0 为 17 个）。
   列不出来 → `.mcp.json` 里 `command` 的绝对路径写错，或没重启。
