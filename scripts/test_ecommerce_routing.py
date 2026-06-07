#!/usr/bin/env python
"""
最小 ecommerce 路由測試腳本。

用途：
- 驗證 planner/router 是否會把「先查文章，再走 specialist，最後走 ecommerce」
    排成正確 queue。
- 驗證完整 graph invoke 會依序經過 pc_board_scraper -> gpu_specialist -> ecommerce -> integrator。

執行方式：
        uv run python scripts/test_ecommerce_routing.py
"""

import json

from pc_builder_agent.graph import build_graph
from pc_builder_agent.nodes.router import _route_targets_for_request


def test_article_then_ecommerce_queue() -> None:
    """測試「第一篇文章的 GPU 價格」是否會保留完整執行順序。"""

    state = {
        "request": "請幫我查第一篇文章的 GPU 目前價格，然後給我可買的建議",
        "plan": (
            '{"task_type":"compare_articles","need_pc_board_query":true,'
            '"article_query":"第一篇文章的GPU價格",'
            '"specialist_targets":["gpu_specialist","ecommerce"],'
            '"execution_order":["pc_board_scraper","gpu_specialist","ecommerce"],'
            '"summary":"先查文章再看顯卡價格",'
            '"reason":"需要先讀文章比對 GPU 價格"}'
        ),
        "pc_board_response": "",
    }

    route_targets, route_reason = _route_targets_for_request(state)

    print("route_targets:", route_targets)
    print("route_reason:", route_reason)

    expected = ["pc_board_scraper", "gpu_specialist", "ecommerce"]
    assert route_targets == expected, f"expected {expected}, got {route_targets}"

    print("✓ queue is correct: pc_board_scraper -> gpu_specialist -> ecommerce")


def test_continue_after_scraper() -> None:
    """測試 scraper 跑完後，router 是否會繼續往下派送 pending queue。"""

    state = {
        "request": "請幫我查第一篇文章的 GPU 目前價格，然後給我可買的建議",
        "plan": (
            '{"task_type":"compare_articles","need_pc_board_query":true,'
            '"article_query":"第一篇文章的GPU價格",'
            '"specialist_targets":["gpu_specialist","ecommerce"],'
            '"execution_order":["pc_board_scraper","gpu_specialist","ecommerce"],'
            '"summary":"先查文章再看顯卡價格",'
            '"reason":"需要先讀文章比對 GPU 價格"}'
        ),
        "pc_board_response": "mock response",
        "route_targets": ["pc_board_scraper", "gpu_specialist", "ecommerce"],
        "route_reason": "使用者明確要求 PTT/電蝦/文章資料，先查詢 PC_Board 文章",
        "completed_route_targets": ["pc_board_scraper"],
        "routing_started": True,
    }

    route_targets, route_reason = _route_targets_for_request(state)

    print("route_targets after scraper:", route_targets)
    print("route_reason after scraper:", route_reason)

    expected = ["pc_board_scraper", "gpu_specialist", "ecommerce"]
    assert route_targets == expected, f"expected {expected}, got {route_targets}"

    print("✓ continuation state is correct: router keeps the full route list after scraper")


def test_full_graph_integration() -> None:
    """測試完整 graph 是否會照順序跑到 integrator。"""

    from pc_builder_agent import graph as graph_module

    call_log: list[str] = []

    original_planner_node = graph_module.planner_node
    original_pc_board_scraper_node = graph_module.pc_board_scraper_node
    original_gpu_specialist_node = graph_module.gpu_specialist_node
    original_ecommerce_node = graph_module.ecommerce_node
    original_integrator_node = graph_module.integrator_node

    def planner_stub(state, *, model_name=None, debug=False):
        call_log.append("planner")
        plan = {
            "task_type": "compare_articles",
            "need_pc_board_query": True,
            "article_query": "第一篇文章的GPU價格",
            "specialist_targets": ["gpu_specialist", "ecommerce"],
            "execution_order": ["pc_board_scraper", "gpu_specialist", "ecommerce"],
            "summary": "先查文章再看顯卡價格",
            "reason": "需要先讀文章比對 GPU 價格",
        }
        return {"messages": [], "plan": json.dumps(plan, ensure_ascii=False)}

    def pc_board_scraper_stub(state, *, model_name=None, mode="query", debug=False):
        call_log.append("pc_board_scraper")
        return {
            "pc_board_response": "mock pc board response",
            "pc_board_results": [{"title": "mock article"}],
        }

    def gpu_specialist_stub(state, *, model_name=None, debug=False):
        call_log.append("gpu_specialist")
        return {"gpu_advice": "mock gpu advice"}

    def ecommerce_stub(state, *, model_name=None, debug=False):
        call_log.append("ecommerce")
        return {"ecommerce_advice": "mock ecommerce advice"}

    def integrator_stub(state, *, model_name=None, debug=False):
        call_log.append("integrator")
        return {"final_answer": "mock final answer"}

    try:
        graph_module.planner_node = planner_stub
        graph_module.pc_board_scraper_node = pc_board_scraper_stub
        graph_module.gpu_specialist_node = gpu_specialist_stub
        graph_module.ecommerce_node = ecommerce_stub
        graph_module.integrator_node = integrator_stub

        app = build_graph(model_name=None, debug=False)
        result = app.invoke(
            {
                "profile_id": "test-thread",
                "preferences": {},
                "request": "請幫我查第一篇文章的 GPU 目前價格，然後給我可買的建議",
                "messages": [],
            },
            config={"configurable": {"thread_id": "test-thread"}},
        )
    finally:
        graph_module.planner_node = original_planner_node
        graph_module.pc_board_scraper_node = original_pc_board_scraper_node
        graph_module.gpu_specialist_node = original_gpu_specialist_node
        graph_module.ecommerce_node = original_ecommerce_node
        graph_module.integrator_node = original_integrator_node

    print("call_log:", call_log)
    print("final_answer:", result.get("final_answer"))

    expected_log = [
        "planner",
        "pc_board_scraper",
        "gpu_specialist",
        "ecommerce",
        "integrator",
    ]
    assert call_log == expected_log, f"expected {expected_log}, got {call_log}"
    assert result.get("final_answer") == "mock final answer", result

    print("✓ full graph integration passed")


def main() -> None:
    test_article_then_ecommerce_queue()
    test_continue_after_scraper()
    test_full_graph_integration()
    print("\n✓ ecommerce routing smoke test passed")


if __name__ == "__main__":
    main()