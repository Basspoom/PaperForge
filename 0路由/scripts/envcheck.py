"""V2 环境体检：把"这套环境到底能不能跑"一次说清楚。

第一代 `bootstrap.py check` 只报"有没有装"，不报"能不能用"。本机就吃了这个亏：
venv 存在、packages 齐全，但解释器被沙箱 ACL 拒绝执行，于是所有子进程调用都失败。
所以这里逐项**实际执行**验证，而不是查文件是否存在。

    python 0路由/scripts/envcheck.py
    python 0路由/scripts/envcheck.py --fix   # 打印修复命令（不自动执行破坏性操作）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C  # noqa: E402

OK, WARN, BAD = "OK", "WARN", "FAIL"


def _row(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def check_python() -> dict:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro}（{sys.executable}）"
    return _row("Python 解释器", OK if v >= (3, 9) else BAD, detail)


def check_deps() -> list[dict]:
    C.init_pylib()
    rows = []
    for mod, why in (("requests", "直连链路必需"), ("bs4", "直连页面解析必需")):
        try:
            __import__(mod)
            rows.append(_row(f"依赖 {mod}", OK, why))
        except Exception as e:  # noqa: BLE001
            rows.append(_row(f"依赖 {mod}", BAD,
                             f"缺失（{why}）；修复：python -m pip install --target "
                             f"\"{C.PKG_LIB_DIR}\" requests beautifulsoup4（{e.__class__.__name__}）"))
    return rows


def check_venv() -> dict:
    exe = C.VENV_DIR / "Scripts" / "python.exe"
    if C.venv_python():
        return _row("venv 解释器", OK, str(exe))
    if exe.exists():
        return _row("venv 解释器", WARN,
                    f"{exe} 存在但**不可执行**（沙箱/ACL 拒绝）；已自动回退系统 Python，"
                    f"这不影响 V2 运行")
    return _row("venv 解释器", WARN, "未创建；V2 用系统 Python + .pylib，不需要 venv")


def check_engine() -> dict:
    r = C.scansci_pdf(["--help"], timeout=120)
    if r.returncode == 0:
        return _row("工程化引擎扫描科学", OK, "scansci_pdf 可调用")
    tail = ((r.stderr or "") + (r.stdout or "")).strip().splitlines()[-2:]
    return _row("工程化引擎扫描科学", BAD,
                "不可调用 → " + " / ".join(tail)[:200] +
                "；修复：把装了 scansci_pdf 的 site-packages 加到 "
                "0路由/downloads.json → engineering.extra_pythonpath")


def check_search() -> dict:
    try:
        import urllib.request  # noqa: F401
        sys.path.insert(0, str(C.SCRIPTS_DIR))
        import search  # noqa: F401
        return _row("学术检索（兜底 search.py）", OK, "标准库实现，可用")
    except Exception as e:  # noqa: BLE001
        return _row("学术检索（兜底 search.py）", BAD, f"{e.__class__.__name__}: {e}")


def check_scihub_config() -> dict:
    cfg = C.load_downloads_config()
    sc = (cfg.get("fulltext", {}) or {}).get("scihub", {}) or {}
    mirrors = sc.get("mirrors") or []
    bad = [m for m in mirrors if any(x in m for x in
                                     ("sci-hub.se", "sci-hub.st", "sci-hub.vg", "sci-hub.ee",
                                      "sci-hub.bz", "sci-hub.mksa", "sci-hub.is", "41610"))]
    detail = f"{len(mirrors)} 个镜像：{', '.join(mirrors)}"
    if bad:
        return _row("直连镜像列表", WARN, f"含已知失效域名 {bad}；建议只用 .box/.su/.ru/.red")
    return _row("直连镜像列表", OK, detail)


def check_network() -> dict:
    try:
        import requests
    except Exception:  # noqa: BLE001
        return _row("外网连通", WARN, "requests 缺失，跳过探测")
    try:
        r = requests.get("https://api.crossref.org/works?rows=1", timeout=20,
                         headers={"User-Agent": "envcheck/1.0"})
        return _row("外网连通", OK if r.status_code == 200 else WARN, f"crossref HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        return _row("外网连通", BAD, f"{e.__class__.__name__}: {str(e)[:120]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="V2 环境体检")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    C.console()
    rows = [check_python(), check_venv(), *check_deps(), check_search(),
            check_scihub_config(), check_engine(), check_network()]

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        C.step("V2 环境体检")
        for r in rows:
            mark = {OK: "[OK]  ", WARN: "[WARN]", BAD: "[FAIL]"}[r["status"]]
            C.say(f"  {mark} {r['name']:<26} {r['detail']}")

    bad = [r for r in rows if r["status"] == BAD]
    war = [r for r in rows if r["status"] == WARN]
    C.say("")
    C.info(f"结论：{len(rows)-len(bad)-len(war)} 项正常，{len(war)} 项告警，{len(bad)} 项失败")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
