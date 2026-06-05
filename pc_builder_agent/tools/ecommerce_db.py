"""
電子商城 SQLite 資料庫層。

此模組為 Phase 1 的核心:把商品資料「匯入 / 查詢 / 找優惠」的能力獨立成純 Python
函式(刻意「不是」LangChain @tool),方便用 script 或 `uv run python -c` 直接驗證,
等資料層穩定後,Phase 2/3 才由 ecommerce node 包裝成工具或直接呼叫這些函式。

設計重點:
- 兩張表:products(商品現況) + price_history(價格歷史)。
- 去重以內部欄位 dedup_key 統一處理:
    * 有 url   -> "source|url"
    * 沒有 url -> "source|category|product_name"
  dedup_key 掛 UNIQUE 約束,upsert 以它判斷 insert 或 update。
- model_key:由 model(或 product_name)正規化而來,讓 "RTX 4060"/"rtx4060"/"RTX-4060"
  都能比對到同一個 key。
- price_history:只有「新商品」或「price/original_price/discount_price 任一變動」才寫一筆。
- 所有金額一律存整數(新台幣),"$12,900" 這類字串會被解析掉。

價格欄位語意(重要,寫入資料時請遵守):
- price          : 目前實際售價(使用者真正要付的金額)。
- original_price : 只代表「特價前」的原價;沒有特價時可為 None。
- discount_price : 特價金額;若商品有特價,price 應等於 discount_price
                   (亦即 price == discount_price < original_price)。
                   沒有特價時 discount_price 可為 None。

注意:dedup_key 為 internal 欄位,查詢結果雖然會帶出它,但未來 node 回覆使用者時不應直接展示;
要把商品交給 LLM / 回覆使用者前,請先經過 sanitize_product_for_llm() 移除內部欄位。
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pc_builder_agent.tools import platform_rules as _pr


DEFAULT_DB_PATH = "data/ecommerce.db"


# ============================================================================
# 內部輔助函式
# ============================================================================

def _now() -> str:
    """回傳目前 UTC 時間的 ISO 字串,作為時間戳記。"""
    return datetime.now(timezone.utc).isoformat()


def _normalize_model_key(value: str | None) -> str:
    """
    將型號正規化成可比對的 key。

    規則:轉小寫,移除所有非英數字元(空白、連字號、底線等)。
    例:
        "RTX 4060"  -> "rtx4060"
        "rtx4060"   -> "rtx4060"
        "RTX-4060"  -> "rtx4060"
        "Core i5-14600K" -> "corei514600k"
    """
    if not value:
        return ""
    return re.sub(r"[^0-9a-z]+", "", value.lower())


def _parse_price(value: Any) -> int | None:
    """
    將各種價格表示法解析成整數,無法解析或空值時回傳 None。

    支援:int / float / "12900" / "$12,900" / "NT$12900" / "12,900 元" / "" / None
    """
    if value is None:
        return None
    if isinstance(value, bool):  # 避免 True/False 被當成 1/0
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^0-9]", "", value)
        if digits == "":
            return None
        return int(digits)
    return None


def _serialize_specs(specs: Any) -> str | None:
    """specs 統一存成 JSON 字串;dict/list 會被序列化,字串原樣保留,空值回 None。"""
    if specs is None:
        return None
    if isinstance(specs, str):
        return specs
    try:
        return json.dumps(specs, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _compute_dedup_key(source: str, url: str, category: str, product_name: str) -> str:
    """
    計算去重鍵:
      * 有 url   -> "source|url"
      * 沒有 url -> "source|category|product_name"

    正規化規則(避免大小寫 / 空白 / 尾端斜線造成同商品被視為兩筆):
      - source / category / product_name 一律 lower().strip()
      - url 先 strip(),再移除尾端的 "/"(僅做最小程度處理,不做完整 canonicalization)
    """
    source = (source or "").strip().lower()
    url = (url or "").strip().rstrip("/")
    if url:
        return f"{source}|{url}"
    category = (category or "").strip().lower()
    product_name = (product_name or "").strip().lower()
    return f"{source}|{category}|{product_name}"


def _ensure_parent_dir(db_path: str) -> None:
    """確保 DB 檔案的父目錄存在(例如 data/)。記憶體 DB(:memory:)則略過。"""
    if db_path == ":memory:":
        return
    parent = Path(db_path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def _connect(db_path: str) -> sqlite3.Connection:
    """建立連線並設定 row_factory,讓查詢結果可轉成 dict。"""
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """把 sqlite3.Row 轉成一般 dict。"""
    return {key: row[key] for key in row.keys()}


# 對外查詢時使用的欄位順序(products 表全欄位)
_PRODUCT_COLUMNS = (
    "id, source, category, product_name, brand, model, model_key, "
    "price, original_price, discount_price, url, specs, stock_status, "
    "bundle_id, dedup_key, last_updated, created_at, updated_at"
)


# 交給 LLM / 回覆使用者時應保留的欄位(白名單)。
# 任何不在此清單的欄位(id / dedup_key / 各種時間戳記 / model_key / 內部 debug 欄位)
# 都會被 sanitize_product_for_llm() 過濾掉。
_LLM_SAFE_FIELDS = (
    "source",
    "category",
    "product_name",
    "brand",
    "model",
    "price",
    "original_price",
    "discount_price",
    "url",
    "specs",
    "stock_status",
    "bundle_id",
    # find_deals 額外附加的優惠標註欄位
    "deal_reasons",
    "category_avg_price",
    "below_avg_threshold",
)


def sanitize_product_for_llm(product: dict) -> dict:
    """
    把一筆商品 dict 整理成「可安全交給 LLM / 回覆使用者」的版本。

    用途:未來 ecommerce_tools.py / ecommerce node 在把查詢結果丟給 LLM 前先呼叫此函式,
    移除內部欄位,避免模型把 dedup_key、資料庫 id、時間戳記等實作細節寫進回覆。

    會移除:id、dedup_key、model_key、created_at、updated_at、last_updated,
            以及任何以 "_" 開頭的 internal/debug 欄位(例如 _discount_strength)。
    會保留:_LLM_SAFE_FIELDS 白名單內、且該商品實際存在的欄位。

    Returns:
        只含白名單欄位的新 dict(不會修改傳入的 product)。
    """
    if not isinstance(product, dict):
        return {}
    return {key: product[key] for key in _LLM_SAFE_FIELDS if key in product}


# ============================================================================
# Schema 建立
# ============================================================================

def _ensure_schema(conn: sqlite3.Connection) -> None:
    """建立資料表與索引(IF NOT EXISTS,可重複執行不破壞既有資料)。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source          TEXT,
            category        TEXT,
            product_name    TEXT,
            brand           TEXT,
            model           TEXT,
            model_key       TEXT,
            price           INTEGER,
            original_price  INTEGER,
            discount_price  INTEGER,
            url             TEXT,
            specs           TEXT,
            stock_status    TEXT,
            bundle_id       TEXT,
            dedup_key       TEXT NOT NULL UNIQUE,
            last_updated    TEXT,
            created_at      TEXT,
            updated_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id      INTEGER NOT NULL,
            source          TEXT,
            price           INTEGER,
            original_price  INTEGER,
            discount_price  INTEGER,
            recorded_at     TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_products_category   ON products(category);
        CREATE INDEX IF NOT EXISTS idx_products_source     ON products(source);
        CREATE INDEX IF NOT EXISTS idx_products_model_key  ON products(model_key);
        CREATE INDEX IF NOT EXISTS idx_products_price      ON products(price);
        CREATE INDEX IF NOT EXISTS idx_history_product_id  ON price_history(product_id);

        -- 商城優惠(Phase Promo-A)。只記錄『明確可見、可解析』的優惠;
        -- below_avg 一律不寫入此表(它不是優惠,只是低於均價的價格訊號)。
        CREATE TABLE IF NOT EXISTS promotions (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            source            TEXT,
            promo_key         TEXT NOT NULL UNIQUE,
            promo_type        TEXT,
            title             TEXT,
            promo_text        TEXT,
            discount_amount   INTEGER,
            discount_percent  REAL,
            original_price    INTEGER,
            promo_price       INTEGER,
            required_category TEXT,
            required_keyword  TEXT,
            min_items         INTEGER,
            source_url        TEXT,
            confidence        TEXT,
            created_at        TEXT,
            updated_at        TEXT
        );

        -- promotion <-> product 關聯;product_role: trigger/target/member/unknown。
        CREATE TABLE IF NOT EXISTS promotion_products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            promotion_id  INTEGER NOT NULL,
            product_id    INTEGER NOT NULL,
            product_role  TEXT,
            created_at    TEXT,
            UNIQUE(promotion_id, product_id, product_role),
            FOREIGN KEY (promotion_id) REFERENCES promotions(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id)   REFERENCES products(id)   ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_promotions_type      ON promotions(promo_type);
        CREATE INDEX IF NOT EXISTS idx_promo_products_promo ON promotion_products(promotion_id);
        CREATE INDEX IF NOT EXISTS idx_promo_products_prod  ON promotion_products(product_id);
        """
    )


# ============================================================================
# 公開 API
# ============================================================================

def init_db(db_path: str = DEFAULT_DB_PATH) -> str:
    """
    初始化資料庫:建立父目錄、建立 products / price_history 表與索引。

    可重複執行(IF NOT EXISTS),不會破壞既有資料。

    Returns:
        實際使用的 db_path 字串。
    """
    conn = _connect(db_path)
    try:
        _ensure_schema(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path


def upsert_products(
    products: list[dict],
    db_path: str = DEFAULT_DB_PATH,
    with_promotions: bool = False,
) -> dict[str, int]:
    """
    匯入或更新商品資料。

    去重依據(內部 dedup_key):
      * 有 url   -> source + url
      * 沒有 url -> source + category + product_name

    價格歷史(price_history):
      * 新商品 -> 寫入一筆
      * 既有商品且 price/original_price/discount_price 任一變動 -> 寫入一筆
      * 價格未變動 -> 不寫(避免重複灌爆歷史表)

    Args:
        products: 商品 dict 列表,欄位對應 products 表(可缺欄位,缺者視為 None/空)。
        db_path: 資料庫路徑。
        with_promotions: 為 True 時,匯入每筆商品後同步解析並 upsert 其優惠(promotions)。
            預設 False —— 不影響既有匯入行為(優惠同步為 opt-in,Phase Promo-A 只用於測試)。

    Returns:
        統計 dict:{"inserted", "updated", "history_added", "skipped", "promotions_synced"}。
    """
    conn = _connect(db_path)
    stats = {"inserted": 0, "updated": 0, "history_added": 0, "skipped": 0,
             "promotions_synced": 0}
    try:
        _ensure_schema(conn)

        for item in products:
            if not isinstance(item, dict):
                stats["skipped"] += 1
                continue

            source = (item.get("source") or "").strip()
            category = (item.get("category") or "").strip()
            product_name = (item.get("product_name") or "").strip()
            url = (item.get("url") or "").strip()

            # 至少要有 source 與 (url 或 product_name) 才能算出有意義的 dedup_key
            if not source or (not url and not product_name):
                stats["skipped"] += 1
                continue

            dedup_key = _compute_dedup_key(source, url, category, product_name)

            model = item.get("model")
            # model_key:優先用傳入值,否則由 model 正規化,再退而求其次用 product_name
            model_key = item.get("model_key")
            if not model_key:
                model_key = _normalize_model_key(model) or _normalize_model_key(product_name)

            price = _parse_price(item.get("price"))
            original_price = _parse_price(item.get("original_price"))
            discount_price = _parse_price(item.get("discount_price"))
            brand = item.get("brand")
            specs = _serialize_specs(item.get("specs"))
            stock_status = item.get("stock_status")
            bundle_id = item.get("bundle_id") or ""
            now = _now()

            existing = conn.execute(
                "SELECT id, price, original_price, discount_price "
                "FROM products WHERE dedup_key = ?",
                (dedup_key,),
            ).fetchone()

            if existing is None:
                # ---- 新商品 ----
                cursor = conn.execute(
                    """
                    INSERT INTO products (
                        source, category, product_name, brand, model, model_key,
                        price, original_price, discount_price, url, specs,
                        stock_status, bundle_id, dedup_key,
                        last_updated, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source, category, product_name, brand, model, model_key,
                        price, original_price, discount_price, url, specs,
                        stock_status, bundle_id, dedup_key,
                        now, now, now,
                    ),
                )
                product_id = cursor.lastrowid
                stats["inserted"] += 1

                # 新商品一律記一筆價格歷史
                conn.execute(
                    """
                    INSERT INTO price_history (
                        product_id, source, price, original_price,
                        discount_price, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (product_id, source, price, original_price, discount_price, now),
                )
                stats["history_added"] += 1
            else:
                # ---- 既有商品:更新現況 ----
                product_id = existing["id"]
                price_changed = (
                    existing["price"] != price
                    or existing["original_price"] != original_price
                    or existing["discount_price"] != discount_price
                )

                conn.execute(
                    """
                    UPDATE products SET
                        category = ?, product_name = ?, brand = ?, model = ?,
                        model_key = ?, price = ?, original_price = ?,
                        discount_price = ?, url = ?, specs = ?, stock_status = ?,
                        bundle_id = ?, last_updated = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        category, product_name, brand, model, model_key,
                        price, original_price, discount_price, url, specs,
                        stock_status, bundle_id, now, now, product_id,
                    ),
                )
                stats["updated"] += 1

                # 只有價格有變動才寫歷史
                if price_changed:
                    conn.execute(
                        """
                        INSERT INTO price_history (
                            product_id, source, price, original_price,
                            discount_price, recorded_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (product_id, source, price, original_price, discount_price, now),
                    )
                    stats["history_added"] += 1

            # opt-in:同步該商品的優惠訊號(actual_discount 由價格欄位判定,其餘解析文字)
            if with_promotions:
                stats["promotions_synced"] += _sync_product_promotions(
                    conn,
                    {
                        "product_name": product_name,
                        "category": category,
                        "url": url,
                        "specs": specs,
                        "original_price": original_price,
                        "discount_price": discount_price,
                    },
                    product_id,
                    source,
                )

        conn.commit()
    finally:
        conn.close()
    return stats


def query_products(
    keyword: str | None = None,
    category: str | None = None,
    source: str | None = None,
    max_price: int | None = None,
    min_price: int | None = None,
    limit: int = 20,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict]:
    """
    依條件查詢商品。

    Args:
        keyword: 關鍵字,會同時比對 product_name / brand / model(LIKE)
                 以及正規化後的 model_key(讓 "RTX 4060" 能對到 model_key=rtx4060)。
        category: 類別(不分大小寫完全比對)。
        source: 商城(不分大小寫完全比對)。
        max_price / min_price: 價格上下限(以 price 欄位比對)。
        limit: 回傳上限。
        db_path: 資料庫路徑。

    Returns:
        商品 dict 列表(依 price 由低到高排序;price 為 NULL 者排最後)。
    """
    conn = _connect(db_path)
    try:
        _ensure_schema(conn)
        clauses: list[str] = []
        params: list[Any] = []

        if keyword:
            kw = f"%{keyword.lower()}%"
            nkey = f"%{_normalize_model_key(keyword)}%"
            clauses.append(
                "(lower(product_name) LIKE ? OR lower(brand) LIKE ? "
                "OR lower(model) LIKE ? OR model_key LIKE ?)"
            )
            params.extend([kw, kw, kw, nkey])

        if category:
            clauses.append("lower(category) = ?")
            params.append(category.lower())

        if source:
            clauses.append("lower(source) = ?")
            params.append(source.lower())

        if max_price is not None:
            clauses.append("price IS NOT NULL AND price <= ?")
            params.append(int(max_price))

        if min_price is not None:
            clauses.append("price IS NOT NULL AND price >= ?")
            params.append(int(min_price))

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT {_PRODUCT_COLUMNS} FROM products {where} "
            "ORDER BY (price IS NULL), price ASC LIMIT ?"
        )
        params.append(int(limit))

        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def find_deals(
    keyword: str | None = None,
    category: str | None = None,
    max_price: int | None = None,
    avg_discount_ratio: float = 0.10,
    limit: int = 20,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict]:
    """
    尋找優惠商品。第一階段支援兩種優惠定義(以 OR 合併):

      1. 單品特價:discount_price 與 original_price 皆有值,且 discount_price < original_price。
      2. 低於同類均價:price 低於「同 category 平均價」的 (1 - avg_discount_ratio) 倍,
         預設 ratio=0.10,即比平均便宜 10% 以上。

    可用 keyword / category / max_price 進一步過濾。

    回傳的每筆商品會額外帶上:
      - deal_reasons: list[str]，可能含 "discount"(單品特價)、"below_avg"(低於均價)
      - category_avg_price: 該類別平均價(int 或 None)
      - below_avg_threshold: 低於均價的判定門檻(int 或 None)

    限制與未來方向(below_avg 的注意事項):
      - "below_avg" 只是「低於同 category 平均價」的初步訊號,並不保證是真正的最佳優惠。
        平均價會被高階 / 低階產品拉高或拉低(例如 GPU 類別同時含 RTX 4090 與 RTX 3060),
        因此便宜的入門卡很容易被判為 below_avg,這未必代表它「划算」。
      - 第一階段刻意採用最簡單的「同類別平均」做法以求可運作;
        未來應改成「同型號(model_key)或同規格區間」比較,才能反映真正的相對優惠程度。

    Returns:
        商品 dict 列表(依折扣幅度由大到小排序)。
    """
    conn = _connect(db_path)
    try:
        _ensure_schema(conn)

        # 先算每個類別的平均價(只計 price 非 NULL 者)
        avg_rows = conn.execute(
            "SELECT category, AVG(price) AS avg_price FROM products "
            "WHERE price IS NOT NULL GROUP BY category"
        ).fetchall()
        category_avg: dict[str, float] = {
            row["category"]: row["avg_price"]
            for row in avg_rows
            if row["avg_price"] is not None
        }

        # 套用過濾條件取候選
        clauses: list[str] = []
        params: list[Any] = []
        if keyword:
            kw = f"%{keyword.lower()}%"
            nkey = f"%{_normalize_model_key(keyword)}%"
            clauses.append(
                "(lower(product_name) LIKE ? OR lower(brand) LIKE ? "
                "OR lower(model) LIKE ? OR model_key LIKE ?)"
            )
            params.extend([kw, kw, kw, nkey])
        if category:
            clauses.append("lower(category) = ?")
            params.append(category.lower())
        if max_price is not None:
            clauses.append("price IS NOT NULL AND price <= ?")
            params.append(int(max_price))

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT {_PRODUCT_COLUMNS} FROM products {where}"
        candidates = [_row_to_dict(row) for row in conn.execute(sql, params).fetchall()]

        deals: list[dict] = []
        for item in candidates:
            reasons: list[str] = []
            price = item.get("price")
            original_price = item.get("original_price")
            discount_price = item.get("discount_price")

            # 計算折扣幅度,供排序用(0~1,越大越優惠)
            discount_strength = 0.0

            # 條件 1:單品特價
            if (
                discount_price is not None
                and original_price is not None
                and discount_price < original_price
                and original_price > 0
            ):
                reasons.append("discount")
                discount_strength = max(
                    discount_strength,
                    (original_price - discount_price) / original_price,
                )

            # 條件 2:低於同類均價
            avg_price = category_avg.get(item.get("category"))
            threshold = None
            if avg_price is not None:
                threshold = int(avg_price * (1 - avg_discount_ratio))
                if price is not None and price < threshold:
                    reasons.append("below_avg")
                    discount_strength = max(
                        discount_strength,
                        (avg_price - price) / avg_price,
                    )

            if reasons:
                item["deal_reasons"] = reasons
                item["category_avg_price"] = int(avg_price) if avg_price is not None else None
                item["below_avg_threshold"] = threshold
                item["_discount_strength"] = discount_strength
                deals.append(item)

        deals.sort(key=lambda d: d["_discount_strength"], reverse=True)
        for d in deals:
            d.pop("_discount_strength", None)

        return deals[: int(limit)]
    finally:
        conn.close()


# ============================================================================
# 商城優惠 promotions(Phase Promo-A:寫入 / 同步 / 查詢)
# ============================================================================

# 訊號角色 -> 關聯表 product_role(parser 已建議 role,這裡只做白名單收斂)
_VALID_ROLES = ("trigger", "target", "member", "unknown")


def _source_text_of(product: dict) -> str:
    """取商品用來解析優惠的原始文字:優先 specs.source_text,退而求其次 product_name。"""
    specs = product.get("specs")
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except (json.JSONDecodeError, TypeError):
            specs = None
    if isinstance(specs, dict) and specs.get("source_text"):
        return str(specs["source_text"])
    return product.get("product_name") or ""


def _promo_key(source: str, product_token: str, signal: dict) -> str:
    """為一筆 (商品 + 優惠訊號) 算出可去重的 promo_key。

    同一商品同型別同金額的優惠重複匯入會得到相同 key -> update 而非 insert。

    product_token 必須能『唯一識別該商品』—— 使用商品的 dedup_key
    (source|url 或 source|category|product_name)。
    注意:刻意『不』用 _normalize_model_key(product_name),因為它會移除所有非 ASCII
    字元,導致中文名稱不同、但 ASCII 片段(如 "750w" / "ddr5")相同的兩個商品
    產生相同 key 而被錯誤合併。改用 dedup_key 可保證不同商品不互相覆蓋。
    """
    parts = [
        (source or "").strip().lower(),
        signal.get("promo_type") or "",
        (product_token or "").strip().lower(),
        str(signal.get("discount_amount") if signal.get("discount_amount") is not None else ""),
        (signal.get("required_category") or "").lower(),
        str(signal.get("min_amount") if signal.get("min_amount") is not None else ""),
    ]
    return "|".join(parts)


def _actual_discount_signal(product: dict) -> dict | None:
    """由商品的 original_price / discount_price 直接判定『單品特價』訊號(權威來源)。

    條件:original_price 與 discount_price 皆有值且 discount_price < original_price。
    這是 actual_discount 的權威判定,避免只靠文字 ↘ 解析的誤差;明確標記它『不是 bundle』。
    """
    op = product.get("original_price")
    dp = product.get("discount_price")
    if op is None or dp is None or not (dp < op and op > 0):
        return None
    return {
        "promo_type": "actual_discount",
        "title": "單品特價",
        "promo_text": (product.get("product_name") or "").strip(),
        "discount_amount": op - dp,
        "discount_percent": round((op - dp) / op * 100, 1),
        "original_price": op,
        "promo_price": dp,
        "required_category": None,
        "required_keyword": None,
        "min_amount": None,
        "confidence": "high",
        "role": "target",
    }


def _upsert_one_promotion(
    conn: sqlite3.Connection,
    source: str,
    product_id: int,
    product_token: str,
    signal: dict,
    source_url: str = "",
) -> None:
    """寫入 / 更新單筆 promotion,並建立與商品的關聯(皆冪等)。

    product_token:唯一識別該商品的字串(商品 dedup_key),用於組 promo_key。
    """
    promo_key = _promo_key(source, product_token, signal)
    role = signal.get("role") or "unknown"
    if role not in _VALID_ROLES:
        role = "unknown"
    now = _now()

    existing = conn.execute(
        "SELECT id FROM promotions WHERE promo_key = ?", (promo_key,)
    ).fetchone()

    if existing is None:
        cur = conn.execute(
            """
            INSERT INTO promotions (
                source, promo_key, promo_type, title, promo_text,
                discount_amount, discount_percent, original_price, promo_price,
                required_category, required_keyword, min_items, source_url,
                confidence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source, promo_key, signal.get("promo_type"), signal.get("title"),
                signal.get("promo_text"), signal.get("discount_amount"),
                signal.get("discount_percent"), signal.get("original_price"),
                signal.get("promo_price"), signal.get("required_category"),
                signal.get("required_keyword"), signal.get("min_items"),
                source_url, signal.get("confidence"), now, now,
            ),
        )
        promo_id = cur.lastrowid
    else:
        promo_id = existing["id"]
        conn.execute(
            """
            UPDATE promotions SET
                promo_type = ?, title = ?, promo_text = ?, discount_amount = ?,
                discount_percent = ?, original_price = ?, promo_price = ?,
                required_category = ?, required_keyword = ?, min_items = ?,
                source_url = ?, confidence = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                signal.get("promo_type"), signal.get("title"), signal.get("promo_text"),
                signal.get("discount_amount"), signal.get("discount_percent"),
                signal.get("original_price"), signal.get("promo_price"),
                signal.get("required_category"), signal.get("required_keyword"),
                signal.get("min_items"), source_url, signal.get("confidence"),
                now, promo_id,
            ),
        )

    # 關聯(UNIQUE(promotion_id, product_id, product_role) -> 重複匯入不新增)
    link = conn.execute(
        "SELECT id FROM promotion_products WHERE promotion_id = ? AND product_id = ? "
        "AND product_role = ?",
        (promo_id, product_id, role),
    ).fetchone()
    if link is None:
        conn.execute(
            "INSERT INTO promotion_products (promotion_id, product_id, product_role, "
            "created_at) VALUES (?, ?, ?, ?)",
            (promo_id, product_id, role, now),
        )


def _delete_product_promotions_of_type(
    conn: sqlite3.Connection, product_id: int, promo_type: str
) -> None:
    """移除某商品某 promo_type 的關聯;若該 promotion 因此無任何關聯則一併刪除。

    用於『重新匯入後該商品已不再符合此優惠』時清掉殘留(stale)資料,
    確保 promotion 與商品『現況』一致(例如 CoolPC 同商品重複列出、其中一筆有特價、
    另一筆無特價;以最終 product 價格欄位為準)。
    """
    promo_ids = [
        r["promotion_id"]
        for r in conn.execute(
            "SELECT pp.promotion_id FROM promotion_products pp "
            "JOIN promotions p ON p.id = pp.promotion_id "
            "WHERE pp.product_id = ? AND p.promo_type = ?",
            (product_id, promo_type),
        ).fetchall()
    ]
    if not promo_ids:
        return
    conn.executemany(
        "DELETE FROM promotion_products WHERE promotion_id = ? AND product_id = ?",
        [(pid, product_id) for pid in promo_ids],
    )
    # 刪掉因此變成孤立(無任何關聯)的 promotion
    for pid in promo_ids:
        remaining = conn.execute(
            "SELECT COUNT(*) AS c FROM promotion_products WHERE promotion_id = ?", (pid,)
        ).fetchone()["c"]
        if remaining == 0:
            conn.execute("DELETE FROM promotions WHERE id = ?", (pid,))


def _sync_product_promotions(
    conn: sqlite3.Connection,
    product: dict,
    product_id: int,
    source: str,
) -> int:
    """為單一商品同步其所有優惠訊號(actual_discount 由價格欄位權威判定,其餘由文字解析)。

    Returns:
        實際處理(upsert)的 promotion 訊號數。
    """
    from pc_builder_agent.tools.ecommerce_scraper import _parse_promotion_signals

    product_name = (product.get("product_name") or "").strip()
    source_url = (product.get("url") or "").strip()
    category = (product.get("category") or "").strip()
    # 唯一識別該商品(避免 promo_key 因中文被移除而跨商品碰撞)
    product_token = _compute_dedup_key(source, source_url, category, product_name)

    signals: list[dict] = []
    seen_types: set[str] = set()

    # actual_discount:以價格欄位為權威來源(只取一筆)。
    # 若現況無特價,清掉該商品殘留的 actual_discount(處理重複列出、後者無特價的情況),
    # 確保 actual_discount promo 嚴格等同於商品價格欄位的特價狀態。
    ad = _actual_discount_signal(product)
    if ad is not None:
        signals.append(ad)
        seen_types.add("actual_discount")
    else:
        _delete_product_promotions_of_type(conn, product_id, "actual_discount")

    # 其餘文字訊號(同型別只取首筆,避免重複)。
    # actual_discount『只』承認價格欄位(original_price/discount_price)的權威判定,
    # 一律忽略文字版的 actual_discount —— 避免文字 ↘/原價 解析與實際價格欄位不一致時誤判
    # (例如某些 PSU 文字殘留價格,但商品價格欄位並無特價)。
    for sig in _parse_promotion_signals(_source_text_of(product)):
        ptype = sig.get("promo_type")
        if ptype == "actual_discount":
            continue
        if ptype in seen_types:
            continue
        seen_types.add(ptype)
        signals.append(sig)

    for sig in signals:
        _upsert_one_promotion(conn, source, product_id, product_token, sig, source_url)
    return len(signals)


def rebuild_promotions(db_path: str = DEFAULT_DB_PATH) -> dict[str, int]:
    """掃描既有 products,(重新)解析並同步所有 promotions。

    冪等:重複執行相同資料不會新增重複 promotion / 關聯(靠 promo_key 與關聯 UNIQUE)。
    不會刪除 products,也不影響 query_products / find_deals / recommend_pc_build。

    Returns:
        {"products_scanned", "signals_upserted"}。
    """
    conn = _connect(db_path)
    stats = {"products_scanned": 0, "signals_upserted": 0}
    try:
        _ensure_schema(conn)
        rows = conn.execute(
            f"SELECT {_PRODUCT_COLUMNS} FROM products"
        ).fetchall()
        for row in rows:
            product = _row_to_dict(row)
            stats["products_scanned"] += 1
            stats["signals_upserted"] += _sync_product_promotions(
                conn, product, product["id"], product.get("source") or ""
            )
        conn.commit()
    finally:
        conn.close()
    return stats


def count_promotions(db_path: str = DEFAULT_DB_PATH) -> dict[str, Any]:
    """回傳 promotions 統計:總數、各 promo_type 分布、關聯數。"""
    conn = _connect(db_path)
    try:
        _ensure_schema(conn)
        total = conn.execute("SELECT COUNT(*) AS c FROM promotions").fetchone()["c"]
        links = conn.execute("SELECT COUNT(*) AS c FROM promotion_products").fetchone()["c"]
        by_type_rows = conn.execute(
            "SELECT promo_type, COUNT(*) AS c FROM promotions GROUP BY promo_type "
            "ORDER BY c DESC"
        ).fetchall()
        by_type = {r["promo_type"]: r["c"] for r in by_type_rows}
        return {"total": total, "links": links, "by_type": by_type}
    finally:
        conn.close()


# 交給 LLM / 回覆使用者時,promotion 應保留的欄位(白名單)。
# 刻意『不』含 promotion internal id / product internal id / created_at / updated_at /
# dedup_key / model_key / promo_key 等內部欄位。
_PROMO_LLM_FIELDS = (
    "source",
    "promo_type",
    "title",
    "promo_text",
    "discount_amount",
    "discount_percent",
    "original_price",
    "promo_price",
    "required_category",
    "required_keyword",
    "confidence",
    "product_role",
    "product_name",
    "product_category",
    "product_price",
    "source_url",
)

# promo_type -> 對使用者的精確語意說明(避免把訊號講成保證折扣)。
_PROMO_TYPE_MEANING = {
    "actual_discount": "單品特價(原價>特價,可直接看到折扣金額)",
    "bundle_discount": "搭配折扣(例如搭主機板現省,需符合搭配條件才成立,僅供人工參考)",
    "combo": "組合/套裝優惠(整組販售,非單品折扣)",
    "add_on": "加購優惠(買主商品才能加價購)",
    "gift": "贈品(買就送,非價格折扣)",
    "threshold_gift": "滿額贈/滿額優惠",
    "text_promo": "文字型活動訊號(低信心,需登錄/活動頁,不可直接扣總價)",
}

# promo_type -> 附在 build item 上的 note(明確說明『未自動扣總價』,避免誤會已折抵)。
_PROMO_NOTE_BY_TYPE = {
    "actual_discount": "已反映在商品目前售價中,未額外扣總價",
    "bundle_discount": "需符合搭配條件,僅供人工參考,未自動扣總價",
    "combo": "組合/套裝優惠,需整組購買,未自動扣總價",
    "add_on": "加購優惠,需符合條件,未自動扣總價",
    "gift": "贈品活動,需人工確認,未自動扣總價",
    "threshold_gift": "滿額贈,需人工確認,未自動扣總價",
    "text_promo": "活動提醒,需人工確認,未自動扣總價",
}


def sanitize_promotion_for_llm(promo: dict) -> dict:
    """把一筆 promotion(已 join 商品)整理成可安全交給 LLM 的版本。

    只保留 _PROMO_LLM_FIELDS 白名單欄位,並補上 promo_type_meaning 說明,
    移除任何 internal id / 時間戳記 / dedup_key / model_key 等內部欄位。
    """
    if not isinstance(promo, dict):
        return {}
    out = {k: promo[k] for k in _PROMO_LLM_FIELDS if k in promo}
    pt = out.get("promo_type")
    if pt in _PROMO_TYPE_MEANING:
        out["promo_type_meaning"] = _PROMO_TYPE_MEANING[pt]
    return out


# join 後對外的安全欄位(不含任何 internal id)。INNER JOIN 確保『只回傳有 product link 的 promotion』。
_PROMO_JOIN_SELECT = """
    SELECT p.source, p.promo_type, p.title, p.promo_text, p.discount_amount,
           p.discount_percent, p.original_price, p.promo_price,
           p.required_category, p.required_keyword, p.confidence, p.source_url,
           pp.product_role,
           pr.product_name AS product_name, pr.category AS product_category,
           pr.price AS product_price
    FROM promotions p
    JOIN promotion_products pp ON pp.promotion_id = p.id
    JOIN products pr           ON pr.id = pp.product_id
"""

# confidence 排序:high -> medium -> low
_PROMO_ORDER = (
    " ORDER BY CASE p.confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
    "WHEN 'low' THEN 2 ELSE 3 END, p.discount_amount IS NULL, p.discount_amount DESC"
)


def _query_promotions(
    conn: sqlite3.Connection, clauses: list[str], params: list[Any], limit: int | None
) -> list[dict]:
    """共用:依條件 join 查 promotions(只回有 product link 者),回傳 sanitize 後 dict。"""
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = _PROMO_JOIN_SELECT + where + _PROMO_ORDER
    if limit is not None:
        sql += " LIMIT ?"
        params = params + [int(limit)]
    rows = conn.execute(sql, params).fetchall()
    return [sanitize_promotion_for_llm(_row_to_dict(r)) for r in rows]


def list_promotions(
    promo_type: str | None = None,
    category: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict]:
    """唯讀:依條件列出 promotions(只回傳『有關聯到 8 類商品』的 promotion)。

    Args:
        promo_type: 過濾優惠型別(actual_discount / bundle_discount / combo / add_on /
            gift / threshold_gift / text_promo)。
        category: 過濾『關聯商品』的類別(CPU/GPU/Motherboard/RAM/Storage/PSU/Case/Cooler)。
        keyword: 同時比對 promo_text 與關聯商品 product_name(LIKE)。
        limit: 回傳上限。
        db_path: 資料庫路徑。

    Returns:
        sanitize 後的 promotion dict 列表(不含任何 internal id);
        below_avg 不是 promotion,不會出現在此結果。
    """
    conn = _connect(db_path)
    try:
        _ensure_schema(conn)
        clauses: list[str] = []
        params: list[Any] = []
        if promo_type:
            clauses.append("lower(p.promo_type) = ?")
            params.append(promo_type.strip().lower())
        if category:
            clauses.append("lower(pr.category) = ?")
            params.append(category.strip().lower())
        if keyword:
            kw = f"%{keyword.strip().lower()}%"
            clauses.append("(lower(p.promo_text) LIKE ? OR lower(pr.product_name) LIKE ?)")
            params.extend([kw, kw])
        return _query_promotions(conn, clauses, params, limit)
    finally:
        conn.close()


def get_promotions_for_product(
    product_id: int | None = None,
    product_name: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict]:
    """唯讀:查某商品關聯的所有 promotions(可用 product_id 或 product_name)。

    至少需提供 product_id 或 product_name 其中一個;兩者皆空回傳空列表。
    回傳 sanitize 後的 promotion dict(含 product_role),不含 internal id。
    """
    if product_id is None and not product_name:
        return []
    conn = _connect(db_path)
    try:
        _ensure_schema(conn)
        clauses: list[str] = []
        params: list[Any] = []
        if product_id is not None:
            clauses.append("pp.product_id = ?")
            params.append(int(product_id))
        if product_name:
            clauses.append("lower(pr.product_name) = ?")
            params.append(product_name.strip().lower())
        return _query_promotions(conn, clauses, params, limit=None)
    finally:
        conn.close()


def _annotate_promo_note(promo: dict) -> dict:
    """為一筆 promotion 補上 note(說明此優惠未自動扣總價);回傳新 dict。"""
    out = dict(promo)
    note = _PROMO_NOTE_BY_TYPE.get(out.get("promo_type"))
    if note:
        out["note"] = note
    return out


def attach_promotions_to_products(
    products: list[dict], db_path: str = DEFAULT_DB_PATH
) -> list[dict]:
    """為一組商品(例如完整 build 的各零件)附上其 promotions(唯讀、純附加資訊)。

    不修改任何價格、不套用折扣;只在每筆商品上新增 ``promotions`` 欄位
    (該商品關聯到的 sanitize 後 promotion 列表,每筆附 note 說明『未自動扣總價』,
    無關聯則為空列表)。以 product_name 比對(build 項目通常只帶 product_name,不帶 internal id)。

    Returns:
        新的 list(每個元素是 dict 的淺複製 + promotions 欄位);不修改傳入物件。
    """
    out: list[dict] = []
    for p in products:
        if not isinstance(p, dict):
            out.append(p)
            continue
        item = dict(p)
        name = item.get("product_name")
        promos = (
            get_promotions_for_product(product_name=name, db_path=db_path) if name else []
        )
        item["promotions"] = [_annotate_promo_note(pr) for pr in promos]
        out.append(item)
    return out


def build_promotion_summary(build_items: list[dict]) -> dict[str, Any]:
    """彙整一份(已 attach promotions 的)build,產生 promotion_summary。

    重要:這只是『參考資訊摘要』,total_price_includes_auto_discount 永遠為 False
    —— promotions 不會自動扣總價、不影響選品。
    """
    by_type: dict[str, int] = {}
    count = 0
    for item in build_items:
        if not isinstance(item, dict):
            continue
        for pr in item.get("promotions") or []:
            count += 1
            pt = pr.get("promo_type") or "unknown"
            by_type[pt] = by_type.get(pt, 0) + 1
    return {
        "has_promotions": count > 0,
        "count": count,
        "by_type": by_type,
        "actual_discount_count": by_type.get("actual_discount", 0),
        "bundle_discount_count": by_type.get("bundle_discount", 0),
        "text_promo_count": by_type.get("text_promo", 0),
        "total_price_includes_auto_discount": False,
        "note": (
            "promotions are shown as reference only; total_price is NOT automatically "
            "reduced. 優惠僅供參考,總價未自動扣除任何搭配折扣或活動折扣。"
        ),
    }


def _mem_gen_ok(a: str | None, b: str | None) -> bool:
    """兩個記憶體世代是否相容(容忍 'DDR4_or_DDR5');任一缺失視為『不衝突』。"""
    if not a or not b:
        return True
    if "DDR4_or_DDR5" in (a, b):
        other = b if a == "DDR4_or_DDR5" else a
        return other in ("DDR4", "DDR5", "DDR4_or_DDR5")
    return a == b


def _bundle_compat_status(
    cpu_socket: str | None, cpu_mem: str | None,
    mb_socket: str | None, mb_mem: str | None,
) -> str:
    """判斷 CPU 與 Motherboard 是否相容,回傳 'compatible' / 'incompatible' / 'unknown'。

    以 socket 為主要依據(AM5 CPU 只能搭 AM5 board);socket 任一缺失時,
    才退而以 memory_generation 的明顯錯配(如 DDR5 vs DDR4)做保守判斷。
    """
    if cpu_socket and mb_socket:
        if cpu_socket != mb_socket:
            return "incompatible"
        if not _mem_gen_ok(cpu_mem, mb_mem):
            return "incompatible"
        return "compatible"
    # socket 缺一邊:只能用記憶體世代抓明顯錯配,無法確認則回 unknown
    if cpu_mem and mb_mem and not _mem_gen_ok(cpu_mem, mb_mem):
        return "incompatible"
    return "unknown"


def estimate_promotion_adjusted_total(
    build_result: dict, db_path: str | None = None
) -> dict[str, Any]:
    """為一份(已 attach promotions 的)build 試算『可計算優惠後的預估總價』。

    Args:
        build_result: recommend_pc_build() 的結果,且其 build 各項已帶 promotions。
        db_path: 僅為與其他 ecommerce helper 的 API 一致而保留的『可選』參數;
            **本函式不讀也不寫 DB**(試算完全根據 build_result 內已 attach 的 promotions),
            傳入此參數不會改變任何行為,只是避免呼叫端誤傳時報錯。

    重要安全規則:
    - **不**覆蓋 total_price;只回傳額外的 estimated_* 欄位。
    - 只有『可確認條件成立』的 high-confidence bundle_discount 才計入折抵:
        * confidence == "high"
        * discount_amount 存在且 > 0
        * required_category 必須真的出現在這份 build 的零件類別中
          (若 required_keyword 有值且 required_category 為空,改以關鍵字比對 build 零件)
    - actual_discount:不重複扣(已反映在商品目前售價),不計入 estimated_discount。
    - text_promo / combo / add_on / gift / threshold_gift:不自動折抵,列入 unapplied_promotions。
    - below_avg:不是 promotion,本來就不在 promotions 中,不參與。

    Returns:
        dict,含 estimated_discount_amount / estimated_final_price /
        total_price_includes_auto_discount / estimated_final_price_applies_calculable_promotions /
        applied_promotions / unapplied_promotions / promotion_price_note。
    """
    build = build_result.get("build") or []
    total_price = build_result.get("total_price") or 0

    # build 中實際出現的零件類別(供 bundle_discount required_category 條件確認)
    build_categories = {
        (it.get("category") or "").lower() for it in build if isinstance(it, dict)
    }

    # platform 解析器:優先用 build item 上的 socket / memory_generation
    # (recommend_pc_build 已提供);缺失且有 db_path 時,才以 product_name 查 DB specs。
    # 這是 db_path 唯一的『讀 DB』用途 —— 為了驗證 CPU/Motherboard 平台相容性。
    _spec_cache: dict[str, dict] = {}
    _conn = _connect(db_path) if db_path else None

    def platform_of(item: dict) -> tuple[str | None, str | None]:
        socket = item.get("socket")
        mem = item.get("memory_generation")
        name = item.get("product_name")
        if (not socket or not mem) and _conn is not None and name:
            if name not in _spec_cache:
                row = _conn.execute(
                    "SELECT specs FROM products WHERE product_name = ? LIMIT 1", (name,)
                ).fetchone()
                _spec_cache[name] = _specs_of(_row_to_dict(row)) if row else {}
            sp = _spec_cache[name]
            socket = socket or sp.get("socket")
            mem = mem or sp.get("memory_generation")
        return socket, mem

    applied: list[dict] = []
    unapplied: list[dict] = []
    estimated_discount = 0

    try:
        for it in build:
            if not isinstance(it, dict):
                continue
            affected = it.get("product_name")
            for pr in it.get("promotions") or []:
                ptype = pr.get("promo_type")
                if ptype == "actual_discount":
                    # 已反映在目前售價,不重複扣、不列入 applied/unapplied
                    continue
                if ptype == "bundle_discount":
                    amt = pr.get("discount_amount")
                    conf = pr.get("confidence")
                    req_cat = (pr.get("required_category") or "").lower()
                    req_kw = pr.get("required_keyword") or ""

                    def add_unapplied(reason: str) -> None:
                        unapplied.append({
                            "promo_type": ptype,
                            "promo_text": pr.get("promo_text"),
                            "affected_product": affected,
                            "reason": reason,
                        })

                    # 1) 基本條件:high 信心 + 有正折扣金額
                    if not (isinstance(amt, int) and amt > 0):
                        add_unapplied("Bundle discount has no calculable discount_amount")
                        continue
                    if conf != "high":
                        add_unapplied(f"Bundle discount confidence is '{conf}', not high")
                        continue

                    # 2) 找出 required_category(通常 Motherboard)對應的 build 零件
                    if req_cat:
                        targets = [x for x in build if isinstance(x, dict)
                                   and (x.get("category") or "").lower() == req_cat]
                    elif req_kw:
                        targets = [x for x in build if isinstance(x, dict)
                                   and (req_kw in (x.get("product_name") or "")
                                        or req_kw in (x.get("category") or ""))]
                    else:
                        targets = []
                    if not targets:
                        add_unapplied(
                            f"Required category '{pr.get('required_category')}' / keyword "
                            f"'{req_kw}' not present in build")
                        continue

                    # 3) 相容性守門:bundle 掛在 CPU 上,檢查 CPU socket 與目標主機板 socket 相容
                    cpu_socket, cpu_mem = platform_of(it)
                    comp = incomp = unknown = None
                    for mb in targets:
                        mb_socket, mb_mem = platform_of(mb)
                        status = _bundle_compat_status(cpu_socket, cpu_mem, mb_socket, mb_mem)
                        if status == "compatible":
                            comp = (mb, mb_socket); break
                        if status == "incompatible":
                            incomp = incomp or (mb, mb_socket)
                        else:
                            unknown = unknown or (mb, mb_socket)

                    if comp is not None:
                        mb, mb_socket = comp
                        estimated_discount += amt
                        applied.append({
                            "promo_type": ptype,
                            "promo_text": pr.get("promo_text"),
                            "discount_amount": amt,
                            "applied_reason": (
                                f"Build contains required category {pr.get('required_category')} "
                                f"and motherboard socket {mb_socket} matches CPU socket {cpu_socket}"),
                            "affected_product": affected,
                            "matched_product": mb.get("product_name"),
                            "required_category": pr.get("required_category"),
                            "required_keyword": pr.get("required_keyword"),
                            "confidence": conf,
                        })
                    elif unknown is not None and incomp is None:
                        add_unapplied(
                            "cannot confirm CPU/Motherboard compatibility (missing socket specs); "
                            "not applied automatically")
                    elif incomp is not None:
                        mb, mb_socket = incomp
                        add_unapplied(
                            f"Required category Motherboard exists, but selected motherboard socket "
                            f"{mb_socket} does not match CPU socket {cpu_socket}")
                    else:
                        add_unapplied(
                            "cannot confirm CPU/Motherboard compatibility; not applied automatically")
                    continue
                else:
                    # text_promo / combo / add_on / gift / threshold_gift -> 不自動折抵
                    unapplied.append({
                        "promo_type": ptype,
                        "promo_text": pr.get("promo_text"),
                        "affected_product": affected,
                        "reason": (
                            "Text/activity promotion requires manual confirmation; not applied to total"
                            if ptype == "text_promo"
                            else f"'{ptype}' is not a calculable single-item discount; not applied to total"
                        ),
                    })
    finally:
        if _conn is not None:
            _conn.close()

    estimated_final_price = total_price - estimated_discount
    return {
        "estimated_discount_amount": estimated_discount,
        "estimated_final_price": estimated_final_price,
        "total_price_includes_auto_discount": False,
        "estimated_final_price_applies_calculable_promotions": bool(applied),
        "applied_promotions": applied,
        "unapplied_promotions": unapplied,
        "promotion_price_note": (
            "estimated_final_price only applies calculable high-confidence bundle discounts "
            "whose required category is present in the build. Actual checkout price may differ. "
            "原始 total_price 不變;estimated_final_price 僅試算可確認的高信心搭配折扣,"
            "實際結帳價格仍以商城為準。"
        ),
    }


# 搭板優惠配對結果對外的安全欄位白名單(不含任何 internal id)。
_BUNDLE_PAIR_FIELDS = (
    "cpu_product_name", "cpu_price", "cpu_socket", "cpu_memory_generation",
    "motherboard_product_name", "motherboard_price", "motherboard_socket",
    "motherboard_memory_generation", "promo_type", "promo_text", "discount_amount",
    "required_category", "confidence", "total_price", "estimated_discount_amount",
    "estimated_final_price", "compatibility_status", "compatibility_reason",
    "promotion_price_note", "source",
)


def find_compatible_bundle_discount_pairs(
    promo_type: str = "bundle_discount",
    cpu_keyword: str | None = None,
    motherboard_keyword: str | None = None,
    prefer_platform: str | None = None,
    max_total_price: int | None = None,
    limit: int = 10,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict]:
    """deterministic、唯讀:找出『有搭板折扣的 CPU + 相容主機板』的可試算配對。

    流程(完全不寫 DB、不改任何價格):
    1. 取有 bundle_discount 的 CPU(透過 list_promotions)。
    2. 讀 CPU specs(socket / platform / memory_generation)。
    3. 在 Motherboard 中找『socket 相同且記憶體世代不衝突』的相容板(取最便宜一張)。
    4. 用 estimate_promotion_adjusted_total() 做相容性守門 + 折抵試算。
    5. **只回傳真正相容且折抵 > 0 的配對**;不相容 / 無法確認 / 折抵 0 一律不列入。

    回傳每筆只含 _BUNDLE_PAIR_FIELDS 白名單欄位(不含任何 internal id)。
    """
    # 取所有 bundle_discount 優惠(數量不多,給高 limit 一次撈齊)
    promos = list_promotions(promo_type=promo_type, keyword=cpu_keyword,
                             limit=200, db_path=db_path)
    # 載入 CPU / Motherboard 池並建索引(specs 在 query_products 結果中為 JSON 字串)
    cpus = {c["product_name"]: c for c in
            query_products(category="CPU", limit=5000, db_path=db_path)}
    mbs = query_products(category="Motherboard", keyword=motherboard_keyword,
                         limit=5000, db_path=db_path)

    results: list[dict] = []
    seen: set[str] = set()
    for promo in promos:
        if (promo.get("product_category") or "").lower() != "cpu":
            continue  # 搭板折扣應掛在 CPU 上
        cpu_name = promo.get("product_name")
        if not cpu_name or cpu_name in seen:
            continue
        cpu = cpus.get(cpu_name)
        if not cpu or cpu.get("price") is None:
            continue
        csp = _specs_of(cpu)
        cpu_socket = csp.get("socket")
        cpu_mem = csp.get("memory_generation")
        if not cpu_socket:
            continue  # 無法確認 CPU 平台 -> 保守跳過,不自動套用
        if prefer_platform and cpu_socket != prefer_platform.strip().upper():
            continue

        # 找相容主機板(socket 相同、記憶體世代不衝突),取最便宜
        compat_mbs = []
        for m in mbs:
            if m.get("price") is None:
                continue
            msp = _specs_of(m)
            if msp.get("socket") == cpu_socket and _mem_gen_ok(cpu_mem, msp.get("memory_generation")):
                compat_mbs.append((m, msp))
        if not compat_mbs:
            continue  # 查無相容板 -> 不硬湊
        mb, msp = min(compat_mbs, key=lambda x: x[0]["price"])

        # 組 mini build 並用守門邏輯試算(item 直接帶 socket,estimate 不需再查 DB)
        cpu_item = {"category": "CPU", "product_name": cpu_name, "price": cpu["price"],
                    "socket": cpu_socket, "memory_generation": cpu_mem}
        mb_item = {"category": "Motherboard", "product_name": mb["product_name"],
                   "price": mb["price"], "socket": msp.get("socket"),
                   "memory_generation": msp.get("memory_generation")}
        items = attach_promotions_to_products([cpu_item, mb_item], db_path=db_path)
        total = int(cpu["price"]) + int(mb["price"])
        if max_total_price is not None and total > int(max_total_price):
            continue
        est = estimate_promotion_adjusted_total({"total_price": total, "build": items})
        if est["estimated_discount_amount"] <= 0 or not est["applied_promotions"]:
            continue  # 守門未通過(不相容/無法確認)-> 不列入主要結果
        ap = est["applied_promotions"][0]

        results.append({
            "cpu_product_name": cpu_name,
            "cpu_price": cpu["price"],
            "cpu_socket": cpu_socket,
            "cpu_memory_generation": cpu_mem,
            "motherboard_product_name": mb["product_name"],
            "motherboard_price": mb["price"],
            "motherboard_socket": msp.get("socket"),
            "motherboard_memory_generation": msp.get("memory_generation"),
            "promo_type": promo.get("promo_type"),
            "promo_text": promo.get("promo_text"),
            "discount_amount": est["estimated_discount_amount"],
            "required_category": promo.get("required_category"),
            "confidence": promo.get("confidence"),
            "total_price": total,
            "estimated_discount_amount": est["estimated_discount_amount"],
            "estimated_final_price": est["estimated_final_price"],
            "compatibility_status": "compatible",
            "compatibility_reason": ap.get("applied_reason"),
            "promotion_price_note": est["promotion_price_note"],
            "source": promo.get("source"),
        })
        seen.add(cpu_name)
        if len(results) >= int(limit):
            break

    results.sort(key=lambda r: r["estimated_final_price"])
    return results


# ============================================================================
# 完整 PC 菜單推薦(deterministic build engine)
# ============================================================================

# 各用途的預算分配權重(各類別佔總目標的比例)
_GAMING_WEIGHTS = {
    "GPU": 0.33, "CPU": 0.17, "Motherboard": 0.10, "RAM": 0.10,
    "Storage": 0.09, "PSU": 0.08, "Case": 0.065, "Cooler": 0.065,
}
# 文書用途:不配獨立顯卡(以內顯為主),預算重心在 CPU/平台/儲存
_OFFICE_WEIGHTS = {
    "CPU": 0.24, "Motherboard": 0.16, "RAM": 0.16, "Storage": 0.16,
    "PSU": 0.12, "Case": 0.10, "Cooler": 0.06,
}
_OFFICE_REASONABLE_TOTAL = 16000   # 文書機合理總價上限參考
_GAMING_MIN_BUDGET = 15000         # 一般遊戲機合理最低預算
_4K_MIN_BUDGET = 40000             # 4K 遊戲機合理最低預算
_BUILD_PLATFORM_ORDER = ("AM5", "LGA1700", "AM4")


def _specs_of(row: dict) -> dict:
    s = row.get("specs")
    if isinstance(s, str):
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return {}
    return s or {}


def _cap_to_gb(capstr: str | None) -> int | None:
    """'1TB'->1000、'500GB'->500、'480GB'->480。"""
    if not capstr:
        return None
    m = re.match(r"(\d+)\s*(TB|GB)", capstr, re.IGNORECASE)
    if not m:
        return None
    n = int(m.group(1))
    return n * 1000 if m.group(2).upper() == "TB" else n


def _ram_gb(capstr: str | None) -> int | None:
    if not capstr:
        return None
    m = re.match(r"(\d+)\s*GB", capstr, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _mem_compatible(ram_mem: str | None, mb_mem: str | None) -> bool:
    if not ram_mem or not mb_mem:
        return False
    if mb_mem in ("DDR4", "DDR5"):
        return ram_mem == mb_mem
    if mb_mem == "DDR4_or_DDR5":
        return ram_mem in ("DDR4", "DDR5")
    return False


def _classify_use_case(use_case: str | None) -> str:
    t = (use_case or "").lower()
    if any(k in t for k in ("4k", "2160", "4k_gaming")):
        return "4k_gaming"
    if any(k in t for k in ("office", "文書", "辦公")):
        return "office"
    # gaming / 遊戲 / 電競 / 2k / 預設
    return "gaming"


def _pick_near(pool: list[dict], target: float) -> dict | None:
    """從 pool 選價格最接近 target 的商品;同距離取較便宜。"""
    candidates = [p for p in pool if p.get("price") is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda p: (abs(p["price"] - target), p["price"]))


def _mb_mem_from_name(name: str | None) -> str | None:
    """由主機板商品名判斷記憶體世代(DDR4/DDR5);辨識 DDR4/DDR5 與縮寫 D4/D5。

    用途:即使正式 DB 的 specs 尚未重建(可能把 D4 板誤標 DDR4_or_DDR5 或 DDR5),
    也能以商品名 fallback 修正,避免 MB/RAM 世代錯配。判不出回 None。
    """
    if not name:
        return None
    t = name.upper()
    if "DDR5" in t or re.search(r"\bD5\b", t):
        return "DDR5"
    if "DDR4" in t or re.search(r"\bD4\b", t):
        return "DDR4"
    return None


def _effective_mb_mem(mb_row: dict) -> str | None:
    """主機板的『有效』記憶體世代:商品名明確的 DDR4/DDR5/D4/D5 優先,其次才用 specs。

    這樣即使 specs 為 DDR4_or_DDR5 或舊資料誤標,只要名稱明確就以名稱為準。
    """
    name_mem = _mb_mem_from_name(mb_row.get("product_name"))
    if name_mem:
        return name_mem
    return _specs_of(mb_row).get("memory_generation")


def _is_ssd_storage(row: dict) -> bool:
    """判斷 Storage 是否為 SSD 類(NVMe / M.2 / PCIe / 2.5吋 SSD);純 HDD 回 False。

    gaming / 4k_gaming 主要儲存只接受 SSD 類:有 SSD 訊號且不是純 HDD。
    """
    sp = _specs_of(row)
    name = (row.get("product_name") or "")
    text = (name + " " + (sp.get("source_text") or "")).upper()
    ssd_sig = (
        bool(re.search(r"SSD|NVME|M\.2|PCIE|GEN\s?[345]", text))
        or sp.get("interface") in ("NVMe", "PCIe 5.0", "PCIe 4.0", "PCIe 3.0")
        or sp.get("form_factor") == "M.2"
        or (sp.get("interface") == "SATA" and "SSD" in text)
        or bool(re.search(r"2\.5\s*吋\s*SSD|2\.5吋.*SSD", name))
    )
    hdd_sig = bool(re.search(r"HDD|5400\s*轉|7200\s*轉|新梭魚|3\.5\s*吋|機械", text))
    if hdd_sig and not ssd_sig:
        return False
    return ssd_sig


def _cpu_has_igpu(row: dict) -> bool:
    """保守判斷 CPU 是否內建顯示(integrated graphics)。

    規則(寧可保守判 False,避免無顯示輸出):
    - 含「無內顯」-> False;含「內顯/具內顯」-> True。
    - Intel iX-NNNN:結尾不含 F -> True(非 F 通常有 UHD 內顯);含 F -> False。
      Core Ultra:非 F -> True;F -> False。
    - AMD:型號含 G / GT(如 5600G/5500GT/8500G/8700G)-> True;含 F(7500F/8400F)-> False。
      其餘 AMD 一般 Ryzen 一律保守視為『無法確認』-> False(除非名稱明寫內顯)。
    """
    name = (row.get("product_name") or "")
    sp = _specs_of(row)
    full = (name + " " + (sp.get("source_text") or "")).upper()
    if "無內顯" in name or "無內顯" in (sp.get("source_text") or ""):
        return False
    if "內顯" in full:  # 涵蓋「具內顯」「內顯」
        return True
    # Intel Core Ultra
    if "CORE ULTRA" in full or re.search(r"\bULTRA\s?\d\s?2\d\d", full):
        return not re.search(r"ULTRA\s?\d\s?2\d\d\s*F", full)
    # Intel Core iX-NNNN(含縮寫 i5-12400 / i5-12400F)
    m = re.search(r"\bI[3579][\s-]?\d{4,5}([A-Z]*)", full)
    if m:
        return "F" not in m.group(1)
    # AMD:G/GT 有內顯;F 無內顯;其餘保守 False
    if re.search(r"\d{3,4}\s?G[T]?\b", full):
        return True
    return False


def recommend_pc_build(
    budget: int,
    use_case: str = "gaming",
    db_path: str = DEFAULT_DB_PATH,
    prefer_platform: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """組出一套平台一致的完整 PC 菜單,並計算總價與預算佔比(deterministic)。

    Returns dict:ok / use_case / budget / budget_min / budget_max / total_price /
      budget_usage_percent / in_budget_range / platform / build(list) /
      compatibility / warnings / explanation。
    """
    budget = int(budget)
    uc = _classify_use_case(use_case)
    budget_min = int(budget * 0.8)
    budget_max = int(budget * 1.2)
    warnings: list[str] = []

    if budget <= 0:
        return {"ok": False, "use_case": uc, "budget": budget, "warnings": ["預算需大於 0"],
                "build": [], "total_price": 0, "explanation": "未提供有效預算。"}

    # --- 合理性 gating:決定『組裝目標總價』target_total(不硬湊) ---
    if uc == "office":
        target_total = min(budget, _OFFICE_REASONABLE_TOTAL)
        if budget > _OFFICE_REASONABLE_TOTAL * 1.3:
            warnings.append(
                f"文書用途通常不需花到 {budget} 元;合理預算約 {_OFFICE_REASONABLE_TOTAL} 元上下,"
                f"以下依文書需求配置,不硬湊到您的預算。")
    elif uc == "4k_gaming":
        target_total = budget
        if budget < _4K_MIN_BUDGET:
            warnings.append(
                f"4K 遊戲機建議預算約 {_4K_MIN_BUDGET} 元以上;{budget} 元偏低,"
                f"以下為此預算內的最佳嘗試,但可能無法穩定 4K。")
    else:  # gaming
        target_total = budget
        if budget < _GAMING_MIN_BUDGET:
            warnings.append(
                f"一般遊戲機建議預算約 {_GAMING_MIN_BUDGET} 元以上;{budget} 元偏低,"
                f"以下為此預算內的最佳嘗試。")

    weights = _OFFICE_WEIGHTS if uc == "office" else _GAMING_WEIGHTS
    gaming = uc != "office"

    # --- 載入各類別商品池(含 gaming 最低規格過濾) ---
    def pool(cat: str) -> list[dict]:
        return query_products(category=cat, limit=2000, db_path=db_path)

    cpu_pool = [c for c in pool("CPU") if _specs_of(c).get("socket")]
    mb_pool = [m for m in pool("Motherboard") if _specs_of(m).get("socket")]
    ram_all = pool("RAM")
    gpu_pool = pool("GPU")
    storage_all = pool("Storage")
    psu_all = pool("PSU")
    case_pool = pool("Case")
    cooler_pool = pool("Cooler")

    # gaming RAM:DDR4/DDR5 且 >=16GB(不主推 DDR3 / 8GB)
    def ram_ok(r: dict) -> bool:
        s = _specs_of(r)
        g = _ram_gb(s.get("capacity"))
        return s.get("memory_generation") in ("DDR4", "DDR5") and (g is not None and g >= 16)
    ram_pool = [r for r in ram_all if ram_ok(r)] or ram_all  # 退而求其次仍有 RAM

    # gaming Storage:必須是 SSD 類(NVMe/M.2/PCIe/2.5吋 SSD)且 >=480GB;純 HDD 不可當主要儲存。
    def st_ok(s: dict) -> bool:
        sp = _specs_of(s)
        cap = _cap_to_gb(sp.get("capacity"))
        if cap is None or cap < 480:
            return False
        if gaming and not _is_ssd_storage(s):  # gaming/4k:排除純 HDD(5400/7200轉/新梭魚/3.5吋)
            return False
        return True
    storage_pool = [s for s in storage_all if st_ok(s)] or storage_all

    # PSU:有獨顯時 >=550W
    def psu_ok(p: dict) -> bool:
        w = _specs_of(p).get("wattage")
        return w is not None and w >= 550
    psu_pool = [p for p in psu_all if psu_ok(p)] if gaming else psu_all
    if not psu_pool:
        psu_pool = psu_all

    if not gpu_pool:
        warnings.append("資料庫查無顯示卡。")

    platforms = [prefer_platform] if prefer_platform else list(_BUILD_PLATFORM_ORDER)

    best = None
    for plat in platforms:
        cpus = [c for c in cpu_pool if _specs_of(c).get("socket") == plat]
        if not cpus:
            continue
        # office(無獨顯)優先選『有內顯』的 CPU,確保有顯示輸出
        if uc == "office":
            igpu_cpus = [c for c in cpus if _cpu_has_igpu(c)]
            cpu_candidates = igpu_cpus or cpus
        else:
            cpu_candidates = cpus
        cpu = _pick_near(cpu_candidates, target_total * weights["CPU"])
        socket = _specs_of(cpu).get("socket")
        mbs = [m for m in mb_pool if _specs_of(m).get("socket") == socket]
        if not mbs:
            continue
        mb = _pick_near(mbs, target_total * weights["Motherboard"])
        mb_mem = _effective_mb_mem(mb)  # 以商品名 DDR4/DDR5/D4/D5 優先,修正舊 specs 誤標
        rams = [r for r in ram_pool if _mem_compatible(_specs_of(r).get("memory_generation"), mb_mem)]
        if not rams:
            continue
        ram = _pick_near(rams, target_total * weights["RAM"])
        # 最終守門:再次確認 RAM 與主機板記憶體世代相容,不相容則放棄此平台
        if not _mem_compatible(_specs_of(ram).get("memory_generation"), mb_mem):
            continue

        parts: dict[str, dict] = {"CPU": cpu, "Motherboard": mb, "RAM": ram}
        if gaming and gpu_pool:
            parts["GPU"] = _pick_near(gpu_pool, target_total * weights["GPU"])
        if storage_pool:
            parts["Storage"] = _pick_near(storage_pool, target_total * weights["Storage"])
        if psu_pool:
            parts["PSU"] = _pick_near(psu_pool, target_total * weights["PSU"])
        if case_pool:
            parts["Case"] = _pick_near(case_pool, target_total * weights["Case"])
        if cooler_pool:
            parts["Cooler"] = _pick_near(cooler_pool, target_total * weights["Cooler"])

        # display output guard:沒有 GPU 的 build,CPU 必須有內顯;否則加一張最便宜的顯卡
        cpu_igpu = _cpu_has_igpu(cpu)
        gpu_added_for_display = False
        if "GPU" not in parts and not cpu_igpu and gpu_pool:
            cheap_gpu = _pick_near(gpu_pool, 0)  # 最便宜的顯卡作為顯示輸出
            if cheap_gpu:
                parts["GPU"] = cheap_gpu
                gpu_added_for_display = True

        def total_of(pp: dict) -> int:
            return sum(int(x["price"]) for x in pp.values() if x and x.get("price"))

        # --- 調整:用 GPU(gaming)或 CPU 升/降價,讓總價靠近預算 [budget_min, budget_max] ---
        def adjust(pp: dict) -> dict:
            if uc == "office":
                return pp  # 文書不硬湊
            for cat in ("GPU", "CPU"):
                if cat not in pp:
                    continue
                cat_pool = sorted(
                    (gpu_pool if cat == "GPU" else cpus),
                    key=lambda x: x["price"] if x.get("price") else 0,
                )
                if not cat_pool:
                    continue
                # 對 CPU 要維持 socket 一致(cpus 已是同平台)
                for _ in range(40):
                    t = total_of(pp)
                    if budget_min <= t <= budget_max:
                        return pp
                    cur = pp[cat]
                    try:
                        idx = cat_pool.index(cur)
                    except ValueError:
                        idx = 0
                    if t < budget_min and idx < len(cat_pool) - 1:
                        pp[cat] = cat_pool[idx + 1]  # 升級
                    elif t > budget_max and idx > 0:
                        pp[cat] = cat_pool[idx - 1]  # 降級
                    else:
                        break
            return pp

        parts = adjust(parts)
        total = total_of(parts)
        # 評分:在區間內最佳;否則總價離預算最近
        in_range = budget_min <= total <= budget_max
        score = (0 if in_range else 1, abs(total - budget))
        if best is None or score < best["score"]:
            best = {"platform": plat, "parts": parts, "total": total,
                    "in_range": in_range, "score": score, "mb_mem": mb_mem,
                    "cpu_igpu": cpu_igpu, "gpu_added_for_display": gpu_added_for_display}

    if best is None:
        return {"ok": False, "use_case": uc, "budget": budget, "budget_min": budget_min,
                "budget_max": budget_max, "build": [], "total_price": 0,
                "warnings": warnings + ["找不到可組成相容平台的完整菜單(資料庫零件不足)。"],
                "explanation": "無法組出相容的 CPU/主機板/RAM 平台。"}

    # --- 組裝輸出 ---
    order = ["CPU", "Cooler", "Motherboard", "RAM", "GPU", "Storage", "PSU", "Case"]
    build = []
    for cat in order:
        p = best["parts"].get(cat)
        if not p:
            continue
        sp = _specs_of(p)
        # 主機板記憶體世代以『有效值』(名稱優先)輸出,避免舊 specs 誤標
        mem_gen = _effective_mb_mem(p) if cat == "Motherboard" else sp.get("memory_generation")
        build.append({
            "category": cat,
            "product_name": p.get("product_name"),
            "model": p.get("model"),
            "price": p.get("price"),
            "source": p.get("source"),
            "platform": sp.get("platform"),
            "socket": sp.get("socket"),
            "memory_generation": mem_gen,
        })
    total = best["total"]
    usage = round(total / budget * 100, 1) if budget else None

    compat = (f"平台 {best['platform']};CPU/主機板 socket 一致;"
              f"RAM 世代={best['mb_mem']}(已與主機板相容)。"
              f"空冷高度 / AIO 水冷排尺寸 / socket 扣具 / 機殼支援仍需人工確認。")
    # 顯示輸出說明(display output guard)
    if "GPU" not in best["parts"]:
        if best.get("cpu_igpu"):
            compat += " 未含獨立顯卡,使用 CPU 內顯作為顯示輸出。"
        else:
            warnings.append(
                "所選 CPU 無內顯,且資料庫查無可加入的顯示卡;此配置可能沒有顯示輸出,"
                "請改選有內顯的 CPU 或自行加裝獨立顯卡。")
    elif best.get("gpu_added_for_display"):
        compat += " 所選 CPU 無內顯,已加入一張入門獨立顯卡作為顯示輸出。"
    elif not gaming:
        compat += " 文書配置以內顯為主。"

    expl_bits = [f"目標用途={uc};預算 {budget}(合理區間 {budget_min}~{budget_max})。",
                 f"總價 {total},佔預算 {usage}%。",
                 "落在 80%~120% 區間。" if best["in_range"] else "未落在 80%~120% 區間(原因見 warnings/說明)。"]
    return {
        "ok": True,
        "use_case": uc,
        "budget": budget,
        "budget_min": budget_min,
        "budget_max": budget_max,
        "total_price": total,
        "budget_usage_percent": usage,
        "in_budget_range": best["in_range"],
        "platform": best["platform"],
        "build": build,
        "compatibility": compat,
        "warnings": warnings,
        "explanation": " ".join(expl_bits),
    }


def load_seed_products(db_path: str = DEFAULT_DB_PATH) -> dict[str, int]:
    """
    從 ecommerce_seed.DEFAULT_SEED_PRODUCTS 匯入示範資料(不讀 CSV)。

    內部會先 init_db,再 upsert,因此可重複執行;相同資料再次匯入只會 update,
    不會重複新增,也不會在價格未變時灌爆 price_history。

    Returns:
        upsert_products 的統計 dict。
    """
    # 延遲 import,避免在不需要 seed 時也載入資料模組
    from pc_builder_agent.tools.ecommerce_seed import DEFAULT_SEED_PRODUCTS

    init_db(db_path)
    return upsert_products(DEFAULT_SEED_PRODUCTS, db_path=db_path)


# ============================================================================
# 互動式零組件候選推薦(deterministic;Phase Simplify-B)
# ============================================================================
# 設計:依「目前已選零件 + 指定平台」推導出 deterministic 的相容性約束
# (socket / memory_generation / brand),只在約束內挑出 2~3 個多樣化候選。
# 相容性「不」交給 LLM 判斷,全部由下列規則與 specs 決定。

# 互動式選件支援的標準類別(canonical),以及常見別名 -> canonical 對照。
_COMPONENT_CATEGORIES = ("CPU", "GPU", "Motherboard", "RAM", "Storage", "PSU", "Case", "Cooler")
_CATEGORY_ALIASES = {
    "cpu": "CPU", "處理器": "CPU",
    "gpu": "GPU", "顯卡": "GPU", "顯示卡": "GPU",
    "motherboard": "Motherboard", "mb": "Motherboard", "主機板": "Motherboard", "mainboard": "Motherboard",
    "ram": "RAM", "記憶體": "RAM", "memory": "RAM",
    "storage": "Storage", "ssd": "Storage", "硬碟": "Storage", "儲存": "Storage", "nvme": "Storage",
    "psu": "PSU", "電源": "PSU", "電源供應器": "PSU", "power": "PSU",
    "case": "Case", "機殼": "Case", "chassis": "Case",
    "cooler": "Cooler", "散熱器": "Cooler", "散熱": "Cooler", "cpu cooler": "Cooler",
}
# 互動流程的『固定』選件順序(deterministic):
# CPU → 顯示卡 → 主機板 → 記憶體 → 硬碟 → 電源 → 散熱器 → 機殼。
COMPONENT_SELECTION_ORDER = ("CPU", "GPU", "Motherboard", "RAM", "Storage", "PSU", "Cooler", "Case")
# 向後相容別名(舊程式碼引用);內容已對齊新順序。
_SELECTION_ORDER = COMPONENT_SELECTION_ORDER
# 各類別中文標籤(給 next_step_suggestion 用)
_CATEGORY_LABEL_ZH = {
    "CPU": "CPU(處理器)", "Motherboard": "主機板", "RAM": "記憶體", "GPU": "顯示卡",
    "Storage": "儲存裝置", "PSU": "電源供應器", "Case": "機殼", "Cooler": "散熱器",
}

# ---- 虛擬「無」選項(GPU 用內顯 / Cooler 不額外購買)----
_VIRTUAL_NONE_NAME = {
    "GPU": "無獨立顯示卡（使用 CPU 內顯）",
    "Cooler": "無額外散熱器",
}
_VIRTUAL_SOURCE = "virtual_option"


def _is_none_selection(name: str | None, category: str | None) -> bool:
    """判斷 selected_* 是否為『無』虛擬選項(GPU 用內顯 / Cooler 不另購)。"""
    if not name:
        return False
    n = str(name).strip().lower()
    if category == "GPU":
        if n in ("無", "none", "no gpu", "內顯", "用內顯", "使用內顯"):
            return True
        return ("無" in name) and any(k in name for k in ("內顯", "獨立顯", "獨顯", "顯示卡"))
    if category == "Cooler":
        if n in ("無", "none", "no cooler"):
            return True
        return ("無" in name) and any(k in name for k in ("散熱", "cooler"))
    return False


def _virtual_none_spec(category: str) -> dict:
    """回傳『無』虛擬選項的標準化規格(price=0、is_virtual=True)。"""
    return {
        "found": True, "product_name": _VIRTUAL_NONE_NAME.get(category, "無"),
        "price": 0, "source": _VIRTUAL_SOURCE, "socket": None, "platform": None,
        "memory_generation": None, "has_igpu": None, "brand": None,
        "query_name": None, "match_level": "virtual", "ambiguous": False,
        "is_virtual": True,
    }


def _cpu_needs_cooler_attention(cpu_name: str | None) -> bool:
    """高功耗 / K / X3D / 高階 CPU,或無法確認盒裝散熱器時,選 Cooler=無 需提醒。

    保守:只要無法確認是低功耗附原廠散熱器,就回 True(寧可提醒)。
    明確低功耗線索(AMD 盒裝 G/GT、Intel 非 K 含內顯)較可能附原廠,回 False。
    """
    if not cpu_name:
        return True
    t = cpu_name.upper()
    if re.search(r"X3D|\bK\b|KF|KS|\bI[79]-|RYZEN\s*9|\bR9\b|CORE ULTRA\s*[79]|ULTRA\s*[79]", t):
        return True
    # AMD G/GT 盒裝、Intel 非 K 帶內顯通常附原廠散熱器
    if re.search(r"\d{3,4}\s?G[T]?\b", t) or ("盒" in (cpu_name or "")):
        return False
    return True


def get_next_component_category(selected_components: dict | None, use_case: str | None = None) -> str | None:
    """依固定順序回傳『下一個要選』的類別;全部選完回 None。

    selected_components:{canonical_category: name} 的 dict(name 非空即視為已選,
    含『無』虛擬選項)。順序固定為 COMPONENT_SELECTION_ORDER。
    """
    sel = selected_components or {}
    chosen = {k for k, v in sel.items() if v}
    for cat in COMPONENT_SELECTION_ORDER:
        if cat not in chosen:
            return cat
    return None


def _canonical_category(value: str | None) -> str | None:
    """把使用者/LLM 傳入的類別字串正規化成 canonical 類別名;無法對應回 None。"""
    if not value:
        return None
    v = value.strip()
    if v in _COMPONENT_CATEGORIES:
        return v
    return _CATEGORY_ALIASES.get(v.lower())


def _norm_full(s: str | None) -> str:
    """把商品名正規化成『可寬鬆比對』的字串。

    處理 LLM 常見的改寫差異:全形/半形、空白、標點、以及 ↑/最高(都代表最大時脈)等。
    規則:NFKC 正規化 -> 小寫 -> 去掉 ↑ 與『最高』-> 只保留英數與 CJK(其餘空白標點全移除)。
    例:'AMD R5 8500G盒…3.5G(↑5.0G)65W' 與 '…3.5G(最高5.0G) 65W' 會正規化成可互相包含的字串。
    """
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", str(s)).lower()
    t = t.replace("↑", "").replace("最高", "")
    return re.sub(r"[^0-9a-z一-鿿]+", "", t)


# CPU / RAM / 主機板的「識別 token」抽取規則(用於 brand+model 比對階段)
_CPU_MODEL_RES = (
    re.compile(r"\bR[3579]\s?\d{3,4}[A-Z0-9]*", re.IGNORECASE),       # R5 7500F / R7 9800X3D
    re.compile(r"\bRYZEN\s?\d\s?\d{3,4}[A-Z0-9]*", re.IGNORECASE),    # Ryzen 5 7500F
    re.compile(r"\bI[3579][-\s]?\d{4,5}[A-Z]*", re.IGNORECASE),       # i5-12400F
    re.compile(r"\bULTRA\s?\d\s?\d{3}[A-Z]*", re.IGNORECASE),         # Core Ultra 5 225F
)
_BRAND_ALIASES = {
    "華碩": "ASUS", "ASUS": "ASUS", "技嘉": "GIGABYTE", "GIGABYTE": "GIGABYTE",
    "微星": "MSI", "MSI": "MSI", "華擎": "ASROCK", "ASROCK": "ASROCK",
    "AMD": "AMD", "INTEL": "INTEL", "RYZEN": "AMD",
}


def _key_tokens(s: str | None, category: str | None) -> set[str]:
    """抽出商品的『識別 token』集合(大寫、去空白),用於 brand+model token 比對。

    - CPU:Ryzen/R# 型號、iX-NNNN、Core Ultra 型號。
    - Motherboard:晶片組(B650/H610/...)。
    - RAM:DDR4/DDR5、容量(16GB)、頻率(6000)。
    - 各類:可辨識的品牌(華碩/技嘉/微星/華擎/AMD/Intel)。
    """
    tokens: set[str] = set()
    if not s:
        return tokens
    up = unicodedata.normalize("NFKC", str(s)).upper()

    # 品牌
    for alias, canon in _BRAND_ALIASES.items():
        if alias in up:
            tokens.add("BRAND:" + canon)

    if category == "CPU" or category is None:
        for rx in _CPU_MODEL_RES:
            for m in rx.findall(up):
                tokens.add("MODEL:" + re.sub(r"[\s-]+", "", m))
    if category == "Motherboard" or category is None:
        for m in _pr._MB_CHIPSET_RE.findall(up):
            base = m.upper().rstrip("E")[:4]
            tokens.add("CHIP:" + base)
    # 記憶體世代:主機板與 RAM 都需要(主機板名常含 DDR4/DDR5 或縮寫 D4/D5)
    if category in ("Motherboard", "RAM") or category is None:
        for g in re.findall(r"DDR[345]", up):
            tokens.add("MEM:" + g)
        if re.search(r"\bD5\b", up):
            tokens.add("MEM:DDR5")
        if re.search(r"\bD4\b", up):
            tokens.add("MEM:DDR4")
    if category == "RAM" or category is None:
        for cap in re.findall(r"(\d{1,3})\s*GB", up):
            tokens.add("CAP:" + cap + "GB")
        for sp in re.findall(r"DDR[345][-\s]?(\d{4,5})", up):
            tokens.add("SPD:" + sp)
    return tokens


# 各比對階段的分數(越高越精確)
_MATCH_EXACT = 100
_MATCH_NORM_EQUAL = 90
_MATCH_NORM_SUBSTR = 70
_MATCH_MODEL_KEY = 60
_MATCH_BRAND_MODEL = 40
# 只有 exact / normalized-equal 視為「精確比對」,其餘為 fuzzy(會在工具層提示)
_FUZZY_LEVELS = {"normalized-substr", "model_key", "brand_model"}


def _score_candidate(qn: str, qfull: str, qkey: str, qtokens: set[str],
                     p: dict, category: str | None) -> tuple[int, str | None]:
    """對單一候選商品打分,回 (score, match_level);不相符回 (0, None)。"""
    pname = p.get("product_name") or ""
    if pname.strip() == qn.strip():
        return _MATCH_EXACT, "exact"
    pfull = _norm_full(pname)
    if qfull and pfull and qfull == pfull:
        return _MATCH_NORM_EQUAL, "normalized"
    if qfull and pfull and (qfull in pfull or pfull in qfull):
        # 包含關係:較長者需明顯包含較短者(避免極短字串亂中)
        if len(qfull) >= 4:
            return _MATCH_NORM_SUBSTR, "normalized-substr"
    pkey = _normalize_model_key(p.get("model") or "") or _normalize_model_key(pname)
    # 需共享至少 5 字元前綴,避免極短型號鍵(如 'h610')亂中,忽略 DDR4/DDR5 等差異
    if qkey and pkey and (pkey.startswith(qkey) or qkey.startswith(pkey)) and min(len(qkey), len(pkey)) >= 5:
        return _MATCH_MODEL_KEY, "model_key"
    # brand + model token:要求 query 的識別 token 全部出現在候選(避免 DDR4 配到 DDR5)
    if qtokens:
        ptokens = _key_tokens(pname, category)
        # 只比對「識別性」token(MODEL/CHIP/MEM/CAP),品牌作加分但非必要
        q_ident = {t for t in qtokens if not t.startswith("BRAND:")}
        if q_ident and q_ident.issubset(ptokens):
            bonus = 1 if (any(t.startswith("BRAND:") for t in qtokens)
                          and qtokens & ptokens) else 0
            return _MATCH_BRAND_MODEL + len(q_ident) + bonus, "brand_model"
    return 0, None


def _match_selected_product(name: str | None, category: str | None, db_path: str) -> dict:
    """多階段把『使用者已選商品名(可能被 LLM 改寫)』對回 DB 商品。

    階段(由精確到寬鬆):exact -> normalized-equal -> normalized-substr ->
    model_key 前綴 -> brand+model token。限定 category 以避免跨類別誤配。

    Returns dict:row(對到的商品或 None)/ match_level / ambiguous /
    candidate_count(同分候選數)。唯讀,不寫 DB。
    """
    out = {"row": None, "match_level": "none", "ambiguous": False, "candidate_count": 0}
    if not name or not str(name).strip():
        return out
    qn = str(name).strip()
    qfull = _norm_full(qn)
    qkey = _normalize_model_key(qn)
    qtokens = _key_tokens(qn, category)

    pool = query_products(category=category, limit=5000, db_path=db_path)
    if not pool:
        return out

    # 硬性約束:若 query 明確帶記憶體世代(DDR4/DDR5)或晶片組(B650/H610…),
    # 候選必須含相同 token,否則先剔除——確保『H610 DDR4』不會誤配到 DDR5 板。
    hard = {t for t in qtokens if t.startswith("MEM:") or t.startswith("CHIP:")}
    if hard:
        filtered = [p for p in pool if hard.issubset(_key_tokens(p.get("product_name"), category))]
        if filtered:
            pool = filtered

    best_score = 0
    best_level: str | None = None
    tied: list[dict] = []
    for p in pool:
        score, level = _score_candidate(qn, qfull, qkey, qtokens, p, category)
        if score <= 0:
            continue
        if score > best_score:
            best_score, best_level, tied = score, level, [p]
        elif score == best_score:
            tied.append(p)

    if best_score <= 0 or not tied:
        return out

    # 同分多筆:取最便宜者(price 為 None 排後),並標記 ambiguous(僅 fuzzy 階段才視為需提醒)
    distinct = {(p.get("product_name"), p.get("price")) for p in tied}
    tied_sorted = sorted(tied, key=lambda r: (r.get("price") is None, r.get("price") or 0))
    chosen = tied_sorted[0]
    ambiguous = (len(distinct) > 1) and (best_level in _FUZZY_LEVELS)
    return {
        "row": chosen,
        "match_level": best_level or "none",
        "ambiguous": ambiguous,
        "candidate_count": len(distinct),
    }


def _find_product_by_name(name: str | None, category: str | None, db_path: str) -> dict | None:
    """以名稱/型號把使用者已選商品對回 DB 的一筆商品;找不到回 None。

    內部走多階段比對(_match_selected_product),容忍 LLM 對商品名的常見改寫
    (↑/最高、空白、標點、全半形、只給品牌+型號或部分型號)。限定 category 不跨類別誤配。
    唯讀,不寫 DB。
    """
    return _match_selected_product(name, category, db_path)["row"]


def _get_selected_product_specs(name: str | None, category: str, db_path: str) -> dict:
    """解析「已選商品」的平台規格。

    優先用 DB 內該商品的 specs;DB 找不到時退而用 platform_rules 由名稱字串推斷
    (這樣即使使用者打的型號 DB 沒有,仍能套用相容性規則,而非完全失效)。

    Returns dict:found / product_name / price / socket / platform /
    memory_generation / has_igpu(僅 CPU) / brand。
    """
    # 『無』虛擬選項(GPU 用內顯 / Cooler 不另購):不查 DB,直接回 price=0 的虛擬規格。
    if _is_none_selection(name, category):
        return _virtual_none_spec(category)

    out: dict[str, Any] = {
        "found": False, "product_name": name, "price": None,
        "source": None,
        "socket": None, "platform": None, "memory_generation": None,
        "has_igpu": None, "brand": None,
        "query_name": name, "match_level": "none", "ambiguous": False,
        "is_virtual": False,
    }
    match = _match_selected_product(name, category, db_path)
    row = match["row"]
    out["match_level"] = match["match_level"]
    out["ambiguous"] = match["ambiguous"]
    if row:
        sp = _specs_of(row)
        out["found"] = True
        out["product_name"] = row.get("product_name")
        out["price"] = row.get("price")
        out["source"] = row.get("source")
        out["socket"] = sp.get("socket")
        out["platform"] = sp.get("platform")
        out["memory_generation"] = (
            _effective_mb_mem(row) if category == "Motherboard" else sp.get("memory_generation")
        )
        out["brand"] = row.get("brand") or _pr.cpu_brand_from_text(row.get("product_name"))
        if category == "CPU":
            out["has_igpu"] = _cpu_has_igpu(row)
        # specs 缺 socket 時,用名稱推斷補上(不覆蓋既有值)
        if not out["socket"]:
            nm = row.get("product_name")
            if category == "CPU":
                s, p, m = _pr.cpu_platform_from_text(nm)
            elif category == "Motherboard":
                s, p, m = _pr.mb_platform_from_text(nm)
            else:
                s = p = m = None
            out["socket"] = out["socket"] or s
            out["platform"] = out["platform"] or p
            out["memory_generation"] = out["memory_generation"] or m
        return out

    # DB 找不到:純由名稱字串推斷
    if category == "CPU":
        s, p, m = _pr.cpu_platform_from_text(name)
        out["has_igpu"] = _cpu_has_igpu({"product_name": name or ""})
        out["brand"] = _pr.cpu_brand_from_text(name)
    elif category == "Motherboard":
        s, p, m = _pr.mb_platform_from_text(name)
    else:
        s = p = m = None
        if category == "RAM":
            m = _pr.mem_from_text(name)
    out["socket"], out["platform"], out["memory_generation"] = s, p, m
    return out


def _collect_selected(selected_kwargs: dict[str, str | None]) -> dict[str, str]:
    """把 selected_cpu / selected_motherboard ... 收斂成 {canonical_category: name}。"""
    mapping = {
        "selected_cpu": "CPU", "selected_motherboard": "Motherboard", "selected_ram": "RAM",
        "selected_gpu": "GPU", "selected_storage": "Storage", "selected_psu": "PSU",
        "selected_case": "Case", "selected_cooler": "Cooler",
    }
    out: dict[str, str] = {}
    for key, cat in mapping.items():
        val = selected_kwargs.get(key)
        if val and str(val).strip():
            out[cat] = str(val).strip()
    return out


def _resolve_platform_constraints(
    selected_map: dict[str, str],
    prefer_platform: str | None,
    selected_socket: str | None,
    selected_memory_generation: str | None,
    db_path: str,
) -> dict[str, Any]:
    """由已選零件 + 指定平台推導 deterministic 約束。

    優先序:已選主機板(socket+mem 最權威)> 已選 CPU(socket/品牌)> 已選 RAM(mem)
    > prefer_platform > selected_socket / selected_memory_generation。
    最後由 socket 補出 brand 與預設 mem(LGA1700 的 mem 留待主機板版本決定)。

    Returns dict:socket / memory_generation / brand / notes(list) /
    cpu_specs(已選 CPU 的規格,供內顯判斷) / mem_ambiguous(bool)。
    """
    socket: str | None = None
    mem: str | None = None
    brand: str | None = None
    notes: list[str] = []
    cpu_specs: dict | None = None

    # 1) 主機板:socket 與記憶體世代最權威
    if "Motherboard" in selected_map:
        sp = _get_selected_product_specs(selected_map["Motherboard"], "Motherboard", db_path)
        if sp["socket"]:
            socket = sp["socket"]
            notes.append(f"已選主機板 → socket={socket}")
        if sp["memory_generation"] in ("DDR4", "DDR5"):
            mem = sp["memory_generation"]
            notes.append(f"已選主機板 → memory_generation={mem}")
        elif sp["memory_generation"] == "DDR4_or_DDR5":
            notes.append("已選主機板同時支援 DDR4/DDR5,記憶體世代待確認")

    # 2) CPU:socket(若主機板未給)、品牌
    if "CPU" in selected_map:
        sp = _get_selected_product_specs(selected_map["CPU"], "CPU", db_path)
        cpu_specs = sp
        if not socket and sp["socket"]:
            socket = sp["socket"]
            notes.append(f"已選 CPU → socket={socket}")
        if not mem and sp["memory_generation"] in ("DDR4", "DDR5"):
            mem = sp["memory_generation"]
            notes.append(f"已選 CPU → memory_generation={mem}")
        if sp["brand"]:
            brand = brand or sp["brand"]

    # 3) RAM:補記憶體世代
    if "RAM" in selected_map and not mem:
        sp = _get_selected_product_specs(selected_map["RAM"], "RAM", db_path)
        if sp["memory_generation"] in ("DDR4", "DDR5"):
            mem = sp["memory_generation"]
            notes.append(f"已選記憶體 → memory_generation={mem}")

    # 4) prefer_platform(AM5/AM4/LGA1700/LGA1851 或 AMD/Intel)
    norm = _pr.normalize_platform(prefer_platform)
    if norm in ("AM4", "AM5", "LGA1700", "LGA1851"):
        if not socket:
            socket = norm
            notes.append(f"指定平台 → socket={norm}")
    elif norm in ("AMD", "Intel"):
        if not brand:
            brand = norm
            notes.append(f"指定平台 → 品牌={norm}")

    # 5) 顯式 selected_socket / selected_memory_generation(僅在尚未決定時採用)
    if not socket and selected_socket:
        s = _pr.normalize_platform(selected_socket)
        if s in ("AM4", "AM5", "LGA1700", "LGA1851"):
            socket = s
            notes.append(f"指定 socket={s}")
    if not mem and selected_memory_generation:
        m = str(selected_memory_generation).strip().upper()
        if m in ("DDR4", "DDR5"):
            mem = m
            notes.append(f"指定 memory_generation={m}")

    # 6) 由 socket 補出 brand 與預設 mem(LGA1700 的 mem 不臆測)
    if socket and not brand:
        brand = _pr.SOCKET_BRAND.get(socket)
    mem_ambiguous = False
    if socket and not mem:
        default_mem = _pr.SOCKET_DEFAULT_MEM.get(socket)
        if default_mem:
            mem = default_mem
        elif socket == "LGA1700":
            mem_ambiguous = True  # DDR4/DDR5 取決於主機板版本

    return {
        "socket": socket,
        "memory_generation": mem,
        "brand": brand,
        "notes": notes,
        "cpu_specs": cpu_specs,
        "mem_ambiguous": mem_ambiguous,
    }


def _candidate_platform_fields(row: dict, category: str) -> dict[str, Any]:
    """取出某候選商品的平台欄位(socket / platform / memory_generation / brand)。"""
    sp = _specs_of(row)
    socket = sp.get("socket")
    platform = sp.get("platform")
    if category == "Motherboard":
        mem = _effective_mb_mem(row)
    else:
        mem = sp.get("memory_generation")
    brand = row.get("brand") or _pr.cpu_brand_from_text(row.get("product_name"))
    # specs 缺 socket 時用名稱推斷補上(僅 CPU / Motherboard)
    if not socket:
        if category == "CPU":
            s, p, m = _pr.cpu_platform_from_text(row.get("product_name"))
        elif category == "Motherboard":
            s, p, m = _pr.mb_platform_from_text(row.get("product_name"))
        else:
            s = p = m = None
        socket = socket or s
        platform = platform or p
        mem = mem or m
    return {"socket": socket, "platform": platform, "memory_generation": mem, "brand": brand}


def _filter_candidates(
    pool: list[dict],
    target_category: str,
    constraints: dict[str, Any],
    gaming: bool,
    has_dgpu_expected: bool,
) -> tuple[list[dict], list[str], list[str]]:
    """依 deterministic 規則過濾候選池。

    Returns (kept_rows, constraints_applied, warnings)。kept_rows 內每筆會附 _pf 平台欄位。
    平台關鍵類別(CPU/Motherboard/RAM)若過濾後為空,**不**回退(正確性優先);
    PSU/Storage 等若過濾後為空則回退原池並加註說明。
    """
    socket = constraints.get("socket")
    mem = constraints.get("memory_generation")
    brand = constraints.get("brand")
    applied: list[str] = []
    warnings: list[str] = []

    kept: list[dict] = []
    for row in pool:
        pf = _candidate_platform_fields(row, target_category)
        row = {**row, "_pf": pf}

        if target_category == "CPU":
            if not pf["socket"]:
                continue  # 無法判定平台的 CPU 不列(避免誤導)
            if socket and pf["socket"] != socket:
                continue
            if brand and pf["brand"] and pf["brand"] != brand:
                continue
            kept.append(row)

        elif target_category == "Motherboard":
            if not pf["socket"]:
                continue
            if socket and pf["socket"] != socket:
                continue
            if mem in ("DDR4", "DDR5"):
                # 主機板需能支援該世代(DDR4_or_DDR5 視為可相容)
                if not _mem_compatible(mem, pf["memory_generation"]):
                    continue
            kept.append(row)

        elif target_category == "RAM":
            rmem = pf["memory_generation"]
            if rmem == "DDR3":
                continue  # 現代菜單不推 DDR3
            if mem in ("DDR4", "DDR5"):
                if rmem != mem:
                    continue
            else:
                # 無明確世代約束:只保留 DDR4/DDR5
                if rmem not in ("DDR4", "DDR5"):
                    continue
            kept.append(row)

        elif target_category == "Storage":
            if gaming and not _is_ssd_storage(row):
                continue  # 遊戲/4K 主要儲存只接受 SSD 類
            kept.append(row)

        elif target_category == "PSU":
            if has_dgpu_expected:
                w = _specs_of(row).get("wattage")
                if w is None or w < 550:
                    continue
            kept.append(row)

        else:  # GPU / Case / Cooler:無硬性平台過濾
            kept.append(row)

    # RAM(gaming/4k):優先 >=16GB(沿用完整菜單引擎的選品門檻);足夠時才收斂
    if target_category == "RAM" and gaming and kept:
        big = [r for r in kept if (_ram_gb(_specs_of(r).get("capacity")) or 0) >= 16]
        if len(big) >= 2:
            kept = big
            applied.append("capacity>=16GB")

    # CPU(office / 文書機):優先『有內顯』的 CPU(deterministic 用 _cpu_has_igpu 判斷),
    # 讓下一輪 GPU 能合理提供『無獨立顯示卡(使用 CPU 內顯)』。gaming/4k 不套用此偏好。
    if target_category == "CPU" and (not gaming) and kept:
        igpu = [r for r in kept if _cpu_has_igpu(r)]
        if len(igpu) >= 2:
            kept = igpu  # DB 有足夠內顯 CPU → 候選全部有內顯
            applied.append("office=內顯優先")
        elif igpu:
            # 內顯 CPU 不足 2 個:把有內顯的排前面,仍補無內顯款,但提醒
            kept = igpu + [r for r in kept if r not in igpu]
            warnings.append(
                "資料庫中內顯 CPU 數量有限;部分候選可能無內顯,文書機若選無內顯款仍需搭配獨立顯卡。")
        else:
            warnings.append(
                "資料庫中目前找不到內顯 CPU;以下候選可能無內顯,文書機若選無內顯款仍需搭配獨立顯卡。")

    # constraints_applied 記錄
    if target_category in ("CPU", "Motherboard") and socket:
        applied.append(f"socket={socket}")
    if target_category in ("Motherboard", "RAM") and mem in ("DDR4", "DDR5"):
        applied.append(f"memory_generation={mem}")
    if target_category == "CPU" and brand:
        applied.append(f"brand={brand}")
    if target_category == "RAM" and constraints.get("mem_ambiguous"):
        applied.append("memory_generation=DDR4/DDR5(待主機板版本確認)")
        warnings.append(
            "已選主機板為 Intel LGA1700,記憶體世代取決於主機板 DDR4/DDR5 版本;"
            "已同時列出可能候選,請先確認主機板支援的世代再下單。")
    if target_category == "Storage" and gaming:
        applied.append("storage=SSD/NVMe/M.2(排除純 HDD 作主碟)")
    if target_category == "PSU" and has_dgpu_expected:
        applied.append("psu>=550W(含獨立顯卡)")

    # 非平台關鍵類別:過濾後為空則回退,避免完全無候選
    if not kept and target_category in ("Storage", "PSU"):
        kept = [{**r, "_pf": _candidate_platform_fields(r, target_category)} for r in pool]
        warnings.append(
            f"此條件下找不到完全符合 {target_category} 規格門檻的商品,已放寬列出候選,請人工確認規格。")

    return kept, applied, warnings


def _pick_component_options(kept: list[dict], target_price: float | None, limit: int) -> list[dict]:
    """從相容候選中挑出多樣化的 2~3(最多 limit)個:性價比 / 平衡 / 高階。

    不是只回最便宜的;以價格分佈取低 / 中(或最接近 target)/ 高三個級距,去重後回傳,
    並在每筆附 _tier 標籤。候選不足時回較少筆。
    """
    priced = [r for r in kept if r.get("price") is not None]
    if not priced:
        return []
    priced.sort(key=lambda r: r["price"])

    # 去除同型號重複(例:同一顆 i5-12400F 不同店家/價格),保留最便宜那筆,提高候選多樣性。
    # 若去重後不足 limit,再把先前略過的補回來,確保仍能湊出足夠候選。
    deduped: list[dict] = []
    seen_models: set[str] = set()
    leftovers: list[dict] = []
    for r in priced:
        mk = _normalize_model_key(r.get("model") or "") or _normalize_model_key(r.get("product_name") or "")
        if mk and mk in seen_models:
            leftovers.append(r)
            continue
        if mk:
            seen_models.add(mk)
        deduped.append(r)
    priced = deduped if len(deduped) >= min(limit, 3) else (deduped + leftovers)
    n = len(priced)
    if n <= limit:
        for i, r in enumerate(priced):
            r["_tier"] = ("性價比", "平衡", "高階")[min(i, 2)] if n <= 3 else "候選"
        return priced

    # 平衡:最接近 target_price(沒有 target 就取中位數)
    if target_price is not None:
        bal_idx = min(range(n), key=lambda i: (abs(priced[i]["price"] - target_price), priced[i]["price"]))
    else:
        bal_idx = n // 2
    value_idx = max(0, int(n * 0.15))
    high_idx = min(n - 1, int(n * 0.85))

    tiers: list[tuple[int, str]] = [(value_idx, "性價比"), (bal_idx, "平衡"), (high_idx, "高階")]
    selected: list[dict] = []
    used_idx: set[int] = set()
    used_names: set[str] = set()
    for idx, tier in tiers:
        if len(selected) >= limit:
            break
        # 若該 idx 已被用,往後找一個未用的
        j = idx
        while j < n and (j in used_idx or priced[j].get("product_name") in used_names):
            j += 1
        if j >= n:
            j = idx
            while j >= 0 and (j in used_idx or priced[j].get("product_name") in used_names):
                j -= 1
        if 0 <= j < n and j not in used_idx and priced[j].get("product_name") not in used_names:
            r = priced[j]
            r["_tier"] = tier
            selected.append(r)
            used_idx.add(j)
            used_names.add(r.get("product_name"))

    # 若 limit > 3,補入其餘等距候選
    if limit > len(selected):
        for j in range(n):
            if len(selected) >= limit:
                break
            if j in used_idx or priced[j].get("product_name") in used_names:
                continue
            r = priced[j]
            r["_tier"] = "候選"
            selected.append(r)
            used_idx.add(j)
            used_names.add(r.get("product_name"))

    selected.sort(key=lambda r: r["price"])
    return selected


# 各用途下,某類別「目標單價」估算用的權重(沿用完整菜單引擎的權重觀念)
def _is_office_inappropriate_cpu(row: dict) -> bool:
    """判斷此 CPU 是否『不適合文書機作主推』(高階遊戲 / 高功耗 CPU)。

    deterministic 依型號:X3D、Ryzen 9/R9、Intel i9 / Core Ultra 9、Intel K/KF、Core Ultra K。
    """
    name = (row.get("product_name") or "").upper()
    if "X3D" in name:
        return True
    if re.search(r"RYZEN\s*9|\bR9\b", name):
        return True
    if re.search(r"\bI9\b|I9[-\s]?\d|CORE ULTRA\s*9|\bULTRA\s*9\b", name):
        return True
    if re.search(r"I[3579][-\s]?\d{4,5}[A-Z]*K", name):  # Intel K / KF (i5-14600K, i7-14700KF)
        return True
    if re.search(r"ULTRA\s*\d\s*\d{3}[A-Z]*K", name):    # Core Ultra K (Ultra 5 245K)
        return True
    return False


def _gaming_cpu_min_price(budget: int | None) -> int | None:
    """gaming 依整機預算給 CPU『最低價』門檻(高預算不主推中低階 CPU);資訊不足回 None。

    - budget > 50000(高預算):CPU 至少約 budget×10%(下限 8000)→ 排除 i5-12400F / R5 5500 等。
    - 25000 < budget <= 50000(中高):至少約 budget×6%(下限 3500)→ 排除極低階,但不過度拉高。
    - budget <= 25000:不設門檻(入門/中階皆可)。
    """
    if not budget:
        return None
    b = int(budget)
    if b > 50000:
        return max(int(b * 0.10), 8000)
    if b > 25000:
        return max(int(b * 0.06), 3500)
    return None


def _gaming_cpu_tier_filter(kept: list[dict], budget: int | None) -> tuple[list[dict], list[str], list[str]]:
    """gaming CPU 預算級距過濾:高預算時只留 >= 門檻的中高階 / 高階 CPU 作主推。

    若門檻內候選 >= 2 個才收斂;較入門的 CPU 以『省預算 alternative』列入 warnings(不放主推)。
    DB 高階候選不足時退回原候選,不硬擋。
    """
    applied: list[str] = []
    warns: list[str] = []
    floor = _gaming_cpu_min_price(budget)
    if not floor or not kept:
        return kept, applied, warns
    high = [r for r in kept if (r.get("price") or 0) >= floor]
    if len(high) >= 2:
        applied.append(f"gaming高預算級距:CPU>=~{floor:,}元")
        cheaper = [r for r in kept if (r.get("price") or 0) < floor]
        if cheaper:
            c = min(cheaper, key=lambda r: r.get("price") or 0)
            warns.append(
                f"若想省 CPU 預算,亦可考慮較入門的「{c.get('product_name')}」"
                f"({int(c.get('price') or 0):,} 元);但此預算級距建議搭配較高階 CPU,"
                f"以發揮高階顯示卡效能。")
        return high, applied, warns
    return kept, applied, warns


# ---- GPU / 其他類別的 use_case + budget tier 過濾(deterministic) ----
_GPU_PRO_KW = ("QUADRO", "TESLA", "FIREPRO", "RADEON PRO", "ARC PRO", "PROART",
               "CREATOR", "WORKSTATION", "繪圖", "工作站", "專業卡", "CMP")


def _is_workstation_gpu(row: dict) -> bool:
    """是否為工作站 / 專業 / 非遊戲顯卡(Ada workstation / Quadro / ARC PRO / ProArt / Creator / ECC…)。"""
    n = (row.get("product_name") or "").upper()
    if any(k in n for k in _GPU_PRO_KW):
        return True
    if re.search(r"\bADA\b", n):       # RTX 2000/4000/6000 Ada 工作站卡
        return True
    if re.search(r"RTX\s?A\d", n):     # RTX A 系列工作站
        return True
    if "ECC" in n:                     # 專業卡常標 GDDR6 ECC
        return True
    return False


def _is_gaming_gpu(row: dict) -> bool:
    """是否為遊戲顯卡(GeForce RTX/GTX、Radeon RX、Intel Arc A/B gaming);排除工作站卡。"""
    if _is_workstation_gpu(row):
        return False
    n = (row.get("product_name") or "").upper()
    return bool(re.search(r"RTX\s?\d|GTX\s?\d|\bRX\s?\d|ARC\s?[AB]\d|RADEON\s?RX", n))


def _gpu_min_price(budget: int | None) -> int | None:
    """gaming GPU 依預算的最低價門檻(高預算不主推低階卡);資訊不足回 None。"""
    if not budget:
        return None
    b = int(budget)
    if b > 60000:
        return max(int(b * 0.20), 16000)
    if b > 40000:
        return max(int(b * 0.15), 9000)
    if b > 25000:
        return max(int(b * 0.10), 6000)
    return None


def _apply_price_floor(kept: list[dict], floor: int | None, tag: str,
                       alt_prefix: str | None = None) -> tuple[list[dict], list[str], list[str]]:
    """保留 price >= floor 的候選(>=2 才收斂);較便宜者以 alt 提示放 warnings。"""
    if not floor or not kept:
        return kept, [], []
    high = [r for r in kept if (r.get("price") or 0) >= floor]
    if len(high) < 2:
        return kept, [], []
    applied = [tag]
    warns: list[str] = []
    cheaper = [r for r in kept if (r.get("price") or 0) < floor]
    if cheaper and alt_prefix:
        c = min(cheaper, key=lambda r: r.get("price") or 0)
        warns.append(f"{alt_prefix}「{c.get('product_name')}」({int(c.get('price') or 0):,} 元)")
    return high, applied, warns


def _gpu_tier_filter(kept: list[dict], budget: int | None, uc: str) -> tuple[list[dict], list[str], list[str]]:
    """gaming GPU:排除工作站/專業卡 + 依預算級距設最低價(高預算不主推低階卡)。"""
    applied: list[str] = []
    warns: list[str] = []
    if uc not in ("gaming", "4k_gaming"):
        return kept, applied, warns
    gaming = [r for r in kept if not _is_workstation_gpu(r)]
    if len(gaming) >= 2:
        kept = gaming
        applied.append("gaming GPU:排除工作站/專業卡(Ada/Quadro/ARC PRO/ProArt/Creator)")
    floor = _gpu_min_price(budget)
    if floor:
        kept, ap, w = _apply_price_floor(
            kept, floor, f"gaming GPU 預算級距:>=~{floor:,}元",
            "若想省 GPU 預算,亦可考慮較入門的")
        applied += ap
        warns += w
    return kept, applied, warns


def _ram_tier_filter(kept: list[dict], budget: int | None, uc: str) -> tuple[list[dict], list[str], list[str]]:
    """RAM:排除 ECC/伺服器記憶體;高預算 gaming 優先 32GB+。"""
    applied: list[str] = []
    warns: list[str] = []
    consumer = [r for r in kept if "ECC" not in (r.get("product_name") or "").upper()]
    if len(consumer) >= 2:
        kept = consumer
        applied.append("排除 ECC / 伺服器記憶體")
    if uc in ("gaming", "4k_gaming") and budget and int(budget) > 50000:
        big = [r for r in kept if (_ram_gb(_specs_of(r).get("capacity")) or 0) >= 32]
        if len(big) >= 2:
            kept = big
            applied.append("高預算 gaming:RAM>=32GB")
    return kept, applied, warns


def _storage_tier_filter(kept: list[dict], budget: int | None, uc: str) -> tuple[list[dict], list[str], list[str]]:
    """Storage:高預算 gaming 優先 1TB+ SSD(主系統碟 SSD 已在 _filter_candidates 保證)。"""
    applied: list[str] = []
    if uc in ("gaming", "4k_gaming") and budget and int(budget) > 50000:
        big = [r for r in kept if (_cap_to_gb(_specs_of(r).get("capacity")) or 0) >= 1000]
        if len(big) >= 2:
            kept = big
            applied.append("高預算 gaming:Storage>=1TB")
    return kept, applied, []


def _psu_tier_filter(kept: list[dict], budget: int | None, uc: str,
                     gpu_price: int | None) -> tuple[list[dict], list[str], list[str]]:
    """PSU:依預算 / 已選 GPU 等級設瓦數下限;低預算不硬推超高瓦數。"""
    applied: list[str] = []

    def watt(r):
        return _specs_of(r).get("wattage") or 0

    floor = 550 if uc in ("gaming", "4k_gaming") else 0
    if uc in ("gaming", "4k_gaming") and budget:
        b = int(budget)
        if b > 60000:
            floor = max(floor, 750)
        elif b > 40000:
            floor = max(floor, 650)
    if gpu_price and gpu_price >= 20000:
        floor = max(floor, 750)
    if gpu_price and gpu_price >= 30000:
        floor = max(floor, 850)
    if floor:
        hi = [r for r in kept if watt(r) >= floor]
        if len(hi) >= 2:
            kept = hi
            applied.append(f"PSU>=~{floor}W")
    # 低預算不要硬推超高瓦數(>850W)
    if budget and int(budget) <= 35000:
        cap = [r for r in kept if watt(r) <= 850]
        if len(cap) >= 2:
            kept = cap
            applied.append("低預算:PSU<=850W")
    return kept, applied, []


def _mb_tier_filter(kept: list[dict], budget: int | None, constraints: dict) -> tuple[list[dict], list[str], list[str]]:
    """Motherboard:高預算 / 高階 CPU 避免最低階板作主推(socket/世代仍由 _filter_candidates 守門)。"""
    applied: list[str] = []
    warns: list[str] = []
    cpu_name = ((constraints.get("cpu_specs") or {}).get("product_name") or "").upper()
    high_cpu = bool(re.search(r"X3D|RYZEN\s*9|\bR9\b|\bI9\b|ULTRA\s*[79]|\d{4,5}K", cpu_name))
    floor = None
    if budget and int(budget) > 50000:
        floor = max(int(int(budget) * 0.05), 3000)
    if high_cpu:
        floor = max(floor or 0, 3000)
    if floor:
        kept, ap, w = _apply_price_floor(
            kept, floor, f"主機板級距:>=~{floor:,}元",
            "省預算可考慮較入門主機板")
        applied += ap
        warns += w
    return kept, applied, warns


def _case_tier_filter(kept: list[dict], budget: int | None) -> tuple[list[dict], list[str], list[str]]:
    """Case:高預算避免只推超便宜小機殼,並提醒顯卡長度 / 散熱器高度 / airflow 需確認。"""
    applied: list[str] = []
    warns: list[str] = []
    if budget and int(budget) > 50000:
        floor = max(int(int(budget) * 0.02), 1500)
        hi = [r for r in kept if (r.get("price") or 0) >= floor]
        if len(hi) >= 2:
            kept = hi
            applied.append(f"機殼級距:>=~{floor:,}元")
        warns.append("高預算 / 高階顯卡:請確認機殼可容納顯卡長度、散熱器高度與良好散熱(airflow);"
                     "規格不足時需人工確認。")
    return kept, applied, warns


def _office_cpu_value_filter(kept: list[dict], budget: int | None) -> tuple[list[dict], list[str], list[str]]:
    """office CPU 價值過濾:排除高階遊戲 CPU(X3D/R9/i9/Ultra9/K)與明顯超出文書需求的高價 CPU。

    有足夠(>=2)文書合理候選時才收斂;否則保留原候選但加 warning。
    """
    applied: list[str] = []
    warnings: list[str] = []
    if not kept:
        return kept, applied, warnings
    reasonable = [r for r in kept if not _is_office_inappropriate_cpu(r)]
    # 價格上限:文書 CPU 不應佔太高預算(約 45%,floor 7000);另設『文書用途絕對上限』~10000,
    # 避免高預算把 i7/R7 這類過剩 CPU 拉進文書主推。足夠候選時才以此收斂。
    if budget:
        cap = min(max(int(int(budget) * 0.45), 7000), 10000)
        priced_ok = [r for r in reasonable if (r.get("price") or 0) <= cap]
        if len(priced_ok) >= 2:
            reasonable = priced_ok
    else:
        priced_ok = [r for r in reasonable if (r.get("price") or 0) <= 10000]
        if len(priced_ok) >= 2:
            reasonable = priced_ok
    if len(reasonable) >= 2:
        applied.append("office=文書用途優先(排除高階遊戲/高功耗 CPU)")
        if budget and int(budget) > int(_OFFICE_REASONABLE_TOTAL * 1.3):
            warnings.append(
                f"文書機通常不需花到 {int(budget):,} 元;以下為文書用途合理的內顯 CPU,"
                f"不硬推高階遊戲 CPU。")
        return reasonable, applied, warnings
    # fallback:文書合理候選不足,保留原候選但提醒偏高階
    warnings.append("資料庫中文書用途合理的內顯 CPU 不足;以下候選可能偏高階,文書用途通常不需要。")
    return kept, applied, warnings


def _target_price_for(category: str, budget: int | None, remaining_budget: int | None, uc: str) -> float | None:
    """估一個該類別的目標單價,用於挑「平衡」候選;資訊不足回 None。"""
    base = remaining_budget if remaining_budget else budget
    if not base:
        return None
    weights = _OFFICE_WEIGHTS if uc == "office" else _GAMING_WEIGHTS
    w = weights.get(category)
    if w is None:
        return None
    # 用整體預算 * 類別權重作為目標單價估計(remaining_budget 已是剩餘,故直接用其相對比例)
    return float(budget * w) if budget else float(base * w)


def _build_reason(tier: str, category: str, pf: dict, gaming: bool) -> str:
    """組出該候選的推薦原因(deterministic 文字)。"""
    tier_txt = {
        "性價比": "性價比/入門選擇,此相容範圍內價位較低",
        "平衡": "平衡選擇,價位與規格折衷,適合多數使用情境",
        "高階": "較高階選擇,效能/用料較佳,預算充足可考慮",
        "候選": "相容候選之一",
    }.get(tier, "相容候選")
    extra = []
    plat = pf.get("platform") or pf.get("socket")
    if category in ("CPU", "Motherboard") and plat:
        extra.append(f"平台 {plat}")
    if category in ("Motherboard", "RAM") and pf.get("memory_generation"):
        extra.append(pf["memory_generation"])
    return tier_txt + ("(" + " / ".join(extra) + ")" if extra else "")


def _build_compat_notes(category: str, pf: dict, constraints: dict[str, Any]) -> str:
    """組出該候選的相容性說明(deterministic 文字)。"""
    socket = pf.get("socket")
    mem = pf.get("memory_generation")
    csocket = constraints.get("socket")
    cmem = constraints.get("memory_generation")
    notes: list[str] = []

    if category == "CPU":
        if socket:
            notes.append(f"{socket} / {mem or '記憶體世代依主機板'}")
            if csocket:
                notes.append("與已選平台一致" if socket == csocket else "與已選平台不一致")
        else:
            notes.append("平台無法由規格確認,需人工確認")
    elif category == "Motherboard":
        if socket:
            notes.append(f"{socket} / {mem or 'DDR 世代依版本'}")
            if csocket:
                notes.append("socket 與已選 CPU 一致" if socket == csocket else "socket 與已選 CPU 不一致")
        else:
            notes.append("平台無法由規格確認,需人工確認")
    elif category == "RAM":
        if mem:
            notes.append(mem)
            if cmem in ("DDR4", "DDR5"):
                notes.append("與已選主機板世代相容" if mem == cmem else "與已選主機板世代不相容")
        else:
            notes.append("記憶體世代無法確認,需人工確認")
    elif category == "Storage":
        notes.append("SSD/NVMe 類" if _is_ssd_pf(pf) else "請確認是否為 SSD 主碟")
        notes.append("與平台無關,容量/介面需符合主機板 M.2/SATA 支援")
    elif category == "PSU":
        w = pf.get("wattage")
        notes.append(f"{w}W" if w else "瓦數需確認")
        notes.append("瓦數需 ≥ 顯卡建議值,接頭需符合顯卡供電")
    elif category == "GPU":
        notes.append("與 CPU/主機板平台無關;長度需符合機殼,供電需符合 PSU")
    elif category == "Case":
        notes.append("需確認可容納主機板尺寸 / 顯卡長度 / 散熱器高度 / 水冷排")
    elif category == "Cooler":
        notes.append("散熱器扣具(socket)/ 空冷高度 / AIO 水冷排尺寸需人工確認")
    return ";".join(notes)


def _is_ssd_pf(pf: dict) -> bool:
    # pf 沒有完整 row,這裡僅用於文字提示的保守判斷;真正過濾在 _filter_candidates
    return True


def _recommend_component_options_legacy(
    target_category: str,
    *,
    budget: int | None = None,
    use_case: str = "gaming",
    remaining_budget: int | None = None,
    prefer_platform: str | None = None,
    selected_cpu: str | None = None,
    selected_motherboard: str | None = None,
    selected_ram: str | None = None,
    selected_gpu: str | None = None,
    selected_storage: str | None = None,
    selected_psu: str | None = None,
    selected_case: str | None = None,
    selected_cooler: str | None = None,
    selected_socket: str | None = None,
    selected_memory_generation: str | None = None,
    limit: int = 3,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """**Legacy 內建推薦**:讀 DB + 我們自己的 filter / tier / ranking 決定 2~3 個候選。

    這是 `USE_EXTERNAL_COMPONENT_RECOMMENDER=False`(或外部 recommender 未接 / 失敗)時的 fallback。
    Returns dict:category / options / constraints_applied / warnings / next_step_suggestion。
    每個 option 含 product_name / price / source / category / brand / model / socket /
    platform / memory_generation / reason / compatibility_notes(無 DB 內部欄位)。
    """
    cat = _canonical_category(target_category)
    if cat is None:
        return {
            "category": target_category,
            "options": [],
            "constraints_applied": [],
            "warnings": [f"無法辨識的 target_category:{target_category}。"
                         f"請用 {' / '.join(_COMPONENT_CATEGORIES)} 其中之一。"],
            "next_step_suggestion": "",
        }

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 3
    limit = max(1, min(limit, 5))

    uc = _classify_use_case(use_case)
    gaming = uc != "office"

    selected_map = _collect_selected({
        "selected_cpu": selected_cpu, "selected_motherboard": selected_motherboard,
        "selected_ram": selected_ram, "selected_gpu": selected_gpu,
        "selected_storage": selected_storage, "selected_psu": selected_psu,
        "selected_case": selected_case, "selected_cooler": selected_cooler,
    })

    constraints = _resolve_platform_constraints(
        selected_map, prefer_platform, selected_socket, selected_memory_generation, db_path)

    # 候選池(以 remaining_budget 或 budget 當價格上限,避免明顯超預算)
    price_cap = remaining_budget if remaining_budget else budget
    pool = query_products(category=cat, max_price=price_cap, limit=2000, db_path=db_path)

    has_dgpu_expected = bool(selected_map.get("GPU")) or gaming
    kept, applied, filter_warnings = _filter_candidates(
        pool, cat, constraints, gaming, has_dgpu_expected)

    # office CPU 價值過濾:在 iGPU 偏好之上,再排除高階遊戲/高功耗/高價 CPU(需 budget)
    if cat == "CPU" and uc == "office":
        kept, _ap, _w = _office_cpu_value_filter(kept, budget)
        applied += _ap
        filter_warnings += _w
    # gaming / 4k CPU 預算級距:高預算遊戲機不把中低階 CPU 放主推(office 不套用)
    elif cat == "CPU" and uc in ("gaming", "4k_gaming"):
        kept, _ap, _w = _gaming_cpu_tier_filter(kept, budget)
        applied += _ap
        filter_warnings += _w
    # GPU:gaming 排除工作站/專業卡 + 預算級距(高預算不主推低階卡)
    elif cat == "GPU":
        kept, _ap, _w = _gpu_tier_filter(kept, budget, uc)
        applied += _ap
        filter_warnings += _w
    elif cat == "RAM":
        kept, _ap, _w = _ram_tier_filter(kept, budget, uc)
        applied += _ap
        filter_warnings += _w
    elif cat == "Storage":
        kept, _ap, _w = _storage_tier_filter(kept, budget, uc)
        applied += _ap
        filter_warnings += _w
    elif cat == "PSU":
        _gpu_price = None
        if selected_map.get("GPU"):
            _gpu_price = _get_selected_product_specs(selected_map["GPU"], "GPU", db_path).get("price")
        kept, _ap, _w = _psu_tier_filter(kept, budget, uc, _gpu_price)
        applied += _ap
        filter_warnings += _w
    elif cat == "Motherboard":
        kept, _ap, _w = _mb_tier_filter(kept, budget, constraints)
        applied += _ap
        filter_warnings += _w
    elif cat == "Case":
        kept, _ap, _w = _case_tier_filter(kept, budget)
        applied += _ap
        filter_warnings += _w

    target_price = _target_price_for(cat, budget, remaining_budget, uc)
    picks = _pick_component_options(kept, target_price, limit)

    options: list[dict] = []
    for r in picks:
        pf = r.get("_pf") or _candidate_platform_fields(r, cat)
        # PSU 補上 wattage 給說明用
        if cat == "PSU":
            pf = {**pf, "wattage": _specs_of(r).get("wattage")}
        options.append({
            "product_name": r.get("product_name"),
            "price": r.get("price"),
            "source": r.get("source"),
            "category": cat,
            "brand": r.get("brand"),
            "model": r.get("model"),
            "socket": pf.get("socket"),
            "platform": pf.get("platform"),
            "memory_generation": pf.get("memory_generation"),
            "reason": _build_reason(r.get("_tier", "候選"), cat, pf, gaming),
            "compatibility_notes": _build_compat_notes(cat, pf, constraints),
            "is_virtual": False,
        })

    real_count = len(options)
    warnings: list[str] = list(constraints.get("notes", [])) + list(filter_warnings)
    cpu_specs = constraints.get("cpu_specs")

    # ---- 虛擬「無」選項 ----
    # Cooler:每次都固定多一個「無」選項(price=0);依 CPU 功耗決定是否加提醒。
    if cat == "Cooler":
        if cpu_specs and _cpu_needs_cooler_attention(cpu_specs.get("product_name")):
            cnote = ("選『無』前請確認:此 CPU 可能為高功耗 / K / X3D / 高階款,可能需要額外散熱器;"
                     "請確認 CPU 盒裝是否附原廠散熱器,以及機殼散熱與 CPU 溫度。")
            warnings.append(cnote)
        else:
            cnote = "若 CPU 盒裝已附原廠散熱器或屬低功耗用途,選『無』可為合理選項;仍建議確認盒裝內容。"
        options.append({
            "product_name": _VIRTUAL_NONE_NAME["Cooler"], "price": 0, "source": _VIRTUAL_SOURCE,
            "category": "Cooler", "brand": None, "model": None, "socket": None, "platform": None,
            "memory_generation": None, "reason": "不額外購買散熱器(使用 CPU 盒裝原廠散熱器或既有散熱器)。",
            "compatibility_notes": cnote, "is_virtual": True,
        })

    # GPU:文書(office)且已選 CPU 有內顯時,提供「無獨立顯示卡(使用內顯)」。
    if cat == "GPU" and uc == "office" and (cpu_specs is None or cpu_specs.get("has_igpu") is True):
        options.append({
            "product_name": _VIRTUAL_NONE_NAME["GPU"], "price": 0, "source": _VIRTUAL_SOURCE,
            "category": "GPU", "brand": None, "model": None, "socket": None, "platform": None,
            "memory_generation": None,
            "reason": "文書用途且 CPU 具內顯,可不裝獨立顯卡以節省預算。",
            "compatibility_notes": "使用 CPU 內顯作為畫面輸出;若日後有遊戲/繪圖需求再加裝獨立顯卡。",
            "is_virtual": True,
        })

    # 無內顯 CPU + 未選 GPU 提醒(規則 13);此時不提供 GPU『無』選項
    if cpu_specs and cpu_specs.get("has_igpu") is False and "GPU" not in selected_map:
        warnings.append(
            f"已選 CPU『{cpu_specs.get('product_name')}』無內顯,尚未選顯示卡;"
            f"此配置需搭配獨立顯卡(GPU)才有畫面輸出,不可選『無獨立顯示卡』。")

    # 候選不足提醒(只計實體候選,不含虛擬『無』)
    if real_count < min(limit, 3):
        warnings.append(
            f"此相容條件下 {cat} 實體候選僅 {real_count} 個"
            f"(可能因平台/世代限制或預算上限);如需更多選擇可放寬條件或更新資料庫。")

    # 下一步建議
    chosen = set(selected_map.keys()) | {cat}
    nxt = next((c for c in _SELECTION_ORDER if c not in chosen), None)
    if nxt:
        next_step = f"選定本類別後,建議下一步挑選:{_CATEGORY_LABEL_ZH.get(nxt, nxt)}。"
    else:
        next_step = "主要零件皆已挑選,可用 validate / summarize 工具檢查相容性與總價。"

    return {
        "category": cat,
        "options": options,
        "constraints_applied": applied,
        "warnings": warnings,
        "next_step_suggestion": next_step,
    }


# ============================================================================
# External component recommender adapter(Phase External-Component-Recommender-Integration)
# ----------------------------------------------------------------------------
# 「要推薦哪些零組件候選」的邏輯可委派給外部 recommender(同學的實作)。
# 本 adapter 負責:整理 context → 呼叫外部 → 正規化成現有 options schema →
# 套用最小 safety validation + 固定虛擬「無」選項 → 回給互動流程。
# 外部未接 / 關閉 / 失敗時,一律安全 fallback 到 legacy 內建推薦(功能不壞)。
# ============================================================================

# Feature flag:預設用 legacy(內建 tier/ranking)。設 True 並提供 recommender 才走外部。
USE_EXTERNAL_COMPONENT_RECOMMENDER = False
# 外部 recommender:callable(context: dict) -> list[dict](每個 dict 為一個候選)。None 表示未接。
_EXTERNAL_COMPONENT_RECOMMENDER = None
_EXTERNAL_ENV_LOADED = False


def set_external_component_recommender(fn) -> None:
    """註冊外部 component recommender(同學的函式)。fn(context) -> list[候選 dict]。

    註冊後並把 USE_EXTERNAL_COMPONENT_RECOMMENDER 設為 True,即會改由外部決定候選。
    """
    global _EXTERNAL_COMPONENT_RECOMMENDER
    _EXTERNAL_COMPONENT_RECOMMENDER = fn


def _maybe_load_external_from_env() -> None:
    """支援以環境變數 `PC_BUILDER_EXTERNAL_RECOMMENDER="pkg.module:func"` 接入(零改碼)。"""
    global _EXTERNAL_ENV_LOADED, _EXTERNAL_COMPONENT_RECOMMENDER, USE_EXTERNAL_COMPONENT_RECOMMENDER
    if _EXTERNAL_ENV_LOADED:
        return
    _EXTERNAL_ENV_LOADED = True
    import os
    spec = os.getenv("PC_BUILDER_EXTERNAL_RECOMMENDER")
    if not spec or ":" not in spec:
        return
    mod_name, _, fn_name = spec.partition(":")
    try:
        import importlib
        mod = importlib.import_module(mod_name.strip())
        fn = getattr(mod, fn_name.strip())
        _EXTERNAL_COMPONENT_RECOMMENDER = fn
        USE_EXTERNAL_COMPONENT_RECOMMENDER = True
    except Exception:
        pass  # 接入失敗就維持 legacy,不讓系統壞掉


def _external_recommender_active() -> bool:
    _maybe_load_external_from_env()
    return bool(USE_EXTERNAL_COMPONENT_RECOMMENDER and _EXTERNAL_COMPONENT_RECOMMENDER)


def _build_recommender_context(
    cat, *, budget, use_case, remaining_budget, prefer_platform, selected_map,
    constraints, db_path,
) -> dict:
    """整理一份乾淨 context 給外部 recommender(含預算/用途/已選零件/相容性約束)。"""
    selected_specs = {c: _get_selected_product_specs(n, c, db_path) for c, n in selected_map.items()}
    total = sum(int(s.get("price") or 0) for s in selected_specs.values())
    rb = remaining_budget if remaining_budget is not None else (
        (int(budget) - total) if budget else None)
    cpu_specs = constraints.get("cpu_specs") or selected_specs.get("CPU") or {}
    return {
        "target_category": cat,
        "budget": int(budget) if budget else None,
        "use_case": _classify_use_case(use_case),
        "remaining_budget": rb,
        "current_total": total,
        "total_selected_price": total,
        "prefer_platform": prefer_platform,
        "limit": 3,
        "db_path": db_path,
        "selected_components": selected_specs,           # {category: 規格 dict(已 sanitize)}
        "selected_cpu": selected_map.get("CPU"),
        "selected_gpu": selected_map.get("GPU"),
        "selected_motherboard": selected_map.get("Motherboard"),
        "selected_ram": selected_map.get("RAM"),
        "selected_storage": selected_map.get("Storage"),
        "selected_psu": selected_map.get("PSU"),
        "selected_cooler": selected_map.get("Cooler"),
        "selected_case": selected_map.get("Case"),
        # 相容性約束(供外部過濾;我們這邊也會再做一次 safety validation)
        "constraints": {
            "socket": constraints.get("socket"),
            "memory_generation": constraints.get("memory_generation"),
            "brand": constraints.get("brand"),
        },
        "cpu_has_igpu": cpu_specs.get("has_igpu"),
    }


def _normalize_external_option(raw: dict, cat: str, db_path: str) -> dict:
    """把外部回傳的候選正規化成現有 options schema;不外洩 DB 內部欄位。

    支援兩種輸入:(a) 已成形的 option dict;(b) 原始 DB product dict(含 specs)。
    """
    if not isinstance(raw, dict):
        return {}
    if raw.get("is_virtual"):  # 外部若直接給虛擬「無」選項,原樣保留(僅取白名單欄位)
        return {
            "category": cat, "product_name": raw.get("product_name"), "price": 0,
            "source": raw.get("source") or _VIRTUAL_SOURCE, "source_url": raw.get("source_url"),
            "socket": None, "platform": None, "memory_generation": None,
            "brand": None, "model": None,
            "reason": raw.get("reason") or raw.get("recommendation_reason"),
            "compatibility_notes": raw.get("compatibility_notes"), "is_virtual": True,
        }
    pf = _candidate_platform_fields(raw, cat)
    return {
        "category": cat,
        "product_name": raw.get("product_name"),
        "price": raw.get("price"),
        "source": raw.get("source"),
        "source_url": raw.get("source_url") or raw.get("url"),
        "brand": raw.get("brand") or _pr.cpu_brand_from_text(raw.get("product_name")),
        "model": raw.get("model"),
        "socket": raw.get("socket") or pf.get("socket"),
        "platform": raw.get("platform") or pf.get("platform"),
        "memory_generation": raw.get("memory_generation") or pf.get("memory_generation"),
        "reason": raw.get("reason") or raw.get("recommendation_reason") or "外部 recommender 推薦",
        "compatibility_notes": raw.get("compatibility_notes") or _build_compat_notes(cat, pf, {}),
        "is_virtual": False,
    }


def _safety_filter_options(cat, options, constraints, selected_map, uc):
    """最小 safety validation:過濾明顯不相容的外部候選,回 (filtered, warnings)。

    - CPU/Motherboard:socket 與已選平台不符 → 過濾。
    - RAM:記憶體世代與主機板不相容 → 過濾。
    - Intel/AMD 品牌約束(CPU)→ 過濾。
    """
    socket = constraints.get("socket")
    mem = constraints.get("memory_generation")
    brand = constraints.get("brand")
    kept = []
    warns = []
    dropped = 0
    for o in options:
        if o.get("is_virtual"):
            kept.append(o)
            continue
        if cat in ("CPU", "Motherboard") and socket and o.get("socket") and o["socket"] != socket:
            dropped += 1
            continue
        if cat == "CPU" and brand and o.get("brand") and o["brand"] != brand:
            dropped += 1
            continue
        if cat == "Motherboard" and mem in ("DDR4", "DDR5") and o.get("memory_generation"):
            if not _mem_compatible(mem, o["memory_generation"]):
                dropped += 1
                continue
        if cat == "RAM" and mem in ("DDR4", "DDR5") and o.get("memory_generation"):
            if o["memory_generation"] != mem:
                dropped += 1
                continue
        kept.append(o)
    if dropped:
        warns.append(f"外部 recommender 回傳 {dropped} 個與已選平台不相容的 {cat} 候選,已過濾。")
    return kept, warns


def _inject_virtual_none_options(cat, options, uc, cpu_specs, selected_map, limit):
    """為 GPU(office+內顯)與 Cooler 固定加上虛擬「無」選項(與 legacy 行為一致),回 (options, warnings)。"""
    warns = []
    real_count = sum(1 for o in options if not o.get("is_virtual"))
    has_none = any(o.get("is_virtual") for o in options)
    if cat == "Cooler" and not has_none:
        if cpu_specs and _cpu_needs_cooler_attention(cpu_specs.get("product_name")):
            cnote = ("選『無』前請確認:此 CPU 可能為高功耗 / K / X3D / 高階款,可能需要額外散熱器;"
                     "請確認 CPU 盒裝是否附原廠散熱器,以及機殼散熱與 CPU 溫度。")
            warns.append(cnote)
        else:
            cnote = "若 CPU 盒裝已附原廠散熱器或屬低功耗用途,選『無』可為合理選項;仍建議確認盒裝內容。"
        options = options + [{
            "category": "Cooler", "product_name": _VIRTUAL_NONE_NAME["Cooler"], "price": 0,
            "source": _VIRTUAL_SOURCE, "source_url": None, "brand": None, "model": None,
            "socket": None, "platform": None, "memory_generation": None,
            "reason": "不額外購買散熱器(使用 CPU 盒裝原廠散熱器或既有散熱器)。",
            "compatibility_notes": cnote, "is_virtual": True,
        }]
    if cat == "GPU" and uc == "office" and (cpu_specs is None or cpu_specs.get("has_igpu") is True) and not has_none:
        options = options + [{
            "category": "GPU", "product_name": _VIRTUAL_NONE_NAME["GPU"], "price": 0,
            "source": _VIRTUAL_SOURCE, "source_url": None, "brand": None, "model": None,
            "socket": None, "platform": None, "memory_generation": None,
            "reason": "文書用途且 CPU 具內顯,可不裝獨立顯卡以節省預算。",
            "compatibility_notes": "使用 CPU 內顯作為畫面輸出;若日後有遊戲/繪圖需求再加裝獨立顯卡。",
            "is_virtual": True,
        }]
    if cat == "GPU" and cpu_specs and cpu_specs.get("has_igpu") is False and "GPU" not in selected_map:
        warns.append(
            f"已選 CPU『{cpu_specs.get('product_name')}』無內顯,尚未選顯示卡;"
            f"此配置需搭配獨立顯卡(GPU)才有畫面輸出,不可選『無獨立顯示卡』。")
    if real_count < min(limit, 3):
        warns.append(f"外部 recommender 回傳的 {cat} 實體候選僅 {real_count} 個。")
    return options, warns


def _recommend_component_options_external(
    target_category, *, budget=None, use_case="gaming", remaining_budget=None,
    prefer_platform=None, selected_cpu=None, selected_motherboard=None, selected_ram=None,
    selected_gpu=None, selected_storage=None, selected_psu=None, selected_case=None,
    selected_cooler=None, selected_socket=None, selected_memory_generation=None,
    limit=3, db_path=DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """委派給外部 recommender,再轉成現有 options schema + 套 safety validation + 虛擬「無」。"""
    cat = _canonical_category(target_category)
    if cat is None:
        return {"category": target_category, "options": [], "constraints_applied": [],
                "warnings": [f"無法辨識的 target_category:{target_category}。"], "next_step_suggestion": ""}
    try:
        limit = max(1, min(int(limit), 5))
    except (TypeError, ValueError):
        limit = 3
    uc = _classify_use_case(use_case)
    selected_map = _collect_selected({
        "selected_cpu": selected_cpu, "selected_motherboard": selected_motherboard,
        "selected_ram": selected_ram, "selected_gpu": selected_gpu,
        "selected_storage": selected_storage, "selected_psu": selected_psu,
        "selected_case": selected_case, "selected_cooler": selected_cooler,
    })
    constraints = _resolve_platform_constraints(
        selected_map, prefer_platform, selected_socket, selected_memory_generation, db_path)
    context = _build_recommender_context(
        cat, budget=budget, use_case=use_case, remaining_budget=remaining_budget,
        prefer_platform=prefer_platform, selected_map=selected_map,
        constraints=constraints, db_path=db_path)

    raw = _EXTERNAL_COMPONENT_RECOMMENDER(context) or []   # 同學的邏輯決定候選
    options = [_normalize_external_option(o, cat, db_path) for o in raw if isinstance(o, dict)]
    options = [o for o in options if o.get("product_name")]

    options, safety_warns = _safety_filter_options(cat, options, constraints, selected_map, uc)
    options, vwarns = _inject_virtual_none_options(
        cat, options, uc, constraints.get("cpu_specs"), selected_map, limit)
    # 截斷實體候選到 limit(虛擬「無」保留)
    real = [o for o in options if not o.get("is_virtual")][:limit]
    virtual = [o for o in options if o.get("is_virtual")]
    options = real + virtual

    warnings = list(constraints.get("notes", [])) + safety_warns + vwarns
    applied = ["external_recommender"]
    if constraints.get("socket"):
        applied.append(f"socket={constraints['socket']}")
    if constraints.get("memory_generation") in ("DDR4", "DDR5"):
        applied.append(f"memory_generation={constraints['memory_generation']}")

    chosen = set(selected_map.keys()) | {cat}
    nxt = next((c for c in _SELECTION_ORDER if c not in chosen), None)
    next_step = (f"選定本類別後,建議下一步挑選:{_CATEGORY_LABEL_ZH.get(nxt, nxt)}。" if nxt
                 else "主要零件皆已挑選,可用 validate / summarize 工具檢查相容性與總價。")
    return {
        "category": cat, "options": options, "constraints_applied": applied,
        "warnings": warnings, "next_step_suggestion": next_step,
    }


def recommend_component_options(target_category: str, **kwargs) -> dict[str, Any]:
    """**Dispatcher**:依 feature flag 決定由外部 recommender 或 legacy 內建邏輯決定候選。

    - `USE_EXTERNAL_COMPONENT_RECOMMENDER=True` 且已註冊外部 recommender → 走外部 + adapter。
    - 否則(預設)或外部失敗 → 安全 fallback 到 legacy 內建推薦。
    回傳 schema 與 legacy 一致(category / options / constraints_applied / warnings / next_step_suggestion)。
    """
    if _external_recommender_active():
        try:
            res = _recommend_component_options_external(target_category, **kwargs)
        except Exception as exc:  # 外部出錯 → 安全退回 legacy,不 traceback、不讓互動流程壞掉
            leg = _recommend_component_options_legacy(target_category, **kwargs)
            leg.setdefault("warnings", []).insert(
                0, f"外部 recommender 失敗,已改用內建推薦({exc})。")
            return leg
        # 外部回傳空(無實體候選)→ fallback legacy 並加 warning(legacy 僅為備援)
        if not any(not o.get("is_virtual") for o in res.get("options", [])):
            leg = _recommend_component_options_legacy(target_category, **kwargs)
            leg.setdefault("warnings", []).insert(
                0, "外部 recommender 沒有回傳有效候選,已改用內建推薦。")
            return leg
        return res
    return _recommend_component_options_legacy(target_category, **kwargs)


def validate_selected_build(
    *,
    use_case: str = "gaming",
    budget: int | None = None,
    selected_cpu: str | None = None,
    selected_motherboard: str | None = None,
    selected_ram: str | None = None,
    selected_gpu: str | None = None,
    selected_storage: str | None = None,
    selected_psu: str | None = None,
    selected_case: str | None = None,
    selected_cooler: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """deterministic 檢查目前已選零件是否相容。

    Returns dict:is_valid / issues / warnings / selected_summary /
    missing_categories / total_price / compatibility_summary。
    """
    uc = _classify_use_case(use_case)
    gaming = uc != "office"
    selected_map = _collect_selected({
        "selected_cpu": selected_cpu, "selected_motherboard": selected_motherboard,
        "selected_ram": selected_ram, "selected_gpu": selected_gpu,
        "selected_storage": selected_storage, "selected_psu": selected_psu,
        "selected_case": selected_case, "selected_cooler": selected_cooler,
    })

    specs: dict[str, dict] = {}
    rows: dict[str, dict] = {}
    issues: list[str] = []
    warnings: list[str] = []
    for cat, name in selected_map.items():
        sp = _get_selected_product_specs(name, cat, db_path)
        specs[cat] = sp
        rows[cat] = _match_selected_product(name, cat, db_path)["row"] or {}
        # 比對透明度提醒:找不到 / 模糊比對 / 多筆同分
        if not sp.get("found"):
            warnings.append(
                f"已選 {cat}『{name}』在資料庫中找不到對應商品,該零件的價格/規格未納入計算;"
                f"請改用工具回傳的完整 product_name。")
        elif sp.get("ambiguous"):
            warnings.append(
                f"已選 {cat}『{name}』以模糊比對對應到多筆商品,已採用『{sp.get('product_name')}』"
                f"(價格 {sp.get('price')});若非預期請改用完整 product_name。")
        elif sp.get("match_level") in _FUZZY_LEVELS:
            warnings.append(
                f"已選 {cat}『{name}』以模糊比對對應到『{sp.get('product_name')}』;"
                f"若非預期請改用工具回傳的完整 product_name。")

    # 1) CPU / Motherboard socket 一致
    if "CPU" in specs and "Motherboard" in specs:
        cs = specs["CPU"]["socket"]
        ms = specs["Motherboard"]["socket"]
        if cs and ms:
            if cs != ms:
                issues.append(f"CPU socket({cs})與主機板 socket({ms})不一致,無法安裝。")
        else:
            warnings.append("CPU 或主機板 socket 無法由規格確認,需人工確認相容性。")

    # 2) Motherboard / RAM 記憶體世代相容
    if "Motherboard" in specs and "RAM" in specs:
        mm = specs["Motherboard"]["memory_generation"]
        rm = specs["RAM"]["memory_generation"]
        if mm and rm:
            if not _mem_compatible(rm, mm):
                issues.append(f"主機板記憶體世代({mm})與記憶體({rm})不相容。")
        else:
            warnings.append("主機板或記憶體的世代無法確認,需人工確認 DDR4/DDR5。")

    # GPU 是否為真實獨顯(非『無』虛擬選項)
    gpu_is_none = ("GPU" in specs) and bool(specs["GPU"].get("is_virtual"))
    gpu_real = ("GPU" in selected_map) and not gpu_is_none

    # 3) 顯示輸出守門:沒有真實獨顯時 CPU 必須有內顯(警告)
    if "CPU" in specs and not gpu_real:
        if specs["CPU"].get("has_igpu") is False:
            who = "選了『無獨立顯示卡』" if gpu_is_none else "尚未選顯示卡"
            warnings.append(
                f"已選 CPU『{specs['CPU'].get('product_name')}』無內顯且{who};"
                f"需加裝獨立顯卡(GPU)才有畫面輸出。")

    # 4) gaming 有『真實獨顯』時 PSU >= 550W(警告);GPU=無 不需要
    if gaming and gpu_real and "PSU" in selected_map:
        w = _specs_of(rows.get("PSU", {})).get("wattage")
        if w is None:
            warnings.append("電源瓦數無法確認,建議確認是否 ≥ 550W(含獨立顯卡)。")
        elif w < 550:
            warnings.append(f"電源僅 {w}W;含獨立顯卡建議至少 550W(高階顯卡更高)。")

    # 5) gaming Storage 必須是 SSD 類(警告)
    if gaming and "Storage" in selected_map and not specs["Storage"].get("is_virtual"):
        if not _is_ssd_storage(rows.get("Storage", {})):
            warnings.append("已選儲存裝置可能為純 HDD;遊戲主要儲存建議使用 SSD/NVMe。")

    # 6) Cooler=無 + 高功耗 CPU(警告)
    if ("Cooler" in specs) and specs["Cooler"].get("is_virtual"):
        cpu_name = specs.get("CPU", {}).get("product_name")
        if "CPU" in specs and _cpu_needs_cooler_attention(cpu_name):
            warnings.append(
                f"已選 Cooler=無,但 CPU『{cpu_name}』可能為高功耗 / K / X3D / 高階款;"
                f"請確認 CPU 盒裝是否附原廠散熱器,以及機殼散熱與 CPU 溫度,必要時需加購散熱器。")

    # 摘要
    selected_summary = []
    total_price = 0
    for cat in _SELECTION_ORDER:
        if cat in selected_map:
            p = specs[cat].get("price")
            if isinstance(p, int):
                total_price += p
            selected_summary.append({
                "category": cat,
                "product_name": specs[cat].get("product_name"),
                "price": p,
                "source": specs[cat].get("source"),
                "socket": specs[cat].get("socket"),
                "memory_generation": specs[cat].get("memory_generation"),
                "is_virtual": bool(specs[cat].get("is_virtual")),
            })

    missing_categories = [c for c in _SELECTION_ORDER if c not in selected_map]
    # 文書機不需獨顯,GPU 不算缺
    if uc == "office" and "GPU" in missing_categories:
        missing_categories = [c for c in missing_categories if c != "GPU"]

    is_valid = len(issues) == 0
    if "CPU" in specs and "Motherboard" in specs and not issues:
        compat = f"已選 CPU/主機板 socket 一致({specs['CPU'].get('socket')})"
        if "RAM" in specs:
            compat += f";記憶體世代 {specs['RAM'].get('memory_generation')} 與主機板相容"
        compat += "。其餘(機殼空間/散熱器高度/供電接頭)仍需人工確認。"
    elif issues:
        compat = "偵測到相容性問題:" + ";".join(issues)
    else:
        compat = "目前已選零件不足以完整驗證相容性(尚缺 CPU/主機板/RAM 之一)。"

    return {
        "is_valid": is_valid,
        "issues": issues,
        "warnings": warnings,
        "selected_summary": selected_summary,
        "missing_categories": missing_categories,
        "total_price": total_price,
        "compatibility_summary": compat,
    }


def summarize_selected_build(
    *,
    use_case: str = "gaming",
    budget: int | None = None,
    selected_cpu: str | None = None,
    selected_motherboard: str | None = None,
    selected_ram: str | None = None,
    selected_gpu: str | None = None,
    selected_storage: str | None = None,
    selected_psu: str | None = None,
    selected_case: str | None = None,
    selected_cooler: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """彙整目前已選零件:清單 / 總價 / 預算 / 剩餘預算 / 缺少類別 / 相容性 / 下一步。

    Returns dict:selected_summary / total_price / budget / remaining_budget /
    missing_categories / compatibility_summary / next_recommended_category /
    next_recommended_category_key / is_complete / warnings。
    """
    v = validate_selected_build(
        use_case=use_case, budget=budget,
        selected_cpu=selected_cpu, selected_motherboard=selected_motherboard,
        selected_ram=selected_ram, selected_gpu=selected_gpu,
        selected_storage=selected_storage, selected_psu=selected_psu,
        selected_case=selected_case, selected_cooler=selected_cooler,
        db_path=db_path,
    )
    total_price = v["total_price"]
    remaining = (int(budget) - total_price) if budget else None

    # 下一步:依固定順序(get_next_component_category);office 的 GPU 也算需選(可選『無』)。
    selected_map = _collect_selected({
        "selected_cpu": selected_cpu, "selected_motherboard": selected_motherboard,
        "selected_ram": selected_ram, "selected_gpu": selected_gpu,
        "selected_storage": selected_storage, "selected_psu": selected_psu,
        "selected_case": selected_case, "selected_cooler": selected_cooler,
    })
    next_cat = get_next_component_category(selected_map, use_case)
    next_recommended = _CATEGORY_LABEL_ZH.get(next_cat, next_cat) if next_cat else None
    is_complete = next_cat is None

    warnings = list(v["warnings"])
    if not v["is_valid"]:
        warnings = v["issues"] + warnings
    if remaining is not None and remaining < 0:
        warnings.append(f"已選零件總價 {total_price} 元已超出預算 {budget} 元 {abs(remaining)} 元。")
    elif remaining is not None and budget and remaining > int(budget) * 0.3:
        warnings.append(
            f"目前總價 {total_price} 元,離預算 {budget} 元尚有 {remaining} 元;"
            f"若想用滿預算,可考慮升級 GPU / CPU / Storage。")

    return {
        "selected_summary": v["selected_summary"],
        "total_price": total_price,
        "budget": int(budget) if budget else None,
        "remaining_budget": remaining,
        "missing_categories": v["missing_categories"],
        "compatibility_summary": v["compatibility_summary"],
        "next_recommended_category": next_recommended,
        "next_recommended_category_key": next_cat,
        "is_complete": is_complete,
        "warnings": warnings,
    }


# ============================================================================
# 保存最終菜單為 JSON(互動式選件完成後;只在使用者明確確認時呼叫)
# ============================================================================

_DEFAULT_BUILD_OUTPUT_DIR = "outputs/builds"


def build_selected_build_payload(
    selected_map: dict[str, str],
    *,
    budget: int | None,
    use_case: str,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """把已選零件整理成可保存 / 顯示的 build payload(含 virtual 選項)。"""
    v = validate_selected_build(
        use_case=use_case, budget=budget,
        selected_cpu=selected_map.get("CPU"), selected_motherboard=selected_map.get("Motherboard"),
        selected_ram=selected_map.get("RAM"), selected_gpu=selected_map.get("GPU"),
        selected_storage=selected_map.get("Storage"), selected_psu=selected_map.get("PSU"),
        selected_case=selected_map.get("Case"), selected_cooler=selected_map.get("Cooler"),
        db_path=db_path,
    )
    components: list[dict] = []
    for cat in COMPONENT_SELECTION_ORDER:
        if cat not in selected_map:
            continue
        sp = _get_selected_product_specs(selected_map[cat], cat, db_path)
        components.append({
            "category": cat,
            "product_name": sp.get("product_name"),
            "price": sp.get("price") or 0,
            "source": sp.get("source"),
            "socket": sp.get("socket"),
            "platform": sp.get("platform"),
            "memory_generation": sp.get("memory_generation"),
            "is_virtual": bool(sp.get("is_virtual")),
        })
    total_price = sum(int(c["price"]) for c in components if isinstance(c["price"], int))
    remaining = (int(budget) - total_price) if budget else None
    warnings = list(v["warnings"])
    if not v["is_valid"]:
        warnings = v["issues"] + warnings
    return {
        "budget": int(budget) if budget else None,
        "use_case": _classify_use_case(use_case),
        "total_price": total_price,
        "remaining_budget": remaining,
        "components": components,
        "compatibility_summary": v["compatibility_summary"],
        "warnings": warnings,
        "missing_categories": v["missing_categories"],
    }


def save_selected_build(
    selected_map: dict[str, str],
    *,
    budget: int | None,
    use_case: str,
    created_at: str,
    output_dir: str = _DEFAULT_BUILD_OUTPUT_DIR,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """把最終菜單寫成 JSON 檔(不覆蓋舊檔;不寫 data/)。

    created_at 由呼叫端(tool 層)以當下時間帶入,檔名用其時間戳。回傳
    ok / output_path / total_price / component_count / warnings。
    """
    payload = build_selected_build_payload(
        selected_map, budget=budget, use_case=use_case, db_path=db_path)
    payload = {"created_at": created_at, **payload}

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 檔名時間戳:由 created_at 取數字部分,失敗則用安全字串
    stamp = re.sub(r"[^0-9]", "", created_at)[:14] or "build"
    base = f"pc_build_{stamp}"
    path = out_dir / f"{base}.json"
    n = 2
    while path.exists():  # 不覆蓋舊檔
        path = out_dir / f"{base}_{n}.json"
        n += 1
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "output_path": str(path),
        "total_price": payload["total_price"],
        "component_count": len(payload["components"]),
        "warnings": payload["warnings"],
    }


# ============================================================================
# State-driven 互動式選件引擎(Phase Interactive-State-Driven-Fix)
# 第 N 個解析 / 下一步類別 / selected_components 更新 / 渲染 全部 deterministic,
# 不依賴 LLM tool-calling,避免跳過工具或自寫候選。
# ============================================================================

_ARG_KEY = {
    "CPU": "selected_cpu", "GPU": "selected_gpu", "Motherboard": "selected_motherboard",
    "RAM": "selected_ram", "Storage": "selected_storage", "PSU": "selected_psu",
    "Cooler": "selected_cooler", "Case": "selected_case",
}
_ZH_NUM = {"一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9}
_RESELECT_VERBS = ("重新選", "重選", "重新挑", "換", "太貴")
_CAT_WORD = {
    "cpu": "CPU", "處理器": "CPU", "顯示卡": "GPU", "顯卡": "GPU", "gpu": "GPU",
    "主機板": "Motherboard", "記憶體": "RAM", "ram": "RAM", "儲存": "Storage",
    "硬碟": "Storage", "ssd": "Storage", "電源": "PSU", "psu": "PSU",
    "散熱器": "Cooler", "散熱": "Cooler", "機殼": "Case",
}
_BUILD_INTENT = ("組電腦", "組一台", "組一臺", "組機", "遊戲機", "文書機", "辦公機",
                 "工作機", "配一台", "組遊戲", "組台電腦", "裝一台")
_PRICE_QUERY = ("優惠", "特價", "折扣", "比價", "多少錢", "報價", "促銷", "庫存",
                "現貨", "搭主機板", "bundle", "搭板", "deal")


def _parse_choice_index(text: str | None) -> int | None:
    """由文字解析使用者要選『第幾個』;解析不出回 None。"""
    if not text:
        return None
    t = str(text).strip()
    m = re.search(r"第\s*([0-9一二兩三四五六七八九])\s*[個張顆隻支台片條]?", t)
    if m:
        g = m.group(1)
        return int(g) if g.isdigit() else _ZH_NUM.get(g)
    m = re.search(r"(?:選|選擇|要|挑)\s*第?\s*([0-9]{1,2})", t)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"\s*([0-9]{1,2})\s*", t)
    if m:
        return int(m.group(1))
    return None


def _is_none_intent(text: str | None) -> bool:
    if not text:
        return False
    return any(k in text for k in ("無", "不買", "不需要", "不額外", "不用買", "不裝", "跳過", "略過"))


def resolve_selection_from_last_options(
    user_text: str | None, last_options: list | None, current_target_category: str | None = None
) -> dict | None:
    """由 state.last_component_options + 使用者文字 deterministic 解析所選候選;解析不出回 None。

    - 『第 N 個 / 選 N / N』→ last_options[N-1]。
    - 『無 / 不買 / 不需要』且當前類別為 Cooler / GPU → 該類的虛擬『無』選項(若存在)。
    """
    if not last_options:
        return None
    if current_target_category in ("Cooler", "GPU") and _is_none_intent(user_text):
        for o in last_options:
            if o.get("is_virtual"):
                return o
    idx = _parse_choice_index(user_text)
    if idx and 1 <= idx <= len(last_options):
        return last_options[idx - 1]
    return None


def _option_to_selected(option: dict, category: str) -> dict:
    """把推薦候選 option 正規化成 selected_components 條目。"""
    return {
        "category": category,
        "product_name": option.get("product_name"),
        "price": option.get("price") or 0,
        "source": option.get("source"),
        "socket": option.get("socket"),
        "platform": option.get("platform"),
        "memory_generation": option.get("memory_generation"),
        "is_virtual": bool(option.get("is_virtual")),
    }


def detect_reselect_category(text: str | None) -> str | None:
    """偵測『重新選/換/太貴 + 某類別』;回 canonical 類別或 None。"""
    if not text or not any(v in text for v in _RESELECT_VERBS):
        return None
    low = text.lower()
    for w, cat in _CAT_WORD.items():
        if w in low:
            return cat
    return None


def is_confirm_save_text(text: str | None) -> bool:
    if not text:
        return False
    if any(k in text for k in ("確認此菜單", "確認菜單", "確認這套", "確認配置", "就這套",
                               "就這台", "保存", "存成json", "存成 json", "存檔", "存起來",
                               "輸出json", "輸出 json", "存成檔", "保存成")):
        return True
    return text.strip() in ("確認", "確定", "OK", "ok", "好", "就這套")


def is_explicit_full_menu_text(text: str | None) -> bool:
    if not text:
        return False
    return any(k in text for k in ("完整菜單", "完整 8 類", "完整8類", "一次配好", "不用讓我選",
                                   "直接產生完整", "直接幫我配", "直接配一台", "直接配好",
                                   "一次給整套", "整套配好", "一次給我完整"))


def _detect_brand_from_text(text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower()
    if "都可以" in text or "都行" in text or "都ok" in t:
        return None
    has_amd = ("amd" in t) or ("ryzen" in t)
    has_intel = ("intel" in t) or bool(re.search(r"\bi[3579]\b", t)) or ("core ultra" in t)
    if has_amd and has_intel:
        return None
    if has_amd:
        return "AMD"
    if has_intel:
        return "Intel"
    return None


_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_num(s: str | None) -> float | None:
    """把小數量級的中文/阿拉伯數字字串轉成數值;轉不出回 None。

    支援:'5' / '1.5' / '一'(1) / '兩'(2) / '十'(10) / '十二'(12) / '二十'(20) / '二十五'(25)。
    """
    if not s:
        return None
    s = s.strip()
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", s):
        return float(s) if "." in s else int(s)
    if s == "十":
        return 10
    if "十" in s:
        left, _, right = s.partition("十")
        tens = _CN_DIGIT.get(left, 1) if left else 1
        ones = _CN_DIGIT.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(s) == 1 and s in _CN_DIGIT:
        return _CN_DIGIT[s]
    # 多位純中文個位數(罕見)取第一個
    return _CN_DIGIT.get(s[0]) if s and s[0] in _CN_DIGIT else None


def _extract_budget_from_text(text: str | None) -> int | None:
    """從文字解析預算(支援中文金額);避免把商品型號數字(RTX 5070 / i5-12400F / B650 / DDR5)當預算。"""
    if not text:
        return None

    # 1) 『<數>萬<數?>』:數可為阿拉伯或中文(十萬 / 十二萬 / 三萬 / 一萬五 / 5萬5 / 1.5萬)
    m = re.search(
        r"([0-9]+(?:\.[0-9]+)?|[零〇一二兩三四五六七八九十]+)\s*萬\s*([0-9]|[一二兩三四五六七八九])?",
        text,
    )
    if m:
        pre = _cn_num(m.group(1))
        if pre is not None:
            val = pre * 10000
            post = _cn_num(m.group(2)) if m.group(2) else None
            if post is not None:
                val += post * 1000  # 『X萬Y』的 Y 代表千位
            return int(val)

    # 2) 阿拉伯數字:需有預算語境(預算/$/花/約 在前,或 元/塊/k 在後),或整句就是一個數字;
    #    且數字不可黏在英數/連字號型號上(排除 i5-12400F / RTX5070 / B650 / DDR5)。
    whole_number = bool(re.fullmatch(r"\s*[0-9][0-9,]{2,}\s*", text))
    for mm in re.finditer(r"(?<![A-Za-z0-9\-/])([0-9][0-9,]{2,})(?![0-9A-Za-z])", text):
        n = int(mm.group(1).replace(",", ""))
        if n < 3000:
            continue
        start, end = mm.span(1)
        before = text[max(0, start - 4):start]
        after = text[end:end + 3].lstrip()
        cue = (
            "預算" in before or "$" in before or "花" in before or "約" in before
            or after.startswith(("元", "塊"))
            or after[:1].lower() == "k"
            or whole_number
        )
        if cue:
            return n
    return None


def _detect_use_case_from_text(text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower()
    if any(k in text for k in ("文書", "辦公", "office")):
        return "office"
    if "4k" in t or "2160" in t:
        return "4k_gaming"
    if any(k in text for k in ("遊戲", "電競")) or "gaming" in t or "1080" in t or "1440" in t or "2k" in t:
        return "gaming"
    return None


def is_interactive_intent_text(text: str | None) -> bool:
    """是否為互動式逐步選件意圖(用於 fresh 對話的分類)。"""
    if not text:
        return False
    t = text.lower()
    if any(k in text for k in _BUILD_INTENT):
        return True
    if any(k in t for k in ("從cpu", "從 cpu", "自己挑", "自己選", "挑零件", "選零件", "逐步", "一個一個")):
        return True
    if any(k in text for k in ("候選", "選項", "幾個", "幾款")):
        return True
    if _parse_choice_index(text) is not None:
        return True
    if any(k in text for k in ("下一步", "接下來")):
        return True
    if detect_reselect_category(text) or is_confirm_save_text(text):
        return True
    if _detect_brand_from_text(text) and any(k in t for k in ("cpu", "處理器", "組", "遊戲", "文書")):
        return True
    return False


def is_selection_like_input(text: str | None) -> bool:
    """是否為『選件動作』輸入:純數字 / 第 N 個 / 無 / 確認保存 / 重新選 X。

    這類輸入只有在『已有 active selection flow』時才有意義;fresh session 不應拿它開始流程。
    """
    if not text:
        return False
    if _parse_choice_index(text) is not None:
        return True
    if _is_none_intent(text):
        return True
    if is_confirm_save_text(text):
        return True
    if detect_reselect_category(text):
        return True
    return False


def has_active_selection_state(state: dict | None) -> bool:
    """是否已有正在進行(或已完成)的互動式選件狀態。"""
    if not state:
        return False
    return bool(
        state.get("current_target_category")
        or state.get("last_component_options")
        or state.get("selected_components")
        or state.get("selection_flow_complete")
    )


def is_budget_only_input(text: str | None) -> bool:
    """是否為『只給預算』的裸句(如「我預算 30000」「預算 3 萬」「30000 元」)。

    需含可解析的預算,且**不**含用途 / 組機·選件意圖 / 價格優惠查詢 / 明確品類·型號查詢。
    這類輸入應進互動式 guard 詢問用途,而非走一般 LLM 商品查詢。
    """
    if not text:
        return False
    if _extract_budget_from_text(text) is None:
        return False
    low = text.lower()
    if any(k in low for k in _PRICE_QUERY):
        return False
    if _detect_use_case_from_text(text) is not None:
        return False
    if is_interactive_intent_text(text) or is_selection_like_input(text):
        return False
    # 明確品類 / 型號 / 找查推薦 → 視為商品查詢,不算 budget-only
    if any(k in low for k in (
            "找", "查", "推薦", "gpu", "cpu", "顯卡", "顯示卡", "主機板", "記憶體", "ram",
            "ssd", "硬碟", "儲存", "電源", "機殼", "散熱", "rtx", "rx", "arc", "ryzen",
            "ultra", "i5", "i7", "i9", "r5", "r7", "r9")):
        return False
    return True


def _start_intent_hint() -> str:
    """fresh session 提示:請先提供預算與用途。"""
    return (
        "請先告訴我你的預算與用途,例如:\n"
        "「我預算 30000,要組遊戲機,但我想自己挑零件,請從 CPU 開始。」\n"
        "或\n"
        "「我預算 20000,要組中低階文書機,請從 CPU 開始。」"
    )


def classify_ecommerce_mode(text: str | None, has_active_flow: bool) -> str:
    """回 'full_menu' / 'interactive' / 'llm':決定 ecommerce node 該走哪條路。"""
    if is_explicit_full_menu_text(text):
        return "full_menu"
    price_q = bool(text) and any(k in text.lower() for k in _PRICE_QUERY)
    if has_active_flow:
        selectiony = (
            _parse_choice_index(text) is not None or _is_none_intent(text)
            or detect_reselect_category(text) or is_confirm_save_text(text)
            or (text and any(k in text for k in ("下一步", "接下來", "候選", "選項")))
        )
        if selectiony:
            return "interactive"
        if price_q:
            return "llm"
        return "interactive"
    # fresh:選件動作(裸 1 / 我選第 N 個 / 無 / 確認)、只給預算的裸句也走 interactive,
    # 由引擎 guard 友善詢問缺少資訊,不走一般 LLM 商品查詢。
    if is_selection_like_input(text) or is_budget_only_input(text):
        return "interactive"
    if is_interactive_intent_text(text) and not price_q:
        return "interactive"
    return "llm"


# ---- 渲染(deterministic 文字) ----
def _sc_total(sc: dict) -> int:
    return sum(int(c.get("price") or 0) for c in sc.values())


def _render_running_list(sc: dict, budget: int | None) -> tuple[int, str]:
    lines = ["目前已選零件:"]
    if not sc:
        lines.append("- (尚未選擇任何零件)")
    total = 0
    for cat in COMPONENT_SELECTION_ORDER:
        if cat in sc:
            c = sc[cat]
            p = int(c.get("price") or 0)
            total += p
            lines.append(f"- {_CATEGORY_LABEL_ZH.get(cat, cat)}:{c.get('product_name')},{p:,} 元")
    lines.append(f"\n目前總額:{total:,} 元")
    if budget:
        lines.append(f"剩餘預算:{int(budget) - total:,} 元")
    return total, "\n".join(lines)


def _render_options_block(category: str, options: list, warnings: list | None = None) -> str:
    zh = _CATEGORY_LABEL_ZH.get(category, category)
    lines = [f"{zh}候選:"]
    for i, o in enumerate(options, 1):
        bits = []
        plat = o.get("platform") or o.get("socket")
        if plat:
            bits.append(plat)
        if o.get("memory_generation"):
            bits.append(o["memory_generation"])
        meta = (" - " + " / ".join(bits)) if bits else ""
        lines.append(f"{i}. {o.get('product_name')} - {int(o.get('price') or 0):,} 元{meta}")
        if o.get("reason"):
            lines.append(f"   推薦理由:{o['reason']}")
        if o.get("compatibility_notes"):
            lines.append(f"   相容性:{o['compatibility_notes']}")
    for w in (warnings or []):
        lines.append(f"⚠️ {w}")
    lines.append("\n請回覆要選第幾個(例如「我選第 1 個」);散熱器/顯示卡若不需要可回「無」。")
    return "\n".join(lines)


def _render_complete_menu(sc: dict, budget: int | None) -> str:
    total, listtxt = _render_running_list(sc, budget)
    lines = ["完整菜單:"]
    for cat in COMPONENT_SELECTION_ORDER:
        if cat in sc:
            c = sc[cat]
            lines.append(f"- {_CATEGORY_LABEL_ZH.get(cat, cat)}:{c.get('product_name')},{int(c.get('price') or 0):,} 元")
    lines.append(f"\n總價:{total:,} 元")
    if budget:
        diff = int(budget) - total
        lines.append(f"預算:{int(budget):,} 元")
        lines.append(f"差額:{diff:,} 元" + ("(超出預算!)" if diff < 0 else ""))
        if diff < 0:
            lines.append("⚠️ 總價已超出預算,建議重新選較便宜的零件。")
        elif budget and diff > int(budget) * 0.3:
            lines.append("提示:離預算還很多,可考慮升級 GPU / CPU / Storage。")
    lines.append(
        "\n你可以:\n1. 確認此菜單  2. 重新選 CPU  3. 重新選顯示卡  4. 重新選主機板  "
        "5. 重新選記憶體  6. 重新選硬碟/儲存  7. 重新選電源  8. 重新選散熱器  9. 重新選機殼\n"
        "(說「確認此菜單 / 保存 / 存成 JSON」即可存檔)")
    return "\n".join(lines)


def _reselect_dependency_notice(category: str) -> str:
    return {
        "CPU": "提醒:重新選 CPU 後,主機板 / 記憶體 / 散熱器 / 顯示卡可能需要一併重選以維持相容。",
        "Motherboard": "提醒:重新選主機板後,記憶體(DDR4/DDR5)可能需要重選。",
        "GPU": "提醒:重新選顯示卡後,電源供應器(瓦數)可能需要重選。",
        "Cooler": "提醒:重新選散熱器後,請確認機殼空間與散熱器高度 / 水冷排是否相容。",
    }.get(category, "")


def _write_build_json(payload: dict, output_dir: str) -> str:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = re.sub(r"[^0-9]", "", payload.get("created_at", ""))[:14] or "build"
    base = f"pc_build_{stamp}"
    path = out_dir / f"{base}.json"
    n = 2
    while path.exists():
        path = out_dir / f"{base}_{n}.json"
        n += 1
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def save_selected_components(
    selected_components: dict,
    *,
    budget: int | None,
    use_case: str,
    created_at: str,
    output_dir: str = _DEFAULT_BUILD_OUTPUT_DIR,
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """直接由 state.selected_components(已含完整規格)寫 JSON,不重新向 LLM 要商品名。"""
    components = [selected_components[c] for c in COMPONENT_SELECTION_ORDER if c in selected_components]
    total = sum(int(c.get("price") or 0) for c in components)
    remaining = (int(budget) - total) if budget else None
    # 相容性摘要 / warnings:用已選名稱跑一次 validate(名稱來自 DB / 虛擬,皆可解析)
    names = {_ARG_KEY[c]: selected_components[c]["product_name"]
             for c in selected_components if c in _ARG_KEY}
    v = validate_selected_build(use_case=use_case, budget=budget, db_path=db_path, **names)
    warnings = list(v["warnings"]) + ([] if v["is_valid"] else v["issues"])
    payload = {
        "created_at": created_at,
        "budget": int(budget) if budget else None,
        "use_case": _classify_use_case(use_case),
        "total_price": total,
        "remaining_budget": remaining,
        "components": components,
        "compatibility_summary": v["compatibility_summary"],
        "warnings": warnings,
        "missing_categories": v["missing_categories"],
    }
    path = _write_build_json(payload, output_dir)
    return {"ok": True, "output_path": path, "total_price": total,
            "component_count": len(components), "warnings": warnings}


# 完整菜單操作選單:索引 -> 動作(對應 _render_complete_menu 的『1.確認…9.重新選機殼』)
_MENU_ACTION_INDEX = {
    1: "confirm", 2: "CPU", 3: "GPU", 4: "Motherboard", 5: "RAM",
    6: "Storage", 7: "PSU", 8: "Cooler", 9: "Case",
}


def parse_completed_menu_action(user_text: str | None) -> tuple | None:
    """完整菜單(selection_flow_complete)時把輸入解析成 ('confirm', None) 或 ('reselect', category)。

    **只在完整菜單畫面時**呼叫:此時純數字 1~9 代表操作選單(1=確認此菜單;2~9=重新選對應類別);
    也接受文字『確認 / 重新選 X / 換 X / X 太貴』。解析不出回 None。
    一般候選階段(尚未完成)**不**走此函式,純數字仍代表候選第 N 個。
    """
    if not user_text:
        return None
    if is_confirm_save_text(user_text):
        return ("confirm", None)
    rc = detect_reselect_category(user_text)
    if rc:
        return ("reselect", rc)
    idx = _parse_choice_index(user_text)
    if idx in _MENU_ACTION_INDEX:
        a = _MENU_ACTION_INDEX[idx]
        return ("confirm", None) if a == "confirm" else ("reselect", a)
    return None


def _reselect_remove_dependents(sc: dict, category: str) -> tuple[list[str], list[str]]:
    """重新選某類時,deterministic 移除受影響(相依)的下游已選零件;回傳 (removed, warnings)。

    CPU→GPU 的條件移除(新 CPU 無內顯且 GPU 為虛擬『無』)在選到新 CPU 時另外處理,不在此。
    """
    removed: list[str] = []
    warns: list[str] = []
    if category == "CPU":
        for c in ("Motherboard", "RAM", "Cooler"):
            if c in sc:
                del sc[c]
                removed.append(c)
    elif category == "Motherboard":
        if "RAM" in sc:
            del sc["RAM"]
            removed.append("RAM")
        if "Cooler" in sc:
            warns.append("重選主機板:請確認散熱器扣具是否仍相容(未自動移除)。")
    elif category == "GPU":
        if "PSU" in sc:
            del sc["PSU"]
            removed.append("PSU")
        if "Case" in sc:
            warns.append("重選顯示卡:請確認機殼可容納新顯卡長度(未自動移除)。")
    elif category == "Cooler":
        if "Case" in sc:
            warns.append("重選散熱器:請確認機殼可容納散熱器高度 / AIO 水冷排(未自動移除)。")
    elif category == "Case":
        warns.append("重選機殼:請確認 GPU 長度 / 散熱器高度仍相容。")
    return removed, warns


def run_interactive_selection(
    state: dict, *, created_at: str, db_path: str = DEFAULT_DB_PATH,
    output_dir: str = _DEFAULT_BUILD_OUTPUT_DIR,
) -> dict[str, Any]:
    """State-driven 互動式選件引擎。回傳 graph state 更新(含 final_answer / interactive_response)。

    created_at:由呼叫端(node)以當下時間帶入(用於保存 JSON 檔名/內容)。
    """
    sc = dict(state.get("selected_components") or {})
    budget = state.get("selected_budget")
    use_case = state.get("selected_use_case")
    last_opts = list(state.get("last_component_options") or [])
    cur = state.get("current_target_category")
    text = state.get("request", "") or ""

    b = _extract_budget_from_text(text)
    if b:
        budget = b
    uc = _detect_use_case_from_text(text)
    if uc:
        use_case = uc
    # 注意:此時**不要**預設 use_case=gaming;fresh-session guard 需要知道使用者是否真的給了用途。

    active = has_active_selection_state(state)

    # ---- fresh-session guard:沒有 active flow 時,不可用裸選件動作 / 不足資訊開始 gaming ----
    def _ask(msg: str) -> dict:
        # 友善提示:不推薦、不預設 gaming、不更新 selected_components、不保存。
        # 僅保留(若使用者明確給了)budget / use_case 供下一輪續用。
        out = {"final_answer": msg, "ecommerce_advice": msg, "interactive_response": True}
        if budget:
            out["selected_budget"] = budget
        if use_case:
            out["selected_use_case"] = use_case
        return out

    if not active:
        if is_selection_like_input(text):
            if _is_none_intent(text):
                msg = ("目前沒有正在進行的選件流程,也沒有候選可以選"
                       "(『無』請在散熱器 / 顯示卡的選擇階段使用)。\n\n" + _start_intent_hint())
            elif is_confirm_save_text(text):
                msg = ("目前尚未開始或尚未完成選件流程,無法確認 / 保存。\n\n" + _start_intent_hint())
            else:  # 純數字 / 我選第 N 個 / 重新選 X
                msg = ("目前還沒有正在進行的選件流程,也沒有上一輪候選可以選。\n\n" + _start_intent_hint())
            return _ask(msg)
        # 非選件動作:視為起手意圖,但需 budget + use_case 才能開始(不預設 gaming)
        if not budget or not use_case:
            if not budget and not use_case:
                msg = _start_intent_hint()
            elif not use_case:
                msg = (f"收到預算 {int(budget):,} 元。請再告訴我用途(遊戲 / 文書 / 4K 遊戲 / 剪輯),例如:\n"
                       f"「我預算 {int(budget):,},要組遊戲機,請從 CPU 開始。」")
            else:
                zh_uc = {"gaming": "遊戲機", "4k_gaming": "4K 遊戲機", "office": "文書機"}.get(use_case, "電腦")
                msg = (f"收到用途。請再告訴我預算,例如:\n"
                       f"「我預算 30000,要組{zh_uc},請從 CPU 開始。」")
            return _ask(msg)

    if not use_case:
        use_case = "gaming"

    def options_for(category: str) -> dict:
        names = {_ARG_KEY[c]: sc[c]["product_name"] for c in sc if c in _ARG_KEY}
        total = _sc_total(sc)
        rb = (int(budget) - total) if budget else None
        prefer = _detect_brand_from_text(text) if category == "CPU" else None
        return recommend_component_options(
            target_category=category, budget=budget, use_case=use_case,
            remaining_budget=rb, prefer_platform=prefer, db_path=db_path, **names)

    def _finish(msg: str, **extra) -> dict:
        out = {"selected_budget": budget, "selected_use_case": use_case,
               "selected_components": sc, "final_answer": msg, "ecommerce_advice": msg,
               "interactive_response": True}
        out.update(extra)
        return out

    def _do_reselect(cat: str) -> dict:
        """進入『重新選 cat』:移除相依下游零件 + cat 本身,推薦 cat 候選。"""
        removed, warns = _reselect_remove_dependents(sc, cat)
        sc.pop(cat, None)  # 移除該類本身,待重新選
        res = options_for(cat)
        opts = res["options"]
        _, listtxt = _render_running_list(sc, budget)
        parts = [f"你正在重新選 {_CATEGORY_LABEL_ZH.get(cat, cat)}。"]
        if removed:
            parts.append("因相容性可能改變,以下相依零件已自動移除需重新選:"
                         + "、".join(_CATEGORY_LABEL_ZH.get(c, c) for c in removed))
        for w in warns:
            parts.append("⚠️ " + w)
        parts.append(listtxt)
        parts.append(_render_options_block(cat, opts, res.get("warnings")))
        return _finish("\n\n".join(p for p in parts if p),
                       current_target_category=cat, last_component_options=opts,
                       pending_reselect_category=cat, selection_flow_complete=False)

    # 是否已選完所有類別(完整菜單畫面);以 selected_components 為唯一權威依據
    completed = bool(sc) and get_next_component_category(sc, use_case) is None

    # 0) 完整菜單操作介面:1~9 / 確認 / 重新選 X(deterministic,不靠 LLM)
    if completed:
        action = parse_completed_menu_action(text)
        if action is None:
            menu = _render_complete_menu(sc, budget)
            return _finish(menu + "\n\n(請輸入 1~9,或說「確認此菜單 / 重新選 CPU」等。)",
                           selection_flow_complete=True, current_target_category=None,
                           last_component_options=[], pending_reselect_category=None)
        if action[0] == "confirm":
            # 策略:在完整菜單按「1 / 確認此菜單 / 保存」即視為確認並直接保存 JSON。
            saveres = save_selected_components(
                sc, budget=budget, use_case=use_case, created_at=created_at,
                output_dir=output_dir, db_path=db_path)
            menu = _render_complete_menu(sc, budget)
            return _finish(menu + f"\n\n已確認並保存最終菜單。\nJSON 路徑:{saveres['output_path']}",
                           selection_flow_complete=True, current_target_category=None,
                           last_component_options=[], pending_reselect_category=None)
        return _do_reselect(action[1])

    # 1) 確認 / 保存(尚未選完 → 提醒還缺哪些)
    if is_confirm_save_text(text):
        _, listtxt = _render_running_list(sc, budget)
        missing = [c for c in COMPONENT_SELECTION_ORDER if c not in sc]
        zh_missing = "、".join(_CATEGORY_LABEL_ZH.get(c, c) for c in missing)
        return _finish(listtxt + f"\n\n尚未選完(還缺:{zh_missing}),請先選完所有零件再確認保存。")

    # 2) 重新選某類(文字觸發『重新選 X / 換 X / X 太貴』;含相依零件自動移除)
    rc = detect_reselect_category(text)
    if rc:
        return _do_reselect(rc)

    # 3) 從 last_options 解析『第 N 個 / 無』
    sel = resolve_selection_from_last_options(text, last_opts, cur) if (last_opts and cur) else None
    if sel is not None:
        sc[cur] = _option_to_selected(sel, cur)
        was_reselect = (state.get("pending_reselect_category") == cur)
        header: list[str] = []
        if was_reselect:
            header.append(
                f"已重新選擇 {_CATEGORY_LABEL_ZH.get(cur, cur)}:"
                f"{sc[cur].get('product_name')},{int(sc[cur].get('price') or 0):,} 元")
            # CPU 重選後條件移除:新 CPU 無內顯且 GPU 為虛擬『無』 → 移除 GPU 需重選
            if cur == "CPU":
                gpu = sc.get("GPU")
                if gpu and gpu.get("is_virtual") and not _cpu_has_igpu(
                        {"product_name": sc["CPU"].get("product_name")}):
                    del sc["GPU"]
                    header.append("新 CPU 無內顯,已移除『無獨立顯示卡』,需重新選顯示卡。")
        nxt = get_next_component_category(sc, use_case)
        if nxt is None:
            menu = _render_complete_menu(sc, budget)
            return _finish("\n\n".join(header + [menu]) if header else menu,
                           current_target_category=None, last_component_options=[],
                           pending_reselect_category=None, selection_flow_complete=True)
        res = options_for(nxt)
        opts = res["options"]
        _, listtxt = _render_running_list(sc, budget)
        body = _render_options_block(nxt, opts, res.get("warnings"))
        nxt_line = f"下一步:推薦 {_CATEGORY_LABEL_ZH.get(nxt, nxt)} 候選"
        return _finish("\n\n".join(header + [listtxt, nxt_line, body]),
                       current_target_category=nxt, last_component_options=opts,
                       pending_reselect_category=None, selection_flow_complete=False)

    # 3b) 看起來想選但解析不出 → 請使用者明確編號(不猜)
    if last_opts and cur and _parse_choice_index(text) is None and _is_none_intent(text) is False \
            and any(k in text for k in ("選", "第", "要")):
        body = _render_options_block(cur, last_opts)
        return _finish("我不確定你要選哪一個,請明確回覆編號(例如「我選第 1 個」)。\n\n" + body,
                       current_target_category=cur, last_component_options=last_opts)

    # 4) 起手 / 推薦下一類
    nxt = get_next_component_category(sc, use_case)
    if nxt is None:
        return _finish(_render_complete_menu(sc, budget), selection_flow_complete=True,
                       current_target_category=None, last_component_options=[])
    res = options_for(nxt)
    opts = res["options"]
    body = _render_options_block(nxt, opts, res.get("warnings"))
    if sc:
        _, listtxt = _render_running_list(sc, budget)
        msg = "\n\n".join([listtxt, f"下一步:推薦 {_CATEGORY_LABEL_ZH.get(nxt, nxt)} 候選", body])
    else:
        intro = (f"以下是預算 {int(budget):,} 元 " if budget else "以下是 ") + \
                f"{_classify_use_case(use_case)} 起手可選的 {_CATEGORY_LABEL_ZH.get(nxt, nxt)} 候選:"
        msg = intro + "\n\n" + body
    return _finish(msg, current_target_category=nxt, last_component_options=opts,
                   selection_flow_complete=False, pending_reselect_category=None)


def is_interactive_selection_request(text: str | None) -> bool:
    """供 router 用的 deterministic 判斷:此 utterance 是否為互動式逐步選件動作。

    為 True 時 router 應**直接導向 ecommerce**(不經 LLM,避免選件中途被誤路由)。
    明確要求完整菜單(full_menu)不算(交給一般 ecommerce/LLM 路徑處理完整菜單)。
    """
    if not text:
        return False
    if is_explicit_full_menu_text(text):
        return False
    # 選件動作(數字 / 第 N 個 / 無 / 確認保存 / 重新選 X)、只給預算的裸句一律導向 ecommerce;
    # fresh session 由引擎 guard 友善提示,不會誤開 gaming 流程。
    if is_selection_like_input(text) or is_budget_only_input(text):
        return True
    return is_interactive_intent_text(text)
