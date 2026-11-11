import json
import re
from typing import TypedDict
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.config import settings

class MetricResult(TypedDict):
    score: float
    reasoning: str

class RAGTriadEvaluation(TypedDict):
    context_relevance: MetricResult
    groundedness: MetricResult
    answer_relevance: MetricResult
    composite_score: float
    passed: bool

def _get_judge_llm():
    """
    Returns the LLM judge instance. Uses OpenAI if configured, otherwise local Ollama.
    """
    if settings.OPENAI_API_KEY:
        return ChatOpenAI(model="gpt-4o", openai_api_key=settings.OPENAI_API_KEY, temperature=0.0)
    from langchain_ollama import ChatOllama
    return ChatOllama(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.0
    )

def _parse_json_response(raw_text: str) -> dict:
    """
    Extracts and parses JSON object from model response.
    """
    json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except Exception:
            pass
    return {"score": 0.5, "reasoning": "Failed to parse structured JSON from judge output."}

def evaluate_context_relevance(query: str, contexts: list[str]) -> MetricResult:
    """
    Evaluates Context Relevance: Is the retrieved context pertinent and focused on the user query?
    """
    context_text = "\n\n---\n\n".join(contexts) if contexts else "NO CONTEXT RETRIEVED"
    llm = _get_judge_llm()

    prompt = (
        "You are an impartial evaluator assessing the Context Relevance of a RAG retrieval system.\n"
        "Evaluate how relevant the retrieved context is to the user query.\n"
        "Output ONLY a valid JSON object with keys 'score' (float between 0.0 and 1.0) and 'reasoning' (brief explanation).\n\n"
        f"User Query:\n{query}\n\n"
        f"Retrieved Context:\n{context_text}\n"
    )

    resp = llm.invoke([SystemMessage(content="You are a strict data evaluation judge."), HumanMessage(content=prompt)])
    res = _parse_json_response(resp.content)
    return {
        "score": round(float(res.get("score", 0.5)), 2),
        "reasoning": res.get("reasoning", "")
    }

def evaluate_groundedness(contexts: list[str], answer: str) -> MetricResult:
    """
    Evaluates Groundedness / Faithfulness: Are all factual claims in the answer supported by the context without hallucination?
    """
    context_text = "\n\n---\n\n".join(contexts) if contexts else "NO CONTEXT"
    llm = _get_judge_llm()

    prompt = (
        "You are an impartial evaluator assessing the Groundedness (Faithfulness) of an AI generated response.\n"
        "Check whether all factual statements in the Generated Answer can be verified directly from the Retrieved Context.\n"
        "If the answer invents facts not present in the context, heavily penalize the score.\n"
        "Output ONLY a valid JSON object with keys 'score' (float between 0.0 and 1.0) and 'reasoning' (brief explanation).\n\n"
        f"Retrieved Context:\n{context_text}\n\n"
        f"Generated Answer:\n{answer}\n"
    )

    resp = llm.invoke([SystemMessage(content="You are a strict data evaluation judge."), HumanMessage(content=prompt)])
    res = _parse_json_response(resp.content)
    return {
        "score": round(float(res.get("score", 0.5)), 2),
        "reasoning": res.get("reasoning", "")
    }

def evaluate_answer_relevance(query: str, answer: str) -> MetricResult:
    """
    Evaluates Answer Relevance: Does the generated answer directly address the user's inquiry?
    """
    llm = _get_judge_llm()

    prompt = (
        "You are an impartial evaluator assessing the Answer Relevance of an AI assistant.\n"
        "Evaluate whether the Generated Answer directly and helpfully answers the User Query.\n"
        "Output ONLY a valid JSON object with keys 'score' (float between 0.0 and 1.0) and 'reasoning' (brief explanation).\n\n"
        f"User Query:\n{query}\n\n"
        f"Generated Answer:\n{answer}\n"
    )

    resp = llm.invoke([SystemMessage(content="You are a strict data evaluation judge."), HumanMessage(content=prompt)])
    res = _parse_json_response(resp.content)
    return {
        "score": round(float(res.get("score", 0.5)), 2),
        "reasoning": res.get("reasoning", "")
    }

def evaluate_rag_triad(query: str, contexts: list[str], answer: str, pass_threshold: float = 0.70) -> RAGTriadEvaluation:
    """
    Runs the complete automated RAG Triad evaluation pipeline.
    """
    c_rel = evaluate_context_relevance(query, contexts)
    grounded = evaluate_groundedness(contexts, answer)
    a_rel = evaluate_answer_relevance(query, answer)

    composite = round((c_rel["score"] + grounded["score"] + a_rel["score"]) / 3.0, 2)
    passed = composite >= pass_threshold and grounded["score"] >= 0.70

    return {
        "context_relevance": c_rel,
        "groundedness": grounded,
        "answer_relevance": a_rel,
        "composite_score": composite,
        "passed": passed
    }
