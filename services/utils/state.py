from typing import TypedDict
from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import Annotated

class MessageState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_info: dict
    intent: str
    transactions: list[dict]