from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool
from langgraph.store.memory import InMemoryStore

PROFILE_NAMESPACE = ("pc_builder_agent", "profiles")
PROFILE_KEY = "preferences"
PROFILE_STORE = InMemoryStore()


def _profile_namespace(profile_id: str) -> tuple[str, ...]:
    return PROFILE_NAMESPACE + (profile_id,)


def load_profile(profile_id: str) -> dict[str, Any]:
    item = PROFILE_STORE.get(_profile_namespace(profile_id), PROFILE_KEY)
    if item is None:
        return {"profile_id": profile_id, "preferences": {}}
    return item.value


def format_profile_summary(profile_id: str) -> str:
    profile = load_profile(profile_id)
    preferences = profile.get("preferences", {})

    if not preferences:
        return "目前沒有已儲存的偏好。"

    return json.dumps(preferences, ensure_ascii=False, indent=2)


@tool
def recall_user_preferences(profile_id: str) -> str:
    """Read the saved build preferences for this profile."""

    return format_profile_summary(profile_id)


@tool
def save_user_preference(profile_id: str, key: str, value: str) -> str:
    """Save a single preference for later conversations."""

    profile = load_profile(profile_id)
    preferences = dict(profile.get("preferences", {}))
    preferences[key] = value
    PROFILE_STORE.put(
        _profile_namespace(profile_id),
        PROFILE_KEY,
        {"profile_id": profile_id, "preferences": preferences},
    )
    return f"已儲存偏好：{key} = {value}"


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


MEMORY_TOOLS = [recall_user_preferences, save_user_preference, estimate_psu_wattage]