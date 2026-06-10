"""
Router Node - 根據 planner 產生的計畫決定下一步要啟動哪些 subAgent。

職責：
- 先判斷是否需要讀取 PC_Board 文章
- 若需要且尚未載入文章，先路由到 pc_board_scraper
- 文章已載入後，再路由到對應的 specialist
- 提供備援關鍵字路由，避免 plan 格式不完整時失效
"""

import json
import re
from typing import Any


# 常數定義
AVAILABLE_SPECIALISTS = [
    "cpu_specialist",
    "gpu_specialist",
    "memory_specialist",
    "storage_specialist",
    "cooling_specialist",
    "pc_board_scraper",
    "ecommerce",
]
DEFAULT_ROUTE_TARGETS = ["cpu_specialist", "gpu_specialist"]

CPU_KEYWORDS = (
    "cpu", "處理器", "記憶體", "ram", "文書", "辦公",
    "學習", "程式", "開發", "省電", "靜音", "主機板",
)

GPU_KEYWORDS = (
    "gpu", "顯卡", "顯示卡", "遊戲", "1440p", "4k", "2k", "1080p",
    "光追", "fps", "剪輯", "繪圖", "渲染",
    # 常見顯卡品牌/系列詞:讓「RTX 5070 vs 5060 Ti」這類純顯卡比較能命中 gpu_specialist
    "rtx", "gtx", "radeon", "geforce",
)
# 「AI」單獨成詞才算 GPU 意圖(避免裸子字串 "ai" 誤中 "aio"/"fail" 等);
# 前後不接英文字母,故 "aio" 不中、"AI繪圖"/"玩 AI" 仍中。
_GPU_AI_RE = re.compile(r"(?<![a-z])ai(?![a-z])")

# 舊的廣義 PC_Board 關鍵字(含「推薦/有什麼/介紹」等泛用詞)。
# 依 Phase 4B 規格保留不大幅移除,避免破壞既有引用;但 fallback 路由「不再」用它做判斷,
# 改用下方更精確的 PC_BOARD_DISCUSSION_KEYWORDS,以免泛用詞把選型/商城問題誤導到 pc_board。
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

# 明確的「文章來源」關鍵字(PTT / 電蝦 / 網友 / 文章 / 社群討論 / PC_Board)。
# 刻意**不含**「菜單 / 推薦 / 有什麼」等泛用詞,避免一般組機需求被誤導到 pc_board_scraper;
# 僅在使用者明確點名文章來源時,才優先去查 PC_Board 文章。
ARTICLE_SOURCE_KEYWORDS = (
    "ptt", "批踢踢", "電蝦", "網友", "文章", "社群討論", "鄉民",
    "pc_board", "pc board", "板上", "版上",
)


# 明確的電子商城 / 價格 / 優惠商業意圖詞。
# 刻意不放入「推薦/有什麼/介紹」等泛用詞,避免把一般問題誤導到 ecommerce。
# 補充:除規格要求清單外另加入「預算」,以涵蓋「預算 10000 以內」這種非連續寫法
# (規格清單中的「預算內」在這種寫法下不會連續出現)。
ECOMMERCE_KEYWORDS = (
    "優惠", "特價", "折扣", "促銷", "便宜", "比價", "價格", "報價",
    "多少錢", "預算內", "預算", "缺貨", "庫存", "現貨", "商城",
    "原價屋", "欣亞", "pchome", "momo", "購買", "下單",
    # Cooler / 散熱器商品查詢(散熱器/水冷/空冷/塔扇/AIO 屬 ecommerce 可查商品)
    "散熱器", "cpu散熱器", "cooler", "空冷", "塔扇", "雙塔", "水冷", "aio",
    # 完整 build / 整機 / 菜單 意圖(由 recommend_pc_build_tool 處理,屬 ecommerce)
    "配一台", "組一台", "組電腦", "組機", "整機", "遊戲機", "文書機", "辦公機",
    "工作機", "菜單", "完整菜單", "電腦菜單",
)


# 互動式的關鍵字，目前用不到

# 互動式逐步選件意圖詞(由 recommend_component_options_tool 處理,屬 ecommerce)。
# 刻意搭配「選件意圖」或「零組件+世代/平台」,避免只因泛用詞(如「推薦」)就誤導到 ecommerce。
# 注意:文字會先 .lower(),故英文一律小寫;中文不受影響。
INTERACTIVE_SELECTION_KEYWORDS = (
    # 選件/候選意圖
    "候選", "選項", "幾個", "幾款", "逐步", "一個一個", "先給我", "先看", "先選",
    "下一步", "我選", "選第", "接下來",
    # 自己挑零件 / CPU-first 起手意圖(預設互動式逐步選件)
    "挑零件", "選零件", "自己挑", "自己選", "從cpu開始", "cpu開始", "從 cpu 開始",
    # 重新選單項 / 確認保存意圖(完整菜單完成後的操作)
    "重新選", "重選", "太貴", "換顯示卡", "換顯卡", "換cpu", "換主機板", "換記憶體",
    "確認此菜單", "確認菜單", "確認這套", "就這套", "保存", "存成json", "存成 json",
    "存檔", "存起來", "存成檔", "輸出json", "輸出 json",
    # 「第 N 個 / 第 N 張」常見寫法(另有 _NTH_RE 處理任意 N 與空白)
    "第1個", "第2個", "第3個", "第1張", "第2張", "第3張",
    # 候選請求常見組合詞
    "cpu候選", "主機板候選", "記憶體候選", "ram候選", "相容主機板", "相容記憶體",
    "ddr4 主機板", "ddr5 主機板", "ddr4主機板", "ddr5主機板",
    "ddr4 平台", "ddr5 平台", "ddr4平台", "ddr5平台",
    # 換平台 / 記憶體世代意圖
    "ddr4", "ddr5",
)

# 「第 N 個 / 第 N 張」(任意數字、可含空白)與「換 平台/世代」意圖,用 regex 補捉。
_NTH_SELECT_RE = re.compile(r"第\s*\d+\s*[個张張顆隻支]")
_SWITCH_PLATFORM_RE = re.compile(r"換\s*(am5|am4|intel|amd|ddr4|ddr5|lga1700|lga1851)")
# 品牌選用意圖(組機/選件情境):『(想/要/用/選) AMD/Intel』或『AMD…Intel…都可以』。
# 用於互動式 CPU-first 起手的品牌指定;純規格比較(無此措辭)不會命中。
_BRAND_INTENT_RE = re.compile(
    r"(想|要|用|選|指定)\s*(amd|intel)|(amd[^a-z]{0,6}intel|intel[^a-z]{0,6}amd)[^a-z]{0,4}都")




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
    execution_order = _normalize_targets(plan_data.get("execution_order"))
    specialist_targets = _normalize_targets(plan_data.get("specialist_targets"))
    planned_targets = execution_order or specialist_targets

    reason = plan_data.get("reason", "")
    if not isinstance(reason, str):
        reason = ""

    summary = plan_data.get("summary", "")
    if not isinstance(summary, str):
        summary = ""

    return planned_targets, need_pc_board_query, reason.strip(), summary.strip()


# def _is_article_related_request(state: dict) -> bool:
#     """判斷目前需求是否屬於文章相關任務。"""

#     combined_text = "\n".join(
#         part for part in [state.get("request", ""), state.get("plan", "")] if part
#     ).lower()

#     """pc_board_match = _contains_keyword(combined_text, PC_BOARD_DISCUSSION_KEYWORDS)
#     interactive_match = (
#         _contains_keyword(combined_text, INTERACTIVE_SELECTION_KEYWORDS)
#         or bool(_NTH_SELECT_RE.search(combined_text))
#         or bool(_SWITCH_PLATFORM_RE.search(combined_text))
#         or bool(_BRAND_INTENT_RE.search(combined_text))
#     )
#     ecommerce_match = _contains_keyword(combined_text, ECOMMERCE_KEYWORDS) or interactive_match
#     cpu_match = _contains_keyword(combined_text, CPU_KEYWORDS)
#     gpu_match = _contains_keyword(combined_text, GPU_KEYWORDS) or bool(_GPU_AI_RE.search(combined_text))"""

#     if any(keyword.lower() in combined_text for keyword in ARTICLE_TASK_KEYWORDS):
#         return True

#     plan_data = _parse_plan(state.get("plan", ""))
#     task_type = plan_data.get("task_type", "")
#     if task_type in {"compare_articles", "analyze_article_configuration"}:
#         return True

#     article_query = plan_data.get("article_query", "")
#     if isinstance(article_query, str) and article_query.strip():
#         return True

#     return False


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

    # 互動式逐步選件意圖(關鍵字 / 第 N 個 / 換平台 / 品牌意圖)與商城商業意圖。
    # interactive_match = (
    #     _contains_keyword(combined_text, INTERACTIVE_SELECTION_KEYWORDS)
    #     or bool(_NTH_SELECT_RE.search(combined_text))
    #     or bool(_SWITCH_PLATFORM_RE.search(combined_text))
    #     or bool(_BRAND_INTENT_RE.search(combined_text))
    # )

    ecommerce_match = _contains_keyword(combined_text, ECOMMERCE_KEYWORDS)

    component_targets: list[str] = []
    if memory_match:
        component_targets.append("memory_specialist")
    if storage_match:
        component_targets.append("storage_specialist")
    if cooling_match:
        component_targets.append("cooling_specialist")

    if component_targets:
        return component_targets, "需求聚焦於特定零件，改由對應專家進行深入分析"

    targets: list[str] = []
    reason_parts: list[str] = []

    if pc_board_match:
        targets.append("pc_board_scraper")
        reason_parts.append("偵測到 PTT/社群/菜單討論詞")
    if ecommerce_match:
        targets.append("ecommerce")
        reason_parts.append("偵測到商城/價格/優惠等商業意圖詞")
    if gpu_match:
        targets.append("gpu_specialist")
        reason_parts.append("偵測到顯卡/遊戲/圖形需求")
    if cpu_match:
        targets.append("cpu_specialist")
        reason_parts.append("偵測到處理器/記憶體/平台需求")

    # 去重並保持加入順序
    deduped: list[str] = []
    for target in targets:
        if target not in deduped:
            deduped.append(target)

    if not deduped:
        return list(DEFAULT_ROUTE_TARGETS), "語意不明確，使用關鍵字備援後採用預設雙專家"

    return deduped, "；".join(reason_parts)


def _route_targets_for_request(
    state: dict,
    *,
    model_name: str | None = None,
) -> tuple[list[str], str]:
    """根據使用者需求、planner 計畫與 deterministic guard 決定路由目標。"""

    # 如果已經開始路由，保持原有 route_targets 不變，讓後續 node 繼續執行完整路線。
    if state.get("routing_started"):
        return list(state.get("route_targets") or []), state.get("route_reason", "")

    request = state.get("request", "")
    plan = state.get("plan", "")
    planned_targets, need_pc_board_query, reason, summary = _extract_plan_targets(state)

    # 0. 明確文章來源優先：若使用者明確點名 PTT/電蝦/網友/文章/社群討論/PC_Board,
    #    且尚未取得文章回應,先去查 PC_Board 文章(必須早於互動選件 pre-route,
    #    否則「PTT…預算X…菜單」會被當成互動選件而誤進 ecommerce)。
    #    註:單純「菜單/推薦」不在 ARTICLE_SOURCE_KEYWORDS,不會誤觸。
    # 只看「使用者 request」本身,不看 LLM 產生的 plan(plan 可能含『文章』等字而誤觸)。
    # article_source_match = _contains_keyword((request or "").lower(), ARTICLE_SOURCE_KEYWORDS)
    # if article_source_match and not state.get("pc_board_response"):
    #     if planned_targets:
    #         if planned_targets[0] != "pc_board_scraper":
    #             planned_targets = [
    #                 "pc_board_scraper",
    #                 *[target for target in planned_targets if target != "pc_board_scraper"],
    #             ]
    #         return planned_targets, "使用者明確要求 PTT/電蝦/文章資料，先查詢 PC_Board 文章"
    #     return ["pc_board_scraper"], "使用者明確要求 PTT/電蝦/文章資料，先查詢 PC_Board 文章"

    # 1. Deterministic 前置路由：互動式逐步選件必須直接進 ecommerce。
    # 這可避免「我選第 N 個 / 無 / 重新選 / 確認保存」被誤送到 specialist，
    # 導致 selected_components / last_component_options 沒有更新。
    # 但若使用者明確點名文章來源(PTT/電蝦/文章…)，不在此被導向 ecommerce：
    # 該需求走 pc_board_scraper → specialist → integrator(由文章內容作答)。
    # try:
    #     from pc_builder_agent.tools.ecommerce_db import is_interactive_selection_request

    #     if not article_source_match and is_interactive_selection_request(request):
    #         return ["ecommerce"], "偵測到互動式逐步選件動作, deterministic 直接導向 ecommerce"
    # except Exception:
    #     pass

    # 3. PC_Board 文章查詢優先：如果 planner 判斷需要文章，且尚未取得回應，先跑 scraper。
    pc_board_get_response = bool(state.get("pc_board_response"))

    # 由pc_board_get_response判斷是否已經取得文章回應
    if need_pc_board_query and not pc_board_get_response:
        if planned_targets:
            if planned_targets[0] != "pc_board_scraper":
                planned_targets = [
                    "pc_board_scraper",
                    *[target for target in planned_targets if target != "pc_board_scraper"],
                ]
            return planned_targets, reason or summary or "需要先讀取 PC_Board 文章再進行分析"
        return ["pc_board_scraper"], reason or summary or "需要先讀取 PC_Board 文章再進行分析"

    if need_pc_board_query and pc_board_get_response:
        targets = planned_targets or list(DEFAULT_ROUTE_TARGETS)
        return targets, summary or f"接續啟動 {', '.join(targets)} 進行分析"

    if planned_targets:
        # 若 planner 指定 specialist 或 execution_order，使用 planner 的 summary 作為說明。
        return planned_targets, summary or "依 planner 計畫啟動專家"

    return _keyword_fallback_route_targets(state)


def router_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Router Node 的執行函數"""

    route_targets, route_reason = _route_targets_for_request(state)
    # 取得待處理的 route_targets，如果尚未開始路由，則從 route_targets 欄位初始化 pending_route_targets。
    pending_route_targets = list(state.get("pending_route_targets") or [])
    if not state.get("routing_started"):
        pending_route_targets = list(route_targets)

    if debug:
        print("Router Node Route Targets:", route_targets)
        print("Router Node Route Reason:", route_reason)
        print("=" * 60)

    return {
        "route_targets": route_targets,
        "route_reason": route_reason,
        "pending_route_targets": pending_route_targets,
        "routing_started": True,
    }