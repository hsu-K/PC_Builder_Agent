"""
電子商城真實爬蟲 — 解析層(Phase: CoolPC parser 最小實作)。

本模組此階段「只做解析,不做網路請求、不寫資料庫」。
原價屋(CoolPC)線上估價頁的真實結構(經實際抓取 evaluate.php 驗證):
  - 每個主要零件是一個 <select name="nX">。
  - 「零件類別」寫在該 <select> 前方的『區段標題文字』,例如「處理器 CPU」、「主機板 MB」、
    「顯示卡VGA」;optgroup 的 label 其實是『子品牌/行銷分區』(例如「華碩 ASUS 品牌主機專區」、
    「NVIDIA / AMD 顯示卡周邊配件」),不可拿來當類別判斷(會誤判)。
  - 每個 <option> 文字內含商品名稱與價格(例如 "AMD Ryzen 5 7600..., $6490")。
所以類別判斷以「select 前方標題」為準,逐一解析該 select 內所有 option。

parse_coolpc_html() 把這種結構解析成可直接交給 ecommerce_db.upsert_products() 的
list[dict]。網路抓取(fetch_coolpc_html)與解析(parse_coolpc_html)刻意分離,
方便用離線 HTML 字串反覆測試,降低對網站的請求;DB 寫入(upsert)由 ecommerce_update 負責。

注意:
- 第一版只收 CPU / GPU / Motherboard,其他類別略過。
- CoolPC 估價單通常沒有單品 URL、也沒有原價/特價,故 url="" 、original/discount=None,
  url 為空時 ecommerce_db 會以 source+category+product_name 去重(已內建)。
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup


# ============================================================================
# 網路抓取(單次、低頻、友善)
# ============================================================================

COOLPC_EVALUATE_URL = "https://www.coolpc.com.tw/evaluate.php"


def fetch_coolpc_html(
    url: str = COOLPC_EVALUATE_URL,
    timeout: int = 15,
    user_agent: str = "pc-builder-agent-course-project/0.1",
) -> str:
    """抓取 CoolPC 估價頁 HTML(單次請求)。

    - 使用 requests、誠實 User-Agent、timeout。
    - CoolPC 為 Big5 編碼,以 apparent_encoding 修正中文。
    - HTTP 非 200 / timeout / requests 例外時回傳空字串(不拋例外、不讓上層崩潰)。
    - 只做一次請求,不重試大量請求,不繞過任何登入/驗證/反爬限制。
    """
    import requests

    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=timeout)
    except requests.RequestException:
        return ""

    if resp.status_code != 200:
        return ""

    # 修正中文編碼:CoolPC 多為 Big5,requests 可能誤判
    if resp.apparent_encoding and (
        not resp.encoding or resp.encoding.lower() != resp.apparent_encoding.lower()
    ):
        resp.encoding = resp.apparent_encoding

    return resp.text or ""


# ============================================================================
# 類別對應(只收 CPU / GPU / Motherboard,其餘回 None 代表略過)
# ============================================================================

def _is_excluded_section(label: str | None) -> bool:
    """判斷區段標題是否為「應整段略過」的非零件區。

    - 隨身/記憶卡(n9 隨身碟｜隨身硬碟｜記憶卡):含「硬碟」但非內接,不可進 Storage。
    - 風扇/配件(n16 機殼風扇｜機殼配件):含「機殼」但非機殼本體,不可進 Case。
    """
    if not label:
        return False
    # 散熱膏/散熱墊:只有「沒有散熱器/水冷/塔扇/空冷」的純配件區段才整段排除。
    # CoolPC n10「散熱器｜散熱墊｜散熱膏」因含「散熱器」-> 不整段排除,改 map 成 Cooler 後
    # 由 _is_accessory_product / allowlist 做逐品項(per-product)過濾,保留真正的 CPU 空冷塔散。
    if ("散熱膏" in label or "散熱墊" in label) and not any(
        k in label for k in ("散熱器", "水冷", "塔扇", "空冷", "CPU散熱")
    ):
        return True
    return any(k in label for k in ("隨身", "記憶卡", "風扇", "配件"))


def _map_category(label: str | None) -> str | None:
    """把 CoolPC『區段標題文字』對應到標準類別;不在白名單內回 None(略過)。

    注意:此函式吃的是 <select> 前方的區段標題(如「處理器 CPU」「主機板 MB」「顯示卡VGA」),
    不是 optgroup 的 label(那是子品牌,會誤判)。
    """
    if not label:
        return None
    if _is_excluded_section(label):
        return None
    text = label.upper()

    # 分類(順序重要):
    # Cooler 必須在 CPU 之前 —— 標題「CPU 散熱器」含「CPU」但應歸 Cooler;
    # CPU 區段標題為「處理器 CPU」,不含散熱/水冷詞,故不會被這條誤收。
    # 注意:刻意「不用」裸 "AIO" 判斷,因為 CoolPC n1 標題「品牌小主機、AIO｜VR虛擬」的
    # AIO 指 All-In-One 整機,會把整機誤收進 Cooler;真正的一體式水冷區段含「水冷」即可命中。
    if any(k in label for k in ("CPU散熱", "CPU 散熱", "散熱器", "塔扇", "水冷", "空冷")):
        return "Cooler"
    if "處理器" in label or "CPU" in text:
        return "CPU"
    if "顯示卡" in label or "顯卡" in label or "VGA" in text or "GPU" in text:
        return "GPU"
    if "主機板" in label or "MOTHERBOARD" in text or "MB" in text:
        return "Motherboard"
    if "記憶體" in label or "RAM" in text:
        return "RAM"
    # 用「固態 / 內接硬碟 / SSD / M.2 / HDD」具體詞,刻意不用裸「硬碟」(排除隨身硬碟)
    if "固態" in label or "內接硬碟" in label or "SSD" in text or "M.2" in text or "HDD" in text:
        return "Storage"
    # Case 必須在 PSU 之前:n14「CASE 機殼(+電源)」同時含「機殼」與「電源」,應歸 Case
    if "機殼" in label or "CASE" in text:
        return "Case"
    if "電源" in label or "POWER" in text or "PSU" in text:
        return "PSU"
    return None


def _category_for_select(select: Any) -> str | None:
    """取 <select> 前方最近、可對應到已知類別的『區段標題文字』。

    只看最近幾個文字節點,避免回頭抓到更前面區段的標題(造成跨區誤判);
    對應不到 CPU/GPU/Motherboard 時回 None(該 select 略過)。
    """
    seen = 0
    for s in select.find_all_previous(string=True):
        text = (s or "").strip()
        if not text:
            continue
        seen += 1
        # 若最近的區段標題是「排除區」(隨身/記憶卡/風扇/配件),直接略過此 select,
        # 不可再往前回溯,否則會誤抓到上一區段的標題(如 n9→Storage、n16→PSU)。
        if _is_excluded_section(text):
            return None
        cat = _map_category(text)
        if cat:
            return cat
        if seen >= 8:
            break
    return None


# ============================================================================
# 價格解析
# ============================================================================

# MVP 價格策略:以 "$" 前綴的金額為準(估價單慣例)。
# 若文字含多個 $ 金額,取「第一個」$ 金額作為主要商品價格(CoolPC 單品通常只有一個);
# 若完全沒有 $ 金額,視為無法解析 -> 由呼叫端略過該品項。
_PRICE_RE = re.compile(r"\$\s*([0-9][0-9,]*)")


def _parse_price(text: str) -> int | None:
    """從 option 文字解析主要價格(整數);無 $ 金額時回 None。"""
    price, _, _ = _parse_prices(text)
    return price


def _parse_prices(text: str) -> tuple[int | None, int | None, int | None]:
    """解析 (price, original_price, discount_price)。

    CoolPC 觀察到的價格格式:
    - '↘' 降價(如 "$4990↘$4880"):原價在前、實售價在後
        -> original=第一個, price=discount=最後一個。
    - 含「原價」且無 ↘(如 "...原價$2290！, $1690"):原價在前、實售價在後
        -> original=第一個, price=discount=最後一個。
        (PSU / Case 常見此格式;若直接取第一個金額會誤把原價當售價。)
    - '↗' 漲價(如 "$1290↗$1390"):現價在前、未來價在後
        -> price=第一個, original/discount=None(不視為折扣)。
    - 一般單一價格:price=第一個, original/discount=None。
    - 無任何 $ 金額:回 (None, None, None)。
    """
    if not text:
        return None, None, None
    amounts: list[int] = []
    for raw in _PRICE_RE.findall(text):
        digits = raw.replace(",", "")
        if digits:
            try:
                amounts.append(int(digits))
            except ValueError:
                pass
    if not amounts:
        return None, None, None

    # 降價 ↘ 或「原價在前」格式:實售價是最後一個金額
    if len(amounts) >= 2 and ("↘" in text or "原價" in text):
        return amounts[-1], amounts[0], amounts[-1]

    # 漲價 ↗ 或一般單一價:實售價是第一個金額(不視為折扣)
    return amounts[0], None, None


# ============================================================================
# 品牌解析(board-partner 品牌優先,避免 GPU 文字中的 AMD/Intel 蓋過華碩/微星)
# ============================================================================

# (canonical_brand, 比對關鍵字)— 依序比對,先命中者勝。
_BRAND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ASUS", ("ASUS", "華碩")),
    ("MSI", ("MSI", "微星")),
    ("GIGABYTE", ("GIGABYTE", "技嘉", "AORUS")),
    ("ASRock", ("ASROCK", "華擎")),
    ("PowerColor", ("POWERCOLOR", "撼訊")),
    ("AMD", ("AMD", "RYZEN")),
    ("Intel", ("INTEL", "CORE I")),
)


def _parse_brand(text: str) -> str | None:
    """以關鍵字 heuristic 解析品牌;解析不到回 None。"""
    if not text:
        return None
    upper = text.upper()
    for canonical, keywords in _BRAND_RULES:
        for kw in keywords:
            if kw in upper:
                return canonical
    return None


# ============================================================================
# 型號解析(常見 GPU / CPU / 主機板晶片組 pattern;抽不到回空字串)
# ============================================================================

# 主機板晶片組 pattern:涵蓋 A/B/H/X/Z/W 開頭 + 3 碼數字,並保留可選的 E 後綴
# (B650E / X670E / X870E 不可被截成 B650 / X670 / X870)。同時供 allowlist 與 model 解析共用,
# 確保「能保留就能解析出 model」。
# 前方保留 \b 以避免吃到 "LGA1700" 裡的 "A170";尾端「不」加 \b,
# 因為 mATX 板常見「晶片組緊接 M」(B760M / A620M / H610M),需能抽出 B760 / A620 / H610。
_MB_CHIPSET_RE = re.compile(r"\b[ABHXZW]\d{3}E?", re.IGNORECASE)

# 依序嘗試;每個 GPU pattern 用「可選後綴」一次抓完整型號,避免把 Ti / XT / SUPER 截掉。
# 例:RTX 4060 Ti / RTX 4070 SUPER / RTX 4070 Ti SUPER / RX 7600 XT / RX 9070 XT 都完整保留。
# Intel Arc:Arc B580 / Arc B570(B+3碼)也要完整,不能只剩 ARC。
# 注意:CoolPC 的 CPU 命名常用縮寫 —— Intel 寫 "i5-14400F"(無 Core)、
# AMD 寫 "R5 5500GT" / "R7 7800X3D"(無 Ryzen),另有 Threadripper "TR PRO 9955WX"、"Xeon W5-2455X"。
# 故除了完整寫法,也補上縮寫 pattern。GPU pattern 放最前面以免被其他 pattern 搶先。
_MODEL_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"RTX\s?\d{4}\s?(?:Ti\s?SUPER|SUPER|Ti)?", re.IGNORECASE),
    re.compile(r"RX\s?\d{4}\s?(?:XT)?", re.IGNORECASE),
    re.compile(r"ARC\s?(?:PRO\s?)?[AB]?\d{2,4}", re.IGNORECASE),  # Arc B580 / Arc A770 / Arc Pro B70
    # 後綴一律限定 ASCII 英數(避免 \w* 把中文如「代理盒裝」一起吃進型號)。
    re.compile(r"Core\s?Ultra\s?\d\s?\d{3}[A-Za-z0-9]*", re.IGNORECASE),  # Core Ultra 5 245K
    re.compile(r"Ryzen\s?\d\s?\d{4}[A-Za-z0-9]*", re.IGNORECASE),         # Ryzen 7 7800X3D
    re.compile(r"(?:Ryzen\s?)?TR\s?(?:PRO\s?)?\d{4}[A-Za-z0-9]*", re.IGNORECASE),  # Threadripper
    re.compile(r"Core\s?i\d[\s-]?\d{3,5}[A-Za-z0-9]*", re.IGNORECASE),    # Core i5-14600K
    re.compile(r"\bi[3579][\s-]?\d{3,5}[A-Za-z0-9]*", re.IGNORECASE),     # 縮寫 Intel:i5-14400F
    re.compile(r"\bR[3579]\s?\d{3,4}[A-Za-z0-9]*", re.IGNORECASE),        # 縮寫 AMD:R5 5500GT
    re.compile(r"Xeon\s?W?\d?-?\d{3,4}[A-Za-z0-9]*", re.IGNORECASE),      # Xeon W5-2455X
    _MB_CHIPSET_RE,                                              # A620 / B650E / X670E / Z790 / W680
)


def _parse_model(text: str, product_name: str) -> str:
    """以 pattern heuristic 抽型號;抽不到時退回商品名稱前段,再不行回空字串。"""
    if not text:
        return ""
    for pattern in _MODEL_PATTERNS:
        m = pattern.search(text)
        if m:
            # 正規化內部多餘空白(例如 "RTX  4060" -> "RTX 4060")
            return re.sub(r"\s+", " ", m.group(0).strip())
    # 退而求其次:用商品名稱前段(避免崩潰),仍抽不到就空字串
    head = (product_name or "").strip().split(",")[0].strip()
    return head[:40]


# ============================================================================
# 新類別 model / specs 解析(RAM / Storage / PSU / Case)
# ============================================================================

# 主機板晶片組 -> (socket, memory_generation);LGA1700 的記憶體世代視名稱而定 -> None
_MB_PLATFORM: dict[str, tuple[str, str | None]] = {
    # AMD AM4
    "A520": ("AM4", "DDR4"), "B550": ("AM4", "DDR4"), "X570": ("AM4", "DDR4"),
    # AMD AM5
    "A620": ("AM5", "DDR5"), "B650": ("AM5", "DDR5"), "X670": ("AM5", "DDR5"), "X870": ("AM5", "DDR5"),
    # Intel LGA1700(DDR4/DDR5 看主機板名稱)
    "H610": ("LGA1700", None), "B660": ("LGA1700", None), "B760": ("LGA1700", None),
    "H770": ("LGA1700", None), "Z690": ("LGA1700", None), "Z790": ("LGA1700", None),
    "W680": ("LGA1700", None),
    # Intel LGA1851
    "B860": ("LGA1851", "DDR5"), "Z890": ("LGA1851", "DDR5"), "W880": ("LGA1851", "DDR5"),
}
_PLATFORM_LABEL = {"AM4": "AMD AM4", "AM5": "AMD AM5",
                   "LGA1700": "Intel LGA1700", "LGA1851": "Intel LGA1851"}


def _cpu_platform(text: str) -> tuple[str | None, str | None, str | None]:
    """由 CPU 文字推斷 (socket, platform, memory_generation);推不出回 (None, None, None)。

    規則(以結構化資料取代 LLM 猜測):
    - Intel Core Ultra 200 -> LGA1851 / DDR5
    - Intel Core 12/13/14 代(iX-12xxx~14xxx)-> LGA1700 / DDR4_or_DDR5(實際看主機板)
    - AMD Ryzen/R# 型號首位數 3/4/5 -> AM4 / DDR4;7/8/9 -> AM5 / DDR5
    """
    t = text.upper()
    if "CORE ULTRA" in t or re.search(r"\bULTRA\s?\d\s?2\d\d", t):
        return "LGA1851", _PLATFORM_LABEL["LGA1851"], "DDR5"
    if re.search(r"\bI[3579][-\s]?1[234]\d{2,3}", t):  # i5-12400 / i5-14600K
        return "LGA1700", _PLATFORM_LABEL["LGA1700"], "DDR4_or_DDR5"
    m = re.search(r"(?:RYZEN\s?\d|\bR[3579])\s?([3-9])\d{3}", t)  # Ryzen 5 5600 / R5 7500F
    if m:
        d = m.group(1)
        if d in "345":
            return "AM4", _PLATFORM_LABEL["AM4"], "DDR4"
        if d in "789":
            return "AM5", _PLATFORM_LABEL["AM5"], "DDR5"
    return None, None, None


def _mb_platform(text: str, chipset: str | None) -> tuple[str | None, str | None, str | None]:
    """由主機板晶片組推斷 (socket, platform, memory_generation)。"""
    if not chipset:
        return None, None, None
    base = chipset.upper().rstrip("E")[:4]  # B650E -> B650;X670E -> X670
    info = _MB_PLATFORM.get(base)
    if not info:
        return None, None, None
    socket, mem = info
    if mem is None:  # LGA1700:依名稱判斷 DDR4 / DDR5,判不出留 DDR4_or_DDR5(不亂猜)
        # 同時辨識完整 "DDR4/DDR5" 與廠商縮寫 "D4/D5"(例:H610I-PLUS D4-CSM -> DDR4)
        if re.search(r"DDR5", text, re.IGNORECASE) or re.search(r"\bD5\b", text, re.IGNORECASE):
            mem = "DDR5"
        elif re.search(r"DDR4", text, re.IGNORECASE) or re.search(r"\bD4\b", text, re.IGNORECASE):
            mem = "DDR4"
        else:
            mem = "DDR4_or_DDR5"
    return socket, _PLATFORM_LABEL[socket], mem


def _cpu_model_specs(text: str, product_name: str) -> tuple[str, dict]:
    """CPU:沿用 _parse_model 取型號,並加上 socket / platform / memory_generation。"""
    model = _parse_model(text, product_name)
    specs: dict = {"source_text": text}
    socket, platform, mem = _cpu_platform(text)
    if socket:
        specs["socket"] = socket
    if platform:
        specs["platform"] = platform
    if mem:
        specs["memory_generation"] = mem
    return model, specs


def _mb_model_specs(text: str, product_name: str) -> tuple[str, dict]:
    """Motherboard:型號(晶片組)+ socket / platform / memory_generation / chipset / form_factor。"""
    model = _parse_model(text, product_name)
    specs: dict = {"source_text": text}
    m = _MB_CHIPSET_RE.search(text)
    chipset = re.sub(r"\s+", "", m.group(0)).upper() if m else None
    if chipset:
        specs["chipset"] = chipset
    socket, platform, mem = _mb_platform(text, chipset)
    if socket:
        specs["socket"] = socket
    if platform:
        specs["platform"] = platform
    if mem:
        specs["memory_generation"] = mem
    ff = _CASE_SIZE_RE.search(text)  # ATX / M-ATX / E-ATX / ITX … 同一組尺寸 pattern
    if ff:
        specs["form_factor"] = re.sub(r"\s+", "", ff.group(0).upper())
    return model, specs


def _ram_model_specs(text: str, product_name: str) -> tuple[str, dict]:
    """RAM:解析世代/容量/速度/套條。model 例:'DDR5 32GB 6000'。"""
    specs: dict = {"source_text": text}
    gen = None
    # 支援完整「DDR5」與品牌縮寫「D5-6000」(十銓/芝奇常用);亦保留 DDR3 等舊世代
    m = re.search(r"DDR([345])", text, re.IGNORECASE) or re.search(r"\bD([45])[-\s]?\d{3,4}", text)
    if m:
        gen = "DDR" + m.group(1)
        specs["memory_generation"] = gen
    cap = None
    m = re.search(r"(\d{1,3})\s?GB", text, re.IGNORECASE)
    if m:
        cap = f"{m.group(1)}GB"
        specs["capacity"] = cap
    speed = None
    m = re.search(r"(?:DDR|D)[345][-\s]?(\d{4})", text, re.IGNORECASE)
    if m:
        speed = m.group(1)
        specs["speed"] = int(speed)
    kit = bool(re.search(r"\d+\s?[Gg][x*]\s?\d|\d\s?[x*]\s?\d{1,3}\s?GB|雙通道|套條", text)) or "x2" in text.lower()
    if kit:
        specs["kit"] = True
    parts = [p for p in (gen, cap, speed) if p]
    model = " ".join(parts) if parts else _name_head(product_name)
    return model, specs


def _storage_model_specs(text: str, product_name: str) -> tuple[str, dict]:
    """Storage:解析容量/介面/型態/系列。model 例:'990 PRO 1TB' 或 '1TB NVMe'。"""
    specs: dict = {"source_text": text}
    cap = None
    m = re.search(r"(\d+)\s?(TB|GB|G)\b", text, re.IGNORECASE)
    if m:
        unit = m.group(2).upper()
        unit = "GB" if unit == "G" else unit
        cap = f"{m.group(1)}{unit}"
        specs["capacity"] = cap
    iface = None
    for pat, val in ((r"NVMe", "NVMe"), (r"PCIe\s?5", "PCIe 5.0"), (r"PCIe\s?4", "PCIe 4.0"),
                     (r"PCIe\s?3", "PCIe 3.0"), (r"SATA", "SATA")):
        if re.search(pat, text, re.IGNORECASE):
            iface = val
            specs["interface"] = val
            break
    form = None
    for pat, val in ((r"M\.2", "M.2"), (r"2\.5\s?吋", "2.5\""), (r"3\.5\s?吋", "3.5\"")):
        if re.search(pat, text, re.IGNORECASE):
            form = val
            specs["form_factor"] = val
            break
    # 常見系列型號(盡量抓,抓不到不強求)
    series = None
    m = re.search(r"\b(SN\d{3,4}\w*|MP\d{2,3}\w*|KC\d{3,4}|MX\d{3,4}|BX\d{3}|SU\d{3,4}|S\d{3}|A400|"
                  r"9[789]0\s?PRO|9[789]0\s?EVO\w*|P\d\s?Plus|P\d{3}|T\d{3}\w*)\b", text, re.IGNORECASE)
    if m:
        series = re.sub(r"\s+", " ", m.group(1).strip())
        specs["series"] = series
    if series and cap:
        model = f"{series} {cap}"
    elif cap:
        model = f"{cap}{(' ' + iface) if iface else ''}"
    else:
        model = _name_head(product_name)
    return model, specs


def _psu_model_specs(text: str, product_name: str) -> tuple[str, dict]:
    """PSU:解析瓦數/認證/ATX 版本/PCIe5。model 例:'750W Gold'。"""
    specs: dict = {"source_text": text}
    watt = None
    m = re.search(r"(\d{3,4})\s?W\b", text, re.IGNORECASE)
    if m:
        watt = f"{m.group(1)}W"
        specs["wattage"] = int(m.group(1))
    cert = None
    cert_map = (("Titanium", (r"Titanium", "鈦金")), ("Platinum", (r"Platinum", "白金")),
                ("Gold", (r"Gold", "金牌")), ("Bronze", (r"Bronze", "銅牌")))
    for canonical, kws in cert_map:
        if any(re.search(k, text, re.IGNORECASE) for k in kws):
            cert = canonical
            specs["certification"] = canonical
            break
    m = re.search(r"ATX\s?3\.[01]", text, re.IGNORECASE)
    if m:
        specs["atx_version"] = re.sub(r"\s+", "", m.group(0).upper())
    if re.search(r"PCIe?\s?5", text, re.IGNORECASE):
        specs["pcie5"] = True
    parts = [p for p in (watt, cert) if p]
    model = " ".join(parts) if parts else _name_head(product_name)
    return model, specs


def _case_model_specs(text: str, product_name: str) -> tuple[str, dict]:
    """Case:解析尺寸/特徵/顏色。型號不規則 -> model 取名稱前段。"""
    specs: dict = {"source_text": text}
    m = _CASE_SIZE_RE.search(text)
    if m:
        specs["case_size"] = re.sub(r"\s+", "", m.group(0).upper())
    feats = [f for f in ("Mesh", "Airflow", "RGB", "ARGB") if re.search(f, text, re.IGNORECASE)]
    if "玻璃" in text:
        feats.append("玻璃透側")
    if feats:
        specs["features"] = feats
    for c in ("黑", "白", "灰", "粉", "銀", "藍"):
        if c in product_name:
            specs["color"] = c
            break
    # 型號:取名稱前段(切到 規格分隔符 之前)
    model = _name_head(product_name, cut_markers=("顯卡長", "CPU高", "U高", "/"))
    return model, specs


def _cooler_model_specs(text: str, product_name: str) -> tuple[str, dict]:
    """Cooler:解析 cooler_type / radiator_size / fan_size / height_mm / socket_support。"""
    specs: dict = {"source_text": text}
    # 類型:水冷/AIO/一體式 -> aio;塔扇/塔散/空冷/氣冷/下吹/風冷/散熱器 -> air;否則 unknown
    if re.search(r"水冷|AIO|一體式", text, re.IGNORECASE):
        ctype = "aio"
    elif re.search(r"塔扇|塔散|空冷|氣冷|下吹|風冷|散熱器", text):
        ctype = "air"
    else:
        ctype = "unknown"
    specs["cooler_type"] = ctype
    # 水冷排尺寸(240/280/360/420);AIO 才有意義
    rad = None
    m = re.search(r"\b(420|360|280|240)\b", text)
    if m and ctype == "aio":
        rad = f"{m.group(1)}mm"
        specs["radiator_size"] = rad
    # 風扇尺寸:14cm/140mm -> 140mm;12cm/120mm -> 120mm
    fan = None
    if re.search(r"14\s?cm|140\s?mm", text, re.IGNORECASE):
        fan = "140mm"
    elif re.search(r"12\s?cm|120\s?mm", text, re.IGNORECASE):
        fan = "120mm"
    if fan:
        specs["fan_size"] = fan
    # 高度:「高:15.5cm」之類 -> 轉成 mm
    m = re.search(r"高\s*[:：]?\s*(\d+(?:\.\d+)?)\s*cm", text)
    if m:
        try:
            specs["height_mm"] = int(round(float(m.group(1)) * 10))
        except ValueError:
            pass
    # 支援腳位
    sockets = re.findall(r"AM5|AM4|LGA\s?1700|LGA\s?1851|LGA\s?1200|LGA\s?115\d", text, re.IGNORECASE)
    if sockets:
        specs["socket_support"] = sorted({re.sub(r"\s+", "", s.upper()) for s in sockets})
    # model
    if ctype == "aio":
        model = f"AIO {rad}" if rad else "AIO 水冷"
    elif ctype == "air":
        model = f"Air Cooler {fan}" if fan else (_name_head(product_name) or "Air Cooler")
    else:
        model = _name_head(product_name)
    return model, specs


def _name_head(product_name: str, cut_markers: tuple[str, ...] = ("/",), limit: int = 30) -> str:
    """取商品名稱前段作為 model fallback;在第一個分隔標記前切斷。"""
    name = product_name or ""
    cut = len(name)
    for mk in cut_markers:
        idx = name.find(mk)
        if idx != -1:
            cut = min(cut, idx)
    return re.sub(r"\s+", " ", name[:cut].strip())[:limit].strip()


def _extract_model_specs(text: str, category: str, product_name: str) -> tuple[str, dict]:
    """依類別產生 (model, specs)。CPU/GPU/Motherboard 沿用既有 _parse_model。"""
    if category == "RAM":
        return _ram_model_specs(text, product_name)
    if category == "Storage":
        return _storage_model_specs(text, product_name)
    if category == "PSU":
        return _psu_model_specs(text, product_name)
    if category == "Case":
        return _case_model_specs(text, product_name)
    if category == "Cooler":
        return _cooler_model_specs(text, product_name)
    if category == "CPU":
        return _cpu_model_specs(text, product_name)
    if category == "Motherboard":
        return _mb_model_specs(text, product_name)
    return _parse_model(text, product_name), {"source_text": text}


# ============================================================================
# 庫存狀態
# ============================================================================

def _parse_stock_status(text: str) -> str:
    """依文字判斷庫存:缺貨/完售/售完 -> out_of_stock;預購 -> preorder;其餘 in_stock。"""
    if not text:
        return "in_stock"
    if any(k in text for k in ("缺貨", "完售", "售完")):
        return "out_of_stock"
    if "預購" in text:
        return "preorder"
    return "in_stock"


# ============================================================================
# 配件過濾(黑名單排除 + GPU/MB 型號 allowlist 優先保留)
# ============================================================================

# 通用配件關鍵字(各類別都排除)。英文以小寫比對,中文直接子字串比對。
# 刻意使用較明確的詞(如「支撐架」「轉接架」),避免用「支」等過短字誤殺
# 規格描述(例如「支援 DDR5」「支援 PCIe 5.0」)。
_GENERIC_ACCESSORY = (
    "延長線", "延長排線", "轉接線", "轉接架", "轉接卡", "擴充卡",
    "外接盒", "螺絲", "配件", "周邊", "riser", "bracket", "holder",
)
_GPU_ACCESSORY = ("支撐架", "支架", "顯卡支架", "vga holder")
_MB_ACCESSORY = ("io擋板", "擋板")  # 主機板區的擋板/IO 擋板等配件;轉接卡/擴充卡已在通用清單

# RAM:刻意「不」黑名單裸「散熱片/馬甲」(真記憶體常含散熱片/RGB 描述),
# 只排除明確的「記憶體散熱片/散熱器」這類獨立配件;主要靠 allowlist(需含 DDR/容量)。
_RAM_ACCESSORY = ("記憶體散熱", "ram散熱", "ddr散熱片", "燈條")
# Storage:外接盒/硬碟架/讀卡機/線材/散熱片等;轉接卡/外接盒/螺絲已在通用清單
_STORAGE_ACCESSORY = ("硬碟盒", "硬碟架", "硬碟座", "外接", "讀卡機", "線材", "散熱片", "散熱器")
# PSU:各種線材/測試器;延長線/轉接線已在通用清單。注意不可放裸「12VHPWR」(真 PSU 規格會提)
_PSU_ACCESSORY = ("電源線", "模組線", "線材", "測試器", "轉接頭", "cable")
# Case:側板/濾網/支架等;螺絲/配件/轉接架已在通用清單。注意不放「風扇」(真機殼常「附風扇」)
_CASE_ACCESSORY = ("側板", "濾網", "支架", "支撐架")
# Cooler:散熱膏/墊、扣具、控制器、SSD/M.2/硬碟/筆電散熱、線材等;不放裸「風扇」(AIO 含一體式風扇)
_COOLER_ACCESSORY = (
    "散熱膏", "散熱墊", "導熱膏", "導熱墊", "扣具", "固定架", "轉接座",
    "控制器", "ssd散熱", "m.2散熱", "硬碟散熱", "筆電散熱", "風扇控制",
)

# allowlist:GPU 型號 pattern,用來「優先保留」真正的卡。
# 主機板晶片組 pattern 使用下方 model 區段定義的 _MB_CHIPSET_RE(含可選 E 後綴),
# 確保 allowlist 與 _parse_model() 一致(能保留就能解析出 model)。
_GPU_MODEL_RE = re.compile(r"(RTX|GTX|RX|ARC)\s?\d{3,4}", re.IGNORECASE)
# 新類別 allowlist pattern(「優先保留」真正商品,排除無規格的純配件)
_RAM_ALLOW_RE = re.compile(r"DDR[45]|\d{1,3}\s?GB", re.IGNORECASE)
_STORAGE_ALLOW_RE = re.compile(r"\d+\s?(?:TB|GB|G)\b", re.IGNORECASE)
_PSU_ALLOW_RE = re.compile(r"\d{3,4}\s?W\b", re.IGNORECASE)
_CASE_SIZE_RE = re.compile(r"E-?ATX|Micro-?ATX|M-?ATX|Mini-?ITX|ITX|ATX", re.IGNORECASE)
# Cooler:需含 水冷/AIO/散熱器/塔扇/CPU散熱 或 水冷排尺寸(240/280/360…)或明確 socket 才保留
_COOLER_ALLOW_RE = re.compile(
    r"水冷|AIO|一體式|散熱器|塔扇|塔散|空冷|氣冷|下吹|"
    r"\b(?:120|140|240|280|360|420)\s?mm\b|"
    r"AM4|AM5|LGA\s?1700|LGA\s?1851|LGA\s?1200",
    re.IGNORECASE,
)


def _has_keyword(name: str, keywords: tuple[str, ...]) -> bool:
    """子字串比對,一律大小寫不敏感(name 與 keyword 都以小寫比較)。

    所有 keyword 皆以小寫定義;name.lower() 會把 ascii 轉小寫、CJK 不變,
    因此純中文(散熱膏)、純英文(holder)、中英混合(ssd散熱、m.2散熱)都能正確比對,
    並避免「SSD散熱器」因大小寫(kw=ssd散熱)而漏抓。
    """
    low = name.lower()
    return any(kw in low for kw in keywords)


def _is_accessory_product(product_name: str, category: str) -> bool:
    """判斷是否為配件(應排除)。黑名單命中即視為配件。"""
    if not product_name:
        return False
    if _has_keyword(product_name, _GENERIC_ACCESSORY):
        return True
    cat_acc = {
        "GPU": _GPU_ACCESSORY,
        "Motherboard": _MB_ACCESSORY,
        "RAM": _RAM_ACCESSORY,
        "Storage": _STORAGE_ACCESSORY,
        "PSU": _PSU_ACCESSORY,
        "Case": _CASE_ACCESSORY,
        "Cooler": _COOLER_ACCESSORY,
    }.get(category)
    if cat_acc and _has_keyword(product_name, cat_acc):
        return True
    return False


def _passes_category_allowlist(text: str, category: str) -> bool:
    """GPU/MB/RAM/Storage/PSU/Case 需含對應規格 pattern 才保留;CPU 不強制(避免過度過濾)。

    這層用「優先保留真正商品」的方式排除無規格的純配件:
    - GPU:型號 RTX/GTX/RX/ARC;Motherboard:晶片組;RAM:DDR/容量;
      Storage:容量;PSU:瓦數;Case:尺寸 ATX/ITX。
    Intel Arc 系列(如 Arc B570)以 'ARC' 關鍵字一併放行。
    """
    if category == "GPU":
        return bool(_GPU_MODEL_RE.search(text)) or ("ARC" in text.upper())
    if category == "Motherboard":
        return bool(_MB_CHIPSET_RE.search(text))
    if category == "RAM":
        return bool(_RAM_ALLOW_RE.search(text))
    if category == "Storage":
        return bool(_STORAGE_ALLOW_RE.search(text))
    if category == "PSU":
        return bool(_PSU_ALLOW_RE.search(text))
    if category == "Case":
        return bool(_CASE_SIZE_RE.search(text))
    if category == "Cooler":
        return bool(_COOLER_ALLOW_RE.search(text))
    return True  # CPU 等不強制 allowlist


# ============================================================================
# 優惠訊號解析(Phase Promo-A)
#
# 只解析「CoolPC option text / 商品名稱中明確可見、可結構化的優惠訊息」。
# 嚴格區分(對應 ecommerce_db 的 promotions 設計):
#   - actual_discount : 單品特價(↘ / 原價$X…$Y),非 bundle。
#   - bundle_discount : 「任搭主機板現省N / 搭板專案 -N / 搭主機板折N」這類
#                       明確金額的搭購折扣(required_category 通常為 Motherboard)。
#   - combo           : 「組合優惠 / 組合價」把多項零件包成一個價格的真正套裝。
#   - add_on          : 「加購優惠 / 搭購優惠」買 A 才能加價購 B。
#   - gift            : 「買就送 / 即贈 / 再送 / 贈品」純贈品(無折扣金額)。
#   - threshold_gift  : 「滿$N 即贈/折」滿額贈。
#   - text_promo      : 「登錄送 / 憑發票登錄」需登錄、活動頁才生效的優惠 -> 低信心。
#
# 刻意「不」判定為優惠(避免把規格 / 推薦語誤判成 promo):
#   - 「含風扇 / 含電源 / 附風扇」-> CPU/機殼規格,不是贈品。
#   - 「建議搭配 / 搭配32G」-> 推薦語或筆電規格,不是搭購折扣。
#   - 「支援 / 相容」-> 規格描述。
#   - below_avg(低於同類均價)根本不是文字訊號,不會出現在此 parser。
# ============================================================================

# 角色建議:此商品在該 promotion 中扮演的角色(供 ecommerce_db.promotion_products 用)。
_PROMO_ROLE_BY_TYPE = {
    "actual_discount": "target",
    "bundle_discount": "trigger",
    "combo": "member",
    "add_on": "trigger",
    "gift": "trigger",
    "threshold_gift": "trigger",
    "text_promo": "unknown",
}


def _promo_amounts(text: str) -> list[int]:
    """抓出文字中所有 $ 金額(整數),供 actual_discount / combo 價格判斷。"""
    amounts: list[int] = []
    for raw in _PRICE_RE.findall(text):
        digits = raw.replace(",", "")
        if digits:
            try:
                amounts.append(int(digits))
            except ValueError:
                pass
    return amounts


def _board_bundle_amount(text: str) -> int | None:
    """抓「搭主機板」類結構化折扣金額(搭板專案 -N / 現省N / 搭主機板折N)。抓不到回 None。"""
    for pat in (
        r"搭板專案\s*[-－]\s*(\d{2,5})",
        r"任搭主機板.*?現省\s*(\d{2,5})",
        r"現省\s*(\d{2,5})",
        r"搭(?:主機板|板)\D{0,6}?[折省]\s*\$?\s*(\d{2,5})",
    ):
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return None


def _parse_promotion_signals(text: str) -> list[dict]:
    """從商品文字解析 0..N 個結構化優惠訊號。

    每個訊號 dict 至少含:
        promo_type / title / promo_text / discount_amount / discount_percent /
        required_category / required_keyword / confidence / role
    (另可含 original_price / promo_price / min_amount)。

    設計原則:
    - 寧可漏判,不要誤判:只在「明確優惠語句」才產生訊號;規格/推薦語一律不產生。
    - 無法算出結構化折扣金額時,discount_amount 留 None,並以 text_promo / 較低 confidence 表示。
    - 同一 promo_type 在同一段文字最多產生一筆(避免重複灌)。
    """
    signals: list[dict] = []
    if not text or not text.strip():
        return signals
    t = text.strip()

    def add(sig: dict) -> None:
        sig.setdefault("discount_amount", None)
        sig.setdefault("discount_percent", None)
        sig.setdefault("original_price", None)
        sig.setdefault("promo_price", None)
        sig.setdefault("required_category", None)
        sig.setdefault("required_keyword", None)
        sig.setdefault("min_amount", None)
        sig["promo_text"] = t
        sig.setdefault("role", _PROMO_ROLE_BY_TYPE.get(sig["promo_type"], "unknown"))
        signals.append(sig)

    # ---- 1. 單品特價 actual_discount(↘ 或 原價$X…$Y,後者較低)----
    if "↘" in t or "原價" in t:
        amts = _promo_amounts(t)
        if len(amts) >= 2 and amts[-1] < amts[0] and amts[0] > 0:
            add({
                "promo_type": "actual_discount",
                "title": "單品特價",
                "discount_amount": amts[0] - amts[-1],
                "discount_percent": round((amts[0] - amts[-1]) / amts[0] * 100, 1),
                "original_price": amts[0],
                "promo_price": amts[-1],
                "confidence": "high",
            })

    # ---- 2. bundle_discount(任搭主機板現省N / 搭板專案 -N / 搭主機板折N)----
    is_board_bundle = any(k in t for k in ("任搭主機板", "搭板專案", "搭主機板", "搭板"))
    amount = _board_bundle_amount(t)
    if amount is not None and (is_board_bundle or "任搭" in t):
        add({
            "promo_type": "bundle_discount",
            "title": f"搭主機板現省{amount}" if is_board_bundle else f"搭購現省{amount}",
            "discount_amount": amount,
            "required_category": "Motherboard" if is_board_bundle else None,
            "required_keyword": "主機板" if is_board_bundle else None,
            "confidence": "high",
        })

    # ---- 3. combo(組合優惠 / 組合價:把多項零件包成一個價格)----
    if "組合優惠" in t or "組合價" in t or ("組合" in t and "+" in t):
        prices = _promo_amounts(t)
        add({
            "promo_type": "combo",
            "title": "商城組合優惠",
            "promo_price": prices[-1] if prices else None,
            "confidence": "high",
        })

    # ---- 3b. 現折$N(明確折扣金額,常伴隨組合)----
    mf = re.search(r"現折\s*\$?\s*(\d{2,5})", t)
    if mf and not any(s["promo_type"] == "bundle_discount" for s in signals):
        add({
            "promo_type": "bundle_discount",
            "title": f"現折{mf.group(1)}",
            "discount_amount": int(mf.group(1)),
            "confidence": "medium",
        })

    # ---- 4. 登錄 / 憑發票(活動頁、需登錄才生效)-> text_promo 低信心 ----
    #        刻意排在 gift 之前並「互斥」:登錄類優惠不確定性高,不升級成 gift。
    is_registration = "登錄" in t or "憑發票" in t
    if is_registration:
        add({
            "promo_type": "text_promo",
            "title": "登錄/活動優惠(需登錄)",
            "confidence": "low",
        })

    # ---- 5. add_on(加購優惠 / 搭購優惠:買 A 加價購 B)----
    if "加購" in t:
        add({
            "promo_type": "add_on",
            "title": "加購優惠",
            "confidence": "medium",
        })
    elif "搭購" in t:  # 套裝搭購優惠 / 筆電搭購優惠
        add({
            "promo_type": "add_on",
            "title": "搭購優惠",
            "confidence": "medium",
            "role": "member",
        })

    # ---- 6. threshold_gift(滿$N 即贈/折/送)—— 先於 gift,命中即抑制 gift 避免重複 ----
    mth = re.search(r"滿\s*\$?\s*(\d{2,6})", t)
    is_threshold = bool(mth and re.search(r"贈|送|折|享", t))
    if is_threshold:
        add({
            "promo_type": "threshold_gift",
            "title": f"滿{mth.group(1)}元優惠",
            "min_amount": int(mth.group(1)),
            "confidence": "medium",
        })

    # ---- 7. gift(買就送 / 即贈 / 再送 / 贈品)----
    #        含風扇 / 含電源 / 建議搭配 等規格詞不在此規則,不會被誤判成贈品。
    #        「不適用…贈品促銷」這類否定性聲明(disclaimer)不是優惠,排除之。
    is_disclaimer = "不適用" in t
    if not is_registration and not is_threshold and not is_disclaimer and re.search(
        r"買就送|就送|即贈|加贈|再送|贈品|購買.{0,12}?送", t
    ):
        add({
            "promo_type": "gift",
            "title": "買就送 / 贈品",
            "confidence": "medium",
        })

    return signals


def parse_promotion_signals(text: str) -> list[dict]:
    """公開版:解析單段商品文字的優惠訊號(供外部 / 測試呼叫)。"""
    return _parse_promotion_signals(text)


# ============================================================================
# 商品名稱清洗
# ============================================================================

def _clean_product_name(text: str) -> str:
    """取價格($)之前的文字作為商品名稱,去除尾端逗號/空白。"""
    name = text
    dollar = text.find("$")
    if dollar != -1:
        name = text[:dollar]
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(",，、 ").strip()
    # CoolPC 常以「...原價$X！, $Y」標降價,切在第一個 $ 後會殘留「原價」「獨家原價」「！」,去除之
    name = re.sub(r"(獨家原價|原價|！|!)+$", "", name).strip()
    return name.rstrip(",，、 ").strip()


# ============================================================================
# 主解析函式
# ============================================================================

def parse_coolpc_html(
    html: str,
    *,
    max_per_category: int | None = None,
) -> list[dict]:
    """解析 CoolPC 估價頁 HTML,輸出標準商品 list[dict]。

    Args:
        html: CoolPC 估價頁的 HTML 字串(本階段由測試/呼叫端提供,不在此抓網路)。
        max_per_category: 每個類別最多取幾筆(None 表示不限制)。

    Returns:
        list[dict]:每筆對應 ecommerce_db.upsert_products() 可接受的欄位。
        只包含 CPU / GPU / Motherboard;無法解析價格的品項會被略過。
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    products: list[dict] = []
    counts: dict[str, int] = {}  # 每類別已收幾筆(供 max_per_category 用)

    for select in soup.find_all("select"):
        category = _category_for_select(select)
        if category is None:
            continue  # 此 select 不屬於 CPU/GPU/Motherboard,略過

        for option in select.find_all("option"):
            if max_per_category is not None and counts.get(category, 0) >= max_per_category:
                break

            # 略過 CoolPC 每個 select 開頭的統計標頭 option(class="bf"、value="0"、
            # 文字以「共有商品」開頭)。CoolPC 的 HTML 未閉合,這個 option 會把整段內容
            # 巢狀包進來,若不略過會產生一筆把所有商品串在一起的垃圾資料。
            classes = option.get("class") or []
            if option.get("value") == "0" or "bf" in classes:
                continue

            text = option.get_text(strip=True)
            if not text or text.startswith("共有商品"):
                continue

            price, original_price, discount_price = _parse_prices(text)
            if price is None:
                continue  # 無法解析價格(如裝飾性標頭/促銷文字)-> 略過

            product_name = _clean_product_name(text)
            if not product_name:
                continue

            # 配件過濾:黑名單命中 -> 排除;GPU/MB 還需通過型號/晶片組 allowlist。
            if _is_accessory_product(product_name, category):
                continue
            if not _passes_category_allowlist(text, category):
                continue

            try:
                model, specs = _extract_model_specs(text, category, product_name)
                product = {
                    "source": "原價屋",
                    "category": category,
                    "product_name": product_name,
                    "brand": _parse_brand(text),
                    "model": model,
                    "price": price,
                    "original_price": original_price,
                    "discount_price": discount_price,
                    "url": "",
                    "specs": specs,
                    "stock_status": _parse_stock_status(text),
                    "bundle_id": "",
                }
            except Exception:
                # 單筆解析失敗不影響其他品項
                continue

            products.append(product)
            counts[category] = counts.get(category, 0) + 1

    return products


def parse_coolpc_promotions(html: str) -> list[dict]:
    """掃描『所有』option 文字(不限 8 類零件、不要求可解析價格)抽出明確優惠訊號。

    與 parse_coolpc_html 不同:後者只收可入庫的 8 類零件,故會略過整機 / 筆電 /
    準系統 / 週邊上的「組合優惠 / 加購 / 買就送」。本函式刻意掃全頁 option,
    讓「頁面中明確可見的優惠」能被完整記錄(供人工檢查與後續關聯)。

    每筆回傳 = _parse_promotion_signals() 的訊號 dict,額外附:
        product_name(清洗後名稱)、category(該 select 對應類別,可能為 None)。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for select in soup.find_all("select"):
        category = _category_for_select(select)
        for option in select.find_all("option"):
            classes = option.get("class") or []
            if option.get("value") == "0" or "bf" in classes:
                continue
            text = option.get_text(strip=True)
            if not text or text.startswith("共有商品"):
                continue
            signals = _parse_promotion_signals(text)
            if not signals:
                continue
            name = _clean_product_name(text)
            for sig in signals:
                sig = dict(sig)
                sig["product_name"] = name
                sig["category"] = category
                out.append(sig)
    return out
