"""P3 队列构建：★门① 收窄选择 → 补全缺失 DOI → 去重 → 就绪队列。

用法：
    python build_queue.py --all                       # 确认全部候选
    python build_queue.py --select 1,3,5-9            # 按候选表序号勾选
    python build_queue.py --select-file picks.txt     # 文件里一行一个 DOI / 序号
    python build_queue.py --deselect 2,4
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C  # noqa: E402
import normalize as N  # noqa: E402


_INDEX_RE = re.compile(r"^\d+(?:-\d+)?$")


def _looks_like_index(token: str) -> bool:
    """这个 token 是"候选表序号"还是"标识符"？

    判别必须严格：**一个 DOI 里完全可能带连字符**
    （`10.1038/s41579-024-01132-z`、`10.1109/wi-iat55865.2022.00148`），
    早期版本用「含 `-` 就当序号」的宽松判别，把这些 DOI 当成区间解析、
    结果它们被静默排除在选中列表之外——26 条只选中 20 条。
    正确判据：整串只由数字、逗号、连字符组成才算序号表达式。
    """
    return bool(re.fullmatch(r"[\d,\-]+", token or ""))


def _parse_selection(spec: str, count: int) -> set[int]:
    """解析 `1,3,5-9` 形式的序号选择（1-based）。"""
    picked: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        m = re.match(r"^(\d+)-(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            picked.update(range(min(lo, hi), max(lo, hi) + 1))
        elif part.isdigit():
            picked.add(int(part))
    return {n for n in picked if 1 <= n <= count}


def resolve_title_to_doi(title: str, mailto: str, year: str = "") -> str:
    """按标题在 Crossref 找回 DOI。只在条目确实没有 DOI 时调用。"""
    if not title or len(title) < 12:
        return ""
    params = {"query.bibliographic": title, "rows": "3"}
    if mailto:
        params["mailto"] = mailto
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": f"paperforge/1.0 (mailto:{mailto or 'anonymous@example.invalid'})",
                      "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return ""

    best = ""
    best_score = 0.0
    norm_title = re.sub(r"\W+", "", title.lower())
    for row in ((data.get("message") or {}).get("items") or []):
        cand_title = ""
        titles = row.get("title") or []
        if titles:
            cand_title = re.sub(r"<[^>]+>", "", str(titles[0]))
        if not cand_title:
            continue
        # 用归一化标题的字符 2-gram 重合度做保守校验，避免张冠李戴
        a, b = norm_title, re.sub(r"\W+", "", cand_title.lower())
        if not a or not b:
            continue
        grams_a = {a[i:i + 2] for i in range(len(a) - 1)}
        grams_b = {b[i:i + 2] for i in range(len(b) - 1)}
        score = len(grams_a & grams_b) / max(1, len(grams_a | grams_b))
        if score > best_score:
            best_score, best = score, C.normalize_doi(str(row.get("DOI") or ""))
    return best if best_score >= 0.75 else ""


def _crossref_batch_meta(dois: list[str], mailto: str) -> dict[str, dict]:
    """一次请求取回多篇的元信息（Crossref 支持 filter 里并列多个 doi）。"""
    import json
    import urllib.request

    params = {
        "filter": ",".join(f"doi:{d}" for d in dois),
        "rows": str(max(len(dois), 20)),
        "select": "DOI,title,author,issued,container-title,is-referenced-by-count",
    }
    if mailto:
        params["mailto"] = mailto
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"paperforge/1.0 (mailto:{mailto or 'anonymous@example.invalid'})",
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}

    out: dict[str, dict] = {}
    for row in ((data.get("message") or {}).get("items") or []):
        doi = C.normalize_doi(str(row.get("DOI") or "")).lower()
        if not doi:
            continue
        title = ""
        titles = row.get("title") or []
        if titles:
            title = re.sub(r"<[^>]+>", "", str(titles[0])).strip()
        year = ""
        for key in ("issued", "published", "published-print", "published-online", "created"):
            parts = ((row.get(key) or {}).get("date-parts") or [[]])[0]
            if parts:
                year = str(parts[0])
                break
        authors = []
        for a in row.get("author") or []:
            name = " ".join(x for x in (a.get("given"), a.get("family")) if x).strip()
            if name:
                authors.append(name)
        out[doi] = {
            "title": title,
            "authors": authors[:30],
            "year": year,
            "journal": str((row.get("container-title") or [""])[0]),
            "cited_by_count": int(row.get("is-referenced-by-count") or 0),
        }
    return out


def _arxiv_batch_meta(ids: list[str], mailto: str) -> dict[str, dict]:
    """从 arXiv Atom API 取预印本元信息。

    为什么要单独一条通道：arXiv 的 DOI（10.48550/arXiv.*）注册在 **DataCite**
    而不是 Crossref，所以 Crossref 查不到它们；不补这一路，纯 arXiv 清单进队后
    元信息表里就只剩一列标识符。
    """
    import urllib.request
    import xml.etree.ElementTree as ET

    if not ids:
        return {}
    url = ("https://export.arxiv.org/api/query?id_list=" + ",".join(ids)
           + "&max_results=" + str(len(ids)))
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"paperforge/1.0 (mailto:{mailto or 'anonymous@example.invalid'})"},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            xml_bytes = resp.read()
    except Exception:  # noqa: BLE001
        return {}

    ns = {"a": "http://www.w3.org/2005/Atom"}
    out: dict[str, dict] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return {}

    for entry in root.findall("a:entry", ns):
        raw_id = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
        arx = C.canonical_arxiv(raw_id.rsplit("/", 1)[-1]) if raw_id else ""
        if not arx:
            continue
        title = " ".join((entry.findtext("a:title", default="", namespaces=ns) or "").split())
        published = (entry.findtext("a:published", default="", namespaces=ns) or "")[:4]
        authors = [
            " ".join((a.findtext("a:name", default="", namespaces=ns) or "").split())
            for a in entry.findall("a:author", ns)
        ]
        journal = ""
        jref = entry.find("{http://arxiv.org/schemas/atom}journal_ref")
        if jref is not None and jref.text:
            journal = jref.text.strip()
        out[arx.lower()] = {
            "title": title,
            "authors": [a for a in authors if a][:30],
            "year": published,
            "journal": journal,
        }
    return out


def enrich_metadata(items: list[C.Item], mailto: str, chunk: int = 20) -> int:
    """给缺元信息的条目补标题/作者/年份/期刊/被引。

    为什么必须有这一步：用户可以直接丢一份纯 DOI 清单进来，那种输入没有任何
    书目信息，不补全的话「文献元信息表」就只剩一列 DOI，交付物名不副实。

    两条通道：Crossref（期刊论文，顺带拿被引数）+ arXiv（预印本，DataCite 注册，
    Crossref 查不到）。
    """
    doi_targets = [it for it in items
                   if it.kind == "doi" and C.is_doi(it.id) and not it.title]
    arx_targets = [it for it in items
                   if C.arxiv_from_doi(it.id) or it.kind == "arxiv"]
    arx_targets = [it for it in arx_targets if not it.title]

    if not doi_targets and not arx_targets:
        return 0

    C.step(f"补全文献元信息（Crossref {len(doi_targets)} 条 / arXiv {len(arx_targets)} 条）")
    filled = 0

    for i in range(0, len(doi_targets), chunk):
        batch = doi_targets[i:i + chunk]
        meta = _crossref_batch_meta([C.normalize_doi(it.id) for it in batch], mailto)
        for it in batch:
            info = meta.get(C.normalize_doi(it.id).lower())
            if not info:
                continue
            if info["title"]:
                it.title = info["title"]
                filled += 1
            it.authors = it.authors or info["authors"]
            it.year = it.year or info["year"]
            it.journal = it.journal or info["journal"]
            it.cited_by_count = it.cited_by_count or info["cited_by_count"]
            if "crossref" not in it.source:
                it.source = f"{it.source}+crossref-meta" if it.source else "crossref-meta"

    for i in range(0, len(arx_targets), chunk):
        batch = arx_targets[i:i + chunk]
        ids = [C.arxiv_from_doi(it.id) or C.canonical_arxiv(it.id) for it in batch]
        meta = _arxiv_batch_meta([x for x in ids if x], mailto)
        for it, arx in zip(batch, ids):
            info = meta.get((arx or "").lower())
            if not info or not info["title"]:
                continue
            it.title = info["title"]
            it.authors = it.authors or info["authors"]
            it.year = it.year or info["year"]
            it.journal = it.journal or info["journal"]
            if "arxiv" not in it.source:
                it.source = f"{it.source}+arxiv-meta" if it.source else "arxiv-meta"
            filled += 1

    total = len(doi_targets) + len(arx_targets)
    C.ok(f"补全成功 {filled}/{total} 条")
    if filled < total:
        C.warn("未补全的条目在元信息表里只有标识符——源站未收录该标识符，或请求被限速。")
    return filled


def build(queue_path: Path, select: str = "", select_file: str = "", deselect: str = "",
          all_items: bool = False, resolve: bool = True, enrich: bool = True) -> int:
    queue = C.load_queue(queue_path)
    items = C.queue_items(queue, only_selected=False)
    if not items:
        C.bad("队列是空的。先跑 normalize.py 或 search.py。")
        return 1

    # ── ★门① 选择 ──────────────────────────────────────────────────────────
    if all_items:
        for it in items:
            it.selected = True
        C.info("已确认：全部条目入选")
    if select:
        picked = _parse_selection(select, len(items))
        for n, it in enumerate(items, 1):
            it.selected = n in picked
        C.info(f"按序号选择：{len(picked)} 条")
    if select_file:
        # 语义：**以这个文件为准**——先清空原有选择，再只保留文件里列出的；
        # 文件里出现、而队列里**没有**的标识符会被**追加**进队列（origin=manual）。
        #
        # 为什么要追加：真实用法经常是"我在好几个查询的结果里人工挑了一批"，
        # 那份清单里的多数条目并不在当前队列里。早期版本只对队列内已有条目置
        # selected，未知 DOI 被静默忽略——用户拿着精选清单却什么也下不到，
        # 而且没有任何提示。契约 §2.1 里的 `manual` 取值也是为此准备的。
        text = Path(select_file).read_text(encoding="utf-8", errors="replace")
        tokens = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        # 注意用 _looks_like_index 而不是「含 - 就当序号」：
        # DOI 里带连字符很常见，宽松判别会把它们当区间吞掉。
        nums = _parse_selection(",".join(t for t in tokens if _looks_like_index(t)), len(items))
        id_tokens = [t for t in tokens if not _looks_like_index(t)]

        for it in items:
            it.selected = False
        for n, it in enumerate(items, 1):
            if n in nums:
                it.selected = True

        matched: set[str] = set()
        for token in id_tokens:
            key = C.dedup_key(token)
            hit = next((it for it in items if C.dedup_key(it.id, it.title) == key), None)
            if hit is not None:
                hit.selected = True
                matched.add(token)
                continue
            kind = C.identifier_kind(token)
            items.append(C.Item(
                id=C.normalize_doi(token) if kind == "doi" else token,
                kind=kind if kind != "unknown" else "unknown",
                title=token if kind == "unknown" else "",
                origin="manual",
                selected=True,
            ))

        added = len(id_tokens) - len(matched)
        C.info(f"按文件选择：{sum(1 for i in items if i.selected)} 条入选"
               + (f"（其中 {added} 条不在原队列里，已作为手工条目追加）" if added else ""))
        if added:
            C.info("  追加的条目会在下一步补全元信息；无法补到的仍可下载（只要有 DOI/arXiv 号）")
    if deselect:
        picked = _parse_selection(deselect, len(items))
        for n, it in enumerate(items, 1):
            if n in picked:
                it.selected = False
        C.info(f"额外排除 {len(picked)} 条")

    selected = [it for it in items if it.selected]
    if not selected:
        C.bad("没有选中任何条目。用 --all 或 --select 指定。")
        return 1

    # ── 补全缺失 DOI ───────────────────────────────────────────────────────
    mailto = C.load_config_state().get("email", "")
    missing = [it for it in selected if it.kind == "unknown" and it.title]
    if missing and resolve:
        C.step(f"补全缺失 DOI（{len(missing)} 条）")
        for it in missing:
            doi = resolve_title_to_doi(it.title, mailto, it.year)
            if doi:
                it.id = doi
                it.kind = "doi"
                it.source = (it.source + "+crossref-title") if it.source else "crossref-title"
                C.ok(f"{it.title[:60]} → {doi}")
            else:
                it.status = C.STATUS_FAIL
                it.reason = "bad_identifier"
                it.detail = "按标题在 Crossref 找不到可信 DOI（相似度不足），需人工补 DOI"
                C.warn(f"补不到：{it.title[:60]}")
    elif missing:
        for it in missing:
            it.status = C.STATUS_FAIL
            it.reason = "bad_identifier"
            it.detail = "缺少 DOI；未启用标题补全"

    # ── 去重 ───────────────────────────────────────────────────────────────
    N.mark_duplicates(items)

    # ── 补全元信息 ─────────────────────────────────────────────────────────
    # 纯 DOI 清单进来时没有任何书目信息，不补全的话元信息表只剩一列 DOI。
    if enrich:
        enrich_metadata([it for it in items
                         if it.selected and it.status != C.STATUS_SKIP], mailto)

    ready = [it for it in items if it.selected and it.status != C.STATUS_SKIP
             and it.reason != "bad_identifier"]
    queue["stage"] = "ready_for_download"
    queue["selection"] = {
        "selected": len(selected),
        "ready": len(ready),
        "at": C.utcnow(),
    }
    C.save_items(queue, items, queue_path)

    C.step("P3 队列就绪")
    C.ok(f"可下载 {len(ready)} 条 / 共 {len(items)} 条")
    blocked = [it for it in items if it.selected and it.status == C.STATUS_FAIL]
    if blocked:
        from collections import Counter
        dist = "，".join(f"{r} {n} 条" for r, n in Counter(i.reason for i in blocked).most_common())
        C.warn(f"另有 {len(blocked)} 条被挡下：{dist}")
        C.info("  最常见的两种：bad_identifier = 按标题补不到可信 DOI；duplicate = 与队列中已有条目重复")
    C.ok(f"已写入 {queue_path}")
    C.info("★门②：确认策略、并发、是否拉补充材料后，跑 download.py")
    return 0


def main() -> int:
    C.console()
    C.require_deployed()
    ap = argparse.ArgumentParser(description="P3 · 队列构建")
    ap.add_argument("--queue", default=str(C.DEFAULT_QUEUE))
    ap.add_argument("--all", action="store_true", help="确认全部候选")
    ap.add_argument("--select", default="", help="按序号：1,3,5-9")
    ap.add_argument("--select-file", default="", help="文件：一行一个 DOI 或序号")
    ap.add_argument("--deselect", default="", help="按序号排除")
    ap.add_argument("--no-resolve", action="store_true", help="不尝试按标题补全 DOI")
    ap.add_argument("--no-enrich", action="store_true", help="不补全文献元信息（标题/作者/年份/期刊）")
    args = ap.parse_args()
    return build(Path(args.queue), args.select, args.select_file, args.deselect,
                 args.all, resolve=not args.no_resolve, enrich=not args.no_enrich)


if __name__ == "__main__":
    raise SystemExit(main())
