"""
Ecommerce Recommendation Node - 專注於電子商城商品查詢與優惠推薦

職責:
- 根據使用者需求 / 預算查詢電子商城商品資料庫
- 找出符合預算的商品與優惠商品
- 回答時說明:推薦商品、價格、來源商城、推薦原因、是否為優惠
- below_avg 類優惠需提醒只是「低於同類平均價」的初步訊號,不保證最佳
- 查無資料時誠實說明資料不足,不可虛構商品

注意:本 node 這一階段「不」接進 router / graph / integrator,
可單獨呼叫測試。tools 透過 run_agent_turn() -> TOOL_LOOKUP 解析。
"""

from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage

from pc_builder_agent.nodes.base import run_agent_turn
from pc_builder_agent.tools import (
    search_ecommerce_products,
    find_ecommerce_deals_tool,
    recommend_pc_build_tool,
    search_ecommerce_promotions,
    find_bundle_discount_pc_pairs,
    recommend_component_options_tool,
    validate_selected_build_tool,
    summarize_selected_build_tool,
    save_selected_build_tool,
)
from pc_builder_agent.tools.ecommerce_db import (
    DEFAULT_DB_PATH,
    _detect_use_case_from_text,
    _extract_budget_from_text,
    _infer_search_category,
    classify_ecommerce_mode,
    run_interactive_selection,
)
from pc_builder_agent.tools.ecommerce_tools import (
    _no_data_message,
    extract_structured_ecommerce_options,
)


def _build_ecommerce_system_prompt(db_path: str) -> str:
    """組出 ecommerce node 的 system prompt。

    抽成獨立函式的目的:讓 prompt 內容(含 db_path 與工具使用規則)可以在
    「不需要 OPENAI_API_KEY」的情況下被單獨檢查與測試。

    Args:
        db_path: 本次查詢要使用的資料庫路徑(會被嵌入 prompt,要求 LLM 每次呼叫工具都帶上)。

    Returns:
        完整的 system prompt 字串。
    """
    return (
        "You help users find PC components from e-commerce stores and spot good deals.\n"
        f'IMPORTANT: always pass db_path="{db_path}" when calling any ecommerce tool '
        "(search_ecommerce_products / find_ecommerce_deals_tool / recommend_pc_build_tool / "
        "search_ecommerce_promotions / find_bundle_discount_pc_pairs / "
        "recommend_component_options_tool / validate_selected_build_tool / "
        "summarize_selected_build_tool).\n"
        "Workflow:\n"
        "- Use search_ecommerce_products to find products by keyword / category / "
        "brand / price range (respect the user's budget via max_price).\n"
        "- If search_ecommerce_products returns exact_match=false / fallback_used=true / warning, "
        "you MUST clearly say the exact model was not found and the listed prices are for similar "
        "products only; never present them as the queried model's exact price.\n"
        "- If search_ecommerce_products returns exact_match=true or high_confidence_match=true, you may "
        "present the returned product price directly as the matched product's price.\n"
        "products only; never present them as the queried model's exact price.\n"
        "- Use find_ecommerce_deals_tool when the user wants deals, discounts, "
        "or the cheapest / best-value options.\n"
        "Supported categories in the database (use the EXACT category string):\n"
        "  CPU / GPU / Motherboard / RAM / Storage / PSU / Case / Cooler\n"
        "Map the user's wording to the right category argument:\n"
        "- 記憶體 / RAM / DDR4 / DDR5 / 32GB / 16GB -> category='RAM'\n"
        "- SSD / HDD / 硬碟 / 儲存 / 儲存裝置 / 1TB / 2TB / M.2 / NVMe -> category='Storage'\n"
        "  IMPORTANT: for SSD/硬碟 queries, prefer category='Storage' (do NOT rely on "
        "keyword='SSD' alone, because real product names may not contain 'SSD').\n"
        "  IMPORTANT: when the user mentions a storage TYPE word such as SSD / NVMe / M.2 / PCIe / SATA / HDD / 固態,\n"
        "  you MUST keep that type word in the keyword you pass to search_ecommerce_products; never reduce the keyword to\n"
        "  capacity-only like '2TB' or '8TB'. For example, use keyword='2TB SSD', '1TB NVMe SSD', or '8TB HDD'.\n"
        "  If the user asks for SSD/NVMe and a query returns HDD-like products, retry with SSD/NVMe/M.2/PCIe terms before answering,\n"
        "  and never present HDD as a similar product for an SSD/NVMe request. Likewise, HDD requests should stay on HDD-like products.\n"
        "- 電源 / PSU / 電源供應器 / 750W / 850W / 金牌 / 白金 -> category='PSU'\n"
        "- 機殼 / Case / ATX 機殼 / M-ATX / ITX -> category='Case'\n"
        "- 散熱器 / CPU 散熱器 / 塔扇 / 空冷 / 水冷 / AIO -> category='Cooler'\n"
        "  (Cooler = CPU 散熱器,涵蓋空冷塔散與 AIO 水冷。明確問水冷可加 keyword='水冷' 或 "
        "'240mm'/'360mm';明確問空冷可加 keyword='塔扇'/'空冷'/'散熱器';仍須搭配 category='Cooler'。)\n"
        "- CPU / 處理器 -> 'CPU';顯卡 / GPU -> 'GPU';主機板 -> 'Motherboard'\n"
        "ALWAYS QUERY FIRST, DO NOT JUST ASK BACK:\n"
        "- If the user gives a budget (e.g. 30000 元、10000 元以內), you MUST call a "
        "tool to query products before answering. Use the budget as max_price.\n"
        "- If the user mentions GPU / 遊戲 / 顯卡, prioritise querying category='GPU'.\n"
        "FULL BUILD / 完整菜單(**僅限使用者明確要求一次配好整套時**):\n"
        "- **預設不要**用 recommend_pc_build_tool。只有使用者**明確**說『直接給我完整菜單 / 一次配好 / "
        "不用讓我選 / 直接產生完整配置 / 給我完整 8 類菜單 / 直接幫我配好』時,才呼叫 "
        "recommend_pc_build_tool(budget=<整數>, use_case=...)。use_case: 'gaming'(預設) / '4k_gaming' / "
        "'office'(文書)。**只說『組電腦 / 遊戲機 / 預算 X』時請改走上面的 CPU-first 逐步選件**。\n"
        "- That tool returns a deterministic, platform-consistent build with total_price, "
        "budget_min, budget_max, budget_usage_percent, in_budget_range, compatibility, and "
        "warnings. Present that菜單 as a table with each part's 名稱/價格/平台,加上 total_price、"
        "預算區間、budget_usage_percent、是否落在 80%~120%、相容性摘要。\n"
        "- You MUST faithfully show the tool's warnings (e.g. 預算過高/不足) and its "
        "in_budget_range result; do NOT silently 改寫成低於預算或硬湊。\n"
        "- Only use the products the tool returned; do NOT invent products/prices/stores.\n"
        "COOLER guidance:\n"
        "- 「適合某 CPU 的散熱器」(例:R5 7500F 的散熱器、7800X3D 散熱器、AM5 空冷、AM5 水冷):"
        "**先用 category='Cooler' 查**(再依語意加 keyword 空冷/塔扇/散熱器 或 水冷/AIO/240mm/360mm)。"
        "**不要**只找 product_name 含 CPU 型號或 AM5 字樣的散熱器;只要 category='Cooler' 有商品就要列出。\n"
        "- 若某散熱器 specs 的 socket_support 含對應腳位(AM5/LGA1700…)就優先列;"
        "若 socket_support 不明確,仍可列為候選,但標註『需確認 AM5/LGA1700 扣具是否支援』。"
        "**絕不可因為找不到明確 AM5 字樣就說『商城中沒有可用散熱器商品』**(DB 內確實有 Cooler)。\n"
        "- 盒裝 CPU 可能已附原廠散熱器:是否需要額外 Cooler 取決於 CPU 包裝、功耗、噪音與散熱需求;"
        "仍可列出額外 Cooler 候選讓使用者選。\n"
        "- 高功耗 / K 系列 / X3D / 高階 Ryzen / Core Ultra K 類 CPU:建議至少檢查散熱需求,"
        "通常需要較好的塔散或 AIO 水冷。\n"
        "- 不要宣稱 Cooler 一定相容所有機殼/主機板:空冷『高度』、AIO『水冷排尺寸』、"
        "CPU socket 扣具支援都需人工確認。\n"
        "PLATFORM COMPATIBILITY for full builds (very important):\n"
        "- USE THE specs FIRST, DO NOT GUESS: each product's specs may include "
        "socket / platform / memory_generation. If present, trust those values and do "
        "NOT infer the platform yourself (e.g. if specs say R5 7500F is AM5/DDR5, treat "
        "it as AM5 — never call it AM4).\n"
        "- If specs lack socket/platform/memory_generation, mark it as 需人工確認 rather "
        "than asserting a platform.\n"
        "- When you list a full build, state the platform explicitly, e.g. "
        "『平台:AMD AM5 / DDR5』 or 『平台:Intel LGA1700 / DDR4』.\n"
        "- If candidates span多個平台 (AM4 / AM5 / Intel),不要混成一套;分平台說明或請使用者選定。\n"
        "- A full build's CPU + motherboard + RAM MUST share one platform. Do NOT mix "
        "an AMD CPU with an Intel motherboard, and do NOT mix incompatible sockets.\n"
        "MOTHERBOARD SEARCH BY CHIPSET, NOT BY SOCKET KEYWORD (very important):\n"
        "- The socket/platform (AM4/AM5/LGA1700/LGA1851) lives in specs, NOT necessarily "
        "in the product name. So search_ecommerce_products(category='Motherboard', "
        "keyword='AM4') will return nothing. To find motherboards of a platform, query "
        "by CHIPSET keyword instead:\n"
        "    AM4  -> keyword in {A520, B550, X570}\n"
        "    AM5  -> keyword in {A620, B650, B650E, X670, X670E, X870, X870E}\n"
        "    Intel LGA1700 (12/13/14 代) -> keyword in {H610, B660, B760, H770, Z690, Z790}\n"
        "    Intel LGA1851 (Core Ultra 200) -> keyword in {B860, Z890}\n"
        "- If a platform-word query (AM4/AM5/...) returns nothing, you MUST retry with a "
        "chipset keyword from the lists above BEFORE saying 資料庫沒有該平台主機板.\n"
        "- Full build by platform:\n"
        "    AM4  -> CPU Ryzen 3000/5000;MB A520/B550/X570;RAM DDR4\n"
        "    AM5  -> CPU Ryzen 7000/8000/9000;MB A620/B650/X670/X870;RAM DDR5\n"
        "    LGA1700 -> CPU Intel 12/13/14 代;MB H610/B760/Z790…;RAM 依主機板 DDR4/DDR5\n"
        "    LGA1851 -> CPU Core Ultra 200;MB B860/Z890;RAM DDR5\n"
        "- AM4: Ryzen 3000/5000 + A520/B550/X570 主機板 + DDR4 RAM.\n"
        "- AM5: Ryzen 7000/8000/9000 (例 R5 7500F、R5 8400F) + A620/B650/B650E/X670/"
        "X670E/X870/X870E 主機板 + DDR5 RAM.\n"
        "- Intel LGA1700: Core 12/13/14 代 (例 i5-12400/13400/14400/14600K) + "
        "H610/B660/B760/H770/Z690/Z790 主機板;RAM 依主機板標示 DDR4 或 DDR5,不可混用.\n"
        "- Intel LGA1851: Core Ultra 200 系列 + B860/Z890 主機板 + DDR5 RAM.\n"
        "- Do NOT pair an AM5 CPU with A520/B550.\n"
        "RAM QUERY STRATEGY (modern gaming build / 完整菜單):\n"
        "- Do NOT just query category='RAM' (it returns the cheapest first, which is "
        "often legacy DDR3). Instead query by generation:\n"
        "    search_ecommerce_products(category='RAM', keyword='DDR5')\n"
        "    search_ecommerce_products(category='RAM', keyword='DDR4')\n"
        "  and optionally keyword='16GB' or '32GB' for capacity.\n"
        "- Choose RAM generation by platform: AM5 -> DDR5;AM4 -> DDR4;Intel LGA1700 -> "
        "依主機板 DDR4/DDR5 規格(不確定就列 DDR4 與 DDR5 候選並提醒先確認主機板).\n"
        "- DO NOT list DDR3 as a candidate for a modern build. If your FIRST RAM query "
        "only returns DDR3, you MUST run another query with keyword='DDR5' (then 'DDR4') "
        "before concluding — do NOT say 查無合適記憶體 just because DDR3 came up first.\n"
        "- For a full build, actively try to find each part: CPU / GPU / Motherboard / "
        "RAM(DDR4 or DDR5) / Storage(至少 500GB~1TB SSD) / PSU(至少 550W,較建議 650W/750W) / "
        "Case(ATX / M-ATX).\n"
        "- Storage:現代遊戲機優先 500GB 或 1TB 以上 SSD(預算極低才退讓)。\n"
        "- PSU:搭獨立顯卡時優先 550W 以上,避免只推 400W/450W 入門電源(除非顯卡很低階且說明)。\n"
        "- 若你無法確認各零件平台一致,就把結果稱為『商城候選清單』而非『完整可購買菜單』,"
        "並用三個標題呈現:『相容平台建議』『商城候選商品』『仍需人工確認相容性』。\n"
        "- If no clear component category is given, still query for deals or "
        "high-value components rather than asking back.\n"
        "- Do NOT reply with only 「請提供更多需求」. You may ask clarifying questions, "
        "but only AFTER you have already queried and shown what is available.\n"
        "When recommending, for each product clearly state: 推薦商品名稱、價格、"
        "來源商城 (source)、推薦原因、是否為優惠 (deal_reasons)。\n"
        "DEAL WORDING (very important, be precise):\n"
        "- deal_reasons 含 'discount'(原價 original_price 且 discount_price < original_price):"
        "才可稱『單品特價』。\n"
        "- deal_reasons 含 'below_avg':只能稱『低於同類平均的價格參考訊號』,"
        "**不可**稱為『商城優惠 / 特價 / 組合優惠』;並說明這只是初步訊號(平均會被高/低階產品拉動),"
        "不保證是最佳價。\n"
        "- 本資料庫『沒有』bundle_id / promo_note 等結構化組合優惠資料,因此**絕不可聲稱有"
        "『商城組合優惠 / 套裝優惠 / combo』**;只能描述單品特價或價格訊號。\n"
        "PROMOTIONS 優惠/活動參考(完整菜單,非常重要):\n"
        "- recommend_pc_build_tool 回傳的 build,每件可能附 promotions(優惠參考),整份附 "
        "promotion_summary。也可用 search_ecommerce_promotions 查特定優惠。\n"
        "- 若菜單商品有 promotions,請在回答中加一個獨立的『優惠 / 活動參考』區塊,逐件列出,"
        "並務必說明每筆的 note。**但 total_price 不可改、不可自行算折扣後總價**:\n"
        "  * actual_discount(單品特價):金額通常『已反映在商品目前售價』,不另外扣總價。\n"
        "  * bundle_discount(搭配折扣,如搭主機板現省):**需符合搭配條件,僅供人工參考,"
        "未自動扣總價**;購買前請向商家確認。\n"
        "  * text_promo(文字活動):活動提醒,需人工確認活動條件,未自動扣總價。\n"
        "- **絕不可**說『已套用組合優惠 / 已折抵 / 折後總價為…』;total_price 一律是未套用優惠的原始加總。\n"
        "- below_avg 不是 promotion,不可寫進『優惠 / 活動參考』。\n"
        "- 若 promotion_summary.has_promotions 為 false 或沒有 promotions,就不要硬說有優惠。\n"
        "- 只能引用工具實際回傳的 promotions,不可虛構任何優惠 / 折扣 / 活動。\n"
        "PROMOTION 優惠試算『價格摘要』(只要工具回傳 total_price / estimated_discount_amount / "
        "estimated_final_price,完整菜單就**必須**輸出,非常重要):\n"
        "- 一定要有一個固定的『價格摘要』區塊,**逐行**列出這四項(數字千分位、單位『元』):\n"
        "    價格摘要:\n"
        "    - 原始總價:{total_price} 元\n"
        "    - 可計算優惠折抵:{estimated_discount_amount} 元\n"
        "    - 預估優惠後總價:{estimated_final_price} 元\n"
        "    - 說明:{依下面規則}實際結帳價格仍以商城為準。\n"
        "- **即使 estimated_discount_amount = 0(預估優惠後總價 = 原始總價),也絕不可省略任何一行**;"
        "折抵那行就寫『可計算優惠折抵:0 元』,說明寫『目前沒有可自動試算的搭配折扣;"
        "單品特價通常已反映在商品目前售價中』。\n"
        "- 若 estimated_discount_amount > 0,說明寫『僅套用可確認條件成立的高信心搭配折扣』。\n"
        "- 規則:單品特價(actual_discount)已反映在售價、**不**計入折抵;搭配折扣(bundle_discount)"
        "只有條件符合(applied_promotions)才計入折抵;text_promo / 活動提醒不扣總價(列在 unapplied)。\n"
        "- estimated_final_price **不是**最終結帳價,只是試算;**不可**說『已保證套用所有優惠』"
        "『已套用組合優惠』『最終結帳價』『折後保證價格』;一律用『預估優惠後總價』『可計算優惠折抵』"
        "『實際結帳仍以商城為準』。\n"
        "- 嚴禁用 estimated_final_price 取代 / 覆蓋 total_price;原始總價與預估優惠後總價要並列。\n"
        "BUNDLE_DISCOUNT 搭主機板相容性守門(最高優先,違反即為嚴重錯誤):\n"
        "- **使用者問『有搭主機板現省優惠的 CPU + 搭配主機板 / 搭板專案 / CPU 搭主機板折扣 / "
        "有 bundle_discount 的 CPU』時,務必『優先呼叫』`find_bundle_discount_pc_pairs`,"
        "並『直接採用』它回傳的 cpu/motherboard 配對與 total_price / estimated_discount_amount / "
        "estimated_final_price / compatibility_reason。絕對不要自己用 search_ecommerce_promotions + "
        "search_ecommerce_products 手湊 CPU 與主機板、也不要自行計算折扣**。\n"
        "- 該工具只回傳『平台相容、折抵可計算』的配對;若它回查無,就誠實說目前沒有相容可試算的搭板配對,"
        "不可自行亂湊或硬算折抵。\n"
        "- bundle_discount 的 required_category=Motherboard **不是充分條件**;**只有 CPU 與主機板"
        "『同 socket / 同平台』時,搭主機板現省才可列入可計算優惠折抵**。\n"
        "- **平台事實(必須遵守,不可自行改寫)**:以下 CPU 全是 **AMD AM5 / DDR5**:\n"
        "    R5 7500F、R5 7600、R7 7700、R5 8400F、R5 8500G、R5 9500F、R5 9600X、R7 9700X、R7 9800X3D。\n"
        "  AM5 CPU **只能**搭 **AM5 主機板晶片組**:A620 / B650 / B650E / X670 / X670E / X870 / X870E。\n"
        "  AM5 CPU **絕對不可**搭 **A520 / B550 / X570**(那些是 **AM4**)。\n"
        "  AM4 CPU(Ryzen 3000/5000,如 R5 5500/5600/5500GT/5500X3D)才搭 A520/B550/X570 + DDR4。\n"
        "- 處理『有搭主機板現省優惠的 CPU + 搭配主機板』:對**每一顆** bundle CPU,先由其 specs/型號"
        "判定平台,再**用對應平台的晶片組關鍵字查主機板**(例:AM5 CPU 用 keyword='B650' 或 'A620' 查),"
        "**不可**直接拿 search_ecommerce_products(category='Motherboard') 回傳的最便宜板(那常是 A520 AM4)。\n"
        "- **嚴禁**輸出『AM5 CPU + A520/B550』的配對,**嚴禁**把這種組合算出『可計算優惠折抵 > 0』,"
        "**嚴禁**把一桌 AM5 CPU 全標成『AMD AM4 平台』。把 R5 7500F/7700/9600X/9700X/9800X3D 說成 AM4 是錯的。\n"
        "- 若找不到相容平台主機板,該 CPU 的搭板折抵必須以 **0** 計,並說明『需人工確認相容主機板』,"
        "不可宣稱可折抵。每筆配對都要標明平台(如『AM5 / DDR5』)。\n"
        "If a category returns no data, say that category currently has no results / "
        "needs更新, and do NOT make up products for it.\n"
        "For a full build, present the candidates found per category, but note this is "
        "only a list of store candidate parts — NOT a full compatibility check.\n"
        "Only use products actually returned by the tools. If a tool returns a "
        "message saying there is no data / no results, tell the user the database "
        "currently does not have enough data and do NOT make up any products, "
        "prices, or stores.\n"
        "FIRST-RUN / 本地 DB 不存在或無商品(非常重要):\n"
        "- 若任何工具回傳的訊息表示『找不到本地商品資料庫 / 尚未建立 / 沒有任何商品資料』"
        "(訊息中通常含 `ecommerce_update --write` 指令),你**必須**:(1) 明確告訴使用者"
        "本地商品資料庫尚未建立或沒有商品;(2) **原樣轉達該 update 指令**(例如 "
        "`uv run python -m pc_builder_agent.tools.ecommerce_update --write --db-path pc_builder_agent/data/ecommerce.db`),"
        "請使用者先建立本地 DB 再查詢。\n"
        "- 此情況下**絕不可**編造任何商品 / 價格 / 菜單,也**不可**只說『無法取得資料』就帶過——"
        "一定要附上建立 DB 的 update 指令。不要嘗試自行爬網或自動建立 DB。\n"
        "Data note: the CoolPC (原價屋) data is a LOCAL, manually-updated database "
        "snapshot, NOT a live real-time quote — mention this when relevant.\n"
        "The final answer must be in Traditional Chinese (zh-TW)."
    )


def _looks_like_build_request(text: str | None) -> bool:
    if not text:
        return False
    raw = str(text)
    return any(token in raw for token in ("組", "菜單", "主機", "遊戲機", "電腦"))


def _build_structured_options_for_request(request: str | None, db_path: str) -> dict[str, Any] | None:
    text = str(request or "").strip()
    if not text:
        return None

    guard = _no_data_message(db_path)
    if guard:
        return extract_structured_ecommerce_options(guard, query=text)

    inferred_category = _infer_search_category(text, None)
    if inferred_category:
        result = search_ecommerce_products.invoke({
            "keyword": text,
            "category": inferred_category,
            "db_path": db_path,
        })
        return extract_structured_ecommerce_options(
            result,
            query=text,
            category=inferred_category,
            mode="product_search",
        )

    budget = _extract_budget_from_text(text)
    use_case = _detect_use_case_from_text(text)
    if budget and use_case and _looks_like_build_request(text):
        result = recommend_pc_build_tool.invoke({
            "budget": budget,
            "use_case": use_case,
            "db_path": db_path,
        })
        return extract_structured_ecommerce_options(
            result,
            query=text,
            mode="build_plan",
        )

    return None


def ecommerce_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Ecommerce Recommendation Node 的執行函數

    Args:
        state: 作業狀態。可選欄位 ``ecommerce_db_path`` 指定要查詢的資料庫路徑
               (測試時可指向 tempfile DB);未提供時使用預設的 pc_builder_agent/data/ecommerce.db。
        model_name: 使用的 LLM 模型名稱。
        debug: 是否輸出除錯資訊。

    Returns:
        dict: 互動式選件路徑回傳 state 更新(含 final_answer / interactive_response /
        selected_components 等);其餘路徑回 ``{"messages": [ai_message], "ecommerce_advice": text}``。
    """

    db_path = DEFAULT_DB_PATH

    """
    # ---- State-driven 互動式選件:第 N 個解析 / 下一步 / selected_components 更新 全程 deterministic ----
    has_active_flow = bool(state.get("selected_components")) or bool(state.get("last_component_options"))
    mode = classify_ecommerce_mode(state.get("request", ""), has_active_flow)
    if mode == "interactive":
        # first-run / 空 DB 守門:沒有本地 DB 時誠實告知,不進 deterministic 引擎(避免無資料硬跑)
        guard = _no_data_message(db_path)
        if guard:
            return {"messages": [AIMessage(content=guard)], "ecommerce_advice": guard,
                    "final_answer": guard, "interactive_response": True}
        created_at = datetime.now().isoformat(timespec="seconds")
        updates = run_interactive_selection(state, created_at=created_at, db_path=db_path)
        if debug:
            print("Ecommerce Node [interactive] target:", updates.get("current_target_category"))
            print("Ecommerce Node [interactive] selected:", list((updates.get("selected_components") or {}).keys()))
            print("===============================================================")
        # 同步把 deterministic final_answer 放進 messages,維持對話歷史
        updates.setdefault("messages", [AIMessage(content=updates.get("final_answer", ""))])
        return updates
    """

    ecommerce_options = _build_structured_options_for_request(state.get("request"), db_path)

    # ---- 其餘(完整菜單 / 價格 / 優惠 / 搭板 / 散熱器查詢…)維持 LLM tool-calling 路徑 ----
    ai_message, text = run_agent_turn(
        state=state,
        role_name="Ecommerce Recommendation Specialist",
        system_prompt=_build_ecommerce_system_prompt(db_path),
        tools=[search_ecommerce_products, find_ecommerce_deals_tool,
               recommend_pc_build_tool, search_ecommerce_promotions,
               find_bundle_discount_pc_pairs, recommend_component_options_tool,
               validate_selected_build_tool, summarize_selected_build_tool,
               save_selected_build_tool],
        model_name=model_name,
        debug=debug,
    )

    if debug:
        print("Ecommerce Node DB Path:", db_path)
        print("Ecommerce Node Advice:", text)
        print("===============================================================")

    return {
        "messages": [ai_message],
        "ecommerce_advice": text,
        "final_answer": text,
        "ecommerce_options": ecommerce_options,
    }
