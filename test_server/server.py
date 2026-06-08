from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from Message import Message
from pydantic import BaseModel

from api import generate

load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開發時先開放，上線再限縮
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatMessage(BaseModel):
    req: str | list[Message]    # 純文字或對話紀錄
    preference: dict = {}       # 偏好設置
    # id: str,
    # build: PCParts|None=None
    # 其他資訊

@app.post("/chat")
async def chat(chatMessage: ChatMessage):
    print(f"Receive:\n{chatMessage}")
    try:
        req = chatMessage.req
        if isinstance(req, str):
            req = [{"role": "user", "content": req}]
        response = generate(
            req=req,
            preference=chatMessage.preference
        )
    except Exception as e:
        response = {
            "error": e
        }
        print(e)

    #return StreamingResponse(response, media_type="text/event-stream")
    return response