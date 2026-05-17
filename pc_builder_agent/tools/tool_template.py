"""
工具模板
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def tool_template(
    attr: int,
) -> str:
    
    return (
        f"這是一個工具模板，接收一個整數參數 attr，目前值為 {attr}。"
    )