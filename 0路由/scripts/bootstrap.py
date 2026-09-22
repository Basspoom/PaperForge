"""部署关：一次性把运行环境、上游工具、目录、密钥与机构通道全部打通。

    python 0路由/scripts/bootstrap.py check                  # 只体检，不改动
    python 0路由/scripts/bootstrap.py plan                   # 打印将要做的事
    python 0路由/scripts/bootstrap.py apply                  # 执行
    python 0路由/scripts/bootstrap.py apply --interactive     # 交互式问一遍

设计约束：
- apply 必须可重复执行（幂等），失败后能原地续跑。
- 需要写系统目录的步骤（Python 安装、pip 临时目录）在受限沙箱里会失败，
  因此这里对每一步都准备了降级路径，并把"必须放宽沙箱"的情况明确报出来。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C  # noqa: E402
import doctor as D  # noqa: E402
import policy as P  # noqa: E402

PROFILES: dict[str, dict] = {
    "safe":       {"label": "稳妥（低封禁风险）", "batch_workers": 2,  "request_delay_min": 5.0, "request_delay_max": 12.0},
    "balanced":   {"label": "均衡（默认）",       "batch_workers": 4,  "request_delay_min": 3.0, "request_delay_max": 8.0},
    "aggressive": {"label": "激进（最快，封 IP 风险高）", "batch_workers": 10, "request_delay_min": 2.0, "request_delay_max": 5.0},
}

DEFAULT_SMOKE_DOI = "10.48550/arXiv.1706.03762"   # Attention Is All You Need：稳定 OA


# ── Python 运行时 ────────────────────────────────────────────────────────────
def _uv_managed_pythons() -> list[Path]:
    root = C.WORKSPACE / ".uv-python"
    return sorted(Path(p) for p in glob.glob(str(root / "*" / "python.exe"))) + \
           sorted(Path(p) for p in glob.glob(str(root / "*" / "bin" / "python")))


def _base_python_candidates() -> list[Path]:
    cands: list[Path] = []
    cands += _uv_managed_pythons()

    def _version_of(exe: str | Path) -> tuple[int, int]:
        try:
            r = C.run([exe, "-c", "import sys;print(f'{sys.version_info[0]}.{sys.version_info[1]}')"], timeout=60)
            major, minor = (r.stdout or "0.0").strip().split(".")[:2]
            return int(major), int(minor)
        except Exception:  # noqa: BLE001
            return (0, 0)

    sys_exe = Path(sys.executable)
    if _version_of(sys_exe) >= (3, 11):
        cands.append(sys_exe)
    for name in ("python3.13", "python3.12", "python3.11", "python3"):
        exe = C.which(name)
        if exe:
            cands.append(Path(exe))
    if os.name == "nt":
        for launcher in ("py",):
            exe = C.which(launcher)
            if not exe:
                continue
            for spec in ("-3.13", "-3.12", "-3.11"):
                try:
                    r = C.run([exe, spec, "-c", "import sys;print(sys.executable)"], timeout=60)
                    if r.returncode == 0 and (r.stdout or "").strip():
                        cands.append(Path((r.stdout or "").strip()))
                except Exception:  # noqa: BLE001
                    pass

    seen, out = set(), []
    for c in cands:
        key = str(c).lower()
        if key not in seen and c.exists():
            seen.add(key)
            out.append(c)

    good = [(v, c) for c in out if (v := _version_of(c)) >= (3, 11)]
    good.sort(key=lambda t: t[0], reverse=True)
    return [c for _, c in good]


def install_uv_python(version: str = "3.12") -> tuple[bool, str]:
    uv = C.which("uv")
    if not uv:
        return False, "未安装 uv"
    C.info(f"用 uv 安装 Python {version} 到 {C.WORKSPACE / '.uv-python'}")
    r = C.run([uv, "python", "install", version], timeout=1800)
    if C.venv_python() is None and not _uv_managed_pythons():
        return False, (r.stderr or r.stdout or "").strip()[-400:]
    return bool(_uv_managed_pythons()), f"已安装到 {C.WORKSPACE / '.uv-python'}"


def venv_python_version() -> tuple[int, int]:
    py = C.venv_python()
    if not py:
        return (0, 0)
    r = C.run([py, "-c", "import sys;print(f'{sys.version_info[0]}.{sys.version_info[1]}')"], timeout=60)
    try:
        major, minor = (r.stdout or "0.0").strip().split(".")[:2]
        return int(major), int(minor)
    except Exception:  # noqa: BLE001
        return (0, 0)


def create_venv() -> tuple[bool, str]:
    """建 venv，逐级降级：uv → python -m venv → python -m venv --without-pip。"""
    if venv_python_version() >= (3, 11):
        return True, f"已存在（Python {venv_python_version()[0]}.{venv_python_version()[1]}）"

    if C.VENV_DIR.exists():
        shutil.rmtree(C.VENV_DIR, ignore_errors=True)

    uv = C.which("uv")
    if uv:
        C.info("尝试 uv venv")
        r = C.run([uv, "venv", "--python", "3.12", str(C.VENV_DIR)], timeout=900)
        if C.venv_python():
            return True, "uv venv"

    for base in _base_python_candidates():
        C.info(f"尝试 {base} -m venv")
        C.run([base, "-m", "venv", str(C.VENV_DIR)], timeout=900)
        if C.venv_python():
            return True, f"{base.name} -m venv"
        C.info(f"尝试 {base} -m venv --without-pip（沙箱下 ensurepip 常被拒）")
        C.run([base, "-m", "venv", "--without-pip", str(C.VENV_DIR)], timeout=900)
        if C.venv_python():
            return True, f"{base.name} -m venv --without-pip"

    return False, "没有可用的 Python 3.11+。安装一个再重试：winget install Python.Python.3.12"


def ensure_pip() -> tuple[bool, str]:
    """确保 venv 里有 pip。

    受限沙箱会拒绝 pip/ensurepip 写系统临时目录；最后一条兜底是直接把基础
    解释器里已有的 pip 复制进 venv——纯文件复制，不触发任何子进程。
    """
    vpy = C.venv_python()
    if not vpy:
        return False, "venv 不存在"

    if C.run([vpy, "-m", "pip", "--version"], timeout=120).returncode == 0:
        return True, "已就绪"

    C.info("venv 内没有 pip，尝试 ensurepip")
    r = C.run([vpy, "-m", "ensurepip", "--upgrade"], timeout=900)
    if C.run([vpy, "-m", "pip", "--version"], timeout=120).returncode == 0:
        return True, "ensurepip"

    C.info("ensurepip 失败，改用「从基础解释器复制 pip」兜底")
    cfg = C.read_json(C.VENV_DIR / "pyvenv.cfg", default=None)
    home = ""
    if isinstance(cfg, dict):
        home = str(cfg.get("home", ""))
    search_dirs = []
    if home:
        search_dirs += [Path(home) / "Lib" / "site-packages",
                        Path(home).parent / "lib" / f"python{venv_python_version()[0]}.{venv_python_version()[1]}" / "site-packages"]
    search_dirs += [Path(p) for p in _uv_managed_pythons()]
    for base in _base_python_candidates():
        search_dirs.append(Path(base).parent / "Lib" / "site-packages")

    dst_sp = (C.VENV_DIR / "Lib" / "site-packages") if os.name == "nt" else \
             (C.VENV_DIR / "lib" / f"python{venv_python_version()[0]}.{venv_python_version()[1]}" / "site-packages")
    dst_sp.mkdir(parents=True, exist_ok=True)

    for sp in search_dirs:
        if not sp.is_dir():
            continue
        found = list(sp.glob("pip")) + list(sp.glob("pip-*.dist-info"))
        if not found:
            continue
        for src in found:
            target = dst_sp / src.name
            if target.exists():
                continue
            if src.is_dir():
                shutil.copytree(src, target)
            else:
                shutil.copy2(src, target)
        if C.run([vpy, "-m", "pip", "--version"], timeout=120).returncode == 0:
            return True, f"从 {sp} 复制 pip"

    return False, ("venv 里装不上 pip。通常是沙箱/杀软挡住了临时目录写入——"
                   "在普通终端里重跑 bootstrap.py apply，或给该命令放宽文件权限。")


# ── 上游工具 ─────────────────────────────────────────────────────────────────
def install_scansci(source: str, extras: str = "fast,vpnsci") -> tuple[bool, str]:
    vpy = C.venv_python()
    if not vpy:
        return False, "venv 不存在"
    if source == "pypi":
        C.info(f"从 PyPI 安装 scansci-pdf[{extras}]（含编译核心，需要联网）")
        target = f"scansci-pdf[{extras}]"
        args = [vpy, "-m", "pip", "install", "--upgrade", target]
    else:
        C.info(f"从本地化快照安装 {C.VENDOR_DIR}[{extras}]（离线可复现，纯 Python 回退）")
        if not C.VENDOR_DIR.exists():
            return False, f"本地快照不存在：{C.VENDOR_DIR}；改用 --source pypi"
        args = [vpy, "-m", "pip", "install", "-e", f"{C.VENDOR_DIR}[{extras}]"]

    r = C.run(args, timeout=3600)
    text = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        tail = "\n".join(text.strip().splitlines()[-12:])
        hint = ""
        if "Permission denied" in text or "WinError 5" in text or "拒绝访问" in text:
            hint = ("\n提示：这是文件系统权限问题，不是依赖问题。受限沙箱/杀软会挡住 pip 写临时目录"
                    f"（{C.TMP_DIR}）。在普通终端里重跑本命令，或给该命令放宽文件权限。")
        return False, f"pip 安装失败：\n{tail}{hint}"
    return True, "已安装"


def install_browser_backend() -> tuple[bool, str]:
    """机构登录与 Cloudflare 绕过需要隐身浏览器后端。"""
    vpy = C.venv_python()
    if not vpy:
        return False, "venv 不存在"
    check = C.run([vpy, "-c",
                   "import importlib.util as u;print('patchright' if u.find_spec('patchright') else '')"], timeout=120)
    if (check.stdout or "").strip() == "patchright":
        return True, "patchright 已安装"
    C.info("安装 patchright（隐身浏览器后端，首次会下载 Chromium，约数百 MB）")
    r = C.run([vpy, "-m", "pip", "install", "patchright"], timeout=3600)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "").strip()[-300:]
    C.info("下载 patchright 的 Chromium 内核")
    C.run([vpy, "-m", "patchright", "install", "chromium"], timeout=3600)
    return True, "patchright + chromium"


# ── 配置固化 ─────────────────────────────────────────────────────────────────
def _academic_search_args() -> list[str]:
    """1学术查询（nature-academic-search）MCP 服务器的启动参数。

    照它自带的 `config/mcp-snippet.json` 来：用 uv 起一个**隔离依赖环境**
    （服务器要求 mcp 1.x，而 scansci-pdf 装的是 2.x，共用 venv 会冲突），
    `--directory` 指向它自己的 mcp-server 目录。
    """
    srv = C.SEARCH_DIR / "mcp-server"
    return [
        "run", "--no-project", "--directory", str(srv),
        "--with", "mcp>=1.0.0,<2.0.0",
        "--with", "requests>=2.28.0,<3.0.0",
        "--with", "toml>=0.10.2,<2.0.0",
        "--with", "lxml>=4.9.0,<6.0.0",
        "--with", "defusedxml>=0.7.1,<1.0.0",
        "--with", "pybliometrics>=4.4.1,<5.0.0",
        "python", "academic_search_server.py",
    ]


def write_mcp_json() -> tuple[bool, str]:
    """按当前安装路径生成仓库根的 .mcp.json。

    为什么由脚本生成而不是随仓库提交：这个文件必须含**本机绝对路径**
    （venv 里的 python、skill 的 workspace），提交一份带别人路径的版本既没用
    也会泄漏路径。模板 `.mcp.json.template` 入库，真实文件 gitignore。
    """
    tpl = C.AGENT_ROOT / ".mcp.json.template"
    out = C.AGENT_ROOT / ".mcp.json"
    if not tpl.exists():
        return False, f"找不到模板 {tpl}"

    # 用 Python 构造而不是对模板做字符串替换：模板里的 {{REPO}} 后面跟的是
    # 正斜杠，替换后会出现 "C:\\...\\智能体/workspace/..." 这种混用分隔符的路径。
    venv_py = C.venv_python() or (C.VENV_DIR / "Scripts" / "python.exe")
    payload = {
        "mcpServers": {
            # 下载引擎
            "scansci-pdf": {
                "command": str(venv_py),
                "args": ["-m", "scansci_pdf", "run"],
                "cwd": str(C.AGENT_ROOT),
                "env": {
                    "SCANSCI_PDF_DATA_DIR": str(C.SCANSCI_DATA_DIR),
                    "TMP": str(C.TMP_DIR),
                    "TEMP": str(C.TMP_DIR),
                    "PLAYWRIGHT_BROWSERS_PATH": str(C.WORKSPACE / ".browsers"),
                    "UV_CACHE_DIR": str(C.WORKSPACE / ".uv-cache"),
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                },
                "startup_timeout_sec": 120,
                "tool_timeout_sec": 1800,
            },
            # 检索：本地化的 nature-academic-search（1学术查询）
            # 模型按 1学术查询/SKILL.md 的 wf1 调用它的 search_papers 等工具，
            # 而不是让本 skill 的胶水代码去替它决定怎么检索。
            "academic-search": {
                "command": "uv",
                "args": _academic_search_args(),
                "cwd": str(C.SEARCH_DIR / "mcp-server"),
                "env": {
                    "UV_CACHE_DIR": str(C.WORKSPACE / ".uv-cache"),
                    "UV_PYTHON_INSTALL_DIR": str(C.WORKSPACE / ".uv-python"),
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "PUBMED_EMAIL": C.contact_email(),
                    "CROSSREF_MAILTO": C.contact_email(),
                },
                "startup_timeout_sec": 300,
                "tool_timeout_sec": 300,
            },
        }
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True, str(out)


def apply_vendor_patches() -> tuple[bool, str]:
    """把 2工程化下载/patches 里的补丁打上本地化上游副本。"""
    script = C.DOWNLOAD_DIR / "scripts" / "apply_patches.py"
    if not script.exists():
        return False, f"找不到补丁脚本 {script}"
    r = C.run([C.python_exe(), script], timeout=300)
    text = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return False, ("存在冲突，需人工核对 patches.json：\n"
                       + "\n".join(text.strip().splitlines()[-8:]))
    applied = [ln.strip() for ln in text.splitlines() if "已应用" in ln and "跳过" not in ln]
    skipped = sum(1 for ln in text.splitlines() if "跳过" in ln)
    return True, f"新应用 {len(applied)} 条，已就位 {skipped} 条"


def build_config(args: argparse.Namespace, existing: dict) -> dict:
    cfg = dict(existing)
    prof = PROFILES[args.profile]

    def pick(cli_value, key, default=None):
        if cli_value not in (None, ""):
            return cli_value
        return cfg.get(key, default)

    cfg.update({
        "email": pick(args.email, "email", "anonymous@example.invalid"),
        "output_dir": str(C.PDF_DIR),
        "cache_dir": str(C.SCANSCI_DATA_DIR / "cache"),
        "network_proxy": pick(args.proxy, "network_proxy", ""),

        # 上游把 WebVPN cookie 的读写路径写成了两个不同的文件：
        #   登录写入 browser_login.webvpn_login → <cache_dir>/instsci-cookies.json
        #   下载读取 auth._get_cookie_path    → <data_dir>/cookies/webvpn-cookies.json
        # 结果是「登录成功」但下载永远报 "All saved cookies have expired."
        # auth.py 认 instsci_cookie_file 这个键，配上它就能把两条路径对齐——不用改源码。
        "instsci_cookie_file": str(C.SCANSCI_DATA_DIR / "cache" / "instsci-cookies.json"),

        # 硬约束：本 skill 的输出契约要求 DOI 命名 + 全部 PDF 落在一个目录
        "auto_rename": False,
        # Agent 场景不要弹 GUI 悬浮窗
        "progress_bar_auto": False,
        # 竞速浏览器无头，减少窗口闪烁；机构登录仍保留可见窗口
        "scihub_browser_headless": True,
        "browser_headless": False,

        "batch_workers": prof["batch_workers"],
        "request_delay_min": prof["request_delay_min"],
        "request_delay_max": prof["request_delay_max"],
    })

    school = pick(args.school, "vpnsci_school", "")
    if school:
        cfg["vpnsci_school"] = school
        cfg["vpnsci_enabled"] = True
    elif args.no_school:
        cfg["vpnsci_enabled"] = False

    if args.elsevier_key:
        cfg["elsevier_api_key"] = args.elsevier_key.strip()
    if args.springer_key:
        cfg["springer_api_key"] = args.springer_key.strip()
    return cfg


# ── 抄通性验收 ───────────────────────────────────────────────────────────────
def smoke_test(doi: str, timeout: float = 900) -> dict:
    C.step("抄通性验收：真下 1 篇")
    C.info(f"目标：{doi}")
    target_file = C.PDF_DIR / (C.identifier_to_filename(doi) + ".pdf")
    r = C.scansci_pdf(["get", doi, "--output", str(C.PDF_DIR)], timeout=timeout, echo=True)
    found = sorted(C.PDF_DIR.glob(f"{C.identifier_to_filename(doi)}*.pdf"))
    others = [p for p in C.PDF_DIR.glob("*.pdf") if p not in found]
    okk = r.returncode == 0 and (found or others)
    result = {
        "doi": doi,
        "success": okk,
        "returncode": r.returncode,
        "files": [str(p) for p in (found + others)],
        "stdout_tail": "\n".join((r.stdout or "").strip().splitlines()[-15:]),
        "stderr_tail": "\n".join((r.stderr or "").strip().splitlines()[-15:]),
    }
    if okk:
        C.ok(f"下载成功：{result['files'][0]}")
    else:
        C.bad("验收未通过。常见原因：网络、代理、灰色源被墙、或该 DOI 需要机构权限。")
        for line in result["stderr_tail"].splitlines()[-6:]:
            C.info(line)
    return result


# ── 主流程 ───────────────────────────────────────────────────────────────────
def cmd_check(args: argparse.Namespace) -> int:
    report = D.full_report(args.email or "", args.proxy or "")
    D.print_report(report)
    return 0 if report["ok"] else 1


def cmd_plan(args: argparse.Namespace) -> int:
    C.step("部署计划（这一步不改动任何东西）")
    C.say(f"""
  目标目录    : {C.AGENT_ROOT}
  运行环境    : {C.WORKSPACE / '.venv'}（Python 3.11+；优先用 uv 装 3.12 到 workspace 内）
  上游工具    : scansci-pdf，来源 = {args.source}
  工作目录    : {C.PDF_DIR}（所有 PDF 集中于此，DOI 命名）
  缓存目录    : {C.SCANSCI_DATA_DIR}
  日志目录    : {C.LOGS_DIR}

  将要固化的配置：
    output_dir              = {C.PDF_DIR}
    cache_dir               = {C.SCANSCI_DATA_DIR / 'cache'}
    auto_rename             = False           ← 必须关，否则文件名是「作者年份_标题」而不是 DOI
    progress_bar_auto       = False           ← Agent 场景不弹 GUI
    scihub_browser_headless = True
    batch_workers           = {PROFILES[args.profile]['batch_workers']}（档位 {args.profile}）
    request_delay           = {PROFILES[args.profile]['request_delay_min']}–{PROFILES[args.profile]['request_delay_max']} 秒
    network_proxy           = {args.proxy or '(自动探测)'}
    email                   = {args.email or '(未提供，会拖低 OpenAlex/Unpaywall 配额)'}
    vpnsci_school           = {args.school or '(未提供 → 没有机构通道，付费墙论文会失败)'}
    elsevier_api_key        = {'已提供' if args.elsevier_key else '(未提供 → Elsevier 论文慢 15–30 秒/篇)'}

  策略档位    : {args.policy} — {P.POLICIES[args.policy]['label']}
               {P.POLICIES[args.policy]['note']}
  隐身浏览器  : {'安装 patchright（约数百 MB Chromium 下载）' if args.browser else '跳过（只走 OA 直连可以跳过）'}
  抄通性验收  : {'真下 1 篇 ' + args.smoke_doi if not args.skip_smoke else '跳过'}

  执行：python 0路由/scripts/bootstrap.py apply""" + " " + " ".join(a for a in [
        f"--profile {args.profile}" if args.profile != "balanced" else "",
        f"--policy {args.policy}" if args.policy != "max" else "",
        f"--email {args.email}" if args.email else "",
        f"--school {args.school}" if args.school else "",
        f"--proxy {args.proxy}" if args.proxy else "",
        f"--source {args.source}" if args.source != "vendor" else "",
        "--browser" if args.browser else "",
        "--skip-smoke" if args.skip_smoke else "",
    ] if a))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    C.ensure_dirs()
    C.step("部署关 · 执行")
    steps: list[dict] = []

    def record(name: str, okk: bool, detail: str) -> bool:
        steps.append({"step": name, "ok": okk, "detail": detail})
        (C.ok if okk else C.bad)(f"{name}: {detail}")
        return okk

    # 1. Python 运行时 ------------------------------------------------------
    if venv_python_version() < (3, 11):
        if C.which("uv"):
            okk, detail = install_uv_python("3.12")
            record("Python 3.12", okk, detail)
        else:
            record("Python 3.12", False, "没有 uv；将尝试用系统 Python 建 venv")
    okk, detail = create_venv()
    if not record("venv", okk, detail):
        return _finish(steps, ok=False)

    # 2. pip ---------------------------------------------------------------
    okk, detail = ensure_pip()
    if not record("pip", okk, detail):
        return _finish(steps, ok=False)

    # 3. 上游工具 -----------------------------------------------------------
    if args.skip_install:
        record("scansci-pdf", True, "按参数跳过安装（复用已有环境）")
    else:
        okk, detail = install_scansci(args.source)
        if not record("scansci-pdf", okk, detail):
            return _finish(steps, ok=False)

    # 4. 上游补丁 -----------------------------------------------------------
    # vendor/ 保持与上游逐字一致；我们对上游的必要修复只以显式补丁存在。
    # 不打补丁的话，浏览器与机构通道会直接不可用（见 2工程化下载/patches/patches.json）。
    okk, detail = apply_vendor_patches()
    record("上游补丁", okk, detail)

    # 5. 浏览器后端（可选） --------------------------------------------------
    if args.browser:
        okk, detail = install_browser_backend()
        record("隐身浏览器", okk, detail)
    else:
        record("隐身浏览器", True, "按参数跳过")

    # 6. 配置固化 -----------------------------------------------------------
    cfg_path = P.scansci_config_path()
    existing = P.load_scansci_config()
    cfg = build_config(args, existing)
    P.save_scansci_config(cfg)
    record("配置固化", True, f"{cfg_path}（auto_rename=False, output_dir={cfg['output_dir']}）")

    # 7. 策略档位 -----------------------------------------------------------
    result = P.apply_policy(args.policy)
    record("策略档位", True, f"{result['label']}（scihub_enabled={result['after']['scihub_enabled']}, "
                             f"strategy={result['after']['download_strategy']}）")

    # 8. 跨框架 MCP 配置 ------------------------------------------------------
    okk, detail = write_mcp_json()
    record("MCP 配置", okk, detail)

    # 7. 体检 ---------------------------------------------------------------
    report = D.full_report(cfg.get("email", ""), cfg.get("network_proxy", ""), verbose_proxy=False)
    C.write_json(C.STATE_DIR / "doctor.json", report)
    D.print_report(report)
    record("体检", report["ok"], "通过" if report["ok"] else "有 FAIL 项（见上）")

    # 8. 抄通性验收 ---------------------------------------------------------
    smoke = {}
    if not args.skip_smoke:
        smoke = smoke_test(args.smoke_doi)
        record("抄通性验收", smoke["success"], smoke["files"][0] if smoke.get("files") else "未产出 PDF")

    ready = all(s["ok"] for s in steps if s["step"] != "体检")
    return _finish(steps, ok=ready, extra={"smoke": smoke, "doctor_ok": report["ok"],
                                           "policy": args.policy, "source": args.source})


def _finish(steps: list[dict], ok: bool, extra: dict | None = None) -> int:
    payload = {
        "ready": ok,
        "deployed_at": C.utcnow(),
        "skill_version": C.SKILL_VERSION,
        "agent_root": str(C.AGENT_ROOT),
        "python": str(C.venv_python() or ""),
        "steps": steps,
        **(extra or {}),
    }
    C.write_json(C.DEPLOY_STATE, payload)
    C.step("结论")
    if ok:
        C.ok("部署关通过。现在可以用了：")
        C.info("python 0路由/scripts/pipeline.py run --input \"<检索需求或清单文件>\"")
    else:
        C.bad("部署关未通过。修掉上面的 [FAIL] 项后重跑 apply（可重复执行）。")
        C.info(f"状态已写入 {C.DEPLOY_STATE}")
    return 0 if ok else 1


def main() -> int:
    C.console()
    ap = argparse.ArgumentParser(description="文献获取智能体 · 部署关")
    ap.add_argument("cmd", choices=["check", "plan", "apply"], help="check=只体检 / plan=打印计划 / apply=执行")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="balanced", help="并发与延迟档位")
    ap.add_argument("--policy", choices=sorted(P.POLICIES), default="legal", help="下载策略档位")
    ap.add_argument("--source", choices=["vendor", "pypi"], default=os.environ.get("SCANSCI_PDF_SOURCE", "vendor"),
                    help="scansci-pdf 来源：vendor=本地快照（默认，纯 Python）/ pypi=上游最新（含编译核心）")
    ap.add_argument("--email", default="", help="联系邮箱（OpenAlex/Unpaywall 礼貌池，强烈建议填）")
    ap.add_argument("--school", default="", help="WebVPN 学校全称，例如「中国科学技术大学」")
    ap.add_argument("--no-school", action="store_true", help="显式关闭 WebVPN")
    ap.add_argument("--proxy", default="", help="HTTP(S) 代理，例如 http://127.0.0.1:7890")
    ap.add_argument("--elsevier-key", default="", help="Elsevier / ScienceDirect API Key")
    ap.add_argument("--springer-key", default="", help="Springer Nature TDM API Key")
    ap.add_argument("--browser", action="store_true", help="安装隐身浏览器后端（机构登录 / 过 Cloudflare 需要）")
    ap.add_argument("--skip-smoke", action="store_true", help="跳过「真下 1 篇」的抄通性验收")
    ap.add_argument("--skip-install", action="store_true", help="跳过 pip 安装（只重新固化配置与策略）")
    ap.add_argument("--smoke-doi", default=DEFAULT_SMOKE_DOI, help="验收用的 OA DOI")
    ap.add_argument("--interactive", action="store_true", help="交互式逐项询问")
    args = ap.parse_args()

    if args.interactive and args.cmd == "apply":
        args.email = args.email or _ask("联系邮箱（OpenAlex/Unpaywall 用，直接回车跳过）: ")
        args.school = args.school or _ask("WebVPN 学校全称（回车跳过）: ")
        args.proxy = args.proxy or _ask("HTTP 代理（回车=自动探测）: ")
        args.elsevier_key = args.elsevier_key or _ask("Elsevier API Key（回车跳过）: ")
        if not args.browser:
            args.browser = _ask_yes("安装隐身浏览器后端（机构登录用，需下载 Chromium）? [y/N] ")

    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "plan":
        return cmd_plan(args)
    return cmd_apply(args)


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _ask_yes(prompt: str) -> bool:
    return _ask(prompt).lower() in ("y", "yes")


if __name__ == "__main__":
    raise SystemExit(main())
