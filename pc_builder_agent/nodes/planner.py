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
            "先理解使用者需求並整理成可執行的組裝方向。\n"
            "一定要先調用 recall_user_preferences 來讀取既有偏好。\n"
            "如果使用者明確提到預算、用途、噪音、尺寸等限制，請用 save_user_preference 儲存。\n"
            "若需要估算電源瓦數，可調用 estimate_psu_wattage。\n"
            "輸出請簡潔，重點放在需求分類、優先順序與風險。"
        ),
        tools=[recall_user_preferences, save_user_preference, estimate_psu_wattage],
        model_name=model_name,
    )
    
    return {"messages": [ai_message], "plan": text}
