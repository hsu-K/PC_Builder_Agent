"""
Memory Specialist Node - 專注於記憶體容量、通道與升級餘裕。
"""

from typing import Any

from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.memory import recall_user_preferences, recall_pc_board_articles
from pc_builder_agent.tools.hardware import recommend_ram_capacity


def memory_specialist_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Memory Specialist Node 的執行函數"""

    ai_message, text = run_agent_turn(
        state=state,
        role_name="Memory specialist",
        system_prompt=(
            "Focus on RAM capacity, channel configuration, and future upgrade headroom.\n"
            "Call recall_user_preferences first to understand profile constraints.\n"
            "If article context is useful, call recall_pc_board_articles.\n"
            "Call recommend_ram_capacity to provide concrete RAM suggestions.\n"
            "The final answer must be in Traditional Chinese (zh-TW)."
        ),
        tools=[recall_user_preferences, recall_pc_board_articles, recommend_ram_capacity],
        model_name=model_name,
        debug=debug,
    )

    return {"messages": [ai_message], "memory_advice": text}
