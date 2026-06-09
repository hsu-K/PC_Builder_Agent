### PC_Builder_UI
含前端與後端


#### 開啟 server(測試)
```
cd test_server
uvicorn server:app --reload --port 8000
```
```
cd backend
uv run uvicorn server:app --reload --port 8000
```

#### UI建置(測試)
```
cd frontend

# 安裝依賴
npm install

# 跑本地UI
npm run dev
```
進入建置的本地UI網站: `http://localhost:5173/`