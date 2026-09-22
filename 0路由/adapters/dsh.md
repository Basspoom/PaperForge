# DSH（DeepSeek Harness）接入

DSH 有两种机制，本 skill 两样都用：

| 机制 | 用途 | 注册位置 |
|---|---|---|
| **Skills** | 让 Agent 知道有这个技能、按需加载指令 | `<技能根>/paperforge/SKILL.md` |
| **MCP** | 把 `scansci-pdf` 的工具注册成 Agent 的原生工具 | agent preset 里的 `dsh-mcp-client` 行 |

> 主干不依赖 MCP——所有能力都能通过 `python 0路由/scripts/pipeline.py` 走 CLI。
> MCP 是"让模型直接看见 18 个工具"的增强层。

---

## 一、两种机制各自的归属（为什么这么放）

DSH 的 Cordis 编排分两个面（plane）：

| 面 | 放什么 | 本 skill 的行 |
|---|---|---|
| **Host composition** | 注册表本身、跨会话的东西、沙箱与审批栈、模型路由 | 不需要改动 |
| **Agent preset** | 一个会话向那些注册表贡献什么：工具、persona、prompt 段 | `dsh-mcp-client` 行在这里 |

`dsh-mcp-client` 注册的是**工具**（写 `ctx.tools`），属于 per-session 层，
所以它放 preset、不放 host composition，也**不需要 `isolate` realm**
（realm 是给"preset 自己发布 service"的行用的，MCP 客户端不发布 service）。

---

## 二、技能发现

DSH 的 `@deepseek-ai/dsh-skill-filesystem` 按下面的根扫描（rank 顺序）：

| Rank | 来源 | 路径 |
|---|---|---|
| 100 | project-dsh | `<项目根>/.dsh/skills` |
| 200 | project-agents | `<项目根>/.agents/skills` |
| 300 | custom | 配置的 `customSkillDirs` |
| 400 | user-dsh | `$DSH_HOME/skills` |
| 500 | user-agents | `~/.agents/skills` |

**发现规则**：只认 `<根>/<name>/SKILL.md`，**深度一层**，不支持嵌套。
frontmatter 的 `name` 必须是 kebab-case。

本仓库的目录名是中文「智能体」，而 frontmatter 是 `name: paperforge`。
为同时满足"目录一层"和"kebab-case"两个要求，**建立目录联接**：

```powershell
# Windows：目录联接（无需管理员）
cmd /c mklink /J "$env:USERPROFILE\.dsh\skills\paperforge" "<仓库绝对路径>"
```

```bash
# macOS / Linux：符号链接
ln -s "<仓库绝对路径>" "$HOME/.dsh/skills/paperforge"
```

这条联接就是 `0路由/scripts/install.ps1` / `install.sh` 做的事（它们会尝试多个技能根）。
建好后 `~/.dsh/skills/paperforge/SKILL.md` 成立，DSH 立刻能发现——
本 skill 就是这么接进来的，建完联接无需重启，目录监视器会即时刷新技能目录。

---

## 三、MCP：新建一个用户 preset

### 为什么必须新建 preset 而不能改 `standard`

`standard` / `code` / `minimal` / `cordis` 是**随 DSH 发行安装**的 preset，
位于 `…\@deepseek-ai\dsh\config\agent-presets\`。**不要改它们**：
升级会覆盖，而且改坏 `cordis` 会让 preset 编写能力本身失效。

正确做法是复制一份到用户根，改副本。

### 步骤

```text
1. 复制
   用 roster 服务的 copy（推荐的唯一写入接口）：
       copy(from='standard', id='paperforge', name='文献搜索与获取')
   它会整目录复制到 `$DSH_HOME/.agent-presets/paperforge/`，
   并重写副本的 preset.yml（保留来源的 description，去掉它的 name 与 order）。

2. 在副本的 agent.cordis.yml 末尾追加 MCP 行（见下）

3. 改副本的 preset.yml 的 name / description

4. 挂载校验
       standingKeyFor('paperforge')
   它真的把这份 composition 组合一遍（不含 agent），能报出四类失败：
   包不存在 / config 非法 / 行未激活 / service 发布到了 root realm。

5. 设为默认
   在 `$DSH_HOME/settings.yaml` 里把 agent-presets.default 改成 paperforge
```

### 追加到 `agent.cordis.yml` 的行

```yaml
- id: mcp-scansci-pdf
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: scansci-pdf
    transport: stdio
    command: '<仓库>/workspace/.venv/Scripts/python.exe'   # Windows
    #        '<仓库>/workspace/.venv/bin/python'          # macOS / Linux
    args:
      - '-m'
      - 'scansci_pdf'
      - 'run'
    cwd: '<仓库>'
    env:
      SCANSCI_PDF_DATA_DIR: '<仓库>/workspace/scansci-pdf'
      PLAYWRIGHT_BROWSERS_PATH: '<仓库>/workspace/.browsers'
      PYTHONUTF8: '1'
      PYTHONIOENCODING: 'utf-8'
    toolCallTimeoutMs: 1800000
    failOnStartupError: false
    reconnect:
      enabled: true
      maxAttempts: 5
```

### 每个字段为什么这么写

| 字段 | 原因 |
|---|---|
| `command` 用 venv 解释器 + `-m scansci_pdf` | console script 不一定在 PATH 上；`-m` 不依赖 venv 是否激活 |
| `cwd` 指向仓库 | 让相对路径（`0路由/scripts/…`）可用 |
| `SCANSCI_PDF_DATA_DIR` **必须**指向 skill 的 workspace | 否则 MCP 服务器读的是 `~/.scansci-pdf` 下另一套 `config.json` 与登录 cookie——**机构通道会莫名其妙失效**，因为 cookie 路径与 `instsci_cookie_file` 对不上 |
| `PLAYWRIGHT_BROWSERS_PATH` | 把浏览器内核收进 workspace，便于清理 |
| `toolCallTimeoutMs: 1800000` | **默认 60000（60 秒）对下载任务远远不够**，批量任务必超时 |
| `failOnStartupError: false` | venv 还没建（未过部署关）时不至于让整个 preset 激活失败 |

### 前置条件

MCP 服务器**依赖 skill 的 venv**，所以必须先在**普通终端**里过部署关：

```bash
python 0路由/scripts/bootstrap.py check
python 0路由/scripts/bootstrap.py plan
python 0路由/scripts/bootstrap.py apply --email <你的邮箱> --school <你的学校> --browser
```

---

## 四、验证接入成功

### 技能

新开一个 DSH 会话，问：

> 你能看到 `paperforge` 技能吗？它的输入和输出分别是什么？

预期：Agent 能说出"输入是自然语言检索需求或文献清单，输出是 DOI 命名的 PDF + 元信息表 + 成功失败日志"。

本仓库接入时的实测结果：建好联接后**当前会话的技能目录立刻出现了**
`paperforge`，无需重启。

### MCP

新会话里问：

> 列出你可用的 scansci-pdf 相关工具。

预期：能看到形如 `mcp__scansci-pdf__scansci_pdf_download`、
`mcp__scansci-pdf__scansci_pdf_batch_download` 的原生工具（该服务器当前暴露 18 个）。

命令行侧的等价自检（不需要 MCP）：

```bash
<仓库>/workspace/.venv/Scripts/python -m scansci_pdf check
```

预期：core 依赖全部 `[OK]`。

### preset 是否挂得上

```text
cordis 会话里：
  cordis_inspect what:"api" name:"agentPresets"
  → 挂一个临时插件调用 standingKeyFor('paperforge')
```

返回 `mounted OK` 即通过。注意 roster 的 `broken` 字段**不是**校验——
它只做结构检查，上面四类失败它都会放过。

---

## 五、排障

| 现象 | 检查 |
|---|---|
| 技能目录里看不到 `paperforge` | 联接是否存在、`<联接>/SKILL.md` 是否可读；frontmatter 的 `name` 是否 kebab-case |
| preset 选择器里显示成裸目录名 | `preset.yml` 缺 `name` / `description` |
| `standingKeyFor` 报 `row(s) published process-global service(s)` | 该行发布 service 却没放 `isolate` realm（MCP 客户端不发布 service，正常不会遇到） |
| MCP 工具没出现 | `failOnStartupError: false` 会把错误吞掉——到会话日志里找 `reconnecting` 记录；再确认 venv 与 `scansci_pdf` 已安装 |
| MCP 工具调用超时 | `toolCallTimeoutMs` 是否已调到 1800000 |
| 机构通道在 MCP 里失效、CLI 里正常 | `SCANSCI_PDF_DATA_DIR` 没指向 skill 的 workspace，读到了另一套 cookie |
| `.xlsx` 导出失败 | 那是 venv 里的 openpyxl 提供的；确认走的是 `pipeline.py`（它会自动切到 venv 解释器） |

---

## 六、撤销

```text
1. settings.yaml 的 agent-presets.default 改回 standard
2. 用 roster 的 remove('paperforge') 删除用户 preset
3. 删掉技能联接目录
```

`standard` 从未被改动，所以回退是干净的。
