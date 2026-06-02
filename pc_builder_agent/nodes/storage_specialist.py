"""
Storage Specialist Node - 專注於 SSD/HDD 的容量與分層策略。
"""

from typing import Any

from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.memory import recall_user_preferences, recall_pc_board_articles
from pc_builder_agent.tools.hardware import recommend_storage_layout


def storage_specialist_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Storage Specialist Node 的執行函數"""

    ai_message, text = run_agent_turn(
        state=state,
        role_name="Storage specialist",
        system_prompt=(
            "Focus on storage layout, SSD/HDD tiering, and workload-fit capacity planning.\n"
            "Use recall_user_preferences to confirm constraints and usage patterns.\n"
            "If needed, use recall_pc_board_articles for practical references.\n"
            "Use recommend_storage_layout to output a concrete storage plan.\n"
            "The final answer must be in Traditional Chinese (zh-TW)."
        ),
        tools=[recall_user_preferences, recall_pc_board_articles, recommend_storage_layout],
        model_name=model_name,
        debug=debug,
    )

    return {"messages": [ai_message], "storage_advice": text}
