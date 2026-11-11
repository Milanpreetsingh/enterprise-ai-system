from typing import Annotated, Sequence, TypedDict, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    """
    State representing the context of our multi-agent enterprise AI system.
    The 'messages' key accumulates conversation history using the add_messages reducer.
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: str
    thread_id: str
    active_agent: Optional[str]
    user_memories: Optional[str]
