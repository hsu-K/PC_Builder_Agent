"""
PC_Board Scraper Node

功能：
- 爬取模式：根據 state 中的 preferences，爬取 PC_Board 文章並存本地
- 查詢模式：讀取本地文章，根據用戶問題進行解讀和回答

由 router 判斷是否進入查詢模式。
"""

import json
from typing import Any

from pc_builder_agent.nodes.base import run_agent_turn, message_text
from pc_builder_agent.tools import pc_board_scraper
from pc_builder_agent.tools.scraper import (
    normalize_articles_payload,
    save_articles_to_disk,
    load_articles_from_disk,
)


def pc_board_scraper_node(
    state: dict,
    *,
    model_name: str | None = None,
    mode: str = "fetch",
    debug: bool = False,
) -> dict[str, Any]:
    """PC_Board Scraper Node - 支持爬取和查詢兩種模式

    Args:
        state: 包含 preferences 的作業狀態
        model_name: 使用的 LLM 模組
        mode: 執行模式
            - "fetch": 爬取新文章並存本地（初始化時）
            - "query": 查詢本地文章並根據用戶問題進行解讀

    Returns:
        dict: 包含 pc_board_results 或回應文本的字典
    """
    
    profile_id = state.get("profile_id", "default")
    
    if mode == "fetch":
        return _fetch_and_save_articles(state, profile_id, model_name, debug=debug)
    elif mode == "query":
        return _query_local_articles(state, profile_id, model_name, debug=debug)
    else:
        return {"pc_board_results": []}


def _fetch_and_save_articles(
    state: dict,
    profile_id: str,
    model_name: str | None,
    *,
    debug: bool = False,
) -> dict[str, Any]:
    """爬取模式：根據偏好爬取文章並存本地"""
    
    ai_message, text = run_agent_turn(
        state=state,
        role_name="PC Board Scraper Agent",
        system_prompt=(
            '''"
            You are the PC_Board Scraper Agent.
            Your task is to determine, based on the user's budget and requirements, whether it is necessary to scrape relevant posts from the PTT PC_Shopping board.
            If you determine that scraping is needed, use the pc_board_scraper tool to retrieve the relevant articles.
            The tool will return a simulated list of PC build articles, including various configuration proposals and community discussions.
            Finally, return the retrieved article information.
            Please respond using this JSON format:
            {
                \"Articles\": {
                    \"article1\": \"the first article content\",
                    \"article2\": \"the second article content\"
                }
            }
            "'''
        ),
        tools=[pc_board_scraper],
        model_name=model_name,
        debug=debug,
    )

    raw_message_text = message_text(ai_message).strip()
    if debug:
        print("PC_Board Scraper Agent AI Message:", raw_message_text)

    pc_board_articles: list[dict] = []

    # 先嘗試直接解析模型回傳的 JSON，支援你貼的 Articles/article1/article2 格式
    if raw_message_text:
        try:
            parsed_payload = json.loads(raw_message_text)
            pc_board_articles = normalize_articles_payload(parsed_payload)
        except json.JSONDecodeError:
            pc_board_articles = []

    # 如果模型回傳不是可解析 JSON，再回退到 tool 結果
    preferences = state.get("preferences", {})
    budget = preferences.get("budget")
    use_case = preferences.get("use_case")
    
    if not pc_board_articles and budget and use_case:
        # 直接呼叫 tool 取得文章
        result = pc_board_scraper.invoke({"budget": budget, "use_case": use_case})
        pc_board_articles = normalize_articles_payload(result)

    # 保存到本地
    if pc_board_articles:
        save_articles_to_disk(pc_board_articles, profile_id)
    
    if debug:
        print(f"\n✓ PC_Board Scraper 成功爬取 {len(pc_board_articles)} 篇文章")
        for idx, article in enumerate(pc_board_articles[:5], 1):
            print(f"   {idx}. [{article.get('id', 'N/A')}] {article.get('title', 'N/A')}")
    
    return {"pc_board_results": pc_board_articles}


def _query_local_articles(
    state: dict,
    profile_id: str,
    model_name: str | None,
    *,
    debug: bool = False,
) -> dict[str, Any]:
    """查詢模式：讀取本地文章並根據用戶問題進行解讀"""
    
    # 從本地讀取文章
    local_articles = load_articles_from_disk(profile_id)
    
    if not local_articles:
        return {
            "messages": [],
            "pc_board_results": [],
            "pc_board_query_attempted": True,
            "pc_board_response": "尚未爬取 PC_Board 文章。請先執行初始化爬取。",
        }
    
    # 準備文章摘要供 agent 參考
    articles_summary = _prepare_articles_summary(local_articles)
    
    # 創建增強的 state，包含本地文章信息
    enhanced_state = dict(state)
    enhanced_state["pc_board_results"] = local_articles
    enhanced_state["pc_board_articles_summary"] = articles_summary
    
    # 使用 agent 根據本地文章回答用戶問題
    ai_message, response_text = run_agent_turn(
        state=enhanced_state,
        role_name="PC Board Query Agent",
        system_prompt=(
            '''"
            You are the PC_Board Query Agent.
            You have access to locally scraped posts from the PTT PC_Shopping board.
            Based on the user's question and the article contents, provide relevant recommendations or information.
            If the articles contain relevant content, cite specific configuration proposals or community discussions.
            Finally, return a clear and concise answer(In Chinese zh-TW).
            "'''
        ),
        tools=[],  # 查詢模式不需要工具
        model_name=model_name,
        debug=debug,
    )
    
    if debug:
        print(f"\n✓ 已從本地載入 {len(local_articles)} 篇文章進行查詢")
    
    return {
        "messages": [ai_message],
        "pc_board_results": local_articles,
        "pc_board_query_attempted": True,
        "pc_board_response": response_text,
    }


def _prepare_articles_summary(articles: list[dict]) -> str:
    """準備文章摘要供 agent 參考"""
    summary_lines = []
    
    for idx, article in enumerate(articles, 1):
        title = article.get("title", "N/A")
        content = article.get("content", "")
        excerpt = content[:150].replace("\n", " ") if content else ""
        
        summary_lines.append(
            f"{idx}. 【{title}】\n"
            f"   作者：{article.get('author', 'N/A')}\n"
            f"   日期：{article.get('date', 'N/A')}\n"
            f"   摘要：{excerpt}"
        )
    
    return "\n\n".join(summary_lines)
