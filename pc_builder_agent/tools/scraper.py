"""
爬蟲工具。

Node 只需要透過統一的工具入口來呼叫。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool


@tool
def web_scrape(url: str, selector: str | None = None) -> str:
    """抓取指定網址內容，若提供 selector 則只回傳對應區塊文字。"""

    import requests
    from bs4 import BeautifulSoup

    response = requests.get(
        url,
        timeout=15,
        headers={"User-Agent": "pc-builder-agent/0.1"},
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    if selector:
        element = soup.select_one(selector)
        if element is None:
            return f"找不到 selector：{selector}"
        return element.get_text(" ", strip=True)

    return soup.get_text(" ", strip=True)[:6000]


def _parse_nrec(nrec_el) -> int:
    """Parse PTT list-page nrec (push count) element into an integer.

    - "爆" → 100 (爆文)
    - "X1"~"X9" → -1~-9
    - "XX" → -100 (大負評)
    - numeric string → that number
    - missing/empty → 0
    """
    if nrec_el is None:
        return 0
    text = nrec_el.get_text(strip=True)
    if not text:
        return 0
    if text == "爆":
        return 100
    if text.startswith("X"):
        if text == "XX":
            return -100
        try:
            return -int(text[1:])
        except ValueError, IndexError:
            return 0
    try:
        return int(text)
    except ValueError:
        return 0


# 用途分類關鍵字對照表：use_case 觸發詞 → 標題應包含的關鍵字
USE_CASE_KEYWORDS: dict[str, list[str]] = {
    "遊戲": ["遊戲", "game", "gaming"],
    "工作": ["工作", "文書", "辦公", "work", "office"],
    "文書": ["工作", "文書", "辦公", "work", "office"],
    "剪輯": ["剪輯", "影片", "編輯", "edit", "editing", "video"],
    "影片": ["剪輯", "影片", "編輯", "edit", "editing", "video"],
    "ai": ["AI", "深度", "機器", "ML", "訓練", "inference", "deep", "learning", "llm"],
    "深度": [
        "AI",
        "深度",
        "機器",
        "ML",
        "訓練",
        "inference",
        "deep",
        "learning",
        "llm",
    ],
    "機器": [
        "AI",
        "深度",
        "機器",
        "ML",
        "訓練",
        "inference",
        "deep",
        "learning",
        "llm",
    ],
}

# PTT 搜尋詢問詞對照表：當比對到的文章太少時，用這些詞去 PTT 搜尋
USE_CASE_SEARCH_QUERIES: dict[str, str] = {
    "遊戲": "遊戲",
    "工作": "文書",
    "文書": "文書",
    "剪輯": "剪輯",
    "影片": "剪輯",
    "ai": "AI",
    "深度": "AI",
    "機器": "AI",
}


def _parse_budget_k(budget: str | None) -> int | None:
    """將預算字串轉換為 K 單位整數（例如 '50000' → 50, '50k' → 50）"""
    if not budget:
        return None
    budget_str = str(budget).strip().lower()
    if budget_str.endswith("k"):
        try:
            return int(float(budget_str[:-1]))
        except ValueError, TypeError:
            return None
    try:
        return int(float(budget_str)) // 1000
    except ValueError, TypeError:
        return None


def _get_budget_range_queries(budget_k: int, use_case: str | None) -> list[str]:
    """根據預算 K 數與用途，產生預算區間搜尋詢問清單

    例如 budget_k=50, use_case="遊戲" → ["40k遊戲", "45k遊戲", "50k遊戲", "55k遊戲", "60k遊戲"]
    會用 PTT 搜尋這些關鍵字，找到預算相近的菜單。
    """
    search_kw = _get_search_query(use_case) if use_case else None
    if not search_kw:
        return []

    # 預算區間步階：-15K, -10K, -5K, 0, +5K, +10K, +15K
    # 步長 5K，確保覆蓋足夠範圍但不會跳太遠
    steps = list(range(-15, 20, 5))  # [-15, -10, -5, 0, 5, 10, 15]

    queries: list[str] = []
    for step in steps:
        k = budget_k + step
        if k >= 10:  # 不低於 10K
            queries.append(f"{k}k{search_kw}")

    # 去重（如果 steps 有重疊）
    seen = set()
    unique_queries: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)

    return unique_queries


def _matches_use_case(title: str, use_case: str) -> bool:
    """Check whether an article title matches the requested use case category.

    Uses keyword dict to match user's use_case input against title keywords.
    """
    use_case_lower = use_case.lower()

    # Try exact match first
    for trigger, keywords in USE_CASE_KEYWORDS.items():
        if trigger in use_case or trigger in use_case_lower:
            for kw in keywords:
                if kw in title:
                    return True
            return False

    # Fallback: check if any keyword matches at all
    for trigger, keywords in USE_CASE_KEYWORDS.items():
        for kw in keywords:
            if kw in use_case or kw in use_case_lower:
                if kw in title:
                    return True

    # Unknown category → match everything
    return True


def _get_search_query(use_case: str) -> str | None:
    """Get PTT search query for a given use case. Returns None if unknown."""
    use_case_lower = use_case.lower()
    for trigger, query in USE_CASE_SEARCH_QUERIES.items():
        if trigger in use_case or trigger in use_case_lower:
            return query
    return None


# ---------------------------------------------------------------------------
# 輔助函式 — PTT 爬蟲
# ---------------------------------------------------------------------------


def _create_ptt_session() -> requests.Session:
    """建立 PTT session 並完成 over18 認證"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    session = requests.Session()
    session.post(
        "https://www.ptt.cc/ask/over18",
        data={"from": "/bbs/PC_Shopping/index.html", "yes": "yes"},
        headers=headers,
        timeout=10,
    )
    return session


def _fetch_list_entries(
    session: requests.Session,
    max_pages: int = 5,
    search_query: str | None = None,
) -> list[dict]:
    """爬取 PTT 列表頁或搜尋結果頁，收集 [菜單] 文章，最多爬 max_pages 頁

    Args:
        session: PTT session
        max_pages: 最多爬幾頁
        search_query: 若提供，則使用 PTT 搜尋功能而非最新列表
    """
    all_entries: list[dict] = []

    if search_query:
        current_url = f"https://www.ptt.cc/bbs/PC_Shopping/search?q={search_query}"
    else:
        current_url = "https://www.ptt.cc/bbs/PC_Shopping/index.html"

    for _ in range(max_pages):
        try:
            resp = session.get(str(current_url), timeout=10)
            resp.raise_for_status()
        except requests.RequestException:
            break
        soup = BeautifulSoup(resp.text, "html.parser")

        # Check if PTT returned "查無此關鍵字" (no results)
        if "查無此關鍵字" in resp.text or "沒有相關文章" in resp.text:
            break

        for r_ent in soup.select(".r-ent"):
            title_el = r_ent.select_one(".title a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title.startswith("[菜單]"):
                continue

            href = title_el.get("href", "")
            href_str = str(href) if href else ""
            full_url = (
                f"https://www.ptt.cc{href_str}"
                if href_str.startswith("/")
                else href_str
            )
            author_el = r_ent.select_one(".author")
            author = author_el.get_text(strip=True) if author_el else ""
            date_el = r_ent.select_one(".date")
            date = date_el.get_text(strip=True) if date_el else ""

            all_entries.append(
                {
                    "title": title,
                    "url": full_url,
                    "author": author,
                    "date": date,
                    "nrec": _parse_nrec(r_ent.select_one(".nrec")),
                }
            )

        if len(all_entries) >= 15:
            break

        # 往上一頁
        paging_btns = soup.select(".btn-group-paging a")
        prev_url = None
        for btn in paging_btns:
            if "上頁" in btn.get_text(strip=True):
                h = btn.get("href", "")
                hs = str(h) if h else ""
                prev_url = f"https://www.ptt.cc{hs}" if hs.startswith("/") else hs
                break
        if prev_url:
            current_url = prev_url
            time.sleep(0.3)
        else:
            break

    return all_entries


def _fetch_list_entries_for_queries(
    session: requests.Session,
    queries: list[str],
    existing_urls: set[str],
    max_per_query: int = 5,
) -> list[dict]:
    """嘗試多組 PTT 搜尋詢問，收集不重複的文章列表"""
    all_entries: list[dict] = []
    seen_urls = set(existing_urls)

    for query in queries:
        if len(all_entries) >= 15:  # 收集夠多了就停
            break
        entries = _fetch_list_entries(session, max_pages=2, search_query=query)
        for e in entries:
            if e["url"] not in seen_urls:
                seen_urls.add(e["url"])
                all_entries.append(e)
        time.sleep(0.3)  # 避免搜尋太頻繁

    return all_entries


def _parse_article_date(url: str, list_date: str) -> str:
    """從 PTT URL 的 Unix timestamp 推斷年份，組合成正確的 YYYY-MM-DD

    PTT article URL: /bbs/PC_Shopping/M.1779872283.A.FDD.html
    The number after "M." is a Unix timestamp. Extract it, convert to date.
    list_date is the article list page date ("5/27", "11/07", etc.)
    """
    import datetime
    # Extract timestamp from URL
    match = re.search(r"/M\.(\d+)\.A\.", url)
    if match:
        ts = int(match.group(1))
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%Y-%m-%d")
    # Fallback: use current year with list_date
    current_year = datetime.datetime.now().year
    return f"{current_year}-{list_date.replace('/', '-')}"


def _fetch_article(session: requests.Session, entry: dict) -> dict | None:
    """爬取單一文章的內容與推文，回傳結構化 article dict；失敗回傳 None"""
    time.sleep(0.5)
    try:
        art_resp = session.get(entry["url"], timeout=10)
        art_resp.raise_for_status()
    except requests.RequestException:
        return None

    art_soup = BeautifulSoup(art_resp.text, "html.parser")
    main_content = art_soup.select_one("#main-content")
    if not main_content:
        return None

    # 4a) 萃取推文結構
    pushes, push_count, boo_count, neutral_count = _parse_pushes(main_content)

    # 4b) 清理本文
    clean_content = _clean_article_content(main_content)

    # 4b-2) 精簡為菜單段落：已買/未買 → 總價
    menu_match = re.search(
        r"(已買/未買.*?總價[^\n]*(?:元)?)",
        clean_content,
        re.DOTALL,
    )
    if menu_match:
        clean_content = menu_match.group(1)

    # 4c) 解析結構化零件
    components = _parse_components(clean_content)

    # 4d) 推論預算區間 + 其他 metadata
    inferred_budget, inferred_budget_range = _infer_budget(clean_content)

    url_match = re.search(r"/(M\.\d+\.A\.[A-Z0-9]+)\.html", entry["url"])
    article_id = f"ptt_{url_match.group(1)}" if url_match else None

    pulled_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
    pulled_at = pulled_at[:-2] + ":" + pulled_at[-2:]

    return {
        "id": article_id or "ptt_temp",
        "source": "ptt",
        "board": "PC_Shopping",
        "title": entry["title"],
        "url": entry["url"],
        "author": entry["author"],
        "date": _parse_article_date(entry["url"], entry["date"]),
        "pulled_at": pulled_at,
        "content": clean_content,
        "components": components,
        "inferred_budget": inferred_budget,
        "inferred_budget_range": inferred_budget_range,
        "push_count": push_count,
        "boo_count": boo_count,
        "neutral_count": neutral_count,
        "pushes": pushes,
    }


def _parse_pushes(main_content: BeautifulSoup) -> tuple[list[dict], int, int, int]:
    """從文章 parse 推噓文結構，同作者連續發言合併為一條

    回傳 (pushes, push_count, boo_count, neutral_count)
    """
    raw_pushes: list[dict] = []

    for push_el in main_content.select(".push"):
        tag_el = push_el.select_one(".push-tag")
        tag = tag_el.get_text(strip=True).replace("\u200b", "") if tag_el else ""
        userid_el = push_el.select_one(".push-userid")
        userid = userid_el.get_text(strip=True) if userid_el else ""
        content_el = push_el.select_one(".push-content")
        raw_content = content_el.get_text(strip=True) if content_el else ""
        ip_el = push_el.select_one(".push-ipdatetime")
        ipdatetime = ip_el.get_text(strip=True) if ip_el else ""

        if raw_content.startswith(":"):
            raw_content = raw_content[1:].strip()

        raw_pushes.append({
            "tag": tag,
            "userid": userid,
            "content": raw_content,
            "ipdatetime": ipdatetime,
        })

    # 統計原始計數（不分合併）
    push_count = sum(1 for p in raw_pushes if p["tag"] == "推")
    boo_count = sum(1 for p in raw_pushes if p["tag"] == "噓")
    neutral_count = sum(1 for p in raw_pushes if p["tag"] == "→")

    # 合併同作者連續發言
    merged: list[dict] = []
    for p in raw_pushes:
        if merged and merged[-1]["userid"] == p["userid"]:
            merged[-1]["content"] += "\n" + p["content"]
            merged[-1]["ipdatetime"] = p["ipdatetime"]
            # 保留最高的 tag priority：噓 > 推 > →
            existing_tag = merged[-1]["tag"]
            if p["tag"] == "噓":
                merged[-1]["tag"] = "噓"
            elif p["tag"] == "推" and existing_tag == "→":
                merged[-1]["tag"] = "推"
        else:
            merged.append(dict(p))

    return merged, push_count, boo_count, neutral_count


def _clean_article_content(main_content: BeautifulSoup) -> str:
    """清除推文、meta、簽名檔，回傳純文字"""
    for el in main_content.select(".push"):
        el.decompose()
    for el in main_content.select(".article-metaline"):
        el.decompose()
    for el in main_content.select(".article-metaline-right"):
        el.decompose()
    for el in main_content.select(".f2"):
        el.decompose()
    return main_content.get_text("\n", strip=True)


COMPONENT_PATTERNS: dict[str, str] = {
    "cpu": r"CPU\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "mb": r"(?:MB|主機板)\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "ram": r"(?:RAM|記憶體)\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "vga": r"(?:VGA|顯示卡|GPU)\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "cooler": r"(?:Cooler|散熱器)\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "ssd": r"SSD\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "hdd": r"HDD\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "psu": r"(?:PSU|電源供應器)\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "chassis": r"(?:CHASSIS|機殼)\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "monitor": r"MONITOR\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "mouse_kb": r"(?:Mouse/KB|鼠鍵)\s*\([^)]*\)[：:][ \t]*([^\n]+)",
    "os": r"OS\s*\([^)]*\)[：:][ \t]*([^\n]+)",
}


def _parse_components(content: str) -> dict[str, str]:
    """從菜單內文解析零件"""
    components: dict[str, str] = {}
    for key, pattern in COMPONENT_PATTERNS.items():
        match = re.search(pattern, content)
        if match:
            components[key] = match.group(1).strip()
    return components


def _infer_budget(content: str) -> tuple[int | None, str]:
    """從總價行推論預算與區間"""
    total_match = re.search(r"總價[^0-9]*(\d+[,]?\d*)", content)
    if not total_match:
        return None, "unknown"
    val = int(total_match.group(1).replace(",", ""))
    if val < 30000:
        return val, "low"
    if val <= 60000:
        return val, "medium"
    return val, "high"


def _filter_within_months(entries: list[dict], months: int = 3) -> list[dict]:
    """過濾出在指定月份內的文章"""
    import datetime
    cutoff = datetime.datetime.now() - datetime.timedelta(days=months * 30)

    filtered: list[dict] = []
    for e in entries:
        date_str = _parse_article_date(e["url"], e["date"])
        try:
            article_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            if article_date >= cutoff:
                filtered.append(e)
        except ValueError:
            filtered.append(e)  # keep if can't parse
    return filtered


@tool
def pc_board_scraper(budget: str | None = None, use_case: str | None = None) -> dict:
    """爬取 PTT PC_Shopping 版 [菜單] 文章，含推噓文分析與社群評價。

    從預算+用途搜尋、純用途搜尋兩個來源收集文章，
    保留近三個月內的文章，去重後依討論熱度（|nrec|）排序，
    取前 10 篇，確保結果同時符合用途、預算區間與時效性。

    Args:
        budget: 預算範圍 (如 "50k", "100k" 等)，用於搜尋預算相近的菜單
        use_case: 使用情境 (如 "遊戲", "工作", "剪輯", "AI" 等)

    Returns:
        dict: {
            "status": "success" | "error",
            "message": str (僅 error 時有),
            "articles_count": int,
            "articles": list[dict],  # each with id, title, url, author, date,
                                     # content, push_count, boo_count, neutral_count, pushes
                                     # components, inferred_budget, inferred_budget_range
        }
    """

    try:
        session = _create_ptt_session()
        raw_entries: list[dict] = []
        seen_urls: set[str] = set()

        # 來源 2：預算+用途搜尋
        budget_k = _parse_budget_k(budget)
        if budget_k and use_case:
            budget_queries = _get_budget_range_queries(budget_k, use_case)
            if budget_queries:
                for e in _fetch_list_entries_for_queries(
                    session, budget_queries, seen_urls
                ):
                    seen_urls.add(e["url"])
                    raw_entries.append(e)

        # 來源 3：純用途搜尋補齊
        if use_case:
            search_q = _get_search_query(use_case)
            if search_q:
                for e in _fetch_list_entries(
                    session, max_pages=3, search_query=search_q
                ):
                    if e["url"] not in seen_urls:
                        seen_urls.add(e["url"])
                        raw_entries.append(e)

        # 若無預算也無用途，仍需要基礎搜尋（搜尋「菜單」關鍵字）
        if not budget_k and not use_case:
            for e in _fetch_list_entries(session, search_query="菜單"):
                if e["url"] not in seen_urls:
                    seen_urls.add(e["url"])
                    raw_entries.append(e)

        if not raw_entries:
            return {
                "status": "error",
                "message": "未在 PTT PC_Shopping 版找到任何 [菜單] 文章",
                "articles_count": 0,
                "articles": [],
            }

        # === 近三個月過濾 ===
        raw_entries = _filter_within_months(raw_entries, months=3)

        if not raw_entries:
            return {
                "status": "success",
                "articles_count": 0,
                "articles": [],
            }

        # === 按用途過濾 ===
        if use_case:
            raw_entries = [
                e for e in raw_entries if _matches_use_case(e["title"], use_case)
            ]

        if not raw_entries:
            return {
                "status": "success",
                "articles_count": 0,
                "articles": [],
            }

        # === 按推文熱度排序，取 top 10 ===
        raw_entries.sort(key=lambda e: abs(e["nrec"]), reverse=True)
        top_entries = raw_entries[:10]

        # === 爬取這 10 篇的完整內容 ===
        articles: list[dict] = []
        for entry in top_entries:
            article = _fetch_article(session, entry)
            if article:
                articles.append(article)

        return {
            "status": "success",
            "articles_count": len(articles),
            "articles": articles,
        }

    except requests.RequestException as e:
        return {
            "status": "error",
            "message": f"PTT 連線失敗：{e}",
            "articles_count": 0,
            "articles": [],
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"爬取過程發生錯誤：{e}",
            "articles_count": 0,
            "articles": [],
        }


# ============================================================================
# 本地文章存儲功能
# ============================================================================


def get_articles_storage_path() -> Path:
    """取得本地文章存儲目錄"""
    storage_dir = Path(__file__).parent.parent / "data" / "articles"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def normalize_articles_payload(payload: Any) -> list[dict]:
    """將不同格式的文章回應轉成標準文章列表。"""

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    if "articles" in payload:
        return normalize_articles_payload(payload["articles"])

    if "Articles" in payload:
        return normalize_articles_payload(payload["Articles"])

    article_items: list[dict] = []
    for key in sorted(payload.keys()):
        value = payload[key]
        if isinstance(value, dict) and value.get("id") and value.get("title"):
            article_items.append(value)

    return article_items


def save_articles_to_disk(
    articles: list[dict] | dict, profile_id: str = "default"
) -> Path:
    """
    將爬取的文章保存到本地

    Args:
        articles: 爬取的文章列表
        profile_id: 使用者 ID，用於分組存儲

    Returns:
        Path: 保存文件的路徑
    """
    articles_to_save = normalize_articles_payload(articles)
    storage_dir = get_articles_storage_path()
    articles_file = storage_dir / f"articles_{profile_id}.json"

    with open(articles_file, "w", encoding="utf-8") as f:
        json.dump(articles_to_save, f, ensure_ascii=False, indent=2)

    return articles_file


def load_articles_from_disk(profile_id: str = "default") -> list[dict]:
    """
    從本地讀取之前爬取的文章

    Args:
        profile_id: 使用者 ID

    Returns:
        list: 文章列表，若無則返回空列表
    """
    storage_dir = get_articles_storage_path()
    articles_file = storage_dir / f"articles_{profile_id}.json"

    if articles_file.exists():
        try:
            with open(articles_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError, IOError:
            return []

    return []
