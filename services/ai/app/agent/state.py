import operator
from typing import Annotated, Sequence, TypedDict, Optional, List, Dict, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class SpecialistFinding(TypedDict):
    agent_name: str
    sub_query: str
    result: str

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
    # Reducer pattern: LangGraph merges findings from parallel nodes automatically without state collision
    findings: Annotated[List[Dict[str, Any]], operator.add]
    is_multi_intent: Optional[bool]
    plan_tasks: Optional[List[Dict[str, str]]]
