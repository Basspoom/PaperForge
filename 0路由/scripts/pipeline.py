"""端到端总控：P0 归一化 → P1 检索 → 门① → P3 队列 → 门② → P5 下载 → P6/P7 产出。

最常用的两条：
    python pipeline.py run --input "2020 年以来钙钛矿稳定性高被引 20 篇"
    python pipeline.py run --input dois.txt --select 1,3,5-9

带两道人机确认门的完整流程：
    python pipeline.py run --input "<需求>"        # 停在 ★门①，给出候选表
    python pipeline.py resume --select 2,5,7       # 确认后一路跑到产出

子命令也可以单独跑（normalize / search / queue / download / finalize / status）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C  # noqa: E402


def ensure_runtime() -> None:
    """如果 venv 已就绪且当前不是 venv 解释器，就切过去再跑。

    这样用户/Agent 只需要记住 `python pipeline.py ...`，
    不必关心到底是哪个 Python——而 .xlsx 导出、PDF 校验等能力依赖 venv 里的包。
    """
    if os.environ.get("LITERATURE_ACQUIRE_NO_REEXEC") == "1":
        return
    vpy = C.venv_python()
    if not vpy:
        return
    try:
        if Path(sys.executable).resolve() == vpy.resolve():
            return
    except OSError:
        return
    env = C.child_env({"LITERATURE_ACQUIRE_NO_REEXEC": "1"})
    sys.exit(subprocess.call([str(vpy), str(Path(__file__).resolve()), *sys.argv[1:]], env=env))


def _print_candidates(items: list[C.Item], limit: int = 40) -> None:
    C.step(f"★门① 候选文献（{len(items)} 条）")
    for n, it in enumerate(items[:limit], 1):
        cite = f"{it.cited_by_count:>6}" if it.cited_by_count else "     -"
        C.say(f"  {n:>3}. [{cite}] {it.year or '----'}  {it.id or '(无 DOI)'}")
        C.say(f"        {(it.title or '')[:96]}")
    if len(items) > limit:
        C.say(f"        …… 其余见 {C.DEFAULT_QUEUE}")


def gate_one(queue: dict) -> None:
    """停在门①：把候选表交给用户，并给出下一步命令。"""
    items = C.queue_items(queue, only_selected=False)
    _print_candidates(items)
    C.step("下一步")
    C.info("把上面的表给用户确认，然后二选一：")
    C.info('  python 0路由/scripts/pipeline.py resume --select 1,3,5-9')
    C.info('  python 0路由/scripts/pipeline.py resume --all')
    C.warn("未经用户确认不要批量下载（除非本轮已明确给定了清单）。")


def stage_of(queue: dict) -> str:
    return str(queue.get("stage") or "unknown")


def do_search(query: str, limit: int, year_from: int | None, year_to: int | None,
              sort: str, sources: str) -> dict:
    import search as S

    mailto = C.load_config_state().get("email", "")
    src = [s.strip() for s in sources.split(",") if s.strip()]
    items, notes = S.run_search(query, limit, year_from, year_to, mailto, sort, src)
    for n in notes:
        C.info(n)
    if not items:
        raise SystemExit("检索没有结果：放宽关键词 / 去掉年份限制 / 换排序 / 检查网络。")
    queue = {
        "schema_version": C.SCHEMA_VERSION,
        "skill_version": C.SKILL_VERSION,
        "created_at": C.utcnow(),
        "stage": "awaiting_selection",
        "input": {"kind": "query", "query": query, "year_from": year_from,
                  "year_to": year_to, "sort": sort, "sources": src, "notes": notes},
        "items": [i.to_dict() for i in items],
    }
    C.write_json(C.DEFAULT_QUEUE, queue)
    C.step("P1 学术查询")
    C.info(f"{query} → {len(items)} 条候选")
    return queue


def do_queue(all_items: bool, select: str, select_file: str, deselect: str) -> int:
    import build_queue as B

    return B.build(C.DEFAULT_QUEUE, select, select_file, deselect, all_items)


def do_download(limit: int | None, racing: bool, retry_only: bool,
                supplement: bool = False, no_scihub: bool = False,
                scihub_only: bool = False) -> int:
    import download as D

    return D.download(C.DEFAULT_QUEUE, limit, racing, retry_only,
                      supplement, no_scihub, scihub_only)


def do_finalize() -> int:
    import finalize as F

    return F.run(C.DEFAULT_QUEUE, C.PDF_DIR)


# ── 子命令 ───────────────────────────────────────────────────────────────────
def cmd_run(args: argparse.Namespace) -> int:
    import normalize as N

    if args.input:
        items, meta = N.normalize_input(args.input)
    else:
        existing = C.read_json(C.DEFAULT_QUEUE, default=None)
        if not existing:
            C.bad("没有 --input，也没有现成的队列。给一个需求或清单文件。")
            return 1
        queue = existing
        meta = queue.get("input", {})
        items = C.queue_items(queue, only_selected=False)
        C.step("复用一个已有队列")
        C.info(f"阶段：{stage_of(queue)}，共 {len(items)} 条")

    if meta.get("kind") == "query" and not items:
        queue = do_search(meta.get("query", ""), args.limit_search,
                          args.year_from, args.year_to, args.sort, args.sources)
    else:
        if args.input:
            queue = {
                "schema_version": C.SCHEMA_VERSION, "skill_version": C.SKILL_VERSION,
                "created_at": C.utcnow(),
                "stage": "awaiting_selection" if items else "needs_search",
                "input": meta, "items": [i.to_dict() for i in items],
            }
            C.write_json(C.DEFAULT_QUEUE, queue)
            C.step("P0 输入归一化")
            C.info(f"输入类型：{meta.get('kind')}；识别 {len(items)} 条")

    return _continue(queue, args)


def cmd_resume(args: argparse.Namespace) -> int:
    queue = C.read_json(C.DEFAULT_QUEUE, default=None)
    if not queue:
        C.bad(f"没有队列文件 {C.DEFAULT_QUEUE}。先跑 run --input ...")
        return 1
    C.step("继续已有队列")
    C.info(f"阶段：{stage_of(queue)}")
    return _continue(queue, args)


def _continue(queue: dict, args: argparse.Namespace) -> int:
    stage = stage_of(queue)
    items = C.queue_items(queue, only_selected=False)

    # 门①：需要用户确认选择
    confirmed = bool(args.all or args.select or args.select_file or args.yes)
    if stage in ("awaiting_selection", "needs_search") and not confirmed:
        if stage == "needs_search":
            C.warn("队列为空且被判定为检索需求，但检索没有执行（--input 可能被当成清单了）。")
        gate_one(queue)
        return 0

    if args.yes and not (args.all or args.select or args.select_file):
        # --yes 且没给具体选择：前 --limit-select 条入选
        n = args.limit_select
        pool = len(items)
        for i, it in enumerate(items, 1):
            it.selected = i <= n
        C.save_items(queue, items)
        C.info(f"--yes：自动选择前 {min(n, pool)} 条（排序靠前的）")

        # 候选池太小时，"选前 N 条"几乎等于"全选"，排序噪声必然入选。
        # 这不是理论问题：实测 --limit-search 20 配 --limit-select 15 会把
        # 「心血管疾病药物靶点预测」这类完全跑题的条目选进来。
        if pool < n * 2:
            C.warn(f"候选池只有 {pool} 条，而你要选 {n} 条——几乎没有收窄空间，"
                   f"排序靠后的噪声条目会一起入选。")
            C.info("  建议重跑并加大候选池：`--limit-search` 至少取 --limit-select 的 3 倍")
            C.info("  更稳的做法：先用 `search.py --out` 从多个查询角度各取一批，"
                   "人工挑完写成清单，再用 `--select-file` 落地（该清单里队列没有的条目会被自动追加）")

    code = do_queue(args.all, args.select, args.select_file, args.deselect)
    if code != 0:
        return code

    # 门②：策略与规模确认（非交互时打印出来，让 Agent 转述给用户）
    C.step("★门② 下载前确认")
    dl = C.load_downloads_config()
    order = (dl.get("fulltext", {}) or {}).get("order", ["scihub", "engineering"])
    C.info(f"全文顺序：{' → '.join(order)}"
           + ("（--no-scihub）" if args.no_scihub else "")
           + ("（--scihub-only）" if args.scihub_only else ""))
    C.info(f"补充材料：{'要 → 走工程化引擎（Sci-Hub 没有 SI）' if args.supplement else '不要'}")
    cfg = C.read_json(C.SCANSCI_DATA_DIR / "config.json", default={}) or {}
    C.info(f"工程化引擎：scihub_enabled={cfg.get('scihub_enabled')}, "
           f"download_strategy={cfg.get('download_strategy')}, "
           f"batch_workers={cfg.get('batch_workers')}, "
           f"延迟={cfg.get('request_delay_min')}–{cfg.get('request_delay_max')}s")
    C.info(f"输出目录：{C.PDF_DIR}")
    C.info(f"灰色源竞速：{'开' if args.racing else '按配置'}")

    code = do_download(args.limit, args.racing, args.retry_only,
                       args.supplement, args.no_scihub, args.scihub_only)
    dl_code = code
    code = do_finalize()
    return 0 if code == 0 and dl_code == 0 else 1


def cmd_status(args: argparse.Namespace) -> int:
    C.step("状态")
    if not C.is_deployed():
        C.warn("部署关未通过。先跑 bootstrap.py apply")
    else:
        dep = C.read_json(C.DEPLOY_STATE, default={}) or {}
        C.ok(f"已部署（{dep.get('deployed_at')}），策略={dep.get('policy')}，来源={dep.get('source')}")

    queue = C.read_json(C.DEFAULT_QUEUE, default=None)
    if not queue:
        C.info("没有队列。")
        return 0
    items = C.queue_items(queue, only_selected=False)
    from collections import Counter
    C.info(f"队列阶段：{stage_of(queue)}")
    C.info(f"条目：{len(items)}；状态分布：{dict(Counter(i.status for i in items))}")
    pdfs = list(C.PDF_DIR.glob("*.pdf")) if C.PDF_DIR.exists() else []
    C.info(f"PDF 目录：{C.PDF_DIR}（{len(pdfs)} 个文件）")
    return 0


def main() -> int:
    C.console()
    # status / help 不需要部署关，其余子命令自己会检查
    ap = argparse.ArgumentParser(description="文献搜索与获取智能体 · 端到端总控",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_gate_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--all", action="store_true", help="确认全部候选（门①）")
        p.add_argument("--select", default="", help="按序号勾选：1,3,5-9（门①）")
        p.add_argument("--select-file", default="",
                       help="清单文件：一行一个 DOI/arXiv 号或序号。以它为准（先清空原有选择）；"
                            "队列里没有的标识符会被追加为手工条目（origin=manual）")
        p.add_argument("--deselect", default="", help="按序号排除")
        p.add_argument("--yes", action="store_true",
                       help="非交互：自动选中排序靠前的 N 条并一路跑完（无人可问时用；"
                            "语义 = 先按顺序取前 --limit-select 条，再过门①）")
        p.add_argument("--limit-select", type=int, default=10,
                       help="--yes 时自动选前 N 条（注意：--limit-search 应至少是它的 3 倍）")
        p.add_argument("--limit", type=int, default=None, help="本次最多下载 N 条")
        p.add_argument("--racing", action="store_true", help="强制灰色源竞速引擎")
        p.add_argument("--retry-only", action="store_true", help="只重跑上次失败的条目")
        # ── V2 新增：下载层级开关 ────────────────────────────────────────────
        p.add_argument("--supplement", action="store_true",
                       help="拉补充材料。**它只能由工程化引擎完成**（Sci-Hub 只有全文 PDF），"
                            "所以打开后整体会变慢——只有用户明确要 SI 时才开")
        p.add_argument("--no-scihub", action="store_true",
                       help="跳过 Sci-Hub 直连，全部走工程化引擎")
        p.add_argument("--scihub-only", action="store_true",
                       help="只走 Sci-Hub 直连、失败不回退（对照测速用）")
        p.add_argument("--out-dir", default="", metavar="DIR",
                       help="交付物目录：PDF、元信息表、失败清单、日志全部落在这里"
                            "（默认落在 skill 自己的 workspace/pdfs）")
        p.add_argument("--sort", choices=("relevance_score", "cited_by_count", "publication_date"),
                       default="relevance_score", help="检索排序键")

    p_run = sub.add_parser("run", help="端到端：归一化 → 检索 → 门① → 队列 → 门② → 下载 → 产出")
    p_run.add_argument("--input", default="", help="文件路径，或直接的检索需求文本")
    p_run.add_argument("--limit-search", type=int, default=40,
                       help="每源取多少候选。**必须显著大于 --limit-select**："
                            "两者接近时等于没筛选，排序噪声会一起入选（建议 ≥ 3 倍）")
    p_run.add_argument("--year-from", type=int, default=None)
    p_run.add_argument("--year-to", type=int, default=None)
    p_run.add_argument("--sources", default="openalex,crossref")
    add_gate_args(p_run)

    p_resume = sub.add_parser("resume", help="从门① 继续一个已有队列")
    add_gate_args(p_resume)

    sub.add_parser("status", help="查看部署与队列状态")

    args = ap.parse_args()

    if args.cmd == "status":
        return cmd_status(args)

    ensure_runtime()
    C.require_deployed()

    # 交付物目录必须在任何阶段跑起来之前改好：各阶段都读 C.PDF_DIR，
    # 晚改会导致 PDF 落一处、元信息表落另一处。
    if getattr(args, "out_dir", ""):
        out = C.set_output_dir(args.out_dir)
        C.step("交付物目录")
        C.info(f"{out}")
        C.info("（PDF、元信息表、失败清单、日志都会落在这里；任务状态仍在 skill 的 workspace/）")

    if args.cmd == "run":
        return cmd_run(args)
    return cmd_resume(args)


if __name__ == "__main__":
    raise SystemExit(main())
