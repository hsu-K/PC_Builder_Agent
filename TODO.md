# TODO

## pc_board_scraper Node
1. 能夠根據需求去爬取所需的文章 --fetch mode
2. 有效分析文章內容 --query mode 

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

## graph流程優化
1. 目前呼叫pc_board_scraper query mode 的流程不夠完善

## 更多專項的Node?
1. 類似gpu分析與cpu分析的專項分析Node...?