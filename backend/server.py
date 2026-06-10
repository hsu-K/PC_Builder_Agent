from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from functools import lru_cache
from pydantic import BaseModel
from Message import Message, convert_messages

from agent import PC_Builder_Agent
from config import DEFAULT_MODEL_NAME
from pc_builder_agent.nodes.pc_board_scraper import pc_board_scraper_node

from dotenv import load_dotenv
load_dotenv()

@lru_cache(maxsize=1)
def get_agent() -> PC_Builder_Agent:  # 拼錯：PCBuilder_Agent -> PC_Builder_Agent
    return PC_Builder_Agent(
        model_name=DEFAULT_MODEL_NAME,
        debug=True
    )

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatMessage(BaseModel):
    id: str
    messages: list[Message]
    preference: dict = {}       # 偏好設置
    pc_board_response: str = ""
    pc_board_articles: list = []  # 前端爬取的文章

class FetchArticlesRequest(BaseModel):
    id: str                    # 使用者 session ID
    preference: dict = {}      # 偏好設置 (budget, use_case 等)

@app.post("/chat")
async def chat(chatMessage: ChatMessage):
    print("Server Recieve:"+"-"*25)
    print(f"id: {chatMessage.id}")
    print(f"messages: {chatMessage.messages}")
    print(f"preference: {chatMessage.preference}")
    print(f"pc_board_response: {chatMessage.pc_board_response}")
    print("-"*30)

    response = {}
    try:
        agent = get_agent()
        messages = convert_messages(chatMessage.messages)
        message = agent.generate(
            id=chatMessage.id,
            messages=messages,
            preference={**chatMessage.preference, "pc_board_response": chatMessage.pc_board_response},
            articles=chatMessage.pc_board_articles,
        )
        state = agent.get_state()
        agent.update_state(state)

        # 將 component_options 轉為前端 PartsPanel 所需的 options 格式
        component_options = state.get("component_options") or {}
        # 只留 frontend 對應的 key，確保 value 是 list
        frontend_options = {}
        frontend_parts = {}
        for key, items in component_options.items():
            if isinstance(items, list) and len(items) > 0:
                frontend_options[key] = items
                # 預設選取每個類別的第一個商品
                frontend_parts[key] = items[0]

        response = {
            **state,
            'message': message,
            'options': frontend_options,
            'parts': frontend_parts,
        }
    except Exception as e:
        response = {"error": str(e)}  # e 要轉 str
        print(e)

    return response


@app.post("/fetch-articles")
async def fetch_articles(req: FetchArticlesRequest):
    """根據使用者偏好爬取 PTT PC_Shopping 文章，回傳全部文章。

    接收 id 與 preference（含 budget, use_case），
    直接呼叫 pc_board_scraper_node 以 fetch 模式爬取文章，
    不回傳部分內容而是回傳完整文章列表。
    """
    print("Fetch Articles Request:" + "-" * 25)
    print(f"id: {req.id}")
    print(f"preference: {req.preference}")
    print("-" * 30)

    try:
        state = {
            "profile_id": req.id,
            "preferences": req.preference,
        }
        result = pc_board_scraper_node(
            state,
            model_name=DEFAULT_MODEL_NAME,
            mode="fetch",
            debug=True,
        )
        articles = result.get("pc_board_results", [])
        return {
            "status": "success",
            "articles_count": len(articles),
            "articles": articles,
        }
    except Exception as e:
        print(f"Fetch articles error: {e}")
        return {
            "status": "error",
            "message": str(e),
            "articles_count": 0,
            "articles": [],
        }