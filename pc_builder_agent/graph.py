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
    integrator_node,
    pc_board_scraper_node,
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
        request (str): 使用者最新的 PC 組裝需求
        messages (Annotated[list[BaseMessage]]): 完整的對話歷史
        plan (str): planner agent 的分析結果
        route_targets (list[str]): router 選中的 subAgent 名稱
        route_reason (str): router 做出此選擇的原因
        cpu_advice (str): CPU specialist 的建議
        gpu_advice (str): GPU specialist 的建議
        pc_board_response (str): PC_Board Scraper 的查詢回應
        final_answer (str): integrator 整合後的最終建議
    """
    profile_id: str
    preferences: dict
    pc_board_results: list
    request: str
    messages: Annotated[list[BaseMessage], add_messages]
    plan: str
    route_targets: list[str]
    route_reason: str
    cpu_advice: str
    gpu_advice: str
    pc_board_response: str
    final_answer: str


# ============================================================================
# 工作流程輔助函數
# ============================================================================

def _dispatch_specialists(state: BuildState) -> list[Send]:
    """根據 router 結果，決定要並行執行哪些 subAgent"""
    targets = state.get("route_targets") or ["cpu_specialist", "gpu_specialist"]
    
    # 如果包含 pc_board_scraper，優先執行它
    if "pc_board_scraper" in targets:
        return [Send("pc_board_scraper", dict(state))]
    
    return [Send(target, dict(state)) for target in targets]



# ============================================================================
# 工作流程圖構建
# ============================================================================

def build_graph(model_name: str | None = None, debug: bool = False):
    """
    建構完整的 LangGraph 工作流程
    
    執行流程圖：
    
        START
          ↓
        planner (理解需求，查詢/保存偏好)
          ↓
        router (根據需求選擇要啟動哪些 subAgent)
            ↓
        ┌─────────────────────────┐
        ↓                         ↓
    pc_board_scraper     ┌─────────────────┐
        ↓                ↓                 ↓
       END          cpu_specialist    gpu_specialist (依需求 fan-out)
                       ↓                 ↓
                       └─────────────────┘
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
    graph.add_node("pc_board_scraper", lambda state: pc_board_scraper_node(state, model_name=model_name, mode="query", debug=debug))
    graph.add_node("integrator", lambda state: integrator_node(state, model_name=model_name, debug=debug))

    # 定義邊（流程連接）
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "router")
    graph.add_conditional_edges("router", _dispatch_specialists)
    graph.add_edge("pc_board_scraper", END)
    graph.add_edge("cpu_specialist", "integrator")
    graph.add_edge("gpu_specialist", "integrator")
    graph.add_edge("integrator", END)

    # 編譯工作流程圖
    return graph.compile(
        checkpointer=InMemorySaver(),
        store=PROFILE_STORE,
        name="pc-builder-agent-gpt",
    )