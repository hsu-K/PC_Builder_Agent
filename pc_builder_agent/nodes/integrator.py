"""
Integrator Node - 整合所有專家的建議成最終回應

職責：
- 整合 planner、CPU specialist、GPU specialist 的輸出
- 生成最終的建議摘要
- 格式：繁體中文、簡潔但具體
- 結構：總結、優先升級項目、下一步
"""

from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from pc_builder_agent.nodes.base import build_model, message_text
from pc_builder_agent.memory import format_profile_summary


def integrator_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Integrator Node 的執行函數"""
    
    model = build_model(model_name)
    
    summary_messages = [
        SystemMessage(
            content=(
                "You are the integrator agent. Combine outputs from planner, router, CPU specialist, and GPU specialist into a final recommendation.\n"
                "The final output must be in Traditional Chinese (zh-TW), concise but specific, and structured as: Summary, Priority Upgrades, Next Steps."
            )
        ),
        HumanMessage(
            content=(
                f"User request: {state.get('request', '')}\n\n"
                f"Planner: {state.get('plan', '')}\n\n"
                f"Router targets: {', '.join(state.get('route_targets', []))}\n"
                f"Router reason: {state.get('route_reason', '')}\n\n"
                f"CPU specialist: {state.get('cpu_advice', '')}\n\n"
                f"GPU specialist: {state.get('gpu_advice', '')}\n\n"
                f"Known preferences: {format_profile_summary(state.get('profile_id', 'default'))}"
            )
        ),
    ]
    
    ai_message = model.invoke(summary_messages)
    
    return {"messages": [ai_message], "final_answer": message_text(ai_message)}
