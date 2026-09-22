"""策略档位：一条命令切换"能力最大化"与"仅合法来源"。

    python 0路由/scripts/policy.py show
    python 0路由/scripts/policy.py set max      # 灰色源开启（本地能力验证用）
    python 0路由/scripts/policy.py set legal    # 关闭灰色源，只走 OA / 出版商 / 机构通道

为什么要有这个开关：本 skill 聚合多条下载通路，其中 Sci-Hub / LibGen 类灰色源
是否可用取决于司法辖区、机构授权与出版商条款。能力验证阶段可以全开，
**发布到公开仓库前必须把默认收紧**，让灰色源成为用户显式选择。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C  # noqa: E402

POLICIES: dict[str, dict] = {
    "max": {
        "label": "能力最大化（灰色源开启）",
        "scihub_enabled": True,
        "download_strategy": "fastest",
        "use_tor_for_scihub": True,
        "note": "仅供本地能力验证，或在你有权获取相应内容时使用。",
    },
    "legal": {
        "label": "仅合法来源（灰色源关闭）",
        "scihub_enabled": False,
        "download_strategy": "legal_only",
        "use_tor_for_scihub": False,
        "note": "只走 OA / 出版商 API / 机构通道。公开仓库的推荐默认值。",
    },
}


def scansci_config_path() -> Path:
    return C.SCANSCI_DATA_DIR / "config.json"


def load_scansci_config() -> dict:
    return C.read_json(scansci_config_path(), default={}) or {}


def save_scansci_config(cfg: dict) -> None:
    C.write_json(scansci_config_path(), cfg)


def current_policy(cfg: dict) -> str:
    if cfg.get("scihub_enabled") is False:
        return "legal"
    if cfg.get("scihub_enabled") is True:
        return "max"
    return "unset"


def apply_policy(name: str, dry_run: bool = False) -> dict:
    if name not in POLICIES:
        raise SystemExit(f"未知策略 {name!r}，可选：{', '.join(POLICIES)}")
    spec = POLICIES[name]
    cfg = load_scansci_config()
    before = {k: cfg.get(k) for k in ("scihub_enabled", "download_strategy", "use_tor_for_scihub")}
    for key in ("scihub_enabled", "download_strategy", "use_tor_for_scihub"):
        cfg[key] = spec[key]
    if not dry_run:
        save_scansci_config(cfg)
        state = C.load_config_state()
        state["policy"] = name
        state["policy_applied_at"] = C.utcnow()
        C.save_config_state(state)
    return {"policy": name, "label": spec["label"], "before": before,
            "after": {k: cfg.get(k) for k in before}, "dry_run": dry_run, "note": spec["note"]}


def main() -> int:
    C.console()
    ap = argparse.ArgumentParser(description="文献获取智能体 · 下载策略档位")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="显示当前档位")
    p_set = sub.add_parser("set", help="切换档位")
    p_set.add_argument("name", choices=sorted(POLICIES))
    p_set.add_argument("--dry-run", action="store_true", help="只打印将要做的改动")
    args = ap.parse_args()

    if args.cmd == "show":
        cfg = load_scansci_config()
        if not cfg:
            C.warn(f"还没有上游配置（{scansci_config_path()}）。先跑 bootstrap.py apply。")
            return 1
        cur = current_policy(cfg)
        C.step("当前策略")
        C.info(f"档位：{cur} — {POLICIES.get(cur, {}).get('label', '未设置')}")
        for key in ("scihub_enabled", "download_strategy", "use_tor_for_scihub"):
            C.info(f"  {key} = {cfg.get(key)}")
        return 0

    result = apply_policy(args.name, dry_run=args.dry_run)
    C.step(f"策略 → {result['label']}" + ("（dry-run）" if result["dry_run"] else ""))
    for key, old in result["before"].items():
        new = result["after"][key]
        flag = "  " if old == new else "→ "
        C.info(f"{flag}{key}: {old} → {new}")
    C.info(result["note"])
    if result["dry_run"]:
        C.warn("dry-run：没有写入任何文件。")
    else:
        C.ok(f"已写入 {scansci_config_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
