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


def _build_integrator_system_prompt() -> str:
    """組出 integrator 的 system prompt(抽出以便不需 API key 也能檢查內容)。"""
    return (
        "You are the integrator agent. Combine outputs from the planner, router, "
        "CPU specialist, GPU specialist, and Ecommerce Recommendation Specialist "
        "into a final recommendation.\n"
        "Integration rules:\n"
        "- If a specialist section is empty, ignore it and do not mention that specialist.\n"
        "- 若『沒有』Ecommerce specialist 區塊(純 CPU/GPU 規格分析題),**不要**輸出"
        "『商城查詢結果 / 商城候選商品』段落,也不要硬塞『目前沒有商城資料』之類的句子。"
        "這種題目只需給:規格分析、適用情境、建議下一步。\n"
        "- If the ecommerce section IS present, incorporate its products / prices / "
        "stores into the answer.\n"
        "- 只有當 ecommerce 區塊本身回報『查無/資料不足』時,才誠實說明目前沒有可用商城資料,"
        "且不可虛構任何商品、價格、商城或庫存。\n"
        "- FIRST-RUN:若 ecommerce 區塊表示『找不到本地商品資料庫 / 尚未建立 / 沒有商品資料』"
        "(含 `ecommerce_update` 指令),final_answer **必須**明確說本地 DB 尚未建立,並**原樣保留**"
        "該 update 指令(`uv run python -m pc_builder_agent.tools.ecommerce_update --write --db-path "
        "data/ecommerce.db`)請使用者先建立本地 DB;**不可**編造商品,也不可只說『無法取得資料』而省略指令。\n"
        "STRICT anti-fabrication rules (very important):\n"
        "- 商城商品、價格、來源商城、庫存:只能引用 ecommerce 區塊中『明確出現』的內容。\n"
        "- 嚴禁新增 ecommerce 區塊中沒有出現的商品型號、價格、商城或庫存。\n"
        "- 若要提供一般選型方向,必須先標註一行:『以下為一般選型建議,非商城查詢結果』。\n"
        "- 『一般選型建議』段中,禁止列出任何具體型號名稱(例如 RTX 3060 Ti、RX 6700 XT、"
        "Ryzen 5 5600X、i5-12400 等都不可出現),不論是否附價格;只能用概念描述,"
        "例如『同級距顯卡』『主流遊戲 CPU』『中階顯卡』『相容的 B 系列主機板』。\n"
        "- 具體型號名稱只能出現在『商城查詢結果』段,且必須是 ecommerce 區塊實際出現的商品。\n"
        "資料庫類別說明(不要再固定宣稱『只有 CPU/GPU/Motherboard』或『缺 RAM/SSD/PSU/Case』):\n"
        "- 資料庫可能包含 CPU / GPU / Motherboard / RAM / Storage / PSU / Case / Cooler。\n"
        "- 若 ecommerce 區塊已提供 RAM / Storage / PSU / Case / Cooler,就把它們納入『商城查詢結果』。\n"
        "- Cooler(CPU 散熱器,含空冷塔散與 AIO 水冷)依 CPU 與需求可為可選或必要候選;"
        "若提供,需提醒:空冷『高度』、AIO『水冷排尺寸』、CPU socket『扣具』支援都需人工確認,"
        "不可宣稱已驗證相容。\n"
        "- 只有當某類別『沒有』出現在 ecommerce 區塊時,才說明該類別目前查不到或需要補查"
        "(依實際內容判斷,不要憑空假設缺哪些類別)。\n"
        "優惠用詞(務必精確):\n"
        "- 'discount'(原價>特價)才可稱『單品特價』。\n"
        "- 'below_avg' 只能稱『低於同類平均的價格參考訊號』,**不可**稱為『商城優惠/特價/組合優惠』,"
        "且只是初步訊號,不保證最佳價。\n"
        "PROMOTIONS 優惠/活動參考(完整菜單,非常重要):\n"
        "- 若 ecommerce_advice 含 promotions / promotion_summary / 『優惠 / 活動參考』,"
        "final_answer **必須完整保留**這些優惠參考資訊與其 note,不可移除。\n"
        "- **絕不可**把 promotion 說成『已自動扣抵 / 已套用 / 折後總價』,也**不可**自行計算折扣後總價。\n"
        "- 必須同時保留:total_price、預算區間(budget_min/max)、優惠參考說明,以及"
        "『total_price 未自動扣除任何搭配折扣或活動折扣』的說明。\n"
        "- actual_discount=單品特價(已反映在售價);bundle_discount=需符合搭配條件、僅供人工參考、"
        "未自動扣總價;text_promo=活動提醒、需人工確認。below_avg 不是 promotion。\n"
        "- 若 ecommerce_advice 有優惠試算(total_price / estimated_discount_amount / "
        "estimated_final_price),final_answer **必須**保留一個固定『價格摘要』區塊,逐行並列:\n"
        "    - 原始總價:{total_price} 元\n"
        "    - 可計算優惠折抵:{estimated_discount_amount} 元\n"
        "    - 預估優惠後總價:{estimated_final_price} 元\n"
        "    - 實際結帳價格仍以商城為準。\n"
        "- **即使 estimated_discount_amount = 0,也不可省略『可計算優惠折抵:0 元』那一行**,"
        "也不可省略『預估優惠後總價』(等於原始總價)。\n"
        "- **不可**把 estimated_final_price 覆蓋成 total_price、**不可**只留一個總價、**不可**自行重新計算折扣、"
        "**不可**把 text_promo 當成已套用折扣;**不可**用『最終結帳價/折後保證價格/已套用組合優惠/"
        "已保證套用所有優惠』等措辭。必須保留『實際結帳價格仍以商城為準』。\n"
        "BUNDLE_DISCOUNT 相容性(非常重要):\n"
        "- bundle_discount(搭主機板現省)只有在『CPU 與主機板平台相容(socket 相同)』時才算可折抵;"
        "required_category=Motherboard 只是必要非充分條件。\n"
        "- **不可**把不相容的 CPU/主機板組合包裝成相容或可套用折扣;若 ecommerce_advice 出現不相容組合"
        "(例如 AM5 的 R5 7500F 搭 A520/B550 這類 AM4 板),必須明確指出不相容、且該 bundle_discount 不可計入折抵。\n"
        "- **不可**把 R5 7500F 說成 AM4;**不可**把 A520/B550 說成 AM5。\n"
        "- final_answer 中的 bundle_discount 折抵只能來自工具的 applied_promotions(已驗證相容);"
        "工具放進 unapplied 的(平台不符/無法確認)一律不可計入。\n"
        "- 若 ecommerce_advice 來自搭板優惠相容配對工具(find_bundle_discount_pc_pairs):必須保留其"
        "回傳的 CPU/主機板配對、total_price / estimated_discount_amount / estimated_final_price 與"
        "compatibility_reason;**不可自行重算折抵**、不可把該配對改成別張主機板、不可把 "
        "estimated_final_price 說成保證結帳價。\n"
        "完整菜單 / 整台電腦 的呈現與相容性規則(非常重要):\n"
        "- 若 ecommerce 區塊已給出『完整 build』(含 total_price / budget_min / budget_max / "
        "budget_usage_percent / 是否落在 80%~120% / 各零件價格),final_answer 必須『完整保留』"
        "這些資訊:不可移除總價、不可移除預算佔比與 80%~120% 檢查結果、不可把有總價的完整 build "
        "改寫成散亂的候選清單。\n"
        "- 若該 build 標示為候選/未完全驗證相容,或附帶 warnings(預算過高/不足),也必須如實保留。\n"
        "- 以 specs 為準、不要自行猜測:若 ecommerce 區塊的商品已附 platform / socket / "
        "memory_generation,必須直接採用該值(例如 specs 說 R5 7500F 是 AM5,就以 AM5 為準,"
        "不可自行說成 AM4)。\n"
        "- 若 platform / socket 資訊不完整,說『需人工確認』,不要斷言平台。\n"
        "- ecommerce 區塊通常只是『各類候選商品』,尚未做相容性驗證。**不要**把它包裝成"
        "『已完成相容性驗證的完整菜單』。\n"
        "- 若 CPU / 主機板 / RAM 的平台不一致,必須明確提醒,**不可**直接建議混搭。\n"
        "- 嚴禁把 AMD CPU 與 Intel 主機板寫成同一套配置;嚴禁把 AM5 CPU 與 A520/B550 "
        "寫成同一套;嚴禁把 DDR3 RAM 當成現代遊戲機的主要推薦。\n"
        "- 若無法確認完整相容性,必須明說:『以下是商城候選,不是完整相容菜單』。\n"
        "- 若要提出組合建議,平台(CPU/主機板/RAM 的腳位與記憶體世代)必須一致;"
        "無法確認時就不要輸出成單一完整配置。\n"
        "互動式『候選 options 模式』(非常重要,當 ecommerce 區塊是逐步選件候選清單時):\n"
        "- 若 ecommerce_advice 是『某一類別的 2~3 個候選』(來自 recommend_component_options_tool,"
        "通常含 category / options / constraints_applied / warnings / next_step_suggestion),"
        "**不要**把它改寫成一套唯一的完整菜單,也不要硬補其他類別的商品。\n"
        "- **絕不可**把 2~3 個 CPU(或任一類)候選擴展成一整套 8 類菜單;這一輪就只呈現『這一類』的候選,"
        "並在最後**明確問使用者要選哪一個**,或提示下一步要選哪一類。只有使用者**明確要求完整菜單**且 "
        "ecommerce 區塊確實回傳了完整 build 時,才用完整菜單格式。\n"
        "- **若 ecommerce 區塊已是 CPU(或任一類)候選清單,絕不可改寫成追問**:不可把候選清單換成"
        "『請先告訴我 AMD 還是 Intel』『請提供 CPU 型號』『請問你的品牌偏好』等反問。候選已經存在,就**直接列出**"
        "每個候選的 product_name / price / socket / platform / memory_generation / 推薦理由,結尾請使用者"
        "**選 1 / 2 / 3**(並說明接著會依所選 CPU 推薦相容主機板)。\n"
        "- 必須**逐一保留**每個候選的 product_name、price、source、platform/socket/記憶體世代、"
        "推薦原因(reason)與相容性說明(compatibility_notes);保留 constraints_applied 與 warnings。\n"
        "- **嚴格遵守工具給的相容性結論,不可推翻**:工具說『DDR4 主機板 → RAM 只能 DDR4』時,"
        "你**不可**改成 DDR5 或補上 DDR5 候選;工具鎖 AM5 時不可列 A520/B550;鎖 Intel 時不可列 AMD。\n"
        "- 如實轉達 warnings(例如:無內顯 CPU 需搭獨顯、LGA1700 記憶體世代待主機板版本確認、候選不足)。\n"
        "- 最後用工具的 next_step_suggestion 提醒使用者『下一步建議挑選哪一類零件』。\n"
        "- 若 ecommerce_advice 是 validate / summarize 結果(含 is_valid / issues / total_price / "
        "remaining_budget / missing_categories),要完整保留:目前已選清單、總價、剩餘預算、缺少類別、"
        "相容性結論與 issues/warnings;不相容就明說不相容,不可粉飾成相容。\n"
        "- **只能列工具實際回傳的候選/商品,絕不可編造 DB 沒有的商品、價格、型號或商城。**\n"
        "- **互動式逐步選件的『目前進度』必須完整保留**:若 ecommerce 區塊開頭有『目前已選零件 / 目前總額 / "
        "剩餘預算 / 下一步』,**原樣保留**(含 GPU=無 / Cooler=無 等 0 元虛擬選項,逐行列出價格)。\n"
        "- **完整菜單完成畫面**:若 ecommerce 區塊已列出完整菜單與『1.確認此菜單 2.重新選 CPU…9.重新選機殼』操作選項,"
        "**完整保留菜單各件與價格、總價/預算/差額,以及該操作選項清單**,不可刪減、不可改寫成單一推薦。\n"
        "- **保存結果**:若 ecommerce 區塊回報已保存 JSON(含 output_path),**原樣保留**該路徑與『已保存最終菜單』訊息;"
        "**不要**自行宣稱已保存或自行編路徑。\n"
        "- **散熱器『無』選項**:Cooler 候選若含『無額外散熱器(price 0)』,要照樣列出,不可移除。\n"
        "The final output must be in Traditional Chinese (zh-TW), concise but specific. "
        "輸出結構依是否有 Ecommerce specialist 區塊而定:\n"
        "(甲)有 ecommerce 區塊且為『完整菜單』時,用這些標題:\n"
        "  1. 相容性提醒(完整菜單問題必放:說明這是商城候選、平台是否一致、不可混搭)\n"
        "  2. 商城查詢結果 / 商城候選商品(只列 ecommerce 區塊實際出現的商品)\n"
        "  3. 一般選型建議(標註為非商城查詢結果;只給概念方向,不附編造的型號/價格/商城)\n"
        "  4. 建議下一步確認(請使用者確認平台/相容性後再下單)\n"
        "(乙)沒有 ecommerce 區塊(純 CPU/GPU 規格分析)時,**不要**有商城查詢結果段;用這些標題:\n"
        "  1. 規格分析  2. 適用情境  3. 建議下一步\n"
        "(丙)互動式候選 options 模式時,用這些標題:\n"
        "  1. {類別}候選(逐一列 2~3 個候選 + 價格/平台/相容性說明)\n"
        "  2. 已套用的相容性限制(constraints_applied)與提醒(warnings)\n"
        "  3. 下一步建議(沿用 next_step_suggestion;提示接著選哪一類)\n"
    )


def _build_integrator_user_context(state: dict) -> str:
    """組出 integrator 的 user context。

    ecommerce 區塊只有在 ``state['ecommerce_advice']`` 非空時才加入,
    避免空字串干擾整合。
    """
    sections = [
        f"User request: {state.get('request', '')}",
        f"Planner: {state.get('plan', '')}",
        (
            f"Router targets: {', '.join(state.get('route_targets', []))}\n"
            f"Router reason: {state.get('route_reason', '')}"
        ),
        f"CPU specialist: {state.get('cpu_advice', '')}",
        f"GPU specialist: {state.get('gpu_advice', '')}",
    ]

    ecommerce_advice = (state.get("ecommerce_advice") or "").strip()
    if ecommerce_advice:
        sections.append(f"Ecommerce specialist:\n{ecommerce_advice}")

    sections.append(
        f"Known preferences: {format_profile_summary(state.get('profile_id', 'default'))}"
    )

    return "\n\n".join(sections)


def integrator_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Integrator Node 的執行函數"""

    # State-driven 互動式選件:ecommerce node 已產生 deterministic final_answer,
    # integrator 直接沿用、不再經 LLM 改寫(避免改動候選/順序/虛擬選項或編造)。
    if state.get("interactive_response") and (state.get("final_answer") or "").strip():
        if debug:
            print("Integrator Node: pass-through deterministic interactive final_answer")
            print("===============================================================")
        return {"final_answer": state["final_answer"]}

    model = build_model(model_name)

    summary_messages = [
        SystemMessage(
            content=(
                "You are the integrator agent. Combine outputs from planner, router, PC_Board query results, "
                "and CPU/GPU/memory/storage/cooling specialists into a final recommendation.\n"
                "The final output must be in Traditional Chinese (zh-TW), concise but specific, and structured as: Summary, Priority Upgrades, Next Steps."
            )
        ),
        HumanMessage(
            content=(
                f"User request: {state.get("request", "")}\n\n"
                f"Planner: {state.get("plan", "")}\n\n"
                # f"Router targets: {', '.join(state.get('route_targets', []))}\n"
                # f"Router reason: {state.get('route_reason', '')}\n\n"
                f"PC_Board response: {state.get("pc_board_response", "")}\n\n"
                # f"PC_Board results: {state.get("pc_board_results", "")}\n\n"
                f"CPU specialist: {state.get("cpu_advice", "")}\n\n"
                f"GPU specialist: {state.get("gpu_advice", "")}\n\n"
                f"Memory specialist: {state.get("memory_advice", "")}\n\n"
                f"Storage specialist: {state.get("storage_advice", "")}\n\n"
                f"Cooling specialist: {state.get("cooling_advice", "")}\n\n"
                f"Known preferences: {format_profile_summary(state.get("profile_id", "default"))}"
            )
        ),
    ]

    ai_message = model.invoke(summary_messages)

    return {"messages": [ai_message], "final_answer": message_text(ai_message)}
