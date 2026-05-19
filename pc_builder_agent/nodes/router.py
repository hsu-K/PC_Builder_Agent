"""
Router Node - 根據需求決定啟動哪些 subAgent

職責：
- 使用 LLM 的語意理解決定要啟動哪些專家
- 備援關鍵字匹配以防 LLM 失敗
- 返回選中的 subAgent 名稱和路由原因
"""

import json
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from pc_builder_agent.nodes.base import build_model, message_text


# 常數定義
AVAILABLE_SPECIALISTS = ["cpu_specialist", "gpu_specialist"]
DEFAULT_ROUTE_TARGETS = ["cpu_specialist", "gpu_specialist"]

CPU_KEYWORDS = (
    "cpu", "處理器", "記憶體", "ram", "文書", "辦公",
    "學習", "程式", "開發", "省電", "靜音", "主機板",
)

GPU_KEYWORDS = (
    "gpu", "顯卡", "顯示卡", "遊戲", "1440p", "4k",
    "光追", "fps", "ai", "剪輯", "繪圖", "渲染",
)


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """判斷文字是否包含任一關鍵字"""
    return any(keyword in text for keyword in keywords)


def _keyword_fallback_route_targets(state: dict) -> tuple[list[str], str]:
    """LLM 路由失敗時的備援規則，基於關鍵字匹配"""
    
    combined_text = "\n".join(
        part for part in [state.get("request", ""), state.get("plan", "")] if part
    ).lower()

    cpu_match = _contains_keyword(combined_text, CPU_KEYWORDS)
    gpu_match = _contains_keyword(combined_text, GPU_KEYWORDS)

    if cpu_match and gpu_match:
        return ["cpu_specialist", "gpu_specialist"], "需求同時涵蓋平台與顯示需求，兩個專家都啟動"

    if gpu_match:
        return ["gpu_specialist"], "需求明確偏向顯卡、遊戲或圖形工作"

    if cpu_match:
        return ["cpu_specialist"], "需求明確偏向處理器、記憶體或整體平台"

    return list(DEFAULT_ROUTE_TARGETS), "語意不明確，使用關鍵字備援後採用預設雙專家"


def _route_targets_for_request(
    state: dict,
    *,
    model_name: str | None = None,
) -> tuple[list[str], str]:
    """使用 LLM 的語意理解決定要啟動哪些 subAgent"""
    
    request = state.get("request", "")
    plan = state.get("plan", "")

    system_prompt = (
        "You are the PC Builder Router. "
        "Decide which specialist nodes to activate based on the user's intent. "
        "Available nodes are only: cpu_specialist, gpu_specialist. "
        "Return JSON only, in this format: "
        '{"targets": ["cpu_specialist"], "reason": "..."}. '
        "The targets field must be a non-empty subset of available nodes. "
        "Write the reason value in Traditional Chinese (zh-TW)."
    )
    user_prompt = (
        "Decide which nodes are needed for the following context.\n\n"
        f"request:\n{request}\n\n"
        f"planner summary:\n{plan}\n"
    )

    try:
        model = build_model(model_name)
        ai_message = model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        raw = message_text(ai_message).strip()

        # 嘗試解析 JSON，若失敗再嘗試擷取最外層 JSON
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            parsed = json.loads(raw[start : end + 1])

        targets = parsed.get("targets", []) if isinstance(parsed, dict) else []
        reason = parsed.get("reason", "") if isinstance(parsed, dict) else ""

        if isinstance(targets, str):
            targets = [targets]
        if not isinstance(targets, list):
            targets = []

        # 過濾非法節點並去重，保持順序
        filtered_targets: list[str] = []
        for target in targets:
            if target in AVAILABLE_SPECIALISTS and target not in filtered_targets:
                filtered_targets.append(target)

        if not filtered_targets:
            return _keyword_fallback_route_targets(state)

        clean_reason = reason.strip() if isinstance(reason, str) else ""
        if not clean_reason:
            clean_reason = "由 LLM 根據需求語意判斷路由"

        return filtered_targets, clean_reason
    except Exception:
        return _keyword_fallback_route_targets(state)


def router_node(state: dict, *, model_name: str | None = None) -> dict[str, Any]:
    """Router Node 的執行函數"""
    
    route_targets, route_reason = _route_targets_for_request(state, model_name=model_name)
    
    return {
        "route_targets": route_targets,
        "route_reason": route_reason,
    }
