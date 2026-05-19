"""
通用函數和輔助工具，供所有 Node 使用
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
import os
from typing import Any

from pc_builder_agent.tools import TOOL_LOOKUP, PROFILE_TOOLS


def _model_name(model_name: str | None = None) -> str:
    """取得要使用的 OpenAI 模型名稱"""
    return model_name or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def build_model(model_name: str | None = None) -> ChatOpenAI:
    """建構 ChatOpenAI 模型實例，temperature=0.2 確保回應相對確定"""
    return ChatOpenAI(model=_model_name(model_name), temperature=0.2)


def message_text(message: BaseMessage) -> str:
    """從 BaseMessage 物件中提取文字內容"""
    if isinstance(message.content, str):
        return message.content
    return "\n".join(str(part) for part in message.content)


def conversation_messages(state: dict) -> list[BaseMessage]:
    """從狀態中取得對話訊息列表"""
    messages = list(state.get("messages", []))
    if not messages and state.get("request"):
        messages.append(HumanMessage(content=state["request"]))
    return messages


def run_agent_turn(
    *,
    state: dict,
    role_name: str,
    system_prompt: str,
    tools: list[Any],
    model_name: str | None = None,
) -> tuple[AIMessage, str]:
    """
    執行一個 Agent 的對話輪次
    
    流程：
    1. 建構模型並綁定工具
    2. 組建對話歷史（系統提示 + 對話歷史）
    3. 進入工具呼叫迴圈直到 LLM 無需呼叫工具為止
    4. 返回最終的 AIMessage 和文字內容
    """
    model = build_model(model_name).bind_tools(tools)
    
    # 動態導入以避免循環導入
    from pc_builder_agent.memory import format_profile_summary
    
    conversation = [
        SystemMessage(
            content=(
                f"You are {role_name}.\n"
                f"Session ID: {state.get('profile_id', 'default')}\n"
                f"Known memory summary:\n{format_profile_summary(state.get('profile_id', 'default'))}\n\n"
                "Always reply in Traditional Chinese (zh-TW).\n\n"
                f"{system_prompt}"
            )
        ),
        *conversation_messages(state),
    ]

    # 工具呼叫迴圈
    while True:
        ai_message = model.invoke(conversation)
        conversation.append(ai_message)

        if not ai_message.tool_calls:
            return ai_message, message_text(ai_message)

        for tool_call in ai_message.tool_calls:
            tool_name = tool_call["name"]
            tool = TOOL_LOOKUP[tool_name]
            args = dict(tool_call.get("args") or {})

            # 若是 profile 相關工具，自動添加 profile_id
            if tool_name in PROFILE_TOOLS and "profile_id" not in args:
                args["profile_id"] = state.get("profile_id", "default")

            result = tool.invoke(args)
            conversation.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )
