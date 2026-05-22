"""
Tools 模組 - 所有工具的統一導出點。

記憶相關工具仍然由 `memory.py` 提供；
像爬蟲這種非記憶工具應該放在這裡集中管理。

導出工具流程：
先import工具 -> 加入ALL_TOOLS列表 -> 定義TOOL_LOOKUP字典 -> 在__all__中導出工具
"""

from pc_builder_agent.memory import MEMORY_TOOLS, PROFILE_TOOLS
from pc_builder_agent.memory import (
    recall_user_preferences,
    save_user_preference,
    recall_pc_board_articles,
)
from pc_builder_agent.tools.hardware import estimate_psu_wattage
from pc_builder_agent.tools.scraper import web_scrape, pc_board_scraper

# 所有工具統一在這裡匯總，Node 只需要查這份表
ALL_TOOLS = [*MEMORY_TOOLS, estimate_psu_wattage, web_scrape, pc_board_scraper]
TOOL_LOOKUP = {tool.name: tool for tool in ALL_TOOLS}

__all__ = [
    "ALL_TOOLS",
    "TOOL_LOOKUP",
    "PROFILE_TOOLS",
    "recall_user_preferences",
    "save_user_preference",
    "recall_pc_board_articles",
    "estimate_psu_wattage",
    "web_scrape",
    "pc_board_scraper",
]
