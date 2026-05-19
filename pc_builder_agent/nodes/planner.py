"""
Planner Node - 理解需求並整理成可執行的組裝方向

職責：
- 理解使用者的 PC 組裝需求
- 調用工具查詢既有偏好和估算電源需求
- 明確提到預算、用途、噪音等時保存偏好
- 輸出簡潔的需求分類和優先順序
"""

from typing import Any
from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.tools import (
    recall_user_preferences,
    save_user_preference,
    estimate_psu_wattage,
)


def planner_node(state: dict, *, model_name: str | None = None) -> dict[str, Any]:
    """Planner Node 的執行函數"""
    
    ai_message, text = run_agent_turn(
        state=state,
        role_name="planner agent",
        system_prompt=(
            "First understand the user's needs and turn them into an actionable PC build direction.\n"
            "You must call recall_user_preferences first to load known preferences.\n"
            "If the user explicitly mentions budget, use case, noise, size, or other constraints, save them with save_user_preference.\n"
            "If power estimation is needed, call estimate_psu_wattage.\n"
            "Keep the output concise and focus on requirement categories, priorities, and risks.\n"
            "The final answer must be in Traditional Chinese (zh-TW)."
        ),
        tools=[recall_user_preferences, save_user_preference, estimate_psu_wattage],
        model_name=model_name,
    )
    
    return {"messages": [ai_message], "plan": text}
