# opencode 接入

把 `paperforge` 接入 opencode（`sst/opencode` / `opencode.ai`）。

> ⚠️ **本文的核实程度低于 Codex 与 Claude Code 两篇**，原因见第 1 节。凡未核实的字段，
> 本文一律标注「**未核实**」，并给出**不依赖这些细节的兜底方案**（第 4 节），
> 所以即使某个字段和你的版本对不上，你也不会卡住。

---

## 1. 核实状态

### 1.1 已核实（只到"官方文档存在且主题确定"这一层）

本环境内 opencode **未安装**（`PATH` 上没有 `opencode`，`~/.config/opencode`、`~/.opencode`
均不存在），且沙箱内**无法打开网页正文**（TLS / 网络受限）。因此下面这些是从
官方文档站的**检索结果（标题 + URL）**确认的，**不是逐字读到正文**：

| 事实 | 内容 | 来源 |
|---|---|---|
| opencode 有官方 **Agent Skills** 文档 | 主题明确为"代理技能"，含"权限配置"章节 | [opencode.ai/docs/skills](https://opencode.ai/docs/skills)（另有 de / ru / pl / ar / da / ko / zh-tw 多语言版） |
| opencode 有官方 **MCP servers** 文档 | 主题明确为 MCP 服务器配置 | [opencode.ai/docs/mcp-servers](https://opencode.ai/docs/mcp-servers)、[zh-cn 版](https://docs.opencode.ai/docs/zh-cn/mcp-servers/) |
| 配置文件是 **`opencode.json`** | 官方 Config 文档；第三方文档标题也写「OpenCode 配置（opencode.json）：模型、工具、Agents、MCP」 | [opencode.ai/docs/config](https://opencode.ai/docs/config)、[open-code.ai/zh/docs/config](https://open-code.ai/zh/docs/config) |
| MCP 配置的顶层键是 **`mcp`** | 官方 MCP 文档；第三方中文文档标题即「模型、工具、Agents、MCP」并列 | 同上 |
| 配置可分层（全局 / 项目） | 官方 Config 文档含 `#files` 锚点，说明有"配置文件"章节 | [opencode.ai/docs/config#files](https://opencode.ai/docs/config) |

### 1.2 未核实（**请按你所用版本核实**）

| 事项 | 状态 |
|---|---|
| **技能目录的确切路径** | **未核实**。官方有 skills 文档页，但我**没有读到正文**，因此**不写具体目录名**。可能的形态有 `<项目>/.opencode/skill/`、`~/.config/opencode/skill/` 等，**本文不做猜测** |
| 技能目录名是 **`skill`（单数）还是 `skills`（复数）** | **未核实**，同上 |
| `opencode.json` 中 **`mcp` 段的字段格式**（例如是否有 `type: "local"`、`command` 是**数组**还是字符串、是否用 `environment` 而非 `env`） | **未核实**。第 3 节给出的是**带明确标注的候选形态**，请务必用下面第 1.3 节的方法就地核对 |
| 全局配置文件的确切位置 | **未核实**（`~/.config/opencode/opencode.json` 是 XDG 惯例下的常见形态，但未核实） |
| opencode 是否跟随符号链接做技能发现 | **未核实**（本项目其它框架的经验是"通常可以"，但不猜） |

### 1.3 怎么就地核实（30 秒，推荐先做）

opencode 自带配置自省，比读文档更快更准：

```bash
opencode --version
opencode --help                 # 看有没有 skills / mcp 相关子命令
opencode mcp --help             # 若存在，直接看它接受的参数
```

然后让它自己把"我读到了哪些技能"说出来：**新开一个 opencode 会话，问
「你能看到 `paperforge` 技能吗？」**（见第 6 节）。
若看不到，直接按第 1.2 节的未核实项逐个试目录名——**试错成本极低**，因为
本项目的链接脚本是幂等的、可反复执行。

---

## 2. 接入策略：先 CLI，后技能，最后 MCP

因为细节未核实，按**风险从低到高**接入，每步都独立可用：

| 顺序 | 做什么 | 依赖未核实项吗 |
|---|---|---|
| ① | 过部署关，用 CLI 调 `pipeline.py` | **不依赖**（框架无关，一定能用） |
| ② | 把技能挂到 opencode 的技能根 | 依赖"目录路径"（第 1.2 节未核实项） |
| ③ | 配 MCP | 依赖"`mcp` 段字段格式"（第 1.2 节未核实项） |

**即使 ② 和 ③ 都没配对，① 依然让本技能完全可用**——这是本仓库"主干是 CLI"的设计目的。

---

## 3. MCP 配置（候选形态，**未核实**）

### 3.1 已核实的部分

- 配置文件：**`opencode.json`**（可放项目根，也可放全局配置目录）
- 顶层键：**`mcp`**

### 3.2 候选形态（**字段格式未核实，请对照你的版本文档确认**）

opencode 的 MCP 段在这类工具里通常是"本地 / 远程"两种类型。
下面给出**看起来最可能**的本地（stdio）写法——**这不是核实结论，是待你确认的候选**：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "scansci-pdf": {
      "type": "local",
      "command": [
        "<仓库绝对路径>\\workspace\\.venv\\Scripts\\python.exe",
        "-m",
        "scansci_pdf",
        "run"
      ],
      "enabled": true,
      "environment": {
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

**逐个字段的风险标注**：

| 字段 | 风险 |
|---|---|
| `mcp`（顶层键） | 已核实存在 |
| `command` 为**数组**（可执行文件 + 参数拼在一个数组里） | **未核实**。若你的版本要求 `command` 是字符串 + 单独 `args` 数组，就拆成 `"command": "...python.exe"` + `"args": ["-m","scansci_pdf","run"]` |
| `type: "local"` | **未核实**。若不需要可删掉 |
| `environment` | **未核实**。若你的版本用 `env`，就把键名改成 `env` |
| `enabled: true` | **未核实**，为可选项，删掉通常也能用 |
| `$schema` | 可选提示字段，删掉不影响运行 |

> **稳妥做法**：先只写 `mcp` + `command`（最少的键），重启 opencode 看 § 6 的验证；
> 能连上再加 `environment` 等。**从最小可用集开始，逐项加**，比一次写满再去猜哪个字段错要快。

### 3.3 环境变量为什么必须写

本仓库默认把 `TMP` / `TEMP` / `SCANSCI_PDF_DATA_DIR` / `PLAYWRIGHT_BROWSERS_PATH`
全部收进 `workspace/`，保证可清理、不污染用户目录（见 `0路由/scripts/_common.py` 的
`child_env()`）。**如果你手写 MCP 配置时不带这些变量**，浏览器内核和缓存会跑到
`%LOCALAPPDATA%` 之类的用户目录去。若你的 opencode 版本不支持在配置里写环境变量，
就退而把它们设成**系统环境变量**——效果相同。

---

## 4. 兜底方案（**不依赖任何未核实项**）

### 4.1 纯 CLI（一定能用）

只要 opencode 能执行 shell，就能用：

```bash
cd "<仓库绝对路径>"
python 0路由/scripts/pipeline.py run --input "2020 年以来高被引的钙钛矿稳定性研究，要 20 篇"
python 0路由/scripts/pipeline.py run --input dois.txt
python 0路由/scripts/pipeline.py run --input refs.bib --no-search
```

告诉 opencode（或在项目根的 `AGENTS.md` 里写）：

> 本项目有文献获取技能。执行文献检索/下载前先读 `智能体/SKILL.md`，
> 并先跑 `python 0路由/scripts/bootstrap.py check` 确认部署关已通过；
> 端到端入口是 `python 0路由/scripts/pipeline.py run --input <需求或清单>`。

把这段放进 `AGENTS.md` 是**框架无关的技能投喂方式**：opencode 读 `AGENTS.md`，
就等价于"看见了技能"，完全不依赖技能目录约定。

### 4.2 让 opencode 自己读技能文本（不用技能发现）

如果技能根怎么都挂不对，就让 Agent **直接把 `SKILL.md` 读进来**：

```text
请先读 "<仓库绝对路径>\SKILL.md"，
然后按里面的工作链路帮我检索并下载这批文献。
```

`SKILL.md` 里的相对链接（`0路由/contract.md`、`1学术查询/`、`2工程化下载/` 等）
都是相对仓库根的，Agent 顺着读即可，不需要任何注册机制。

---

## 5. 接入步骤

1. **过部署关**（框架无关，必须）：

   ```bash
   cd "<仓库绝对路径>"
   python 0路由/scripts/bootstrap.py check
   python 0路由/scripts/bootstrap.py plan
   python 0路由/scripts/bootstrap.py apply
   ```

   要求 `workspace/.venv/`（Windows 为 `Scripts\python.exe`，POSIX 为 `bin/python`）存在，
   `workspace/state/deploy.json` 的 `ready` 为 `true`。

2. **（可选）挂技能**：用本仓库的脚本，把 `paperforge` 链接到候选技能根：

   ```powershell
   # Windows
   powershell -NoProfile -ExecutionPolicy Bypass -File 0路由\scripts\install.ps1
   ```

   ```bash
   # macOS / Linux
   bash 0路由/scripts/install.sh
   ```

   脚本按顺序尝试：`<项目根>/.dsh/skills`、`<项目根>/.agents/skills`、
   `$DSH_HOME/skills`（或 `~/.dsh/skills`）、`~/.agents/skills`、`~/.claude/skills`，
   **已存在的才动**；也可用 `-TargetDir` / `--target-dir` 显式指定。

   核实 opencode 的真实技能根后，一条命令挂过去（Windows 例）：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File 0路由\scripts\install.ps1 `
     -TargetDir "$HOME\.config\opencode\skill"
   ```

3. **（可选）配 MCP**（第 3 节，从最小可用集开始）。
4. **重启 opencode**（技能扫描与 MCP 变更都需重新加载）。
5. **（可选）投喂技能文本**：在项目根 `AGENTS.md` 写第 4.1 节那段话。

---

## 6. 环境要求（务必照做）

| 约束 | 说明 |
|---|---|
| Python ≥ 3.11 | `scansci-pdf` 硬要求；`bootstrap.py` 会用 `uv` 在 `workspace/.uv-python` 装 3.12 |
| 用**普通终端**，别用受限沙箱 | WebVPN / CARSI / EZProxy 登录、过 Cloudflare、sci-hub 竞速的浏览器通道需要**可见浏览器**；链路是 patchright → Edge/Chrome，Playwright 走 **Windows 命名管道**，受限权限下报 `WinError 5 拒绝访问` |
| pip 需要能写临时目录 | 受限环境下放宽文件权限 |
| 机构通道可选 | Elsevier API Key（最快、**无需浏览器**）> 高校 WebVPN > CARSI > EZProxy |

---

## 7. 验证方法

> **新开一个 opencode 会话，问它：「你能看到 `paperforge` 技能吗？」**

1. **技能可见**：它能复述用途（文献搜索与获取），并指出首次使用必须先跑
   `python 0路由/scripts/bootstrap.py check / plan / apply`。
   - 答不上来 → 技能根路径没对上（第 1.2 节未核实项）。**别纠缠**：直接用第 4.1 节
     的 `AGENTS.md` 投喂，或第 4.2 节让它直接读 `SKILL.md`。
2. **环境就绪**（框架无关，最有说服力的验证）：

   ```bash
   python 0路由/scripts/doctor.py     # 环境体检（含代理自动探测）
   ```

3. **CLI 端到端**（框架无关）：

   ```bash
   python 0路由/scripts/pipeline.py run --input "10.48550/arXiv.1706.03762"
   ```

   成功时 `workspace/pdfs/10.48550_arXiv.1706.03762.pdf` 出现。

4. **MCP 连通**（若配了）：让它列出可用工具，应出现 `scansci_pdf_*` 系列
   （上游 1.17.0 为 17 个工具）。列不出来 → 第 3.2 节的字段格式与你的版本不符，
   按那个表格逐个字段试，或**先放弃 MCP**（第 4 节兜底一样能干活）。
