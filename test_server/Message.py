from pydantic import BaseModel


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

