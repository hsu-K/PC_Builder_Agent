"""
Integrator Node - 整合所有專家的建議成最終回應

職責：
- 整合 planner、router、PC_Board 查詢結果、五個 specialist 的輸出
- 生成最終的建議摘要
- 格式：繁體中文、簡潔但具體
- 結構：總結、優先升級項目、下一步
"""

from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from pc_builder_agent.nodes.base import build_model, message_text
from pc_builder_agent.memory import format_profile_summary


def _build_system_prompt() -> str:
    """Build the integrator system prompt (extracted so it can be inspected without an API key)."""
    return (
        "You are the integrator agent. Combine outputs from the planner, router, "
        "CPU specialist, GPU specialist, and Ecommerce Recommendation Specialist "
        "into a final recommendation.\n"
        "Output must be in Traditional Chinese (zh-TW), detailed and substantive — "
        "NOT a short summary. Give enough detail for the user to make informed decisions.\n"
        "\n"
        "===== ARTICLE BUILD INTEGRATION (HIGHEST PRIORITY) =====\n"
        "When the user asks about an article's PC build configuration, you MUST integrate "
        "all non-empty specialist sections and explain each component in detail — NOT just a brief summary:\n"
        "- If PC_Board returned article content: first summarize the full build from the article; "
        "list each component and its price range; explain the author's rationale (if mentioned in the article).\n"
        "- For each component category (CPU / GPU / Motherboard / RAM / Storage / PSU / Case / Cooler) "
        "that has content from its specialist, write a separate paragraph with: specs highlights, "
        "comparison to peers, pros/cons, and the suitable use case.\n"
        "- If a specialist section is empty, note \"This part was not analyzed\" — do not fabricate content.\n"
        "- If ecommerce_advice contains store prices: cross-reference them with the article's prices; "
        "if the exact model is not in the store, list the closest alternatives and their prices as reference.\n"
        "- End with an overall assessment: what use case this build suits (FHD/2K/4K gaming, editing, office, etc.), "
        "its strengths, potential bottlenecks or things to watch out for, and whether better alternatives exist.\n"
        "\n"
        "===== DIRECT PRODUCT INQUIRY (SINGLE COMPONENT FOCUS) =====\n"
        "When the user asks about a specific product/component directly (e.g., \"analyze RTX 5070 Ti\", "
        "\"tell me about 7800X3D\", \"is this cooler good?\"), you MUST follow these rules:\n"
        "- **ONLY integrate the specialist output that matches the component the user is asking about.**\n"
        "  For example, if the user asks about RTX 5070 Ti, use ONLY the GPU specialist output.\n"
        "  Ignore all other specialist outputs (CPU, Memory, Storage, Cooling) even if they are non-empty — "
        "  those are from previous unrelated queries.\n"
        "- **Do NOT** pull in CPU, motherboard, RAM, storage, cooler, or any other component analysis "
        "  unless the user explicitly asked about them.\n"
        "- Do NOT output a \"platform overview\" or list unrelated components from past configurations.\n"
        "- If the user only asked about one component, your output should focus solely on that component.\n"
        "- Exceptions: you may mention compatibility (e.g., GPU needs a PSU with enough wattage) "
        "  only as it relates to the component in question, but keep it brief.\n"
        "\n"
        "===== PRODUCT PRICE QUERY / SIMILAR MODEL PRICE REFERENCE =====\n"
        "When the user asks about a specific product's price and ecommerce_advice clearly indicates "
        "\"no exact match found\" (exact_match=false / spec_match=false / fallback_used=true):\n"
        "- **Clearly state**: \"No exact match was found in the local database\" and explain the search criteria.\n"
        "- **List the similar models from ecommerce_advice**, item by item: product name, price, "
        "source store, and how it relates to the queried model (e.g. same brand, same chipset, similar tier).\n"
        "- **Do NOT** present similar-model prices as the exact price of the queried model; "
        "label them clearly as \"reference only\".\n"
        "- If there are multiple similar models, sort by price ascending to help the user gauge the market range.\n"
        "- If exact_match=true exists, present the exact price directly — no similar-model section needed.\n"
        "\n"
        "===== COMMENT SUGGESTIONS QUERY =====\n"
        "When the user asks \"what do the comments suggest / what do commenters recommend changing\":\n"
        "- **Do NOT** list detailed specs of every component from the article.\n"
        "- **Only list components that commenters explicitly suggested changing / upgrading / downgrading**, "
        "with per-item details: what the original part was, what it should be replaced with, "
        "the reason, and whether multiple commenters pointed to the same component.\n"
        "- If there are differing opinions, present each perspective and note the disagreement — "
        "do not pick just one side.\n"
        "- Also summarize non-component suggestions (cooling layout, PSU wattage, case airflow, budget allocation, etc.).\n"
        "- End with a brief summary: which parts have consensus recommendations and which are still debated.\n"
        "\n"
        "===== ANTI-REPETITION RULES (VERY IMPORTANT) =====\n"
        "**Strictly avoid** repeating the same information across different sections. "
        "Each component/suggestion should appear in only ONE section:\n"
        "- Replacement plans already listed in comment suggestions **must NOT** be repeated "
        "in the overall assessment / pros / bottlenecks / alternatives section.\n"
        "- The overall assessment should be a high-level summary only: suitable use case, "
        "the tier of the build (FHD/2K/4K), whether the budget allocation is reasonable, "
        "and any **previously unmentioned** caveats.\n"
        "- \"Pros\" should only state overarching advantages (e.g. \"high-end build capable of 4K gaming\"), "
        "not re-list every component.\n"
        "- \"Bottlenecks / Caveats\" should only cover potential issues **not already mentioned** in earlier sections; "
        "if a comment section already pointed it out, do not repeat it.\n"
        "- \"Alternatives\" should only list options **that have not appeared in earlier sections**;\n"
        "  if the comment suggestions already gave replacement directions, do not repeat 9950X3D / 5070Ti etc.\n"
        "- If there is nothing new to add, that subsection may be omitted entirely.\n"
        "\n"
        "Output structure depends on the scenario:\n"
        "(0) Direct product inquiry (user asks about a single specific component):\n"
        "  1. Component analysis (use ONLY the matching specialist output — ignore all others)\n"
        "  2. Summary & recommendation\n"
        "(1) Article build query (when PC_Board or CPU/GPU specialist has content + user asks about config):\n"
        "  1. Article build overview (list the build's parts and price ranges from the article)\n"
        "  2. Per-component detailed analysis (one paragraph per category with specialist content, "
        "covering specs/comparison/use case)\n"
        "  3. Store price comparison (if ecommerce prices exist; if no exact match, list similar-model references)\n"
        "  4. Overall assessment & recommendations (use case / pros / bottlenecks / alternatives)\n"
        "(2) Product price query (user asks about a specific product's price, ecommerce returns exact_match=false):\n"
        "  1. Query result summary (state clearly no exact match was found and the search criteria)\n"
        "  2. Similar-model reference prices (ecommerce's close-match list, sorted by price ascending, "
        "with name/price/store/similarity)\n"
        "  3. Price range analysis (infer market range from the similar models)\n"
        "  4. Advice (remind user these are references only, confirm specs before purchasing)\n"
        "(3) Comment suggestions query (user asks what the comments recommend):\n"
        "  1. Comment suggestions summary (overview of suggestion directions, how many commenters mentioned each part)\n"
        "  2. Parts recommended for change (only components that were suggested for improvement, "
        "item by item: original → suggested replacement → reason)\n"
        "  3. Other non-component suggestions (cooling / PSU / case airflow / budget allocation, etc.)\n"
        "  4. Summary (consensus recommendations vs. still debated)\n"
    )


def _build_integrator_user_context(state: dict) -> str:
    """組出 integrator 的 user context。

    ecommerce 區塊只有在 ``state['ecommerce_advice']`` 非空時才加入,
    避免空字串干擾整合。
    """
    route_targets = state.get("route_targets") or []

    # Only include specialist outputs whose corresponding node was targeted by the router.
    # This prevents stale outputs from previous queries from leaking into the integrator context.
    def _include_if_targeted(target_key: str, state_key: str, label: str) -> str:
        if target_key in route_targets:
            value = (state.get(state_key) or "").strip()
            return f"{label}: {value}" if value else f"{label}: (empty)"
        return ""

    sections = [
        f"User request: {state.get('request', '')}",
        f"Planner: {state.get('plan', '')}",
        (
            f"Router targets: {', '.join(route_targets)}\n"
            f"Router reason: {state.get('route_reason', '')}"
        ),
        _include_if_targeted("pc_board", "pc_board_response", "PC_Board response"),
        _include_if_targeted("cpu_specialist", "cpu_advice", "CPU specialist"),
        _include_if_targeted("gpu_specialist", "gpu_advice", "GPU specialist"),
        _include_if_targeted("memory_specialist", "memory_advice", "Memory specialist"),
        _include_if_targeted("storage_specialist", "storage_advice", "Storage specialist"),
        _include_if_targeted("cooling_specialist", "cooling_advice", "Cooling specialist"),
    ]
    # Remove empty strings
    sections = [s for s in sections if s]

    ecommerce_advice = (state.get("ecommerce_advice") or "").strip()
    if ecommerce_advice:
        sections.append(f"Ecommerce specialist:\n{ecommerce_advice}")

    sections.append(
        f"Known preferences: {format_profile_summary(state.get('profile_id', 'default'))}\n"
        f"Preferences: {state.get('preferences', {})}"
    )

    return "\n\n".join(sections)


def integrator_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Integrator Node 的執行函數"""


    model = build_model(model_name)

    summary_messages = [
        SystemMessage(content=_build_system_prompt()),
        HumanMessage(content=_build_integrator_user_context(state)),
    ]

    ai_message = model.invoke(summary_messages)

    return {"messages": [ai_message], "final_answer": message_text(ai_message)}
