```
src/
├── api/                    # 與後端 API 對接服務
│   └── useChat.js          # API 呼叫邏輯
├── components/             # 各 UI 元件
│   ├── Sidebar/
│   │   ├── Sidebar.jsx     # 側邊欄容器
│   │   └── HistoryItem.jsx # 單筆歷史紀錄
│   ├── PartsPanel/
│   │   ├── PartsPanel.jsx  # 零件面板容器
│   │   ├── PartCard.jsx    # 單個零件卡片（含下拉）
│   │   └── BudgetBar.jsx   # 預算進度條
│   └── ChatPanel/
│       ├── ChatPanel.jsx   # 聊天面板容器
│       ├── Message.jsx     # 單則訊息泡泡
│       └── ChatInput.jsx   # 輸入框
├── hooks/                  # 自定義 hook
│   └── useChat.js          # API 呼叫邏輯
├── index.css               # 全域 css
├── App.css                 # 主頁面
├── main.jsx                # 建置的入口
└── README.md               # 本說明文件

```