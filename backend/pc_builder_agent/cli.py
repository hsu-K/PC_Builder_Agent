"""
CLI 模組：處理命令列介面和程式進入點

這個模組負責：
1. 解析命令列引數（需求、session ID、模型選擇等）
2. 支援兩種模式：
   - 單次查詢模式：輸入需求後得到建議並退出
   - 聊天模式：持續對話，保持上下文和記憶
"""

from __future__ import annotations

import argparse
import os

from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

# 在模組載入時讀取 .env 檔案
# 這確保 os.getenv() 能取得 OPENAI_API_KEY 和 OPENAI_MODEL 等環境變數
load_dotenv()

from pc_builder_agent.graph import build_graph
from pc_builder_agent.chatbot import run_chat, prepare_session_state


def parse_args() -> argparse.Namespace:
    """
    解析命令列引數
    
    預設行為：進入聊天模式（自動讀取 preference.json、執行 PC_Board Scraper）
    
    支援的引數：
    - --session-id: 用於保持同一個會話的記憶和偏好 ID
    - --model: 指定使用的模型名稱 (OpenAI 用 OPENAI_MODEL，Gemini 用 GEMINI_MODEL)
    
    返回：
        argparse.Namespace: 包含解析後的所有引數
    
    範例：
        uv run main.py                           # 聊天模式（讀取 preference.json、執行 scraper）
        uv run main.py --session-id user1        # 指定會話 ID 的聊天模式
    """
    parser = argparse.ArgumentParser(
        description="LangGraph multi-agent PC builder demo",
        epilog="範例: uv run main.py   (進入聊天模式)\n"
    )
    parser.add_argument(
        "--session-id",
        default="default",
        help="用於保持同一個會話的記憶和偏好設定的 ID",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL") or os.getenv("GEMINI_MODEL") or "gpt-4.1-mini",
        help="使用的模型名稱 (OpenAI: OPENAI_MODEL / Gemini: GEMINI_MODEL)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="啟用除錯輸出",
    )
    return parser.parse_args()


def main() -> int:
    """
    主程式進入點
    
    執行流程：
    1. 讀取 preference.json 資料
    2. 呼叫 PC_Board Scraper Node 取得相關資訊
    3. 進入聊天模式，讓使用者提問
    
    Returns:
        int: 程式結束碼 (0=成功, 非0=失敗)
    """
    # 解析命令列引數
    args = parse_args()
    
    # 預設行為：進入聊天模式
    # ===== 預設聊天模式 =====
    # 1. 讀取 preference.json
    # 2. 呼叫 pc_board_scraper_node
    # 3. 進入聊天迴圈
    run_chat(session_id=args.session_id, model_name=args.model, debug=args.debug)
    return 0