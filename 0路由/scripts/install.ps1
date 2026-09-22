<#
.SYNOPSIS
    把本仓库（paperforge 文献获取技能）注册到各个 Agent 框架的技能根目录。

.DESCRIPTION
    技能发现要求目录布局是 <技能根>/<name>/SKILL.md，其中 <name> 必须等于
    SKILL.md frontmatter 里的 name（本仓库是 paperforge）。
    而本仓库目录名是中文「智能体」，所以必须在技能根下建一个名为
    paperforge 的链接（Windows 用目录联接 Junction）指向本目录。

    本脚本：
      1. 按顺序尝试一批候选技能根，**只处理已经存在的**（不无中生有地造目录树）；
      2. 幂等——重复执行不报错、不重复创建、已指向本仓库的链接会被跳过；
      3. 链接创建失败（权限不足等）时降级为「打印精确的手动复制命令」，不中断其它目标；
      4. 结束前打印「下一步该跑什么」。

.PARAMETER TargetDir
    显式指定技能根（可重复传多个）。指定后**不再**自动扫描候选根，只处理这些。

.PARAMETER Force
    对不存在的技能根也创建它（默认只认已存在的技能根）。

.PARAMETER WhatIfPlan
    只打印将要做什么，不做任何改动。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File 0路由\scripts\install.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File 0路由\scripts\install.ps1 -TargetDir "$HOME\.codex\skills"

.NOTES
    首个候选根是 ~/.codex/skills —— 该路径已在实机 Codex 安装中核对到（真实存在
    16 个技能目录，每个根下就是 SKILL.md）。
    其它候选根是否被对应框架读取，请以各框架实际技能列表为准，
    详见 0路由/adapters/ 下的适配说明。
#>

[CmdletBinding()]
param(
    [string[]]$TargetDir = @(),
    [switch]$Force,
    [switch]$WhatIfPlan
)

$ErrorActionPreference = 'Stop'

# ── 基本量 ───────────────────────────────────────────────────────────────────
# 本脚本在 <仓库根>\0路由\scripts\ 下，往上三级就是仓库根。
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AgentRoot = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path

# 技能名必须与 SKILL.md frontmatter 的 name 一致，否则技能发现认不出来。
$SkillName = 'paperforge'

# 校验这确实就是我们要注册的仓库。
$SkillMd = Join-Path $AgentRoot 'SKILL.md'
if (-not (Test-Path -LiteralPath $SkillMd)) {
    Write-Host "[FAIL] 在 $AgentRoot 下找不到 SKILL.md —— 本脚本必须放在 <仓库根>\0路由\scripts\ 里。" -ForegroundColor Red
    exit 1
}

# 从 frontmatter 里读出真实的 name，与预期值比对（读不到就只警告，不阻断）。
$declared = $null
try {
    $head = Get-Content -LiteralPath $SkillMd -TotalCount 12 -Encoding UTF8
    foreach ($line in $head) {
        if ($line -match '^\s*name\s*:\s*(.+?)\s*$') { $declared = $Matches[1].Trim('"').Trim("'"); break }
    }
} catch { }
if ($declared -and $declared -ne $SkillName) {
    Write-Host "[WARN] SKILL.md 里的 name 是 '$declared'，与脚本预期的 '$SkillName' 不一致。" -ForegroundColor Yellow
    Write-Host "       将以 '$declared' 作为链接名（技能发现要求目录名 == name）。" -ForegroundColor Yellow
    $SkillName = $declared
}

# ── 工具函数 ─────────────────────────────────────────────────────────────────
function Write-Head([string]$Text) {
    Write-Host ''
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

# 把 -TargetDir 里的 ~ 和相对路径展开成绝对路径。
function Resolve-TargetPath([string]$Raw) {
    $p = $Raw
    if ($p -eq '~') { return $HOME }
    if ($p -like '~/*' -or $p -like '~\*') {
        $p = Join-Path $HOME $p.Substring(2)
    }
    if (-not [System.IO.Path]::IsPathRooted($p)) {
        $p = Join-Path (Get-Location).Path $p
    }
    return [System.IO.Path]::GetFullPath($p)
}

# 判定某个路径是不是「链接」（联接 / 符号链接）。
function Get-IsLink([string]$Path) {
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    } catch { return $false }
    if ($item.LinkType) { return $true }
    return [bool]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
}

function Get-LinkTarget([string]$Path) {
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        $t = $item.Target
        if ($t -is [array]) { return ($t | Select-Object -First 1) }
        if ($t) { return [string]$t }
    } catch { }
    return $null
}

# 判断两个路径是否指向同一处（用 GetFullPath 归一，忽略大小写和结尾斜杠）。
function Test-SamePath([string]$A, [string]$B) {
    if (-not $A -or -not $B) { return $false }
    try {
        $na = [System.IO.Path]::GetFullPath($A).TrimEnd('\', '/')
        $nb = [System.IO.Path]::GetFullPath($B).TrimEnd('\', '/')
        return [string]::Equals($na, $nb, [System.StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

# 生成「手动复制」的精确命令，链接创建失败时用。
function Write-ManualCopyHint([string]$LinkPath) {
    Write-Host '       链接创建失败（通常是权限不足）。降级方案 —— 手动复制，逐条执行：' -ForegroundColor Yellow
    Write-Host ''
    Write-Host "         New-Item -ItemType Directory -Force -Path '$(Split-Path -Parent $LinkPath)'" -ForegroundColor Gray
    Write-Host "         robocopy '$AgentRoot' '$LinkPath' /E /XD workspace .git .tmp __pycache__" -ForegroundColor Gray
    Write-Host ''
    Write-Host '       说明：上面刻意用 robocopy 而不是 Copy-Item，并排除 workspace —— 那是运行产物' -ForegroundColor DarkGray
    Write-Host '             （PDF、venv、浏览器内核，可达数 GB），技能包里不需要它。' -ForegroundColor DarkGray
    Write-Host '       注意：复制出来的是一份快照，以后改了本仓库要重新复制一次。' -ForegroundColor DarkGray
}

# 处理一个技能根下的注册动作。返回 'created' / 'exists' / 'failed' / 'skipped'。
function Invoke-SkillRoot([string]$RootPath) {
    $link = Join-Path $RootPath $SkillName

    Write-Host ''
    Write-Host "--- 技能根: $RootPath" -ForegroundColor White

    # 1) 已经存在同名条目
    if (Test-Path -LiteralPath $link) {
        if (Get-IsLink $link) {
            $tgt = Get-LinkTarget $link
            if (Test-SamePath $tgt $AgentRoot) {
                Write-Host "    [OK]   已存在且指向本仓库，跳过：$link -> $tgt" -ForegroundColor Green
                return 'exists'
            }
            Write-Host "    [WARN] 已存在但指向别处：$link -> $tgt" -ForegroundColor Yellow
            if ($WhatIfPlan) {
                Write-Host '    [PLAN] 会重建该链接指向本仓库' -ForegroundColor Cyan
                return 'created'
            }
            try {
                # 只删链接本身（联结/符号链接），不动目标里的内容。
                # -Recurse 不会删掉联接指向的真实内容，但为稳妥这里不加 -Force 之外的破坏性参数。
                Remove-Item -LiteralPath $link -Force -ErrorAction Stop
                Write-Host '    [..]   已移除旧链接，准备重建' -ForegroundColor Gray
            } catch {
                Write-Host "    [FAIL] 无法移除旧链接：$($_.Exception.Message)" -ForegroundColor Red
                Write-ManualCopyHint $link
                return 'failed'
            }
        }
        else {
            # 是真实目录/文件：可能是用户手动复制的，或另一个同名技能。绝不擅自删除。
            Write-Host "    [WARN] 已存在同名真实目录（不是链接），为安全起见不覆盖：$link" -ForegroundColor Yellow
            Write-Host '           若确认它就是要替换的旧副本，请手动删除后重跑本脚本。' -ForegroundColor DarkGray
            return 'skipped'
        }
    }

    # 2) 创建目录联接
    if ($WhatIfPlan) {
        Write-Host "    [PLAN] 将创建目录联接：$link -> $AgentRoot" -ForegroundColor Cyan
        return 'created'
    }
    try {
        New-Item -ItemType Junction -Path $link -Target $AgentRoot -ErrorAction Stop | Out-Null
    }
    catch {
        Write-Host "    [FAIL] 创建目录联接失败：$($_.Exception.Message)" -ForegroundColor Red
        Write-ManualCopyHint $link
        return 'failed'
    }

    # 3) 校验 <技能根>/<name>/SKILL.md 是否真的成立
    $probe = Join-Path $link 'SKILL.md'
    if (Test-Path -LiteralPath $probe) {
        Write-Host "    [OK]   已创建：$link -> $AgentRoot" -ForegroundColor Green
        Write-Host "           校验通过：$probe" -ForegroundColor DarkGray
        return 'created'
    }

    Write-Host '    [WARN] 联接已创建，但经链接读不到 SKILL.md。' -ForegroundColor Yellow
    Write-Host '           部分工具的目录扫描不跟随重解析点，此时请改用上面的手动复制方案。' -ForegroundColor DarkGray
    return 'failed'
}

# ── 主流程 ───────────────────────────────────────────────────────────────────
Write-Host '=========================================' -ForegroundColor Cyan
Write-Host ' paperforge 跨框架安装脚本' -ForegroundColor Cyan
Write-Host '=========================================' -ForegroundColor Cyan
Write-Host ''
Write-Host "仓库根   : $AgentRoot"
Write-Host "技能名   : $SkillName"
Write-Host "DSH_HOME : $(if ($env:DSH_HOME) { $env:DSH_HOME } else { '(未设置)' })"

if ($WhatIfPlan) {
    Write-Host ''
    Write-Host '*** -WhatIfPlan：只打印计划，不做任何改动 ***' -ForegroundColor Yellow
}

# 组装候选技能根
$candidates = @()
if ($TargetDir.Count -gt 0) {
    Write-Head '显式指定的技能根（-TargetDir）'
    foreach ($t in $TargetDir) { $candidates += [pscustomobject]@{ Path = (Resolve-TargetPath $t); Explicit = $true } }
}
else {
    # 项目根：以「当前工作目录」为项目根来构造项目级技能根。
    $projectRoot = (Get-Location).Path
    $dshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }

    # 顺序：项目级优先，其次用户级。~/.codex/skills 放首位 —— 该路径已在实机核对过。
    $raw = @(
        (Join-Path $HOME '.codex\skills'),                  # 实机核对过：Codex 用户级技能根
        (Join-Path $projectRoot '.dsh\skills'),             # DSH 项目级
        (Join-Path $projectRoot '.agents\skills'),          # 通用项目级
        (Join-Path $dshHome 'skills'),                      # DSH 用户级（$DSH_HOME 或 ~/.dsh）
        (Join-Path $HOME '.agents\skills'),                 # 通用用户级
        (Join-Path $HOME '.claude\skills'),                 # Claude Code 用户级
        (Join-Path $HOME 'plugins')                         # Codex 插件目录（兼容上游写法）
    )
    foreach ($r in $raw) {
        if (Test-Path -LiteralPath $r -PathType Container) {
            $candidates += [pscustomobject]@{ Path = $r; Explicit = $false }
        }
    }
}

if ($candidates.Count -eq 0) {
    Write-Head '结果'
    if ($TargetDir.Count -gt 0) {
        Write-Host '[FAIL] 指定的技能根不存在，且未加 -Force。' -ForegroundColor Red
    } else {
        Write-Host '没有找到任何「已存在」的技能根，因此没有改动任何东西。' -ForegroundColor Yellow
        Write-Host ''
        Write-Host '这不一定代表框架没装 —— 也可能是它还没创建过技能目录。两种选择：' -ForegroundColor Gray
        Write-Host '  a) 先在该框架里用一次技能功能，让它自己把技能目录建出来，再重跑本脚本；' -ForegroundColor Gray
        Write-Host '  b) 用 -TargetDir 显式指定要注册的技能根，例如：' -ForegroundColor Gray
        Write-Host '       powershell -NoProfile -ExecutionPolicy Bypass -File 0路由\scripts\install.ps1 -TargetDir "$HOME\.codex\skills"' -ForegroundColor Gray
        Write-Host '  c) 或加 -Force 让脚本自己创建候选目录：' -ForegroundColor Gray
        Write-Host '       powershell -NoProfile -ExecutionPolicy Bypass -File 0路由\scripts\install.ps1 -Force' -ForegroundColor Gray
    }
    if ($TargetDir.Count -eq 0 -and -not $Force) { exit 0 }
    exit 1
}

# -Force：把不存在的显式/候选根也创建出来
if ($Force) {
    $forceList = if ($TargetDir.Count -gt 0) { $TargetDir | ForEach-Object { Resolve-TargetPath $_ } } else {
        @((Join-Path $HOME '.codex\skills'), (Join-Path (Get-Location).Path '.agents\skills'), (Join-Path $HOME '.agents\skills'))
    }
    foreach ($f in $forceList) {
        if (-not (Test-Path -LiteralPath $f)) {
            if ($WhatIfPlan) {
                Write-Host "[PLAN] 将创建技能根目录：$f" -ForegroundColor Cyan
            } else {
                New-Item -ItemType Directory -Force -Path $f | Out-Null
                Write-Host "[..]   已创建技能根目录：$f" -ForegroundColor Gray
            }
            if (-not ($candidates | Where-Object { (Test-SamePath $_.Path $f) })) {
                $candidates += [pscustomobject]@{ Path = $f; Explicit = ($TargetDir.Count -gt 0) }
            }
        }
    }
}

Write-Head '开始注册'

$tally = @{ created = 0; exists = 0; failed = 0; skipped = 0 }
foreach ($c in $candidates) {
    $r = Invoke-SkillRoot $c.Path
    $tally[$r] = $tally[$r] + 1
}

# ── 汇总 ─────────────────────────────────────────────────────────────────────
Write-Head '汇总'

Write-Host ('  {0,-24} {1}' -f '技能根', '结果')
Write-Host ('  {0,-24} {1}' -f ('-' * 24), ('-' * 6))
foreach ($c in $candidates) {
    $link = Join-Path $c.Path $SkillName
    $state = '未知'
    if (Test-Path -LiteralPath (Join-Path $link 'SKILL.md')) { $state = '已就位' }
    elseif (Test-Path -LiteralPath $link) { $state = '条目存在但校验未过' }
    else { $state = '未创建' }
    Write-Host ('  {0,-24} {1}' -f $c.Path, $state)
}

Write-Host ''
Write-Host ("  新建 {0} 个 / 已存在 {1} 个 / 未覆盖 {2} 个 / 失败 {3} 个" -f `
    $tally['created'], $tally['exists'], $tally['skipped'], $tally['failed'])

if ($tally['failed'] -gt 0) {
    Write-Host ''
    Write-Host '  有失败项。按上面的提示手动复制即可；复制不影响后续步骤。' -ForegroundColor Yellow
}

# ── 下一步 ───────────────────────────────────────────────────────────────────
Write-Head '下一步'

Write-Host @"
本脚本只做「注册」（让 Agent 能发现这个技能）。技能要真的能跑，还必须过部署关 ——
这一步与框架无关，任何框架都跑同一段命令：

    cd "$AgentRoot"
    python 0路由/scripts/bootstrap.py check     # 只体检，不改动任何东西
    python 0路由/scripts/bootstrap.py plan      # 打印计划，等确认
    python 0路由/scripts/bootstrap.py apply     # 执行

部署关会依次打通：运行环境 → scansci-pdf → 目录与策略 → API key →
机构通道（Elsevier API / 高校 WebVPN）→ 网络与代理 → 抄通性验收（真下 1 篇 OA）。

通过后 workspace\state\deploy.json 里 ready 为 true，就可以用了：

    python 0路由/scripts/pipeline.py run --input "2020 年以来高被引的钙钛矿稳定性研究，要 20 篇"
    python 0路由/scripts/pipeline.py run --input dois.txt
    python 0路由/scripts/pipeline.py run --input refs.bib --no-search

环境体检（含代理自动探测）：

    python 0路由/scripts/doctor.py

验证接入成功：新开一个会话，问 Agent「你能看到 paperforge 技能吗？」
若看不到，见 0路由\adapters\ 下对应框架的说明。

提醒（真实踩过的坑）：
  * scansci-pdf 要求 Python >= 3.11
  * 机构登录 / 过 Cloudflare / sci-hub 竞速的浏览器通道需要可见浏览器。
    Playwright 走 Windows 命名管道，受限沙箱下会报 WinError 5 拒绝访问 ——
    请用普通终端运行，或放宽文件权限。
  * pip 安装需要能写系统临时目录。
"@

Write-Host ''
Write-Host '完成。' -ForegroundColor Green
exit 0
