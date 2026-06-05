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
import uuid

from dotenv import load_dotenv

# 在模組載入時讀取 .env(讓 os.getenv() 取得 OPENAI_API_KEY / OPENAI_MODEL)
load_dotenv()

from pc_builder_agent.graph import build_graph
from pc_builder_agent.chatbot import run_chat
from pc_builder_agent.tools.ecommerce_db import DEFAULT_DB_PATH


# ============================================================================
# 正式互動式選件 CLI(python -m pc_builder_agent.cli)
# ============================================================================

_BANNER = (
    "=" * 60 + "\n"
    "PC Builder 互動式選件\n"
    + "=" * 60 + "\n"
    "輸入需求開始,例如:\n"
    "  我預算 30000,要組遊戲機,但我想自己挑零件,請從 CPU 開始。\n"
    "  我預算 20000,要組中低階文書機,請從 CPU 開始。\n"
    "\n"
    "指令:\n"
    "  reset   重置目前選件流程(換新 session)\n"
    "  status  顯示目前 thread_id 與已選零件\n"
    "  exit    離開(或 quit / q)\n"
    + "=" * 60
)


def _new_thread_id() -> str:
    return "cli-" + uuid.uuid4().hex[:8]


def _show_status(thread_id: str, last_result: dict | None) -> None:
    print(f"\n[狀態] thread_id = {thread_id}")
    sc = (last_result or {}).get("selected_components") or {}
    if not sc:
        print("[狀態] 目前尚未選擇任何零件。")
        return
    total = 0
    print("[狀態] 目前已選零件:")
    for cat, item in sc.items():
        price = int(item.get("price") or 0)
        total += price
        print(f"  - {cat}:{item.get('product_name')},{price:,} 元")
    print(f"[狀態] 目前總額:{total:,} 元")
    budget = (last_result or {}).get("selected_budget")
    if budget:
        print(f"[狀態] 預算:{int(budget):,} 元 / 剩餘:{int(budget) - total:,} 元")


def run_interactive_cli(model_name: str | None = None, db_path: str | None = None) -> int:
    """啟動正式互動式選件 CLI。"""
    if not os.getenv("OPENAI_API_KEY"):
        print("未設定 OPENAI_API_KEY。請在專案根目錄的 .env 設定 OPENAI_API_KEY 後再啟動。")
        return 1

    db = db_path or DEFAULT_DB_PATH
    if not os.path.exists(db):
        print(f"提醒:找不到本地商品資料庫 {db}(尚未建立)。")
        print("請先在專案根目錄執行以下指令建立本地 DB,再開始選件:")
        print(f"  uv run python -m pc_builder_agent.tools.ecommerce_update --write --db-path {db}")
        print("(沒有本地 DB 時無法查到真實商品;以下對話仍可進行,但會提示先建立 DB。)\n")

    app = build_graph(model_name=model_name)
    thread_id = _new_thread_id()
    messages: list = []
    last_result: dict | None = None

    print(_BANNER)
    # 延遲匯入訊息型別
    from langchain_core.messages import HumanMessage, AIMessage

    while True:
        try:
            user = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再見!")
            break

        if not user:
            continue
        low = user.lower()
        if low in ("exit", "quit", "q"):
            print("再見!")
            break
        if low == "reset":
            thread_id = _new_thread_id()
            messages = []
            last_result = None
            print(f"[已重置] 新 session,thread_id = {thread_id}。請重新輸入需求開始。")
            continue
        if low == "status":
            _show_status(thread_id, last_result)
            continue

        messages.append(HumanMessage(content=user))
        try:
            result = app.invoke(
                {"profile_id": thread_id, "preferences": {}, "request": user, "messages": messages},
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception as exc:  # 不讓單次錯誤中斷整個 CLI
            print(f"[發生錯誤] {exc}")
            print("請重新輸入,或輸入 exit 離開。")
            continue

        last_result = result
        answer = (result.get("final_answer") or result.get("pc_board_response")
                  or result.get("ecommerce_advice") or "(無回應)")
        messages.append(AIMessage(content=answer))
        targets = result.get("route_targets")
        if targets:
            print(f"\n[route: {', '.join(targets)}]")
        print(f"\nAgent:\n{answer}")

    return 0


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


if __name__ == "__main__":
    # `uv run python -m pc_builder_agent.cli` → 互動式選件 CLI
    raise SystemExit(run_interactive_cli(model_name=os.getenv("OPENAI_MODEL")))
