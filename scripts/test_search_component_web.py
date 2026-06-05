"""
測試 search_component_web 工具的輸出品質。

執行方式（專案根目錄）：
    python scripts/test_search_component_web.py

可指定單一關鍵字：
    python scripts/test_search_component_web.py --query "Kingston Fury Beast DDR5 6000"

可指定回傳筆數：
    python scripts/test_search_component_web.py --max-results 8
"""

from __future__ import annotations

import argparse
import re
from urllib.parse import parse_qs, unquote, urlparse

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from pc_builder_agent.tools.component_search import search_component_web
from pc_builder_agent.tools.scraper import web_scrape

load_dotenv()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test hardware.search_component_web")
    parser.add_argument(
        "--query",
        default="",
        help="單一搜尋關鍵字；若不填則使用內建測試清單。",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="每組查詢最多抓取的結果筆數（工具內會再限制 1~8）。",
    )
    parser.add_argument(
        "--read-top-k",
        type=int,
        default=2,
        help="每組查詢要進一步讀取內文並分析的網址數量。",
    )
    parser.add_argument(
        "--model",
        default="gpt-4.1-mini",
        help="用於分析內文的模型名稱。",
    )
    return parser.parse_args()


def _extract_urls(search_output: str) -> list[str]:
    raw_urls = re.findall(r"連結：\s*(\S+)", search_output)
    normalized_urls: list[str] = []

    for raw in raw_urls:
        url = raw.strip()
        if not url:
            continue

        # DuckDuckGo 常回傳 protocol-relative URL: //duckduckgo.com/l/?uddg=...
        if url.startswith("//"):
            url = "https:" + url

        # 解析 DuckDuckGo redirect，優先取 uddg 參數作為實際目標網址
        try:
            parsed = urlparse(url)
            if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
                qs = parse_qs(parsed.query)
                uddg = qs.get("uddg", [])
                if uddg:
                    url = unquote(uddg[0])
        except Exception:
            continue

        if url.startswith(("http://", "https://")):
            normalized_urls.append(url)

    return list(dict.fromkeys(normalized_urls))


def _analyze_with_model(
    *,
    model_name: str,
    query: str,
    scraped_pages: list[tuple[str, str]],
) -> str:
    model = ChatOpenAI(model=model_name, temperature=0.2)

    page_blocks = []
    for idx, (url, content) in enumerate(scraped_pages, start=1):
        page_blocks.append(
            f"[來源 {idx}]\nURL: {url}\n內容摘要:\n{content[:3000]}"
        )

    prompt = (
        f"使用者問題：{query}\n\n"
        "以下是你讀過的網頁內容，請做繁體中文分析：\n"
        "- 先給重點結論\n"
        "- 再列出規格/優缺點/適用情境\n"
        "- 最後給購買建議與風險提醒\n\n"
        + "\n\n".join(page_blocks)
    )

    messages = [
        SystemMessage(
            content=(
                "你是電腦零件評測分析師。"
                "請依據提供的網頁內容分析，不要憑空捏造。"
            )
        ),
        HumanMessage(content=prompt),
    ]
    return model.invoke(messages).content


def run_demo(query: str, max_results: int, read_top_k: int, model_name: str) -> None:
    queries = [query] if query else [
        "Kingston Fury Beast DDR5 6000 review",
        "Samsung 990 PRO 2TB TBW warranty",
        "Thermalright Peerless Assassin 120 review noise",
    ]

    print("=" * 72)
    print("search_component_web 測試開始")
    print("=" * 72)

    for i, q in enumerate(queries, start=1):
        print(f"\n--- 測試 {i}: {q}")
        search_output = search_component_web.invoke(
            {
                "query": q,
                "max_results": max_results,
            }
        )
        print(search_output)

        urls = _extract_urls(search_output)
        if not urls:
            print("⚠️ 無法從搜尋結果擷取有效網址，跳過內文分析。")
            print("-" * 72)
            continue

        selected_urls = urls[: max(1, read_top_k)]
        scraped_pages: list[tuple[str, str]] = []

        for url in selected_urls:
            print(f"\n[讀取內文] {url}")
            try:
                content = web_scrape.invoke({"url": url})
            except Exception as exc:
                print(f"讀取失敗：{exc}")
                continue

            if isinstance(content, str) and content.strip():
                scraped_pages.append((url, content))
                print(f"已取得內容（長度約 {len(content)} 字）")
            else:
                print("讀取到空內容。")

        if not scraped_pages:
            print("⚠️ 沒有可分析內容，略過模型分析。")
            print("-" * 72)
            continue

        print(f"\n[模型分析中] model={model_name}")
        try:
            analysis = _analyze_with_model(
                model_name=model_name,
                query=q,
                scraped_pages=scraped_pages,
            )
            print("\n=== 分析結果 ===")
            print(analysis)
        except Exception as exc:
            print(f"模型分析失敗：{exc}")

        print("-" * 72)


if __name__ == "__main__":
    args = parse_args()
    run_demo(
        query=args.query,
        max_results=args.max_results,
        read_top_k=args.read_top_k,
        model_name=args.model,
    )
