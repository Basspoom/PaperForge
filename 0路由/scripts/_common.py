"""共享基础层：路径解析、子进程环境、JSON/JSONL 读写、日志与结果契约。

本模块被 0路由/scripts/ 下的所有脚本导入。它不依赖任何第三方包，
只用 Python 3.9+ 标准库，因此即使 venv 还没建好也能被导入。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

# ── 路径 ─────────────────────────────────────────────────────────────────────
# 0路由/scripts/_common.py -> scripts -> 0路由 -> 智能体(=仓库根=skill bundle 根)
SCRIPTS_DIR = Path(__file__).resolve().parent
ROUTER_DIR = SCRIPTS_DIR.parent
AGENT_ROOT = ROUTER_DIR.parent

WORKSPACE = AGENT_ROOT / "workspace"
PDF_DIR = WORKSPACE / "pdfs"
LOGS_DIR = WORKSPACE / "logs"
STATE_DIR = WORKSPACE / "state"
TMP_DIR = WORKSPACE / ".tmp"
VENV_DIR = WORKSPACE / ".venv"
SCANSCI_DATA_DIR = WORKSPACE / "scansci-pdf"

# 同一 DOI 的多余副本的存放位置（在 PDF 目录旁边）
ALTERNATES_DIR = WORKSPACE / "pdf_alternates"

SEARCH_DIR = AGENT_ROOT / "1学术查询"
DOWNLOAD_DIR = AGENT_ROOT / "2工程化下载"
VENDOR_DIR = DOWNLOAD_DIR / "vendor" / "scansci-pdf"

DEPLOY_STATE = STATE_DIR / "deploy.json"
CONFIG_STATE = STATE_DIR / "config.json"
DEFAULT_QUEUE = STATE_DIR / "queue.json"

# ── V2 新增：下载层策略与本地依赖 ────────────────────────────────────────────
# downloads.json 决定授权工程化来源与可选实验性来源的层级策略。
DOWNLOADS_CONFIG = ROUTER_DIR / "downloads.json"

# 没有 venv 时用的纯 Python 依赖目录（requests / beautifulsoup4）。
# 为什么不再新建 venv：本机沙箱拒绝执行 workspace 内新建的解释器二进制，
# 与其和沙箱斗，不如把依赖装进一个普通目录，用 PYTHONPATH 挂上去。
PKG_LIB_DIR = AGENT_ROOT / ".pylib"

# 已装扫描科学引擎的 site-packages 回退路径（本机 venv 不可执行时的兜底）。
# Optional local fallback paths may be supplied through configuration or
# PYTHONPATH. Never bake a workstation-specific path into a cloneable skill.
SCANSCI_FALLBACK_PATHS: list[Path] = []


def load_downloads_config() -> dict:
    """读下载层策略；文件缺失时给一份安全默认值。"""
    cfg = read_json(DOWNLOADS_CONFIG, default=None)
    if not isinstance(cfg, dict):
        return {
            "fulltext": {"order": ["engineering"],
                         "scihub": {"enabled": False, "mirrors": [], "max_page_tries": 10}},
            "supplement": {"order": ["engineering"], "engineering_args": ["--si"]},
            "engineering": {},
            "gates": {"confirm_before_batch": True},
        }
    return cfg


def import_scihub():
    """导入 scihub 模块（必要时把 .pylib 挂到 sys.path 上）。"""
    init_pylib()
    import scihub  # noqa: PLC0415
    return scihub


def init_pylib() -> None:
    """把本仓库的纯 Python 依赖目录挂到 sys.path 上（幂等）。

    为什么不用 venv：本机沙箱拒绝执行 workspace 内新建的解释器二进制，
    venv 建得出来却跑不了；依赖装在普通目录里用路径挂载则完全不受影响。
    """
    if PKG_LIB_DIR.is_dir() and str(PKG_LIB_DIR) not in sys.path:
        sys.path.insert(0, str(PKG_LIB_DIR))


# 模块级自动挂载：任何 import _common 的脚本都自动拿到 requests / bs4 等依赖，
# 不必每个入口都记得调一次。
init_pylib()



def set_output_dir(path: str | Path) -> Path:
    """把交付物目录改到别处（`pipeline.py run --out-dir`）。

    默认所有产物都落在 skill 自己的 `workspace/` 下——那是"技能自己的家"。
    但用户经常想把某次任务的成果直接放到自己的目录里。这个函数把
    **PDF、元信息表、失败清单、日志**一起搬过去，而**任务状态**
    （queue.json / deploy.json / 配置）仍留在 workspace/：
    状态是技能的运行记忆，不是交付物。

    产出布局（自包含，可以直接整目录交出去）：
        <dir>/*.pdf                 所有 PDF，DOI 命名
        <dir>/metadata.csv|.xlsx|.md 元信息表
        <dir>/failures.md           失败清单与重试建议
        <dir>/doi_index.json        DOI → 文件索引
        <dir>/pdf_alternates/       同一 DOI 的多余副本
        <dir>/logs/                 运行日志
    """
    global PDF_DIR, LOGS_DIR, ALTERNATES_DIR
    PDF_DIR = Path(path).expanduser().resolve()
    LOGS_DIR = PDF_DIR / "logs"
    ALTERNATES_DIR = PDF_DIR / "pdf_alternates"
    ensure_dirs()
    return PDF_DIR

# ── 版本与常量 ───────────────────────────────────────────────────────────────
SCHEMA_VERSION = 1
SKILL_VERSION = (AGENT_ROOT / "VERSION").read_text(encoding="utf-8").strip() if (AGENT_ROOT / "VERSION").exists() else "0.0.0"

# 失败原因分类（契约的一部分，改动需同步 0路由/contract.md）
REASONS = (
    "not_found",             # 各源都找不到这篇文献的可下载副本
    "paywalled_no_access",   # 找到落地页但有付费墙，且当前没有可用机构通道
    "ip_blocked",            # 出版商封禁出口 IP（403 / ACS block page / 429 持续）
    "cf_challenge",          # Cloudflare / CAPTCHA / Turnstile 拦截
    "network",               # 超时、DNS、TLS、代理等网络层失败
    "bad_identifier",        # DOI / arXiv 号本身无效或无法解析
    "file_missing",          # 声称成功但磁盘上没有有效 PDF
    "duplicate",             # 与队列中已有条目重复
    "unsupported",           # 输入类型或来源当前不支持
    "unknown",               # 未归类
)

STATUS_OK = "success"
STATUS_FAIL = "failed"
STATUS_SKIP = "skipped"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ── 控制台 ───────────────────────────────────────────────────────────────────
def console() -> None:
    """Windows 控制台默认 cp936，中文与符号会乱码；强制 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(msg: str) -> None:
    say(f"\n=== {msg} ===")


def ok(msg: str) -> None:
    say(f"  [OK]   {msg}")


def warn(msg: str) -> None:
    say(f"  [WARN] {msg}")


def bad(msg: str) -> None:
    say(f"  [FAIL] {msg}")


def info(msg: str) -> None:
    say(f"  [..]   {msg}")


# ── 目录与 JSON ──────────────────────────────────────────────────────────────
def ensure_dirs() -> None:
    """确保所有需要的目录存在。

    注意每个模块函数都读**模块级变量**（PDF_DIR 等）而不是把它们当参数传，
    所以 `set_output_dir()` 改完变量后，后续所有阶段自动跟着走。
    """
    for d in (WORKSPACE, PDF_DIR, LOGS_DIR, STATE_DIR, TMP_DIR, SCANSCI_DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        # default=str：报告里混进 Path / datetime 时不应该让整个写入失败
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    tmp.replace(path)


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ── 子进程 ───────────────────────────────────────────────────────────────────
_VENV_USABLE: bool | None = None


def _venv_runs(exe: Path) -> bool:
    """探测 venv 解释器是不是**真的能执行**。

    V2 加了这一步是因为踩过坑：第一代的 `workspace/.venv/Scripts/python.exe`
    在这台机器上被沙箱的 ACL 拒绝执行（`拒绝访问`），文件明明在、`python_exe()`
    却一直返回它，于是所有子进程调用全部失败、报错还看不出是权限问题。
    与其让调用方对着 `WinError 5` 猜，不如在这里一次性探测并回退到系统解释器。
    """
    try:
        r = subprocess.run([str(exe), "-c", "print(1)"], timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def venv_python() -> Path | None:
    """返回可执行的 venv 解释器；不存在或不可执行时返回 None。

    探测结果缓存到 `workspace/state/venv_health.json`：每次调用都起一个子进程
    探测太贵（各阶段脚本都会调 `python_exe()`），而"解释器能不能跑"这种事
    在同一次部署里不会变。
    """
    global _VENV_USABLE
    for cand in (
        VENV_DIR / "Scripts" / "python.exe",   # Windows
        VENV_DIR / "bin" / "python",           # POSIX
    ):
        if not cand.exists():
            continue
        if _VENV_USABLE is None:
            cached = read_json(STATE_DIR / "venv_health.json", default=None) or {}
            if cached.get("path") == str(cand) and "usable" in cached:
                _VENV_USABLE = bool(cached["usable"])
            else:
                _VENV_USABLE = _venv_runs(cand)
                write_json(STATE_DIR / "venv_health.json",
                           {"path": str(cand), "usable": _VENV_USABLE, "checked_at": utcnow()})
            if not _VENV_USABLE:
                warn(f"venv 解释器不可执行（沙箱/ACL 拒绝），已回退到系统 Python：{cand}")
        return cand if _VENV_USABLE else None
    return None


def python_exe() -> Path:
    return venv_python() or Path(sys.executable)


def extra_pythonpath() -> str:
    """子进程要额外挂的 site-packages（engine 不在当前解释器里时用）。"""
    parts = []
    if PKG_LIB_DIR.is_dir():
        parts.append(str(PKG_LIB_DIR))
    cfg = load_downloads_config().get("engineering", {}) or {}
    explicit = str(cfg.get("extra_pythonpath", "") or "").strip()
    if explicit:
        parts.append(explicit)
    if not _has_scansci():
        parts += [str(p) for p in SCANSCI_FALLBACK_PATHS if p.is_dir()]
    return os.pathsep.join(parts)


def _has_scansci() -> bool:
    """当前解释器能不能 import scansci_pdf。"""
    try:
        import importlib.util
        return importlib.util.find_spec("scansci_pdf") is not None
    except Exception:  # noqa: BLE001
        return False


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """构造子进程环境：把临时目录与本 skill 的数据目录全部收进 workspace。

    这是本项目能在受限沙箱里跑起来的前提——pip / 浏览器 / 上游工具
    默认都会写用户目录，散落在 workspace 之外既不可控也不可清理。
    """
    env = dict(os.environ)
    for var in ("TMP", "TEMP", "TMPDIR"):
        env[var] = str(TMP_DIR)
    env["SCANSCI_PDF_DATA_DIR"] = str(SCANSCI_DATA_DIR)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["UV_CACHE_DIR"] = str(WORKSPACE / ".uv-cache")
    env["UV_PYTHON_INSTALL_DIR"] = str(WORKSPACE / ".uv-python")
    # patchright/playwright 默认把 Chromium 下到 %LOCALAPPDATA%\ms-playwright，
    # 在受限环境里既写不进去也不好清理；统一收进 workspace。
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(WORKSPACE / ".browsers")
    # V2：把本地依赖目录挂上，让子进程也能 import requests / bs4 / scansci_pdf
    pp = extra_pythonpath()
    if pp:
        env["PYTHONPATH"] = pp + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    if SCANSCI_PDF_SOURCE:
        env["SCANSCI_PDF_SOURCE"] = SCANSCI_PDF_SOURCE
    if extra:
        env.update(extra)
    return env


def run(
    args: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    capture: bool = True,
    env: dict[str, str] | None = None,
    echo: bool = False,
) -> subprocess.CompletedProcess:
    """跑一个子进程并（可选）收回输出。

    为什么不用 subprocess 的 pipe：受限沙箱会拒绝 CreatePipe，`capture_output=True`
    直接抛 WinError 5。这里改成**重定向到临时文件**再读回——沙箱内外行为一致，
    也不会有管道缓冲区写满导致子进程挂死的问题。
    """
    ensure_dirs()
    argv = [str(a) for a in args]
    if echo:
        info("$ " + " ".join(argv))

    common = dict(
        cwd=str(cwd) if cwd else None,
        env=env or child_env(),
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )

    if not capture:
        return subprocess.run(argv, **common)  # type: ignore[arg-type]

    out_path = TMP_DIR / f"run-{os.getpid()}-{time.time_ns()}.out"
    err_path = TMP_DIR / f"run-{os.getpid()}-{time.time_ns()}.err"
    try:
        with out_path.open("w", encoding="utf-8", errors="replace") as out_fh, \
                err_path.open("w", encoding="utf-8", errors="replace") as err_fh:
            proc = subprocess.run(argv, stdout=out_fh, stderr=err_fh, **common)  # type: ignore[arg-type]
        proc.stdout = out_path.read_text(encoding="utf-8", errors="replace")
        proc.stderr = err_path.read_text(encoding="utf-8", errors="replace")
        return proc
    finally:
        for p in (out_path, err_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def scansci_pdf(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """调用本地化的 scansci-pdf CLI。

    统一用 `python -m scansci_pdf`：不依赖 console script 在 PATH 上，
    也不受 venv 激活状态影响。
    """
    ensure_dirs()
    return run([python_exe(), "-m", "scansci_pdf", *args], **kwargs)


SCANSCI_PDF_SOURCE = os.environ.get("SCANSCI_PDF_SOURCE", "vendor").strip().lower()


# ── 标识符 ───────────────────────────────────────────────────────────────────
def normalize_doi(value: str) -> str:
    v = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi:", "DOI:"):
        if v.lower().startswith(prefix.lower()):
            v = v[len(prefix):]
    return v.strip().strip(".").strip()


def is_doi(value: str) -> bool:
    import re
    return bool(re.match(r"^10\.\d{4,9}/\S+$", normalize_doi(value)))


def is_arxiv(value: str) -> bool:
    import re
    v = (value or "").strip()
    v = re.sub(r"^(arxiv:|https?://arxiv\.org/(abs|pdf)/)", "", v, flags=re.I)
    v = re.sub(r"v\d+$", "", v.strip())
    return bool(re.match(r"^\d{4}\.\d{4,5}$", v) or re.match(r"^[a-z-]+(\.[A-Z]{2})?/\d{7}$", v, re.I))


def canonical_arxiv(value: str) -> str:
    import re
    v = (value or "").strip()
    v = re.sub(r"^(arxiv:|https?://arxiv\.org/(abs|pdf)/)", "", v, flags=re.I)
    v = v.removesuffix(".pdf")
    return re.sub(r"v\d+$", "", v.strip())


def identifier_kind(value: str) -> str:
    if is_doi(value):
        return "doi"
    if is_arxiv(value):
        return "arxiv"
    return "unknown"


# arXiv 的 DataCite DOI 前缀。同一篇预印本经常同时以这两种形态出现，
# 必须归一到同一个去重键，否则「10.48550/arXiv.1706.03762」和
# 「1706.03762」会被当成两篇，实跑时会重复下载同一个文件。
ARXIV_DOI_PREFIX = "10.48550/arxiv."


def arxiv_from_doi(value: str) -> str:
    """`10.48550/arXiv.1706.03762` → `1706.03762`；不是 arXiv DOI 则返回空串。"""
    v = normalize_doi(value)
    low = v.lower()
    if low.startswith(ARXIV_DOI_PREFIX):
        return canonical_arxiv(v[len(ARXIV_DOI_PREFIX):])
    return ""


def dedup_key(identifier: str, title: str = "") -> str:
    """全流程统一的去重键。

    三个阶段（归一化 / 检索合并 / 队列构建）必须用同一个键空间，
    否则同一篇文献会在不同阶段以不同身份存活下来。
    """
    import re

    ident = (identifier or "").strip()
    arx = arxiv_from_doi(ident)
    if arx:
        return "arxiv:" + arx.lower()
    if is_doi(ident):
        return "doi:" + normalize_doi(ident).lower()
    if is_arxiv(ident):
        return "arxiv:" + canonical_arxiv(ident).lower()
    basis = title or ident
    return "title:" + re.sub(r"\W+", "", basis.lower())[:120]


# 上游按来源保存中间结果时会加后缀，例如：
#   10.1038_nature12373_Sci-Hub_scihub_sci-hub_vg.pdf
#   10.1371_journal.pone.0173717_Sci-Hub.pdf
# 反推 DOI 时必须把这些来源标记切掉，否则会把同一篇的副本当成另一篇文献。
_SOURCE_TOKENS = (
    "_Sci-Hub", "_SciHub", "_scihub", "_LibGen", "_libgen",
    "_Unpaywall", "_unpaywall", "_EuropePMC", "_europepmc",
    "_Crossref", "_CrossrefPage", "_PLOSDirect", "_arXiv", "_arxiv",
    "_CORE", "_DOAJ", "_OpenAIRE", "_Publisher", "_Gateway", "_Browser",
)


def _strip_source_suffix(rest: str) -> str:
    """切掉 DOI 后缀后面的来源标记，返回真正的 DOI 后缀。"""
    import re

    for token in _SOURCE_TOKENS:
        idx = rest.find(token)
        if idx > 0:
            rest = rest[:idx]

    # 通用规则：`_` 之后剩下的一段不含 `.`，说明它更像来源标签而不是 DOI 段
    # （真实 DOI 段基本都带 `.`）。这样既能切掉未知来源名，又不会误伤 DOI。
    m = re.search(r"_([A-Z][A-Za-z0-9-]*)$", rest)
    if m and m.start() > 0 and "." not in m.group(1):
        rest = rest[:m.start()]
    return rest


def recover_doi_from_filename(stem: str) -> str:
    """从文件名反推 DOI。

    上游不同通道会给出不同形态的文件名，这里都要能还原：
        10.1038_nature12373                     → 10.1038/nature12373
        10.1371_journal.pone.0173717            → 10.1371/journal.pone.0173717
        unpaywall_10.1038_nature12373           → 10.1038/nature12373（来源前缀）
        scihub-10.1016_j.cell.2020.02.052       → 10.1016/j.cell.2020.02.052
        10.1038_nature12373_Sci-Hub_scihub_...  → 10.1038/nature12373（来源后缀）
        1706.03762                              → 10.48550/arXiv.1706.03762

    最后一条很关键：上游把 `10.48550/arXiv.X` 归一化成裸 arXiv 号后会**额外**
    落一份 `X.pdf`，不还原它就会把同一篇预印本当成两个不同条目。

    只按 DOI / arXiv 的形态特征还原，不猜；不符合就返回空串，避免造出假 DOI。
    """
    import re

    m = re.search(r"(10\.\d{4,9})[._](.+)$", stem or "")
    if m:
        suffix = _strip_source_suffix(m.group(2).strip("_")).strip("_")
        if suffix:
            return f"{m.group(1)}/{suffix}"

    # 没有 DOI 形态：看看是不是裸 arXiv 号
    if is_arxiv(stem):
        return f"10.48550/arXiv.{canonical_arxiv(stem)}"
    return ""


def source_suffix_of(stem: str) -> str:
    """取出文件名里的来源后缀（用于日志与「保留哪一份」的说明），没有则空串。"""
    import re

    m = re.search(r"10\.\d{4,9}[._](.+)$", stem or "")
    if not m:
        return ""
    full = m.group(1)
    stripped = _strip_source_suffix(full.strip("_")).strip("_")
    if full.strip("_") == stripped:
        return ""
    return full[len(stripped):].strip("_")


def doi_to_filename(doi: str) -> str:
    """DOI → 文件名主干。`/` 等非法字符替换为 `_`。"""
    import re
    return re.sub(r"[^A-Za-z0-9._-]+", "_", doi).strip("_") or "paper"


def identifier_to_filename(value: str) -> str:
    """标识符 → PDF 文件名主干（契约要求的规范形态，一律 DOI 命名）。

    arXiv 号单独进队时会补上它的 DataCite DOI 前缀，保证同一篇论文无论以哪种
    形态入队，落盘文件名都一致。
    """
    arx = arxiv_from_doi(value)
    if arx:
        return doi_to_filename(f"10.48550/arXiv.{arx}")
    if is_doi(value):
        return doi_to_filename(normalize_doi(value))
    if is_arxiv(value):
        return doi_to_filename(f"10.48550/arXiv.{canonical_arxiv(value)}")
    return doi_to_filename(value)


def alias_stems(identifier: str) -> list[str]:
    """一个标识符可能对应的**所有**文件名主干，规范形态排第一。

    上游会做标识符归一化：进队时写 `10.48550/arXiv.1706.03762`，结果行里回
    `1706.03762`，落盘也是 `1706.03762.pdf`。所以认领磁盘文件、匹配结果行时
    都必须同时认 DOI 形态与裸 arXiv 形态，否则会把已下好的文件误判为缺失。
    """
    keys = [identifier_to_filename(identifier)]
    arx = arxiv_from_doi(identifier)
    if arx:
        keys.append(doi_to_filename(arx))
    elif is_arxiv(identifier):
        keys.append(doi_to_filename(canonical_arxiv(identifier)))
    if is_doi(identifier):
        keys.append(doi_to_filename(normalize_doi(identifier)))

    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


# ── 条目模型 ─────────────────────────────────────────────────────────────────
@dataclass
class Item:
    """队列中的一条文献。"id" 是规范化后的 DOI 或 arXiv 号。"""

    id: str
    kind: str = "doi"
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    journal: str = ""
    abstract: str = ""
    cited_by_count: int = 0
    is_oa: bool = False
    source: str = ""            # 元信息来自哪个源（crossref / openalex / ...）
    origin: str = "direct"      # direct(用户直接给) / search(检索得到) / manual(人工补)
    selected: bool = True       # ★门① 的用户选择
    status: str = "pending"     # pending / success / failed / skipped
    file: str = ""
    reason: str = ""            # REASONS 之一
    detail: str = ""            # 原始错误信息 / 来源通道
    channel: str = ""           # 实际下载通道（scansci-pdf 报告）

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title,
            "authors": self.authors, "year": self.year, "journal": self.journal,
            "abstract": self.abstract, "cited_by_count": self.cited_by_count,
            "is_oa": self.is_oa, "source": self.source, "origin": self.origin,
            "selected": self.selected, "status": self.status, "file": self.file,
            "reason": self.reason, "detail": self.detail, "channel": self.channel,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def load_queue(path: Path | None = None) -> dict:
    data = read_json(path or DEFAULT_QUEUE, default=None)
    if not data:
        raise SystemExit(
            f"找不到队列文件 {path or DEFAULT_QUEUE}。先跑 `pipeline.py normalize` 或 `pipeline.py search`。"
        )
    return data


def queue_items(queue: dict, only_selected: bool = True) -> list[Item]:
    items = [Item.from_dict(d) for d in queue.get("items", [])]
    if only_selected:
        items = [i for i in items if i.selected]
    return items


def save_items(queue: dict, items: Iterable[Item], path: Path | None = None) -> None:
    queue = dict(queue)
    queue["items"] = [i.to_dict() for i in items]
    queue["updated_at"] = utcnow()
    write_json(path or DEFAULT_QUEUE, queue)


# ── 运行日志 ─────────────────────────────────────────────────────────────────
class RunLog:
    """一次运行的日志：同时落 JSONL（机读）和 Markdown（人读）。"""

    def __init__(self, stage: str, log_dir: Path | None = None) -> None:
        ensure_dirs()
        self.stage = stage
        self.stamp = run_stamp()
        base = (log_dir or LOGS_DIR) / f"{stage}-{self.stamp}"
        self.jsonl = base.with_suffix(".jsonl")
        self.markdown = base.with_suffix(".md")
        self.started = utcnow()
        self.records: list[dict] = []

    def log(self, event: str, **fields: Any) -> dict:
        rec = {"ts": utcnow(), "stage": self.stage, "event": event, **fields}
        self.records.append(rec)
        append_jsonl(self.jsonl, rec)
        return rec

    def item(self, item_id: str, status: str, reason: str = "", detail: str = "", **extra: Any) -> None:
        self.log("item", id=item_id, status=status, reason=reason, detail=detail[:800], **extra)

    def close(self, summary: str = "") -> Path:
        lines = [
            f"# 运行日志 · {self.stage} · {self.stamp}",
            "",
            f"- 开始：{self.started}",
            f"- 结束：{utcnow()}",
        ]
        if summary:
            lines.append(f"- 摘要：{summary}")
        lines += ["", "| 时间 | 事件 | 标识符 | 状态 | 原因 | 详情 |", "|---|---|---|---|---|---|"]
        for r in self.records:
            cells = [
                r.get("ts", ""), r.get("event", ""), str(r.get("id", "")),
                str(r.get("status", "")), str(r.get("reason", "")),
                str(r.get("detail", "")).replace("|", "\\|").replace("\n", " ")[:200],
            ]
            lines.append("| " + " | ".join(cells) + " |")
        self.markdown.parent.mkdir(parents=True, exist_ok=True)
        self.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.markdown


# ── 部署状态 ─────────────────────────────────────────────────────────────────
def load_config_state() -> dict:
    return read_json(CONFIG_STATE, default={}) or {}


def contact_email() -> str:
    """取联系邮箱（OpenAlex / Unpaywall / Crossref 的"礼貌池"身份）。

    这里要**按优先级找多个来源**：早期版本只读 `state/config.json`，而
    `bootstrap.py --email` 把邮箱写在 `scansci-pdf/config.json` 里——两者不是
    同一个文件，于是邮箱从来没有传到检索层，OpenAlex 一直 429，
    用户明明配了邮箱却毫无效果。环境变量也认，方便临时覆盖。
    """
    env = (os.environ.get("OPENALEX_MAILTO") or os.environ.get("LITERATURE_ACQUIRE_EMAIL") or "").strip()
    if env:
        return env
    for path in (SCANSCI_DATA_DIR / "config.json", CONFIG_STATE):
        cfg = read_json(path, default={}) or {}
        value = str(cfg.get("email", "") or "").strip()
        if value and "example.invalid" not in value:
            return value
    return ""


def save_config_state(cfg: dict) -> None:
    write_json(CONFIG_STATE, cfg)


def is_deployed() -> bool:
    return bool(read_json(DEPLOY_STATE, default={}).get("ready"))


def require_deployed() -> None:
    if not is_deployed():
        raise SystemExit(
            "部署关还没过。先运行：\n"
            "  python 0路由/scripts/bootstrap.py check\n"
            "  python 0路由/scripts/bootstrap.py plan\n"
            "  python 0路由/scripts/bootstrap.py apply"
        )


def which(name: str) -> str | None:
    return shutil.which(name)


def sleep_ms(ms: int) -> None:
    time.sleep(ms / 1000.0)
