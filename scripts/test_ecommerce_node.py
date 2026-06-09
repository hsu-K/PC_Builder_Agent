"""
測試腳本：直接呼叫 Ecommerce Node，查詢 RTX 5070 相關產品

執行方式：
    uv run python scripts/test_ecommerce_node.py

此腳本會：
1. 呼叫 ecommerce_node，傳入 request = "查rtx 5070的相關產品"
2. 印出回傳的各個欄位，包含：
   - final_answer（最終顯示給使用者的文字）
   - ecommerce_advice（LLM 的原始回應文字）
   - ecommerce_options（結構化查詢結果，如果有的話）
   - messages（對話歷史中的 AIMessage）

注意：需要設定 OPENAI_API_KEY 環境變數才會實際呼叫 LLM。
若無 API key，腳本會展示「DB 不存在」的守門訊息流程。
"""

import os
from dotenv import load_dotenv
from pc_builder_agent.nodes.ecommerce import ecommerce_node

load_dotenv()

def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"【{title}】")
    print(f"{'=' * 60}")


def test_ecommerce_node_rtx5070():
    """測試 ecommerce node 查詢 RTX 5070 產品"""

    state = {
        "request": "查rtx 5070的相關產品",
    }

    _section("測試 ecommerce_node")
    print(f"Request: {state['request']}")

    # 檢查 OPENAI_API_KEY

    # 呼叫 ecommerce node
    try:
        result = ecommerce_node(state, model_name= 'gpt-4.1-mini', debug=True)
    except Exception as e:
        print(f"\n❌ 錯誤：{type(e).__name__}: {e}")
        print("\n💡 說明：若為 OpenAI API key 錯誤，請設定 OPENAI_API_KEY 後重試。")
        print("   若為其他錯誤，請檢查程式碼與資料庫狀態。")
        return

    _section("回傳結果")

    # 1. final_answer：最終顯示給使用者的完整回答
    final_answer = result.get("final_answer", "")
    print("\n📄 final_answer（最終回答）：")
    print("-" * 40)
    print(final_answer if final_answer else "（空）")

    # 2. ecommerce_advice：LLM tool-calling 路徑的原始回應文字
    ecommerce_advice = result.get("ecommerce_advice", "")
    print("\n📄 ecommerce_advice（LLM 原始回應）：")
    print("-" * 40)
    print(ecommerce_advice if ecommerce_advice else "（空）")

    # 3. ecommerce_options：結構化查詢結果（若有的話）
    ecommerce_options = result.get("ecommerce_options")
    print("\n📄 ecommerce_options（結構化查詢結果）：")
    print("-" * 40)
    if ecommerce_options:
        print(f"  mode:           {ecommerce_options.get('mode')}")
        print(f"  category:       {ecommerce_options.get('category')}")
        print(f"  exact_match:    {ecommerce_options.get('exact_match')}")
        print(f"  spec_match:     {ecommerce_options.get('spec_match')}")
        print(f"  fallback_used:  {ecommerce_options.get('fallback_used')}")
        print(f"  query:          {ecommerce_options.get('query')}")
        print(f"  summary:        {ecommerce_options.get('summary')}")
        print(f"  warnings:       {ecommerce_options.get('warnings', [])}")
        items = ecommerce_options.get("items", [])
        print(f"  items 筆數:     {len(items)}")
        for i, item in enumerate(items, 1):
            price = item.get("price_text") or f"{item.get('price', 'N/A')} 元"
            print(f"  [{i}] {item.get('name')} — {price}")
    else:
        print("  （無結構化查詢結果 → 此 request 由 LLM tool-calling 路徑全權處理）")

    # 4. messages：對話歷史中的 AIMessage
    messages = result.get("messages", [])
    print(f"\n📄 messages 筆數：{len(messages)}")
    for i, msg in enumerate(messages):
        preview = str(msg.content)[:120]
        print(f"  [{i}] type={type(msg).__name__}, content_preview={preview}...")

    _section("測試完成")

def find_related_goods(good_list: list[str]):
    for good in good_list:
        _section(f"測試 ecommerce_node 查詢 {good} 相關產品")
        state = {
            "request": f"查{good}的相關產品"
        }
        result = ecommerce_node(state, model_name='gpt-4.1-mini', debug=False)

        _section("回傳結果")


        # 2. ecommerce_advice：LLM tool-calling 路徑的原始回應文字
        ecommerce_advice = result.get("ecommerce_advice", "")
        print("\n📄 ecommerce_advice（LLM 原始回應）：")
        print("-" * 40)
        print(ecommerce_advice if ecommerce_advice else "（空）")

        # 3. ecommerce_options：結構化查詢結果（若有的話）
        ecommerce_options = result.get("ecommerce_options")
        print("\n📄 ecommerce_options（結構化查詢結果）：")
        print("-" * 40)
        if ecommerce_options:
            print(f"  mode:           {ecommerce_options.get('mode')}")
            print(f"  category:       {ecommerce_options.get('category')}")
            print(f"  exact_match:    {ecommerce_options.get('exact_match')}")
            print(f"  spec_match:     {ecommerce_options.get('spec_match')}")
            print(f"  fallback_used:  {ecommerce_options.get('fallback_used')}")
            print(f"  query:          {ecommerce_options.get('query')}")
            print(f"  summary:        {ecommerce_options.get('summary')}")
            print(f"  warnings:       {ecommerce_options.get('warnings', [])}")
            items = ecommerce_options.get("items", [])
            print(f"  items 筆數:     {len(items)}")
            for i, item in enumerate(items, 1):
                price = item.get("price_text") or f"{item.get('price', 'N/A')} 元"
                print(f"  [{i}] {item.get('name')} — {price}")

if __name__ == "__main__":
    # test_ecommerce_node_rtx5070()
    # find_related_goods(["RTX 5060Ti 16GB", "intel Core Ultra 7 270K", "華碩 PRIME Z890-P WIFI-CSM D5/ATX/3+1年保/LGA1851", "ZOTAC RTX5080 SOLID CORE OC"])
    find_related_goods(["INNO3D RTX5080 X3", "INNO3D RTX5080 X3 OC", "華碩 PRIME-RTX5080-16G", "微星 RTX5080 16G VENTUS 3X OC"])
