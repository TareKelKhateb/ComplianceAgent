from typing import Annotated, List, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.documents import Document

class AgentState(TypedDict):
    # The 'add_messages' annotation is the core of LangGraph memory
    messages: Annotated[list, add_messages]
    
    # We keep these for internal processing state
    question: str
    destination: List[str]  # Changed to a list since we might query BOTH databases
    documents: List[Document]
    generation: str