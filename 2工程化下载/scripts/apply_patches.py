"""把 2工程化下载/patches/patches.json 里的补丁应用到 vendor 快照。

设计原则：**vendor/ 保持与上游逐字一致**，我们对上游的必要修改只以显式补丁
的形式存在、可审计、可回放，重新同步上游后一条命令就能重新打上。

    python apply_patches.py --check     # 只报告补丁状态，不写文件
    python apply_patches.py             # 应用（幂等）
    python apply_patches.py --revert    # 撤销
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows 控制台默认 cp936，中文标记会乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
DOWNLOAD_DIR = HERE.parent
VENDOR = DOWNLOAD_DIR / "vendor" / "scansci-pdf"
MANIFEST = DOWNLOAD_DIR / "patches" / "patches.json"

STATUS_APPLIED = "applied"
STATUS_PENDING = "pending"
STATUS_CONFLICT = "conflict"


def inspect(patch: dict) -> tuple[str, Path]:
    target = VENDOR / patch["file"]
    if not target.exists():
        return "missing-file", target
    text = target.read_text(encoding="utf-8")
    if patch["replace"] in text:
        return STATUS_APPLIED, target
    if patch["find"] in text:
        return STATUS_PENDING, target
    return STATUS_CONFLICT, target


def apply_patch(patch: dict, revert: bool) -> tuple[bool, str]:
    status, target = inspect(patch)
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


def main() -> int:
    ap = argparse.ArgumentParser(description="应用/检查本 skill 对 vendor 快照的补丁")
    ap.add_argument("--check", action="store_true", help="只报告状态")
    ap.add_argument("--revert", action="store_true", help="撤销补丁")
    ap.add_argument("--only", default="", help="只处理指定 id（可逗号分隔）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"找不到补丁清单 {MANIFEST}")
        return 1
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    patches = data.get("patches", [])
    if args.only:
        wanted = {p.strip() for p in args.only.split(",") if p.strip()}
        patches = [p for p in patches if p.get("id") in wanted]
    if not patches:
        if not args.quiet:
            print("没有需要应用的补丁。")
        return 0

    failures = 0
    for patch in patches:
        pid = patch.get("id", "?")
        if args.check:
            status, target = inspect(patch)
            marker = {"applied": "[已应用]", "pending": "[待应用]",
                      "conflict": "[冲突!]", "missing-file": "[缺文件!]"}[status]
            print(f"  {marker} {pid}  {patch['file']}")
            if status in ("conflict", "missing-file"):
                failures += 1
                print(f"           → {patch.get('title', '')}")
            continue

        ok, detail = apply_patch(patch, args.revert)
        if not ok:
            failures += 1
        if not args.quiet:
            print(f"  [{'OK' if ok else 'FAIL'}] {pid}: {detail}")

    if args.revert and not failures and not args.quiet:
        print("  注意：撤销补丁会让浏览器后端相关命令重新不可用。")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
