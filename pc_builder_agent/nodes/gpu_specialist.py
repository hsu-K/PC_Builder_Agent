"""
GPU Specialist Node - 專注於顯卡、螢幕與電源需求。
"""

from typing import Any

from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.memory import recall_user_preferences
from pc_builder_agent.tools import estimate_psu_wattage, search_component_web


def gpu_specialist_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """GPU Specialist Node 的執行函數"""
    specialist_state = dict(state)

    ai_message, text = run_agent_turn(
        state=specialist_state,
        role_name="GPU specialist",
        system_prompt=(
            "Focus ONLY on GPU (graphics card) component-level analysis, including specs, thermal behavior, display fit, and power requirements.\n"
            "\n"
            "=== SCOPE RESTRICTION (highest priority, strictly enforced) ===\n"
            "You are the GPU specialist. Your output must follow this structure:\n"
            "  GPU: <model> — <analysis>\n"
            "  Summary: <conclusion covering only GPU>\n"
            "  Sources: <URLs>\n"
            "You are FORBIDDEN from outputting any other sections.\n"
            "- Your analysis and output must ONLY include GPU (graphics card). All other components are strictly prohibited.\n"
            "- Do NOT list or discuss: CPU, motherboard, RAM/memory, SSD/storage, PSU, case, cooler, monitor, or any other component.\n"
            "- Even if the article text includes other components, you must ignore them completely — do not mention, list, or number them.\n"
            "- The summary paragraph must only cover GPU; never mention any other component.\n"
            "- Sole exception: you may use estimate_psu_wattage to estimate GPU power draw, but only briefly mention wattage within the GPU analysis — never dedicate a separate section to PSU.\n"
            "- SEARCH RESTRICTION: When calling search_component_web, you MUST ONLY search for GPU/graphics card models. Never search for CPU, motherboard, RAM, storage, cooler, PSU, case, or any other component. Your search queries must be limited to the GPU mentioned in the request or article.\n"
            "\n"
            "If the request mentions gaming, AI, video editing, or creative workloads, prioritize GPU-driven decisions.\n"
            "Use recall_user_preferences to confirm constraints and usage patterns.\n"
            "MANDATORY WEB SEARCH (highest priority):\n"
            "- You MUST call search_component_web at least once before any conclusion or recommendation.\n"
            "- Do not answer from pc_board_response, request text, or memory alone; pc_board_response is only for identifying the GPU model to search.\n"
            "- Even if pc_board_response already lists specs, still search to verify gaming/AI performance, thermals, power, and value from trusted reviews.\n"
            "- Do not output your final answer until search_component_web has returned.\n"
            "- The '資料來源' section must include at least one URL from search_component_web results.\n"
            "Classify the request first:\n"
            "- Direct product inquiry: ignore pc_board_response; take the model name from the user request as the search query.\n"
            "- Article-related inquiry ('文章', '菜單', '這篇', '配置'): read pc_board_response only to find the GPU model, then immediately call search_component_web with that exact model; never stop at repeating the summary. Only extract the GPU model from the article — skip all other components.\n"
            "If the user asks follow-up details, call search_component_web again with refined keywords.\n"
            "Use search results to explain key specs (VRAM, TDP, boost behavior, encoder support), resolution/refresh fit, noise/thermals, and practical pros/cons.\n"
            "When direct product inquiry and pc_board_response conflict, trust web search results over pc_board_response.\n"
            "Call estimate_psu_wattage when needed to validate PSU headroom for the GPU.\n"
            "Only rely on trusted review sources returned by the tool; do not use unsupported assumptions.\n"
            "At the end, provide a '資料來源' section listing the URLs used in your analysis.\n"
            "The final answer must be in Traditional Chinese (zh-TW)."
        ),
        tools=[recall_user_preferences, search_component_web, estimate_psu_wattage],
        model_name=model_name,
        debug=debug,
    )

    return {"messages": [ai_message], "gpu_advice": text}
