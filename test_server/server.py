from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from Message import Message

from api import generate

load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開發時先開放，上線再限縮
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/chat")
async def chat(
    req: str | list[Message], # 純文字或對話紀錄
    # id: str,
    # build: PCParts|None=None
    # 其他資訊
  ):
    print(f"Recieve:\n{req}")
    try:
        if isinstance(req, str):
            req = [{"role": "user", "content": req}]
        response = generate(req, None)
    except Exception as e:
        response = {
            "error": e
        }

    #return StreamingResponse(response, media_type="text/event-stream")
    return response