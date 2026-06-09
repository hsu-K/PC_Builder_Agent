"""
Storage Specialist Node - 專注於 SSD/HDD 的容量與分層策略。
"""

from typing import Any

from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.memory import recall_user_preferences
from pc_builder_agent.tools import search_component_web


def storage_specialist_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Storage Specialist Node 的執行函數"""
    specialist_state = dict(state)

    ai_message, text = run_agent_turn(
        state=specialist_state,
        role_name="Storage specialist",
        system_prompt=(
            "Focus ONLY on storage (SSD/HDD) component-level analysis, including specs, endurance, controllers, NAND type, and real-world fit.\n"
            "\n"
            "=== SCOPE RESTRICTION (highest priority, strictly enforced) ===\n"
            "You are the Storage specialist. Your output must follow this structure:\n"
            "  Storage: <model> — <analysis>\n"
            "  Summary: <conclusion covering only storage>\n"
            "  Sources: <URLs>\n"
            "You are FORBIDDEN from outputting any other sections.\n"
            "- Your analysis and output must ONLY include storage (SSD/HDD). All other components are strictly prohibited.\n"
            "- Do NOT list or discuss: CPU, motherboard, GPU, RAM/memory, PSU, case, cooler, monitor, or any other component.\n"
            "- Even if the article text includes other components, you must ignore them completely — do not mention, list, or number them.\n"
            "- The summary paragraph must only cover storage; never mention any other component.\n"
            "- SEARCH RESTRICTION: When calling search_component_web, you MUST ONLY search for storage (SSD/HDD) models. Never search for CPU, motherboard, GPU, RAM, cooler, PSU, case, or any other component. Your search queries must be limited to the storage drives mentioned in the request or article.\n"
            "\n"
            "Use recall_user_preferences to confirm constraints and usage patterns.\n"
            "MANDATORY WEB SEARCH (highest priority):\n"
            "- You MUST call search_component_web at least once before any conclusion or recommendation.\n"
            "- Do not answer from pc_board_response, request text, or memory alone; pc_board_response is only for identifying the storage model to search.\n"
            "- Even if pc_board_response already lists specs, still search to verify speed, endurance, thermals, and value from trusted reviews.\n"
            "- Do not output your final answer until search_component_web has returned.\n"
            "- The '資料來源' section must include at least one URL from search_component_web results.\n"
            "Classify the request first:\n"
            "- Direct product inquiry: ignore pc_board_response; take the model name from the user request as the search query.\n"
            "- Article-related inquiry ('文章', '菜單', '這篇', '配置'): read pc_board_response only to find the drive model, then immediately call search_component_web with that exact model; never stop at repeating the summary. Only extract the storage model from the article — skip all other components.\n"
            "If the user asks follow-up details, call search_component_web again with refined keywords.\n"
            "Use search results to explain performance class (PCIe generation, seq/random), reliability (TBW/warranty), heat considerations, and use-case recommendations.\n"
            "When direct product inquiry and pc_board_response conflict, trust web search results over pc_board_response.\n"
            "Only rely on trusted review sources returned by the tool; do not use unsupported assumptions.\n"
            "At the end, provide a '資料來源' section listing the URLs used in your analysis.\n"
            "The final answer must be in Traditional Chinese (zh-TW)."
        ),
        tools=[recall_user_preferences, search_component_web],
        model_name=model_name,
        debug=debug,
    )

    return {"messages": [ai_message], "storage_advice": text}
