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

- [x] 建立 SQLite 商品資料庫層
- [x] 建立 seed demo data
- [x] 建立商品查詢 tool
- [x] 建立優惠查詢 tool
- [x] 建立 ecommerce node
- [x] 接入 graph/router/integrator
- [x] 完成無 API key 的離線整合測試
- [x] 使用 OPENAI_API_KEY 完整端到端測試
- [x] 建立正式 data/ecommerce.db
- [x] CoolPC parser
- [x] CoolPC fetch + update flow
- [x] CoolPC tempfile DB update test
- [x] CoolPC parser 擴充至 8 類：CPU/GPU/Motherboard/RAM/Storage/PSU/Case/Cooler
- [x] Cooler / 散熱器正式納入
- [x] Cooler 支援空冷塔散與 AIO 水冷
- [x] Cooler 配件過濾：散熱膏 / 散熱墊 / SSD 散熱片 / 機殼風扇等排除
- [x] Cooler 路由支援：散熱器 / 空冷 / 水冷 / AIO 查詢會 route 到 ecommerce
- [x] CoolPC 正式本地 DB 更新（8 類）
- [x] 完整菜單推薦工具 recommend_pc_build_tool
- [x] 完整菜單總價計算
- [x] 預算 80%～120% 區間檢查
- [x] 不合理需求例外處理（高預算文書機 / 低預算 4K 遊戲機不硬湊）
- [x] gaming build 最低選品策略：RAM / Storage / PSU
- [x] CPU / Motherboard / RAM 基本相容性檢查（socket / memory_generation）
- [ ] 欣亞爬蟲
- [ ] PChome 爬蟲
- [ ] momo 爬蟲
- [ ] 自動排程更新
- [ ] 改善 below_avg：改成同型號或同規格比較
- [ ] 更完整的硬性零組件相容性檢查器
- [ ] 更完整的機殼 / GPU 長度 / Cooler 高度 / AIO 水冷排相容性檢查

## 商城優惠（Promotions）

- [x] Promotion schema：promotions / promotion_products
- [x] CoolPC promotion parser
- [x] Promotions 正式寫入本地 SQLite DB
- [x] Promotion 查詢工具 search_ecommerce_promotions
- [x] 完整菜單附加 promotion 參考資訊
- [x] actual_discount 單品特價辨識
- [x] bundle_discount 搭配折扣辨識
- [x] text_promo 活動提醒辨識
- [x] below_avg 與 promotion 語意分離
- [x] 優惠試算欄位 estimated_final_price（不覆蓋原始 total_price）
- [x] 固定價格摘要：原始總價 / 可計算優惠折抵 / 預估優惠後總價
- [x] 搭板優惠相容配對工具 find_bundle_discount_pc_pairs
- [x] bundle_discount CPU + Motherboard socket 相容性守門
- [x] 防止 AM5 CPU 搭 AM4 主機板仍套用搭板折扣
- [x] 防止 LLM 自行手算搭板折扣
- [x] 端到端搭板優惠查詢使用 deterministic tool 結果
- [ ] 讓使用者選擇是否套用 bundle_discount 試算
- [ ] 讓 promotion 影響一般完整菜單選品排序 / build scoring
- [ ] 搭板優惠配對加入主機板供電 / VRM / 擴充性評分
- [ ] 高階 CPU 避免只配最低價入門主機板的 scoring
- [ ] 購物車 / 結帳頁最終價格同步
- [ ] 欣亞 promotion parser
- [ ] PChome promotion parser
- [ ] momo promotion parser
- [ ] 更完整的跨商品 bundle / combo rules 推理

## 完整菜單硬體邏輯守門（Final-QA）

- [x] D4 / D5 主機板記憶體世代 fallback 判斷
- [x] Motherboard / RAM memory_generation 最終相容性守門
- [x] Gaming build 主要 Storage SSD guard
- [x] 無 GPU build 的 CPU 內顯 / 顯示輸出守門
- [x] Final hardware logic QA：9 個完整菜單案例通過
- [ ] 更完整的 BIOS 版本相容性檢查
- [ ] GPU 長度 / 機殼空間相容性檢查
- [ ] Cooler 高度 / AIO 水冷排安裝位檢查
- [ ] PSU 接頭 / 顯卡供電需求檢查
- [ ] 主機板 VRM / 供電 / 擴充性評分
- [ ] 正式 DB specs 重建，使 D4 / D5 fallback 結果直接寫回 DB

## 互動式零組件候選推薦（Phase Simplify）

- [x] 新增互動式零組件候選推薦工具 recommend_component_options_tool
- [x] 新增已選零件相容性驗證工具 validate_selected_build_tool
- [x] 新增已選零件摘要工具 summarize_selected_build_tool
- [x] 新增 platform_rules.py 作為平台 / socket / memory_generation 規則來源
- [x] Router 支援互動式選件意圖，例如候選、選項、第 N 個、換平台、DDR4/DDR5 主機板
- [x] ecommerce node 支援逐步選件流程
- [x] integrator 支援候選 options 模式
- [x] selected_* 商品名稱多階段比對（exact / normalized / model_key / brand+model token / category 限定 + 世代·晶片組硬性約束）
- [x] 互動式選件端到端測試通過
- [x] DDR4/DDR5、AM4/AM5、Intel/AMD 相容性測試通過
- [x] 預算組機預設改為 CPU-first 逐步選件
- [x] 一般組機問題不再主動直接輸出完整菜單
- [x] AMD / Intel 品牌偏好可限制 CPU 候選
- [x] 選 CPU 後主機板依 socket 過濾
- [x] 選主機板後 RAM 依 DDR4 / DDR5 過濾
- [x] 完整菜單模式僅在明確要求時使用
- [x] Router 支援「自己挑零件 / 從 CPU 開始 / 接下來主機板 / 接下來 RAM」等互動式流程

### State-driven 互動式選件（Phase Interactive-State-Driven-Fix / Office）

- [x] graph state 保存 selected_components
- [x] graph state 保存 last_component_options / current_target_category
- [x] 「第 N 個」改為 deterministic 解析（resolve_selection_from_last_options）
- [x] 下一步類別由 get_next_component_category deterministic 決定
- [x] 固定選件順序 CPU → GPU → Motherboard → RAM → Storage → PSU → Cooler → Case
- [x] 每輪顯示已選零件與目前總額 / 剩餘預算 / 下一步
- [x] GPU 虛擬「無獨立顯示卡」選項
- [x] Cooler 固定「無額外散熱器」選項
- [x] 完整菜單後支援重新選單項（reselect）
- [x] 確認後保存 JSON 到 outputs/builds
- [x] Router deterministic 前置路由互動選件動作到 ecommerce
- [x] integrator 對 interactive_response 直接沿用 deterministic final_answer
- [x] office CPU 優先有內顯
- [x] office CPU value filter 避免高階遊戲 CPU（X3D / R9 / i9 / Core Ultra 9 / K / 高價）

### 完整菜單操作選單與 reselect 相依清除（Phase Interactive-Reselect-Menu-Fix）

- [x] 完整菜單操作選單 1~9 deterministic 解析（parse_completed_menu_action）
- [x] selection_flow_complete=True 時，2/3/4… 對應 reselect CPU/GPU/Motherboard…
- [x] 非完整狀態下數字仍代表上一輪候選第 N 個
- [x] 重新選 CPU 時自動移除 Motherboard / RAM / Cooler
- [x] 重新選 CPU 且 GPU none 不再有效時自動移除 GPU
- [x] 重新選 GPU 時自動移除 PSU
- [x] 重新選 Motherboard 時自動移除 RAM
- [x] 重新選 Cooler 時保留 Cooler none 選項並提醒 Case 空間
- [x] reselect 後從第一個缺少類別繼續推薦
- [x] final menu 與 JSON 以 selected_components 為唯一權威來源

### CLI 入口與 fresh-session guard（Phase CLI-and-First-Input-Guard）

- [x] 正式互動式 CLI 入口（uv run python -m pc_builder_agent.cli）
- [x] CLI 支援 reset / status / exit
- [x] fresh session selection-like input guard（is_selection_like_input / has_active_selection_state）
- [x] 無 active flow 時，裸輸入 1 / 我選第 N 個 / 無 / 確認 不會預設 gaming 或開始流程
- [x] 只給預算缺用途會問用途；只給用途缺預算會問預算（不預設 gaming）
- [x] 只給預算的裸句（我預算 30000 / 30000 元 / 預算 3 萬）deterministic 進 guard，不走 LLM 商品查詢（is_budget_only_input）
- [x] 只說要組電腦 / 我想自己挑零件（無預算無用途）會要求提供預算與用途
- [x] budget / use_case 記憶：先給預算再給用途即可開始 CPU-first

### 中文金額解析與 gaming CPU 預算級距（Phase Budget-Parsing-and-Tiered-CPU-Recommendation）

- [x] 中文金額解析：十萬 / 10萬 / 三萬 / 兩萬 / 一萬五 / 5萬5 / 十二萬 / 1.5萬
- [x] 避免把商品型號數字當預算（RTX 5070 / i5-12400F / B650 / DDR5）
- [x] 「預算十萬元，組遊戲機」直接 budget=100000 + gaming 開始 CPU-first
- [x] gaming CPU 依預算級距推薦（>50k 主推中高階/高階，排除 i5-12400F/R5 5500/5600）
- [x] 省預算較入門 CPU 以 warning alternative 呈現，不放主要候選
- [x] gaming 30000 CPU 不被高預算規則過度拉高
- [x] office CPU value filter 與 gaming tier 互斥、互不影響

### 各類別 use_case + 預算級距過濾（Phase Component-Tier-Audit-and-Fix）

- [x] GPU 排除工作站/專業卡（RTX Ada / Quadro / ARC PRO / ProArt / Creator / ECC / CMP）
- [x] GPU gaming 預算級距：高預算不主推低階卡（80k/100k 不出 RTX 2000 Ada / ARC PRO / 8k 入門卡為主推）
- [x] GPU 30000 gaming 不被高預算規則過度拉高
- [x] RAM 排除 ECC / 伺服器記憶體；高預算 gaming 優先 32GB+
- [x] Storage 高預算 gaming 優先 1TB+（主系統碟仍為 SSD/NVMe）
- [x] PSU 依預算/已選 GPU 設瓦數下限；低預算不硬推 >850W
- [x] Motherboard 高預算/高階 CPU 避免只推最低階供電板
- [x] Case 高預算避免只推超便宜小機殼 + airflow/顯卡長度 warning
- [x] 省預算較入門候選以 warning alternative 呈現，不放主要候選
- [ ] 以 specs（顯卡長度 / 散熱器高度 / 機殼相容尺寸）做硬性過濾（目前以名稱/價格 + warning）

### 外部 component recommender 整合（Phase External-Component-Recommender-Integration）

- [x] 將候選零件推薦邏輯抽成 external recommender adapter（recommend_component_options dispatcher）
- [x] feature flag USE_EXTERNAL_COMPONENT_RECOMMENDER + set_external_component_recommender + 環境變數接入
- [x] 整理乾淨 context（預算/用途/已選零件/總價/剩餘/socket/世代/相容性）給外部
- [x] 外部結果正規化成現有 options schema、不外洩內部欄位
- [x] 保留最小 safety validation（socket / 世代 / 品牌不符過濾 + warning）與固定虛擬「無」選項
- [x] 外部未接 / 失敗時安全 fallback 到 legacy 內建推薦
- [x] 建立 recommenders 接入點套件（recommenders/external_adapter.py + 範例 example_recommend + context/option schema）
- [x] 環境變數 / 程式註冊啟用外部 recommender，並端到端驗證（CLI 候選改由外部決定）
- [x] fallback 策略：外部空/出錯/不相容 → warning + fallback legacy
- [ ] 接入同學實作的正式 recommender（待同學提供檔案路徑/函式名稱/輸入輸出格式）
- [ ] 完全停用 legacy tier ranking（待外部 recommender 穩定後）
- [ ] 擴充 external recommender 的相容性測試
- [ ] 定義 recommender context / option schema 文件（已在 external_adapter.py docstring 提供初版）
- [ ] 更完整硬體相容性檢查：BIOS、GPU 長度、機殼空間、Cooler 高度、AIO 水冷排、PSU 接頭、VRM
- [ ] UI selector / button 選項（而非只靠文字「第 N 個」）
- [ ] 多商城候選排序
- [ ] 使用者偏好記憶：品牌、靜音、RGB、小機殼
- [ ] office CPU 候選更精細的 TDP / 功耗 / 能耗評分
- [ ] 非互動式 ecommerce 查詢減少 LLM tool-calling 依賴
- [ ] 更精細的 Case / GPU / Cooler 尺寸自動驗證
- [ ] 確認保存前是否需要二次確認的 UX 設定選項

## 本地 DB 更新（手動，無自動排程）

- [x] Manual local DB update flow documented
- [x] Dry-run update command documented
- [x] Write update command documented
- [x] DB update flowchart documented
- [ ] OS cron / systemd automatic update
- [ ] Multi-store update scheduler
- [ ] Update failure notification

## 前端應用介面

1. 使用這可互動的前端介面

## 驗證 Node

## graph流程優化

1. 目前呼叫pc_board_scraper query mode 的流程不夠完善

## 更多專項的Node?

1. 類似gpu分析與cpu分析的專項分析Node...?
