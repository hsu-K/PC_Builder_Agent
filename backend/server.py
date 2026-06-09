from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from functools import lru_cache
from pydantic import BaseModel
from Message import Message, convert_messages

from agent import PC_Builder_Agent
from config import DEFAULT_MODEL_NAME

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