from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from functools import lru_cache
from pydantic import BaseModel
from Message import Message, convert_messages

from agent import PC_Builder_Agent

from dotenv import load_dotenv
load_dotenv()

@lru_cache(maxsize=1)
def get_agent() -> PC_Builder_Agent:  # 拼錯：PCBuilder_Agent -> PC_Builder_Agent
    return PC_Builder_Agent(
        model_name=None,
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

@app.post("/chat")
async def chat(chatMessage: ChatMessage):
    print(f"Recieve:\n{chatMessage}")
    try:
        agent = get_agent()
        messages = convert_messages(chatMessage.messages)
        response = agent.generate(
            id=chatMessage.id,
            messages=messages,
            preference={**chatMessage.preference, "pc_board_response": chatMessage.pc_board_response}
        )
        state = agent.get_state()
    except Exception as e:
        response = {"error": str(e)}  # e 要轉 str
        print(e)

    return response