"""
LangGraph Agent 工作流程模組

核心責任：
1. 定義工作流程狀態結構 (BuildState)
2. 組裝各個 Node 成完整的工作流程圖
3. 返回可執行的編譯圖

各 Node 的具體實現已移至 nodes/ 模組中，
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Send

from pc_builder_agent.nodes import (
    planner_node,
    router_node,
    cpu_specialist_node,
    gpu_specialist_node,
    memory_specialist_node,
    storage_specialist_node,
    cooling_specialist_node,
    integrator_node,
    pc_board_scraper_node,
    ecommerce_node,
)
from pc_builder_agent.memory import PROFILE_STORE


# ============================================================================
# 狀態定義
# ============================================================================

class BuildState(TypedDict, total=False):
    """
    LangGraph 狀態管理 - 整個工作流程中流動的數據結構
    
    Attributes:
        profile_id (str): 使用者 ID，用於查詢和保存偏好設定
        preferences (dict): 從 preference.json 讀取的使用者偏好
        pc_board_results (list): 從 PC_Board Scraper 爬取的文章列表
        pc_board_query_attempted (bool): 是否已嘗試執行過 PC_Board 查詢
        request (str): 使用者最新的 PC 組裝需求
        messages (Annotated[list[BaseMessage]]): 完整的對話歷史
        plan (str): planner agent 輸出的 JSON 計畫
        route_targets (list[str]): router 選中的 subAgent 名稱
        route_reason (str): router 做出此選擇的原因
        cpu_advice (str): CPU specialist 的建議
        gpu_advice (str): GPU specialist 的建議
        memory_advice (str): Memory specialist 的建議
        storage_advice (str): Storage specialist 的建議
        cooling_advice (str): Cooling specialist 的建議
        pc_board_response (str): PC_Board Scraper 的查詢回應
        ecommerce_advice (str): Ecommerce Recommendation Specialist 的商品/優惠建議
        ecommerce_db_path (str): ecommerce 查詢使用的資料庫路徑(可選,主要供測試注入)
        final_answer (str): integrator 整合後的最終建議

        互動式選件 state(state-driven,跨 thread 多輪保留):
        selected_components (dict): {category: {product_name, price, source, socket, platform,
            memory_generation, is_virtual}};已選零件的權威來源(非自然語言摘要)。
        selected_budget (int|None): 互動式選件的預算。
        selected_use_case (str|None): 互動式選件的用途(gaming/4k_gaming/office)。
        current_target_category (str|None): 目前正在挑選的類別。
        last_component_options (list): 上一輪推薦的候選清單(供「第 N 個」deterministic 解析)。
        selection_flow_complete (bool): 是否已選完全部類別。
        pending_reselect_category (str|None): 正在重新選擇的類別。
        interactive_response (bool): 本輪是否由 deterministic 互動式引擎產生 final_answer
            (為 True 時 integrator 直接沿用,不再經 LLM 改寫)。
    """
    profile_id: str
    preferences: dict
    pc_board_results: list
    pc_board_query_attempted: bool
    request: str
    messages: Annotated[list[BaseMessage], add_messages]
    plan: str
    route_targets: list[str]
    route_reason: str
    cpu_advice: str
    gpu_advice: str
    memory_advice: str
    storage_advice: str
    cooling_advice: str
    pc_board_response: str
    ecommerce_advice: str
    ecommerce_db_path: str
    final_answer: str
    # 互動式選件 state(Phase Interactive-State-Driven-Fix)
    selected_components: dict
    selected_budget: int | None
    selected_use_case: str | None
    current_target_category: str | None
    last_component_options: list
    selection_flow_complete: bool
    pending_reselect_category: str | None
    interactive_response: bool


# ============================================================================
# 工作流程輔助函數
# ============================================================================

# 可並行 fan-out 並收斂到 integrator 的 specialist(pc_board_scraper 不在此列,它走短路 → END)
FAN_OUT_SPECIALISTS = ("cpu_specialist", "gpu_specialist", "ecommerce")
DEFAULT_FAN_OUT = ["cpu_specialist", "gpu_specialist"]


def _dispatch_specialists(state: BuildState) -> list[Send]:
    """根據 router 結果，決定要並行執行哪些 subAgent"""
    
    # 如果沒有 router 結果，退回預設的雙專家，之後可能需要改成直接進結論
    targets = state.get("route_targets") or ["cpu_specialist", "gpu_specialist"]
    
    # 如果包含 pc_board_scraper，優先執行它
    if "pc_board_scraper" in targets:
        return [Send("pc_board_scraper", dict(state))]

    # 非 pc_board 情況:cpu_specialist / gpu_specialist / ecommerce 都可並行 fan-out → integrator。
    # 過濾掉未知 target 以避免 Send 到不存在的節點;若過濾後為空，退回原本預設雙專家。
    dispatch_targets = [t for t in targets if t in FAN_OUT_SPECIALISTS]
    if not dispatch_targets:
        dispatch_targets = list(DEFAULT_FAN_OUT)

    return [Send(target, dict(state)) for target in dispatch_targets]



# ============================================================================
# 工作流程圖構建
# ============================================================================

def build_graph(model_name: str | None = None, debug: bool = False):
    """
    建構完整的 LangGraph 工作流程
    
        執行流程圖：

                START
                    ↓
                planner (理解需求並產生查詢/分析計畫)
                    ↓
                router (決定先查文章或直接啟動 specialist)
                    ↓
            ┌────────────────────────────────────────────────────┐
            │                                                    │
            │ 若需要先查文章且尚未載入：                            │
            │   pc_board_scraper (query 模式讀取/解讀本地文章)     │
            │                    ↓                               │
            │                  router (再次判斷下一步)            │
            │                                                    │
            └────────────────────────────────────────────────────┘
                                                    ↓
                             cpu_specialist / gpu_specialist
                                        (依需求 fan-out)
                                                    ↓
                                            integrator (整合所有建議)
                                                    ↓
                                                 END
    
    Args:
        model_name: 使用的 OpenAI 模型名稱
    
    Returns:
        CompiledStateGraph: 已編譯的工作流程圖，可直接呼叫 invoke() 執行
    """
    graph = StateGraph(BuildState)

    # 添加所有節點，從 nodes 模組導入
    graph.add_node("planner", lambda state: planner_node(state, model_name=model_name, debug=debug))
    graph.add_node("router", lambda state: router_node(state, model_name=model_name, debug=debug))
    graph.add_node("cpu_specialist", lambda state: cpu_specialist_node(state, model_name=model_name, debug=debug))
    graph.add_node("gpu_specialist", lambda state: gpu_specialist_node(state, model_name=model_name, debug=debug))
    graph.add_node("memory_specialist", lambda state: memory_specialist_node(state, model_name=model_name, debug=debug))
    graph.add_node("storage_specialist", lambda state: storage_specialist_node(state, model_name=model_name, debug=debug))
    graph.add_node("cooling_specialist", lambda state: cooling_specialist_node(state, model_name=model_name, debug=debug))
    graph.add_node("pc_board_scraper", lambda state: pc_board_scraper_node(state, model_name=model_name, mode="query", debug=debug))
    graph.add_node("ecommerce", lambda state: ecommerce_node(state, model_name=model_name, debug=debug))
    graph.add_node("integrator", lambda state: integrator_node(state, model_name=model_name, debug=debug))

    # 定義邊（流程連接）
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "router")
    graph.add_conditional_edges("router", _dispatch_specialists)
    graph.add_edge("pc_board_scraper", "router")
    graph.add_edge("cpu_specialist", "integrator")
    graph.add_edge("gpu_specialist", "integrator")
    graph.add_edge("ecommerce", "integrator")
    graph.add_edge("memory_specialist", "integrator")
    graph.add_edge("storage_specialist", "integrator")
    graph.add_edge("cooling_specialist", "integrator")
    graph.add_edge("integrator", END)

    # 編譯工作流程圖
    return graph.compile(
        checkpointer=InMemorySaver(),
        store=PROFILE_STORE,
        name="pc-builder-agent-gpt",
    )