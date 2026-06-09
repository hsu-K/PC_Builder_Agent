"""
聊天機器人模組：實現與 PC Builder Agent 的持續互動

完整執行流程：
1. 讀取 preference.json 資料存入 State
2. 執行 PC_Board Scraper Node 根據偏好爬取文章
3. 進入聊天模式，用戶可詢問爬取的文章內容
4. 每輪對話時傳入完整 State，包含偏好和文章資訊
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import HumanMessage, AIMessage, message_to_dict, messages_from_dict
from pc_builder_agent.graph import build_graph
from pc_builder_agent.nodes import pc_board_scraper_node
from pc_builder_agent.memory import PROFILE_STORE, _profile_namespace, PROFILE_KEY


# ============================================================================
# Session 持久化 - 將 state 存到 data/sessions/{session_id}.json
# ============================================================================

SESSION_DIR = Path(__file__).parent / "data" / "sessions"


def _ensure_session_dir() -> None:
    """確保 data/sessions/ 資料夾存在。"""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(session_id: str) -> Path:
    """回傳 session 檔案的完整路徑。"""
    return SESSION_DIR / f"{session_id}.json"


def save_session(session_id: str, state: dict, messages: list) -> None:
    """將當前的 session state 持久化到 data/sessions/{session_id}.json。

    包含偏好設定、文章結果、已選零件、訊息歷史等，讓下次同 session_id 啟動時能接續對話。
    """
    _ensure_session_dir()
    data = {
        "preferences": state.get("preferences", {}),
        "pc_board_results": state.get("pc_board_results", []),
        "pc_board_response": state.get("pc_board_response", ""),
        "selected_components": state.get("selected_components"),
        "selected_budget": state.get("selected_budget"),
        "selected_use_case": state.get("selected_use_case"),
        "current_target_category": state.get("current_target_category"),
        "selection_flow_complete": state.get("selection_flow_complete"),
        "last_component_options": state.get("last_component_options"),
        "pending_reselect_category": state.get("pending_reselect_category"),
        "messages": [message_to_dict(m) for m in messages],
    }
    # 移除 None 值讓 JSON 更乾淨
    data = {k: v for k, v in data.items() if v is not None}
    with open(_session_path(session_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_session(session_id: str) -> dict | None:
    """從 data/sessions/{session_id}.json 載入先前儲存的 session state。

    Returns:
        dict | None: 包含 preferences / messages / pc_board_results 等欄位；
                      若檔案不存在或格式錯誤則回傳 None。
    """
    path = _session_path(session_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 反序列化訊息歷史（dict → BaseMessage 物件）
        if "messages" in data:
            data["messages"] = messages_from_dict(data["messages"])
        return data
    except Exception as e:
        print(f"\n⚠️  無法載入 session 檔案 ({e})，將重新開始新的對話")
        return None


def load_preferences() -> dict[str, str]:
    """
    讀取 preference.json 檔案
    
    Returns:
        dict: 包含預設偏好設定的字典，若檔案不存在則返回空字典
    """
    preferences_path = Path(__file__).parent / "preference.json"
    
    if preferences_path.exists():
        try:
            with open(preferences_path, "r", encoding="utf-8") as f:
                preferences = json.load(f)
                print("\n【已載入預設偏好設定】")
                print(json.dumps(preferences, ensure_ascii=False, indent=2))
                return preferences
        except (json.JSONDecodeError, IOError) as e:
            print(f"\n警告：無法讀取 preference.json - {e}")
            return {}
    else:
        print("\n提示：尚未找到 preference.json，將使用空白偏好設定")
        return {}


def prepare_session_state(
    session_id: str,
    model_name: str | None = None,
    debug: bool = False,
) -> dict:
    """讀取偏好並完成 PC_Board Scraper 前置初始化（爬取模式）。"""

    preferences = load_preferences()

    if preferences:
        PROFILE_STORE.put(
            _profile_namespace(session_id),
            PROFILE_KEY,
            {"profile_id": session_id, "preferences": preferences},
        )
        print("✓ 已將偏好設定存入記憶系統")

    print("\n【執行 PC_Board Scraper Node - 爬取模式】")
    state = {
        "profile_id": session_id,
        "preferences": preferences,
        "request": "",
        "messages": [],
        "pc_board_results": [],
    }

    # 以爬取模式執行 pc_board_scraper_node，根據偏好爬取文章並存本地
    scraper_result = pc_board_scraper_node(
        state,
        model_name=model_name,
        mode="fetch",
        debug=debug,
    )
    state.update(scraper_result)

    # pc_board_query_attempted 用於標記是否已經嘗試過查詢文章，初始為 False
    # state["pc_board_query_attempted"] = False

    # 將爬取的文章結果存入記憶系統，目前不確定是否要採用
    # PROFILE_STORE.put(
    #     _profile_namespace(session_id),
    #     PROFILE_KEY,
    #     {
    #         "profile_id": session_id,
    #         "preferences": state.get("preferences", {}),
    #         "pc_board_results": state.get("pc_board_results", []),
    #     },
    # )

    if preferences:
        print("✓ 已將偏好與 PC_Board 文章存入記憶系統")

    if state.get("pc_board_results"):
        print("\n【PC_Board 文章已載入到 State】")
        print(f"✓ 成功載入 {len(state['pc_board_results'])} 篇文章，供後續對話查詢")
        for idx, article in enumerate(state["pc_board_results"][:len(state['pc_board_results'])], 1):
            print(f"  {idx}. {article.get('title', 'N/A')}")

    return state


def run_chat(
    session_id: str = "default",
    model_name: str | None = None,
    debug: bool = False,
) -> None:
    """
    執行聊天機器人主迴圈
    
    完整執行流程：
    1. 讀取 preference.json 資料
    2. 將偏好存入 State 和 PROFILE_STORE
    3. 呼叫 pc_board_scraper_node 爬取相關文章，結果也存入 State
    4. 進入聊天迴圈，用戶可詢問相關信息
    5. 每輪對話時都傳入完整的 State（包含偏好和文章資訊）給 Agent
    
    Args:
        session_id: 用於保持同一個對話會話的 ID，相同 ID 會共享記憶和偏好
        model_name: 使用的 OpenAI 模型名稱
    """
    
    print("=" * 60)
    print("PC Builder Agent - 初始化中...")
    print("=" * 60)

    # ===== 步驟 1：嘗試載入已儲存的 session =====
    saved_session = load_session(session_id)
    if saved_session is not None:
        print(f"✓ 找到先前儲存的 session「{session_id}」，還原對話狀態")
        state = {
            "preferences": saved_session.get("preferences", {}),
            "pc_board_results": saved_session.get("pc_board_results", []),
            "pc_board_response": saved_session.get("pc_board_response", ""),
            "selected_components": saved_session.get("selected_components"),
            "selected_budget": saved_session.get("selected_budget"),
            "selected_use_case": saved_session.get("selected_use_case"),
            "current_target_category": saved_session.get("current_target_category"),
            "selection_flow_complete": saved_session.get("selection_flow_complete"),
            "last_component_options": saved_session.get("last_component_options"),
            "pending_reselect_category": saved_session.get("pending_reselect_category"),
        }
        # 還原訊息歷史（已由 messages_from_dict 反序列化為 BaseMessage 物件）
        messages_history = list(saved_session.get("messages", []))

        if state.get("pc_board_results"):
            print(f"✓ 載入 {len(state['pc_board_results'])} 篇先前取得的 PC_Board 文章")
        if messages_history:
            print(f"✓ 載入 {len(messages_history)} 筆對話歷史")
    else:
        # ===== 無已儲存 session：載入偏好設定與爬取文章 =====
        state = prepare_session_state(session_id=session_id, model_name=model_name, debug=debug)
        messages_history = []

    # ===== 步驟 2：建構 LangGraph 應用 =====
    app = build_graph(model_name=model_name, debug=debug)
    
    # ===== 步驟 3：進入聊天迴圈 =====
    print("\n" + "=" * 60)
    print("PC Builder Agent - 聊天模式")
    print("=" * 60)
    print(f"Session ID: {session_id}")
    print("\n說明:")
    print("  • 輸入你的 PC 組裝需求")
    print("  • 可詢問關於已載入文章的內容（如：'告訴我文章中有哪些配置'）")
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
            # 每回合重置路由控制欄位，避免沿用上一輪 request 的 route queue / 進度。
            # 這些欄位是 graph checkpoint 的一部分；若不清掉，同一個 thread_id 會繼承舊路由。
            state["pc_board_response"] = ""
            state["route_targets"] = []
            state["route_reason"] = ""
            state["execution_order"] = []
            state["pending_route_targets"] = []
            state["completed_route_targets"] = []
            state["routing_started"] = False

            # 呼叫 LangGraph 應用執行完整的 agent 分析流程
            # 傳入完整的 State，包含：
            #   - profile_id: 使用者 ID
            #   - preferences: 從 preference.json 讀取的偏好
            #   - pc_board_results: 已爬取的 PC_Board 文章列表
            #   - request: 目前輪次的使用者需求
            #   - messages: 完整對話歷史
            #
            # 工作流程會自動根據使用者需求決定：
            # 1. 呼叫 planner 理解需求
            # 2. 呼叫 router 判斷是否查詢文章或建議配置
            # 3. 若查詢文章：呼叫 pc_board_scraper（查詢模式）
            #    若建議配置：並行呼叫 cpu_specialist 和 gpu_specialist，最後由 integrator 整合
            result = app.invoke(
                {
                    "profile_id": session_id,  # 使用者會話 ID
                    "preferences": state["preferences"],  # 偏好設定
                    "pc_board_response": state.get("pc_board_response", ""),
                    "route_targets": state.get("route_targets", []),
                    "route_reason": state.get("route_reason", ""),
                    "execution_order": state.get("execution_order", []),
                    "pending_route_targets": state.get("pending_route_targets", []),
                    "completed_route_targets": state.get("completed_route_targets", []),
                    "routing_started": state.get("routing_started", False),
                    "request": user_input,  # 目前輪次的使用者需求
                    "messages": messages_history,  # 完整對話歷史
                },
                config={"configurable": {"thread_id": session_id}},
            )

            # 更新本地 state，保留本輪的文章查詢結果供下一輪參考
            # state["pc_board_results"] = result.get("pc_board_results", state.get("pc_board_results", []))
            # state["pc_board_query_attempted"] = bool(result.get("pc_board_query_attempted", False))

            
            # 從結果中取出回應
            # 優先使用整合後的 final_answer，查詢失敗時再退回 pc_board_response
            response = result.get("final_answer") or result.get("pc_board_response") or ""
            
            if not response:
                response = "無法生成回應，請重新嘗試。"
            
            # 顯示 agent 的回應
            print(f"\nAgent: {response}")
            print()
            
            # 將 agent 的回應也加入訊息歷史
            messages_history.append(AIMessage(content=response))

            # 將本次回合的 state 持久化，下次同 session_id 啟動時可接續對話
            save_session(session_id, state, messages_history)
            
        except KeyboardInterrupt:
            # 允許使用者用 Ctrl+C 中斷
            print("\n\n[已中斷]")
            break
        except Exception as e:
            # 錯誤處理 - 顯示錯誤訊息但不中斷對話
            print(f"\n發生錯誤: {e}")
            print("請重新嘗試。\n")
