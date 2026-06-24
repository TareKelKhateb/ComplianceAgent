from typing import List, Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

class RouteDecision(BaseModel):
    databases: List[Literal["internal_policies", "external_regulations"]] = Field(
        description="The databases to route the query to. Can be one or both."
    )

class SemanticRouter:
    def __init__(self, llm: BaseChatModel):
        # Force the LLM to strictly output our Pydantic schema
        self.router_chain = llm.with_structured_output(RouteDecision)
        
        system_prompt = """You are an expert routing agent for a Regulatory Compliance System.
        Your job is to analyze the user's query and decide which vector databases contain the necessary context.
        
        Databases available:
        1. "internal_policies": Contains the company's internal rules, corporate policies, and guidelines.
        2. "external_regulations": Contains external state laws, financial regulations, and government compliance rules.
        
        Routing Logic:
        - If the user asks about company rules, return ["internal_policies"].
        - If the user asks about state laws or external regulations, return ["external_regulations"].
        - If the user asks to compare a company policy to a state law (compliance mapping/gap detection), return BOTH: ["internal_policies", "external_regulations"].
        """
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{question}")
        ])

    def route(self, question: str) -> List[str]:
        chain = self.prompt | self.router_chain
        decision = chain.invoke({"question": question})
        return decision.databases