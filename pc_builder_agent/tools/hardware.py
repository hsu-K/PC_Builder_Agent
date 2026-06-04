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
