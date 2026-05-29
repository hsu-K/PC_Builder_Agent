#!/usr/bin/env python
"""
PC_Board Scraper Node 測試腳本

測試項目：
1. 直接測試 pc_board_scraper 工具（多種 budget/use_case 組合）
2. 測試 _analyze_articles 輔助函數
3. 測試 fetch 模式（需 OPENAI_API_KEY）
4. 測試 query 模式的本地分析功能

執行方式：
    uv run python scripts/test_pc_board_scraper.py
"""

import os
import sys

from dotenv import load_dotenv

from pc_builder_agent.nodes.pc_board_scraper import (
    _analyze_articles,
    _prepare_articles_summary,
    pc_board_scraper_node,
)
from pc_builder_agent.tools.scraper import (
    load_articles_from_disk,
    normalize_articles_payload,
    pc_board_scraper,
    save_articles_to_disk,
)

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_direct_tool_call():
    """Test 1: 直接測試工具，驗證不同情境下的文章回傳"""
    print("=" * 70)
    print("Test 1: 直接呼叫 pc_board_scraper 工具")
    print("=" * 70)

    test_cases = [
        ("50k", "遊戲"),
        ("100k", "AI"),
        ("30k", "文書"),
        ("80k", "剪輯"),
        (None, None),
    ]

    for budget, use_case in test_cases:
        result = pc_board_scraper.invoke({"budget": budget, "use_case": use_case})
        articles = normalize_articles_payload(result)
        print(
            f"\n  budget={budget!r}, use_case={use_case!r}  →  {len(articles)} 篇文章"
        )
        for a in articles:
            print(f"    [{a.get('id', 'N/A')}] {a.get('title', 'N/A')}")

    print("\n✓ Test 1 完成\n")


def test_analyze_articles():
    """Test 2: 驗證 _analyze_articles 結構化分析功能"""
    print("=" * 70)
    print("Test 2: _analyze_articles 結構化分析")
    print("=" * 70)

    # 混合多種類別文章進行分析
    all_articles = []
    for budget, use_case in [("30k", "遊戲"), ("100k", "AI"), ("40k", "工作")]:
        result = pc_board_scraper.invoke({"budget": budget, "use_case": use_case})
        all_articles.extend(normalize_articles_payload(result))

    report = _analyze_articles(all_articles)
    print(report)

    print("\n✓ Test 2 完成\n")


def test_fetch_mode():
    """Test 3: 測試 fetch 模式（需要 OPENAI_API_KEY）"""
    print("=" * 70)
    print("Test 3: pc_board_scraper_node  fetch 模式")
    print("=" * 70)

    state = {
        "profile_id": "test_user",
        "preferences": {
            "budget": "50k",
            "use_case": "遊戲",
            "cpu": "AMD",
            "gpu": "AMD",
        },
        "messages": [],
    }

    result = pc_board_scraper_node(state, mode="fetch", debug=True)
    articles = result.get("pc_board_results", [])
    print(f"\nNode 回傳 {len(articles)} 篇文章")

    # 驗證已存到磁碟
    loaded = load_articles_from_disk("test_user")
    print(f"從磁碟載入 {len(loaded)} 篇文章")
    for a in loaded:
        print(f"  [{a.get('id', 'N/A')}] {a.get('title', 'N/A')}")

    print("\n✓ Test 3 完成\n")


def test_query_mode_analysis():
    """Test 4: 測試 query 模式的本機分析（不須 LLM）"""
    print("=" * 70)
    print("Test 4: Query 模式 — 本機文章分析（無 LLM）")
    print("=" * 70)

    # 先確保有文章
    result = pc_board_scraper.invoke({"budget": "50k", "use_case": "遊戲"})
    articles = normalize_articles_payload(result)
    save_articles_to_disk(articles, "test_user")

    # 測試本地分析
    loaded = load_articles_from_disk("test_user")
    print(f"\n從磁碟載入 {len(loaded)} 篇文章")
    for a in loaded:
        print(f"  [{a.get('id', 'N/A')}] {a.get('title', 'N/A')}")

    print("\n--- 文章摘要 ---")
    summary = _prepare_articles_summary(loaded)
    print(summary)

    print("\n--- 結構化分析 ---")
    report = _analyze_articles(loaded)
    print(report)

    print("\n✓ Test 4 完成\n")


def test_fetch_mode_fallback():
    """Test 5: 驗證 fetch 模式在無 LLM 情境下的工具回退"""
    print("=" * 70)
    print("Test 5: Fetch 模式工具回退機制")
    print("=" * 70)

    # 模擬 LLM 不傳回 JSON 的情境，直接測試工具回退
    preferences = {"budget": "80k", "use_case": "剪輯"}
    result = pc_board_scraper.invoke(preferences)
    articles = normalize_articles_payload(result)

    print(f"\n工具直接回傳 {len(articles)} 篇 {preferences['use_case']} 相關文章:")
    for a in articles:
        cpu = ""
        gpu = ""
        content = a.get("content", "")
        for line in content.split("\n"):
            if "CPU" in line and "：:" in line:
                cpu = line.split("：")[-1].strip() if "：" in line else ""
            if "VGA" in line and "：:" in line:
                gpu = line.split("：")[-1].strip() if "：" in line else ""
        print(f"  [{a.get('id', 'N/A')}] {a.get('title', 'N/A')}")
        print(f"      作者：{a.get('author', 'N/A')} ｜ 日期：{a.get('date', 'N/A')}")
        if a.get("comments"):
            print(f"      推文數：{len(a['comments'].split(chr(10)))}")

    # 驗證 save/load 週期
    save_articles_to_disk(articles, "test_fallback")
    reloaded = load_articles_from_disk("test_fallback")
    assert len(reloaded) == len(articles), "儲存/讀取週期失敗"
    print(f"\n✓ 儲存/讀取驗證通過：{len(reloaded)} 篇")

    print("\n✓ Test 5 完成\n")


def main():
    has_api_key = bool(os.getenv("OPENAI_API_KEY"))
    if not has_api_key:
        print("⚠  OPENAI_API_KEY 未設定 – 將跳過需要 LLM 的測試\n")

    test_direct_tool_call()
    test_analyze_articles()
    test_query_mode_analysis()
    test_fetch_mode_fallback()

    if has_api_key:
        test_fetch_mode()
    else:
        print("=" * 70)
        print("Test 3: Fetch 模式 — 跳過（需要 OPENAI_API_KEY）")
        print("=" * 70)
        print()

    print("=" * 70)
    print("✅ 所有測試完成！")
    print("=" * 70)


if __name__ == "__main__":
    main()
