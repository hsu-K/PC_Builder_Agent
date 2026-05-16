"""
LangGraph Agent 工作流程模組

這個模組定義了完整的 PC Builder Agent 系統架構，包含：

1. 狀態管理 (BuildState)
   - 儲存使用者需求、對話歷史、各 agent 的分析結果

2. 四個 Agent 節點
   - planner: 理解需求，查詢/保存使用者偏好
   - cpu_specialist: CPU、記憶體、主機板建議
   - gpu_specialist: 顯卡、螢幕、散熱建議
   - integrator: 整合所有建議成最終回應

3. 執行流程
   - planner 先執行 → cpu_specialist 和 gpu_specialist 並行執行 → integrator 最後整合

4. 記憶和工具
   - 使用記憶工具保存用戶偏好，跨越多輪對話保持上下文
   - 工具包括：recall_user_preferences、save_user_preference、estimate_psu_wattage
"""

from __future__ import annotations

import os
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from pc_builder_agent.memory import (
    MEMORY_TOOLS,
    PROFILE_STORE,
    estimate_psu_wattage,
    format_profile_summary,
    recall_user_preferences,
    save_user_preference,
)


# ============================================================================
# 狀態定義
# ============================================================================

class BuildState(TypedDict, total=False):
    """
    LangGraph 狀態管理 - 整個工作流程中流動的數據結構
    
    Attributes:
        profile_id (str): 使用者 ID，用於查詢和保存偏好設定
        request (str): 使用者最新的 PC 組裝需求
        messages (Annotated[list[BaseMessage]]): 完整的對話歷史
            - 包含所有 HumanMessage (使用者輸入) 和 AIMessage (agent 回應)
            - 自動使用 add_messages 功能進行合併，避免重複
        plan (str): planner agent 的分析結果
        cpu_advice (str): CPU specialist 的建議
        gpu_advice (str): GPU specialist 的建議
        final_answer (str): integrator 整合後的最終建議
    """
    profile_id: str
    request: str
    messages: Annotated[list[BaseMessage], add_messages]
    plan: str
    cpu_advice: str
    gpu_advice: str
    final_answer: str


# ============================================================================
# 常數和輔助函數
# ============================================================================

# Profile 相關的工具集 - 用於查詢和保存使用者偏好
PROFILE_TOOLS = {"recall_user_preferences", "save_user_preference"}

# 建立工具查詢表 - 方便根據工具名稱快速查找工具物件
TOOL_LOOKUP = {tool.name: tool for tool in MEMORY_TOOLS}


def _model_name(model_name: str | None = None) -> str:
    """
    取得要使用的 OpenAI 模型名稱
    
    優先順序：
    1. 明確傳入的 model_name
    2. 環境變數 OPENAI_MODEL
    3. 預設值 "gpt-4.1-mini"
    
    Args:
        model_name: 要使用的模型名稱
    
    Returns:
        str: 最終使用的模型名稱
    """
    return model_name or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def _build_model(model_name: str | None = None) -> ChatOpenAI:
    """
    建構 ChatOpenAI 模型實例
    
    Args:
        model_name: OpenAI 模型名稱
    
    Returns:
        ChatOpenAI: 已設置 temperature=0.2 的模型 (相對確定的回應)
    """
    return ChatOpenAI(model=_model_name(model_name), temperature=0.2)


def _message_text(message: BaseMessage) -> str:
    """
    從 BaseMessage 物件中提取文字內容
    
    Args:
        message: LangChain BaseMessage 物件
    
    Returns:
        str: 訊息的文字內容
    """
    if isinstance(message.content, str):
        return message.content
    return "\n".join(str(part) for part in message.content)


def _conversation_messages(state: BuildState) -> list[BaseMessage]:
    """
    從狀態中取得對話訊息列表
    
    主要用於構建傳送給 LLM 的對話歷史。
    
    Args:
        state: BuildState 狀態物件
    
    Returns:
        list[BaseMessage]: 對話訊息列表
    """
    messages = list(state.get("messages", []))
    if not messages and state.get("request"):
        # 如果沒有訊息歷史但有新的 request，則建立初始訊息
        messages.append(HumanMessage(content=state["request"]))
    return messages


def _run_agent_turn(
    *,
    state: BuildState,
    role_name: str,
    system_prompt: str,
    tools: list[Any],
    model_name: str | None = None,
) -> tuple[AIMessage, str]:
    """
    執行一個 Agent 的對話輪次
    
    這是整個 agent 執行的核心邏輯。流程說明：
    
    1. 建構模型並綁定工具
    2. 組建完整的對話歷史，包含：
       - 系統提示 (定義 agent 的角色和行為)
       - 使用者對話歷史
    3. 進入工具呼叫迴圈：
       - 呼叫 LLM 取得回應
       - 如果回應包含工具呼叫，則執行工具
       - 將工具結果反饋給 LLM，讓它繼續對話
       - 重複直到 LLM 無需呼叫工具為止
    4. 返回最終的 AIMessage 和文字內容
    
    Args:
        state: BuildState 狀態物件
        role_name: Agent 的角色名稱 (例如 "planner agent")
        system_prompt: 系統提示，定義該 agent 的職責
        tools: 該 agent 可用的工具列表
        model_name: 使用的 OpenAI 模型
    
    Returns:
        tuple[AIMessage, str]: (LLM 的最終訊息, 訊息文字內容)
    """
    # 建構模型並綁定可用的工具
    model = _build_model(model_name).bind_tools(tools)
    
    # 組建對話歷史
    conversation = [
        SystemMessage(
            content=(
                f"你是 {role_name}。\n"
                f"session id: {state.get('profile_id', 'default')}\n"
                f"已知記憶摘要:\n{format_profile_summary(state.get('profile_id', 'default'))}\n\n"
                f"{system_prompt}"
            )
        ),
        *_conversation_messages(state),
    ]

    # 工具呼叫迴圈 - 直到 LLM 無需呼叫工具為止
    while True:
        # 呼叫 LLM
        ai_message = model.invoke(conversation)
        conversation.append(ai_message)

        # 如果 LLM 沒有呼叫工具，則返回最終訊息
        if not ai_message.tool_calls:
            return ai_message, _message_text(ai_message)

        # 執行所有工具呼叫
        for tool_call in ai_message.tool_calls:
            tool_name = tool_call["name"]
            tool = TOOL_LOOKUP[tool_name]
            args = dict(tool_call.get("args") or {})

            # 如果是 profile 相關工具，自動添加 profile_id 引數
            if tool_name in PROFILE_TOOLS and "profile_id" not in args:
                args["profile_id"] = state.get("profile_id", "default")

            # 執行工具並將結果反饋給 LLM
            result = tool.invoke(args)
            conversation.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )


# ============================================================================
# Agent 節點定義
# ============================================================================

def planner_node(state: BuildState, *, model_name: str | None = None) -> dict[str, Any]:
    """
    Planner Agent 節點
    
    職責：
    - 理解使用者的 PC 組裝需求
    - 調用 recall_user_preferences 查詢既有偏好
    - 如果使用者明確提到預算、用途、噪音等限制，則調用 save_user_preference 儲存
    - 可視需要調用 estimate_psu_wattage 估算電源需求
    - 輸出簡潔的需求分類和優先順序
    
    Args:
        state: BuildState 狀態物件
        model_name: 使用的 OpenAI 模型
    
    Returns:
        dict: 包含 messages 和 plan 的結果字典
    """
    ai_message, text = _run_agent_turn(
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


def cpu_specialist_node(state: BuildState, *, model_name: str | None = None) -> dict[str, Any]:
    """
    CPU 專家 Agent 節點
    
    職責：
    - 專注 CPU、記憶體、主機板 和整體平台平衡
    - 從記憶中確認用途和偏好，並作為決策參考
    - 可調用 estimate_psu_wattage 協助判斷電源餘裕
    - 提供一段可直接採用的建議
    
    Args:
        state: BuildState 狀態物件
        model_name: 使用的 OpenAI 模型
    
    Returns:
        dict: 包含 messages 和 cpu_advice 的結果字典
    """
    ai_message, text = _run_agent_turn(
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


def gpu_specialist_node(state: BuildState, *, model_name: str | None = None) -> dict[str, Any]:
    """
    GPU 專家 Agent 節點
    
    職責：
    - 專注顯卡、螢幕解析度、散熱與電源需求
    - 如果使用者提到遊戲、AI、剪輯或繪圖，優先對應 GPU 需求
    - 可調用 estimate_psu_wattage 協助判斷電源需求
    - 清楚說明顯卡選型方向
    
    Args:
        state: BuildState 狀態物件
        model_name: 使用的 OpenAI 模型
    
    Returns:
        dict: 包含 messages 和 gpu_advice 的結果字典
    """
    ai_message, text = _run_agent_turn(
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


def integrator_node(state: BuildState, *, model_name: str | None = None) -> dict[str, Any]:
    """
    整合器 Agent 節點
    
    職責：
    - 整合 planner、CPU specialist、GPU specialist 的輸出
    - 生成最終的建議摘要
    - 格式：繁體中文、簡潔但具體、分成：總結、優先升級項目、下一步
    
    Args:
        state: BuildState 狀態物件
        model_name: 使用的 OpenAI 模型
    
    Returns:
        dict: 包含 messages 和 final_answer 的結果字典
    """
    model = _build_model(model_name)
    summary_messages = [
        SystemMessage(
            content=(
                "你是總結 agent，負責把 planner、CPU specialist、GPU specialist 的輸出整合成最終建議。\n"
                "輸出格式請用繁體中文，簡潔但具體，分成：總結、優先升級項目、下一步。"
            )
        ),
        HumanMessage(
            content=(
                f"使用者需求：{state.get('request', '')}\n\n"
                f"Planner: {state.get('plan', '')}\n\n"
                f"CPU specialist: {state.get('cpu_advice', '')}\n\n"
                f"GPU specialist: {state.get('gpu_advice', '')}\n\n"
                f"既有偏好：{format_profile_summary(state.get('profile_id', 'default'))}"
            )
        ),
    ]
    ai_message = model.invoke(summary_messages)
    return {"messages": [ai_message], "final_answer": _message_text(ai_message)}


# ============================================================================
# 工作流程圖構建
# ============================================================================

def build_graph(model_name: str | None = None):
    """
    建構完整的 LangGraph 工作流程
    
    執行流程圖：
    
    START
      ↓
    planner (理解需求，查詢/保存偏好)
      ↓
    ┌─────────────────────────┐
    ↓                         ↓
  cpu_specialist        gpu_specialist (並行執行)
    ↓                         ↓
    └─────────────────────────┘
      ↓
    integrator (整合所有建議)
      ↓
    END
    
    Args:
        model_name: 使用的 OpenAI 模型名稱
    
    Returns:
        CompiledStateGraph: 已編譯的工作流程圖，可直接呼叫 invoke() 執行
    """
    # 建立 StateGraph，使用 BuildState 作為狀態管理
    graph = StateGraph(BuildState)

    # 添加所有節點 - 每個節點都是一個 agent
    graph.add_node("planner", lambda state: planner_node(state, model_name=model_name))
    graph.add_node("cpu_specialist", lambda state: cpu_specialist_node(state, model_name=model_name))
    graph.add_node("gpu_specialist", lambda state: gpu_specialist_node(state, model_name=model_name))
    graph.add_node("integrator", lambda state: integrator_node(state, model_name=model_name))

    # 定義邊（流程連接）
    # START → planner
    graph.add_edge(START, "planner")
    
    # planner → cpu_specialist
    graph.add_edge("planner", "cpu_specialist")
    # planner → gpu_specialist
    graph.add_edge("planner", "gpu_specialist")
    
    # [cpu_specialist, gpu_specialist] → integrator (兩個都完成後才進行下一步)
    graph.add_edge(["cpu_specialist", "gpu_specialist"], "integrator")
    
    # integrator → END
    graph.add_edge("integrator", END)

    # 編譯工作流程圖
    # - checkpointer: 用於保存檢查點 (對話歷史等)
    # - store: 用於保存 profile 和其他持久化數據
    # - name: 工作流程的名稱
    return graph.compile(
        checkpointer=InMemorySaver(),
        store=PROFILE_STORE,
        name="pc-builder-agent-gpt",
    )


def planner_node(state: BuildState, *, model_name: str | None = None) -> dict[str, Any]:
    ai_message, text = _run_agent_turn(
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


def cpu_specialist_node(state: BuildState, *, model_name: str | None = None) -> dict[str, Any]:
    ai_message, text = _run_agent_turn(
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


def gpu_specialist_node(state: BuildState, *, model_name: str | None = None) -> dict[str, Any]:
    ai_message, text = _run_agent_turn(
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


def integrator_node(state: BuildState, *, model_name: str | None = None) -> dict[str, Any]:
    model = _build_model(model_name)
    summary_messages = [
        SystemMessage(
            content=(
                "你是總結 agent，負責把 planner、CPU specialist、GPU specialist 的輸出整合成最終建議。\n"
                "輸出格式請用繁體中文，簡潔但具體，分成：總結、優先升級項目、下一步。"
            )
        ),
        HumanMessage(
            content=(
                f"使用者需求：{state.get('request', '')}\n\n"
                f"Planner: {state.get('plan', '')}\n\n"
                f"CPU specialist: {state.get('cpu_advice', '')}\n\n"
                f"GPU specialist: {state.get('gpu_advice', '')}\n\n"
                f"既有偏好：{format_profile_summary(state.get('profile_id', 'default'))}"
            )
        ),
    ]
    ai_message = model.invoke(summary_messages)
    return {"messages": [ai_message], "final_answer": _message_text(ai_message)}


def build_graph(model_name: str | None = None):
    graph = StateGraph(BuildState)

    graph.add_node("planner", lambda state: planner_node(state, model_name=model_name))
    graph.add_node("cpu_specialist", lambda state: cpu_specialist_node(state, model_name=model_name))
    graph.add_node("gpu_specialist", lambda state: gpu_specialist_node(state, model_name=model_name))
    graph.add_node("integrator", lambda state: integrator_node(state, model_name=model_name))

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "cpu_specialist")
    graph.add_edge("planner", "gpu_specialist")
    graph.add_edge(["cpu_specialist", "gpu_specialist"], "integrator")
    graph.add_edge("integrator", END)

    return graph.compile(
        checkpointer=InMemorySaver(),
        store=PROFILE_STORE,
        name="pc-builder-agent-gpt",
    )