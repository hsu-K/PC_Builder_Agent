"""
平台相容性規則(deterministic,單一真實來源)。

目的:把 CPU / 主機板 / RAM 的平台判定規則集中成「程式碼層級」的事實表與推斷函式,
讓互動式候選推薦(recommend_component_options)與驗證(validate_selected_build)
不必依賴 LLM 自行判斷 socket / memory_generation。

注意:此模組刻意「不」import ecommerce_scraper(避免拉進 bs4 等爬蟲相依)。
ecommerce_scraper.py 內有一份功能相同的入庫期規則(_MB_PLATFORM / _cpu_platform 等);
本模組是推薦/驗證期使用的對應版本,規則內容需與其保持一致。
"""

from __future__ import annotations

import re

# 主機板晶片組 -> (socket, memory_generation)。
# LGA1700 的記憶體世代要看主機板名稱(DDR4 / DDR5 / D4 / D5),因此這裡標 None。
MB_PLATFORM: dict[str, tuple[str, str | None]] = {
    # AMD AM4
    "A520": ("AM4", "DDR4"), "B550": ("AM4", "DDR4"), "X570": ("AM4", "DDR4"),
    # AMD AM5
    "A620": ("AM5", "DDR5"), "B650": ("AM5", "DDR5"), "X670": ("AM5", "DDR5"), "X870": ("AM5", "DDR5"),
    # Intel LGA1700(DDR4 / DDR5 看主機板名稱)
    "H610": ("LGA1700", None), "B660": ("LGA1700", None), "B760": ("LGA1700", None),
    "H770": ("LGA1700", None), "Z690": ("LGA1700", None), "Z790": ("LGA1700", None),
    "W680": ("LGA1700", None),
    # Intel LGA1851
    "B860": ("LGA1851", "DDR5"), "Z890": ("LGA1851", "DDR5"), "W880": ("LGA1851", "DDR5"),
}

PLATFORM_LABEL = {
    "AM4": "AMD AM4", "AM5": "AMD AM5",
    "LGA1700": "Intel LGA1700", "LGA1851": "Intel LGA1851",
}

# socket -> CPU 品牌(用於 prefer_platform=AMD/Intel 與品牌守門)
SOCKET_BRAND = {
    "AM4": "AMD", "AM5": "AMD",
    "LGA1700": "Intel", "LGA1851": "Intel",
}

# socket -> 預設記憶體世代(LGA1700 例外:依主機板名稱,故不放這裡)
SOCKET_DEFAULT_MEM = {
    "AM4": "DDR4", "AM5": "DDR5", "LGA1851": "DDR5",
}

# 不要求結尾 word boundary:晶片組常接字母(H610M / B650E / Z790-A / B760M),
# 仍要能辨識出 H610 / B650 / Z790 等基底晶片組。
_MB_CHIPSET_RE = re.compile(
    r"(?<![A-Za-z0-9])(A520|B550|X570|A620|B650|X670|X870|H610|B660|B760|H770|Z690|Z790|W680|B860|Z890|W880)",
    re.IGNORECASE,
)


def normalize_platform(value: str | None) -> str | None:
    """把使用者輸入的平台字串正規化成 socket / 品牌 token。

    回傳可能是 socket(AM4/AM5/LGA1700/LGA1851)或品牌(AMD/Intel),或 None。
    """
    if not value:
        return None
    t = value.strip().upper().replace(" ", "")
    if t in ("AM4", "AM5", "LGA1700", "LGA1851"):
        return t
    if t in ("AMD", "INTEL"):
        return t.capitalize() if t == "INTEL" else "AMD"
    # 常見別名
    if t in ("1700", "LGA-1700"):
        return "LGA1700"
    if t in ("1851", "LGA-1851"):
        return "LGA1851"
    return None


def mem_from_text(text: str | None) -> str | None:
    """由文字判斷記憶體世代:DDR5 / DDR4(辨識 DDR4/DDR5 與縮寫 D4/D5);判不出回 None。"""
    if not text:
        return None
    t = text.upper()
    if "DDR5" in t or re.search(r"\bD5\b", t):
        return "DDR5"
    if "DDR4" in t or re.search(r"\bD4\b", t):
        return "DDR4"
    if "DDR3" in t or re.search(r"\bD3\b", t):
        return "DDR3"
    return None


def cpu_brand_from_text(text: str | None) -> str | None:
    """由 CPU 文字判斷品牌(Intel / AMD);判不出回 None。"""
    if not text:
        return None
    t = text.upper()
    if "INTEL" in t or "CORE ULTRA" in t or re.search(r"\bI[3579][-\s]?\d{3,5}", t):
        return "Intel"
    if "AMD" in t or "RYZEN" in t or re.search(r"\bR[3579]\b", t):
        return "AMD"
    return None


def cpu_platform_from_text(text: str | None) -> tuple[str | None, str | None, str | None]:
    """由 CPU 文字推斷 (socket, platform_label, memory_generation);推不出回 (None, None, None)。

    - Intel Core Ultra 200 -> LGA1851 / DDR5
    - Intel Core 12/13/14 代(iX-12xxx~14xxx)-> LGA1700 / DDR4_or_DDR5(實際看主機板)
    - AMD Ryzen 首位數 3/4/5 -> AM4 / DDR4;7/8/9 -> AM5 / DDR5
    """
    if not text:
        return None, None, None
    t = text.upper()
    if "CORE ULTRA" in t or re.search(r"\bULTRA\s?\d\s?2\d\d", t):
        return "LGA1851", PLATFORM_LABEL["LGA1851"], "DDR5"
    if re.search(r"\bI[3579][-\s]?1[234]\d{2,3}", t):  # i5-12400 / i5-14600K
        return "LGA1700", PLATFORM_LABEL["LGA1700"], "DDR4_or_DDR5"
    m = re.search(r"(?:RYZEN\s?\d|\bR[3579])\s?([3-9])\d{3}", t)  # Ryzen 5 5600 / R5 7500F
    if m:
        d = m.group(1)
        if d in "345":
            return "AM4", PLATFORM_LABEL["AM4"], "DDR4"
        if d in "789":
            return "AM5", PLATFORM_LABEL["AM5"], "DDR5"
    return None, None, None


def mb_platform_from_text(text: str | None) -> tuple[str | None, str | None, str | None]:
    """由主機板商品名推斷 (socket, platform_label, memory_generation);推不出回 (None, None, None)。"""
    if not text:
        return None, None, None
    m = _MB_CHIPSET_RE.search(text)
    if not m:
        return None, None, None
    chipset = re.sub(r"\s+", "", m.group(0)).upper()
    base = chipset.rstrip("E")[:4]  # B650E -> B650;X670E -> X670
    info = MB_PLATFORM.get(base)
    if not info:
        return None, None, None
    socket, mem = info
    label = PLATFORM_LABEL.get(socket)
    if mem is None:  # LGA1700:依名稱判斷 DDR4 / DDR5,判不出留 DDR4_or_DDR5(不亂猜)
        mem = mem_from_text(text) or "DDR4_or_DDR5"
        if mem == "DDR3":
            mem = "DDR4_or_DDR5"
    return socket, label, mem


__all__ = [
    "MB_PLATFORM",
    "PLATFORM_LABEL",
    "SOCKET_BRAND",
    "SOCKET_DEFAULT_MEM",
    "normalize_platform",
    "mem_from_text",
    "cpu_brand_from_text",
    "cpu_platform_from_text",
    "mb_platform_from_text",
]
