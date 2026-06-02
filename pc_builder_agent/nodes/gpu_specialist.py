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


def gpu_specialist_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """GPU Specialist Node 的執行函數"""

    specialist_state = dict(state)
    # 專家只讀取 pc_board_response 摘要，不直接讀整篇文章內容
    specialist_state["pc_board_results"] = []
    
    ai_message, text = run_agent_turn(
        state=specialist_state,
        role_name="GPU specialist",
        system_prompt=(
            "Focus on GPU selection, display resolution, thermal behavior, and power requirements.\n"
            "If the request mentions gaming, AI, video editing, or creative workloads, prioritize GPU-driven decisions.\n"
            "When article context is needed, only use PC_Board query summary in pc_board_response.\n"
            "Do not assume any article details that are not present in pc_board_response.\n"
            "Call estimate_psu_wattage when needed.\n"
            "Explain the GPU selection direction clearly and concretely.\n"
            "The final answer must be in Traditional Chinese (zh-TW)."
        ),
        tools=[recall_user_preferences, estimate_psu_wattage],
        model_name=model_name,
        debug=debug,
    )
    
    return {"messages": [ai_message], "gpu_advice": text}
