"""
Planner Node - 只負責把使用者需求整理成 router 可執行的計畫。

職責：
- 分析使用者需求的任務類型
- 判斷是否需要先讀取 PC_Board 文章
- 規劃後續應啟動的 specialist 與 ecommerce
- 輸出結構化計畫，不直接解題
"""

from typing import Any
from pc_builder_agent.nodes.base import run_agent_turn

def planner_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Planner Node 的執行函數"""
    
    ai_message, text = run_agent_turn(
        state=state,
        role_name="planner agent",
        # 目前呼叫專家node太多，而每個專家node其實會把每個零件都跑過一次
        system_prompt=(
            "You are the planner for a PC building workflow.\n"
            "Your job is not to solve the user's problem.\n"
            "Analyze the request and produce a structured execution plan for router.\n"
            "If the user wants to compare articles, find differences between articles, or inspect article contents before analysis, set need_pc_board_query to true.\n"
            "When a PC_Board query is needed, describe the article_query clearly, such as first article vs second article, a specific board post, or relevant menu articles.\n"
            "Choose downstream specialist_targets that should run after the query, including [cpu_specialist, gpu_specialist, memory_specialist, storage_specialist, cooling_specialist].\n"
            "If the user request involves checking current prices, availability, or making purchase decisions, include ecommerce in specialist_targets.\n"
            "If ecommerce is needed, include it in execution_order after all specialist nodes so it runs last before integrator.\n"
            "Return JSON only, with keys: task_type, need_pc_board_query, article_query, specialist_targets, comparison_axes, execution_order, summary, reason.\n"
            "summary and reason must be in Traditional Chinese (zh-TW).\n"
            "Do not include markdown fences, extra commentary, or direct recommendations."
        ),
        tools=[],
        model_name=model_name,
        debug=debug,
    )
    
    if debug:
        # print("Planner Node AI Message:", ai_message)
        print("Planner Node Text Output:", text)
        print("===============================================================")

    return {"messages": [ai_message], "plan": text}
