#!/usr/bin/env bash
#
# 把本仓库（paperforge 文献获取技能）注册到各个 Agent 框架的技能根目录。
#
# 技能发现要求目录布局是 <技能根>/<name>/SKILL.md，其中 <name> 必须等于
# SKILL.md frontmatter 里的 name（本仓库是 paperforge）。
# 而本仓库目录名是中文「智能体」，所以必须在技能根下建一个名为
# paperforge 的软链接指向本目录。
#
# 本脚本：
#   1. 按顺序尝试一批候选技能根，**只处理已经存在的**（不无中生有地造目录树）；
#   2. 幂等 —— 重复执行不报错、不重复创建、已指向本仓库的链接会被跳过；
#   3. 链接创建失败（权限不足等）时降级为「打印精确的手动复制命令」，不中断其它目标；
#   4. 结束前打印「下一步该跑什么」。
#
# 用法：
#   bash 0路由/scripts/install.sh
#   bash 0路由/scripts/install.sh --target-dir "$HOME/.config/opencode/skill"
#   bash 0路由/scripts/install.sh --force
#   bash 0路由/scripts/install.sh --plan
#
# 说明：~/.codex/skills 已在一个真实的 Codex 安装中核对到（该目录下真实存在
# 16 个技能目录，每个根下就是 SKILL.md）。其它候选根是否被对应框架读取，
# 请以各框架实际技能列表为准，详见 0路由/adapters/ 下的适配说明。
#
# 实现说明：刻意使用 bash 数组而非「换行分隔的字符串 + IFS 切割」来保存路径，
# 以免路径里含空格或通配符时被误拆。

# 注意：刻意不使用 `set -u`，因为某些 shell 下未定义变量会导致脚本静默退出。
set -o pipefail 2>/dev/null || true

# ── 基本量 ───────────────────────────────────────────────────────────────────
# 本脚本在 <仓库根>/0路由/scripts/ 下，往上三级就是仓库根。
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AGENT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

# 技能名必须与 SKILL.md frontmatter 的 name 一致，否则技能发现认不出来。
SKILL_NAME='paperforge'

SKILL_MD="$AGENT_ROOT/SKILL.md"
if [ ! -f "$SKILL_MD" ]; then
    printf '[FAIL] 在 %s 下找不到 SKILL.md —— 本脚本必须放在 <仓库根>/0路由/scripts/ 里。\n' "$AGENT_ROOT" >&2
    exit 1
fi

# 从 frontmatter 里读出真实的 name，与预期值比对（读不到就只警告，不阻断）。
DECLARED=$(sed -n '1,12p' "$SKILL_MD" 2>/dev/null \
    | sed -n "s/^[[:space:]]*name[[:space:]]*:[[:space:]]*//p" \
    | head -n 1 \
    | sed "s/^[\"']//; s/[\"'][[:space:]]*$//; s/[[:space:]]*$//")
if [ -n "$DECLARED" ] && [ "$DECLARED" != "$SKILL_NAME" ]; then
    printf '[WARN] SKILL.md 里的 name 是 %s，与脚本预期的 %s 不一致。\n' "$DECLARED" "$SKILL_NAME"
    printf '       将以 %s 作为链接名（技能发现要求目录名 == name）。\n' "$DECLARED"
    SKILL_NAME="$DECLARED"
fi

# ── 输出工具 ─────────────────────────────────────────────────────────────────
head_line() { printf '\n=== %s ===\n' "$1"; }

# 生成「手动复制」的精确命令，链接创建失败时用。
manual_copy_hint() {
    link="$1"
    parent=$(dirname -- "$link")
    printf '       链接创建失败（通常是权限不足）。降级方案 —— 手动复制，逐条执行：\n'
    printf '\n'
    printf '         mkdir -p "%s"\n' "$parent"
    printf '         cp -a "%s" "%s"\n' "$AGENT_ROOT" "$link"
    printf '\n'
    printf '       若想排除运行产物（PDF、venv、浏览器内核，可达数 GB），用带 --exclude 的 tar：\n'
    printf '         mkdir -p "%s"\n' "$link"
    printf '         tar -C "%s" --exclude=workspace --exclude=.git --exclude=.tmp \\\n' "$AGENT_ROOT"
    printf '             -cf - . | tar -C "%s" -xf -\n' "$link"
    printf '\n'
    printf '       注意：复制出来的是一份快照，以后改了本仓库要重新复制一次。\n'
}

# 把 ~ 展开成 $HOME
expand_home() {
    case "$1" in
        '~') printf '%s' "$HOME" ;;
        '~/'*) printf '%s/%s' "$HOME" "${1#\~/}" ;;
        *) printf '%s' "$1" ;;
    esac
}

# ── 参数解析 ─────────────────────────────────────────────────────────────────
TARGET_DIRS=()
FORCE=0
PLAN=0
while [ $# -gt 0 ]; do
    case "$1" in
        --target-dir)
            if [ -z "${2:-}" ]; then printf '[FAIL] --target-dir 后面要跟一个路径。\n' >&2; exit 1; fi
            TARGET_DIRS+=("$2")
            shift 2
            ;;
        --target-dir=*)
            TARGET_DIRS+=("${1#--target-dir=}")
            shift
            ;;
        --force|-f) FORCE=1; shift ;;
        --plan|--dry-run|-n) PLAN=1; shift ;;
        -h|--help)
            sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            printf '[FAIL] 不认识的参数：%s（用 --help 看用法）\n' "$1" >&2
            exit 1
            ;;
    esac
done

printf '=========================================\n'
printf ' paperforge 跨框架安装脚本\n'
printf '=========================================\n\n'
printf '仓库根   : %s\n' "$AGENT_ROOT"
printf '技能名   : %s\n' "$SKILL_NAME"
printf 'DSH_HOME : %s\n' "${DSH_HOME:-(未设置)}"

if [ "$PLAN" -eq 1 ]; then
    printf '\n*** --plan：只打印计划，不做任何改动 ***\n'
fi

# ── 组装候选技能根（bash 数组，天然支持含空格的路径） ────────────────────────
CANDIDATES=()

add_candidate() {
    candidate="$1"
    if [ "${#CANDIDATES[@]}" -gt 0 ]; then
        for existing in "${CANDIDATES[@]}"; do
            [ "$existing" = "$candidate" ] && return 0
        done
    fi
    CANDIDATES+=("$candidate")
}

if [ "${#TARGET_DIRS[@]}" -gt 0 ]; then
    head_line '显式指定的技能根（--target-dir）'
    for t in "${TARGET_DIRS[@]}"; do
        add_candidate "$(expand_home "$t")"
    done
else
    DSH_HOME_DIR="${DSH_HOME:-$HOME/.dsh}"
    # 顺序：实机核对过的 Codex 技能根优先，其次项目级，再用户级。
    # [ -d ] 会跟随符号链接，符合预期。
    for r in \
        "$HOME/.codex/skills" \
        "$PWD/.dsh/skills" \
        "$PWD/.agents/skills" \
        "$DSH_HOME_DIR/skills" \
        "$HOME/.agents/skills" \
        "$HOME/.claude/skills" \
        "$HOME/plugins"
    do
        [ -d "$r" ] && add_candidate "$r"
    done
fi

# -Force：把候选根里不存在的也创建出来
if [ "$FORCE" -eq 1 ]; then
    if [ "${#TARGET_DIRS[@]}" -gt 0 ]; then
        force_list=("${TARGET_DIRS[@]}")
    else
        force_list=("$HOME/.codex/skills" "$PWD/.agents/skills" "$HOME/.agents/skills")
    fi
    for f in "${force_list[@]}"; do
        f=$(expand_home "$f")
        if [ ! -d "$f" ]; then
            if [ "$PLAN" -eq 1 ]; then
                printf '[PLAN] 将创建技能根目录：%s\n' "$f"
            elif mkdir -p -- "$f" 2>/dev/null; then
                printf '[..]   已创建技能根目录：%s\n' "$f"
            else
                printf '[FAIL] 无法创建技能根目录：%s\n' "$f" >&2
                continue
            fi
        fi
        add_candidate "$f"
    done
fi

if [ "${#CANDIDATES[@]}" -eq 0 ]; then
    head_line '结果'
    if [ "${#TARGET_DIRS[@]}" -gt 0 ]; then
        printf '[FAIL] 指定的技能根不存在，且未加 --force。\n' >&2
        exit 1
    fi
    printf '没有找到任何「已存在」的技能根，因此没有改动任何东西。\n\n'
    printf '这不一定代表框架没装 —— 也可能是它还没创建过技能目录。两种选择：\n'
    printf '  a) 先在该框架里用一次技能功能，让它自己把技能目录建出来，再重跑本脚本；\n'
    printf '  b) 用 --target-dir 显式指定要注册的技能根，例如：\n'
    printf '       bash 0路由/scripts/install.sh --target-dir "$HOME/.codex/skills"\n'
    printf '  c) 或加 --force 让脚本自己创建三个常用候选目录：\n'
    printf '       bash 0路由/scripts/install.sh --force\n'
    exit 0
fi

# ── 逐个注册 ─────────────────────────────────────────────────────────────────
head_line '开始注册'

CREATED=0; EXISTS=0; FAILED=0; SKIPPED=0

for root in "${CANDIDATES[@]}"; do
    root=$(expand_home "$root")
    link="$root/$SKILL_NAME"

    printf '\n--- 技能根: %s\n' "$root"

    # 1) 已经存在同名软链接
    if [ -L "$link" ]; then
        # 读出现有链接指向哪里（BSD readlink 没有 -f，这里只用最基础的形态）
        current=$(readlink -- "$link" 2>/dev/null || true)
        if [ "$current" = "$AGENT_ROOT" ]; then
            printf '    [OK]   已存在且指向本仓库，跳过：%s -> %s\n' "$link" "$current"
            EXISTS=$((EXISTS + 1))
            continue
        fi
        printf '    [WARN] 已存在但指向别处：%s -> %s\n' "$link" "$current"
        if [ "$PLAN" -eq 1 ]; then
            printf '    [PLAN] 会重建该链接指向本仓库\n'
            CREATED=$((CREATED + 1))
            continue
        fi
        # 只删链接本身（rm -f 对符号链接只删链接，不动目标内容）
        if rm -f -- "$link" 2>/dev/null; then
            printf '    [..]   已移除旧链接，准备重建\n'
        else
            printf '    [FAIL] 无法移除旧链接\n'
            manual_copy_hint "$link"
            FAILED=$((FAILED + 1))
            continue
        fi

    # 2) 已存在同名真实目录/文件：可能是用户手动复制的，或另一个同名技能。绝不擅自删除。
    elif [ -e "$link" ]; then
        printf '    [WARN] 已存在同名真实目录（不是链接），为安全起见不覆盖：%s\n' "$link"
        printf '           若确认它就是要替换的旧副本，请手动删除后重跑本脚本。\n'
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # 3) 创建软链接
    if [ "$PLAN" -eq 1 ]; then
        printf '    [PLAN] 将创建软链接：%s -> %s\n' "$link" "$AGENT_ROOT"
        CREATED=$((CREATED + 1))
        continue
    fi

    # 目标父目录必须存在，否则 ln 会失败（候选根已保证存在，这里双保险）
    mkdir -p -- "$root" 2>/dev/null || true

    if ! ln -s -- "$AGENT_ROOT" "$link" 2>/dev/null; then
        printf '    [FAIL] 创建软链接失败（可能是权限不足，或文件系统不支持符号链接，如部分 Windows 挂载盘）\n'
        manual_copy_hint "$link"
        FAILED=$((FAILED + 1))
        continue
    fi

    # 4) 校验 <技能根>/<name>/SKILL.md 是否真的成立
    if [ -f "$link/SKILL.md" ]; then
        printf '    [OK]   已创建：%s -> %s\n' "$link" "$AGENT_ROOT"
        printf '           校验通过：%s/SKILL.md\n' "$link"
        CREATED=$((CREATED + 1))
    else
        printf '    [WARN] 链接已创建，但经链接读不到 SKILL.md。\n'
        printf '           部分工具的目录扫描不跟随符号链接，此时请改用上面的手动复制方案。\n'
        FAILED=$((FAILED + 1))
    fi
done

# ── 汇总 ─────────────────────────────────────────────────────────────────────
head_line '汇总'

printf '  %-40s %s\n' '技能根' '结果'
printf '  %-40s %s\n' '----------------------------------------' '------'
for root in "${CANDIDATES[@]}"; do
    root=$(expand_home "$root")
    link="$root/$SKILL_NAME"
    if [ -f "$link/SKILL.md" ]; then
        state='已就位'
    elif [ -e "$link" ] || [ -L "$link" ]; then
        state='条目存在但校验未过'
    else
        state='未创建'
    fi
    printf '  %-40s %s\n' "$root" "$state"
done

printf '\n  新建 %s 个 / 已存在 %s 个 / 未覆盖 %s 个 / 失败 %s 个\n' \
    "$CREATED" "$EXISTS" "$SKIPPED" "$FAILED"

if [ "$FAILED" -gt 0 ]; then
    printf '\n  有失败项。按上面的提示手动复制即可；复制不影响后续步骤。\n'
fi

# ── 下一步 ───────────────────────────────────────────────────────────────────
head_line '下一步'

cat <<EOF
本脚本只做「注册」（让 Agent 能发现这个技能）。技能要真的能跑，还必须过部署关 ——
这一步与框架无关，任何框架都跑同一段命令：

    cd "$AGENT_ROOT"
    python 0路由/scripts/bootstrap.py check     # 只体检，不改动任何东西
    python 0路由/scripts/bootstrap.py plan      # 打印计划，等确认
    python 0路由/scripts/bootstrap.py apply     # 执行

部署关会依次打通：运行环境 → scansci-pdf → 目录与策略 → API key →
机构通道（Elsevier API / 高校 WebVPN）→ 网络与代理 → 抄通性验收（真下 1 篇 OA）。

通过后 workspace/state/deploy.json 里 ready 为 true，就可以用了：

    python 0路由/scripts/pipeline.py run --input "2020 年以来高被引的钙钛矿稳定性研究，要 20 篇"
    python 0路由/scripts/pipeline.py run --input dois.txt
    python 0路由/scripts/pipeline.py run --input refs.bib --no-search

环境体检（含代理自动探测）：

    python 0路由/scripts/doctor.py

验证接入成功：新开一个会话，问 Agent「你能看到 paperforge 技能吗？」
若看不到，见 0路由/adapters/ 下对应框架的说明。

提醒（真实踩过的坑）：
  * scansci-pdf 要求 Python >= 3.11
  * 机构登录 / 过 Cloudflare / sci-hub 竞速的浏览器通道需要可见浏览器。
    受限沙箱下浏览器驱动通信会被拒（Windows 上表现为 WinError 5 拒绝访问）——
    请用普通终端运行，或放宽文件权限。
  * pip 安装需要能写系统临时目录。
EOF

printf '\n完成。\n'
exit 0
