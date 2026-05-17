"""
爬蟲工具。

Node 只需要透過統一的工具入口來呼叫。
"""

from __future__ import annotations

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