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
    component_parser_node,
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

        execution_order (list[str]): planner 建議的實際執行順序
        pending_route_targets (list[str]): 尚未執行的 route queue
        routing_started (bool): 是否已經開始順序式路由
        completed_route_targets (list[str]): 已完成的 route queue

        cpu_advice (str): CPU specialist 的建議
        gpu_advice (str): GPU specialist 的建議
        memory_advice (str): Memory specialist 的建議
        storage_advice (str): Storage specialist 的建議
        cooling_advice (str): Cooling specialist 的建議
        pc_board_response (str): PC_Board Scraper 的查詢回應
        ecommerce_advice (str): Ecommerce Recommendation Specialist 的商品/優惠建議
        ecommerce_db_path (str): ecommerce 查詢使用的資料庫路徑(可選,主要供測試注入)
        final_answer (str): integrator 整合後的最終建議
        parsed_components (dict): component_parser 從 final_answer 解析出的零件 JSON

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

    execution_order: list[str]
    pending_route_targets: list[str]
    routing_started: bool
    completed_route_targets: list[str]
    
    cpu_advice: str
    gpu_advice: str
    memory_advice: str
    storage_advice: str
    cooling_advice: str
    pc_board_response: str
    final_answer: str
    
    parsed_components: dict
    
    ecommerce_advice: str
    ecommerce_db_path: str
    
    # 互動式選件 state(Phase Interactive-State-Driven-Fix)
    # selected_components: dict
    # selected_budget: int | None
    # selected_use_case: str | None
    # current_target_category: str | None
    # last_component_options: list
    # selection_flow_complete: bool
    # pending_reselect_category: str | None
    # interactive_response: bool


# ============================================================================
# 工作流程輔助函數
# ============================================================================

AVAILABLE_ROUTE_TARGETS = {
    "cpu_specialist",
    "gpu_specialist",
    "memory_specialist",
    "storage_specialist",
    "cooling_specialist",
    "pc_board_scraper",
    "ecommerce",
}


def _with_completed_target(state: BuildState, result: dict[str, object], target: str) -> dict[str, object]:
    """把已完成的 target 累加到 state 中，供下一輪 router 取用。"""

    output = dict(result or {})
    completed = list(state.get("completed_route_targets") or [])
    if not completed or completed[-1] != target:
        completed.append(target)
    output["completed_route_targets"] = completed
    return output


def _dispatch_next_target(state: BuildState) -> list[Send]:
    """依照 route queue 順序，逐一派送下一個 node。"""

    route_targets = list(state.get("route_targets") or [])
    completed_targets = list(state.get("completed_route_targets") or [])

    if not route_targets:
        return [Send("integrator", dict(state))]

    next_index = len(completed_targets)
    if next_index >= len(route_targets):
        return [Send("integrator", dict(state))]

    next_target = route_targets[next_index]
    if next_target not in AVAILABLE_ROUTE_TARGETS:
        return [Send("integrator", dict(state))]

    next_state = dict(state)
    next_state["routing_started"] = True

    return [Send(next_target, next_state)]



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
                │ router 依 planner 的 execution_order 逐一派送下一個 node │
                │                                                    │
                └────────────────────────────────────────────────────┘
                                    ↓
                       pc_board_scraper / specialists / ecommerce
                          (依 planner 順序逐一執行)
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
    graph.add_node(
        "cpu_specialist",
        lambda state: _with_completed_target(
            state,
            cpu_specialist_node(state, model_name=model_name, debug=debug),
            "cpu_specialist",
        ),
    )
    graph.add_node(
        "gpu_specialist",
        lambda state: _with_completed_target(
            state,
            gpu_specialist_node(state, model_name=model_name, debug=debug),
            "gpu_specialist",
        ),
    )
    graph.add_node(
        "memory_specialist",
        lambda state: _with_completed_target(
            state,
            memory_specialist_node(state, model_name=model_name, debug=debug),
            "memory_specialist",
        ),
    )
    graph.add_node(
        "storage_specialist",
        lambda state: _with_completed_target(
            state,
            storage_specialist_node(state, model_name=model_name, debug=debug),
            "storage_specialist",
        ),
    )
    graph.add_node(
        "cooling_specialist",
        lambda state: _with_completed_target(
            state,
            cooling_specialist_node(state, model_name=model_name, debug=debug),
            "cooling_specialist",
        ),
    )
    graph.add_node(
        "pc_board_scraper",
        lambda state: _with_completed_target(
            state,
            pc_board_scraper_node(state, model_name=model_name, mode="query", debug=debug),
            "pc_board_scraper",
        ),
    )
    graph.add_node(
        "ecommerce",
        lambda state: _with_completed_target(
            state,
            ecommerce_node(state, model_name=model_name, debug=debug),
            "ecommerce",
        ),
    )
    graph.add_node(
        "integrator",
        lambda state: _with_completed_target(
            state,
            integrator_node(state, model_name=model_name, debug=debug),
            "integrator",
        ),
    )
    graph.add_node(
        "component_parser",
        lambda state: component_parser_node(state, model_name=model_name, debug=debug),
    )

    # 定義邊（流程連接）
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "router")
    graph.add_conditional_edges("router", _dispatch_next_target)
    graph.add_edge("pc_board_scraper", "router")
    graph.add_edge("cpu_specialist", "router")
    graph.add_edge("gpu_specialist", "router")
    graph.add_edge("ecommerce", "router")
    graph.add_edge("memory_specialist", "router")
    graph.add_edge("storage_specialist", "router")
    graph.add_edge("cooling_specialist", "router")
    # graph.add_edge("integrator", END)
    graph.add_edge("integrator", "component_parser")
    graph.add_edge("component_parser", END)

    # 編譯工作流程圖
    return graph.compile(
        checkpointer=InMemorySaver(),
        store=PROFILE_STORE,
        name="pc-builder-agent-gpt",
    )