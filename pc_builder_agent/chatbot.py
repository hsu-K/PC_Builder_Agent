"""
聊天機器人模組：實現與 PC Builder Agent 的持續互動

這個模組提供聊天介面，讓使用者可以：
1. 提出 PC 組裝需求
2. 持續與 agent 對話，提出追加問題或修改需求
3. 保持記憶與偏好設定跨越多輪對話
"""

from langchain_core.messages import HumanMessage
from pc_builder_agent.graph import build_graph


def run_chat(session_id: str = "default", model_name: str | None = None) -> None:
    """
    執行聊天機器人主迴圈
    
    Args:
        session_id: 用於保持同一個對話會話的 ID，相同 ID 會共享記憶和偏好
        model_name: 使用的 OpenAI 模型名稱
    
    流程說明：
    1. 建構 LangGraph agent，包含 planner、cpu_specialist、gpu_specialist 和 integrator
    2. 進入持續對話迴圈，直到使用者輸入 'exit' 或 'quit'
    3. 每輪對話會執行完整的 agent 分析流程，並保留之前的訊息歷史
    4. Agent 會根據記憶自動調整建議
    """
    
    # 建構 LangGraph 應用，包含所有 agent 節點和執行流程
    app = build_graph(model_name=model_name)
    
    # 初始化訊息歷史 - 用於追蹤整個對話的訊息序列
    # 這樣 agent 可以看到完整的對話上下文
    messages_history = []
    
    print("=" * 60)
    print("PC Builder Agent - 聊天模式")
    print("=" * 60)
    print(f"Session ID: {session_id}")
    print("\n說明:")
    print("  • 輸入你的 PC 組裝需求")
    print("  • 根據需要進行後續對話和修改")
    print("  • 輸入 'exit' 或 'quit' 結束")
    print("=" * 60)
    print()
    
    # 持續對話迴圈 - 直到使用者決定退出
    while True:
        # 取得使用者輸入
        user_input = input("你: ").strip()
        
        # 檢查退出指令
        if user_input.lower() in ("exit", "quit"):
            print("\nAgent: 再見！感謝使用 PC Builder Agent。")
            break
        
        # 忽略空輸入
        if not user_input:
            continue
        
        # 將使用者輸入添加到訊息歷史
        messages_history.append(HumanMessage(content=user_input))
        
        print("\n[正在分析...]")
        
        try:
            # 呼叫 LangGraph 應用執行完整的 agent 分析流程
            # 
            # 輸入狀態說明：
            #   - profile_id: 用於查詢和保存使用者偏好 (跨越多輪對話)
            #   - request: 最新的使用者需求 (用於 agent 分析)
            #   - messages: 完整的對話歷史 (讓 agent 了解上下文)
            #
            # 執行流程：
            #   1. planner agent: 理解需求，查詢/保存偏好
            #   2. cpu_specialist & gpu_specialist: 並行分析 CPU/GPU 建議
            #   3. integrator: 整合所有建議成最終回應
            result = app.invoke(
                {
                    "profile_id": session_id,  # 維持同一個使用者會話的記憶
                    "request": user_input,      # 目前輪次的使用者需求
                    "messages": messages_history,  # 完整對話歷史供 agent 參考
                },
                config={"configurable": {"thread_id": session_id}},  # 線程 ID 用於檢查點管理
            )
            
            # 從結果中取出最終的整合答案
            final_answer = result.get("final_answer", "")
            
            # 顯示 agent 的回應
            print(f"\nAgent: {final_answer}")
            print()
            
            # 將 agent 的回應也加入訊息歷史，讓下一輪對話能參考
            # 這樣可以保持完整的對話上下文
            from langchain_core.messages import AIMessage
            messages_history.append(AIMessage(content=final_answer))
            
        except KeyboardInterrupt:
            # 允許使用者用 Ctrl+C 中斷
            print("\n\n[已中斷]")
            break
        except Exception as e:
            # 錯誤處理 - 顯示錯誤訊息但不中斷對話
            print(f"\n發生錯誤: {e}")
            print("請重新嘗試。\n")
