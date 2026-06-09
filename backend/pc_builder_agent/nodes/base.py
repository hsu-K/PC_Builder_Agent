"""
通用函數和輔助工具，供所有 Node 使用
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
import os
from typing import Any

from pc_builder_agent.tools import TOOL_LOOKUP, PROFILE_TOOLS

MAX_LOOP_LIMIT = 3

def _model_name(model_name: str | None = None) -> str:
    """取得要使用的 OpenAI 模型名稱"""
    return model_name or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def build_model(model_name: str | None = None, temperature=0.2) -> ChatOpenAI | ChatGoogleGenerativeAI:
    """依 model_name 建構 ChatOpenAI 或 ChatGoogleGenerativeAI 模型實例，temperature=0.2 確保回應相對確定"""
    model_name = _model_name(model_name)
    if model_name.startswith("gpt"):
        return ChatOpenAI(model=model_name, temperature=temperature)
    elif model_name.startswith("gemini"):
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )
    else:
        raise ValueError(f"Unknown model: '{model_name}'")


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


# 將preferences, pc_board_results, pc_board_response等都載入
def _state_summary(state: dict) -> str:
    """將 state 中的重要資料整理成可讀摘要，注入給 agent 參考。"""
    preferences = state.get("preferences") or {}
    pc_board_results = state.get("pc_board_results") or []
    pc_board_response = (state.get("pc_board_response") or "").strip()

    preference_lines = [f"- {key}: {value}" for key, value in preferences.items()]
    if not preference_lines:
        preference_lines = ["- 無偏好資料"]

    board_lines = [f"- 已載入文章數量: {len(pc_board_results)}"]
    if pc_board_results:
        for index, article in enumerate(pc_board_results, 1):
            title = article.get("title", "N/A")
            author = article.get("author", "N/A")
            date = article.get("date", "N/A")
            url = article.get("url", "N/A")
            content = article.get("content", "") or "(無內容)"
            comments = article.get("comments", "") or "(無留言)"
            board_lines.append(
                f"- 文章 {index}: {title}\n"
                f"  作者: {author}\n"
                f"  日期: {date}\n"
                f"  連結: {url}\n"
                f"  內文:\n{content}\n"
                f"  留言:\n{comments}"
            )
    if pc_board_response:
        board_lines.append(f"- 最新查詢摘要:\n{pc_board_response[:1500]}")
    else:
        board_lines.append("- 尚無本回合 PC_Board 查詢摘要")

    return (
        "Current state snapshot:\n"
        f"Preferences:\n{chr(10).join(preference_lines)}\n\n"
        f"PC_Board articles:\n{chr(10).join(board_lines)}"
    )


def run_agent_turn(
    *,
    state: dict,
    role_name: str,
    system_prompt: str,
    tools: list[Any],
    model_name: str | None = None,
    debug: bool = False,
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
                f"{_state_summary(state)}\n\n"
                "Always reply in Traditional Chinese (zh-TW).\n\n"
                f"{system_prompt}"
            )
        ),
        *conversation_messages(state),
    ]

    # 工具呼叫迴圈
    max_loop = MAX_LOOP_LIMIT
    while max_loop:
        max_loop -= 1
        ai_message = model.invoke(conversation)

        if debug:
            print(f"\n【{role_name} 回應】")
            print(f"✓ AIMessage 內容:\n{message_text(ai_message)}")
            print(f"✓ 工具呼叫: {ai_message.tool_calls}")
            print("=" * 60)
        
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
            if debug:
                print(f"工具 {tool_name} 執行結果: {result}")
            conversation.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )
        
        if debug:
            print("=" * 60)
