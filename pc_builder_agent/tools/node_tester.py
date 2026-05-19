"""
簡易 Node 測試工具（Mock 模式）

說明：
- 讓不同專案成員可獨立執行與測試 `pc_builder_agent.nodes` 下的 node 函式。
- 預設使用內建的 mock model，避免呼叫外部 LLM API。

使用範例：
python -m pc_builder_agent.tools.node_tester --node cpu_specialist_node --state-json '{"request":"我要一台遊戲用電腦"}'

"""
from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys
from types import SimpleNamespace


def find_node(node_name: str):
    """根據給定名稱尋找 node 函式。

    支援完整模組路徑 `pc_builder_agent.nodes.cpu_specialist.cpu_specialist_node`
    或只提供函式名稱 `cpu_specialist_node`（會在 nodes 套件中搜尋）。
    """
    if "." in node_name:
        mod_name, func_name = node_name.rsplit(".", 1)
        mod = importlib.import_module(mod_name)
        return getattr(mod, func_name)

    nodes_pkg = importlib.import_module("pc_builder_agent.nodes")
    for finder, name, ispkg in pkgutil.iter_modules(nodes_pkg.__path__):
        try:
            mod = importlib.import_module(f"{nodes_pkg.__name__}.{name}")
        except Exception:
            continue
        if hasattr(mod, node_name):
            return getattr(mod, node_name)

    raise ImportError(f"Node '{node_name}' not found in pc_builder_agent.nodes")


class MockModel:
    """簡單的 mock model，回傳固定回應且不會呼叫外部 API。"""

    def __init__(self, response: str = "[MOCK] 模擬回應"):
        self._response = response

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return SimpleNamespace(content=self._response, tool_calls=[])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Node 測試工具（mock 模式）")
    p.add_argument("--node", required=True, help="要測試的 node 函式名稱或模組路徑")
    p.add_argument("--state-file", help="JSON 檔案，作為 state 輸入")
    p.add_argument("--state-json", help="直接提供 JSON 字串作為 state")
    p.add_argument("--mock-response", default="[MOCK] 這是測試回應", help="Mock 模型回應文字")
    args = p.parse_args(argv)

    if not args.state_file and not args.state_json:
        print("請提供 --state-file 或 --state-json 作為 node 的 state。", file=sys.stderr)
        return 2

    try:
        if args.state_file:
            with open(args.state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
        else:
            state = json.loads(args.state_json)
    except Exception as e:
        print("無法讀取 state：", e, file=sys.stderr)
        return 3

    # 覆寫 base.build_model 為 MockModel
    try:
        base = importlib.import_module("pc_builder_agent.nodes.base")
        base.build_model = lambda model_name=None: MockModel(response=args.mock_response)
    except Exception as e:
        print("無法覆寫 base.build_model：", e, file=sys.stderr)
        return 4

    try:
        node_fn = find_node(args.node)
    except Exception as e:
        print("找不到 node：", e, file=sys.stderr)
        return 5

    try:
        # 大多數 node 函式接受 (state, *, model_name=None)
        result = node_fn(state, model_name=None)
    except TypeError:
        result = node_fn(state)
    except Exception as e:
        print("執行 node 時發生錯誤：", e, file=sys.stderr)
        return 6

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
