"""
Component Parser Node - 解析 Integrator 的最終回答，擷取其中提到的零件名稱並以 JSON 格式輸出

職責：
- 讀取 state 中的 final_answer（integrator 產出的最終建議文字）
- 透過 LLM 解析文字中提到的 PC 零件名稱
- 以結構化 JSON 輸出擷取到的零件清單

輸出存放在 state["parsed_components"] 中，格式範例：
{
  "components": [
    {"name": "Ryzen 9 9900X3D", "category": "CPU", "mention_context": "留言建議升級" },
    {"name": "RTX 5080", "category": "GPU", "mention_context": "文章原始配置" }
  ],
  "summary": "共解析出 2 個零件"
}
"""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from pc_builder_agent.nodes.base import build_model, message_text


def _build_parser_system_prompt() -> str:
    """組出 component parser 的 system prompt。"""
    return (
        "You extract PC component names from text and output them as JSON.\n"
        "Rules:\n"
        "- Only extract components that are **explicitly named** in the text.\n"
        "- Do NOT infer or add components that are not directly mentioned.\n"
        "- For each extracted component, output: name, category "
        "(CPU/GPU/Motherboard/RAM/Storage/PSU/Case/Cooler/Other), "
        "and a brief mention_context.\n"
        "- If the same component appears multiple times, include it only once.\n"
        "- If no components are found, return "
        '{"components": [], "summary": "未解析到任何零件"}.\n'
        "\n"
        "Respond with ONLY valid JSON. Structure:\n"
        '{"components": [{"name": "...", "category": "...", '
        '"mention_context": "..."}], "summary": "..."}'
    )


def component_parser_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Component Parser Node 的執行函數

    從 state['final_answer'] 中解析出零件名稱，以 JSON 結構存入 state['parsed_components']。

    Args:
        state: 作業狀態，須包含 final_answer 欄位。
        model_name: 使用的 LLM 模型名稱。
        debug: 是否輸出除錯資訊。

    Returns:
        dict: 包含 parsed_components（dict）與 messages（list[AIMessage]）的更新。
    """

    final_answer = (state.get("final_answer") or "").strip()
    if not final_answer:
        if debug:
            print("【Component Parser】final_answer 為空，跳過解析")
        return {
            "parsed_components": {"components": [], "summary": "無 final_answer 可解析"},
        }

    model = build_model(model_name)

    messages = [
        SystemMessage(content=_build_parser_system_prompt()),
        HumanMessage(content=f"請解析以下文字中的 PC 零件：\n\n{final_answer}"),
    ]

    ai_message = model.invoke(messages)
    raw = message_text(ai_message).strip()

    # 嘗試從 LLM 回覆中提取 JSON（可能被 markdown 包圍）
    if raw.startswith("```"):
        # 移除 ```json ... ``` 標記
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            raw = raw[start : end + 1]

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # 若 LLM 回傳非合法 JSON，嘗試補救：包成統一的錯誤格式
        if debug:
            print("【Component Parser】LLM 回傳非 JSON，原始內容：", raw)
        parsed = {
            "components": [],
            "summary": f"解析失敗，LLM 原始回覆：{raw[:200]}",
        }

    if debug:
        print("【Component Parser】解析結果：")
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
        print("=" * 60)

    return {
        "parsed_components": parsed,
        "messages": [AIMessage(content=json.dumps(parsed, ensure_ascii=False))],
    }
