# TODO

## pc_board_scraper Node ✅ 已完成

### 1. Fetch Mode — 根據需求爬取 PTT 文章 ✅

**爬蟲引擎 (`tools/scraper.py`)**

- 真實連線 PTT PC_Shopping 版，通過 Over18 認證
- 僅擷取 `[菜單]` 開頭的文章，過濾其他討論
- 支援多來源收集：最新熱門列表 + 預算區間搜尋 + 純用途搜尋，去重後合併
- 依推文熱度（|nrec|）排序，取前 10 篇最熱門文章
- 支援 `爆` / `X1`~`X9` / `XX` / 數字 等推文數解析
- 自動分頁（最多 5 頁），每頁間隔 0.3 秒避免被封鎖
- Rate limiting：每篇文章間隔 0.5 秒

**文章內容萃取**

- 推文結構化：推/噓/→ 三種分類，個別記錄 userid、content、ipdatetime
- 內容清理：移除推文區塊、meta 資訊、簽名檔
- 菜單精簡：只保留「已買/未買」到「總價」段落，去除 PTT 版規注意事項
- 零件解析：支援 12 種零件（CPU、主機板、記憶體、顯示卡、散熱器、SSD、HDD、電源、機殼、螢幕、鼠鍵、作業系統），以結構化 `components` 欄位儲存
- 預算推論：從總價行自動計算金額，分類為 low / medium / high

**JSON 儲存格式最佳化**

- `id`：從 URL 提取 `ptt_M.xxxx.A.xxx` 語意化 ID
- `source` / `board`：標示來源為 `ptt` / `PC_Shopping`
- `pulled_at`：ISO 8601 時間戳
- `inferred_budget` / `inferred_budget_range`：預先推論預算，避免重複 regex
- 不含 PTT 版規雜訊，節省 75% token

**預算+用途篩選機制**

- 支援分類：遊戲（game）、工作/文書（work/office）、剪輯/影片（edit/video）、AI/深度/機器（AI/deep/ML/LLM）
- 預算區間搜尋：以使用者預算為中心 ±15K，步長 5K 產生搜尋詞（如 `40k遊戲`、`45k遊戲`、`50k遊戲`）
- 三階段搜尋策略：最新文章 → 預算+用途搜尋 → 純用途搜尋，確保結果精準且數量充足
- 最終結果固定 10 篇，不超過

### 2. Query Mode — 有效分析文章內容 ✅

**結構化分析報表 (`nodes/pc_board_scraper.py`)**

- 預算分布：自動將文章分為低（<30K）、中（30K~60K）、高（>60K）三個區間
- 各文章完整配置：逐篇列出 12 種零件的型號與品牌
- 零件配置統計：依零件類型彙總，去重後列出所有出現的型號
- 配置多樣性：涵蓋零件類型數、預算區間數
- 社群評價分析：
  - 全體推/噓/中立統計
  - 整體好評率計算（推 / (推+噓)）
  - 各文章社群反響（附情感標籤 🟢 社群推薦 / 🟡 尚可 / 🔴 爭議較大）
  - 代表性推文擷取（最多 3 則推/噓）
  - 常見建議關鍵字統計（散熱、電源、SSD、記憶體...共 11 個關鍵字）
- 分析報表直接注入 LLM system prompt，提供 AI 即時引用

**查詢模式流程**

- 優先從 state 讀取文章，若無則從磁碟載入
- 支援離線分析（無需 LLM）
- 輸出包含完整文章連結、推文統計與好評率

### 3. 程式碼品質 ✅

**遵循的最佳實踐**

- Pure function 設計：報表建構函式皆為純函式，不修改外部資料
- 常數集中管理：`COMPONENT_LABELS` 定義於模組層級
- 爬蟲工具拆分：`scraper.py` 拆分為 10+ 個單一職責輔助函式
- 型別提示：完整 function signature type hints
- 零 lint error

**測試覆蓋（`scripts/test_pc_board_scraper.py`）**

- Test 1：工具直接呼叫（5 種 budget/use_case 組合）
- Test 2：結構化分析報表驗證
- Test 3：完整爬取流程（需 OPENAI_API_KEY）
- Test 4：本機文章分析（無需 API Key）
- Test 5：直接工具呼叫與儲存/讀取週期驗證

## 電子商城推薦 Node

1. 爬取資料
2. 建立資料庫
3. 使用這詢問時可以尋找優惠組合

## 前端應用介面

1. 使用這可互動的前端介面

## 驗證 Node

## graph流程優化

1. 目前呼叫pc_board_scraper query mode 的流程不夠完善

## 更多專項的Node?

1. 類似gpu分析與cpu分析的專項分析Node...?
