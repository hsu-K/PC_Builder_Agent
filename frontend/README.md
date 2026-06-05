## PC Builder Agent UI

### UI建置(測試)
```
cd frontend
npm run dev
```

### 功能
#### 左邊 Sidebar
* 歷史紀錄

#### 中間 PartPanel
* 顯示預算
* 顯示配件資訊
* 選擇配件
* 匯出配置.txt

#### 右邊 ChatPanel
* 與agent溝通
* 使用模板

#### 其他
* 目前使用瀏覽器的 LocalStorage 儲存每項紀錄


---

## React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.
