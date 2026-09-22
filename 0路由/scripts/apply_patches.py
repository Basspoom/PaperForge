"""对本地化上游副本应用/检查/撤销补丁（整个仓库通用）。

设计原则：**vendor/ 与本地化副本保持与上游逐字一致**，我们对上游的必要修改
只以显式补丁存在、可审计、可回放，重新同步上游后一条命令就能重新打上。

补丁清单按目标副本分布，本工具自动发现：
    1学术查询/patches/patches.json          → 作用于 1学术查询/
    2工程化下载/patches/patches.json        → 作用于 2工程化下载/vendor/scansci-pdf/

    python 0路由/scripts/apply_patches.py --check     # 只报告状态，不写文件
    python 0路由/scripts/apply_patches.py             # 应用（幂等）
    python 0路由/scripts/apply_patches.py --revert    # 撤销
    python 0路由/scripts/apply_patches.py --only 0004 # 只处理指定 id（可逗号分隔）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

AGENT_ROOT = Path(__file__).resolve().parents[2]

# 补丁清单 → 它作用的副本根目录
TARGETS: list[tuple[Path, Path]] = [
    (AGENT_ROOT / "1学术查询" / "patches" / "patches.json", AGENT_ROOT / "1学术查询"),
    (AGENT_ROOT / "2工程化下载" / "patches" / "patches.json",
     AGENT_ROOT / "2工程化下载" / "vendor" / "scansci-pdf"),
]

STATUS_APPLIED = "applied"
STATUS_PENDING = "pending"
STATUS_CONFLICT = "conflict"

MARK = {"applied": "[已应用]", "pending": "[待应用]", "conflict": "[冲突!]",
        "missing-file": "[缺文件!]"}


def inspect(patch: dict, root: Path) -> tuple[str, Path]:
    target = root / patch["file"]
    if not target.exists():
        return "missing-file", target
    text = target.read_text(encoding="utf-8")
    if patch["replace"] in text:
        return STATUS_APPLIED, target
    if patch["find"] in text:
        return STATUS_PENDING, target
    return STATUS_CONFLICT, target


def apply_patch(patch: dict, root: Path, revert: bool) -> tuple[bool, str]:
    status, target = inspect(patch, root)
    if status == "missing-file":
        return False, f"目标文件不存在：{target}"
    if revert:
        if status != STATUS_APPLIED:
            return True, "未应用，无需撤销"
        text = target.read_text(encoding="utf-8")
        target.write_text(text.replace(patch["replace"], patch["find"], 1), encoding="utf-8")
        return True, "已撤销"
    if status == STATUS_APPLIED:
        return True, "已应用（跳过）"
    if status == STATUS_CONFLICT:
        return False, ("补丁上下文不匹配——上游该处代码已变。"
                       "请人工核对后更新 patches.json（不要盲目强打）。")
    text = target.read_text(encoding="utf-8")
    target.write_text(text.replace(patch["find"], patch["replace"], 1), encoding="utf-8")
    return True, "已应用"


def load_jobs(only: set[str]) -> list[tuple[str, dict, Path]]:
    jobs: list[tuple[str, dict, Path]] = []
    for manifest, root in TARGETS:
        if not manifest.exists():
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        label = root.relative_to(AGENT_ROOT).as_posix()
        for patch in data.get("patches", []):
            if only and patch.get("id") not in only:
                continue
            jobs.append((label, patch, root))
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description="应用/检查本仓库对本地化上游副本的补丁")
    ap.add_argument("--check", action="store_true", help="只报告状态")
    ap.add_argument("--revert", action="store_true", help="撤销补丁")
    ap.add_argument("--only", default="", help="只处理指定 id（可逗号分隔）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    only = {p.strip() for p in args.only.split(",") if p.strip()}
    jobs = load_jobs(only)
    if not jobs:
        if not args.quiet:
            print("没有找到任何补丁清单。")
        return 1 if only else 0

    failures = 0
    by_label: dict[str, list[str]] = {}
    for label, patch, root in jobs:
        pid = patch.get("id", "?")
        if args.check:
            status, _ = inspect(patch, root)
            by_label.setdefault(label, []).append(f"  {MARK[status]} {pid}")
            if status in ("conflict", "missing-file"):
                failures += 1
            continue
        ok, detail = apply_patch(patch, root, args.revert)
        if not ok:
            failures += 1
        by_label.setdefault(label, []).append(f"  [{'OK' if ok else 'FAIL'}] {pid}: {detail}")

    for label, lines in by_label.items():
        if not args.check:
            print(f"{label}/")
        print("\n".join(lines))

    if args.check and not failures:
        print("  所有补丁已就位")
    if args.revert and not failures and not args.quiet:
        print("  注意：撤销补丁会让浏览器后端与机构登录相关命令重新不可用。")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
