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
from pc_builder_agent.chatbot import run_chat


def parse_args() -> argparse.Namespace:
    """
    解析命令列引數
    
    支援的引數：
    - request: 使用者的 PC 組裝需求 (選填，聊天模式時會被忽略)
    - --session-id: 用於保持同一個會話的記憶和偏好 ID
    - --model: 指定 OpenAI 模型 (預設從 OPENAI_MODEL 環境變數讀取)
    - --chat: 啟用聊天模式 (持續對話)
    
    Returns:
        argparse.Namespace: 包含解析後的所有引數
    """
    parser = argparse.ArgumentParser(
        description="LangGraph multi-agent PC builder demo",
        epilog="範例: python main.py --chat --session-id demo"
    )
    parser.add_argument(
        "request",
        nargs="?",
        default=None,
        help="PC 組裝需求 (單次查詢模式使用，聊天模式會被忽略)",
    )
    parser.add_argument(
        "--session-id",
        default="default",
        help="用於保持同一個會話的記憶和偏好設定的 ID",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        help="使用的 OpenAI 模型名稱 (預設: gpt-4.1-mini)",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="啟用聊天模式，允許持續對話而不是單次查詢",
    )
    return parser.parse_args()


def main() -> int:
    """
    主程式進入點
    
    執行流程：
    1. 解析命令列引數
    2. 根據 --chat 旗標決定執行模式：
       - 聊天模式 (--chat): 呼叫 run_chat() 進入持續對話迴圈
       - 單次模式: 執行一次完整的 agent 分析並顯示結果
    
    Returns:
        int: 程式結束碼 (0=成功, 非0=失敗)
    """
    # 解析命令列引數
    args = parse_args()
    
    # 根據模式進行不同的處理
    if args.chat:
        # ===== 聊天模式 =====
        # 進入持續對話迴圈，使用者可以多次提出問題
        run_chat(session_id=args.session_id, model_name=args.model)
        return 0
    
    else:
        # ===== 單次查詢模式 =====
        # 如果沒有提供需求，使用預設值
        if not args.request:
            args.request = "我想組一台適合文書與輕度遊戲的電腦"
        
        # 建構 LangGraph 應用
        # build_graph() 會建立完整的 agent 工作流程，包含：
        #   1. planner: 理解需求、查詢/保存偏好
        #   2. cpu_specialist: CPU 和記憶體建議
        #   3. gpu_specialist: GPU 和顯示裝置建議
        #   4. integrator: 整合所有建議
        app = build_graph(model_name=args.model)
        
        # 執行 agent 工作流程
        # 輸入狀態說明：
        #   - profile_id: 用於查詢使用者偏好 (跨越多個 session)
        #   - request: 使用者提供的 PC 組裝需求
        #   - messages: 對話歷史 (初次查詢只有使用者訊息)
        # 
        # config 說明：
        #   - thread_id: 用於檢查點管理，保存對話歷史供後續查詢使用
        result = app.invoke(
            {
                "profile_id": args.session_id,  # 用於記憶管理
                "request": args.request,         # 使用者的組裝需求
                "messages": [HumanMessage(content=args.request)],  # 初始訊息歷史
            },
            config={"configurable": {"thread_id": args.session_id}},
        )
        
        # 顯示詳細的分析結果
        # 執行流程會經過所有 agent，每個 agent 都會產生自己的分析
        print("\n" + "=" * 60)
        print("PC Builder Agent - 分析結果")
        print("=" * 60)
        
        print("\n【使用者需求】")
        print(result["request"])
        
        print("\n【Planner 分析】(理解需求、檢查偏好)")
        print(result["plan"])
        
        print("\n【CPU 專家建議】(CPU、記憶體、主機板)")
        print(result["cpu_advice"])
        
        print("\n【GPU 專家建議】(顯卡、螢幕、散熱)")
        print(result["gpu_advice"])
        
        print("\n【最終建議】(整合所有專家意見)")
        print(result["final_answer"])
        print("\n" + "=" * 60)
        
        return 0