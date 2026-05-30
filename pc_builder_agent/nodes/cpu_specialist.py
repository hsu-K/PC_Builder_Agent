"""
CPU Specialist Node - 專注於 CPU、記憶體和主機板

職責：
- 專注 CPU、記憶體、主機板和整體平台平衡
- 從記憶中確認用途和偏好
- 協助判斷電源餘裕
- 提供可直接採用的建議
"""

from typing import Any
from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.tools import (
    recall_user_preferences,
    estimate_psu_wattage,
)


def cpu_specialist_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """CPU Specialist Node 的執行函數"""
    
    ai_message, text = run_agent_turn(
        state=state,
        role_name="CPU specialist",
        system_prompt=(
            "Focus on CPU, memory, motherboard, and overall platform balance.\n"
            "When usage patterns or preferences are found in memory, incorporate them.\n"
            "When PC_Board article data exists in the current state snapshot, use it directly for analysis.\n"
            "Call estimate_psu_wattage when needed to validate PSU headroom.\n"
            "Provide a practical recommendation that can be used directly.\n"
            "The final answer must be in Traditional Chinese (zh-TW)."
        ),
        tools=[recall_user_preferences, estimate_psu_wattage],
        model_name=model_name,
        debug=debug,
    )
    
    return {"messages": [ai_message], "cpu_advice": text}
