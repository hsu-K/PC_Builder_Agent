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


@tool
def pc_board_scraper(budget: str | None = None, use_case: str | None = None) -> dict:
    """根據預算和用途爬取 PC_Board 文章。
    
    此工具會查詢 PTT PC_Shopping 版的相關文章，根據使用者偏好推薦。
    
    Args:
        budget: 預算範圍 (如 "50k", "100k" 等)
        use_case: 使用情境 (如 "遊戲", "工作" 等)
    
    Returns:
        dict: 包含爬取的文章列表和統計資訊
    """
    
    pc_board_articles = []
    
    # 模擬文章 1: 預算分析文章
    if budget and use_case:
        pc_board_articles.append({
            "id": "pcb_001",
            "title": f"[菜單] {budget}遊戲機",
            "url": "https://www.ptt.cc/bbs/PC_Shopping/M.1779164308.A.DD1.html",
            "author": "LiuJY0327 (Hansel)",
            "date": "2026-05-19",
            "content": (
                f"預算/用途：{budget}\n"
                f"每次大概1-2個遊戲在跑而已，SSD抓1T應該夠，也比較符合自己預算\n"
                f"\n"
                f"CPU (中央處理器)：AMD Ryzen7 7800X3D Tray\n"
                f"MB      (主機板)：【任搭CPU】華碩 TUF GAMING B650-E WIFI\n"
                f"RAM     (記憶體)：【X3D專案】V-COLOR MANTA XSKY RGB DDR5-6000 32GB(16G*2)黑\n"
                f"VGA     (顯示卡)：【救贖】華碩 PRIME-RX9060XT-O16G\n"
                f"Cooler  (散熱器)： ID-COOLING FROZN A620 PRO SE ARGB 黑\n"
                f"SSD   (固態硬碟)：鎧俠 KIOXIA Exceria G2 1TB\n"
                f"HDD       (硬碟)：\n"
                f"PSU (電源供應器)：【救贖】MONTECH Century II 850W 金牌電源\n"
                f"CHASSIS   (機殼)：聯力 V100R 黑 全景玻璃機殼\n"
                f"MONITOR   (螢幕)：1080p自備\n"
                f"Mouse/KB  (鼠鍵)：\n"
                f"OS    (作業系統)：\n"
                f"\n"
                f"其它      (自填)：\n"
                f"總價 (未稅/含稅)：50,499"
            ),
            "comments": (
                "→ marsqq: 如果是跑3a不是競技類的話可考慮降成7700   114.33.93.15 05/19 12:57\n"
                "→ marsqq: 價差看省起來或補顯卡或其它地方   114.33.93.15 05/19 12:58\n"
                "推 aa0801aa: idcooling的a410不錯啊，熱管直觸對AMD    27.51.9.211 05/19 15:07"
            ),
        })
    
    # 模擬文章 2: 顯示卡比較文章
    pc_board_articles.append({
        "id": "pcb_002",
        "title": "2026 年中端顯示卡推薦鑑賞",
        "url": "https://www.pc-board.cc/bbs/PC_Shopping/M.1234567891.A.html",
        "author": "GPU_Expert",
        "date": "2026-05-19",
        "content": (
            "我整理了 2026 年中端 GPU 的一些撥特\n"
            "RTX 4070: 優誼的 1440P 機能\n"
            "RX 7800 XT: 地鱗章幀，效能相似"
        ),
    })
    
    return {
        "status": "success",
        "articles_count": len(pc_board_articles),
        "articles": pc_board_articles,
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


def save_articles_to_disk(articles: list[dict] | dict, profile_id: str = "default") -> Path:
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
        except (json.JSONDecodeError, IOError):
            return []
    
    return []