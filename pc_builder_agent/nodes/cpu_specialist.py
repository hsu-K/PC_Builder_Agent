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


def cpu_specialist_node(state: dict, *, model_name: str | None = None) -> dict[str, Any]:
    """CPU Specialist Node 的執行函數"""
    
    ai_message, text = run_agent_turn(
        state=state,
        role_name="CPU specialist",
        system_prompt=(
            "專注 CPU、記憶體、主機板與整體平台平衡。\n"
            "如果能從記憶中確認用途或偏好就參考它。\n"
            "必要時可調用 estimate_psu_wattage 協助判斷電源餘裕。\n"
            "輸出請提供一段可直接採用的建議。"
        ),
        tools=[recall_user_preferences, estimate_psu_wattage],
        model_name=model_name,
    )
    
    return {"messages": [ai_message], "cpu_advice": text}
