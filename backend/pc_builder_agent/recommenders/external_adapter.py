"""
External component recommender — 介面契約 + 範例實作。

互動式選件流程(state-driven 選件 / reselect / JSON 保存 / DB guard / 中文預算解析 /
基本相容性 safety validation)由本專案負責;**實際挑哪 2~3 個候選**委派給此處的 recommender。

================================ 介面契約 ================================

函式簽名:

    def recommend(context: dict) -> list[dict]:
        ...

------------------------------ 輸入 context ------------------------------
由本專案整理後傳入,欄位(CONTEXT_FIELDS):

    target_category      str   要推薦的類別(CPU/GPU/Motherboard/RAM/Storage/PSU/Cooler/Case)
    budget               int|None  整機預算
    use_case             str   gaming / 4k_gaming / office
    remaining_budget     int|None  剩餘預算(= budget - 已選總價)
    current_total        int   目前已選零件總價
    total_selected_price int   同 current_total(別名)
    prefer_platform      str|None  AMD/Intel/AM5/AM4/LGA1700/LGA1851(若使用者指定)
    selected_components  dict  {category: 規格 dict(含 product_name/price/socket/platform/
                               memory_generation/has_igpu/source…,已 sanitize)}
    selected_cpu / selected_gpu / selected_motherboard / selected_ram /
    selected_storage / selected_psu / selected_cooler / selected_case  str|None  已選商品名
    constraints          dict  {socket, memory_generation, brand}  目前相容性約束
    cpu_has_igpu         bool|None  已選 CPU 是否有內顯
    db_path              str   本地 data/ecommerce.db 路徑(若 recommender 需自行查 DB)

------------------------------ 回傳 options ------------------------------
回傳一個 list,每個元素為候選 dict;**可以是**:
  (a) 原始 DB 商品 dict(含 specs),或
  (b) 已成形 option dict。
至少包含 product_name 與 price;可選欄位(OPTION_FIELDS)會被本專案 adapter 正規化:

    category, product_name, price, source, source_url, socket, platform,
    memory_generation, reason(或 recommendation_reason), warnings, is_virtual

> adapter 會把結果**正規化成統一 schema、套基本 safety validation、補固定虛擬「無」選項**,
> 並**過濾掉** id / product_id / promotion_id / dedup_key / model_key / promo_key /
> created_at / updated_at / raw specs 等內部欄位(不外洩)。

=========================================================================
"""

from __future__ import annotations

CONTEXT_FIELDS = (
    "target_category", "budget", "use_case", "remaining_budget", "current_total",
    "total_selected_price", "prefer_platform", "selected_components",
    "selected_cpu", "selected_gpu", "selected_motherboard", "selected_ram",
    "selected_storage", "selected_psu", "selected_cooler", "selected_case",
    "constraints", "cpu_has_igpu", "db_path",
)

OPTION_FIELDS = (
    "category", "product_name", "price", "source", "source_url", "socket",
    "platform", "memory_generation", "reason", "warnings", "is_virtual",
)


def example_recommend(context: dict) -> list[dict]:
    """**範例 / 參考實作**(請替換成同學的正式 recommender)。

    這個範例只示範介面契約:依 target_category 從本地 DB 取預算內候選回傳(不含本專案的
    tier/ranking),讓接入路徑可被端到端驗證。**正式上線請以同學的 recommender 取代。**
    """
    # 延遲匯入,避免 import 循環
    from pc_builder_agent.tools.ecommerce_db import query_products

    cat = context.get("target_category")
    if not cat:
        return []
    cap = context.get("remaining_budget") or context.get("budget")
    limit = context.get("limit") or 3
    rows = query_products(category=cat, max_price=cap, limit=max(int(limit) + 2, 5),
                          db_path=context.get("db_path"))
    out: list[dict] = []
    for r in rows:
        # 直接回傳原始商品 dict(含 specs);本專案 adapter 會正規化並移除內部欄位。
        item = dict(r)
        item["source_url"] = r.get("url")
        item["recommendation_reason"] = f"範例 recommender:{cat} 於預算內的候選(請改用正式 recommender)"
        out.append(item)
    return out


# 別名:讓 PC_BUILDER_EXTERNAL_RECOMMENDER="...external_adapter:recommend" 也可指向範例。
recommend = example_recommend
