#!/usr/bin/env python3
"""Wrapper script: normalize inbound payload -> call pm_handler -> emit standardized JSON.

Input options:
1) JSON via --json '{...}'
2) JSON via stdin
3) Direct CLI args (--message --chat --message-id ...)

Output JSON shape:
{
  "ok": true,
  "status": "created|duplicate|needs_due_date|ignored|error",
  "reply": "...optional user-facing text...",
  "dedup_key": "...",
  "decision": {...},
  "raw": {...pm_handler result...}
}
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent
PM_HANDLER = HERE / "pm_handler.py"


def _read_stdin_json() -> Optional[Dict[str, Any]]:
    if sys.stdin.isatty():
        return None
    data = sys.stdin.read().strip()
    if not data:
        return None
    return json.loads(data)


def _dig(d: Dict[str, Any], *keys: str, default=None):
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, str]:
    # Best-effort support for various envelope shapes.
    text = (
        _dig(payload, "message", "text")
        or payload.get("text")
        or payload.get("message")
        or ""
    )

    chat = (
        str(_dig(payload, "message", "chat", "id", default=""))
        or str(payload.get("chat_id", ""))
        or str(_dig(payload, "chat", "id", default=""))
    )

    message_id = (
        str(_dig(payload, "message", "message_id", default=""))
        or str(payload.get("message_id", ""))
        or str(payload.get("id", ""))
    )

    source = str(payload.get("source") or payload.get("channel") or "telegram")

    ts = (
        _dig(payload, "message", "date")
        or payload.get("date")
        or datetime.now(UTC).date().isoformat()
    )

    # If unix seconds, convert to YYYY-MM-DD
    if isinstance(ts, int) or (isinstance(ts, str) and ts.isdigit()):
        ts_int = int(ts)
        ts = datetime.fromtimestamp(ts_int, tz=UTC).date().isoformat()
    else:
        ts = str(ts)[:10]

    return {
        "message": str(text),
        "chat": str(chat),
        "message_id": str(message_id),
        "source": source,
        "received_at": ts,
    }


def _call_pm_handler(n: Dict[str, str], dry_run: bool) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(PM_HANDLER),
        "process-message",
        "--message",
        n["message"],
        f"--chat={n['chat']}",
        f"--message-id={n['message_id']}",
        "--source",
        n["source"],
        "--received-at",
        n["received_at"],
    ]
    if dry_run:
        cmd.append("--dry-run")

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {
            "ok": False,
            "status": "error",
            "reply": "⚠️ Failed to process message",
            "error": proc.stderr.strip() or proc.stdout.strip(),
        }

    out = json.loads(proc.stdout.strip())

    status = out.get("status", "error")
    decision = out.get("decision", {})
    task_name = decision.get("task_name") or "task"

    if status == "created":
        reply = f"✅ Logged to Notion: {task_name}"
    elif status == "duplicate":
        reply = "ℹ️ Already logged"
    elif status in ("needs_clarification", "needs_due_date"):
        reply = out.get("clarification_prompt", "❓ What due date should I use? (YYYY-MM-DD)")
    elif status in ("ignored", "dry_run_create"):
        reply = None
    else:
        reply = "⚠️ Notion processing issue"

    mapped_status = "duplicate" if status == "duplicate" else status
    return {
        "ok": True,
        "status": mapped_status,
        "reply": reply,
        "dedup_key": out.get("dedup_key"),
        "decision": decision,
        "raw": out,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest wrapper for PM Notion handler")
    p.add_argument("--json", help="Raw inbound payload JSON string")
    p.add_argument("--message")
    p.add_argument("--chat")
    p.add_argument("--message-id")
    p.add_argument("--source", default="telegram")
    p.add_argument("--received-at", default=datetime.now(UTC).date().isoformat())
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    payload: Optional[Dict[str, Any]] = None
    if args.json:
        payload = json.loads(args.json)
    else:
        payload = _read_stdin_json()

    if payload is not None:
        normalized = _normalize_payload(payload)
    else:
        if not (args.message and args.chat and args.message_id):
            raise SystemExit("Provide JSON input or --message --chat --message-id")
        normalized = {
            "message": args.message,
            "chat": args.chat,
            "message_id": args.message_id,
            "source": args.source,
            "received_at": args.received_at[:10],
        }

    result = _call_pm_handler(normalized, args.dry_run)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
