"""
PC_Board Scraper Node（測試版）

功能：
- 根據 state 中的 preferences，爬取相關 PC_Board 文章
- 將爬取的文章列表存到 state['pc_board_results']，供其他 Agent 參考

注意：此版本並不執行真實爬蟲，僅回傳模擬資料供測試。
"""

from typing import Any


def pc_board_scraper_node(state: dict, *, model_name: str | None = None) -> dict[str, Any]:
    """根據偏好爬取 PC_Board 文章的 Node

    Args:
        state: 包含 preferences 的作業狀態
        model_name: 使用的 LLM 模組（此例未使用）
    
    Returns:
        dict: 包含 pc_board_results 的字典，供完整 Agent 流程使用
    """
    
    preferences = state.get("preferences", {})
    budget = preferences.get("budget", "未指定")
    use_case = preferences.get("use_case", "未指定")
    
    # 根據偏好產生模擬的 PC_Board 文章
    pc_board_articles = []
    
    # 模擬文章 1: 預算分析文章
    if budget and use_case:
        pc_board_articles.append({
            "id": "pcb_001",
            "title": f"[菜單] 50k遊戲機",
            "url": "https://www.ptt.cc/bbs/PC_Shopping/M.1779164308.A.DD1.html",
            "author": "LiuJY0327 (Hansel)",
            "date": "2026-05-19",
            "content": (
                f"預算/用途：50k\n"
                f"每次大概1-2個遊戲在跑而已，SSD抓1T應該夠，也比較符合自己預算\n"
                f"\n"
                f"CPU (中央處理器)：AMD Ryzen7 7800X3D Tray\n"
                f"MB      (主機板)：【任搭CPU】華碩 TUF GAMING B650-E WIFI\n"
                f"RAM     (記憶體)：【X3D專案】V-COLOR MANTA XSKY RGB DDR5-6000 32GB(16G*2)黑\n"
                f"VGA     (顯示卡)：【救贖】華碩 PRIME-RX9060XT-O16G\n"
                f"Cooler  (散熱器)： ID-COOLING FROZN A620 PRO SE ARGB 黑\n"
                f"SSD   (固態硬碟)：鎧俠 KIOXIA Exceria G2 1TB\n"
                f"HDD       (硬碟)：\n"
                f"PSU (電源供應器)：【救贖】MONTECH Century II 850W 金牌電源\n"
                f"CHASSIS   (機殼)：聯力 V100R 黑 全景玻璃機殼\n"
                f"MONITOR   (螢幕)：1080p自備\n"
                f"Mouse/KB  (鼠鍵)：\n"
                f"OS    (作業系統)：\n"
                f"\n"
                f"其它      (自填)：\n"
                f"總價 (未稅/含稅)：50,499"
            ),
            "comments": (
                "→ marsqq: 如果是跑3a不是競技類的話可考慮降成7700   114.33.93.15 05/19 12:57\n"
                "→ marsqq: 價差看省起來或補顯卡或其它地方   114.33.93.15 05/19 12:58\n"
                "→ Zenryaku: 顯卡拿Nitro+ +電源送G2 2T ，比你這樣 27.242.132.214 05/19 13:10\n"
                "→ Zenryaku: 買1T還便宜 27.242.132.214 05/19 13:10\n"
                "→ Zenryaku: 再不然也拿技嘉gaming+電源+ssd送主機板 27.242.132.214 05/19 13:11\n"
                "→ Zenryaku: 主板不要買這張，比差不多的em force貴 27.242.132.214 05/19 13:12\n"
                "→ Zenryaku: 五百，比更高級的b650a只便宜五百 27.242.132.214 05/19 13:12\n"
                "→ Zenryaku: xsky比較高，你要雙塔的話要拿高度160以 27.242.132.214 05/19 13:13\n"
                "→ Zenryaku: 上或是有偏移的 27.242.132.214 05/19 13:13\n"
                "→ Zenryaku: 一樓 降7700要拿同性能的記憶體不會比 27.242.132.214 05/19 13:17\n"
                "→ Zenryaku: 較省 27.242.132.214 05/19 13:17\n"
                "推 aa0801aa: idcooling的a410不錯啊，熱管直觸對AMD    27.51.9.211 05/19 15:07\n"
                "→ aa0801aa: 單CCD有奇效，單塔雙扇很夠了，78X3D連1    27.51.9.211 05/19 １5:07\n"
                "→ aa0801aa: 00w都跑不到用什麼雙塔    27.5１.9.２１１ 05/１９ １５:０７\n"
                "→ Zenryaku: xsky沒了 可以用黑王蛇代替 貴一點點 ２７.２４２.１３２.２１４ ０５/１９ １８:１６\n"
                "→ cutejojocat: ７８X３D問題是積熱 預算夠在意溫度就上 ３６.２２９.２４８.１６５ ０５/２０ ０１:１１\n"
                "→ cutejojocat: 雙塔 顯卡不在意非三大廠的話 藍寶 ３６.２２９.２４８.１６５ ０５/２０ ０１:１１\n"
                "→ cutejojocat: 石也是五年保  "
            ),
        })
    
    # 模擬文章 2: 顯示卡比較文章
    pc_board_articles.append({
        "id": "pcb_002",
        "title": "2026 年中端顯示卡推薦鑑賞",
        "url": "https://www.pc-board.cc/bbs/PC_Shopping/M.1234567891.A.html",
        "author": "GPU_Expert",
        "date": "2026-05-19",
        "content": (
            "我整理了 2026 年中端 GPU 的一些撥特\n"
            "RTX 4070: 優誼的 1440P 機能\n"
            "RX 7800 XT: 地鱗章幀，效能相似"
        ),
    })
    
    
    print(f"\n✓ PC_Board Scraper 成功爬取 {len(pc_board_articles)} 篇文章")
    for idx, article in enumerate(pc_board_articles, 1):
        print(f"   {idx}. [{article['id']}] {article['title']}")
    
    # 回傳整合的結果
    return {"pc_board_results": pc_board_articles}
