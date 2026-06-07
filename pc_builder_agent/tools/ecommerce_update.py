"""
CoolPC 真實資料更新流程(手動執行,非 LLM tool)。

串接:fetch_coolpc_html() -> parse_coolpc_html() -> upsert_products()

設計重點:
- 這是「手動更新」用的腳本/模組,刻意「不」註冊到 tools/__init__.py 的 ALL_TOOLS,
  避免 LLM 直接觸發爬取/寫 DB。
- 失敗或解析為空時「不覆蓋既有 DB」;可選 fallback 到 seed data。
- 預設 dry_run / 預設不寫正式 data/ecommerce.db,需明確 --write 才寫入。
"""

from __future__ import annotations

import argparse
from typing import Any

from pc_builder_agent.tools.ecommerce_scraper import (
    fetch_coolpc_html,
    parse_coolpc_html,
)
from pc_builder_agent.tools.ecommerce_db import (
    DEFAULT_DB_PATH,
    upsert_products,
    load_seed_products,
)


def _count_by_category(products: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in products:
        cat = p.get("category", "?")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def _summary_samples(products: list[dict], n: int = 5) -> list[dict]:
    """取前 n 筆,只保留人類可讀的精簡欄位作為 sample。"""
    keep = ("source", "category", "product_name", "brand", "model", "price",
            "original_price", "discount_price", "stock_status")
    return [{k: p.get(k) for k in keep} for p in products[:n]]


def update_coolpc_products(
    db_path: str = DEFAULT_DB_PATH,
    max_per_category: int | None = None,
    dry_run: bool = False,
    fallback_to_seed: bool = False,
    with_promotions: bool = True,
) -> dict[str, Any]:
    """抓取並更新 CoolPC 商品到資料庫。

    Args:
        db_path: 目標 DB 路徑。
        max_per_category: 每類別最多解析幾筆(None 不限)。
        dry_run: True 則只解析、不寫 DB。
        fallback_to_seed: 抓取失敗/解析為空時,是否改用 seed data 匯入(僅在非 dry_run 生效)。
        with_promotions: 寫入商品時是否一併同步 promotions(預設 True;Phase Promo-C 起
            正式更新流程預設包含優惠寫入)。注意:這只是把『可查詢的優惠資料』寫進 DB,
            完全不影響 recommend_pc_build 的總價計算,也不會自動套用任何折扣。

    Returns:
        dict:source / ok / fetched / parsed_count / count_by_category /
              upsert_stats / error / sample_products / dry_run / with_promotions。
    """
    result: dict[str, Any] = {
        "source": "原價屋",
        "ok": False,
        "fetched": False,
        "parsed_count": 0,
        "count_by_category": {},
        "upsert_stats": None,
        "error": None,
        "sample_products": [],
        "dry_run": dry_run,
        "with_promotions": with_promotions,
    }

    # 1) 抓取
    html = fetch_coolpc_html()
    if not html:
        result["error"] = "抓取 CoolPC 失敗(HTTP 非 200 / timeout / 連線錯誤),未變更既有 DB。"
        if fallback_to_seed and not dry_run:
            result["upsert_stats"] = load_seed_products(db_path)
            result["error"] += " 已改用 seed data 匯入。"
            result["ok"] = True
        return result
    result["fetched"] = True

    # 2) 解析
    products = parse_coolpc_html(html, max_per_category=max_per_category)
    result["parsed_count"] = len(products)
    result["count_by_category"] = _count_by_category(products)
    result["sample_products"] = _summary_samples(products)

    # 3) 解析為空 -> 不覆蓋既有 DB
    if not products:
        result["error"] = "解析結果為空,未變更既有 DB。"
        if fallback_to_seed and not dry_run:
            result["upsert_stats"] = load_seed_products(db_path)
            result["error"] += " 已改用 seed data 匯入。"
            result["ok"] = True
        return result

    # 4) dry_run:不寫 DB
    if dry_run:
        result["ok"] = True
        return result

    # 5) 寫入 DB(Phase Promo-C 起預設一併同步 promotions;不影響總價/不套折扣)
    result["upsert_stats"] = upsert_products(
        products, db_path=db_path, with_promotions=with_promotions
    )
    result["ok"] = True
    return result


def _print_result(result: dict[str, Any]) -> None:
    print("=" * 60)
    print(f"來源        : {result['source']}")
    print(f"dry_run     : {result['dry_run']}")
    print(f"fetched     : {result['fetched']}")
    print(f"parsed_count: {result['parsed_count']}")
    print(f"count_by_cat: {result['count_by_category']}")
    print(f"with_promos : {result.get('with_promotions')}")
    print(f"upsert_stats: {result['upsert_stats']}")
    print(f"ok          : {result['ok']}")
    if result["error"]:
        print(f"error       : {result['error']}")
    print("-" * 60)
    print("sample_products(前幾筆):")
    for s in result["sample_products"]:
        op = ""
        if s.get("discount_price"):
            op = f"(原{s.get('original_price')}→{s.get('discount_price')})"
        print(f"  [{s.get('category')}] {str(s.get('product_name'))[:38]} | "
              f"{s.get('brand')} | {s.get('model')} | ${s.get('price')}{op} | {s.get('stock_status')}")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="手動更新 CoolPC 商品資料(預設 dry-run,不寫 DB)。",
    )
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH,
                        help="目標 DB 路徑(預設 data/ecommerce.db;測試請指向 tempfile)")
    parser.add_argument("--max-per-category", type=int, default=None,
                        help="每類別最多解析幾筆")
    parser.add_argument("--write", action="store_true",
                        help="實際寫入 DB(不加此旗標則為 dry-run,不寫任何 DB)")
    parser.add_argument("--fallback-to-seed", action="store_true",
                        help="抓取失敗/解析為空時改用 seed data 匯入(僅在 --write 時生效)")
    parser.add_argument("--no-promotions", action="store_true",
                        help="寫入時不同步 promotions(預設會寫入優惠;優惠僅供查詢,不影響總價)")
    args = parser.parse_args()

    result = update_coolpc_products(
        db_path=args.db_path,
        max_per_category=args.max_per_category,
        dry_run=not args.write,  # 預設 dry-run
        fallback_to_seed=args.fallback_to_seed,
        with_promotions=not args.no_promotions,
    )
    _print_result(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
