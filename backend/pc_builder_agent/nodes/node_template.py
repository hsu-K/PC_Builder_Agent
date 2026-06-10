"""
Base Node - 理解需求並整理成可執行的組裝方向

"""

from typing import Any
from pc_builder_agent.nodes.base import run_agent_turn



def base_node(
    state: dict, 
    *,
    model_name: str | None = None,
    debug: bool = False
) -> dict[str, Any]:
    """Base Node 的執行函數"""
    
    ai_message, text = run_agent_turn(
        state=state,
        role_name="base agent",
        system_prompt=(
            ""
        ),
        tools=[...],  # 傳入所需的工具
        model_name=model_name,
    )

    if debug:
        pass  # 在 debug 模式下可以選擇性地輸出 ai_message 和 text 以便調試
    
    return {"messages": [ai_message], "response": text}