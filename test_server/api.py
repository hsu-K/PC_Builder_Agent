import json
from Message import Message, PCParts

with open('./mockdata.json', 'r', encoding='utf-8') as f:
    mockdata = json.load(f)

def generate(req: list[Message], parts: PCParts):
    return mockdata