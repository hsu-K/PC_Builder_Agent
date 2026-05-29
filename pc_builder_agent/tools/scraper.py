"""
爬蟲工具。

Node 只需要透過統一的工具入口來呼叫。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def _matches_use_case(title: str, use_case: str) -> bool:
    """Check whether an article title matches the requested use case category.

    If no known category is detected, returns True (no filtering).
    """
    use_case_lower = use_case.lower()

    if "遊戲" in use_case or "game" in use_case_lower:
        return "遊戲" in title
    if (
        "工作" in use_case
        or "文書" in use_case
        or "work" in use_case_lower
        or "office" in use_case_lower
    ):
        return "工作" in title or "文書" in title
    if "剪輯" in use_case or "影片" in use_case or "edit" in use_case_lower:
        return "剪輯" in title or "影片" in title
    if "ai" in use_case_lower or "深度" in use_case or "machine" in use_case_lower:
        return "AI" in title or "深度" in title

    # Unknown category → don't filter
    return True


@tool
def pc_board_scraper(budget: str | None = None, use_case: str | None = None) -> dict:
    """爬取 PTT PC_Shopping 版最新熱門 [菜單] 文章，含推噓文分析與社群評價。

    支援依 use_case 篩選用途類別（遊戲、工作、剪輯、AI 等），
    並依討論熱度（|nrec|）排序，取前 10 篇。

    Args:
        budget: 預算範圍 (如 "50k", "100k" 等)，暫未用於 PTT 篩選
        use_case: 使用情境 (如 "遊戲", "工作", "剪輯", "AI" 等)

    Returns:
        dict: {
            "status": "success" | "error",
            "message": str (僅 error 時有),
            "articles_count": int,
            "articles": list[dict],  # each with id, title, url, author, date,
                                     # content, push_count, boo_count, neutral_count, pushes
        }
    """

    import time

    import requests
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    session = requests.Session()

    try:
        # === Step 1: Over18 認證 ===
        session.post(
            "https://www.ptt.cc/ask/over18",
            data={"from": "/bbs/PC_Shopping/index.html", "yes": "yes"},
            headers=headers,
            timeout=10,
        )

        # === Step 2: 爬取列表頁，收集 [菜單] 文章 ===
        all_entries: list[dict] = []
        current_url = "https://www.ptt.cc/bbs/PC_Shopping/index.html"
        max_pages = 5

        for _ in range(max_pages):
            resp = session.get(str(current_url), headers=headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

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

            # 往上一頁繼續爬
            paging_btns = soup.select(".btn-group-paging a")
            prev_url = None
            for btn in paging_btns:
                if "上頁" in btn.get_text(strip=True):
                    href = btn.get("href", "")
                    href_str = str(href) if href else ""
                    prev_url = (
                        f"https://www.ptt.cc{href_str}"
                        if href_str.startswith("/")
                        else href_str
                    )
                    break
            if prev_url:
                current_url = prev_url
                time.sleep(0.3)
            else:
                break

        if not all_entries:
            return {
                "status": "error",
                "message": "未在 PTT PC_Shopping 版找到任何 [菜單] 文章",
                "articles_count": 0,
                "articles": [],
            }

        # === Step 3: 按討論熱度（|nrec|）排序，取前 10 篇 ===
        all_entries.sort(key=lambda e: abs(e["nrec"]), reverse=True)
        top_entries = all_entries[:10]

        # === Step 4: 逐篇爬取完整內容與推文 ===
        articles: list[dict] = []
        for entry in top_entries:
            time.sleep(0.5)  # rate limit
            try:
                art_resp = session.get(entry["url"], headers=headers, timeout=10)
                art_resp.raise_for_status()
            except requests.RequestException:
                continue  # skip individual article failures

            art_soup = BeautifulSoup(art_resp.text, "html.parser")
            main_content = art_soup.select_one("#main-content")
            if not main_content:
                continue

            # 4a) 萃取推文結構
            pushes: list[dict] = []
            push_count = 0
            boo_count = 0
            neutral_count = 0

            for push_el in main_content.select(".push"):
                tag_el = push_el.select_one(".push-tag")
                tag = (
                    tag_el.get_text(strip=True).replace("\u200b", "") if tag_el else ""
                )
                userid_el = push_el.select_one(".push-userid")
                userid = userid_el.get_text(strip=True) if userid_el else ""
                content_el = push_el.select_one(".push-content")
                raw_content = content_el.get_text(strip=True) if content_el else ""
                ip_el = push_el.select_one(".push-ipdatetime")
                ipdatetime = ip_el.get_text(strip=True) if ip_el else ""

                # content 前綴常有 ": "
                if raw_content.startswith(":"):
                    raw_content = raw_content[1:].strip()

                pushes.append(
                    {
                        "tag": tag,
                        "userid": userid,
                        "content": raw_content,
                        "ipdatetime": ipdatetime,
                    }
                )
                if tag == "推":
                    push_count += 1
                elif tag == "噓":
                    boo_count += 1
                else:
                    neutral_count += 1

            # 4b) 清理本文：移除推文區塊、meta 資料、簽名檔
            for push_el in main_content.select(".push"):
                push_el.decompose()
            for el in main_content.select(".article-metaline"):
                el.decompose()
            for el in main_content.select(".article-metaline-right"):
                el.decompose()
            for el in main_content.select(".f2"):
                el.decompose()

            clean_content = main_content.get_text("\n", strip=True)

            # 4b-2) 清理 PTT 版規注意事項：只保留菜單段落（從 已買/未買 到 總價 行）
            import re as _clean_re

            menu_match = _clean_re.search(
                r"(已買/未買.*?總價[^\n]*(?:元)?)",
                clean_content,
                _clean_re.DOTALL,
            )
            if menu_match:
                clean_content = menu_match.group(1)

            # 4c) 解析結構化零件
            import re as _re

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
            components: dict[str, str] = {}
            for key, pattern in COMPONENT_PATTERNS.items():
                match = _re.search(pattern, clean_content)
                if match:
                    components[key] = match.group(1).strip()

            # Extract article ID from URL
            import re as _id_re

            url_match = _id_re.search(r"/(M\.\d+\.A\.[A-Z0-9]+)\.html", entry["url"])

            # 4d) 推論預算區間
            import re as _budget_re

            inferred_budget = None
            inferred_budget_range = "unknown"
            total_price_match = _budget_re.search(
                r"總價[^0-9]*(\d+[,]?\d*)", clean_content
            )
            if total_price_match:
                inferred_budget = int(total_price_match.group(1).replace(",", ""))
                if inferred_budget < 30000:
                    inferred_budget_range = "low"
                elif inferred_budget <= 60000:
                    inferred_budget_range = "medium"
                else:
                    inferred_budget_range = "high"

            from datetime import datetime, timezone

            pulled_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
            pulled_at = pulled_at[:-2] + ":" + pulled_at[-2:]

            article_id = (
                f"ptt_{url_match.group(1)}"
                if url_match
                else f"ptt_{len(articles) + 1:03d}"
            )
            articles.append(
                {
                    "id": article_id,
                    "source": "ptt",
                    "board": "PC_Shopping",
                    "title": entry["title"],
                    "url": entry["url"],
                    "author": entry["author"],
                    "date": f"2026-{entry['date'].replace('/', '-')}",
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
            )

        # === Step 5: 依 use_case 過濾（無匹配則保留全部） ===
        if use_case:
            matched = [a for a in articles if _matches_use_case(a["title"], use_case)]
            if matched:
                articles = matched

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
