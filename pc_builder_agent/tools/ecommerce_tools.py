"""
電子商城 LangChain 工具層 (Phase 2)。

把 ecommerce_db 的查詢能力包裝成 LangChain @tool,供未來的 ecommerce node 透過
run_agent_turn() / TOOL_LOOKUP 呼叫。本層只負責:
  1. 參數整理(例如 limit 上限保護)
  2. 資料庫不存在 / 查無資料的優雅處理(回傳清楚訊息,不報錯、不亂編資料)
  3. 用 sanitize_product_for_llm() 清掉內部欄位(id / dedup_key / model_key / 時間戳記)

實際的 SQL 與優惠判定邏輯仍在 ecommerce_db,本層不重複實作。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from pc_builder_agent.tools.ecommerce_db import (
    DEFAULT_DB_PATH,
    query_products,
    find_deals,
    sanitize_product_for_llm,
    recommend_pc_build,
    list_promotions,
    attach_promotions_to_products,
    build_promotion_summary,
    estimate_promotion_adjusted_total,
    find_compatible_bundle_discount_pairs,
)


# tool 回傳給 LLM 的 limit 上限保護:預設 10,使用者最多 20
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 20

# 資料庫不存在時的標準訊息(first-run):不自動建 DB、不自動爬網、不編造商品,
# 明確告訴使用者要先手動執行 update 指令建立本地 DB。
_EMPTY_DB_MESSAGE = (
    "目前找不到本地商品資料庫 data/ecommerce.db(尚未建立)。\n"
    "請先在專案根目錄執行:\n"
    "  uv run python -m pc_builder_agent.tools.ecommerce_update --write --db-path data/ecommerce.db\n"
    "建立本地商品資料庫後,再查詢商品或產生完整菜單。\n"
    "(注意:沒有本地 DB 時無法查到真實商品;seed demo data 僅為 fallback / 示範,非正式商品資料。)"
)
# 資料庫存在、但這次查詢條件查無結果(與「資料庫整個沒資料」要區分,避免誤導)
_NO_RESULT_MESSAGE = (
    "找不到符合條件的商品。可放寬條件(例如移除 keyword、拉高 max_price 或改變 category)。"
)
_NO_DEAL_MESSAGE = (
    "目前找不到符合條件的優惠商品。可放寬條件(例如拉高 max_price 或移除 keyword),"
    "或先確認資料庫已匯入商品資料。"
)
_NO_PROMO_MESSAGE = (
    "目前找不到符合條件的商城優惠(promotion)。可移除 promo_type / category / keyword 再查,"
    "或先確認資料庫已匯入商品與優惠資料。注意:below_avg(低於同類均價)不是 promotion,不會出現在此。"
)
# DB 檔存在、但裡面沒有任何商品(例如只有 schema 沒 upsert,或匯入失敗)
_NO_PRODUCTS_MESSAGE = (
    "本地商品資料庫存在,但目前沒有任何商品資料(可能尚未成功匯入)。\n"
    "請在專案根目錄執行:\n"
    "  uv run python -m pc_builder_agent.tools.ecommerce_update --write --db-path data/ecommerce.db\n"
    "匯入商品後再查詢。(seed demo data 僅為 fallback / 示範,非正式商品資料。)"
)


def _clamp_limit(limit: int) -> int:
    """把 limit 限制在 1..20,預設情境下由呼叫端給 10。"""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT
    if limit < 1:
        return 1
    if limit > _MAX_LIMIT:
        return _MAX_LIMIT
    return limit


def _db_exists(db_path: str) -> bool:
    """
    判斷資料庫是否已存在。

    重要:這裡刻意「不」呼叫 ecommerce_db 的任何函式,因為那些函式會經由 _connect()
    自動建立父目錄與資料表(等於會生出一個空的 data/ecommerce.db)。我們要在查詢前先擋下,
    避免在資料庫尚未準備好時憑空建立空檔。
    """
    if db_path == ":memory:":
        return True
    return Path(db_path).exists()


def _db_product_count(db_path: str) -> int | None:
    """唯讀地數 products 筆數;DB 檔不存在 / 無 products 表 / 讀取失敗時回 0。

    刻意用 sqlite3 唯讀連線、不呼叫 ecommerce_db 任何會自動建表/建檔的函式,
    避免在 first-run 時憑空建立空 DB。
    """
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) FROM products").fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _no_data_message(db_path: str) -> str | None:
    """first-run / 空 DB 守門訊息:DB 不存在或沒有商品時回清楚指引,否則回 None。

    - DB 檔不存在 -> _EMPTY_DB_MESSAGE(請先執行 update 建立本地 DB)。
    - DB 存在但 0 筆商品 -> _NO_PRODUCTS_MESSAGE。
    - DB 有商品 -> None(交由各工具正常查詢;查無結果另有 _NO_RESULT_MESSAGE 等)。
    """
    if not _db_exists(db_path):
        return _EMPTY_DB_MESSAGE
    if db_path == ":memory:":
        return None
    if _db_product_count(db_path) == 0:
        return _NO_PRODUCTS_MESSAGE
    return None


@tool
def search_ecommerce_products(
    keyword: str | None = None,
    category: str | None = None,
    source: str | None = None,
    max_price: int | None = None,
    min_price: int | None = None,
    limit: int = 10,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict] | str:
    """查詢電子商城商品資料庫,依條件回傳商品清單。

    適用於使用者想找特定零件、品牌、型號或價格區間的商品時。

    Args:
        keyword: 關鍵字,會比對商品名稱 / 品牌 / 型號(例如 "RTX 4060"、"Ryzen"、"華碩")。
        category: 零件類別,例如 "CPU"、"GPU"、"Motherboard"。
        source: 商城 / 店家名稱,例如 "原價屋"、"欣亞"。
        max_price: 價格上限(新台幣整數)。
        min_price: 價格下限(新台幣整數)。
        limit: 回傳筆數,預設 10,最多 20(超過會被自動限制為 20)。
        db_path: 資料庫路徑,預設為正式資料庫。

    Returns:
        商品 dict 列表(已移除 id / dedup_key / model_key 等內部欄位);
        若資料庫不存在或查無資料,回傳清楚的中文說明字串。
    """
    _msg = _no_data_message(db_path)
    if _msg:
        return _msg

    safe_limit = _clamp_limit(limit)
    results = query_products(
        keyword=keyword,
        category=category,
        source=source,
        max_price=max_price,
        min_price=min_price,
        limit=safe_limit,
        db_path=db_path,
    )

    if not results:
        return _NO_RESULT_MESSAGE

    return [sanitize_product_for_llm(item) for item in results]


@tool
def find_ecommerce_deals_tool(
    keyword: str | None = None,
    category: str | None = None,
    max_price: int | None = None,
    avg_discount_ratio: float = 0.10,
    limit: int = 10,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict] | str:
    """尋找電子商城的優惠商品(單品特價,或價格明顯低於同類平均)。

    適用於使用者想找「划算」「特價」「優惠」「便宜」的商品時。
    回傳的每筆商品會附上 deal_reasons 標註優惠原因:
      - "discount": 有原價且特價低於原價的單品特價。
      - "below_avg": 價格低於同類別平均價達一定比例(預設便宜 10% 以上)。
    注意:below_avg 只是初步訊號,平均會被高 / 低階產品拉動,不保證一定是最佳優惠。

    Args:
        keyword: 關鍵字,會比對商品名稱 / 品牌 / 型號(例如 "RTX 4060")。
        category: 零件類別,例如 "CPU"、"GPU"、"Motherboard"。
        max_price: 價格上限(新台幣整數)。
        avg_discount_ratio: 低於同類平均的比例門檻,預設 0.10(便宜 10% 以上才算優惠)。
        limit: 回傳筆數,預設 10,最多 20(超過會被自動限制為 20)。
        db_path: 資料庫路徑,預設為正式資料庫。

    Returns:
        優惠商品 dict 列表(含 source / category / product_name / brand / model / price /
        original_price / discount_price / url / stock_status / deal_reasons /
        category_avg_price / below_avg_threshold,已移除內部欄位);
        若資料庫不存在或查無優惠,回傳清楚的中文說明字串。
    """
    _msg = _no_data_message(db_path)
    if _msg:
        return _msg

    safe_limit = _clamp_limit(limit)
    results = find_deals(
        keyword=keyword,
        category=category,
        max_price=max_price,
        avg_discount_ratio=avg_discount_ratio,
        limit=safe_limit,
        db_path=db_path,
    )

    if not results:
        return _NO_DEAL_MESSAGE

    return [sanitize_product_for_llm(item) for item in results]


@tool
def recommend_pc_build_tool(
    budget: int,
    use_case: str = "gaming",
    prefer_platform: str | None = None,
    include_promotions: bool = True,
    estimate_promotions: bool = True,
    db_path: str = DEFAULT_DB_PATH,
) -> dict | str:
    """組出一套平台一致的完整 PC 菜單,並計算總價與預算佔比。

    適用於使用者要求「配一台電腦 / 完整菜單 / 遊戲機 / 主機 / 組電腦」並給了預算時。
    這是 deterministic 工具:會檢查 CPU/主機板 socket 與 RAM 記憶體世代相容、套用遊戲機
    最低規格(RAM 至少 16GB DDR4/DDR5、SSD 至少 ~500GB、獨顯時 PSU 至少 550W),
    並盡量讓總價落在預算的 80%~120%;不合理的需求(如 5 萬文書機、1 萬 4K 機)會回 warning
    而不硬湊。

    優惠資訊(promotions)只是『參考資訊』:
    - total_price / budget_min / budget_max / budget_usage_percent / in_budget_range
      皆為『未套用任何 promotion』的原始加總,promotion **不會**自動扣總價、不影響選品。
    - 每個 build item 若有優惠,會在該 item 下附 promotions(含 note 說明未自動扣總價);
      整份 build 另附 promotion_summary。
    - actual_discount=已反映在商品目前售價;bundle_discount=需符合搭配條件,僅供人工參考;
      text_promo=活動提醒需人工確認。below_avg 不是 promotion,不會出現在此。

    優惠試算(estimate_promotions=True 時):
    - 額外回傳 estimated_final_price / estimated_discount_amount / applied_promotions /
      unapplied_promotions / promotion_price_note,**不覆蓋** total_price。
    - estimated_final_price 只折抵『可確認條件的 high-confidence bundle_discount』
      (required_category 須出現在 build 中);actual_discount 不重複扣、text_promo 不扣、
      below_avg 不參與。estimated_final_price 不是保證結帳價,實際以商城為準。

    Args:
        budget: 預算(新台幣整數)。
        use_case: 用途,如 "gaming"(預設) / "4k_gaming" / "office"(文書)。
        prefer_platform: 可選,指定平台 "AM5"/"AM4"/"LGA1700"。
        include_promotions: 是否附上 promotions 參考資訊(預設 True;不影響總價)。
        estimate_promotions: 是否額外試算 estimated_final_price(預設 True;不覆蓋 total_price)。
        db_path: 資料庫路徑。

    Returns:
        dict:含 build(各零件 category/product_name/price/socket/memory_generation,
        若 include_promotions 則每件附 promotions)、total_price(原始總價,不變)、budget_min、
        budget_max、budget_usage_percent(基於 total_price)、in_budget_range、platform、
        compatibility、warnings、explanation、promotion_summary,以及(estimate_promotions 時)
        estimated_final_price / estimated_discount_amount / applied_promotions /
        unapplied_promotions / promotion_price_note;
        若資料庫不存在回清楚訊息字串。所有商品僅來自資料庫,不會虛構。
    """
    _msg = _no_data_message(db_path)
    if _msg:
        return _msg
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        return "請提供有效的預算金額(整數)。"
    result = recommend_pc_build(budget=budget, use_case=use_case,
                                prefer_platform=prefer_platform, db_path=db_path)
    # 附加 promotions 參考資訊(唯讀、不改 total_price / 不改選品)
    if include_promotions and isinstance(result, dict) and result.get("build"):
        result["build"] = attach_promotions_to_products(result["build"], db_path=db_path)
        result["promotion_summary"] = build_promotion_summary(result["build"])
        # 優惠試算:新增 estimated_* 欄位,絕不覆蓋 total_price
        if estimate_promotions:
            result.update(estimate_promotion_adjusted_total(result))
    return result


@tool
def search_ecommerce_promotions(
    promo_type: str | None = None,
    category: str | None = None,
    keyword: str | None = None,
    limit: int = 10,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict] | str:
    """查詢電子商城『明確可見』的優惠(promotion),唯讀、不套用折扣、不改任何價格。

    只回傳『已關聯到實際商品』的優惠,並保留原始 promo_text 供人工確認。
    優惠型別語意(務必依此說明,不可把訊號講成保證折扣):
      - actual_discount:單品特價(原價>特價,可直接看到折扣金額)。
      - bundle_discount:搭配折扣(例如「搭主機板現省」),需符合搭配條件才成立,僅供人工參考,
        **不可**直接從總價扣除。
      - combo / add_on / gift / threshold_gift:組合/加購/贈品/滿額,屬附加優惠,非單品折扣。
      - text_promo:文字型活動訊號(低信心,常需登錄/活動頁),只能當提醒,**不可**扣總價。
    注意:below_avg(低於同類均價)不是 promotion,不會出現在此工具的結果。

    Args:
        promo_type: 過濾優惠型別(如 "actual_discount" / "bundle_discount" / "text_promo")。
        category: 過濾關聯商品類別(CPU/GPU/Motherboard/RAM/Storage/PSU/Case/Cooler)。
        keyword: 關鍵字,會比對 promo_text 與關聯商品名稱(例如 "主機板"、"現省")。
        limit: 回傳筆數,預設 10,最多 20(超過會被自動限制為 20)。
        db_path: 資料庫路徑,預設為正式資料庫。

    Returns:
        優惠 dict 列表(含 source / promo_type / promo_type_meaning / title / promo_text /
        discount_amount / discount_percent / original_price / promo_price /
        required_category / required_keyword / confidence / product_role / product_name /
        product_category / product_price / source_url,已移除所有內部欄位);
        若資料庫不存在或查無優惠,回傳清楚的中文說明字串。
    """
    _msg = _no_data_message(db_path)
    if _msg:
        return _msg

    safe_limit = _clamp_limit(limit)
    results = list_promotions(
        promo_type=promo_type,
        category=category,
        keyword=keyword,
        limit=safe_limit,
        db_path=db_path,
    )

    if not results:
        return _NO_PROMO_MESSAGE

    return results


@tool
def find_bundle_discount_pc_pairs(
    cpu_keyword: str | None = None,
    motherboard_keyword: str | None = None,
    prefer_platform: str | None = None,
    max_total_price: int | None = None,
    limit: int = 10,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict] | str:
    """查詢『有搭主機板現省優惠的 CPU + 相容主機板』的可試算配對(deterministic、唯讀)。

    使用者問「搭主機板現省 / 搭板專案 / CPU 搭主機板折扣 / 有 bundle_discount 的 CPU 並搭主機板」
    時,**優先用本工具**,不要自己用 search_ecommerce_promotions + search_ecommerce_products 手湊、
    也不要自行計算折扣。

    本工具會:找出有 bundle_discount 的 CPU → 讀 CPU socket/平台 → 找『socket 相同、記憶體世代不衝突』
    的相容主機板(最便宜一張)→ 做相容性守門 + 折抵試算。**只回傳真正相容、折抵 > 0 的配對**;
    AM5 CPU 不會配 A520/B550(AM4),不相容 / 無法確認的一律不列入。

    Args:
        cpu_keyword: 可選,限定 CPU(例如 "7500F")。
        motherboard_keyword: 可選,限定主機板晶片組(例如 "B650")。
        prefer_platform: 可選,限定平台 "AM5"/"AM4"/"LGA1700"/"LGA1851"。
        max_total_price: 可選,CPU+主機板原始總價上限。
        limit: 回傳筆數,預設 10,最多 20。
        db_path: 資料庫路徑。

    Returns:
        配對 dict 列表,每筆含 cpu_product_name / cpu_price / cpu_socket /
        motherboard_product_name / motherboard_price / motherboard_socket / promo_type /
        promo_text / discount_amount / total_price / estimated_discount_amount /
        estimated_final_price / compatibility_status / compatibility_reason /
        promotion_price_note / source(已移除所有內部欄位);
        estimated_final_price 為**試算**,非保證結帳價,實際以商城為準。
        資料庫不存在或查無相容配對時回清楚的中文說明字串。
    """
    _msg = _no_data_message(db_path)
    if _msg:
        return _msg
    safe_limit = _clamp_limit(limit)
    results = find_compatible_bundle_discount_pairs(
        cpu_keyword=cpu_keyword,
        motherboard_keyword=motherboard_keyword,
        prefer_platform=prefer_platform,
        max_total_price=max_total_price,
        limit=safe_limit,
        db_path=db_path,
    )
    if not results:
        return (
            "目前找不到『有搭主機板現省優惠且平台相容』的 CPU + 主機板配對。"
            "可移除 prefer_platform / cpu_keyword / motherboard_keyword 再查,"
            "或先確認資料庫已匯入商品與優惠資料。"
        )
    return results


__all__ = [
    "search_ecommerce_products",
    "find_ecommerce_deals_tool",
    "recommend_pc_build_tool",
    "search_ecommerce_promotions",
    "find_bundle_discount_pc_pairs",
]
