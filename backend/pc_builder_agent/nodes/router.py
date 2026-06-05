"""
Router Node - 根據 planner 產生的計畫決定下一步要啟動哪些 subAgent。

職責：
- 先判斷是否需要讀取 PC_Board 文章
- 若需要且尚未載入文章，先路由到 pc_board_scraper
- 文章已載入後，再路由到對應的 specialist
- 提供備援關鍵字路由，避免 plan 格式不完整時失效
"""

import json
from typing import Any


# 常數定義
AVAILABLE_SPECIALISTS = [
    "cpu_specialist",
    "gpu_specialist",
    "memory_specialist",
    "storage_specialist",
    "cooling_specialist",
    "pc_board_scraper",
]
DEFAULT_ROUTE_TARGETS = ["cpu_specialist", "gpu_specialist"]

CPU_KEYWORDS = (
    "cpu", "處理器", "記憶體", "ram", "文書", "辦公",
    "學習", "程式", "開發", "省電", "靜音", "主機板",
)

GPU_KEYWORDS = (
    "gpu", "顯卡", "顯示卡", "遊戲", "1440p", "4k",
    "光追", "fps", "ai", "剪輯", "繪圖", "渲染",
)

MEMORY_KEYWORDS = (
    "記憶體", "ram", "ddr", "xmp", "expo", "時序", "頻率",
)

STORAGE_KEYWORDS = (
    "ssd", "hdd", "硬碟", "儲存", "nvme", "pcie", "tbw", "容量",
)

COOLING_KEYWORDS = (
    "散熱", "風扇", "水冷", "塔散", "溫度", "噪音", "風道",
)

PC_BOARD_KEYWORDS = (
    "文章", "菜單", "推薦", "ptt", "分享", "討論", "社群",
    "之前", "爬取", "查看", "看看", "告訴我", "有什麼", "介紹",
)

ARTICLE_TASK_KEYWORDS = (
    "compare_articles",
    "analyze_article_configuration",
    "article_query",
    "第一篇",
    "第二篇",
    "文章內容",
    "比較文章",
    "分析文章",
    "文章差異",
    "配置內容",
    "摘要",
)


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """判斷文字是否包含任一關鍵字"""
    return any(keyword in text for keyword in keywords)


def _parse_plan(plan_text: str) -> dict[str, Any]:
    """將 planner 輸出的 JSON 計畫轉成 dict。"""

    if not plan_text:
        return {}

    raw = plan_text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json\n", "", 1).strip()

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def _normalize_targets(targets: Any) -> list[str]:
    """過濾非法節點並去重，保持順序。"""

    if isinstance(targets, str):
        targets = [targets]
    if not isinstance(targets, list):
        return []

    filtered_targets: list[str] = []
    for target in targets:
        if target in AVAILABLE_SPECIALISTS and target not in filtered_targets:
            filtered_targets.append(target)
    return filtered_targets


def _extract_plan_targets(state: dict) -> tuple[list[str], bool, str, str]:
    """從 planner 計畫中抽出後續路由資訊。"""

    plan_data = _parse_plan(state.get("plan", ""))
    need_pc_board_query = bool(plan_data.get("need_pc_board_query"))
    specialist_targets = _normalize_targets(plan_data.get("specialist_targets"))

    reason = plan_data.get("reason", "")
    if not isinstance(reason, str):
        reason = ""

    summary = plan_data.get("summary", "")
    if not isinstance(summary, str):
        summary = ""

    return specialist_targets, need_pc_board_query, reason.strip(), summary.strip()


def _is_article_related_request(state: dict) -> bool:
    """判斷目前需求是否屬於文章相關任務。"""

    combined_text = "\n".join(
        part for part in [state.get("request", ""), state.get("plan", "")] if part
    ).lower()

    if any(keyword.lower() in combined_text for keyword in ARTICLE_TASK_KEYWORDS):
        return True

    plan_data = _parse_plan(state.get("plan", ""))
    task_type = plan_data.get("task_type", "")
    if task_type in {"compare_articles", "analyze_article_configuration"}:
        return True

    article_query = plan_data.get("article_query", "")
    if isinstance(article_query, str) and article_query.strip():
        return True

    return False


def _keyword_fallback_route_targets(state: dict) -> tuple[list[str], str]:
    """計畫格式不完整時的備援規則，基於關鍵字匹配。"""

    combined_text = "\n".join(
        part for part in [state.get("request", ""), state.get("plan", "")] if part
    ).lower()
    pc_board_loaded = bool(state.get("pc_board_results"))

    # 優先檢查是否在查詢文章
    pc_board_match = _contains_keyword(combined_text, PC_BOARD_KEYWORDS)
    if pc_board_match and not pc_board_loaded:
        return ["pc_board_scraper"], "使用者想先查看或比較 PC_Board 文章，因此先讀取文章"

    if pc_board_match and pc_board_loaded:
        cpu_match = _contains_keyword(combined_text, CPU_KEYWORDS)
        gpu_match = _contains_keyword(combined_text, GPU_KEYWORDS)

        if cpu_match and gpu_match:
            return ["cpu_specialist", "gpu_specialist"], "文章已載入，接續由 CPU 與 GPU 專家分析差異"

        if gpu_match:
            return ["gpu_specialist"], "文章已載入，接續由 GPU 專家分析差異"

        if cpu_match:
            return ["cpu_specialist"], "文章已載入，接續由 CPU 專家分析差異"

        return list(DEFAULT_ROUTE_TARGETS), "文章已載入，接續啟動雙專家進行分析"

    cpu_match = _contains_keyword(combined_text, CPU_KEYWORDS)
    gpu_match = _contains_keyword(combined_text, GPU_KEYWORDS)
    memory_match = _contains_keyword(combined_text, MEMORY_KEYWORDS)
    storage_match = _contains_keyword(combined_text, STORAGE_KEYWORDS)
    cooling_match = _contains_keyword(combined_text, COOLING_KEYWORDS)

    component_targets: list[str] = []
    if memory_match:
        component_targets.append("memory_specialist")
    if storage_match:
        component_targets.append("storage_specialist")
    if cooling_match:
        component_targets.append("cooling_specialist")

    if component_targets:
        return component_targets, "需求聚焦於特定零件，改由對應專家進行深入分析"

    if cpu_match and gpu_match:
        return ["cpu_specialist", "gpu_specialist"], "需求同時涵蓋平台與顯示需求，兩個專家都啟動"

    if gpu_match:
        return ["gpu_specialist"], "需求明確偏向顯卡、遊戲或圖形工作"

    if cpu_match:
        return ["cpu_specialist"], "需求明確偏向處理器、記憶體或整體平台"

    return list(DEFAULT_ROUTE_TARGETS), "語意不明確，使用關鍵字備援後採用預設雙專家"


def _route_targets_for_request(state: dict) -> tuple[list[str], str]:
    """根據 planner 計畫決定路由目標。"""

    # 先從 planner 的計畫中取得路由資訊，這是最正式且優先的來源
    specialist_targets, need_pc_board_query, reason, summary = _extract_plan_targets(state)

    # 判斷是否已經載入 PC_Board 文章，以及是否需要去查詢文章
    pc_board_loaded = bool(state.get("pc_board_results"))

    # 目前先取消使用pc_board_query_attempted
    # pc_board_query_attempted = bool(state.get("pc_board_query_attempted"))

    # 根據pc_board_response來判斷是否已經取得查詢回應
    pc_board_get_response = bool(state.get("pc_board_response"))
    # if pc_board_get_response:
    #     print("已經取得查詢回應")
    # else:
    #     print("尚未取得查詢回應")


    
    # 由router判斷是否為文章相關需求，這會影響是否優先查詢 scraper，但跟plan的need_pc_board_query不完全相同(目前先移除)
    # article_related = _is_article_related_request(state)

    # if need_pc_board_query and not pc_board_query_attempted:
    if need_pc_board_query and not pc_board_get_response:
        # 文章相關任務在每回合都先查詢一次 scraper，再交給 specialist
        return ["pc_board_scraper"], reason or summary or "需要先讀取 PC_Board 文章再進行分析"

    # if need_pc_board_query and pc_board_loaded:
    if need_pc_board_query and pc_board_get_response:
        # 查詢已經完畢或是不需要查詢，接續由專家分析
        targets = specialist_targets or list(DEFAULT_ROUTE_TARGETS)
        post_reason = summary or f"接續啟動 {', '.join(targets)} 進行分析"
        return targets, post_reason

    # if need_pc_board_query and pc_board_query_attempted and not pc_board_loaded:
    if need_pc_board_query and not pc_board_loaded:
        # 查詢過但本地沒有文章：降級為直接由專家分析（不要使用 planner 原始 reason）
        targets = specialist_targets or list(DEFAULT_ROUTE_TARGETS)
        downgrade_reason = summary or "本地未找到文章，改由專家根據目前需求直接分析"
        return targets, downgrade_reason

    if specialist_targets:
        # 若 planner 指定 specialist，使用 planner 的 summary 作為說明，但避免沿用 planner 的 detailed reason
        return specialist_targets, summary or "依 planner 計畫啟動專家"

    return _keyword_fallback_route_targets(state)


def router_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Router Node 的執行函數"""

    route_targets, route_reason = _route_targets_for_request(state)

    if debug:
        print("Router Node Route Targets:", route_targets)
        print("Router Node Route Reason:", route_reason)
        print("=" * 60)

    return {
        "route_targets": route_targets,
        "route_reason": route_reason,
    }