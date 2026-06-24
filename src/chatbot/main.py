from typing import Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver # NEW: In-memory checkpointer
from langchain_core.messages import HumanMessage, AIMessage

from chatbot.config import get_llm, get_embeddings, STORAGE_DIR
from chatbot.state import AgentState
from chatbot.router.query_router import SemanticRouter
from chatbot.vector_db.db_manager import IncrementalVectorManager
from chatbot.generation.llm_generator import LLMGenerator


# 1. Initialize Core Components
llm = get_llm()
router = SemanticRouter(llm=llm)
generator = LLMGenerator(llm=llm)
embeddings = get_embeddings()

# Initialize the two newly named compliance databases
db_internal = IncrementalVectorManager(
    collection_name="internal_policies",
    embedding_model=embeddings,
    persist_directory=str(STORAGE_DIR / "internal_policies")
)
db_external = IncrementalVectorManager(
    collection_name="external_regulations",
    embedding_model=embeddings,
    persist_directory=str(STORAGE_DIR / "external_regulations")
)

# 2. Define Node Functions
def route_question(state: AgentState) -> Dict[str, Any]:
    # Extract the latest question from the conversation history
    question = state["messages"][-1].content
    print(f"---ROUTING QUESTION: {question}---")
    
    destinations = router.route(question)
    return {"destination": destinations, "question": question}

def retrieve_docs(state: AgentState) -> Dict[str, Any]:
    question = state["question"]
    destinations = state["destination"]
    
    print(f"---RETRIEVING FROM {destinations}---")
    all_docs = []
    
    # Dynamically pull from whichever databases the router selected
    if "internal_policies" in destinations:
        retriever = db_internal.as_retriever()
        all_docs.extend(retriever.invoke(question))
        
    if "external_regulations" in destinations:
        retriever = db_external.as_retriever()
        all_docs.extend(retriever.invoke(question))
        
    return {"documents": all_docs}

def generate_answer(state: AgentState) -> Dict[str, Any]:
    print(f"---GENERATING ANSWER---")
    # Pass the full conversation history to the generator
    generation = generator.generate(state["messages"], state["documents"])
    
    # NEW: Return the generation AND append it to the messages array!
    return {
        "generation": generation,
        "messages": [AIMessage(content=generation)]
    }

# 3. Build the LangGraph Workflow Workflow
workflow = StateGraph(AgentState)

workflow.add_node("router", route_question)
workflow.add_node("retriever", retrieve_docs)
workflow.add_node("generator", generate_answer)

workflow.set_entry_point("router")
workflow.add_edge("router", "retriever")
workflow.add_edge("retriever", "generator")
workflow.add_edge("generator", END)

# 4. Compile the Graph with Memory!
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)