from pydantic import BaseModel, Field
from typing import List

class ChatRequest(BaseModel):
    question: str
    thread_id: str = Field(default="default_user_1", description="Unique ID for the conversation thread")

class SourceDetail(BaseModel):
    content: str
    source_id: str

class ChatResponse(BaseModel):
    answer: str
    routed_destinations: List[str] # Updated to be a list
    sources_used: List[SourceDetail]