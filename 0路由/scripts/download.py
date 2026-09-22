"""P5 下载（V2 · 双引擎）。

与第一代的唯一区别就是下载层：**先直连，失败再工程化**。

    ┌── Sci-Hub 直连（scihub.py，spider 路线）──┐   快：2 请求/篇，3–10 秒
    │  成功 → 该条结束                          │
    └── 失败（反爬/未收录/下载中断）────────────┘
                     │
                     ▼
    ┌── scansci-pdf 工程化引擎 ────────────────┐   慢：多源竞速/机构通道
    │  能拿到付费墙、OA 直链、预印本            │
    └──────────────────────────────────────────┘

为什么要这个顺序：全文 PDF 这一个场景里，直连命中时比工程化引擎快一个数量级
（实测 3–10s vs 20–200s）。而工程化引擎的价值在于**直连拿不到的那些**——
付费墙、OA 直链、以及**补充材料**（Sci-Hub 只有全文 PDF，没有 SI）。

补充材料走不了直连，所以：
  * 用户**不要**补充材料 → order = [scihub, engineering]
  * 用户**要**补充材料   → 全文仍可先试直连，SI 一律交给工程化引擎
    （`supplement.order` 里写 scihub 也无效，会被跳过）

用法：
    python download.py                     # 下队列里 selected=true 的条目
    python download.py --supplement        # 额外拉补充材料（只有工程化引擎能做）
    python download.py --no-scihub         # 跳过直连，纯工程化
    python download.py --scihub-only       # 只直连，失败不回退（用于测速/对照）
    python download.py --retry-only        # 只重跑上次失败的
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C  # noqa: E402

BATCH_RESULTS = "batch_results.json"
NORMALIZED_RESULTS = "download_results.json"

REASON_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("ip_blocked", ("ip address blocked", "ip_blocked", "ipblock@", "unusual behavior",
                    "blocked automatically", " 403", "code=403", "http 403", " 429")),
    ("cf_challenge", ("cloudflare", "captcha", "turnstile", "challenge", "just a moment",
                      "cf-", "被拦截")),
    ("bad_identifier", ("invalid doi", "malformed", "cannot parse", "bad identifier",
                        "no valid identifier", "unresolved")),
    ("paywalled_no_access", ("not_entitled", "not entitled", "paywall", "subscription",
                             "no access", "requires institutional", "needs institutional",
                             "无权限", "未订阅")),
    ("network", ("timeout", "timed out", "connection", "connectionerror", "sslerror",
                 "proxyerror", "name or service not known", "getaddrinfo", "temporary failure")),
    ("not_found", ("not_found", "no pdf found", "not found", "no source", "all sources failed",
                   "no pdf", "404", "no downloadable", "exhausted", "none of the sources")),
    ("file_missing", ("file missing", "not found on disk")),
]


def classify(text: str, success: bool) -> str:
    if success:
        return ""
    low = (text or "").lower()
    for reason, needles in REASON_RULES:
        if any(n in low for n in needles):
            return reason
    return "unknown"


# ── 引擎 A：Sci-Hub 直连 ─────────────────────────────────────────────────────
def download_scihub(items: list[C.Item], cfg: dict, log: C.RunLog) -> None:
    """对一批条目走直连。成功/失败都写回 item，供后续回退使用。"""
    scihub = C.import_scihub()
    scfg = (cfg.get("fulltext", {}) or {}).get("scihub", {}) or {}
    if not scfg.get("enabled", True):
        C.info("直连已按配置关闭（downloads.json → fulltext.scihub.enabled=false）")
        for it in items:
            it.reason = it.reason or "not_found"
            it.detail = it.detail or "直连已关闭"
        return

    mirrors = scfg.get("mirrors") or None
    max_tries = int(scfg.get("max_page_tries", 10))
    pdf_retry = int(scfg.get("pdf_retry", 2))
    delay = (float(scfg.get("delay_min", 0.6)), float(scfg.get("delay_max", 2.0)))
    timeout = int(scfg.get("timeout", 30))
    gap = float(scfg.get("gap_between_papers", 1.0))

    shared = scihub.new_session()
    breaker = scihub.CircuitBreaker()
    C.step(f"P5a Sci-Hub 直连（{len(items)} 条，镜像 {mirrors or '默认'}）")
    ok_n = 0
    for n, it in enumerate(items, 1):
        if not breaker.allow():
            it.status = C.STATUS_FAIL
            it.reason = "challenge"
            it.detail = "直连已熔断，直接交给工程化引擎"
            C.warn(f"  [{n}/{len(items)}] {it.id}  跳过直连（熔断）")
            log.item(it.id, it.status, it.reason, it.detail)
            continue

        r = scihub.fetch(it.id, C.PDF_DIR, mirrors=mirrors, max_page_tries=max_tries,
                         pdf_retry=pdf_retry, delay=delay, timeout=timeout, session=shared)
        breaker.observe(r.reason if not r.ok else "")
        if r.ok:
            ok_n += 1
            it.status = C.STATUS_OK
            it.file = r.file
            it.reason = ""
            it.channel = "scihub:" + (r.mirror or "")
            it.detail = f"{r.bytes/1024:.0f} KB，{r.elapsed:.1f}s，{r.requests_made} 请求"
            C.ok(f"  [{n}/{len(items)}] {it.id}  {r.elapsed:.1f}s  {r.bytes/1024:.0f}KB")
        else:
            it.status = C.STATUS_FAIL
            it.reason = r.reason
            it.channel = ""
            it.detail = f"直连失败：{r.detail}"
            C.warn(f"  [{n}/{len(items)}] {it.id}  {r.elapsed:.1f}s  {r.reason} {r.detail[:60]}")
        log.item(it.id, it.status, it.reason, it.detail, channel=it.channel, file=it.file)
        if gap and n < len(items):
            time.sleep(gap)
    if breaker.note():
        C.warn("  " + breaker.note())
    C.info(f"直连结果：{ok_n}/{len(items)} 成功")


# ── 引擎 B：scansci-pdf 工程化 ───────────────────────────────────────────────
def _load_results(output_dir: Path) -> list[dict]:
    """读上游两份结果文件（字段互补，都要看）。"""
    rows: list[dict] = []
    data = C.read_json(output_dir / BATCH_RESULTS, default=None)
    if isinstance(data, list):
        rows += [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict) and isinstance(data.get("results"), list):
        rows += [r for r in data["results"] if isinstance(r, dict)]

    norm = C.read_json(output_dir / NORMALIZED_RESULTS, default=None)
    if isinstance(norm, dict) and isinstance(norm.get("entries"), list):
        for entry in norm["entries"]:
            if not isinstance(entry, dict):
                continue
            row = dict(entry)
            extra = " ".join(str(x) for x in (entry.get("error_type"), entry.get("reason")) if x)
            if extra:
                row["error"] = (str(row.get("error") or "") + " " + extra).strip()
            rows.append(row)
    return rows


def _result_identifier(row: dict) -> str:
    for key in ("doi", "identifier", "id", "input"):
        val = row.get(key)
        if val:
            return str(val)
    return ""


def _result_success(row: dict) -> bool:
    if row.get("success") is True:
        return True
    return str(row.get("status") or "").lower() in ("success", "ok", "downloaded")


def _result_file(row: dict) -> str:
    for key in ("file", "pdf_path", "path", "output"):
        val = row.get(key)
        if val:
            return str(val)
    return ""


def _result_detail(row: dict) -> str:
    for key in ("error", "reason", "message", "detail", "note"):
        val = row.get(key)
        if val:
            return str(val)
    q = row.get("quality")
    return f"quality={q}" if q else ""


def _result_channel(row: dict) -> str:
    for key in ("source", "channel", "strategy", "provider"):
        val = row.get(key)
        if val:
            return str(val)
    return ""


def normalize_pdf_name(doi: str, output_dir: Path) -> str:
    """确保磁盘上的文件名就是 DOI 命名（`/` → `_`）。"""
    want = C.identifier_to_filename(doi)
    target = output_dir / f"{want}.pdf"
    if target.exists():
        return str(target)
    safe = C.doi_to_filename(doi)
    for cand in output_dir.glob(f"{safe}*.pdf"):
        if cand.name == f"{want}.pdf":
            return str(cand)
        try:
            cand.replace(target)
            return str(target)
        except OSError:
            return str(cand)
    return ""


def run_batch(identifiers: list[str], output_dir: Path, racing: bool = False,
              extra_args: list[str] | None = None, timeout: float = 7200) -> tuple[int, str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    list_file = C.STATE_DIR / "download_queue.txt"
    list_file.write_text("\n".join(identifiers) + "\n", encoding="utf-8")
    args = ["batch", str(list_file), "--output", str(output_dir), "--format", "json"]
    if racing:
        args.append("--scihub")
    args += list(extra_args or [])
    C.info(f"调用 scansci-pdf batch（{len(identifiers)} 条，racing={racing}，"
           f"额外参数={extra_args or []}）")
    r = C.scansci_pdf(args, timeout=timeout, echo=True)
    return r.returncode, r.stdout or "", r.stderr or ""


def _alias_keys(identifier: str) -> list[str]:
    return C.alias_stems(identifier)


def _index_results(rows: list[dict]) -> dict[str, dict]:
    """按标识符建索引：成功行优先，失败行只留错误素材。"""
    index: dict[str, dict] = {}
    for row in rows:
        ident = _result_identifier(row)
        if not ident:
            continue
        okk = _result_success(row)
        err = _result_detail(row)
        for key in _alias_keys(ident):
            entry = index.get(key)
            if entry is None:
                index[key] = {"row": row, "errors": [err] if err else []}
                continue
            cur_ok = _result_success(entry["row"])
            if okk and not cur_ok:
                errs = entry["errors"]
                index[key] = {"row": row, "errors": errs}
            elif okk == cur_ok and not _result_file(entry["row"]) and _result_file(row):
                index[key] = {"row": row, "errors": entry["errors"]}
            elif err and err not in entry["errors"]:
                entry["errors"].append(err)
    return index


def _entry_detail(entry: dict) -> str:
    parts: list[str] = []
    row_detail = _result_detail(entry["row"])
    if row_detail:
        parts.append(row_detail)
    for err in entry.get("errors", []):
        if err and err not in parts:
            parts.append(err)
    return "；".join(parts)


def fallback_get(items: list[C.Item], timeout_each: float = 900) -> None:
    """对「上游报成功、磁盘上没有文件」的条目走单篇 get 再取一次。

    上游 batch 的竞速引擎会在"迟到的成功"上回报文件路径，而其它源还在跑
    （日志原文 `Racing finished with N source(s) still running (waived)`），
    进程收尾时那份文件可能被带走——表现为"报成功却没文件"。
    """
    if not items:
        return
    C.warn(f"{len(items)} 条回报成功但磁盘上没有文件；改走单篇 get 兜底重取")
    for it in items:
        target = C.PDF_DIR / (C.identifier_to_filename(it.id) + ".pdf")
        if target.exists() and target.stat().st_size > 0:
            it.status = C.STATUS_OK
            it.file = str(target)
            it.reason = ""
            continue
        r = C.scansci_pdf(["get", it.id, "--output", str(C.PDF_DIR)], timeout=timeout_each)
        found = normalize_pdf_name(it.id, C.PDF_DIR)
        if found:
            try:
                size = Path(found).stat().st_size / 1024
            except OSError:
                size = 0
            it.status = C.STATUS_OK
            it.reason = ""
            it.file = found
            it.detail = f"batch 报成功但文件缺失，单篇 get 兜底成功（{size:.0f} KB）"
            it.channel = f"{it.channel}+get-fallback" if it.channel else "get-fallback"
            C.ok(f"  {it.id} → 兜底成功")
        else:
            tail = [ln for ln in ((r.stderr or "") + (r.stdout or "")).strip().splitlines() if ln][-3:]
            it.status = C.STATUS_FAIL
            it.reason = classify(" ".join(tail), success=False)
            it.detail = ("batch 报成功但磁盘上没有文件，单篇 get 兜底也失败："
                         + " / ".join(tail))[:800]
            C.warn(f"  {it.id} → 兜底仍失败")


def download_engineering(items: list[C.Item], cfg: dict, log: C.RunLog,
                         racing: bool = False, label: str = "P5b 工程化引擎") -> None:
    """把一批条目交给 scansci-pdf batch，并把结果映射回队列。"""
    if not items:
        return
    ecfg = cfg.get("engineering", {}) or {}
    batch_timeout = float(ecfg.get("batch_timeout", 7200))
    extra_args = list(ecfg.get("batch_args") or [])

    C.step(f"{label}（{len(items)} 条）")
    code, out, err = run_batch([i.id for i in items], C.PDF_DIR, racing=racing,
                               extra_args=extra_args, timeout=batch_timeout)
    rows = _load_results(C.PDF_DIR)
    by_id = _index_results(rows)
    suspect: list[C.Item] = []

    for it in items:
        entry = next((by_id[k] for k in _alias_keys(it.id) if k in by_id), None)
        if entry is None:
            found = normalize_pdf_name(it.id, C.PDF_DIR)
            it.status = C.STATUS_OK if found else C.STATUS_FAIL
            it.file = found
            if not found:
                it.reason = "not_found"
                it.detail = "上游没有为该条目返回结果行，且磁盘上没有对应 PDF"
        else:
            row = entry["row"]
            okk = _result_success(row)
            path = _result_file(row) or normalize_pdf_name(it.id, C.PDF_DIR)
            detail = _entry_detail(entry)
            it.channel = _result_channel(row)
            if okk and path:
                real = Path(path)
                if real.exists() and real.stat().st_size > 0:
                    it.status = C.STATUS_OK
                    it.file = str(real)
                    it.reason = ""
                else:
                    it.status = C.STATUS_FAIL
                    it.reason = "file_missing"
                    it.detail = "batch 报成功，但磁盘上找不到该文件（疑为竞速引擎收尾竞态）"
                    suspect.append(it)
            elif okk:
                it.status = C.STATUS_OK
                it.file = it.file or normalize_pdf_name(it.id, C.PDF_DIR)
            else:
                it.status = C.STATUS_FAIL
                it.reason = classify(detail, success=False)
                it.detail = (detail or "上游未给出错误信息")[:800]

    if suspect:
        fallback_get(suspect)

    for it in items:
        log.item(it.id, it.status, it.reason, it.detail, channel=it.channel, file=it.file)

    if code != 0 and not rows:
        C.warn(f"scansci-pdf 退出码 {code}，且没有产出结果文件；按磁盘文件判定结果。")
        if err.strip():
            C.info(err.strip()[-400:])


def download_supplement(items: list[C.Item], cfg: dict, log: C.RunLog) -> None:
    """补充材料：只有工程化引擎能做（Sci-Hub 不提供 SI）。"""
    scfg = cfg.get("supplement", {}) or {}
    si_args = list(scfg.get("engineering_args") or ["--si"])
    if not items:
        return
    C.step(f"P5c 补充材料（{len(items)} 条 · 走工程化引擎 {si_args}）")
    C.warn("Sci-Hub 只有全文 PDF、没有补充材料；这一步只能由 scansci-pdf 完成，"
           "所以会比只下全文慢很多。")

    per_paper = float((cfg.get("engineering", {}) or {}).get("timeout_per_paper", 900))
    for it in items:
        r = C.scansci_pdf(["get", it.id, "--output", str(C.PDF_DIR), *si_args],
                          timeout=per_paper)
        out = (r.stdout or "") + (r.stderr or "")
        si_files = [p for p in C.PDF_DIR.glob(f"{C.doi_to_filename(it.id)}*")
                    if p.suffix.lower() != ".pdf"]
        if si_files:
            it.detail = (it.detail + f"；补充材料 {len(si_files)} 个："
                         + ", ".join(p.name for p in si_files[:3])).strip("；")
            C.ok(f"  {it.id} → {len(si_files)} 个补充文件")
        else:
            tail = " / ".join([ln for ln in out.strip().splitlines() if ln][-2:])
            C.warn(f"  {it.id} → 没有拿到补充材料（{tail[:120]}）")
        log.item(it.id, it.status, it.reason, it.detail, supplement=bool(si_files))


# ── 编排 ─────────────────────────────────────────────────────────────────────
def download(queue_path: Path | None = None, limit: int | None = None,
             racing: bool = False, retry_only: bool = False,
             supplement: bool = False, no_scihub: bool = False,
             scihub_only: bool = False) -> int:
    queue_path = queue_path or C.DEFAULT_QUEUE
    queue = C.load_queue(queue_path)
    cfg = C.load_downloads_config()

    all_items = C.queue_items(queue, only_selected=False)
    items = [i for i in all_items if i.selected]
    if retry_only:
        items = [i for i in items if i.status == C.STATUS_FAIL]
    else:
        items = [i for i in items if i.status != C.STATUS_SKIP]
    if not items:
        C.warn("没有需要下载的条目。")
        return 0
    if limit:
        items = items[:limit]

    with_id = [i for i in items if i.kind in ("doi", "arxiv")]
    no_id = [i for i in items if i.kind not in ("doi", "arxiv")]
    for it in no_id:
        it.status = C.STATUS_FAIL
        it.reason = "bad_identifier"
        it.detail = "没有可用的 DOI / arXiv 号，无法下载"

    log = C.RunLog("download")
    order = (cfg.get("fulltext", {}) or {}).get("order", ["scihub", "engineering"])
    log.log("start", count=len(with_id), output_dir=str(C.PDF_DIR),
            order=order, supplement=supplement, racing=racing)

    C.step("P5 下载策略")
    C.info(f"全文顺序：{' → '.join(order)}"
           + ("（--no-scihub：跳过直连）" if no_scihub else "")
           + ("（--scihub-only：不回退）" if scihub_only else ""))
    C.info(f"补充材料：{'要（只能走工程化引擎）' if supplement else '不要'}")
    C.info(f"输出目录：{C.PDF_DIR}")

    remaining = list(with_id)
    if "scihub" in order and not no_scihub:
        download_scihub(remaining, cfg, log)
        remaining = [i for i in remaining if i.status != C.STATUS_OK]
        C.info(f"直连之后仍需工程化引擎的：{len(remaining)} 条")

    if "engineering" in order and not scihub_only:
        download_engineering(remaining, cfg, log, racing=racing)

    if supplement:
        download_supplement(list(with_id), cfg, log)

    for it in no_id:
        log.item(it.id, it.status, it.reason, it.detail)

    C.save_items(queue, all_items, queue_path)

    okk = sum(1 for i in items if i.status == C.STATUS_OK)
    ok_scihub = sum(1 for i in items
                    if i.status == C.STATUS_OK and (i.channel or "").startswith("scihub"))
    ok_eng = okk - ok_scihub
    failed = [i for i in items if i.status == C.STATUS_FAIL]
    log.close(summary=f"{okk}/{len(items)} 成功（直连 {ok_scihub}，工程化 {ok_eng}）")

    C.step("下载结果")
    C.ok(f"成功 {okk} / 共 {len(items)}（直连 {ok_scihub}，工程化 {ok_eng}）")
    if failed:
        C.bad(f"失败 {len(failed)}：")
        for reason, n in Counter(i.reason for i in failed).most_common():
            C.info(f"  {reason:<22} {n} 条")
    C.info(f"日志：{log.markdown}")
    return 0 if okk else 1


def main() -> int:
    C.console()
    ap = argparse.ArgumentParser(description="P5 · 下载（V2 双引擎）")
    ap.add_argument("--queue", default=str(C.DEFAULT_QUEUE))
    ap.add_argument("--limit", type=int, default=None, help="只下前 N 条（先试水用）")
    ap.add_argument("--racing", action="store_true", help="工程化引擎强制用灰色源竞速（--scihub）")
    ap.add_argument("--retry-only", action="store_true", help="只重跑上次失败的条目")
    ap.add_argument("--supplement", action="store_true",
                    help="额外拉补充材料（只有工程化引擎能做，会明显变慢）")
    ap.add_argument("--no-scihub", action="store_true", help="跳过 Sci-Hub 直连，纯工程化")
    ap.add_argument("--scihub-only", action="store_true",
                    help="只走直连、失败不回退（对照测速用）")
    ap.add_argument("--out-dir", default="", metavar="DIR",
                    help="PDF 输出目录（默认 workspace/pdfs）")
    args = ap.parse_args()

    if args.out_dir:
        C.set_output_dir(args.out_dir)
    return download(Path(args.queue), args.limit, args.racing, args.retry_only,
                    args.supplement, args.no_scihub, args.scihub_only)


if __name__ == "__main__":
    raise SystemExit(main())
