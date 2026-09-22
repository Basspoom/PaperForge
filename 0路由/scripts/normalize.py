"""P0 输入归一化：把任何形式的输入变成统一的条目列表。

支持：自然语言检索需求、DOI/arXiv 清单（txt/csv/xlsx）、
BibTeX / RIS / EndNote(.nbib) / APA 等引文文本、以及上述混排。

用法：
    python normalize.py --input dois.txt
    python normalize.py --input "钙钛矿太阳能电池稳定性 2020 以来高被引 20 篇"
    python normalize.py --input refs.bib --out workspace/state/queue.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C  # noqa: E402

# DOI 的宽松匹配：Crossref 实际注册的 DOI 前缀是 10.<4-9 位数字>
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9<>]+\b")
ARXIV_RE = re.compile(r"\b(?:arXiv[:\s]*)?(\d{4}\.\d{4,5})(?:v\d+)?\b")

DOI_COLUMN_HINTS = ("doi", "dois", "digital object identifier", "doi号", "doi 号", "文献doi")
TITLE_COLUMN_HINTS = ("title", "题名", "标题", "文献标题", "篇名", "论文标题")
YEAR_COLUMN_HINTS = ("year", "年份", "年", "发表年份", "出版年")
JOURNAL_COLUMN_HINTS = ("journal", "期刊", "来源", "刊物", "source")
AUTHOR_COLUMN_HINTS = ("author", "authors", "作者", "第一作者")


# ── 基础工具 ─────────────────────────────────────────────────────────────────
def _clean_doi(raw: str) -> str:
    doi = C.normalize_doi(raw)
    doi = doi.rstrip(".,;)]}>\"'")
    return doi


def _split_authors(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"\s*(?:;|\band\b|、|，|,)\s*", raw)
    return [p.strip() for p in parts if p.strip()][:30]


def _looks_like_prose(text: str) -> bool:
    """输入更像「检索需求」而不是「标识符清单」时返回 True。

    仅用于 --as-query 的辅助判断与日志说明；normalize_text 不依赖它做路由。
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    id_like = sum(1 for ln in lines if C.identifier_kind(ln) != "unknown")
    if id_like and id_like >= max(1, int(len(lines) * 0.5)):
        return False
    if len(lines) == 1 and len(lines[0]) > 40:
        return True
    return not any(C.identifier_kind(ln) != "unknown" for ln in lines)


# ── 各格式解析 ───────────────────────────────────────────────────────────────
def parse_bibtex(text: str) -> list[C.Item]:
    items: list[C.Item] = []
    for block in re.findall(r"@\w+\s*\{[^@]*", text):
        def field(name: str) -> str:
            m = re.search(rf"\b{name}\s*=\s*[{{\"](.+?)[}}\"]\s*,?\s*(?=\n\s*\w+\s*=|\}})",
                          block, re.I | re.S)
            return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

        doi = _clean_doi(field("doi"))
        title = field("title")
        year = (re.search(r"\d{4}", field("year") or field("date")) or [""])[0] if (field("year") or field("date")) else ""
        if not doi and not title:
            continue
        ident = doi if doi else ""
        items.append(C.Item(
            id=ident or f"title:{title[:80]}",
            kind="doi" if doi else "unknown",
            title=title,
            authors=_split_authors(field("author")),
            year=year,
            journal=field("journal") or field("booktitle"),
            source="bibtex",
            origin="direct",
        ))
    return items


def parse_ris(text: str) -> list[C.Item]:
    items: list[C.Item] = []
    current: dict[str, list[str]] = {}

    def flush() -> None:
        if not current:
            return
        doi = _clean_doi((current.get("DO") or [""])[0])
        title = (current.get("TI") or current.get("T1") or [""])[0]
        if not doi and not title:
            return
        items.append(C.Item(
            id=doi or f"title:{title[:80]}",
            kind="doi" if doi else "unknown",
            title=title,
            authors=[a for a in current.get("AU", []) if a][:30],
            year=((current.get("PY") or current.get("Y1") or [""])[0] or "")[:4],
            journal=(current.get("JO") or current.get("JF") or current.get("T2") or [""])[0],
            abstract=(current.get("AB") or [""])[0][:500],
            source="ris",
            origin="direct",
        ))

    for line in text.splitlines():
        if line.startswith("ER  -") or line.startswith("ER -"):
            flush()
            current = {}
            continue
        m = re.match(r"^([A-Z][A-Z0-9])\s{1,2}-\s?(.*)$", line)
        if m:
            current.setdefault(m.group(1), []).append(m.group(2).strip())
    flush()
    return items


def parse_medline(text: str) -> list[C.Item]:
    items: list[C.Item] = []
    current: dict[str, list[str]] = {}

    def flush() -> None:
        if not current:
            return
        doi = ""
        for cand in current.get("DO", []) + current.get("LID", []):
            if "10." in cand:
                doi = _clean_doi(cand)
                break
        title = (current.get("TI") or [""])[0]
        if not doi and not title:
            return
        items.append(C.Item(
            id=doi or f"title:{title[:80]}",
            kind="doi" if doi else "unknown",
            title=title,
            authors=[a for a in current.get("AU", []) if a][:30],
            year=((current.get("DP") or [""])[0] or "")[:4],
            journal=(current.get("JT") or current.get("TA") or [""])[0],
            abstract=(current.get("AB") or [""])[0][:500],
            source="medline",
            origin="direct",
        ))

    for line in text.splitlines():
        if not line.strip():
            flush()
            current = {}
            continue
        m = re.match(r"^([A-Z]{2,4})\s*-\s?(.*)$", line)
        if m:
            current.setdefault(m.group(1), []).append(m.group(2).strip())
    flush()
    return items


def _row_to_item(row: dict[str, str], source: str) -> C.Item | None:
    lower = {str(k).strip().lower(): ("" if v is None else str(v).strip()) for k, v in row.items() if k}

    def pick(hints) -> str:
        for hint in hints:
            for key, val in lower.items():
                if key == hint or hint in key:
                    if val:
                        return val
        return ""

    doi_cell = pick(DOI_COLUMN_HINTS)
    doi = _clean_doi(doi_cell) if doi_cell else ""
    if not doi:
        # 单元格里可能塞了整条引文
        found = DOI_RE.findall(" ".join(lower.values()))
        doi = _clean_doi(found[0]) if found else ""

    title = pick(TITLE_COLUMN_HINTS)
    if not doi and not title:
        return None
    return C.Item(
        id=doi or f"title:{title[:80]}",
        kind="doi" if doi else "unknown",
        title=title,
        authors=_split_authors(pick(AUTHOR_COLUMN_HINTS)),
        year=(re.search(r"\d{4}", pick(YEAR_COLUMN_HINTS)) or [""])[0] if pick(YEAR_COLUMN_HINTS) else "",
        journal=pick(JOURNAL_COLUMN_HINTS),
        source=source,
        origin="direct",
    )


def parse_csv(text: str) -> list[C.Item]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    return [it for it in (_row_to_item(row, "csv") for row in reader) if it]


def parse_xlsx(path: Path) -> list[C.Item]:
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError:
        C.warn("没有 openpyxl，读不了 .xlsx。用 pipeline.py 跑（它会自动切到 venv 解释器），或先另存为 .csv。")
        return []
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    try:
        header = [str(h) if h is not None else "" for h in next(rows)]
    except StopIteration:
        return []
    out: list[C.Item] = []
    for values in rows:
        row = {header[i]: values[i] for i in range(min(len(header), len(values)))}
        item = _row_to_item(row, "xlsx")
        if item:
            out.append(item)
    wb.close()
    return out


# ── 主导航 ───────────────────────────────────────────────────────────────────
def _scan_identifiers(text: str) -> list[C.Item]:
    """全文本扫 DOI / arXiv 号。覆盖 APA、杂排清单、聊天记录粘贴等自由格式。

    注意：arXiv 的 DataCite DOI（10.48550/arXiv.xxxx.xxxxx）里本身就嵌着一个
    arXiv 号。所以先记下所有 DOI 的字符区间，落在这些区间内的 arXiv 命中要跳过，
    否则同一篇预印本会被识别成两条。
    """
    items: list[C.Item] = []
    seen: set[str] = set()
    doi_spans: list[tuple[int, int]] = []

    for m in DOI_RE.finditer(text):
        doi = _clean_doi(m.group(0))
        if not doi:
            continue
        doi_spans.append(m.span())
        key = C.dedup_key(doi)
        if key in seen:
            continue
        seen.add(key)
        kind = "arxiv" if C.arxiv_from_doi(doi) else "doi"
        items.append(C.Item(id=doi, kind=kind, source="text-scan", origin="direct"))

    for m in ARXIV_RE.finditer(text):
        start, end = m.span()
        if any(s <= start < e or s < end <= e for s, e in doi_spans):
            continue
        raw = m.group(1)
        key = C.dedup_key(raw)
        if key in seen:
            continue
        seen.add(key)
        items.append(C.Item(id=raw, kind="arxiv", source="text-scan", origin="direct"))

    return items


def normalize_text(text: str) -> tuple[list[C.Item], dict]:
    """把任意文本解析成条目；确实解析不出标识符时，才判定为「检索需求」。

    顺序很重要：先认结构化格式，再全文扫标识符，最后才当作检索需求。
    反过来的话，一段 BibTeX 会被误判成自然语言需求。
    """
    meta: dict = {"kind": "unknown"}
    items: list[C.Item] = []

    if re.search(r"^@\w+\s*\{", text, re.M):
        items = parse_bibtex(text)
        meta["kind"] = "bibtex"
    elif re.search(r"^TY\s{1,2}-\s", text, re.M):
        items = parse_ris(text)
        meta["kind"] = "ris"
    elif re.search(r"^PMID-\s", text, re.M):
        items = parse_medline(text)
        meta["kind"] = "medline"
    elif len(text.splitlines()) > 1 and "," in text.splitlines()[0]:
        items = parse_csv(text)
        if items:
            meta["kind"] = "csv"

    if items:
        return items, meta

    items = _scan_identifiers(text)
    if items:
        meta["kind"] = "id-list"
        return items, meta

    meta.update({"kind": "query", "query": " ".join(text.split())})
    return [], meta


def normalize_input(raw: str) -> tuple[list[C.Item], dict]:
    """raw 可以是文件路径，也可以是直接的文本/需求描述。"""
    p = Path(raw)
    meta: dict = {"input": raw if p.exists() else raw[:200]}
    if p.exists() and p.is_file():
        meta["kind_file"] = p.suffix.lower()
        meta["kind_path"] = str(p)
        if p.suffix.lower() == ".xlsx":
            items = parse_xlsx(p)
            meta["kind"] = "xlsx"
        else:
            items = []
    else:
        items = []

    if not items:
        text = p.read_text(encoding="utf-8", errors="replace") if (p.exists() and p.is_file()) else raw
        items, info = normalize_text(text)
        meta.update(info)

    return dedup(items), meta


def dedup(items: list[C.Item]) -> list[C.Item]:
    """按统一去重键去重（见 C.dedup_key）；没有标识符的按标题归一化。"""
    seen: dict[str, C.Item] = {}
    order: list[str] = []
    for it in items:
        key = C.dedup_key(it.id, it.title)
        if key in seen:
            # 合并：把非空字段补给已有条目
            prev = seen[key]
            for f in ("title", "year", "journal", "abstract"):
                if not getattr(prev, f) and getattr(it, f):
                    setattr(prev, f, getattr(it, f))
            if not prev.authors and it.authors:
                prev.authors = it.authors
            # 已经被归一化成 DOI 形态的条目优先保留（信息更全、可直接下载）
            if prev.kind != "doi" and it.kind == "doi":
                it.authors = it.authors or prev.authors
                it.title = it.title or prev.title
                seen[key] = it
            continue
        seen[key] = it
        order.append(key)
    return [seen[k] for k in order]


def mark_duplicates(items: list[C.Item]) -> None:
    """把重复项标成 skipped，保留在表里以便用户看到。"""
    seen: set[str] = set()
    for it in items:
        key = C.dedup_key(it.id, it.title)
        if key in seen:
            it.status = C.STATUS_SKIP
            it.reason = "duplicate"
            it.detail = "队列中已有同一标识符"
            it.selected = False
        else:
            seen.add(key)


def main() -> int:
    C.console()
    ap = argparse.ArgumentParser(description="P0 · 输入归一化")
    ap.add_argument("--input", required=True, help="文件路径，或直接的检索需求文本")
    ap.add_argument("--out", default=str(C.DEFAULT_QUEUE), help="队列输出路径")
    ap.add_argument("--as-query", action="store_true", help="强制当作检索需求（即使看起来像清单）")
    args = ap.parse_args()

    C.ensure_dirs()
    items, meta = normalize_input(args.input)
    if args.as_query:
        meta.update({"kind": "query", "query": args.input})

    queue = {
        "schema_version": C.SCHEMA_VERSION,
        "skill_version": C.SKILL_VERSION,
        "created_at": C.utcnow(),
        "stage": "awaiting_selection" if items else "needs_search",
        "input": meta,
        "items": [i.to_dict() for i in items],
    }
    C.write_json(Path(args.out), queue)

    C.step("输入归一化")
    C.info(f"输入类型：{meta.get('kind')}")
    C.info(f"识别到 {len(items)} 条")
    if meta.get("kind") == "query":
        C.info(f"判定为「检索需求」，下一步走 1学术查询：{meta.get('query')}")
    else:
        for i, it in enumerate(items[:15], 1):
            C.info(f"{i:>3}. [{it.kind}] {it.id}  {it.title[:60]}")
        if len(items) > 15:
            C.info(f"     …… 其余 {len(items)-15} 条见队列文件")
    C.ok(f"已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
