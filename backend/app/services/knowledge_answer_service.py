"""Answer questions only from the SQLite knowledge base."""

from __future__ import annotations

import json
import re

from app.services import ai_model_service, knowledge_base_service


MIN_MATCHES = 1


def _strip_possible_citations(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"\n*依据[:：].*$", "", text, flags=re.S)
    return text.strip()


def answer_from_knowledge(question: str, *, limit: int = 5) -> dict:
    question = str(question or "").strip()
    if not question:
        return {"ok": False, "answer": "请先输入问题。", "matches": [], "used_ai": False}

    matches = knowledge_base_service.search_knowledge(question, limit=limit)
    if len(matches) < MIN_MATCHES:
        return {
            "ok": True,
            "answer": knowledge_base_service.NO_ANSWER_TEXT,
            "matches": [],
            "used_ai": False,
            "no_answer": True,
        }

    evidence = [
        {
            "id": item.get("item_id"),
            "title": item.get("title"),
            "content": item.get("content"),
            "category": item.get("category"),
            "source": item.get("source"),
        }
        for item in matches
    ]
    system_prompt = (
        "你是数据库知识库客服助手。你只能根据传入的知识库片段回答用户问题。"
        "禁止使用常识补全，禁止编造价格、规则、服务内容、承诺、联系方式或不存在的功能。"
        f"如果知识库片段无法直接支持答案，只能回复：{knowledge_base_service.NO_ANSWER_TEXT}"
        "回答使用中文，只输出给用户看的结论，不要列出引用编号和依据清单。"
    )
    context = {
        "question": question,
        "knowledge_evidence": evidence,
        "strict_rule": "Only answer from knowledge_evidence. If not supported, return the fixed no-answer text.",
    }
    answer, meta = ai_model_service.chat_text(
        "deep_analysis",
        system_prompt,
        f"用户问题：{question}\n\n知识库片段：\n{json.dumps(evidence, ensure_ascii=False)}",
        context,
        profile="chat_assistant",
    )
    answer = _strip_possible_citations(answer)
    if not meta.get("ok") or not answer or "模型调用" in answer:
        best = matches[0]
        answer = (best.get("content") or best.get("snippet") or knowledge_base_service.NO_ANSWER_TEXT).strip()
        answer = answer[:900]
        meta = {**meta, "used_ai": False, "fallback": "top_knowledge_chunk"}
    if not answer:
        answer = knowledge_base_service.NO_ANSWER_TEXT
    return {
        "ok": True,
        "answer": answer,
        "matches": matches,
        "matched_item_ids": sorted({m.get("item_id") for m in matches if m.get("item_id")}),
        "used_ai": bool(meta.get("used_ai")),
        "ai_meta": meta,
        "no_answer": answer.strip() == knowledge_base_service.NO_ANSWER_TEXT,
    }
