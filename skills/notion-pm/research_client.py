#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

TAVILY_API_URL = "https://api.tavily.com/search"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _bootstrap_env() -> None:
    here = os.path.abspath(os.path.dirname(__file__))
    root = os.path.abspath(os.path.join(here, "..", ".."))
    _load_env_file(os.path.join(root, ".env"))


def _get_tavily_key() -> str:
    _bootstrap_env()
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("Missing TAVILY_API_KEY")
    return api_key


def _openai_summarize_if_available(query: str, raw_answer: str, links: List[Dict[str, str]]) -> Dict[str, Any]:
    """Optional LLM summarization to produce one coherent paragraph.

    Runs only if OPENAI_API_KEY is set; otherwise returns raw answer fallback.
    """
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return {"used": False, "summary": (raw_answer or "").strip()}

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    bullets = []
    for i, l in enumerate(links[:5], start=1):
        bullets.append(f"{i}. {l.get('title','')} — {l.get('url','')} — {l.get('snippet','')}")
    sources_block = "\n".join(bullets)

    prompt = (
        "You are summarizing web research for a PM task. "
        "Write exactly one coherent paragraph (max 110 words), neutral tone, no bullets. "
        "Use only provided evidence; do not invent facts. "
        "If evidence conflicts, mention that briefly.\n\n"
        f"Task query: {query}\n"
        f"Tavily answer: {raw_answer}\n"
        f"Top sources:\n{sources_block}"
    )

    payload = {
        "model": model,
        "input": prompt,
        "temperature": 0.2,
        "max_output_tokens": 180,
    }

    req = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            r = json.loads(resp.read().decode("utf-8"))

        summary: Optional[str] = r.get("output_text")
        if not summary:
            # Fallback parse for older/newer response shapes
            out = r.get("output") or []
            parts = []
            for item in out:
                for c in item.get("content", []):
                    txt = c.get("text")
                    if txt:
                        parts.append(txt)
            summary = " ".join(parts).strip()

        summary = (summary or raw_answer or "").strip()
        return {"used": True, "summary": summary[:900], "model": model}
    except Exception as e:
        return {"used": False, "summary": (raw_answer or "").strip(), "error": str(e)}


def research_task(query: str, max_results: int = 3) -> Dict[str, Any]:
    tavily_key = _get_tavily_key()
    body = {
        "api_key": tavily_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        TAVILY_API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
        raise RuntimeError(f"Tavily HTTP error: {e.code} {msg}") from e
    except Exception as e:
        raise RuntimeError(f"Tavily request failed: {e}") from e

    raw_answer = (payload.get("answer") or "").strip()
    results = payload.get("results") or []

    links: List[Dict[str, str]] = []
    for r in results[:max_results]:
        links.append(
            {
                "title": (r.get("title") or "").strip(),
                "url": (r.get("url") or "").strip(),
                "snippet": (r.get("content") or "").strip()[:240],
            }
        )

    if not raw_answer:
        raw_answer = "; ".join([x["title"] for x in links if x.get("title")][:3])

    llm = _openai_summarize_if_available(query, raw_answer, links)
    summary = (llm.get("summary") or raw_answer or "").strip()

    return {
        "ok": True,
        "query": query,
        "summary": summary[:900],
        "links": links,
        "llm_used": bool(llm.get("used")),
        "llm_model": llm.get("model"),
        "llm_error": llm.get("error"),
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Tavily research client")
    p.add_argument("query")
    p.add_argument("--max-results", type=int, default=3)
    args = p.parse_args()
    print(json.dumps(research_task(args.query, args.max_results), ensure_ascii=False))
