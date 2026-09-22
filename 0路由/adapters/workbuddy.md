# WorkBuddy 接入

把 `paperforge` 接入 WorkBuddy。

> ⚠️ **先说结论：我没有找到（也未能读到）WorkBuddy 权威的接入文档正文，
> 因此本文不给任何"确切目录名 / 确切配置字段"。**
> 本文给出的是**通用兜底方案**——不依赖 WorkBuddy 的任何内部约定，只要能执行 shell 或能上传技能包就能用。

---

## 1. 核实状态

### 1.1 查到的（只到"这些页面存在、主题相关"这一层）

本环境内 WorkBuddy **未安装**（`PATH` 上没有 `workbuddy`），且沙箱内**无法打开网页正文**
（TLS / 网络受限）。`web_search` 只返回**标题与 URL**，不返回正文。所以下面只是"存在性证据"，
**不是"我读到了接入规范"**：

| 找到的东西 | 内容 | 链接 |
|---|---|---|
| WorkBuddy 官方文档站存在 | `workbuddy.cn` 下有文档区 | [workbuddy.cn](https://www.workbuddy.cn/) |
| **疑似**官方技能文档页 | 检索标题为「CodeBuddy Code Skills（技能系统）」，URL 落在 `/docs/cli/skills` | [workbuddy.cn/docs/cli/skills](https://www.workbuddy.cn/docs/cli/skills) |
| 官方相关站点（CodeBuddy）的 Skills 文档 | 标题「Skills」 | [codebuddy.cn/docs/ide/Features/Skills](https://www.codebuddy.cn/docs/ide/Features/Skills) |
| WorkBuddy 有 MCP 连接器相关材料 | 社区教程仓库含 `s17_mcp_connectors` 章节 | [adongwanai/learn-workbuddy](https://github.com/adongwanai/learn-workbuddy/blob/main/s17_mcp_connectors/README.md) |
| 社区教程：WorkBuddy 技能可**上传导入** | 描述为「点击『添加技能』→『上传技能』→ 拖拽本地技能包 → 自动配置」 | [WorkBuddy 从入门到精通](https://cloud.tencent.cn/developer/article/2664219) |
| 社区教程：WorkBuddy 有"自建技能"流程 | 相关文章与"专家/插件"体系 | [自己创建专家，WorkBuddy 实战攻略](https://cloud.tencent.cn/developer/article/2736199)、[WorkBuddy Skills 完全上手指南](https://cloud.tencent.cn/developer/article/2672840)、[WorkBuddy 从零开发 Skill](https://news.qiniu.com/archives/1785981167161) |
| 有第三方 WorkBuddy 适配参考 | `@qoder-ai/better-harness` 的 `references/agent-customize/platforms/workbuddy.md` | [jsDelivr 镜像](https://cdn.jsdelivr.net/npm/@qoder-ai/better-harness@0.6.2/references/agent-customize/platforms/workbuddy.md) |

### 1.2 未核实的（**本文一律不编造**）

| 事项 | 状态 |
|---|---|
| WorkBuddy 技能目录的确切路径（用户级 / 项目级） | **未核实** |
| 技能包的目录结构与必需文件（是否就是 `SKILL.md` 约定） | **未核实** |
| MCP 配置文件的位置、文件名、字段格式 | **未核实** |
| 是否支持符号链接 / 目录联接 | **未核实** |
| `workbuddy.cn` 与 `codebuddy.cn` 两个产品的关系（技能体系是否共享） | **未核实**。检索结果里两者标题相互出现，但**没有读到正文说明**，我不做推断 |
| 技能是否可纯 CLI 接入（无需 GUI） | **未核实** |

### 1.3 怎么自己核实（推荐）

1. 打开上面那个疑似官方文档页：[workbuddy.cn/docs/cli/skills](https://www.workbuddy.cn/docs/cli/skills)。
   若它讲的是技能系统，**以它为准**，本文的兜底方案就不用走了。
2. 在 WorkBuddy 里问它自己：「你的技能放在哪个目录？怎么注册一个本地技能？
   MCP 配置写在哪里、什么格式？」——这类问题通常能直接得到当前版本的准确答案。
3. 翻 WorkBuddy 的"设置 / 扩展 / 技能"面板，看有没有"打开技能目录"之类的入口。

**若上面任一步给出了确切约定，请优先按那个约定做，并回来修正本文档**（本文已标注未核实，
改动成本很低）。

---

## 2. 兜底方案总纲

因为目录名、配置字段都未核实，本文只给**不依赖这些细节**的三条路，按推荐顺序：

| 优先级 | 方案 | 依赖 WorkBuddy 的什么能力 |
|---|---|---|
| ① | **纯 CLI 调用**（第 3 节） | 只要能执行 shell 命令 |
| ② | **上传技能包**（第 4 节） | 只要有"添加技能 / 上传技能"的 UI |
| ③ | **Claude-Code 兼容布局**（第 5 节） | 只要它兼容 `.claude/skills/` 或标准 `SKILL.md` 约定 |

三条路可以叠加：技能文本负责"让 Agent 知道该做什么"，CLI 负责"真的做到"。

---

## 3. 方案①：纯 CLI 调用（**首选，最稳**）

不依赖任何 WorkBuddy 约定。只要 WorkBuddy 能执行 shell 命令，就能用。

1. **过部署关**（框架无关）：

   ```bash
   cd "<仓库绝对路径>"
   python 0路由/scripts/bootstrap.py check
   python 0路由/scripts/bootstrap.py plan
   python 0路由/scripts/bootstrap.py apply
   ```

   要求 `workspace/.venv/Scripts/python.exe`（POSIX 为 `workspace/.venv/bin/python`）存在，
   `workspace/state/deploy.json` 的 `ready` 为 `true`。

2. **让 WorkBuddy 执行**：

   ```bash
   python 0路由/scripts/pipeline.py run --input "2020 年以来高被引的钙钛矿稳定性研究，要 20 篇"
   python 0路由/scripts/pipeline.py run --input dois.txt
   python 0路由/scripts/pipeline.py run --input refs.bib --no-search
   ```

3. **技能文本怎么喂给它**（本节的关键）——把下面这段作为**指令/自定义提示**交给 WorkBuddy，
   或写入它的项目级说明文件（若它支持 `AGENTS.md` / 自定义指令之类，**具体位置未核实**）：

   ```text
   本机安装了一个文献获取技能，仓库根目录：
     <仓库绝对路径>

   处理"检索文献 / 批量下载论文 / 获取全文 PDF / 文献清单补 DOI"这类需求时：

   1. 先读技能说明：<仓库根>\SKILL.md（里面写了完整工作链路与两道用户确认门）
   2. 首次使用必须先过部署关，执行：
        python 0路由/scripts/bootstrap.py check
        python 0路由/scripts/bootstrap.py plan
        python 0路由/scripts/bootstrap.py apply
      要求 workspace\state\deploy.json 里 ready 为 true。
   3. 端到端入口：
        python 0路由/scripts/pipeline.py run --input "<检索需求或清单文件>"
   4. 批量下载前必须让用户确认文献列表（门①）与下载策略（门②）。
   5. 产物在 <仓库根>\workspace\ 下：pdfs\（DOI 命名）、metadata.csv/.xlsx/.md、
      failures.md、doi_index.json、logs\。
   6. 环境体检：python 0路由/scripts\doctor.py
   ```

   > **为什么要这样喂**：`SKILL.md` 里的所有链接都是**相对仓库根**的
   > （`0路由/bootstrap.md`、`0路由/contract.md`、`1学术查询/SKILL.md` …，已逐一核对存在），
   > 所以只要告诉它"仓库根在哪 + 先读 `SKILL.md`"，Agent 就能顺着读完整个技能，
   > **完全不需要技能发现机制**。
   >
   > 同理，若 WorkBuddy 有"自定义系统提示词 / 角色设定"，把上面这段塞进去即可。

4. **（可选）MCP**：本仓库根已有 `.mcp.json`（`mcpServers` → `scansci-pdf`，
   venv python + `-m scansci_pdf run`）。**WorkBuddy 是否吃这个格式未核实**。
   它的 MCP 配置位置与字段请按第 1.3 节自行核实后再填；字段含义可参考
   [codex.md](codex.md#2-本仓库已经准备好的两份配置) 或 [claude-code.md](claude-code.md#31-方式一mcpjson可直接粘贴)。

---

## 4. 方案②：上传技能包

社区教程描述 WorkBuddy 支持「点击『添加技能』→『上传技能』→ 拖拽本地技能包 → 自动配置」
（来源见第 1.1 节）。若你的版本有这个 UI，按下面打包：

1. **先建一个顶层目录叫 `paperforge`**（技能名必须与 `SKILL.md` frontmatter 的
   `name: paperforge` 一致；本仓库目录名是中文「智能体」，直接打包上去很可能不被识别）。
2. **把整个仓库内容放进去**（`SKILL.md` 必须在 `paperforge/` 这一层的根下）：

   ```powershell
   $repo = "<仓库绝对路径>"
   $out  = "$env:USERPROFILE\Desktop\paperforge-skill"
   robocopy $repo $out /E /XD workspace .git .tmp .venv .uv-python .uv-cache __pycache__ 2>$null
   Test-Path "$out\SKILL.md"     # 必须为 True
   ```

   > **必须排除 `workspace/`**：它是运行产物（PDF、venv、浏览器内核，可能几个 GB），
   > 放进技能包既臃肿又无意义。技能包里只需要脚本与文档。
   > **但上传后要记得**：目标机器上仍要先过部署关，`workspace/` 会被重新建出来。

3. **打包并上传**：

   ```powershell
   Compress-Archive -Path $out -DestinationPath "$env:USERPROFILE\Desktop\paperforge.zip" -Force
   ```

   然后在 WorkBuddy 的「添加技能 → 上传技能」里选这个 zip。

4. **上传后必须做的一步**：仓库路径变成了解压后的目录，`SKILL.md` 里的相对链接仍然成立
   （都是相对技能包根的），但**绝对路径全部失效**。所以要让 Agent 在目标机器上重跑部署关：

   ```bash
   python 0路由/scripts/bootstrap.py check
   python 0路由/scripts/bootstrap.py plan
   python 0路由/scripts/bootstrap.py apply
   ```

5. **兜底**：若上传后的目录结构不被接受（例如它要求平铺的 `SKILL.md`，不接受带子目录），
   就退回方案①：把第 3.3 节那段指令文本贴进它的自定义指令里。

---

## 5. 方案③：Claude-Code 兼容布局

很多国产/桌面 Agent 工具的技能体系与 Claude Code 的技能约定兼容（**WorkBuddy 是否兼容，
未核实**）。若你想试，这是成本最低的一试：

```powershell
# 假设 WorkBuddy 兼容 ~/.claude/skills/ 约定（未核实，试错成本极低）
$repo = "<仓库绝对路径>"
New-Item -ItemType Directory -Force -Path "$HOME\.claude\skills" | Out-Null
New-Item -ItemType Junction -Path "$HOME\.claude\skills\paperforge" -Target $repo
```

或用本仓库的脚本，把技能根指到 WorkBuddy 实际读取的目录（**路径需你先核实**）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File 0路由\scripts\install.ps1 `
  -TargetDir "<你核实到的 WorkBuddy 技能根>"
```

```bash
bash 0路由/scripts/install.sh --target-dir "<你核实到的 WorkBuddy 技能根>"
```

**为什么要给 `-TargetDir` / `--target-dir`**：正因为 WorkBuddy 的目录约定未核实，
这两个脚本支持显式指定技能根——你核实到什么路径，就挂到那个路径，不必依赖内置候选表。

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

> **新开一个 WorkBuddy 会话，问它：「你能看到 `paperforge` 技能吗？」**

- **能看到** → 方案②/③ 成功。再让它跑一次环境体检确认链路：
  `python 0路由/scripts/doctor.py`。
- **看不到** → 这在预期之内（本文第 1.2 节的约定都未核实）。**不要继续在技能发现上耗时间**，
  直接用方案①：把第 3.3 节那段指令文本交给它，然后验证下面这条：

  ```bash
  python 0路由/scripts/pipeline.py run --input "10.48550/arXiv.1706.03762"
  ```

  成功时 `workspace/pdfs/10.48550_arXiv.1706.03762.pdf` 出现。
  **只要这条通，技能就是可用的**——技能文本的作用只是让 Agent 知道该调它。
