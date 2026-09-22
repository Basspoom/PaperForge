"""P1 学术查询：多源检索 → 去重 → 排序 → 候选表。

主干直接复用本地化的 `1学术查询/`：
  - OpenAlex 通道调用 `1学术查询/scripts/academic_search.py`（纯标准库、无需 key、无 MCP 依赖）
  - Crossref 通道直连 REST API（纯标准库）
  - 可选再叠加 `2工程化下载` 自带的 `scansci-pdf search`

用法：
    python search.py --query "perovskite solar cell stability" --limit 20
    python search.py --query "钙钛矿稳定性" --year-from 2020 --sort cited_by_count
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C  # noqa: E402

OPENALEX_SCRIPT = C.SEARCH_DIR / "scripts" / "academic_search.py"

SORTS = ("relevance_score", "cited_by_count", "publication_date")

# 先按相关性取一个更宽的候选池，再本地重排——避免"全局高被引但跑题"的结果
POOL_FACTOR = 5


def _ua(mailto: str) -> str:
    who = mailto or "anonymous@example.invalid"
    return f"paperforge/1.0 (mailto:{who})"


def _http_json(url: str, mailto: str, timeout: float = 45.0) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": _ua(mailto), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── 通道 1：OpenAlex（复用本地化的 1学术查询 脚本） ──────────────────────────
def search_openalex(query: str, limit: int, year_from: int | None, year_to: int | None,
                    mailto: str, sort: str) -> tuple[list[C.Item], str]:
    if not OPENALEX_SCRIPT.exists():
        return [], f"找不到 {OPENALEX_SCRIPT}"
    args = [C.python_exe(), OPENALEX_SCRIPT, query, "--limit", str(limit), "--sort", sort]
    if year_from:
        args += ["--year-from", str(year_from)]
    if mailto:
        args += ["--mailto", mailto]

    r = C.run(args, timeout=300)
    # OpenAlex 对无 mailto 的匿名调用限速很严（常见 429）。退避重试两次。
    attempt = 0
    while r.returncode != 0 and "429" in ((r.stderr or "") + (r.stdout or "")) and attempt < 2:
        attempt += 1
        wait = 5 * attempt
        C.info(f"OpenAlex 429 限速，{wait}s 后重试（第 {attempt}/2 次）")
        C.sleep_ms(wait * 1000)
        r = C.run(args, timeout=300)

    if r.returncode != 0:
        reason = (r.stderr or r.stdout or "academic_search.py 失败").strip()[-300:]
        if "429" in reason:
            reason += "\n   → 给 bootstrap.py 传 --email，或设 OPENALEX_MAILTO，进礼貌池后可解除限速。"
        return [], reason

    out = r.stdout or ""
    start = out.find("[")
    if start < 0:
        return [], "academic_search.py 输出里没有 JSON 数组"
    try:
        rows = json.loads(out[start:])
    except json.JSONDecodeError as exc:
        return [], f"解析 OpenAlex 结果失败：{exc}"

    items: list[C.Item] = []
    for row in rows:
        doi = C.normalize_doi(str(row.get("doi") or ""))
        year = row.get("year")
        if year_to and year and year > year_to:
            continue
        title = str(row.get("title") or "")
        items.append(C.Item(
            id=doi or f"title:{title[:80]}",
            kind="doi" if doi else "unknown",
            title=title,
            authors=[a for a in (row.get("authors") or []) if a],
            year=str(year or ""),
            journal=str(row.get("journal") or ""),
            abstract=str(row.get("abstract") or "")[:500],
            cited_by_count=int(row.get("cited_by_count") or 0),
            source="openalex",
            origin="search",
        ))
    return items, f"OpenAlex {len(items)} 条"


# ── 通道 2：Crossref（直连 REST，纯标准库） ─────────────────────────────────
def search_crossref(query: str, limit: int, year_from: int | None, year_to: int | None,
                    mailto: str, sort: str) -> tuple[list[C.Item], str]:
    """Crossref 检索。

    注意一个真实坑：Crossref 的 `sort=is-referenced-by-count` 是**全局**排序，
    它会在整库范围内按被引排，而 query 只做过滤——于是「perovskite stability」
    会返回 SARS-CoV-2 这类全局高被引论文，主题完全跑偏。
    所以这里永远先用相关性取一个更大的候选池，再在本地按目标字段重排。
    """
    pool = min(max(limit * POOL_FACTOR, limit), 100)
    params = {"query": query, "rows": str(pool)}
    if mailto:
        params["mailto"] = mailto
    filters = []
    if year_from:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if year_to:
        filters.append(f"until-pub-date:{year_to}-12-31")
    if filters:
        params["filter"] = ",".join(filters)

    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    try:
        data = _http_json(url, mailto)
    except Exception as exc:  # noqa: BLE001
        return [], f"Crossref 失败：{type(exc).__name__}: {exc}"

    rows = ((data or {}).get("message") or {}).get("items") or []  # type: ignore[union-attr]
    items: list[C.Item] = []
    for row in rows:
        doi = C.normalize_doi(str(row.get("DOI") or ""))
        title = ""
        titles = row.get("title") or []
        if titles:
            title = re.sub(r"<[^>]+>", "", str(titles[0])).strip()
        year = ""
        for key in ("published-print", "published-online", "published", "issued", "created"):
            parts = ((row.get(key) or {}).get("date-parts") or [[]])[0]
            if parts:
                year = str(parts[0])
                break
        authors = []
        for a in row.get("author") or []:
            name = " ".join(x for x in (a.get("given"), a.get("family")) if x).strip()
            if name:
                authors.append(name)
        items.append(C.Item(
            id=doi or f"title:{title[:80]}",
            kind="doi" if doi else "unknown",
            title=title,
            authors=authors[:30],
            year=year,
            journal=str((row.get("container-title") or [""])[0]),
            cited_by_count=int(row.get("is-referenced-by-count") or 0),
            source="crossref",
            origin="search",
        ))

    items = rank(items, sort)[:limit]
    return items, f"Crossref {len(items)} 条（相关性池 {pool} → 本地按 {sort} 重排）"


# ── 通道 3：scansci-pdf 自带检索（可选） ─────────────────────────────────────
def search_scansci(query: str, limit: int, year_from: int | None, year_to: int | None) -> tuple[list[C.Item], str]:
    if not C.venv_python():
        return [], "venv 不存在，跳过"
    yr = ""
    if year_from and year_to:
        yr = f"{year_from}-{year_to}"
    elif year_from:
        yr = f"{year_from}-"
    args = ["search", query, "--limit", str(limit)]
    if yr:
        args += ["--year", yr]
    r = C.scansci_pdf(args, timeout=300)
    if r.returncode != 0:
        return [], f"scansci-pdf search 失败：{((r.stderr or r.stdout) or '').strip()[-200:]}"

    items: list[C.Item] = []
    text = r.stdout or ""
    # scansci-pdf search 输出是 Markdown 风格的结果块；只抽 DOI 与标题
    blocks = re.split(r"\n(?=###\s|\d+\.\s)", text)
    for blk in blocks:
        m = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", blk)
        if not m:
            continue
        doi = C.normalize_doi(m.group(0))
        title_m = re.search(r"(?:###\s*\d*\.?\s*|\d+\.\s*)(.+)", blk)
        title = title_m.group(1).strip() if title_m else ""
        items.append(C.Item(id=doi, kind="doi", title=title, source="scansci-pdf", origin="search"))
    return items, f"scansci-pdf {len(items)} 条"


# ── 合并 ─────────────────────────────────────────────────────────────────────
def merge(*groups: list[C.Item]) -> list[C.Item]:
    """按 DOI 优先、标题兜底合并；保留信息量最大的那条。"""
    import normalize as N  # 复用同一套去重规则

    def richness(it: C.Item) -> int:
        return (bool(it.abstract) * 3 + bool(it.journal) * 2 + len(it.authors) +
                bool(it.year) + (it.cited_by_count > 0) + (it.kind == "doi") * 2)

    merged: dict[str, C.Item] = {}
    for group in groups:
        for it in group:
            key = C.dedup_key(it.id, it.title)
            cur = merged.get(key)
            if cur is None or richness(it) > richness(cur):
                if cur is not None:
                    it.cited_by_count = max(it.cited_by_count, cur.cited_by_count)
                    if not it.abstract:
                        it.abstract = cur.abstract
                    it.source = f"{cur.source}+{it.source}" if cur.source not in it.source else it.source
                merged[key] = it
    out = N.dedup(list(merged.values()))
    return out


def rank(items: list[C.Item], sort: str) -> list[C.Item]:
    if sort == "cited_by_count":
        return sorted(items, key=lambda i: (-i.cited_by_count, i.year or "0"), reverse=False)
    if sort == "publication_date":
        return sorted(items, key=lambda i: (i.year or "0", i.cited_by_count), reverse=True)
    return items


def run_search(query: str, limit: int, year_from: int | None, year_to: int | None,
               mailto: str, sort: str, sources: list[str]) -> tuple[list[C.Item], list[str]]:
    notes: list[str] = []
    groups: list[list[C.Item]] = []
    if "openalex" in sources:
        items, note = search_openalex(query, limit, year_from, year_to, mailto, sort)
        groups.append(items); notes.append(note)
    if "crossref" in sources:
        items, note = search_crossref(query, limit, year_from, year_to, mailto, sort)
        groups.append(items); notes.append(note)
    if "scansci" in sources:
        items, note = search_scansci(query, limit, year_from, year_to)
        groups.append(items); notes.append(note)
    merged = merge(*groups) if groups else []
    return rank(merged, sort), notes


def main() -> int:
    C.console()
    ap = argparse.ArgumentParser(description="P1 · 学术查询")
    ap.add_argument("--query", required=True, help="检索需求（自然语言或关键词）")
    ap.add_argument("--limit", type=int, default=20, help="每源取多少条候选")
    ap.add_argument("--year-from", type=int, default=None)
    ap.add_argument("--year-to", type=int, default=None)
    ap.add_argument("--sort", choices=SORTS, default="relevance_score")
    ap.add_argument("--sources", default="openalex,crossref", help="逗号分隔：openalex,crossref,scansci")
    ap.add_argument("--mailto", default="")
    ap.add_argument("--out", default=str(C.DEFAULT_QUEUE))
    args = ap.parse_args()

    C.ensure_dirs()
    mailto = args.mailto or C.load_config_state().get("email", "")
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    C.step("P1 学术查询")
    C.info(f"需求：{args.query}")
    C.info(f"通道：{', '.join(sources)}；排序：{args.sort}")

    items, notes = run_search(args.query, args.limit, args.year_from, args.year_to, mailto, args.sort, sources)
    for n in notes:
        C.info(n)

    if not items:
        C.bad("所有通道都没返回结果。可以：放宽关键词 / 去掉年份限制 / 换 --sort / 检查网络与代理。")
        return 1

    queue = {
        "schema_version": C.SCHEMA_VERSION,
        "skill_version": C.SKILL_VERSION,
        "created_at": C.utcnow(),
        "stage": "awaiting_selection",
        "input": {"kind": "query", "query": args.query,
                  "year_from": args.year_from, "year_to": args.year_to,
                  "sort": args.sort, "sources": sources, "notes": notes},
        "items": [i.to_dict() for i in items],
    }
    C.write_json(Path(args.out), queue)

    C.step(f"候选文献（{len(items)} 条）")
    for i, it in enumerate(items, 1):
        cite = f"{it.cited_by_count:>6}" if it.cited_by_count else "     -"
        C.info(f"{i:>3}. [{cite}] {it.year or '----'} {it.id or '(无 DOI)'}")
        C.info(f"      {it.title[:100]}")
    C.ok(f"已写入 {args.out}")
    C.info("★门①：把这张表给用户确认，然后用 pipeline.py queue --select 收窄范围。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
