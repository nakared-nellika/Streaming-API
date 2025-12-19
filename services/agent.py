import json, os
from langchain.messages import HumanMessage, AIMessage, SystemMessage, AnyMessage
from typing_extensions import Annotated
from langgraph.graph.message import add_messages
from langgraph.config import get_stream_writer
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from services.utils.state import MessageState
from services.utils.nodes import (
    map_intent, fetch_transactions, analyze_transactions_agent,
    summarize_case_agent, general_agent, need_call, lock_card
)
from services.utils.status import append_status, get_status
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.prompts import HumanMessagePromptTemplate
from services.utils.prompt_manager import all_prompts
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from dotenv import load_dotenv

# ใช้ AzureChatOpenAI
from langchain_openai import AzureChatOpenAI

load_dotenv()


class VBChatbot:
    def __init__(self):
        self.general_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=all_prompts['general_system']),
            MessagesPlaceholder(variable_name="messages")
        ])
        self.intent_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=all_prompts['intent_system']),
            MessagesPlaceholder(variable_name="messages")
        ])
        self.transaction_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=all_prompts['transaction_analyze_system']),
            HumanMessagePromptTemplate.from_template(all_prompts['transaction_analyze_user']),
        ])
        self.case_summary_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=all_prompts['case_summary_system']),
            HumanMessagePromptTemplate.from_template(all_prompts['case_summary_user']),
        ])

        # Azure OpenAI LLM factory
        def _az_llm(temperature: float, max_tokens: int):
            return AzureChatOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],  # ชื่อ deployment ของคุณ
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                temperature=temperature,
                max_tokens=max_tokens,
            )

        # สร้างโมเดล (Azure)
        self.general_model = self.general_prompt | _az_llm(temperature=0.2, max_tokens=2000)
        self.intent_model = self.intent_prompt | _az_llm(temperature=0, max_tokens=100)
        self.transaction_model = self.transaction_prompt | _az_llm(temperature=0.2, max_tokens=2000)
        self.case_summary_model = self.case_summary_prompt | _az_llm(temperature=0.2, max_tokens=2000)

        self.graphs = {}
        self.memory_saver = MemorySaver()

    async def map_intent_node(self, state: MessageState):
        return await map_intent(state, self.intent_model)

    async def analyze_transactions_node(self, state: MessageState):
        return await analyze_transactions_agent(state, self.transaction_model)

    async def summarize_case_node(self, state: MessageState):
        return await summarize_case_agent(state, self.case_summary_model)

    async def general_agent_node(self, state: MessageState):
        return await general_agent(state, self.general_model)

    async def build_graph(self, thread_id: str):
        if thread_id in self.graphs:
            return self.graphs[thread_id]

        builder = StateGraph(MessageState)
        builder.add_node("map_intent", self.map_intent_node)
        builder.add_node("fetch_transactions", fetch_transactions)
        builder.add_node("analyze_transactions_agent", self.analyze_transactions_node)
        builder.add_node("lock_card", lock_card)
        builder.add_node("general_agent", self.general_agent_node)
        builder.add_node("need_call", need_call)
        builder.add_node("summarize_case_agent", self.summarize_case_node)

        builder.add_edge(START, "map_intent")
        builder.add_edge("fetch_transactions", "analyze_transactions_agent")
        builder.add_edge("analyze_transactions_agent", "lock_card")
        builder.add_edge("summarize_case_agent", END)
        builder.add_edge("general_agent", END)
        builder.add_edge("need_call", END)

        graph = builder.compile(self.memory_saver)
        self.graphs[thread_id] = graph
        return graph

    async def delete_graph(self, thread_id: str):
        if thread_id in self.graphs:
            del self.graphs[thread_id]

    async def run(self, thread_id: str, message: str, resume: bool, user_info: dict):
        graph = await self.build_graph(thread_id)

        if resume:
            input = Command(resume=message)
        else:
            input = {"messages": [HumanMessage(content=message)], "user_info": user_info}

        config = {"configurable": {"thread_id": thread_id}}

        async for result in graph.astream(input, config=config, stream_mode=['updates', 'messages', 'custom']):
            if result[0] == 'updates':
                if "__interrupt__" in result[1]:
                    yield "Interrupt:", result[1]["__interrupt__"][0].value['question']
            if result[0] == 'custom':
                yield result[1]
            if result[0] == 'messages':
                if result[1][1]['langgraph_node'] != 'map_intent':
                    yield result[1][0].content
