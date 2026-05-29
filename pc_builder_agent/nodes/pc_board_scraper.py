"""
PC_Board Scraper Node

功能：
- 爬取模式：根據 state 中的 preferences，爬取 PC_Board 文章並存本地
- 查詢模式：讀取本地文章，根據用戶問題進行解讀和回答

由 router 判斷是否進入查詢模式。
"""

from typing import Any

from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.tools import pc_board_scraper
from pc_builder_agent.tools.scraper import (
    load_articles_from_disk,
    normalize_articles_payload,
    save_articles_to_disk,
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
    """爬取模式：直接從 PTT 爬取最新熱門菜單文章並存本地（跳過 LLM 浪費 token）"""

    preferences = state.get("preferences", {})
    budget = preferences.get("budget")
    use_case = preferences.get("use_case")

    if debug:
        print(
            f"\n🔍 開始爬取 PTT PC_Shopping 文章 (budget={budget}, use_case={use_case})"
        )

    # 直接呼叫工具爬取 PTT，不需要 LLM 決定「要不要爬」
    tool_result = pc_board_scraper.invoke({"budget": budget, "use_case": use_case})
    pc_board_articles = normalize_articles_payload(tool_result)

    if tool_result.get("status") == "error":
        print(f"⚠ PTT 爬取失敗: {tool_result.get('message', '未知錯誤')}")
        return {"pc_board_results": []}

    # 保存到本地
    if pc_board_articles:
        save_articles_to_disk(pc_board_articles, profile_id)
        if debug:
            print(f"\n✓ 成功爬取 {len(pc_board_articles)} 篇文章並存入磁碟")
            for idx, article in enumerate(pc_board_articles[:5], 1):
                print(
                    f"   {idx}. [{article.get('id', 'N/A')}] {article.get('title', 'N/A')}"
                )
                print(
                    f"      推 {article.get('push_count', 0)} / 噓 {article.get('boo_count', 0)} / → {article.get('neutral_count', 0)}"
                )
    elif debug:
        print("\n⚠ 沒有爬取到任何文章")

    return {"pc_board_results": pc_board_articles}


def _query_local_articles(
    state: dict,
    profile_id: str,
    model_name: str | None,
    *,
    debug: bool = False,
) -> dict[str, Any]:
    """查詢模式：讀取本地文章並根據用戶問題進行解讀"""

    # 先從 state 讀取，若無則從磁碟載入
    local_articles = state.get("pc_board_results") or load_articles_from_disk(
        profile_id
    )

    if not local_articles:
        return {
            "messages": [],
            "pc_board_response": "尚未爬取 PC_Board 文章。請先執行初始化爬取。",
        }

    # 執行結構化分析
    analysis_report = _analyze_articles(local_articles)

    if debug:
        print("\n📊 文章分析報告:")
        print(analysis_report)

    # 創建增強的 state，包含本地文章信息
    enhanced_state = dict(state)
    enhanced_state["pc_board_results"] = local_articles
    enhanced_state["pc_board_articles_summary"] = _prepare_articles_summary(
        local_articles
    )

    # 增強 system prompt，加入結構化分析結果
    enhanced_system_prompt = (
        '"'
        "You are the PC_Board Query Agent. "
        "You have access to locally scraped posts from the PTT PC_Shopping board.\n\n"
        "Below is a structured analysis of the available articles:\n"
        f"{analysis_report}\n\n"
        "Based on the user's question and the article contents, provide relevant recommendations or information.\n\n"
        "Please follow these guidelines:\n"
        "- Cite specific articles and their configurations when making recommendations\n"
        "- Compare different build proposals when multiple options exist\n"
        "- Point out relevant community comments and discussions\n"
        "- Give clear recommendations based on the user's question\n"
        "- Answer in Traditional Chinese (zh-TW)\n\n"
        "Finally, return a clear and concise answer."
        '"'
    )

    # 使用 agent 根據本地文章回答用戶問題
    ai_message, response_text = run_agent_turn(
        state=enhanced_state,
        role_name="PC Board Query Agent",
        system_prompt=enhanced_system_prompt,
        tools=[],  # 查詢模式不需要工具
        model_name=model_name,
        debug=debug,
    )

    if debug:
        print(f"\n✓ 已從本地載入 {len(local_articles)} 篇文章進行查詢")

    return {
        "messages": [ai_message],
        "pc_board_response": response_text,
    }


def _analyze_articles(articles: list[dict]) -> str:
    """分析文章內容，按預算範圍分組、擷取所有零件資訊，產出結構化報表（含社群評價分析）"""

    budget_categories: dict[str, list[dict]] = {"low": [], "medium": [], "high": []}

    # 零件中文標籤對照表（對應 scraper.py 中的 key）
    COMPONENT_LABELS: dict[str, str] = {
        "cpu": "CPU",
        "mb": "主機板",
        "ram": "記憶體",
        "vga": "顯示卡",
        "cooler": "散熱器",
        "ssd": "SSD",
        "hdd": "HDD",
        "psu": "電源",
        "chassis": "機殼",
        "monitor": "螢幕",
        "mouse_kb": "鼠鍵",
        "os": "作業系統",
    }
    all_components: dict[str, list[str]] = {key: [] for key in COMPONENT_LABELS}

    for article in articles:
        # 使用預先推論的預算區間（若無則用舊邏輯 regex 解析價格）
        inferred_range = article.get("inferred_budget_range")
        if inferred_range and inferred_range in ("low", "medium", "high"):
            budget_categories[inferred_range].append(article)
        else:
            # 舊資料相容：從內文解析價格
            import re

            content = article.get("content", "")
            title = article.get("title", "")
            combined = title + " " + content
            total_match = re.search(r"總價[^0-9]*(\d+[,]?\d*)", combined)
            if total_match:
                val = int(total_match.group(1).replace(",", ""))
                if val < 30000:
                    budget_categories["low"].append(article)
                elif val <= 60000:
                    budget_categories["medium"].append(article)
                else:
                    budget_categories["high"].append(article)
            else:
                k_match = re.search(r"(\d+)\s*[kK]", combined)
                if k_match:
                    val = int(k_match.group(1)) * 1000
                    if val < 30000:
                        budget_categories["low"].append(article)
                    elif val <= 60000:
                        budget_categories["medium"].append(article)
                    else:
                        budget_categories["high"].append(article)
                else:
                    budget_categories["medium"].append(article)

        # 從結構化欄位讀取零件
        article_components: dict[str, str] = dict(article.get("components", {}) or {})
        article["_components"] = article_components

        for key in COMPONENT_LABELS:
            if key in article_components:
                all_components[key].append(article_components[key])

    # 建構報表
    budget_labels = {
        "low": "低預算 (< 30K)",
        "medium": "中預算 (30K ~ 60K)",
        "high": "高預算 (> 60K)",
    }
    lines = ["## 📋 文章分析報告\n"]
    lines.append("### 預算分布")
    for cat in ("low", "medium", "high"):
        items = budget_categories[cat]
        if items:
            lines.append(f"- **{budget_labels[cat]}**: {len(items)} 篇")
            for a in items:
                lines.append(f"  - {a.get('title', 'N/A')}")
    lines.append("")

    lines.append("### 各文章完整配置")
    lines.append("")
    for article in articles:
        title = article.get("title", "N/A")
        lines.append(f"**{title}**")
        comps = article.get("_components", {})
        if comps:
            for key, label in COMPONENT_LABELS.items():
                if key in comps:
                    lines.append(f"  - {label}：{comps[key]}")
        else:
            lines.append("  - 未偵測到零件資訊")
        lines.append("")

    lines.append("---")
    lines.append("### 零件配置統計")
    lines.append("")
    for key, label in COMPONENT_LABELS.items():
        items = all_components[key]
        if items:
            lines.append(f"**{label}** ({len(items)} 組)")
            seen = set()
            for item in items:
                if item not in seen:
                    seen.add(item)
                    lines.append(f"  - {item}")
        else:
            lines.append(f"**{label}** — 未偵測到")
        lines.append("")

    lines.append("### 配置多樣性")
    lines.append(f"- 文章總數：{len(articles)} 篇")
    non_empty = sum(1 for v in all_components.values() if v)
    lines.append(f"- 涵蓋零件類型：{non_empty} / {len(COMPONENT_LABELS)} 種")
    budget_hit = sum(1 for v in budget_categories.values() if v)
    lines.append(f"- 涵蓋預算區間：{budget_hit} 個")

    # ================================================================
    # 社群評價分析（推噓文情感分析）
    # ================================================================
    lines.append("")
    lines.append("### 社群評價分析")

    total_push = sum(a.get("push_count", 0) for a in articles)
    total_boo = sum(a.get("boo_count", 0) for a in articles)
    total_neutral = sum(a.get("neutral_count", 0) for a in articles)
    total_comments = total_push + total_boo + total_neutral

    lines.append(
        f"- 總推文數：{total_push} 推 / {total_boo} 噓 / {total_neutral} 中立 → 共 {total_comments} 則"
    )

    if total_push + total_boo > 0:
        overall_ratio = total_push / (total_push + total_boo) * 100
        lines.append(f"- 整體好評率：{overall_ratio:.0f}%（推 / (推+噓)）")

    lines.append("")
    lines.append("#### 各文章社群反響")
    for article in articles:
        title = article.get("title", "N/A")
        pc = article.get("push_count", 0)
        bc = article.get("boo_count", 0)
        nc = article.get("neutral_count", 0)
        sentiment = ""
        if pc + bc > 0:
            r = pc / (pc + bc) * 100
            if r >= 80:
                sentiment = "🟢 社群推薦"
            elif r >= 50:
                sentiment = "🟡 尚可"
            else:
                sentiment = "🔴 爭議较大"
        lines.append(f"  - {title}")
        lines.append(f"    推 {pc} / 噓 {bc} / 中立 {nc} {sentiment}")

        # 列出代表性推文（最多 3 則）
        pushes = article.get("pushes", [])
        key_pushes = [p for p in pushes if p.get("tag") in ("推", "噓")][:3]
        for p in key_pushes:
            lines.append(f"    · {p['tag']} {p['userid']}: {p['content']}")

    lines.append("")
    lines.append("#### 常見建議與關鍵字")
    # 從推文中提取常見字詞做簡單的頻率分析
    all_push_texts = []
    for article in articles:
        for p in article.get("pushes", []):
            all_push_texts.append(p.get("content", ""))

    # 簡單的關鍵字統計
    keyword_counts = {}
    suggestion_keywords = [
        "散熱",
        "電源",
        "SSD",
        "RAM",
        "記憶體",
        "機殼",
        "主機板",
        "顯卡",
        "CPU",
        "升級",
        "降預算",
    ]
    for text in all_push_texts:
        for kw in suggestion_keywords:
            if kw in text:
                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

    if keyword_counts:
        sorted_kw = sorted(keyword_counts.items(), key=lambda x: -x[1])
        top_kw = sorted_kw[:5]
        for kw, count in top_kw:
            lines.append(f"  - 「{kw}」被提及 {count} 次")
    else:
        lines.append("  - 暫無足夠推文進行關鍵字分析")

    return "\n".join(lines)


def _prepare_articles_summary(articles: list[dict]) -> str:
    """準備文章摘要供 agent 參考（含連結與社群評價）"""
    summary_lines = []

    for idx, article in enumerate(articles, 1):
        title = article.get("title", "N/A")
        content = article.get("content", "")
        excerpt = content[:150].replace("\n", " ") if content else ""
        push_c = article.get("push_count", 0)
        boo_c = article.get("boo_count", 0)
        neutral_c = article.get("neutral_count", 0)

        # 計算好評率
        total_sentiment = push_c + boo_c
        sentiment_str = ""
        if total_sentiment > 0:
            ratio = push_c / total_sentiment * 100
            sentiment_str = f"（好評率 {ratio:.0f}%）"

        summary_lines.append(
            f"{idx}. 【{title}】\n"
            f"   作者：{article.get('author', 'N/A')}\n"
            f"   日期：{article.get('date', 'N/A')}\n"
            f"   連結：{article.get('url', 'N/A')}\n"
            f"   評價：推 {push_c} / 噓 {boo_c} / 中立 {neutral_c} {sentiment_str}\n"
            f"   摘要：{excerpt}"
        )

    return "\n\n".join(summary_lines)
