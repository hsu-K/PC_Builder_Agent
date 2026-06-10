import json
from pc_builder_agent.graph import build_graph
#from pc_builder_agent.memory import save_user_preference
from config import DEFAULT_MODEL_NAME
from langchain_core.messages import BaseMessage
import ast


from dotenv import load_dotenv
load_dotenv()

class PC_Builder_Agent:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        debug: bool = False
    ):
        self.graph = build_graph(
            model_name=model_name,
            debug=debug
        )
        self.state = {
            "profile_id": "default",    # 使用者會話 ID
            "preferences": {},          # 偏好設定
            "pc_board_response": "",    # 已爬取的 PC_Board 文章列表
            "request": "",              # 目前輪次的使用者需求
            "messages": [],             # 完整對話歷史
        }

    def generate(
        self,
        id: str,
        messages: list[BaseMessage],
        #parts: PCParts = {},
        preference={},
    ):
        self.state = {
            "profile_id": id,
            "preferences": preference,
            "pc_board_response": self.state.get("pc_board_response", ""),
            "request": messages[-1].content,
            "messages": messages,
        }
        result = self.graph.invoke(
            self.state,
            config={"configurable": {"thread_id": id}},
        )
        print(result)
        final_answer = result.get("final_answer")

        if isinstance(final_answer, str):
            try:
                final_answer = ast.literal_eval(final_answer)  # "{'type': 'text', 'text': '...'}" → dict
            except (ValueError, SyntaxError):
                pass

        response = (
            final_answer.get("text") if isinstance(final_answer, dict)
            else final_answer
        ) or result.get("pc_board_response") or "ERROR"

        self.state["pc_board_response"] += '\n' + result.get("pc_board_response", "")

        return response
    
    def update_state(self, state: dict):
        self.state.update(state)

    def get_state(self):
        return self.state


def test():
    agent = PC_Builder_Agent(DEFAULT_MODEL_NAME, debug=True)
    messages=[]
    while True:
        query = input("你: ")
        if query.lower() in ['quit', 'exit']:
            break
        messages.append({'role': 'user', 'content': query})
        res = agent.generate(
            id='123',
            messages=messages,
            preference={"budget": "40000"},
            debug=True
        )
        messages.append({'role': 'assistant', 'content': res})

        print("Agent 回覆:")
        print(res)
        print("="*30)
        print("State:")
        print(agent.get_state())


if __name__ == '__main__':
    test()