"""
Router Node - 根據需求決定啟動哪些 subAgent

職責：
- 使用 LLM 的語意理解決定要啟動哪些專家
- 備援關鍵字匹配以防 LLM 失敗
- 支持路由到 pc_board_scraper 進行文章查詢
- 返回選中的 subAgent 名稱和路由原因
"""

import json
import re
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage
from pc_builder_agent.nodes.base import build_model, message_text


# 常數定義
# 注意:route target 名稱需與 graph.py 的 add_node 名稱一致(ecommerce 節點名為 "ecommerce")
AVAILABLE_SPECIALISTS = ["cpu_specialist", "gpu_specialist", "pc_board_scraper", "ecommerce"]
DEFAULT_ROUTE_TARGETS = ["cpu_specialist", "gpu_specialist"]

CPU_KEYWORDS = (
    "cpu", "處理器", "記憶體", "ram", "文書", "辦公",
    "學習", "程式", "開發", "省電", "靜音", "主機板",
)

GPU_KEYWORDS = (
    "gpu", "顯卡", "顯示卡", "遊戲", "1440p", "4k",
    "光追", "fps", "剪輯", "繪圖", "渲染",
)
# 「AI」單獨成詞才算 GPU 意圖(避免裸子字串 "ai" 誤中 "aio"/"fail" 等);
# 前後不接英文字母,故 "aio" 不中、"AI繪圖"/"玩 AI" 仍中。
_GPU_AI_RE = re.compile(r"(?<![a-z])ai(?![a-z])")

# 舊的廣義 PC_Board 關鍵字(含「推薦/有什麼/介紹」等泛用詞)。
# 依 Phase 4B 規格保留不大幅移除,避免破壞既有引用;但 fallback 路由「不再」用它做判斷,
# 改用下方更精確的 PC_BOARD_DISCUSSION_KEYWORDS,以免泛用詞把選型/商城問題誤導到 pc_board。
PC_BOARD_KEYWORDS = (
    "文章", "菜單", "推薦", "ptt", "分享", "討論", "社群",
    "之前", "爬取", "查看", "看看", "告訴我", "有什麼", "介紹",
)

# 明確的 PTT / 社群 / 菜單討論詞(刻意比 PC_BOARD_KEYWORDS 窄,不含泛用詞),
# fallback 只在命中這些詞時才把 pc_board_scraper 納入 targets。
# 注意:刻意「不放」裸「菜單」—— 「菜單」常指完整 build(屬 ecommerce 完整菜單),
# pc_board 只在明確的社群來源詞(PTT/電蝦/網友/文章/社群/討論…)出現時才觸發。
PC_BOARD_DISCUSSION_KEYWORDS = (
    "ptt", "電蝦", "網友", "文章", "討論", "社群", "分享", "配單", "最近討論",
)

# 明確的電子商城 / 價格 / 優惠商業意圖詞。
# 刻意不放入「推薦/有什麼/介紹」等泛用詞,避免把一般問題誤導到 ecommerce。
# 補充:除規格要求清單外另加入「預算」,以涵蓋「預算 10000 以內」這種非連續寫法
# (規格清單中的「預算內」在這種寫法下不會連續出現)。
ECOMMERCE_KEYWORDS = (
    "優惠", "特價", "折扣", "促銷", "便宜", "比價", "價格", "報價",
    "多少錢", "預算內", "預算", "缺貨", "庫存", "現貨", "商城",
    "原價屋", "欣亞", "pchome", "momo", "購買", "下單",
    # Cooler / 散熱器商品查詢(散熱器/水冷/空冷/塔扇/AIO 屬 ecommerce 可查商品)
    "散熱器", "cpu散熱器", "cooler", "空冷", "塔扇", "雙塔", "水冷", "aio",
    # 完整 build / 整機 / 菜單 意圖(由 recommend_pc_build_tool 處理,屬 ecommerce)
    "配一台", "組一台", "組電腦", "組機", "整機", "遊戲機", "文書機", "辦公機",
    "工作機", "菜單", "完整菜單", "電腦菜單",
)

# 互動式逐步選件意圖詞(由 recommend_component_options_tool 處理,屬 ecommerce)。
# 刻意搭配「選件意圖」或「零組件+世代/平台」,避免只因泛用詞(如「推薦」)就誤導到 ecommerce。
# 注意:文字會先 .lower(),故英文一律小寫;中文不受影響。
INTERACTIVE_SELECTION_KEYWORDS = (
    # 選件/候選意圖
    "候選", "選項", "幾個", "幾款", "逐步", "一個一個", "先給我", "先看", "先選",
    "下一步", "我選", "選第", "接下來",
    # 自己挑零件 / CPU-first 起手意圖(預設互動式逐步選件)
    "挑零件", "選零件", "自己挑", "自己選", "從cpu開始", "cpu開始", "從 cpu 開始",
    # 重新選單項 / 確認保存意圖(完整菜單完成後的操作)
    "重新選", "重選", "太貴", "換顯示卡", "換顯卡", "換cpu", "換主機板", "換記憶體",
    "確認此菜單", "確認菜單", "確認這套", "就這套", "保存", "存成json", "存成 json",
    "存檔", "存起來", "存成檔", "輸出json", "輸出 json",
    # 「第 N 個 / 第 N 張」常見寫法(另有 _NTH_RE 處理任意 N 與空白)
    "第1個", "第2個", "第3個", "第1張", "第2張", "第3張",
    # 候選請求常見組合詞
    "cpu候選", "主機板候選", "記憶體候選", "ram候選", "相容主機板", "相容記憶體",
    "ddr4 主機板", "ddr5 主機板", "ddr4主機板", "ddr5主機板",
    "ddr4 平台", "ddr5 平台", "ddr4平台", "ddr5平台",
    # 換平台 / 記憶體世代意圖
    "ddr4", "ddr5",
)

# 「第 N 個 / 第 N 張」(任意數字、可含空白)與「換 平台/世代」意圖,用 regex 補捉。
_NTH_SELECT_RE = re.compile(r"第\s*\d+\s*[個张張顆隻支]")
_SWITCH_PLATFORM_RE = re.compile(r"換\s*(am5|am4|intel|amd|ddr4|ddr5|lga1700|lga1851)")
# 品牌選用意圖(組機/選件情境):『(想/要/用/選) AMD/Intel』或『AMD…Intel…都可以』。
# 用於互動式 CPU-first 起手的品牌指定;純規格比較(無此措辭)不會命中。
_BRAND_INTENT_RE = re.compile(
    r"(想|要|用|選|指定)\s*(amd|intel)|(amd[^a-z]{0,6}intel|intel[^a-z]{0,6}amd)[^a-z]{0,4}都")


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """判斷文字是否包含任一關鍵字"""
    return any(keyword in text for keyword in keywords)


def _keyword_fallback_route_targets(state: dict) -> tuple[list[str], str]:
    """LLM 路由失敗時的備援規則，基於關鍵字匹配。

    採「加總式」判斷:依各類別關鍵字命中與否,把對應 target 累加起來,
    讓 ecommerce 能與 cpu/gpu/pc_board 共存(例如「30000 元菜單,也看商城優惠」)。

    注意(graph.py 採方案 C 的已知限制):
    若回傳的 targets 含 "pc_board_scraper",graph 的 _dispatch_specialists 會短路,
    只執行 pc_board_scraper 並接 END,其餘 target(含 ecommerce)在本 MVP 不會被執行。
    """

    combined_text = "\n".join(
        part for part in [state.get("request", ""), state.get("plan", "")] if part
    ).lower()

    pc_board_match = _contains_keyword(combined_text, PC_BOARD_DISCUSSION_KEYWORDS)
    interactive_match = (
        _contains_keyword(combined_text, INTERACTIVE_SELECTION_KEYWORDS)
        or bool(_NTH_SELECT_RE.search(combined_text))
        or bool(_SWITCH_PLATFORM_RE.search(combined_text))
        or bool(_BRAND_INTENT_RE.search(combined_text))
    )
    ecommerce_match = _contains_keyword(combined_text, ECOMMERCE_KEYWORDS) or interactive_match
    cpu_match = _contains_keyword(combined_text, CPU_KEYWORDS)
    gpu_match = _contains_keyword(combined_text, GPU_KEYWORDS) or bool(_GPU_AI_RE.search(combined_text))

    targets: list[str] = []
    reason_parts: list[str] = []

    if pc_board_match:
        targets.append("pc_board_scraper")
        reason_parts.append("偵測到 PTT/社群/菜單討論詞")
    if ecommerce_match:
        targets.append("ecommerce")
        if interactive_match:
            reason_parts.append("偵測到互動式逐步選件意圖(候選/選項/第N個/換平台/相容零件)")
        else:
            reason_parts.append("偵測到商城/價格/優惠等商業意圖詞")
    if gpu_match:
        targets.append("gpu_specialist")
        reason_parts.append("偵測到顯卡/遊戲/圖形需求")
    if cpu_match:
        targets.append("cpu_specialist")
        reason_parts.append("偵測到處理器/記憶體/平台需求")

    # 去重並保持加入順序
    deduped: list[str] = []
    for target in targets:
        if target not in deduped:
            deduped.append(target)

    if not deduped:
        return list(DEFAULT_ROUTE_TARGETS), "語意不明確，使用關鍵字備援後採用預設雙專家"

    return deduped, "；".join(reason_parts)


def _route_targets_for_request(
    state: dict,
    *,
    model_name: str | None = None,
) -> tuple[list[str], str]:
    """使用 LLM 的語意理解決定要啟動哪些 subAgent"""

    request = state.get("request", "")
    plan = state.get("plan", "")

    # Deterministic 前置路由(互動式逐步選件):選件動作(第 N 個 / 無 / 重新選 / 確認保存 /
    # 從 CPU 開始 / 候選 等)一律直接導向 ecommerce,不經 LLM,避免選件中途被誤路由到 specialist
    # 而漏掉 state 更新(Phase Interactive-State-Driven-Fix)。
    try:
        from pc_builder_agent.tools.ecommerce_db import is_interactive_selection_request
        if is_interactive_selection_request(request):
            return ["ecommerce"], "偵測到互動式逐步選件動作,deterministic 直接導向 ecommerce"
    except Exception:
        pass

    system_prompt = (
        "You are the PC Builder Router. "
        "Decide which specialist nodes to activate based on the user's intent. "
        "Available nodes and their responsibilities:\n"
        "- cpu_specialist: CPU 選型、CPU 規格、處理器效能與相容性建議。\n"
        "- gpu_specialist: GPU 選型、遊戲/AI/繪圖用途、顯卡效能與相容性建議。\n"
        "- pc_board_scraper: PTT / 社群菜單討論、近期菜單分享、網友配單與文章查詢。\n"
        "- ecommerce: 電子商城商品、價格、優惠、特價、比價、庫存,"
        "以及原價屋/欣亞/PChome/momo 等商城查詢;**並且**負責『互動式逐步零組件候選推薦』"
        "(針對某一類零件給 2~3 個資料庫實品候選,並做相容性過濾)。\n"
        "Selection guidance:\n"
        "INTERACTIVE COMPONENT SELECTION(互動式逐步選件 — 非常重要):\n"
        "- ecommerce 不只負責價格/優惠/完整菜單;它也負責『互動式逐步零組件候選推薦』"
        "(由 recommend_component_options_tool 提供 DB 實品候選 + 相容性過濾)。\n"
        "- 當使用者要求『候選 / 選項 / 幾個選擇 / 第 N 個 / 逐步選 / 一個一個選 / 先看某一類零件 / "
        "先選 CPU / 下一步選主機板 / 換 AM5 / 換 Intel / 指定 DDR4 或 DDR5 主機板 / 相容主機板 / "
        "相容記憶體』時,**必須包含 ecommerce**(例:『給我 CPU 候選』『給我幾張主機板選擇』"
        "『我選第 2 個,接下來給我主機板』『我想用 AM5 平台,先給我 CPU 候選』"
        "『我想用 LGA1700 DDR5 主機板,給我 RAM 候選』)。\n"
        "- **預設組機=互動式逐步選件**:使用者給預算想『組電腦 / 遊戲機 / 文書機 / 主機 / 組一台』"
        "(例:『我預算 30000 要組遊戲機』『我想自己挑零件』『幫我從 CPU 開始推薦』),**必須包含 "
        "ecommerce**(由它走 CPU-first 逐步選件)。指定品牌(『我想用 AMD』『我想用 Intel』"
        "『AMD、Intel 都可以』)同樣**必須包含 ecommerce**。這些都**不可只到 cpu_specialist / "
        "gpu_specialist**(可併選 specialist,但一定要有 ecommerce)。\n"
        "- 這類『逐步選某類零件』的請求,即使提到 CPU / 主機板 / 記憶體,也**不可只選 cpu_specialist**;"
        "若同時涉及 CPU 技術分析可選 ecommerce + cpu_specialist,但**不可只到 cpu_specialist**;"
        "若涉及 GPU 遊戲效能可選 ecommerce + gpu_specialist,但**不可只到 gpu_specialist**。\n"
        "- 例外:**純規格比較**(沒有要選購/候選/逐步選的意圖),例如『RTX 5070 vs 5060 Ti 玩 2K 哪個好』、"
        "『i5-14600K 和 R5 7600 哪顆強』,仍可只選 gpu_specialist / cpu_specialist,不需 ecommerce。\n"
        "- If the user wants real store products, prices, deals/discounts, stock, "
        "or price comparison, choose ecommerce. This includes CPU coolers — "
        "散熱器 / CPU 散熱器 / 水冷 / 空冷 / 塔扇 / AIO 都是 ecommerce 可查的商品類別。\n"
        "- If the user wants to FIND / BUY / 推薦 a cooler (散熱器/水冷/空冷/塔扇/AIO), "
        "choose ecommerce. If the request ALSO mentions a CPU model (e.g. R5 7500F、"
        "7800X3D、i5-14600K), choose BOTH cpu_specialist AND ecommerce — do NOT pick only "
        "cpu_specialist just because a CPU model appears.\n"
        "- FULL BUILD / 完整菜單 / 整機:ecommerce 也負責『配一台電腦 / 組一台 / 完整菜單 / "
        "整機 / 主機 / 預算內組機 / 遊戲機 / 文書機 / 辦公機』。使用者問這類時,通常應選 ecommerce"
        "(由完整菜單工具處理)。若涉及遊戲效能/GPU 規格,可同時選 gpu_specialist;"
        "若涉及 CPU 效能/散熱需求,可同時選 cpu_specialist。\n"
        "- 不要讓單純『菜單』優先導向 pc_board_scraper;pc_board_scraper 只在明確提到 "
        "PTT / 電蝦 / 網友 / 社群討論 / 文章 / 最近討論 時才選。\n"
        "- Only choose pc_board_scraper when the user EXPLICITLY refers to community "
        "discussion sources, e.g. mentions PTT、電蝦、網友、文章、社群討論、最近討論。\n"
        "- The word 「菜單」 ALONE is NOT enough to choose pc_board_scraper. If 「菜單」 "
        "appears together with budget/price/deal/store words (預算、優惠、商城、價格、比價、"
        "原價屋、欣亞) or component needs (GPU/CPU/顯卡/處理器), prefer "
        "cpu_specialist / gpu_specialist / ecommerce instead of pc_board_scraper.\n"
        "- If the user wants spec analysis or component selection advice, choose "
        "cpu_specialist and/or gpu_specialist.\n"
        "- If the user gives a budget AND asks to find / buy a specific component "
        "(e.g. 「預算 10000 以內找 GPU」), include BOTH the relevant specialist "
        "(gpu_specialist / cpu_specialist) AND ecommerce, because the user wants "
        "actual products within budget, not just selection theory.\n"
        "- If the request mixes several needs, you may return multiple targets.\n"
        "- Example: 「30000 元遊戲機菜單，也幫我看有沒有商城優惠」 should map to "
        '["gpu_specialist", "ecommerce"] (cpu_specialist is also acceptable), '
        "NOT pc_board_scraper.\n"
        "- Example: 「請先給我 2~3 個 CPU 候選」 -> must include ecommerce, e.g. "
        '["ecommerce"] or ["ecommerce", "cpu_specialist"]; NOT only cpu_specialist.\n'
        "- Example: 「我選第 2 個 CPU，接下來給我相容主機板候選」 -> include ecommerce.\n"
        "- Example: 「我想用 DDR4 平台，先給我 2~3 張 DDR4 主機板候選」 -> include ecommerce.\n"
        "- Example: 「我想用 AM5 平台，先給我 CPU 候選」 / 「我想用 Intel 平台，先給我 CPU 候選」 "
        "-> include ecommerce (cpu_specialist optional, but not alone).\n"
        "- Counter-example: 「RTX 5070 和 RTX 5060 Ti 玩 2K 哪個比較適合」 -> only "
        '["gpu_specialist"] (pure spec comparison, NOT ecommerce).\n'
        "Return JSON only, in this format: "
        '{"targets": ["cpu_specialist"], "reason": "..."}. '
        "The targets field must be a non-empty subset of "
        "[cpu_specialist, gpu_specialist, pc_board_scraper, ecommerce]. "
        "Note (MVP limitation): if route_targets contains pc_board_scraper, graph 方案 C "
        "will short-circuit and run only pc_board_scraper. "
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


def router_node(
    state: dict,
    *,
    model_name: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Router Node 的執行函數"""
    
    route_targets, route_reason = _route_targets_for_request(state, model_name=model_name)
    
    if debug:
        print("Router Node Route Targets:", route_targets)
        print("Router Node Route Reason:", route_reason)
        print("===============================================================")

    return {
        "route_targets": route_targets,
        "route_reason": route_reason,
    }
