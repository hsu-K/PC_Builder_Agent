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
AVAILABLE_SPECIALISTS = ["cpu_specialist", "gpu_specialist", "pc_board_scraper"]
DEFAULT_ROUTE_TARGETS = ["cpu_specialist", "gpu_specialist"]

CPU_KEYWORDS = (
    "cpu", "處理器", "記憶體", "ram", "文書", "辦公",
    "學習", "程式", "開發", "省電", "靜音", "主機板",
)

GPU_KEYWORDS = (
    "gpu", "顯卡", "顯示卡", "遊戲", "1440p", "4k",
    "光追", "fps", "ai", "剪輯", "繪圖", "渲染",
)

PC_BOARD_KEYWORDS = (
    "文章", "菜單", "推薦", "ptt", "分享", "討論", "社群",
    "之前", "爬取", "查看", "看看", "告訴我", "有什麼", "介紹",
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

    if cpu_match and gpu_match:
        return ["cpu_specialist", "gpu_specialist"], "需求同時涵蓋平台與顯示需求，兩個專家都啟動"

    if gpu_match:
        return ["gpu_specialist"], "需求明確偏向顯卡、遊戲或圖形工作"

    if cpu_match:
        return ["cpu_specialist"], "需求明確偏向處理器、記憶體或整體平台"

    return list(DEFAULT_ROUTE_TARGETS), "語意不明確，使用關鍵字備援後採用預設雙專家"


def _route_targets_for_request(state: dict) -> tuple[list[str], str]:
    """根據 planner 計畫決定路由目標。"""

    specialist_targets, need_pc_board_query, reason, summary = _extract_plan_targets(state)
    pc_board_loaded = bool(state.get("pc_board_results"))
    pc_board_query_attempted = bool(state.get("pc_board_query_attempted"))

    if need_pc_board_query and not pc_board_loaded and not pc_board_query_attempted:
        return ["pc_board_scraper"], reason or summary or "需要先讀取 PC_Board 文章再進行分析"

    if need_pc_board_query and pc_board_loaded:
        targets = specialist_targets or list(DEFAULT_ROUTE_TARGETS)
        return targets, reason or summary or "文章已載入，接續由專家分析差異"

    if need_pc_board_query and pc_board_query_attempted and not pc_board_loaded:
        targets = specialist_targets or list(DEFAULT_ROUTE_TARGETS)
        return targets, reason or summary or "本地未找到文章，改由專家根據目前需求分析"

    if specialist_targets:
        return specialist_targets, reason or summary or "依 planner 計畫啟動專家"

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
        print("===============================================================")

    return {
        "route_targets": route_targets,
        "route_reason": route_reason,
    }