from pydantic import BaseModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage


class Message(BaseModel):
  role: str
  content: str


class PCParts(BaseModel):
    gpu: str
    cpu: str
    ram: str
    mb: str
    ssd: str
    psu: str
    case: str
    cooler: str


def convert_messages(messages: list[Message]) -> list[BaseMessage]:
    role_map = {
        "user": HumanMessage,
        "assistant": AIMessage,
    }
    return [role_map[msg.role](content=msg.content) for msg in messages]