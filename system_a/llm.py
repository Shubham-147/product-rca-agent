from __future__ import annotations

import os
import time

from openai import OpenAI

from .schema import SystemAOutput


def generate_once(instance_id: str, question: str, context: str) -> tuple[SystemAOutput, dict]:
    key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL")
    if not key or not model:
        raise RuntimeError("OPENAI_API_KEY and OPENAI_MODEL are required; no mock fallback is used")
    client = OpenAI(api_key=key, base_url=os.environ.get("OPENAI_BASE_URL"))
    system = """You are System A, a Vanilla RAG product analyst. Use only the supplied retrieved chunks.
Return a ranked structured diagnosis. Do not invent measurements. A regression plus an associated signal supports correlation, not proven causality: phrase claims accordingly. Use only allowed cohort columns. Prefer a single best hypothesis. Cite chunk IDs inside evidence claims. Every cited chunk ID must appear in context. If evidence does not show an actionable SLO breach or fault signal, return innocent_dropoff."""
    prompt = f"INSTANCE: {instance_id}\nQUESTION:\n{question}\n\nONE-SHOT RETRIEVED CONTEXT:\n{context}"
    started = time.perf_counter()
    response = client.beta.chat.completions.parse(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        response_format=SystemAOutput,
        temperature=0,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise ValueError("LLM returned no parseable structured output")
    elapsed = time.perf_counter() - started
    usage = response.usage
    return parsed, {"model": model, "prompt_tokens": usage.prompt_tokens if usage else None,
                    "completion_tokens": usage.completion_tokens if usage else None,
                    "elapsed_seconds": round(elapsed, 3)}
