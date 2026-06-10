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
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from pc_builder_agent.nodes.base import build_model, message_text

from pc_builder_agent.nodes.ecommerce import ecommerce_node

# ecommerce 回傳的 category 對應到前端 PartsPanel 的 key
# 包含 _CATEGORY_OUTPUT_KEYS 和 _frontend_category() 的所有可能輸出值
_CATEGORY_TO_FRONTEND_KEY: dict[str, str] = {
    # 標準大寫（_CATEGORY_OUTPUT_KEYS / _CATEGORY_LABEL_ZH 的 key）
    "CPU": "cpu",
    "GPU": "gpu",
    "Motherboard": "mb",
    "RAM": "ram",
    "Storage": "ssd",
    "PSU": "psu",
    "Case": "case",
    "Cooler": "cooler",
    # _frontend_category() 輸出的小寫別名
    "cpu": "cpu",
    "gpu": "gpu",
    "motherboard": "mb",
    "memory": "ram",
    "storage": "ssd",
    "psu": "psu",
    "case": "case",
    "cooler": "cooler",
}


def _parse_price_to_int(price_text: str) -> int:
    """將價格字串（如 'NT$32,990'、'12900 元'）解析為整數。"""
    if not price_text:
        return 0
    # 移除 NT$、$、元、逗號等非數字字元，取第一個數字
    nums = re.findall(r"\d+", str(price_text).replace(",", ""))
    return int(nums[0]) if nums else 0


def find_related_goods(good_list: list[str], *, debug: bool = False) -> dict[str, list[dict[str, Any]]]:
    """對每個零件名稱查詢電商，回傳以 frontend key 為 key 的分類結果。

    Returns:
        dict, e.g. {"gpu": [{"name": "RTX 5080", "price": 32990}, ...], "cpu": [...]}
    """
    result_by_frontend_key: dict[str, list[dict[str, Any]]] = {}

    if debug:
        print(f"  [find_related_goods] 準備查詢 {len(good_list)} 個零件：{good_list}")

    for good in good_list:
        state = {"request": f"查{good}的相關產品"}
        result = ecommerce_node(state, model_name="gpt-4.1-mini", debug=False)

        ecommerce_options = result.get("ecommerce_options")
        if debug:
            has_options = bool(ecommerce_options)
            item_count = len(ecommerce_options.get("items", [])) if ecommerce_options else 0
            category = ecommerce_options.get("category", "N/A") if ecommerce_options else "N/A"
            print(f"  [find_related_goods] '{good}' → ecommerce_options={'有' if has_options else '無'}, "
                  f"category={category}, items={item_count}")

        if not ecommerce_options:
            continue

        raw_category = ecommerce_options.get("category", "Other")
        frontend_key = _CATEGORY_TO_FRONTEND_KEY.get(raw_category)
        if not frontend_key:
            if debug:
                print(f"  [find_related_goods] '{good}' → 無法對應 category '{raw_category}' 到前端 key，跳過")
            continue

        if frontend_key not in result_by_frontend_key:
            result_by_frontend_key[frontend_key] = []

        for item in ecommerce_options.get("items", []):
            price_text = item.get("price_text") or f"{item.get('price', 'N/A')} 元"
            result_by_frontend_key[frontend_key].append({
                "name": item.get("name", ""),
                "price": _parse_price_to_int(price_text),
                "price_text": price_text,
                "source": item.get("source", ""),
                "url": item.get("url", ""),
            })

    if debug:
        print(f"  [find_related_goods] 最終回傳 {len(result_by_frontend_key)} 個類別："
              f"{list(result_by_frontend_key.keys())}")

    return result_by_frontend_key

def _build_parser_system_prompt() -> str:
    """組出 component parser 的 system prompt。"""
    return (
        "You extract PC component names from text and output them as JSON.\n"
        "Rules:\n"
        "- Only extract components that have an **explicit, specific model name** in the text.\n"
        "  An explicit model name includes at least a brand/manufacturer + product line or model number.\n"
        "  Examples of VALID extractions:\n"
        "    \"NVIDIA GeForce RTX 5070 Ti\", \"ASUS TUF Gaming RTX 5070 Ti\", "
        "\"AMD Ryzen 7 7800X3D\", \"Seasonic Vertex GX-1000\", "
        "\"Samsung 990 Pro 1TB\", \"be quiet! Dark Rock Pro 5\", \"MSI MAG B850 TOMAHAWK\".\n"
        "  Examples of INVALID extractions (DO NOT extract):\n"
        "    \"650W以上電源供應器\" (generic wattage, no model), "
        "\"良好散熱的機殼與冷卻系統\" (generic description), "
        "\"高速DDR5記憶體\" (generic spec), \"白金牌電源\" (generic tier), "
        "\"需要良好的散熱系統\" (advice, not a product).\n"
        "- Do NOT extract vague recommendations, generic specs, or abstract component descriptions "
        "that lack a concrete brand + product identifier.\n"
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

    component_list = []
    for comp in parsed.get("components", []):
        component_list.append(comp["name"])

    if debug:
        print("【Component Parser】解析結果：")
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
        print(f"【Component Parser】擷取到的零件名稱列表 (共 {len(component_list)} 個)：{component_list}")

    good_list = find_related_goods(component_list, debug=debug)

    if debug:
        print("【Component Parser】相關商品查詢結果：")
        if not good_list:
            print("  (無結果 — good_list 為空 dict)")
        for category, items in good_list.items():
            print(f"  {category}:")
            for item in items:
                print(f"    - {item['name']} ({item['price_text']})")
        print("=" * 60)

    return {
        "parsed_components": parsed,
        "component_options": good_list,
        "messages": [AIMessage(content=json.dumps(parsed, ensure_ascii=False))],
    }
