# PC Builder Agent

這是一個使用 LangGraph 建立的 multi-agent 起始範例，現在已串接 GPT API、工具呼叫與記憶體。

它會使用同一個 session id 同時保存短期對話記憶與偏好資料，方便你重跑同一組設定時延續上下文。

## 安裝

使用 uv 安裝依賴：

```bash
uv sync
```

程式會在啟動時自動讀取專案根目錄的 `.env`，所以你可以直接把 `OPENAI_API_KEY` 放進去。

執行前請先設定 OpenAI API key，例如：

```bash
export OPENAI_API_KEY="你的 key"
```

如果想指定模型，也可以設定：

```bash
export OPENAI_MODEL="gpt-4.1-mini"
```

## 執行範例

### 單次查詢模式

執行預設需求分析：

```bash
uv run python main.py
```

或直接傳入特定需求：

```bash
uv run python main.py "我想組一台 1440p 遊戲主機，預算 35000"
```

如果想用套件指令執行：

```bash
uv run pc-builder-agent --session-id demo "我需要一台剪輯用主機"
```

### 聊天模式 ⭐

啟用聊天模式，允許持續與 agent 對話：

```bash
uv run python main.py --chat
```

或指定特定 session-id 來保持記憶：

```bash
uv run python main.py --chat --session-id my-project
```

在聊天模式中：
- 輸入你的需求或提出追加問題
- Agent 會記住你的偏好設定和之前的對話內容
- 輸入 `exit` 或 `quit` 可以結束對話
- 同一個 `session-id` 可以跨越多次執行保持記憶

## 目前的架構

- `planner` 會先讀取偏好記憶，並視需要儲存新的偏好
- `router` 會根據需求判斷要啟動哪些 subAgent，避免每次都固定跑全部節點
- `cpu_specialist` 與 `gpu_specialist` 會依路由結果被啟動，必要時也能呼叫瓦數估算工具
- `integrator` 會把實際執行到的 agent 結果合成最後摘要

如果之後要擴充新的 subAgent，只要新增對應節點，並在 `graph.py` 裡的路由關鍵字與註冊表補上即可。

## 記憶體

同一個 `--session-id` 會共用短期對話記憶與偏好資料。你可以用相同 session id 再跑一次，讓模型讀到之前存下的資訊。

下一步可以把這些節點改成真正的 LLM agent，再接工具、記憶體與檢索資料來源。