"""
簡單測試腳本：示範如何直接呼叫 node（以 router_node 為例）

使用方法：
    uv run scripts/test_node.py

此腳本會建立三個範例 request，逐一呼叫 `router_node`，並印出 `route_targets` 與 `route_reason`。
"""

from pc_builder_agent.nodes.router import router_node


def run_demo():
    examples = [
        {"request": "我要一台能跑遊戲的電腦，重視 1440p 60fps，預算 2 萬"},
        {"request": "主要用於文書與程式開發，需求省電、靜音，預算有限"},
        {"request": "可以幫我找一下之前討論的文章或推薦嗎？"},
    ]

    for i, state in enumerate(examples, start=1):
        print(f"--- 範例 {i} 請求: {state['request']}")
        # router_node 會把結果以 dict 回傳（包含 route_targets 與 route_reason）
        result = router_node(state, model_name=None, debug=True)
        print("回傳結果:", result)
        print()


if __name__ == "__main__":
    run_demo()
