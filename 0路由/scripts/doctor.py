"""体检：运行环境、依赖、网络、代理、上游配置。

只用标准库，因此**在 venv 建好之前也能跑**。bootstrap.py 复用它。

    python 0路由/scripts/doctor.py            # 人读报告
    python 0路由/scripts/doctor.py --json     # 机读报告（给 pipeline / CI）
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C  # noqa: E402

# 需要连通的端点。(名称, URL 模板, 用途, 是否关键)
# 关键 = 不通就直接影响检索或下载能力；非关键 = 不通会降级但不致命，
# 例如 doi.org 在部分网络（fake-ip 代理 / 特定出口）上 TLS 握手不稳定，
# 而 DOI 解析还有 Crossref 与上游自带的解析路径可用。
ENDPOINTS = [
    ("crossref",   "https://api.crossref.org/works?rows=1&mailto={mail}",       "学术检索主源（DOI 元信息）", True),
    ("openalex",   "https://api.openalex.org/works?per-page=1&mailto={mail}",   "无 key 检索兜底 + OA 定位", True),
    ("pubmed",     "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi",  "医学/临床文献", True),
    ("arxiv",      "https://export.arxiv.org/api/query?search_query=all:electron&max_results=1", "预印本", True),
    ("unpaywall",  "https://api.unpaywall.org/v2/10.1038/nature12373?email={mail}", "OA 位置定位", True),
    ("doi.org",    "https://doi.org/api/handles/10.1038/nature12373",           "DOI 解析（Handle API）", False),
    ("semanticscholar", "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1038/nature12373?fields=title", "引用图 / 补充检索", False),
    ("pypi",       "https://pypi.org/simple/",                                  "依赖安装（若被镜像替代可忽略）", False),
    ("github",     "https://raw.githubusercontent.com/",                        "上游同步 / 更新", False),
]

# 这些端点对 UA 敏感：用浏览器风格的 UA，避免被 406/403 误判为不可达
UA_BROWSERLIKE = {
    "arxiv": "paperforge/1.0 (mailto:{mail})",
}
UA_DEFAULT = "paperforge-doctor/1.0 (mailto:{mail})"

# 常见本地代理端口（Clash / Mihomo / v2rayN / Shadowsocks 等）
COMMON_PROXY_PORTS = [7890, 7891, 7897, 10809, 10808, 1080, 1070, 2080, 2081, 8889, 8118, 20171]


def _probe_url(url: str, timeout: float = 12.0) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "paperforge-doctor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        # 4xx/5xx 说明网络本身通，只是这个 URL 没权限/不存在
        return exc.code < 500, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _port_open(host: str, port: int, timeout: float = 0.6) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def _registry_proxy() -> str:
    """读 Windows WinINET 代理设置（系统「Internet 选项」里的那个）。"""
    if os.name != "nt":
        return ""
    try:
        import winreg  # type: ignore
    except Exception:
        return ""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enable:
                return ""
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            return str(server or "")
    except Exception:
        return ""


def _proxy_works(proxy: str, timeout: float = 12.0) -> tuple[bool, str]:
    """确认代理真的能转发 HTTPS（而不是仅端口开着）。

    注意：这里只判定"能不能穿过代理到达目标"。目标返回 4xx（尤其 429 限速）
    恰恰证明代理链路是通的，因此不视为失败。
    """
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    req = urllib.request.Request(
        "https://api.openalex.org/works?per-page=1",
        headers={"User-Agent": "paperforge-doctor/1.0"},
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return True, f"HTTP {exc.code}（链路通，目标限速/拒绝该 URL）"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def detect_proxy(verbose: bool = True) -> dict:
    """找出可用代理：先看环境变量与系统设置，再扫常见本地端口。"""
    result: dict = {"from_env": "", "from_registry": "", "candidates": [], "recommended": ""}

    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = os.environ.get(var, "").strip()
        if val:
            result["from_env"] = val
            break
    result["from_registry"] = _registry_proxy()

    seen: set[str] = set()
    for raw in (result["from_env"], result["from_registry"]):
        if not raw:
            continue
        for part in str(raw).split(";"):
            part = part.strip()
            if not part:
                continue
            url = part if "://" in part else f"http://{part}"
            if url not in seen:
                seen.add(url)
                works, detail = _proxy_works(url)
                result["candidates"].append({"proxy": url, "source": "env/registry", "works": works, "detail": detail})
                if works and not result["recommended"]:
                    result["recommended"] = url

    for port in COMMON_PROXY_PORTS:
        if not _port_open("127.0.0.1", port):
            continue
        url = f"http://127.0.0.1:{port}"
        if url in seen:
            continue
        seen.add(url)
        works, detail = _proxy_works(url)
        if verbose:
            C.info(f"探测 127.0.0.1:{port} → {'可用' if works else '不可用'}")
        result["candidates"].append({"proxy": url, "source": "port-scan", "works": works, "detail": detail})
        if works and not result["recommended"]:
            result["recommended"] = url

    return result


# ── 各项检查 ─────────────────────────────────────────────────────────────────
def check_python() -> dict:
    v = sys.version_info
    return {
        "name": "python",
        "ok": v >= (3, 9),
        "detail": f"{v.major}.{v.minor}.{v.micro} ({sys.executable})",
        "hint": "" if v >= (3, 11) else "上游 scansci-pdf 要求 Python >= 3.11；本 skill 会用它自己的 venv，不影响这个解释器。",
    }


def check_uv() -> dict:
    exe = C.which("uv")
    if not exe:
        return {"name": "uv", "ok": False, "detail": "未安装",
                "hint": "可选。没有 uv 时 bootstrap 会尝试用系统 Python 建 venv；建议安装：winget install astral-sh.uv"}
    try:
        out = C.run([exe, "--version"], timeout=30)
        return {"name": "uv", "ok": True, "detail": (out.stdout or "").strip() or exe, "hint": ""}
    except Exception as exc:  # noqa: BLE001
        return {"name": "uv", "ok": False, "detail": str(exc), "hint": "uv 存在但不可执行，检查 PATH 与杀软拦截。"}


def check_venv() -> dict:
    py = C.venv_python()
    if not py:
        return {"name": "venv", "ok": False, "detail": f"未创建（{C.VENV_DIR}）",
                "hint": "运行 bootstrap.py apply 创建。"}
    out = C.run([py, "--version"], timeout=30)
    return {"name": "venv", "ok": out.returncode == 0,
            "detail": f"{(out.stdout or out.stderr or '').strip()} @ {py}", "hint": ""}


def check_scansci() -> dict:
    if not C.venv_python():
        return {"name": "scansci-pdf", "ok": False, "detail": "venv 不存在，跳过",
                "hint": "先跑 bootstrap.py apply。"}
    out = C.scansci_pdf(["check"], timeout=180)
    text = (out.stdout or "") + (out.stderr or "")
    missing = [ln for ln in text.splitlines() if "[MISSING]" in ln]
    return {
        "name": "scansci-pdf",
        "ok": out.returncode == 0 and not missing,
        "detail": "依赖齐全" if not missing else f"缺依赖：{', '.join(missing)}",
        "hint": "" if not missing else "重跑 bootstrap.py apply 重装依赖。",
    }


def check_browser() -> dict:
    """机构登录 / Cloudflare 绕过依赖隐身浏览器后端。"""
    if not C.venv_python():
        return {"name": "browser", "ok": False, "detail": "venv 不存在，跳过", "hint": ""}
    py = C.venv_python()
    code = (
        "import importlib.util as u;"
        "print('patchright' if u.find_spec('patchright') else ('cloakbrowser' if u.find_spec('cloakbrowser') else 'none'))"
    )
    out = C.run([py, "-c", code], timeout=60)
    backend = (out.stdout or "").strip()
    if backend in ("patchright", "cloakbrowser"):
        return {"name": "browser", "ok": True, "detail": f"后端={backend}", "hint": ""}
    return {"name": "browser", "ok": False, "detail": "未安装隐身浏览器后端",
            "hint": "配置 WebVPN / 绕过 Cloudflare 需要：pip install 'scansci-pdf[patchright]'。只要 OA 直连可以先不管。"}


def check_network(mailto: str, with_proxy: str = "") -> dict:
    handlers = {}
    if with_proxy:
        handlers = {"http": with_proxy, "https": with_proxy}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(handlers)) if handlers else None

    results = []
    for name, template, purpose, critical in ENDPOINTS:
        url = template.format(mail=mailto or "anonymous@example.invalid")
        ua = UA_BROWSERLIKE.get(name, UA_DEFAULT).format(mail=mailto or "anonymous@example.invalid")
        okk, detail, limited = False, "", False
        # 一次重试：握手超时和瞬时限速在这类网络里很常见
        for attempt in range(2):
            limited = False
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
            try:
                target = opener.open if opener else urllib.request.urlopen
                with target(req, timeout=15) as resp:
                    okk, detail = True, f"HTTP {resp.status}"
                break
            except urllib.error.HTTPError as exc:
                # 4xx 说明端点可达，只是这个 URL 被拒或限速；5xx 才算真不可达
                okk, detail = exc.code < 500, f"HTTP {exc.code}"
                limited = exc.code == 429
                if limited:
                    detail += "（限速）"
                break
            except Exception as exc:  # noqa: BLE001
                okk, detail = False, f"{type(exc).__name__}"
                if attempt == 0:
                    C.sleep_ms(1200)
                    continue
        results.append({"name": name, "ok": okk, "detail": detail, "purpose": purpose,
                        "url": url, "limited": limited, "critical": critical})

    failed = [r["name"] for r in results if not r["ok"] and r["critical"]]
    degraded = [r["name"] for r in results if not r["ok"] and not r["critical"]]
    throttled = [r["name"] for r in results if r.get("limited")]
    hint = ""
    if failed:
        hint = "先解决网络/代理，再谈下载；见 proxy 一节。"
    elif degraded:
        hint = f"{', '.join(degraded)} 不可达：会降级但不断链（检索与下载主干不依赖它们）。"
    elif throttled:
        hint = (f"{', '.join(throttled)} 在限速：设置联系邮箱（bootstrap 的 --email）会进入礼貌池，"
                "明显改善；必要时配 API key。")
    return {
        "name": "network",
        "ok": not failed,
        "detail": ("全部关键端点连通" if not failed else f"关键端点不可达：{', '.join(failed)}")
                  + (f"；降级：{', '.join(degraded)}" if degraded else ""),
        "hint": hint,
        "endpoints": results,
    }


def check_config() -> dict:
    cfg_file = C.SCANSCI_DATA_DIR / "config.json"
    cfg = C.read_json(cfg_file, default={}) or {}
    problems = []
    if cfg:
        # 这几项是本 skill 的硬约束，被改回去就破坏输出契约
        if cfg.get("auto_rename") is not False:
            problems.append("auto_rename 必须为 false（否则 PDF 不会用 DOI 命名）")
        if str(cfg.get("output_dir", "")) != str(C.PDF_DIR):
            problems.append(f"output_dir 应指向 {C.PDF_DIR}")
    deps = {
        "config_file": str(cfg_file),
        "exists": cfg_file.exists(),
        "output_dir": cfg.get("output_dir", ""),
        "auto_rename": cfg.get("auto_rename", None),
        "download_strategy": cfg.get("download_strategy", ""),
        "scihub_enabled": cfg.get("scihub_enabled", None),
        "scihub_browser_headless": cfg.get("scihub_browser_headless", None),
        "vpnsci_enabled": cfg.get("vpnsci_enabled", None),
        "vpnsci_school": cfg.get("vpnsci_school", ""),
        "carsi_enabled": cfg.get("carsi_enabled", None),
        "elsevier_key_set": bool(str(cfg.get("elsevier_api_key", "")).strip()),
        "email": cfg.get("email", ""),
        "network_proxy": cfg.get("network_proxy", ""),
    }
    return {"name": "config", "ok": not problems,
            "detail": "符合契约" if problems else "；".join(problems),
            "hint": "" if not problems else "跑 bootstrap.py apply 重新固化配置。",
            "config": deps}


def _webvpn_session_info(cfg: dict) -> tuple[bool, str]:
    """看 WebVPN 会话 cookie 是否落盘且新鲜。

    这里刻意不发网络请求（doctor 要能离线跑）：只判断"登录动作有没有留下凭据"。
    真正的可用性判定由 `scansci-pdf` 侧的 session_status() 完成（它会经网关实测），
    而 cookie 的读写路径对齐由 bootstrap 写入的 instsci_cookie_file 保证。
    """
    import time

    candidates = []
    explicit = str(cfg.get("instsci_cookie_file", "")).strip()
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(C.SCANSCI_DATA_DIR / "cache" / "instsci-cookies.json")
    candidates.append(C.SCANSCI_DATA_DIR / "cookies" / "webvpn-cookies.json")

    for path in candidates:
        if not path.exists():
            continue
        cookies = C.read_json(path, default=[]) or []
        if not isinstance(cookies, list):
            continue
        ticket = next(
            (c for c in cookies
             if isinstance(c, dict) and "wengine_vpn_ticket" in str(c.get("name", "")).lower()),
            None,
        )
        if not ticket or not ticket.get("value"):
            continue
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        return True, f"{path.name}（{len(cookies)} 条 cookie，{age_h:.1f} 小时前写入）"
    return False, ""


def check_credentials() -> dict:
    """密钥与机构通道。缺失不算失败，但要明确告诉用户会损失什么。"""
    cfg = C.read_json(C.SCANSCI_DATA_DIR / "config.json", default={}) or {}
    items = []

    def add(label: str, present: bool, impact: str) -> None:
        items.append({"label": label, "present": present, "impact": impact})

    webvpn_ok, webvpn_detail = _webvpn_session_info(cfg)

    add("Elsevier / ScienceDirect API Key", bool(str(cfg.get("elsevier_api_key", "")).strip()),
        "缺：Elsevier 系论文无法走 1–2 秒的 API 快车道，只能落到竞速/机构通道")
    add("联系邮箱（Unpaywall/OpenAlex 礼貌身份）",
        bool(cfg.get("email")) and "example.invalid" not in str(cfg.get("email")),
        "缺：Unpaywall 查询被拒，OA 定位能力下降")
    add("WebVPN 学校", bool(str(cfg.get("vpnsci_school", "")).strip()),
        "缺：付费墙论文没有机构通道")
    add(f"WebVPN 会话 cookie{'（' + webvpn_detail + '）' if webvpn_ok else ''}", webvpn_ok,
        "缺：WebVPN 未登录，付费墙论文会失败。跑 bootstrap.py 里的登录步骤，"
        "或 `python -m scansci_pdf login --login-type webvpn`")
    add("CARSI 机构", bool(cfg.get("carsi_enabled")), "缺：少一条联邦认证通道")
    add("NCBI API Key（可选）", bool(os.environ.get("NCBI_API_KEY")), "缺：PubMed 速率上限 3 req/s（有 key 为 10）")
    add("Semantic Scholar API Key（可选）", bool(os.environ.get("SEMANTIC_SCHOLAR_API_KEY")),
        "缺：补充检索限速 1 req/s")

    return {"name": "credentials", "ok": True, "detail": f"{sum(1 for i in items if i['present'])}/{len(items)} 已配置",
            "hint": "", "items": items}


def full_report(mailto: str = "", proxy: str = "", verbose_proxy: bool = True) -> dict:
    C.ensure_dirs()
    proxy_info = detect_proxy(verbose=verbose_proxy)
    effective_proxy = proxy or proxy_info.get("recommended", "")
    checks = [
        check_python(),
        check_uv(),
        check_venv(),
        check_scansci(),
        check_browser(),
        check_network(mailto, effective_proxy),
        check_config(),
        check_credentials(),
    ]
    return {
        "generated_at": C.utcnow(),
        "skill_version": C.SKILL_VERSION,
        "agent_root": str(C.AGENT_ROOT),
        "workspace": str(C.WORKSPACE),
        "proxy": {**proxy_info, "effective": effective_proxy},
        "checks": checks,
        "ok": all(c["ok"] for c in checks),
    }


def print_report(report: dict) -> None:
    C.step("环境体检")
    for chk in report["checks"]:
        (C.ok if chk["ok"] else C.bad)(f"{chk['name']:<13} {chk['detail']}")
        if chk.get("hint"):
            C.info(f"                → {chk['hint']}")

    net = next((c for c in report["checks"] if c["name"] == "network"), None)
    if net and net.get("endpoints"):
        C.step("网络端点")
        for ep in net["endpoints"]:
            tag = "" if ep.get("critical", True) else "（非关键）"
            (C.ok if ep["ok"] else (C.bad if ep.get("critical", True) else C.warn))(
                f"{ep['name']:<16} {ep['detail']:<22} {ep['purpose']}{tag}")

    px = report["proxy"]
    C.step("代理")
    if px.get("from_env"):
        C.info(f"环境变量：{px['from_env']}")
    if px.get("from_registry"):
        C.info(f"系统设置：{px['from_registry']}")
    for cand in px.get("candidates", []):
        (C.ok if cand["works"] else C.bad)(f"{cand['proxy']:<28} {cand['source']:<14} {cand['detail']}")
    if px.get("recommended"):
        C.info(f"建议写入 network_proxy：{px['recommended']}")
    else:
        C.info("未发现可用代理；将直连（当前网络直连可用时这是正常的）。")

    cred = next((c for c in report["checks"] if c["name"] == "credentials"), None)
    if cred:
        C.step("密钥与机构通道")
        for it in cred["items"]:
            (C.ok if it["present"] else C.warn)(f"{it['label']}")
            if not it["present"]:
                C.info(f"                → {it['impact']}")

    C.step("结论")
    if report["ok"]:
        C.ok("体检通过。")
    else:
        C.bad("体检未通过，见上方 [FAIL] 项。")


def main() -> int:
    C.console()
    ap = argparse.ArgumentParser(description="文献获取智能体 · 环境体检")
    ap.add_argument("--json", action="store_true", help="输出机读 JSON")
    ap.add_argument("--mailto", default="", help="用于 OpenAlex/Unpaywall 的礼貌邮箱")
    ap.add_argument("--proxy", default="", help="强制使用这个代理做连通性测试")
    ap.add_argument("--no-proxy-scan", action="store_true", help="跳过本地代理端口扫描")
    args = ap.parse_args()

    report = full_report(args.mailto, args.proxy, verbose_proxy=not args.no_proxy_scan)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    C.write_json(C.STATE_DIR / "doctor.json", report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
