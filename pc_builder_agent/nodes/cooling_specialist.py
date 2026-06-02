"""
Cooling Specialist Node - 專注於散熱方案與噪音平衡。
"""

from typing import Any

from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.memory import recall_user_preferences, recall_pc_board_articles
from pc_builder_agent.tools.hardware import recommend_cooling_solution


def cooling_specialist_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Cooling Specialist Node 的執行函數"""

    ai_message, text = run_agent_turn(
        state=state,
        role_name="Cooling specialist",
        system_prompt=(
            "Focus on thermal design, cooler class selection, and noise-performance tradeoffs.\n"
            "Start by checking preferences via recall_user_preferences.\n"
            "Use recall_pc_board_articles when real-world examples are useful.\n"
            "Use recommend_cooling_solution when thermal estimate is needed.\n"
            "The final answer must be in Traditional Chinese (zh-TW)."
        ),
        tools=[recall_user_preferences, recall_pc_board_articles, recommend_cooling_solution],
        model_name=model_name,
        debug=debug,
    )

    return {"messages": [ai_message], "cooling_advice": text}
