"""
Base Node - 理解需求並整理成可執行的組裝方向

"""

from typing import Any
from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.tools import (
    # 導入所需的工具
)


def base_node(state: dict, *, model_name: str | None = None) -> dict[str, Any]:
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
    
    return {"messages": [ai_message], "plan": text}