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
    pc_board_response: str
    # build: PCParts|None=None
    # 其他資訊

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
            preference={**chatMessage.preference, "pc_board_response": chatMessage.pc_board_response}
        )
        state = agent.get_state()
        agent.update_state(state)
        response = {
            **state,
            'message':message,
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