"""
硬體相關工具。

這裡放與組裝知識相關的一般工具。
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def estimate_psu_wattage(
    cpu_tdp_watts: int,
    gpu_tdp_watts: int,
    extra_headroom_watts: int = 150,
) -> str:
    """Estimate a safe power supply wattage for a build."""

    estimated = cpu_tdp_watts + gpu_tdp_watts + extra_headroom_watts
    recommended = ((estimated + 49) // 50) * 50
    return (
        f"估算總瓦數約 {estimated}W，建議電源至少 {recommended}W，"
        f"並保留 {extra_headroom_watts}W 以上餘裕。"
    )


@tool
def recommend_ram_capacity(
    use_case: str,
    multitasking_level: str = "medium",
) -> str:
    """根據用途與多工程度，提供建議記憶體容量與建議區間。"""

    text = f"{use_case} {multitasking_level}".lower()

    base_gb = 16
    if any(k in text for k in ("ai", "剪輯", "render", "渲染", "llm", "training")):
        base_gb = 64
    elif any(k in text for k in ("遊戲", "gaming", "開發", "程式", "design", "設計")):
        base_gb = 32

    if multitasking_level.lower() in ("high", "heavy", "高", "重度"):
        base_gb *= 2
    elif multitasking_level.lower() in ("low", "輕度", "低"):
        base_gb = max(16, base_gb // 2)

    if base_gb <= 16:
        return "建議 16GB（2x8GB）起步，長期建議直接上 32GB（2x16GB）。"
    if base_gb <= 32:
        return "建議 32GB（2x16GB）作為主流甜蜜點，可兼顧遊戲與開發。"
    if base_gb <= 64:
        return "建議 64GB（2x32GB）以應對重度多工、AI 或剪輯工作流。"
    return "建議 96GB~128GB（2x48GB 或 4x32GB），並優先確認主機板 QVL 與穩定性。"


@tool
def recommend_storage_layout(
    use_case: str,
    expected_game_count: int = 0,
    needs_local_archive: bool = False,
) -> str:
    """根據用途與容量需求，提供 SSD/HDD 配置建議。"""

    text = use_case.lower()
    os_drive = "1TB NVMe Gen4 SSD"
    data_drive = ""

    if any(k in text for k in ("剪輯", "影片", "video", "render", "ai", "dataset")):
        os_drive = "2TB NVMe Gen4/Gen5 SSD"
        data_drive = "另加 4TB HDD 或第二顆 2TB SSD 作為專案資料盤"
    elif any(k in text for k in ("遊戲", "gaming")):
        if expected_game_count >= 12:
            os_drive = "2TB NVMe Gen4 SSD"
            data_drive = "可再加 2TB SSD 存大型遊戲庫"
        else:
            os_drive = "1TB~2TB NVMe Gen4 SSD"
    elif any(k in text for k in ("文書", "辦公", "office", "學習")):
        os_drive = "1TB NVMe SSD"

    if needs_local_archive and not data_drive:
        data_drive = "另加 2TB~4TB HDD 作為備份/封存盤"

    if data_drive:
        return f"建議主系統盤：{os_drive}；資料盤：{data_drive}。"
    return f"建議主系統盤：{os_drive}，先單碟配置即可。"


@tool
def recommend_cooling_solution(
    cpu_tdp_watts: int,
    noise_preference: str = "balanced",
) -> str:
    """根據 CPU 功耗與噪音偏好，建議散熱方向。"""

    if cpu_tdp_watts >= 200:
        base = "建議 360mm 一體式水冷，並搭配高風量機殼風道。"
    elif cpu_tdp_watts >= 130:
        base = "建議雙塔風冷或 240/280mm 一體式水冷。"
    else:
        base = "建議高品質單塔/雙塔風冷即可，重點是風道與風扇曲線。"

    pref = noise_preference.lower()
    if pref in ("silent", "quiet", "靜音"):
        extra = "可優先選低轉速風扇與靜壓型風扇，BIOS 設定保守風扇曲線。"
    elif pref in ("performance", "效能", "極致"):
        extra = "可接受較高轉速以換取更低核心溫度，避免長時間降頻。"
    else:
        extra = "建議以平衡曲線運作，待實測溫度後再微調。"

    return f"{base}{extra}"