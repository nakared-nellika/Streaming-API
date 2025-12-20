from services.utils.state import MessageState
from langgraph.types import Command
from langchain.messages import SystemMessage, HumanMessage
from langgraph.config import get_stream_writer
import json, asyncio, aiofiles, os
from services.utils.status import append_status, get_status
from langgraph.types import interrupt
from services.utils.prompt_manager import all_prompts

# Get the directory where this script is located
current_dir = os.path.dirname(os.path.abspath(__file__))
# Navigate to the mock_data directory relative to this script's location
mock_data_dir = os.path.join(current_dir, "..", "mock_data")

async def map_intent(state: MessageState, model_intent):
    intent = await model_intent.ainvoke({"messages": state["messages"]})
    if intent.content not in ["general", "need_call", "lock_card", "unusual_transaction", "check_status"]:
        mapping_intent = "general"
    else:
        mapping_intent = intent.content
    if mapping_intent == "general":
        return Command(goto="general_agent")
    elif mapping_intent == "need_call":
        return Command(goto="need_call")
    elif mapping_intent == "lock_card":
        return Command(goto="lock_card")
    elif mapping_intent == "unusual_transaction":
        return Command(goto="fetch_transactions")
    elif mapping_intent == "check_status":
        return Command(goto="summarize_case_agent")
    


async def fetch_transactions(state: MessageState):
    writer = get_stream_writer()
    # writer("Analyzing your account...")
    # writer("Security check in progress...")
    transactions_file = os.path.join(mock_data_dir, "transactions.json")
    async with aiofiles.open(transactions_file, 'r', encoding='utf-8') as f:
        content = await f.read()
    transactions = json.loads(content)
    return {"transactions" : transactions}

async def analyze_transactions_agent(state: MessageState, model_analyze):
    message = await model_analyze.ainvoke({"transactions": state["transactions"]})
    
    await append_status(state["user_info"]['user_id'], {"unusaual_transaction": {"Reported": "Done", "Investigation": "In Progress", "Resolved": "No"}})
    return {"messages" : message}


async def lock_card(state: MessageState):
    writer = get_stream_writer()
    status = await get_status(state["user_info"]['user_id'])
    if status.get('card_locked', False):
        writer("Your card is already locked")
        return Command(goto="__end__")
    # print(f"Current status before locking card: { state}")
    decision = interrupt({
        "question": "Are you sure you want to lock your card?"
    })

    # print(status.get('card_locked', False))
    # if status.get('card_locked', False):
    #     writer("ได้เลยครับ มีอะไรให้ช่วยอีกไหมครับ?")
    #     return Command(goto="__end__")
    
    if decision == "Yes":
        # writer("Card temporarily locked")
        
        await append_status(state["user_info"]['user_id'], {"card_locked": "LOCKED"})
        return Command(goto="summarize_case_agent")
    else:
        writer("ได้เลยครับ มีอะไรให้ช่วยอีกไหมครับ?")
        return Command(goto="__end__")
    

async def summarize_case_agent(state: MessageState, model_summarize):
    writer = get_stream_writer()
    status = await get_status(state["user_info"]['user_id'])
    writer({"case_progress":status})
    message = await model_summarize.ainvoke({"status": status})
    return {"messages" : message}

async def general_agent(state: MessageState, model_general):
    message = await model_general.ainvoke({"messages": state["messages"]})
    return {"messages" : message}

async def need_call(state: MessageState):
    writer_call = get_stream_writer()
    writer_call("Connecting to Agent...")
    return {}