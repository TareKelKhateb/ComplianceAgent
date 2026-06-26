import os
import sys

# Ensure project root and src are on sys.path before importing chatbot modules
_API_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_API_DIR))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage
from chatbot.api.server.schemas import ChatRequest, ChatResponse, SourceDetail

# Import the compiled LangGraph application
from chatbot.main import app as chatbot_graph

app = FastAPI(
    title="Regulatory Compliance Agent API",
    description="API for policy mapping, gap detection, and compliance queries.",
    version="2.0.0"
)

@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        # 1. Format input as a HumanMessage for the state graph
        inputs = {"messages": [HumanMessage(content=request.question)]}
        
        # 2. Configure the thread ID for memory persistence
        config = {"configurable": {"thread_id": request.thread_id}}
        
        # 3. Execute the graph
        final_state = chatbot_graph.invoke(inputs, config)
        
        # 4. Extract retrieved documents
        retrieved_docs = final_state.get("documents", [])
        sources = [
            SourceDetail(
                content=doc.page_content, 
                source_id=doc.metadata.get("source", "unknown")
            ) for doc in retrieved_docs
        ]
        
        # 5. The final answer is the content of the LAST message in the state
        final_answer = final_state["messages"][-1].content
        
        return ChatResponse(
            answer=final_answer,
            routed_destinations=final_state.get("destination", []),
            sources_used=sources
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline Error: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}