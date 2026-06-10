"""
零件網路搜尋工具。

僅保留可信評測網站資料，供 specialist 進一步分析。
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool


TRUSTED_REVIEW_DOMAINS = {
    "tomshardware.com",
    "techpowerup.com",
    "anandtech.com",
    "guru3d.com",
    "pcgamer.com",
    "rtings.com",
    "gamersnexus.net",
    "kitguru.net",
    "tweaktown.com",
}


def _normalize_ddg_url(url: str) -> str:
    """將 DuckDuckGo redirect URL 還原為原始目標 URL。"""
    normalized = url.strip()
    if normalized.startswith("//"):
        normalized = "https:" + normalized

    parsed = urlparse(normalized)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg", [])
        if uddg:
            normalized = unquote(uddg[0])

    return normalized


def _is_trusted_domain(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not host:
        return False
    if host.startswith("www."):
        host = host[4:]
    return any(host == domain or host.endswith("." + domain) for domain in TRUSTED_REVIEW_DOMAINS)


def _fetch_page_excerpt(url: str, *, limit: int = 600) -> str:
    """抓取網址內容的精簡摘要，供 specialist 參考。"""
    try:
        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "pc-builder-agent/0.1"},
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    if not text:
        return ""
    return text[:limit]


@tool
def search_component_web(query: str, max_results: int = 5) -> str:
    """搜尋指定零件資訊，僅回傳可信評測網站資料與摘要。"""
    safe_max = max(1, min(max_results, 8))
    endpoint = "https://duckduckgo.com/html/"

    try:
        response = requests.get(
            endpoint,
            params={"q": query},
            timeout=15,
            headers={"User-Agent": "pc-builder-agent/0.1"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return f"搜尋失敗：{exc}"

    soup = BeautifulSoup(response.text, "html.parser")
    trusted_results: list[str] = []
    scanned_count = 0

    # 先掃較多結果，再挑出可信網域，避免前幾筆剛好不可信導致空集合
    for result in soup.select(".result")[:40]:
        scanned_count += 1
        title_node = result.select_one(".result__title a")
        snippet_node = result.select_one(".result__snippet")

        if title_node is None:
            continue

        title = title_node.get_text(" ", strip=True)
        raw_url = title_node.get("href", "").strip()
        url = _normalize_ddg_url(raw_url)
        snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""

        if not title or not url.startswith(("http://", "https://")):
            continue

        if not _is_trusted_domain(url):
            continue

        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        page_excerpt = _fetch_page_excerpt(url)

        line = f"- 標題：{title}\n  來源：{domain}\n  連結：{url}"
        if snippet:
            line += f"\n  摘要：{snippet}"
        if page_excerpt:
            line += f"\n  內文摘錄：{page_excerpt}"
        trusted_results.append(line)

        if len(trusted_results) >= safe_max:
            break

    if not trusted_results:
        return (
            "找不到符合可信評測網站的結果。"
            "請改用更精確關鍵字（例如完整型號 + review / benchmark）。"
        )

    return (
        "以下為可信評測網站資料（已優先過濾網域），請基於這些來源分析並在回答中附上連結：\n"
        f"(已掃描 {scanned_count} 筆候選結果，採用 {len(trusted_results)} 筆)\n"
        + "\n".join(trusted_results)
    )
