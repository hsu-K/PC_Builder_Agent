"""
GPU Specialist Node - 專注於顯卡、螢幕和散熱

職責：
- 專注顯卡、螢幕解析度、散熱與電源需求
- 針對遊戲、AI、剪輯或繪圖需求優化選擇
- 協助判斷電源需求
- 清楚說明顯卡選型方向
"""

from typing import Any
from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.tools import (
    recall_user_preferences,
    estimate_psu_wattage,
)


def gpu_specialist_node(state: dict, *, model_name: str | None = None) -> dict[str, Any]:
    """GPU Specialist Node 的執行函數"""
    
    ai_message, text = run_agent_turn(
        state=state,
        role_name="GPU specialist",
        system_prompt=(
            "專注顯卡、螢幕解析度、散熱與電源需求。\n"
            "如果 request 提到遊戲、AI、剪輯或繪圖，請優先對應 GPU 需求。\n"
            "必要時可調用 estimate_psu_wattage。\n"
            "輸出請清楚說明顯卡選型方向。"
        ),
        tools=[recall_user_preferences, estimate_psu_wattage],
        model_name=model_name,
    )
    
    return {"messages": [ai_message], "gpu_advice": text}
