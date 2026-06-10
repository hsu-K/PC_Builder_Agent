"""
CLI 模組:命令列進入點。

提供兩個入口:
- `main()`：console script `pc-builder-agent`(沿用 run_chat,含 preference.json / PC_Board)。
- `run_interactive_cli()`：**正式互動式選件 CLI**,直接

      uv run python -m pc_builder_agent.cli

  啟動後輸入需求即可逐步選零件,不需自行建立 /tmp 測試腳本。
"""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

# 在模組載入時讀取 .env(讓 os.getenv() 取得 OPENAI_API_KEY / OPENAI_MODEL)
load_dotenv()

from pc_builder_agent.chatbot import run_chat



# ============================================================================
# console script: pc-builder-agent(沿用 run_chat)
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LangGraph multi-agent PC builder demo",
        epilog="範例: uv run python -m pc_builder_agent.cli  (互動式選件 CLI)\n",
    )
    parser.add_argument("--session-id", default="default",
                        help="用於保持同一個會話的記憶和偏好設定的 ID")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                        help="使用的 OpenAI 模型名稱 (預設: gpt-4.1-mini)")
    parser.add_argument("--debug", action="store_true", help="啟用除錯輸出")
    return parser.parse_args()


def main() -> int:
    """console script `pc-builder-agent` 進入點(沿用 run_chat:含 preference.json / PC_Board)。"""
    args = parse_args()
    run_chat(session_id=args.session_id, model_name=args.model, debug=args.debug)
    return 0

