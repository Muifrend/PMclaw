#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent
NOTION_CLIENT_PATH = HERE / "notion-client.py"
spec = importlib.util.spec_from_file_location("notion_pm_client", NOTION_CLIENT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load {NOTION_CLIENT_PATH}")
notion_pm_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notion_pm_client)

RESEARCH_CLIENT_PATH = HERE / "research_client.py"
rspec = importlib.util.spec_from_file_location("research_client", RESEARCH_CLIENT_PATH)
if rspec is None or rspec.loader is None:
    raise RuntimeError(f"Could not load {RESEARCH_CLIENT_PATH}")
research_client = importlib.util.module_from_spec(rspec)
rspec.loader.exec_module(research_client)

STATE_DIR = HERE / ".state"
PENDING_FILE = STATE_DIR / "pending.json"

ACTION_CREATE = "create_task"
ACTION_IGNORE = "ignore"
ACTION_CLARIFY = "ask_clarification"
RESEARCH_CONFIDENCE_THRESHOLD = float(os.getenv("RESEARCH_CONFIDENCE_THRESHOLD", "0.8"))


@dataclass
class Decision:
    action: str
    task_name: Optional[str]
    priority: str
    due_date: Optional[str]
    confidence: float
    reason: str
    task_type: str
    research_query: Optional[str]


def _today() -> datetime:
    return datetime.now(UTC)


def _load_pending() -> Dict[str, Any]:
    if not PENDING_FILE.exists():
        return {}
    try:
        return json.loads(PENDING_FILE.read_text())
    except Exception:
        return {}


def _save_pending(state: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def _set_pending(chat: str, item: Dict[str, Any]) -> None:
    state = _load_pending()
    state[chat] = item
    _save_pending(state)


def _pop_pending(chat: str) -> Optional[Dict[str, Any]]:
    state = _load_pending()
    item = state.pop(chat, None)
    _save_pending(state)
    return item


def _peek_pending(chat: str) -> Optional[Dict[str, Any]]:
    state = _load_pending()
    return state.get(chat)


def _extract_due_date(text: str, now: Optional[datetime] = None) -> Optional[str]:
    now = now or _today()
    t = (text or "").strip().lower()

    # 1) ISO date
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", t)
    if m:
        return m.group(1)

    # 2) Relative day keywords
    if "tomorrow" in t:
        return (now + timedelta(days=1)).date().isoformat()
    if re.search(r"\btoday\b", t):
        return now.date().isoformat()

    # 3) in N days
    m_days = re.search(r"\bin\s+(\d{1,2})\s+days?\b", t)
    if m_days:
        n = int(m_days.group(1))
        return (now + timedelta(days=n)).date().isoformat()

    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    # 4) this/next weekday
    m_wd = re.search(r"\b(this|next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m_wd:
        which, day = m_wd.group(1), m_wd.group(2)
        target = weekdays[day]
        cur = now.weekday()
        delta = (target - cur) % 7
        if which == "next":
            delta = delta if delta != 0 else 7
        else:  # this
            delta = delta if delta != 0 else 0
        return (now + timedelta(days=delta)).date().isoformat()

    # 5) Bare weekday => next occurrence (or today if same)
    m_bare_wd = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m_bare_wd:
        target = weekdays[m_bare_wd.group(1)]
        cur = now.weekday()
        delta = (target - cur) % 7
        return (now + timedelta(days=delta)).date().isoformat()

    # 6) Month name formats: march 15, mar 15, march 15 2026
    month_map = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
        "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }
    m_month = re.search(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:,?\s*(20\d{2}))?\b", t)
    if m_month:
        mon_s, day_s, year_s = m_month.group(1), m_month.group(2), m_month.group(3)
        mon = month_map[mon_s]
        day = int(day_s)
        year = int(year_s) if year_s else now.year
        try:
            candidate = datetime(year, mon, day, tzinfo=UTC).date()
        except ValueError:
            return None
        # If year wasn't specified and date already passed, roll to next year
        if not year_s and candidate < now.date():
            try:
                candidate = datetime(year + 1, mon, day, tzinfo=UTC).date()
            except ValueError:
                return None
        return candidate.isoformat()

    return None


def _extract_priority(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["urgent", "asap", "blocker", "high priority", "high"]):
        return "High"
    if any(k in t for k in ["low priority", "low", "later", "someday"]):
        return "Low"
    return "Medium"




def _clean_task_title(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^(task\s*:\s*|todo\s*:\s*)", "", t, flags=re.I)

    # remove stacked filler prefixes iteratively
    prefix = re.compile(r"^(please\s+|can you\s+|could you\s+|need to\s+|i need to\s+|remind me to\s+)", re.I)
    while True:
        t2 = prefix.sub("", t).strip()
        if t2 == t:
            break
        t = t2

    # remove date phrases
    patterns = [
        r"\bby\s+20\d{2}-\d{2}-\d{2}\b",
        r"\b20\d{2}-\d{2}-\d{2}\b",
        r"\b(today|tomorrow)\b",
        r"\bin\s+\d{1,2}\s+days?\b",
        r"\b(this|next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:,?\s*20\d{2})?\b",
    ]
    for pat in patterns:
        t = re.sub(pat, "", t, flags=re.I)

    # remove priority tokens
    t = re.sub(r"\b(high priority|low priority|high|medium|low|urgent|asap)\b", "", t, flags=re.I)

    # remove connectors/punctuation leftovers
    t = re.sub(r"\b(by|due|on)\b", "", t, flags=re.I)
    t = re.sub(r"[,:;.!]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -")

    if not t:
        return "(untitled task)"

    t = t[0].upper() + t[1:]
    return t[:70]

def _sanitize_task_name(text: str) -> str:
    return _clean_task_title(text)


def _classify_task_type(text: str) -> tuple[str, Optional[str]]:
    t = (text or "").lower()
    signals = ["research", "compare", "best", "options", "benchmark", "evaluate", "pros and cons", "pros/cons"]
    if any(sig in t for sig in signals):
        q = _clean_task_title(text)
        return "researchable", q
    return "execution", None


def _is_date_only_reply(text: str) -> bool:
    t = text.strip().lower()
    return bool(
        re.fullmatch(r"20\d{2}-\d{2}-\d{2}", t)
        or t in {"tomorrow", "today"}
        or re.fullmatch(r"in\s+\d{1,2}\s+days?", t)
        or re.fullmatch(r"(this|next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", t)
        or re.fullmatch(r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", t)
        or re.fullmatch(r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:,?\s*20\d{2})?", t)
    )


def decide_message(text: str) -> Decision:
    t = (text or "").strip()
    lower = t.lower()

    if not t:
        return Decision(ACTION_IGNORE, None, "Medium", None, 1.0, "empty_message", "execution", None)

    ignore_tokens = ["lol", "lmao", "😂", "👍", "ok", "thanks", "nice", "haha"]
    if lower in ignore_tokens or len(t) <= 3:
        return Decision(ACTION_IGNORE, None, "Medium", None, 0.95, "short_or_reaction", "execution", None)

    explicit_task = lower.startswith("task:") or lower.startswith("todo:")
    task_signals = ["need to", "please", "remind", "deadline", "due", "by "]
    has_signal = any(s in lower for s in task_signals)

    due_date = _extract_due_date(t)
    priority = _extract_priority(t)

    if explicit_task or has_signal:
        task_type, research_query = _classify_task_type(t)
        if due_date:
            return Decision(
                ACTION_CREATE,
                _sanitize_task_name(t),
                priority,
                due_date,
                0.9 if explicit_task else 0.82,
                "task_with_due_date",
                task_type,
                research_query,
            )
        return Decision(
            ACTION_CLARIFY,
            _sanitize_task_name(t),
            priority,
            None,
            0.88 if explicit_task else 0.62,
            "missing_due_date",
            task_type,
            research_query,
        )

    return Decision(ACTION_IGNORE, None, "Medium", None, 0.9, "no_task_signals", "execution", None)


def process_message(*, message: str, chat: str, message_id: str, source: str, received_at: Optional[str], dry_run: bool) -> Dict[str, Any]:
    msg = (message or "").strip()

    # If user is replying with a date and we have pending task context, complete it.
    pending = _peek_pending(chat)
    if pending and _is_date_only_reply(msg):
        due = _extract_due_date(msg)
        if not due:
            return {
                "decision": {"action": ACTION_CLARIFY, "reason": "invalid_due_date_reply"},
                "status": "needs_due_date",
                "clarification_prompt": "Please provide due date as YYYY-MM-DD (or say 'tomorrow').",
            }

        dedup_key = notion_pm_client.make_dedup_key(source, chat, message_id)
        full_message = pending.get("message", msg)
        priority = pending.get("priority", "Medium")

        result: Dict[str, Any] = {
            "decision": {
                "action": ACTION_CREATE,
                "task_name": pending.get("task_name"),
                "priority": priority,
                "due_date": due,
                "confidence": 0.95,
                "reason": "completed_from_pending_due_date",
                "task_type": pending.get("task_type", "execution"),
                "research_query": pending.get("research_query"),
            },
            "dedup_key": dedup_key,
            "created": False,
        }

        if dry_run:
            result["status"] = "dry_run_create"
            return result

        research_summary = None
        research_links = None
        if (pending.get("task_type") == "researchable" and pending.get("research_query")
            and result["decision"].get("confidence", 0) >= RESEARCH_CONFIDENCE_THRESHOLD):
            try:
                r = research_client.research_task(pending.get("research_query"))
                research_summary = r.get("summary")
                research_links = "\n".join([x.get("url", "") for x in r.get("links", []) if x.get("url")])
                result["research"] = r
            except Exception as e:
                result["research_error"] = str(e)

        created = notion_pm_client.create_task_from_message(
            message=full_message,
            dedup_key=dedup_key,
            due_date=due,
            task_name=pending.get("task_name"),
            research_summary=research_summary,
            research_links=research_links,
            received_at=received_at,
            status="New",
            priority=priority,
        )
        if created.get("created"):
            _pop_pending(chat)
        result["status"] = "created" if created.get("created") else created.get("reason", "skipped")
        result["created"] = bool(created.get("created"))
        result["notion"] = created
        return result

    decision = decide_message(msg)
    dedup_key = notion_pm_client.make_dedup_key(source, chat, message_id)

    result: Dict[str, Any] = {"decision": decision.__dict__, "dedup_key": dedup_key, "created": False}

    if decision.action == ACTION_IGNORE:
        result["status"] = "ignored"
        return result

    if decision.action == ACTION_CLARIFY:
        _set_pending(
            chat,
            {
                "task_name": decision.task_name,
                "message": message,
                "priority": decision.priority,
                "task_type": decision.task_type,
                "research_query": decision.research_query,
                "created_at": _today().isoformat(),
            },
        )
        result["status"] = "needs_due_date"
        result["clarification_prompt"] = "Got it — what’s the due date? (YYYY-MM-DD or 'tomorrow')"
        return result

    if dry_run:
        result["status"] = "dry_run_create"
        return result

    research_summary = None
    research_links = None
    if decision.task_type == "researchable" and decision.research_query and decision.confidence >= RESEARCH_CONFIDENCE_THRESHOLD:
        try:
            r = research_client.research_task(decision.research_query)
            research_summary = r.get("summary")
            research_links = "\n".join([x.get("url", "") for x in r.get("links", []) if x.get("url")])
            result["research"] = r
        except Exception as e:
            result["research_error"] = str(e)

    created = notion_pm_client.create_task_from_message(
        message=message,
        dedup_key=dedup_key,
        due_date=decision.due_date,
        task_name=decision.task_name,
        research_summary=research_summary,
        research_links=research_links,
        received_at=received_at,
        status="New",
        priority=decision.priority,
    )
    result["status"] = "created" if created.get("created") else created.get("reason", "skipped")
    result["created"] = bool(created.get("created"))
    result["notion"] = created
    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PM autonomous message handler")
    sp = p.add_subparsers(dest="cmd", required=True)

    d = sp.add_parser("decide", help="Return autonomous decision for a message")
    d.add_argument("--message", required=True)

    pm = sp.add_parser("process-message", help="Decide + optionally write to Notion")
    pm.add_argument("--message", required=True)
    pm.add_argument("--chat", required=True)
    pm.add_argument("--message-id", required=True)
    pm.add_argument("--source", default=os.getenv("NOTION_SOURCE", "telegram"))
    pm.add_argument("--received-at", default=datetime.now(UTC).date().isoformat())
    pm.add_argument("--dry-run", action="store_true")

    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.cmd == "decide":
        print(json.dumps(decide_message(args.message).__dict__, ensure_ascii=False))
        return

    if args.cmd == "process-message":
        out = process_message(
            message=args.message,
            chat=args.chat,
            message_id=args.message_id,
            source=args.source,
            received_at=args.received_at,
            dry_run=args.dry_run,
        )
        print(json.dumps(out, ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
