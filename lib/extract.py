from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Any

import httpx

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)")
DATE_RE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b", re.I)
AMOUNT_RE = re.compile(r"(?<!\w)(?:USD|INR|EUR|GBP|\$|₹|€|£)\s?\d[\d,]*(?:\.\d{1,2})?(?!\w)")


class ExtractionError(Exception):
    pass


def heuristic_extract(filename: str, full_text: str) -> dict[str, Any]:
    title = next((line.strip() for line in full_text.splitlines() if line.strip()), filename.rsplit("/", 1)[-1])
    low = f"{filename} {full_text[:4000]}".lower()
    if any(word in low for word in ["invoice", "amount due", "bill to"]):
        doc_type = "invoice"
    elif any(word in low for word in ["resume", "curriculum vitae", "experience", "education"]):
        doc_type = "resume"
    elif any(word in low for word in ["agreement", "contract", "party", "termination"]):
        doc_type = "contract"
    elif any(word in low for word in ["quarterly", "revenue", "q1", "q2", "q3", "q4"]):
        doc_type = "report"
    else:
        doc_type = "document"

    emails = sorted(set(EMAIL_RE.findall(full_text)))
    phones = sorted(set(x.strip() for x in PHONE_RE.findall(full_text)))[:10]
    dates = sorted(set(DATE_RE.findall(full_text)))[:20]
    amounts = sorted(set(AMOUNT_RE.findall(full_text)))[:20]

    entities: list[dict[str, Any]] = []
    for value in emails:
        entities.append({"key": "email", "value": value, "type": "email", "confidence": 0.99})
    for value in phones:
        entities.append({"key": "phone", "value": value, "type": "phone", "confidence": 0.92})
    for value in dates:
        entities.append({"key": "date", "value": value, "type": "date", "confidence": 0.90})
    for value in amounts:
        entities.append({"key": "amount", "value": value, "type": "currency", "confidence": 0.88})

    summary = re.sub(r"\s+", " ", full_text).strip()[:650]
    return {
        "title": title[:180],
        "document_type": doc_type,
        "summary": summary,
        "confidence": 0.70 if entities else 0.60,
        "entities": entities,
        "mode": "heuristic",
    }


def _response_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    pieces: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text") if isinstance(content, dict) else None
            if isinstance(text, str):
                pieces.append(text)
    return "\n".join(pieces).strip()


def _safe_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _normalized_extraction(value: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Constrain model output before it reaches the persistence and template layers."""
    document_types = {"invoice", "resume", "contract", "report", "table", "document"}
    entity_types = {"text", "email", "phone", "date", "currency", "number"}

    def bounded_text(candidate: Any, default: str, limit: int) -> str:
        if not isinstance(candidate, str):
            return default
        candidate = candidate.strip()
        return candidate[:limit] if candidate else default

    try:
        confidence = float(value.get("confidence", fallback["confidence"]))
    except (TypeError, ValueError):
        confidence = float(fallback["confidence"])

    entities: list[dict[str, Any]] = []
    raw_entities = value.get("entities", [])
    if isinstance(raw_entities, list):
        for entity in raw_entities[:50]:
            if not isinstance(entity, dict):
                continue
            entity_value = bounded_text(entity.get("value"), "", 500)
            if not entity_value:
                continue
            try:
                entity_confidence = float(entity.get("confidence", 0.5))
            except (TypeError, ValueError):
                entity_confidence = 0.5
            entity_type = entity.get("type")
            entities.append(
                {
                    "key": bounded_text(entity.get("key"), "field", 80),
                    "value": entity_value,
                    "type": entity_type if entity_type in entity_types else "text",
                    "confidence": max(0.0, min(entity_confidence, 1.0)),
                }
            )

    document_type = value.get("document_type")
    return {
        "title": bounded_text(value.get("title"), fallback["title"], 180),
        "document_type": document_type if document_type in document_types else fallback["document_type"],
        "summary": bounded_text(value.get("summary"), fallback["summary"], 2_000),
        "confidence": max(0.0, min(confidence, 1.0)),
        "entities": entities,
    }


def llm_extract(filename: str, full_text: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return heuristic_extract(filename, full_text)

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = f"""
You are a document extraction service. Turn the supplied messy document into a conservative structured record.
Never invent facts. Only extract values directly supported by the text.
Return JSON only with this shape:
{{
  "title": string,
  "document_type": "invoice" | "resume" | "contract" | "report" | "table" | "document",
  "summary": string,
  "confidence": number,
  "entities": [{{"key": string, "value": string, "type": "text"|"email"|"phone"|"date"|"currency"|"number", "confidence": number}}]
}}
Keep entities concise and useful for filtering or answering questions. Prefer named fields such as company, person, invoice_number, total, due_date, role, location, effective_date, expiry_date, amount.

FILENAME: {filename}
DOCUMENT:
{full_text[:24000]}
""".strip()

    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": prompt, "store": False},
            timeout=75.0,
        )
        response.raise_for_status()
        payload = response.json()
        text = _response_text(payload)
        result = _normalized_extraction(_safe_json(text), heuristic_extract(filename, full_text))
        result["mode"] = "llm"
        return result
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        fallback = heuristic_extract(filename, full_text)
        fallback["warnings"] = [f"LLM extraction unavailable; used deterministic extraction instead ({type(exc).__name__})."]
        return fallback


def grounded_answer(question: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    if not sources:
        return {
            "answer": "I couldn't find indexed evidence that answers this question. Try a more specific keyword, or add a document that contains the relevant information.",
            "confidence": 0.0,
            "mode": "no-evidence",
        }

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "answer": "LLM Q&A is disabled because OPENAI_API_KEY is not configured. Use the search results below to inspect the matching evidence.",
            "confidence": 0.0,
            "mode": "search-only",
        }

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    source_text = "\n\n".join(
        f"[{i + 1}] {src['document_name']} — {('page ' + str(src['page'])) if src.get('page') else 'section ' + (src.get('section') or 'document')}\n{src['content']}"
        for i, src in enumerate(sources)
    )
    prompt = f"""
Answer the user's question using ONLY the evidence below.
Rules:
- If the evidence does not support an answer, say so clearly.
- Do not guess or use outside knowledge.
- Cite every material claim with one or more source numbers like [1] or [2].
- Keep the answer concise and operational.
- State ambiguity when sources conflict.

QUESTION:
{question}

EVIDENCE:
{source_text}
""".strip()
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": prompt, "store": False},
            timeout=75.0,
        )
        response.raise_for_status()
        payload = response.json()
        return {"answer": _response_text(payload), "confidence": 0.85, "mode": "llm"}
    except Exception as exc:
        return {
            "answer": f"I couldn't generate a grounded answer right now ({type(exc).__name__}). The retrieved evidence is shown below so you can inspect it directly.",
            "confidence": 0.0,
            "mode": "search-fallback",
        }
