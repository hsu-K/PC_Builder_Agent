from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.pc_builder_agent.Message import Message
from pydantic import BaseModel
from pc_builder_agent.agent import PC_Builder_Agent

from dotenv import load_dotenv
load_dotenv()


@lru_cache(maxsize=1)
def get_agent() -> PCBuilder_Agent:
    return PC_Builder_Agent(
        model_provider = None,
        model_name = None,
        debug = True 
    )

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
    print(f"Recieve:\n{req}")
    try:
        agent = get_agent()
        if isinstance(req, str):
            req = [{"role": "user", "content": req}]
        response = agent.generate(
            req=chatMessage.req, 
            preference=chatMessage.preference
        )
        state = agent.get_state()
    except Exception as e:
        response = {
            "error": e
        }
        print(e)

    #return StreamingResponse(response, media_type="text/event-stream")
    return response