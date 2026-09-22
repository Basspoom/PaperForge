"""V2 下载层 · Sci-Hub 直连（spider 路线）。

这是第二代智能体相对第一代的**新增能力**：不走 scansci-pdf，直接命中
Sci-Hub 镜像取全文 PDF，一条链路 2 个请求，通常 3–10 秒/篇。

现场实测（2026-09，必须先理解再改这个文件）：

1. **反爬是间歇性的，不是恒定的。** 镜像会返回 HTTP 200 + 约 7.3KB 的
   "Sci-Hub: are you are robot?" 页面（altcha 工作量证明）。命中率随请求量
   骤降：连续探测时前 7 篇成功率 100%，之后降到 ~23%。所以：
   * 单次请求式实现（原始 spider.py）批量必然低命中；
   * **换镜像 + 退避重试是必需的，不是优化项**。
2. **镜像列表决定成败。** 实测可用：.box / .su / .ru / .red。
   `sci-hub.se` 已失效（TLS EOF，白等 8s 超时）；
   `.st / .vg / .ee / .bz / .mksa.top / .is / .41610.org` 多已失效或 DNS 不解析。
   第一代配置里的镜像列表已经整体过期，这是"工程化下载慢"的一个真实原因。
3. **altcha 工作量证明可以解**（难度 maxNumber=200000，用 hashlib 秒解），
   但把解提交到 `/captcha/solution/<id>` 会被服务端拒（`{"success":false}`），
   猜测还有浏览器指纹/时效绑定。**所以本模块不假装能过关**：
   遇到验证页就换镜像重试，并把 `challenge` 如实记为失败原因。

输出契约：`<PDF_DIR>/<doi_sanitized>.pdf`，落盘前校验 `%PDF` 文件头。
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - 运行环境缺依赖时给出可操作的提示
    requests = None
    BeautifulSoup = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

DEFAULT_MIRRORS = ["https://sci-hub.box", "https://sci-hub.su",
                   "https://sci-hub.ru", "https://sci-hub.red"]

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

CHALLENGE_MARKERS = ("are you are robot", "altcha", "captcha", "turnstile")
PDF_PAT = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+\.pdf[^"']*)["']""", re.I)
ANY_PDF_PAT = re.compile(r"""["'](//[^"']+?\.pdf[^"']*)["']""", re.I)


@dataclass
class SciHubResult:
    ok: bool
    file: str = ""
    bytes: int = 0
    elapsed: float = 0.0
    requests_made: int = 0
    reason: str = ""
    detail: str = ""
    mirror: str = ""
    pdf_url: str = ""


def sanitize_filename(doi: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", doi.strip())


def new_session() -> "requests.Session":
    s = requests.Session()
    s.trust_env = False                     # 忽略系统代理：镜像直连更稳
    s.proxies = {"http": None, "https": None}
    s.headers.update(HEADERS)
    return s


def is_challenge(html: str) -> bool:
    low = html[:4000].lower()
    return any(m in low for m in CHALLENGE_MARKERS) and ".pdf" not in low


def _absolutize(url: str, base_url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base_url.rstrip("/") + url
    if url.startswith("http"):
        return url
    return base_url.rstrip("/") + "/" + url


def extract_pdf_url(html: str, base_url: str) -> str | None:
    """按标签语义提取 PDF 链接，最后才退到正则。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag_name in ("iframe", "embed", "object"):
        for tag in soup.find_all(tag_name):
            src = tag.get("src") or tag.get("data")
            if src and ".pdf" in str(src).lower():
                return _absolutize(str(src), base_url)
    for a in soup.find_all("a", href=True):
        if ".pdf" in a["href"].lower():
            return _absolutize(a["href"], base_url)
    m = PDF_PAT.search(html)
    if m:
        return _absolutize(m.group(1), base_url)
    m = ANY_PDF_PAT.search(html)
    if m:
        return _absolutize(m.group(1), base_url)
    return None


def verify_pdf(path: str | Path) -> tuple[bool, int, str]:
    """校验真的是 PDF：非空 + `%PDF` 文件头。"""
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError as e:
        return False, 0, f"stat失败:{e}"
    if size == 0:
        return False, 0, "空文件"
    try:
        with p.open("rb") as fh:
            head = fh.read(5)
    except OSError as e:
        return False, size, f"读取失败:{e}"
    if head[:4] != b"%PDF":
        return False, size, f"非PDF文件头:{head[:8]!r}"
    return True, size, ""


def _download_pdf(session, pdf_url: str, page_url: str, out_path: Path) -> tuple[bool, str]:
    try:
        with session.get(pdf_url, timeout=60, stream=True, allow_redirects=True,
                         headers={"Referer": page_url}) as resp:
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}"
            with out_path.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=32768):
                    fh.write(chunk)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def fetch(doi: str, out_dir: str | Path, *, mirrors: list[str] | None = None,
          max_page_tries: int = 10, pdf_retry: int = 2,
          delay: tuple[float, float] = (0.6, 2.0), timeout: int = 30,
          session=None) -> SciHubResult:
    """取一篇的全文 PDF。已存在且校验通过时直接返回成功（幂等）。"""
    if requests is None:
        return SciHubResult(False, reason="dependency_missing",
                            detail="缺少 requests / beautifulsoup4")

    mirrors = mirrors or DEFAULT_MIRRORS
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (sanitize_filename(doi) + ".pdf")

    if target.exists():
        good, size, _ = verify_pdf(target)
        if good:
            return SciHubResult(True, file=str(target), bytes=size, detail="已存在，跳过")

    session = session or new_session()
    t0 = time.time()
    made = 0
    last_reason, last_detail = "no_pdf_link", ""

    for i in range(max_page_tries):
        mirror = mirrors[i % len(mirrors)]
        page_url = f"{mirror}/{doi}"
        made += 1
        try:
            resp = session.get(page_url, timeout=timeout, allow_redirects=True)
        except Exception as e:  # noqa: BLE001
            last_reason, last_detail = "network", f"{type(e).__name__}: {str(e)[:100]}"
            time.sleep(random.uniform(*delay))
            continue

        if resp.status_code != 200:
            last_reason, last_detail = "http_error", f"HTTP {resp.status_code}"
            time.sleep(random.uniform(*delay))
            continue

        html = resp.text
        if is_challenge(html):
            # 换镜像重试。altcha 解出来也提交不过去（见模块 docstring），
            # 所以这里如实记为 challenge，不要假装能自动过关。
            last_reason, last_detail = "challenge", "altcha 反爬页"
            time.sleep(random.uniform(*delay))
            continue

        pdf_url = extract_pdf_url(html, mirror)
        if not pdf_url:
            last_reason, last_detail = "no_pdf_link", f"页面 {len(html)}B 内无 .pdf 链接"
            time.sleep(random.uniform(*delay))
            continue

        for attempt in range(1, pdf_retry + 1):
            ok, err = _download_pdf(session, pdf_url, page_url, target)
            made += 1
            if ok:
                good, size, vnote = verify_pdf(target)
                if good:
                    return SciHubResult(True, file=str(target), bytes=size,
                                        elapsed=time.time() - t0, requests_made=made,
                                        mirror=mirror, pdf_url=pdf_url)
                last_reason, last_detail = "bad_file", vnote
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                break
            last_reason, last_detail = "pdf_download_failed", err
            time.sleep(1.0 * attempt)

    return SciHubResult(False, elapsed=time.time() - t0, requests_made=made,
                        reason=last_reason, detail=last_detail)


def solve_altcha(session, challenge: dict) -> tuple[int | None, int]:
    """解 altcha 工作量证明（SHA-256(salt+number) == challenge）。

    返回 (number, 耗时毫秒)。保留这个函数是为了将来服务端放宽提交校验时能直接用；
    当前服务端会拒绝提交（`{"success":false}`），所以 fetch() 没有调用它。
    """
    salt, challenge_hash = challenge["salt"], challenge["challenge"]
    max_number = int(challenge.get("maxNumber", 200000))
    t0 = time.time()
    for n in range(max_number + 1):
        if hashlib.sha256(f"{salt}{n}".encode()).hexdigest() == challenge_hash:
            return n, int((time.time() - t0) * 1000)
    return None, int((time.time() - t0) * 1000)


# ── 熔断器 ───────────────────────────────────────────────────────────────────
# 反爬是"打过一定量就整段封"的行为，不是随机丢包。实测：连续探测时前 7 篇几乎全中，
# 之后一次性掉到 0/6、连 6 篇全 challenge。这种状态下**再逐篇试直连就是纯浪费**——
# 每篇要白烧 20–25 秒（10 次请求 × 退避）才回退到工程化引擎。
#
# 所以加一个进程内熔断：连续 N 篇全因 challenge 失败就停止直连，直接走工程化。
# 熔断只在本进程内有效，下次运行重新探测——因为封禁是会随时间恢复的。
_FUSE_THRESHOLD = 3


class CircuitBreaker:
    """连续 challenge 达到阈值后，本次运行不再尝试直连。"""

    def __init__(self, threshold: int = _FUSE_THRESHOLD) -> None:
        self.threshold = threshold
        self.consecutive_challenges = 0
        self.tripped = False
        self.skipped = 0

    def observe(self, reason: str) -> None:
        if reason == "challenge":
            self.consecutive_challenges += 1
            if self.consecutive_challenges >= self.threshold:
                self.tripped = True
        else:
            # 任何非 challenge 的结果都说明链路是通的（哪怕是"未收录"），
            # 这时候不能熔断，否则一次 miss 就会被误判成封禁。
            self.consecutive_challenges = 0

    def allow(self) -> bool:
        if self.tripped:
            self.skipped += 1
            return False
        return True

    def note(self) -> str:
        if not self.tripped:
            return ""
        return (f"直连已熔断（连续 {self.consecutive_challenges} 篇被 altcha 拦截）；"
                f"本次运行剩余 {self.skipped} 篇直接走工程化引擎，避免白等")
