# PC Builder Agent

## 簡介

PC Builder Agent 是一個以節點（node）與工具（tool）為核心的模組化系統，用於根據使用者偏好與需求，提供 PC 組裝建議、爬取討論版文章、以及多角色代理（agent）式的互動流程。

這是一個使用 LangGraph 建立的 multi-agent 起始範例，現在已串接 GPT API、工具呼叫與記憶體。

它會使用同一個 session id 同時保存短期對話記憶與偏好資料，方便你重跑同一組設定時延續上下文。

### 重點功能

- **節點（Nodes）**：每個 node 負責一個職責（例如：爬蟲、專家回答、整合器等）。
- **工具（Tools）**：輔助功能模組，可供 agent 呼叫（例如：爬蟲模擬、硬體資訊查詢）。
- **狀態（state）**：中心化的作業狀態（包含 `preferences`、`profile_id` 等），節點間傳遞與共享。

## 專案目錄（概要）

- **`main.py`**: 程式進入點（示範或 CLI 啟動）。
- **`pyproject.toml`**: 專案相依與建構設定。
- **`pc_builder_agent/`**: 主程式套件目錄。
  - **`nodes/`**: 節點實作目錄（例如爬蟲、專家、整合器）。
  - **`tools/`**: 工具集合（給 agent 呼叫的外部功能或模擬器）。
  - **`chatbot.py`, `cli.py`**: 與使用者互動的入口元件。
  - **`data/articles/`**: 預設或已儲存的文章資料。

## 運作流程（可直接到graph.py查看詳細流程）

1. 首先從`preference.json`讀取使用者的偏好
2. 根據偏好與需求呼叫`pc_board_scraper` 爬蟲 node，來爬取文章
3. 進入chat模式，使用者透過 CLI 或 chat 介面發出需求。
4. Router 決定需要啟動哪些 node（例如：若需要最新討論則啟動 `pc_board_scraper`）。
5. Node 呼叫 `run_agent_turn()` 與 LLM 互動，並可選擇呼叫 `tools` 提供的功能（例如 `pc_board_scraper.invoke()`）。
6. Node 處理結果並回寫到 `state`。
7. 最終由`integrator node` 或回應流程將結果呈現給使用者。

## 開發與執行

```bash
# 建立/同步虛擬環境並安裝相依
uv sync

# 執行主程式（範例）
uv run main.py

# 若要執行debug模式(輸出更多提示訊息)
uv run main.py --debug
```

程式會在啟動時自動讀取專案根目錄的 `.env`，請直接把 `OPENAI_API_KEY` 放進去。

如果想指定模型，也可以設定`OPENAI_MODEL`

### 如何新增一個 Node（節點），範例請參考 node_template.py

1. 在 `pc_builder_agent/nodes/` 下新增檔案，例如 `my_new_node.py`。
2. 節點應實作一個主函式（習慣命名為 `<name>_node(state, *, model_name=None, debug=False)`），並回傳明確的字典結果。
3. 節點可使用 `run_agent_turn()` 與 LLM 互動；必要時把工具（tool）傳入 `tools=[...]`。

注意事項：

- 回傳格式應該一致且可被 router 或其他 node 消費（例如包含 `messages`、或 `response` 欄位）。

### 如何新增一個 Tool（工具），範例請參考 tool_template.py

1. 在 `pc_builder_agent/tools/` 下新增檔案並在 `__init__.py` 中匯出工具。

工具使用建議：

- 工具應保持純粹、單一職責，並避免直接修改 global state；node 負責串接工具結果並決定是否儲存。

## 共同開發流程

- 加入Collaborators → 建 feature branch → 開發並加上測試 → 發 PR。
- PR 記得描述：新增的 node/tool 目的、輸入輸出格式、必要的 state 欄位。

### 範例：測試 Node（router 範例）

示範如何直接呼叫單一 node（router），用於快速驗證路由邏輯。此腳本會對三個範例請求執行 `router_node`，並印出 `route_targets` 與 `route_reason`。

執行方式（在專案根目錄）：

```bash
uv run scripts/test_node.py
```

如果要查看或修改測試腳本，請參考專案根目錄下的 `scripts/test_node.py`。

---
