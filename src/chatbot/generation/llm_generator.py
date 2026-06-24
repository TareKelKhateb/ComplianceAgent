from typing import List
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

class LLMGenerator:
    def __init__(self, llm: BaseChatModel):
        system_prompt = """You are an elite Regulatory Compliance & Policy Mapping Agent. 
        Your primary task is to analyze financial regulations, map corporate policies to state laws, and detect compliance gaps.
        
        You have been provided with context retrieved from internal company policies and/or external regulatory databases.
        
        Retrieved Context:
        {context}
        
        Instructions:
        1. Answer the user's question directly and professionally based ONLY on the provided context.
        2. If you are asked to map policies, explicitly point out any gaps between the internal policy and the external regulation.
        3. If the context does not contain the answer, state clearly that you do not have the regulatory data to answer. Do not hallucinate laws.
        """
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            # This placeholder injects the conversation memory seamlessly
            MessagesPlaceholder(variable_name="messages"), 
        ])
        
        self.chain = self.prompt | llm | StrOutputParser()

    def generate(self, messages: list, docs: List[Document]) -> str:
        # Format the documents into a single string for the context window
        context_str = "\n\n".join(
            f"[Source: {doc.metadata.get('source', 'Unknown')}]\n{doc.page_content}" 
            for doc in docs
        )
        
        return self.chain.invoke({
            "messages": messages,
            "context": context_str
        })